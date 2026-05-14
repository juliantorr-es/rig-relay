import json
from pathlib import Path
import jsonschema
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution

SCHEMA_PATH = Path("docs/schemas/rig.relay.runtime_context.v1.schema.json")
schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

ctx = RuntimeContext(
    session_id="session-1",
    task_id="task-1",
    repo_root="/tmp/repo",
    coordination_enabled=True,
    resolved_from=["derived_task_id"],
    warnings=["derived deterministically"]
)

res = RuntimeContextResolution(status="resolved", context=ctx)

instance = res.model_dump(mode="json")
print("Instance keys:", instance["context"].keys())

try:
    jsonschema.validate(instance=instance, schema=schema)
    print("Validation passed!")
except jsonschema.ValidationError as e:
    print(f"Validation failed: {e.message}")
    print(f"Path: {list(e.path)}")
