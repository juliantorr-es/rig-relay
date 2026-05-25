from __future__ import annotations

import datetime
import difflib
import hashlib
import json
from pathlib import Path

from rig_relay.review_projection.bundle_builder import deterministic_zip_write
from rig_relay.review_projection.provenance import ProjectionSnapshot
from rig_relay.review_projection.python_projection import (
    PythonPseudonymizer,
    ReplacementLedger,
    _detect_dynamic_access_risk,
)
from rig_relay.review_projection.scan_engine import ProjectionScanner


class DiffBundleResult:
    """Result of the diff projection pipeline."""

    __slots__ = (
        "projection_id",
        "zip_path",
        "zip_sha256",
        "crosswalk_path",
        "receipt_path",
        "scan_findings_path",
        "refused",
        "refusal_reason",
        "files_included",
        "files_excluded",
        "files_refused",
    )

    def __init__(self) -> None:
        self.projection_id = ""
        self.zip_path: Path | None = None
        self.zip_sha256 = ""
        self.crosswalk_path: Path | None = None
        self.receipt_path: Path | None = None
        self.scan_findings_path: Path | None = None
        self.refused = False
        self.refusal_reason = ""
        self.files_included = 0
        self.files_excluded = 0
        self.files_refused = 0


def _derive_projection_id(snapshot: ProjectionSnapshot) -> str:
    h = hashlib.sha256()
    h.update(snapshot.head_sha.encode("utf-8"))
    for path in sorted(snapshot.changed_path_names):
        if path.startswith(".build/"):
            continue
        h.update(path.encode("utf-8"))
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# File projection state — language-agnostic model
# ---------------------------------------------------------------------------


class FileProjectionState:
    """Resolved file state before language-specific projection."""

    __slots__ = (
        "path",
        "state",
        "old_path",
        "suffix",
        "baseline_content",
        "dirty_content",
    )

    def __init__(
        self,
        path: str,
        state: str,
        suffix: str,
        baseline_content: bytes | None = None,
        dirty_content: bytes | None = None,
        old_path: str | None = None,
    ) -> None:
        self.path = path
        self.state = state  # "modified", "added", "deleted", "renamed"
        self.old_path = old_path
        self.suffix = suffix
        self.baseline_content = baseline_content
        self.dirty_content = dirty_content


_SUPPORTED_SUFFIXES: frozenset[str] = frozenset({
    ".py",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
})


