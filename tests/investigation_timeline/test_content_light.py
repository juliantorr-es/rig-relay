from __future__ import annotations

from rig_relay.investigation_timeline._content_light import (
    enforce_content_light,
    enforce_content_light_dict,
)
from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    InvestigationTimelineEvent,
    SourceDomain,
    TimelineEventKind,
)


def test_enforce_content_light_passes_on_clean_events():
    events = [
        InvestigationTimelineEvent(
            observed_at="2025-01-15T10:00:00Z",
            event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
            source_domain=SourceDomain.OBSERVABILITY,
            source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            authority_classification=AuthorityClassification.CANONICAL_LIVE,
        )
    ]
    violations = enforce_content_light(events)
    assert len(violations) == 0


def test_enforce_content_light_rejects_raw_file_contents_field():
    rows: list[dict[str, object]] = [
        {
            "event_id": "evt_001",
            "observed_at": "2025-01-15T10:00:00Z",
            "event_kind": "TOOL_CALL_COMPLETED",
            "source_domain": "observability",
            "source_digest": "sha256:aaaa",
            "raw_file_contents": "some secret code",
        }
    ]
    violations = enforce_content_light_dict(rows)
    assert len(violations) > 0
    assert any("raw_file_contents" in v for v in violations)


def test_enforce_content_light_rejects_api_key_field():
    rows: list[dict[str, object]] = [
        {
            "event_id": "evt_001",
            "observed_at": "2025-01-15T10:00:00Z",
            "event_kind": "TOOL_CALL_COMPLETED",
            "source_domain": "observability",
            "source_digest": "sha256:aaaa",
            "api_key": "sk-secret-key",
        }
    ]
    violations = enforce_content_light_dict(rows)
    assert len(violations) > 0
    assert any("api_key" in v for v in violations)


def test_enforce_content_light_rejects_stdout_field():
    rows: list[dict[str, object]] = [
        {
            "event_id": "evt_001",
            "observed_at": "2025-01-15T10:00:00Z",
            "event_kind": "TOOL_CALL_COMPLETED",
            "source_domain": "observability",
            "source_digest": "sha256:aaaa",
            "stdout": "command output here",
        }
    ]
    violations = enforce_content_light_dict(rows)
    assert len(violations) > 0
    assert any("stdout" in v for v in violations)


def test_enforce_content_light_dict_on_clean_rows():
    rows: list[dict[str, object]] = [
        {
            "event_id": "evt_001",
            "event_kind": "TOOL_CALL_COMPLETED",
            "source_domain": "observability",
            "observed_at": "2025-01-15T10:00:00Z",
        },
        {
            "event_id": "evt_002",
            "event_kind": "SESSION_STARTED",
            "source_domain": "observability",
            "observed_at": "2025-01-15T10:00:05Z",
        },
    ]
    violations = enforce_content_light_dict(rows)
    assert len(violations) == 0


def test_enforce_content_light_dict_rejects_forbidden_key():
    rows: list[dict[str, object]] = [
        {
            "event_id": "evt_001",
            "event_kind": "TOOL_CALL_COMPLETED",
            "source_domain": "observability",
            "observed_at": "2025-01-15T10:00:00Z",
            "api_key": "sk-secret-value",
        }
    ]
    violations = enforce_content_light_dict(rows)
    assert len(violations) > 0
    assert any("api_key" in v for v in violations)
