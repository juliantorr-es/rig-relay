from __future__ import annotations

import json
from pathlib import Path

import duckdb
import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.dependency_surface_audit.v1.schema.json"
)
AUDIT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "dependency_surface_audit_v1.v1.json"
)
CSV_PATH = (
    REPO_ROOT / ".build" / "rig-relay" / "derived" / "dependency_surface_audit_v1.csv"
)

_REMOVE_CANDIDATES = frozenset({
    "requests",
    "pyperclip",
    "pyrefly",
    "ast-grep-py",
    "google-auth-httplib2",
})

_CONTENT_LIGHT_FORBIDDEN = frozenset({"secret", "password", "api_key", "token"})


class TestDependencyAuditSchema:
    def test_schema_exists(self) -> None:
        assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    def test_schema_is_valid_json(self) -> None:
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_audit_artifact_exists(self) -> None:
        assert AUDIT_PATH.exists(), f"Audit artifact not found at {AUDIT_PATH}"

    def test_audit_validates_against_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=audit, schema=schema)

    def test_csv_exists(self) -> None:
        assert CSV_PATH.exists(), f"CSV not found at {CSV_PATH}"

    def test_csv_has_expected_columns(self) -> None:
        header = CSV_PATH.read_text(encoding="utf-8").splitlines()[0]
        columns = [c.strip() for c in header.split(",")]
        expected = [
            "package",
            "version_spec",
            "declared_group",
            "import_count",
            "classification",
            "decision",
            "reason",
            "risk_surface",
        ]
        assert columns == expected, f"CSV header mismatch: {columns}"


class TestDependencyAuditContent:
    def test_all_direct_dependencies_accounted(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        direct_deps = [
            d for d in audit["dependencies"] if d["declared_group"] == "direct"
        ]
        assert len(direct_deps) == 49, (
            f"Expected 49 direct deps, got {len(direct_deps)}"
        )

    def test_remove_candidates_documented(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        classified = {d["package"]: d["classification"] for d in audit["dependencies"]}
        for pkg in _REMOVE_CANDIDATES:
            assert pkg in classified, f"{pkg} missing from audit"
            assert classified[pkg] == "remove_candidate", (
                f"{pkg} expected remove_candidate, got {classified[pkg]}"
            )

    def test_canonical_count_matches(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        assert audit["summary"]["production_used"] >= 35, (
            f"production_used={audit['summary']['production_used']}, expected >= 35"
        )

    def test_no_duplicate_packages(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        packages = [d["package"] for d in audit["dependencies"]]
        dupes = [p for p in packages if packages.count(p) > 1]
        assert not dupes, f"Duplicate packages found: {dupes}"

    def test_no_absolute_paths(self) -> None:
        raw = AUDIT_PATH.read_text(encoding="utf-8")
        assert "/Users" not in raw, "Audit JSON contains absolute paths"


class TestDependencyAuditDuckDB:
    def test_duckdb_query_succeeds(self) -> None:
        con = duckdb.connect(":memory:")
        rows = con.execute(
            "SELECT classification, COUNT(*) AS cnt "
            "FROM read_csv_auto(?) "
            "GROUP BY classification ORDER BY cnt DESC",
            [str(CSV_PATH)],
        ).fetchall()
        assert len(rows) > 0, "DuckDB query returned no rows"

    def test_duckdb_group_by_decision(self) -> None:
        con = duckdb.connect(":memory:")
        results = con.execute(
            "SELECT decision, COUNT(*) AS cnt "
            "FROM read_csv_auto(?) "
            "GROUP BY decision ORDER BY decision",
            [str(CSV_PATH)],
        ).fetchall()
        decisions = {row[0] for row in results}
        assert "canonical_keep" in decisions
        assert "test_only_keep" in decisions
        assert "remove_candidate" in decisions

    def test_content_light(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

        def _walk(obj: object) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in _CONTENT_LIGHT_FORBIDDEN:
                        raise AssertionError(f"forbidden_key_in_audit: {key}")
                    _walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(audit)