class DiffBundler:
    """Orchestrate the review projection diff pipeline.

    Uses a language-agnostic file-state model below the Python/JSON/TOML
    dispatch. Every changed path (added, deleted, modified, renamed) is
    represented in the projection or explicitly refused.
    """

    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._output_dir = (
            self._repo_root / ".build" / "rig-relay" / "review_projection"
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _commit_timestamp(self, snapshot: ProjectionSnapshot) -> str:
        try:
            repo = snapshot._repo
            if repo is not None:
                dt = repo.head.commit.committed_datetime
                return dt.isoformat() + "Z"
        except Exception:
            pass
        return "unknown"

    # ------------------------------------------------------------------
    # File-state resolution
    # ------------------------------------------------------------------

    def _resolve_file_states(
        self, snapshot: ProjectionSnapshot
    ) -> list[FileProjectionState]:
        """Resolve every changed path into a FileProjectionState.

        Handles added (untracked), deleted, renamed, and modified files.
        Unresolvable paths (no baseline AND no dirty content) produce
        explicit refusal records rather than silent omission.
        """
        states: list[FileProjectionState] = []

        for delta in snapshot.changed_paths:
            path = delta.path
            if not path:
                continue
            if path.startswith(".build/"):
                continue

            suffix = Path(path).suffix
            if suffix not in _SUPPORTED_SUFFIXES:
                continue

            # Resolve baseline — try HEAD path first, then old_path for renames
            baseline = snapshot.get_baseline_content(path)
            if baseline is None and delta.old_path:
                baseline = snapshot.get_baseline_content(delta.old_path)

            # Resolve dirty content
            dirty = None
            if delta.change_type != "D":
                dirty = snapshot.get_dirty_content(path)

            # Determine state
            if delta.change_type == "D":
                state = "deleted"
                dirty = b""  # empty dirty for deletion diff
            elif baseline is None and dirty is not None:
                state = "added"
                baseline = b""  # empty baseline for addition diff
            elif delta.change_type in ("R",) and delta.old_path:
                state = "renamed"
            elif baseline is not None and dirty is not None:
                state = "modified"
            else:
                state = "unresolvable"

            if baseline is None and dirty is None:
                state = "unresolvable"

            states.append(
                FileProjectionState(
                    path=path,
                    state=state,
                    suffix=suffix,
                    baseline_content=baseline,
                    dirty_content=dirty,
                    old_path=delta.old_path,
                )
            )

        return states

    # ------------------------------------------------------------------
    # Per-file projection dispatch
    # ------------------------------------------------------------------

    def _project_python_file(
        self,
        fs: FileProjectionState,
        snapshot: ProjectionSnapshot,
        scanner: ProjectionScanner,
        pseudonymizer: PythonPseudonymizer,
        diff_files: dict[str, str],
        changed_path_entries: list[dict[str, object]],
        all_findings: list[dict[str, str]],
    ) -> tuple[int, int, int, ReplacementLedger | None]:
        """Project a single Python file. Returns (included, excluded, refused, ledger)."""
        rel_path = fs.path
        base_bytes = fs.baseline_content
        dirty_bytes = fs.dirty_content

        if base_bytes is None or dirty_bytes is None:
            return 0, 1, 0, None

        try:
            baseline_source = base_bytes.decode("utf-8")
            dirty_source = dirty_bytes.decode("utf-8")
        except UnicodeDecodeError:
            changed_path_entries.append({
                "path": rel_path,
                "decision": "excluded",
                "reason": "binary_file",
                "state": fs.state,
            })
            return 0, 1, 0, None

        # Pre-scan
        pre_findings = scanner.pre_scan(baseline_source, rel_path)
        if dirty_source:
            pre_findings += scanner.pre_scan(dirty_source, rel_path)
        if scanner.should_refuse(pre_findings):
            for f in pre_findings:
                all_findings.append({
                    "path": rel_path,
                    "stage": "pre_scan",
                    "category": f.category,
                    "severity": f.severity,
                    "description": f.description,
                })
            changed_path_entries.append({
                "path": rel_path,
                "decision": "refused",
                "reason": "pre_scan_found_prohibited_content",
                "state": fs.state,
            })
            return 0, 0, 1, None

        # Inventory
        baseline_entries, base_bytes_raw, base_offsets = pseudonymizer.inventory(
            baseline_source, rel_path
        )
        dirty_entries, dirty_bytes_raw, dirty_offsets = pseudonymizer.inventory(
            dirty_source, rel_path
        )

        # Refuse if unsupported Python scopes found (annotation, type params, lambda, comprehension)
        if pseudonymizer.has_unsupported_scope:
            changed_path_entries.append({
                "path": rel_path,
                "decision": "refused",
                "reason": "unsupported_python_scope",
                "state": fs.state,
            })
            return 0, 0, 1, None

        # Build ledger
        ledger = pseudonymizer.build_ledger(rel_path, baseline_entries, dirty_entries)

        # Render
        rendered_base = pseudonymizer.render(
            baseline_source, base_bytes_raw, base_offsets, baseline_entries, ledger
        )
        rendered_dirty = pseudonymizer.render(
            dirty_source, dirty_bytes_raw, dirty_offsets, dirty_entries, ledger
        )

        # Diff header — use old_path for renames
        from_label = f"a/{fs.old_path}" if fs.old_path else f"a/{rel_path}"
        to_label = f"b/{rel_path}"

        diff_lines = list(
            difflib.unified_diff(
                rendered_base.splitlines(keepends=True),
                rendered_dirty.splitlines(keepends=True),
                fromfile=from_label,
                tofile=to_label,
            )
        )
        if not diff_lines:
            changed_path_entries.append({
                "path": rel_path,
                "decision": "excluded",
                "reason": "no_diff_after_projection",
                "state": fs.state,
            })
            return 0, 1, 0, ledger

        diff_text = "".join(diff_lines)

        # Post-scan
        original_symbols = {
            e.identity.original_spelling for e in baseline_entries + dirty_entries
        }
        post_findings = scanner.post_scan(
            rendered_dirty, original_symbols, ledger.mapping
        )
        if scanner.should_refuse(post_findings):
            for f in post_findings:
                all_findings.append({
                    "path": rel_path,
                    "stage": "post_scan",
                    "category": f.category,
                    "severity": f.severity,
                    "description": f.description,
                })
            changed_path_entries.append({
                "path": rel_path,
                "decision": "refused",
                "reason": "post_scan_found_residual_disclosure",
                "state": fs.state,
            })
            return 0, 0, 1, ledger

        # Detect dynamic-access ambiguity — pseudonymized names appearing in
        # getattr/setattr/eval/exec patterns or string literals.
        dynamic_risks = _detect_dynamic_access_risk(
            rendered_dirty, {e.identity.original_spelling for e in dirty_entries}
        )
        if dynamic_risks:
            changed_path_entries.append({
                "path": rel_path,
                "decision": "refused",
                "reason": "dynamic_access_ambiguity",
                "state": fs.state,
            })
            return 0, 0, 1, ledger

        safe_path = rel_path.replace("/", "_").replace("\\", "_")
        diff_files[f"projected_diffs/{safe_path}.diff"] = diff_text
        old_hash = (
            snapshot.hash_baseline(fs.old_path if fs.old_path else rel_path) or ""
        )
        new_hash = snapshot.hash_dirty(rel_path) or ""
        changed_path_entries.append({
            "path": safe_path,
            "decision": "included_pseudonymized",
            "state": fs.state,
            "old_blob_sha256": old_hash,
            "new_blob_sha256": new_hash,
            "diff_hash": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
        })
        return 1, 0, 0, ledger

    def _project_contract_file(
        self,
        fs: FileProjectionState,
        snapshot: ProjectionSnapshot,
        scanner: ProjectionScanner,
        diff_files: dict[str, str],
        changed_path_entries: list[dict[str, object]],
        all_findings: list[dict[str, str]],
    ) -> tuple[int, int, int]:
        """Project a contract-evidence file (JSON/TOML/YAML). No pseudonymization."""
        rel_path = fs.path
        base_bytes = fs.baseline_content
        dirty_bytes = fs.dirty_content

        if base_bytes is None or dirty_bytes is None:
            return 0, 1, 0

        try:
            base_src = base_bytes.decode("utf-8")
            dirty_src = dirty_bytes.decode("utf-8")
        except UnicodeDecodeError:
            changed_path_entries.append({
                "path": rel_path,
                "decision": "excluded",
                "reason": "binary_file",
                "state": fs.state,
            })
            return 0, 1, 0

        # Pre-scan
        pre_findings = scanner.pre_scan(base_src, rel_path)
        if dirty_src:
            pre_findings += scanner.pre_scan(dirty_src, rel_path)
        if scanner.should_refuse(pre_findings):
            for f in pre_findings:
                all_findings.append({
                    "path": rel_path,
                    "stage": "pre_scan",
                    "category": f.category,
                    "severity": f.severity,
                    "description": f.description,
                })
            changed_path_entries.append({
                "path": rel_path,
                "decision": "refused",
                "reason": "pre_scan_found_prohibited_content",
                "state": fs.state,
            })
            return 0, 0, 1

        from_label = f"a/{fs.old_path}" if fs.old_path else f"a/{rel_path}"
        to_label = f"b/{rel_path}"

        diff_lines = list(
            difflib.unified_diff(
                base_src.splitlines(keepends=True),
                dirty_src.splitlines(keepends=True),
                fromfile=from_label,
                tofile=to_label,
            )
        )
        if not diff_lines:
            changed_path_entries.append({
                "path": rel_path,
                "decision": "excluded",
                "reason": "no_diff",
                "state": fs.state,
            })
            return 0, 1, 0

        diff_text = "".join(diff_lines)

        post_findings = scanner.pre_scan(dirty_src, rel_path)
        if scanner.should_refuse(post_findings):
            for f in post_findings:
                all_findings.append({
                    "path": rel_path,
                    "stage": "post_scan",
                    "category": f.category,
                    "severity": f.severity,
                    "description": f.description,
                })
            changed_path_entries.append({
                "path": rel_path,
                "decision": "refused",
                "reason": "post_scan_found_prohibited_content",
                "state": fs.state,
            })
            return 0, 0, 1

        safe_path = rel_path.replace("/", "_").replace("\\", "_")
        diff_files[f"projected_diffs/{safe_path}.diff"] = diff_text
        old_hash = (
            snapshot.hash_baseline(fs.old_path if fs.old_path else rel_path) or ""
        )
        new_hash = snapshot.hash_dirty(rel_path) or ""
        changed_path_entries.append({
            "path": safe_path,
            "decision": "included_contract_evidence",
            "state": fs.state,
            "old_blob_sha256": old_hash,
            "new_blob_sha256": new_hash,
            "diff_hash": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
        })
        return 1, 0, 0

    # ------------------------------------------------------------------
    # Main build pipeline
    # ------------------------------------------------------------------

    def build(self) -> DiffBundleResult:
        result = DiffBundleResult()
        snapshot = ProjectionSnapshot(self._repo_root)
        result.projection_id = _derive_projection_id(snapshot)
        commit_ts = self._commit_timestamp(snapshot)
        scanner = ProjectionScanner(str(self._repo_root))

        file_states = self._resolve_file_states(snapshot)

        pseudonymizer = PythonPseudonymizer()
        all_ledger: ReplacementLedger | None = None
        diff_files: dict[str, str] = {}
        changed_path_entries: list[dict[str, object]] = []
        all_findings: list[dict[str, str]] = []
        included_count = 0
        excluded_count = 0
        refused_count = 0

        for fs in file_states:
            rel_path = fs.path

            # Record unresolvable paths as explicit refusal
            if fs.state == "unresolvable":
                refused_count += 1
                changed_path_entries.append({
                    "path": rel_path,
                    "decision": "refused",
                    "reason": "unresolvable_changed_path",
                    "state": fs.state,
                })
                continue

            if fs.suffix == ".py":
                inc, exc, ref, ledger = self._project_python_file(
                    fs,
                    snapshot,
                    scanner,
                    pseudonymizer,
                    diff_files,
                    changed_path_entries,
                    all_findings,
                )
                if ledger is not None:
                    all_ledger = ledger
            elif fs.suffix in (".json", ".toml", ".yml", ".yaml"):
                inc, exc, ref = self._project_contract_file(
                    fs,
                    snapshot,
                    scanner,
                    diff_files,
                    changed_path_entries,
                    all_findings,
                )
            else:
                exc = 1
                inc = 0
                ref = 0
                changed_path_entries.append({
                    "path": rel_path,
                    "decision": "excluded",
                    "reason": "unsupported_file_type",
                    "state": fs.state,
                })

            included_count += inc
            excluded_count += exc
            refused_count += ref

        if included_count == 0:
            result.refused = True
            result.refusal_reason = "All files refused or excluded"
            result.files_excluded = excluded_count
            result.files_refused = refused_count
            return result

        # Build evidence artifacts
        total_changed = len(file_states)
        assurance = {
            "schema_version": "rig.review_projection.projection_assurance.v1",
            "projection_id": result.projection_id,
            "generated_at": commit_ts,
            "head_sha": snapshot.head_sha,
            "branch": snapshot.branch,
            "is_detached": snapshot.is_detached,
            "has_staged_only_changes": snapshot.has_staged_only_changes,
            "has_unstaged_changes": snapshot.has_unstaged_changes,
            "changed_file_count": total_changed,
            "files_included": included_count,
            "files_excluded": excluded_count,
            "files_refused": refused_count,
            "pre_scan_passed": all(
                f.get("severity") != "block"
                for f in all_findings
                if f.get("stage") == "pre_scan"
            ),
            "post_scan_passed": all(
                f.get("severity") != "block"
                for f in all_findings
                if f.get("stage") == "post_scan"
            ),
            "policy_version": "rig.review_projection.compiler.v1",
            "type": "projection_assurance",
        }

        manifest = {
            "schema_version": "rig.review_projection.projection_manifest.v1",
            "projection_id": result.projection_id,
            "head_sha": snapshot.head_sha,
            "branch": snapshot.branch,
            "is_detached": snapshot.is_detached,
            "generated_at": commit_ts,
            "repo_root_fingerprint": str(self._repo_root),
            "comparison_basis": "HEAD_vs_working_tree",
            "has_staged_only_changes": snapshot.has_staged_only_changes,
            "has_unstaged_changes": snapshot.has_unstaged_changes,
            "untracked_file_count": sum(
                1 for p in snapshot.untracked_files if not p.startswith(".build/")
            ),
            "type": "projection_manifest",
        }

        changed_path_entries.sort(key=lambda e: str(e.get("path", "")))
        changed_paths_jsonl = (
            "\n".join(json.dumps(e, sort_keys=True) for e in changed_path_entries)
            + "\n"
        )

        diff_files["projection_manifest.json"] = json.dumps(manifest, indent=2)
        diff_files["projection_assurance.json"] = json.dumps(assurance, indent=2)
        diff_files["changed_paths.jsonl"] = changed_paths_jsonl

        # Build deterministic ZIP
        zip_path = self._output_dir / f"review_projection_{result.projection_id}.zip"
        zip_hash = deterministic_zip_write(zip_path, diff_files)
        result.zip_path = zip_path
        result.zip_sha256 = zip_hash

        # Local-only artifacts
        crosswalk_data: dict[str, str] = {}
        if all_ledger is not None:
            crosswalk_data = all_ledger.mapping

        crosswalk_json = {
            "schema_version": "rig.review_projection.local_crosswalk.v1",
            "projection_id": result.projection_id,
            "local_only_warning": True,
            "export_prohibited": True,
            "mappings": crosswalk_data,
            "candidate_zip_hash": zip_hash,
        }

        cw_path = self._output_dir / f"crosswalk_{result.projection_id}.json"
        cw_path.write_text(json.dumps(crosswalk_json, indent=2), "utf-8")
        result.crosswalk_path = cw_path

        sf_path = self._output_dir / f"scan_findings_{result.projection_id}.jsonl"
        sf_path.write_text(
            "\n".join(json.dumps(f, sort_keys=True) for f in all_findings) + "\n",
            "utf-8",
        )
        result.scan_findings_path = sf_path

        receipt = {
            "schema_version": "rig.review_projection.compilation_receipt.v1",
            "projection_id": result.projection_id,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
            "head_sha": snapshot.head_sha,
            "branch": snapshot.branch,
            "is_detached": snapshot.is_detached,
            "has_staged_only_changes": snapshot.has_staged_only_changes,
            "has_unstaged_changes": snapshot.has_unstaged_changes,
            "disclosure_target": "LOCAL_CANDIDATE_NO_DISCLOSURE",
            "files_included": included_count,
            "files_excluded": excluded_count,
            "files_refused": refused_count,
            "candidate_zip_sha256": zip_hash,
            "crosswalk_hash": hashlib.sha256(
                json.dumps(crosswalk_json, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "human_export_approval_required": True,
            "legal_safety_not_determined": True,
            "patent_safety_not_determined": True,
            "confidential_holdback_exported": False,
            "raw_source_content_in_receipt": False,
            "raw_source_content_in_manifest": False,
        }

        rcpt_path = self._output_dir / f"receipt_{result.projection_id}.json"
        rcpt_path.write_text(json.dumps(receipt, indent=2), "utf-8")
        result.receipt_path = rcpt_path

        result.files_included = included_count
        result.files_excluded = excluded_count
        result.files_refused = refused_count

        return result
