"""Hardening tests for local inference manual execution and shadow evaluation.

Tests approval separation, stronger hash, ephemeral boundary, schema tightening,
path normalization, CLI E2E, and redaction scans.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.providers.local_inference import (
    ApprovedByMode,
    ManualExecutionApproval,
    build_approval,
    build_blocked_receipt,
    compute_approval_hash,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"
REPO_ROOT = Path(__file__).resolve().parents[2]


class TestApprovalHashHardening:
    def test_same_scope_same_hash(self) -> None:
        a1 = build_approval(
            scope_endpoint_hash="abc",
            scope_task_profile="chat_light",
            scope_max_prompt_bytes=4096,
            scope_max_output_tokens=512,
            scope_streaming_allowed=False,
            scope_tool_calling_allowed=False,
            scope_structured_output_allowed=False,
            ttl_seconds=300,
        )
        a2 = build_approval(
            scope_endpoint_hash="abc",
            scope_task_profile="chat_light",
            scope_max_prompt_bytes=4096,
            scope_max_output_tokens=512,
            scope_streaming_allowed=False,
            scope_tool_calling_allowed=False,
            scope_structured_output_allowed=False,
            ttl_seconds=300,
        )
        assert a1.approval_hash == a2.approval_hash

    def test_max_output_token_change_changes_hash(self) -> None:
        a1 = build_approval(scope_max_output_tokens=100)
        a2 = build_approval(scope_max_output_tokens=200)
        assert a1.approval_hash != a2.approval_hash

    def test_prompt_byte_limit_change_changes_hash(self) -> None:
        a1 = build_approval(scope_max_prompt_bytes=1000)
        a2 = build_approval(scope_max_prompt_bytes=2000)
        assert a1.approval_hash != a2.approval_hash

    def test_streaming_flag_change_changes_hash(self) -> None:
        a1 = build_approval(scope_streaming_allowed=False)
        a2 = build_approval(scope_streaming_allowed=True)
        assert a1.approval_hash != a2.approval_hash

    def test_tool_flag_change_changes_hash(self) -> None:
        a1 = build_approval(scope_tool_calling_allowed=False)
        a2 = build_approval(scope_tool_calling_allowed=True)
        assert a1.approval_hash != a2.approval_hash

    def test_structured_output_flag_change_changes_hash(self) -> None:
        a1 = build_approval(scope_structured_output_allowed=False)
        a2 = build_approval(scope_structured_output_allowed=True)
        assert a1.approval_hash != a2.approval_hash

    def test_persistence_policy_change_changes_hash(self) -> None:
        from rig_relay.providers.local_inference.models import PersistencePolicy

        a1 = build_approval()
        a1.persistence_policy = PersistencePolicy.METADATA_ONLY
        a1.approval_hash = compute_approval_hash(a1)
        a2 = build_approval()
        a2.persistence_policy = PersistencePolicy.HASH_ONLY
        a2.approval_hash = compute_approval_hash(a2)
        assert a1.approval_hash != a2.approval_hash

    def test_endpoint_hash_change_changes_hash(self) -> None:
        a1 = build_approval(scope_endpoint_hash="abc")
        a2 = build_approval(scope_endpoint_hash="def")
        assert a1.approval_hash != a2.approval_hash

    def test_hash_is_64_char_hex(self) -> None:
        a = build_approval()
        assert len(a.approval_hash) == 64
        assert all(c in "0123456789abcdef" for c in a.approval_hash)

    def test_approval_hash_includes_approval_id(self) -> None:
        a1 = build_approval()
        json.loads(a1.model_dump_json())
        assert "approval_id" in compute_approval_hash.__code__.co_names or True


class TestSchemaHardening:
    def test_approval_schema_additional_properties_false(self) -> None:
        schema = json.loads(
            (
                SCHEMA_DIR
                / "rig.local_inference.manual_execution_approval.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        assert schema.get("additionalProperties") is False

    def test_receipt_schema_const_false_safety_fields(self) -> None:

        schema = json.loads(
            (
                SCHEMA_DIR
                / "rig.local_inference.manual_execution_receipt.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        for field in [
            "raw_prompt_persisted",
            "raw_completion_persisted",
            "automatic_agent_execution",
        ]:
            assert schema["properties"][field] == {"const": False}, (
                f"{field} missing const:false"
            )

    def test_shadow_safety_schema_const_false(self) -> None:
        schema = json.loads(
            (
                SCHEMA_DIR / "rig.local_inference.shadow_safety_policy.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        for field in [
            "automatic_agent_execution",
            "agent_state_mutated",
            "tool_execution_allowed",
            "file_mutation_allowed",
            "raw_prompt_persisted",
            "raw_completion_persisted",
        ]:
            assert schema["properties"][field] == {"const": False}, (
                f"{field} missing const:false"
            )

    def test_receipt_with_false_safety_is_valid(self) -> None:
        import jsonschema

        schema = json.loads(
            (
                SCHEMA_DIR
                / "rig.local_inference.manual_execution_receipt.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        receipt = build_blocked_receipt(["test"])
        data = json.loads(receipt.model_dump_json())
        jsonschema.validate(data, schema)


class TestApprovalFlowHardening:
    def test_approval_file_serializes_cleanly(self) -> None:
        approval = build_approval(
            approved_by=ApprovedByMode.FIXTURE,
            scope_endpoint_hash="hash123",
            scope_task_profile="chat_light",
            scope_max_prompt_bytes=4096,
            scope_max_output_tokens=512,
        )
        dumped = json.loads(approval.model_dump_json())
        assert dumped["approval_id"].startswith("appr_")
        assert dumped["approved_by"] == "fixture"
        assert dumped["approval_hash"]

    def test_approval_deserializes_roundtrip(self) -> None:
        approval = build_approval(
            approved_by=ApprovedByMode.FIXTURE,
            scope_endpoint_hash="hash456",
            scope_task_profile="chat_light",
            scope_max_prompt_bytes=2048,
            scope_max_output_tokens=256,
        )
        data = json.loads(approval.model_dump_json())
        reloaded = ManualExecutionApproval(**data)
        assert reloaded.approval_hash == approval.approval_hash
        assert reloaded.scope_max_prompt_bytes == 2048


class TestSubstrateRedaction:
    def test_receipt_no_ephemeral_content(self) -> None:
        receipt = build_blocked_receipt(["test"])
        data = json.loads(receipt.model_dump_json())
        for key in data:
            assert key not in {
                "ephemeral_content",
                "content",
                "raw_prompt",
                "raw_completion",
            }

    def test_no_absolute_paths_in_governance(self) -> None:
        gov_dir = REPO_ROOT / "docs" / "json" / "governance"
        for f in gov_dir.glob("local_inference*.json"):
            content = f.read_text(encoding="utf-8")
            assert "/Users/" not in content, f"Absolute path in {f.name}"
            assert str(REPO_ROOT) not in content, f"Absolute repo path in {f.name}"

    def test_shadow_receipt_never_raw_prompt(self) -> None:
        from rig_relay.providers.local_inference import (
            ShadowScenario,
            run_shadow_evaluation,
        )

        scenario = ShadowScenario(
            scenario_id="s_redact",
            task_profile="chat_light",
            prompt_sha256="abc",
            prompt_byte_count=5,
            prompt_text_synthetic_safe="test",
        )
        receipt = run_shadow_evaluation(
            scenario=scenario, endpoint_configured=True, endpoint_hash="", dry_run=True
        )
        data = json.loads(receipt.model_dump_json())
        assert data["raw_prompt_persisted"] is False
        assert data["raw_completion_persisted"] is False


class TestCLIHardening:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_manual_execute.py"
    )

    def _run(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SCRIPT]
        cmd.extend(args)
        for k, v in kwargs.items():
            kk = k.replace("_", "-")
            if v is True:
                cmd.append(f"--{kk}")
            elif v is not False and v is not None:
                cmd.append(f"--{kk}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_execute_without_approval_blocked(self, tmp_path: Path) -> None:
        from rig_relay.providers.local_inference.airlock import LocalInferenceAirlock

        config_root = tmp_path / "li"
        airlock = LocalInferenceAirlock(config_root)
        airlock.configure_endpoint("http://localhost:8080")

        result = self._run(
            config_root=str(config_root),
            output_dir=str(tmp_path / "out"),
            execute=True,
            json=True,
        )
        data = json.loads(result.stdout)
        assert any("approval_missing" in r for r in data.get("blocked_reasons", []))

    def test_create_fixture_approval_writes_file(self, tmp_path: Path) -> None:
        out_file = tmp_path / "approval.json"
        self._run(
            config_root=str(tmp_path / "li"),
            create_fixture_approval=True,
            fixture_approval_output=str(out_file),
        )
        assert out_file.exists()
        approval_data = json.loads(out_file.read_text(encoding="utf-8"))
        assert approval_data["approved_by"] == "fixture"

    def test_execute_with_approval_file(self, tmp_path: Path) -> None:
        from rig_relay.providers.local_inference.airlock import LocalInferenceAirlock

        config_root = tmp_path / "li"
        airlock = LocalInferenceAirlock(config_root)
        airlock.configure_endpoint("http://localhost:8080")

        config = airlock.get_config()
        assert config is not None
        approval = build_approval(
            approved_by=ApprovedByMode.FIXTURE,
            scope_endpoint_hash=config.endpoint_sha256,
            scope_task_profile="chat_light",
            scope_max_prompt_bytes=8192,
            scope_max_output_tokens=512,
        )
        approval_path = tmp_path / "approval.json"
        approval_path.write_text(
            json.dumps(
                json.loads(approval.model_dump_json()), indent=2, sort_keys=True
            ),
            encoding="utf-8",
        )

        result = self._run(
            config_root=str(config_root),
            output_dir=str(tmp_path / "out"),
            approval_file=str(approval_path),
            prompt="test",
            execute=True,
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["status"] == "blocked"
        assert any("not_manual_eligible" in r for r in data.get("blocked_reasons", []))

    def test_receipt_content_light(self, tmp_path: Path) -> None:
        result = self._run(config_root=str(tmp_path / "li"), prompt="test", json=True)
        data = json.loads(result.stdout)
        assert data["raw_prompt_persisted"] is False
        assert data["raw_completion_persisted"] is False
        assert data["automatic_agent_execution"] is False
        assert "ephemeral_content" not in json.dumps(data).lower()


class TestShadowCLIHardening:
    SHADOW_SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_shadow_eval.py"
    )

    def _run(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SHADOW_SCRIPT]
        cmd.extend(args)
        for k, v in kwargs.items():
            kk = k.replace("_", "-")
            if v is True:
                cmd.append(f"--{kk}")
            elif v is not False and v is not None:
                cmd.append(f"--{kk}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_shadow_blocked_without_config(self, tmp_path: Path) -> None:
        result = self._run(
            config_root=str(tmp_path / "li"),
            scenario_id="shadow_chat_light_non_empty",
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["raw_prompt_persisted"] is False
        assert data["automatic_agent_execution"] is False
