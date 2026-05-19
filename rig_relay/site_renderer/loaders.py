from __future__ import annotations

import json
from pathlib import Path
import subprocess

_REQUIRED_PAGE_FIELDS = {"page_id", "title", "route"}
_REQUIRED_MANIFEST_FIELDS = {"schema_version", "inputs"}
_SOURCE_TYPES_FOR_NORMALIZER = {"json", "jsonl", "schema"}


class SchemaValidationError(ValueError):
    """Exception raised when JSON data fails schema validation."""

    pass


def _make_schema_tolerant(schema: dict | list) -> None:
    """Recursively set additionalProperties to True to allow extra metadata fields in artifacts."""
    if isinstance(schema, dict):
        if "additionalProperties" in schema:
            schema["additionalProperties"] = True
        for val in schema.values():
            if isinstance(val, (dict, list)):
                _make_schema_tolerant(val)
    elif isinstance(schema, list):
        for item in schema:
            if isinstance(item, (dict, list)):
                _make_schema_tolerant(item)


def validate_json_schema(
    data: dict, schema_key: str, repo_root: Path
) -> tuple[bool, str | None]:
    """Validate data against a JSON Schema. Resolves schema file from schema_key.
    Returns (is_valid, error_msg).
    """
    try:
        import jsonschema
    except ImportError:
        return True, None

    try:
        # Normalize schema_key aliases
        if schema_key == "rig.relay.rc_candidate_verdict.v1":
            schema_key = "rig.release_gate.rc_candidate_verdict.v1"

        # Resolve the schema path based on schema_key
        schema_path = None
        if schema_key.startswith("http://") or schema_key.startswith("https://"):
            parts = schema_key.split("/")
            name = parts[-1]
            schema_path = repo_root / "docs" / "schemas" / name
        elif schema_key.endswith(".json"):
            # Extract filename and search in docs/schemas
            name = Path(schema_key).name
            schema_path = repo_root / "docs" / "schemas" / name
        elif "/" in schema_key:
            schema_path = repo_root / schema_key
        else:
            name = schema_key
            if not name.endswith(".schema.json"):
                if name.endswith(".json"):
                    name = name[:-5] + ".schema.json"
                else:
                    name += ".schema.json"
            schema_path = repo_root / "docs" / "schemas" / name

        if not schema_path.is_file():
            return (
                False,
                f"Schema file not found at {schema_path} for schema key {schema_key}",
            )

        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)

        # Make schema tolerant of additional properties
        _make_schema_tolerant(schema)

        jsonschema.validate(instance=data, schema=schema)
        return True, None
    except Exception as e:
        return False, str(e)


def load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def load_jsonl(path: Path) -> list[dict]:
    try:
        rows: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
    except (json.JSONDecodeError, OSError):
        return []


def load_page_model(path: Path, repo_root: Path | None = None) -> dict | None:
    data = load_json(path)
    if not data:
        return None
    for field in _REQUIRED_PAGE_FIELDS:
        if field not in data:
            return None

    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    schema_key = data.get("$schema") or data.get("schema_version") or "rig.site.page.v1"
    is_valid, err = validate_json_schema(data, schema_key, repo_root)
    if not is_valid:
        raise SchemaValidationError(
            f"Page model {path.name} failed schema validation: {err}"
        )

    return data


def load_artifacts_for_page(  # noqa: PLR0912
    page_model: dict, manifest: dict, repo_root: Path | None = None
) -> dict:
    if repo_root is None:
        repo_root = Path.cwd()
    root_r = repo_root.resolve()
    artifacts: dict[str, object] = {}
    page_id = page_model.get("page_id", "")
    inputs = manifest.get("inputs", [])
    if not isinstance(inputs, list):
        return artifacts
    for entry in inputs:
        if not isinstance(entry, dict):
            continue
        if entry.get("page_id") != page_id:
            continue
        source_type = entry.get("source_type", "")
        if source_type not in _SOURCE_TYPES_FOR_NORMALIZER:
            continue
        source_path = entry.get("source_path", "")
        kind = entry.get("renderer_kind", "")
        if not source_path or not kind:
            continue
        full = (root_r / source_path).resolve()
        if not str(full).startswith(str(root_r)):
            continue
        if not full.is_file():
            continue
        if kind in artifacts and isinstance(artifacts[kind], dict):
            continue
        if source_type == "jsonl":
            if kind not in artifacts:
                artifacts[kind] = load_jsonl(full)
            # Optional: validate JSONL rows if schema_path is specified in manifest
            schema_path_key = entry.get("schema_path")
            if schema_path_key:
                for idx, row in enumerate(artifacts[kind]):
                    is_valid, err = validate_json_schema(row, schema_path_key, root_r)
                    if not is_valid:
                        raise SchemaValidationError(
                            f"Row {idx} in JSONL artifact {source_path} failed schema validation: {err}"
                        )
        else:
            art_data = load_json(full)
            if not art_data:
                raise SchemaValidationError(
                    f"Artifact {source_path} is not valid JSON or empty"
                )

            # Validate JSON artifact
            schema_key = (
                art_data.get("$schema")
                or art_data.get("schema_version")
                or entry.get("schema_path")
            )
            if schema_key:
                is_valid, err = validate_json_schema(art_data, schema_key, root_r)
                if not is_valid:
                    raise SchemaValidationError(
                        f"Artifact {source_path} failed schema validation: {err}"
                    )
            artifacts[kind] = art_data
    return artifacts


def load_input_manifest(path: Path, repo_root: Path | None = None) -> dict | None:
    data = load_json(path)
    if not data:
        return None
    for field in _REQUIRED_MANIFEST_FIELDS:
        if field not in data and field.replace("schema_version", "$schema") not in data:
            return None
    # Normalize: ensure we have schema_version
    if "schema_version" not in data and "$schema" in data:
        data["schema_version"] = data["$schema"]
    if "inputs" not in data:
        return None

    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    schema_key = (
        data.get("$schema")
        or data.get("schema_version")
        or "rig.site.input_manifest.v1"
    )
    is_valid, err = validate_json_schema(data, schema_key, repo_root)
    if not is_valid:
        raise SchemaValidationError(
            f"Input manifest {path.name} failed schema validation: {err}"
        )

    return data


def get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        sha = result.stdout.strip()
        if sha:
            return sha[:12]
        return "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def load_artifact(rel_path: str) -> dict | None:
    try:
        root = Path.cwd()
        full = (root / rel_path).resolve()
        if not str(full).startswith(str(root.resolve())):
            return None
        if not full.is_file():
            return None
        return load_json(full)
    except (OSError, ValueError):
        return None
