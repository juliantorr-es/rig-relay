from __future__ import annotations

from pathlib import Path

from rig_relay.core.autocompletion.path_prompt import build_path_prompt_payload


def test_deduplicates_same_file_mentioned_twice(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("hello", encoding="utf-8")

    payload = build_path_prompt_payload(
        "See @README.md and again @README.md", base_dir=tmp_path
    )

    assert len(payload.resources) == 1
    assert payload.resources[0].path == readme
    assert len(payload.all_resources) == 2
