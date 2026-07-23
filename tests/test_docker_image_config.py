from __future__ import annotations

import json
from pathlib import Path

from internal_ax.images import _CLAUDE_SETTINGS, _CODEX_CONFIG

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_local_docker_agent_configs_match_modal_image() -> None:
    docker_claude = json.loads(
        (_REPO_ROOT / "docker" / "claude-settings.json").read_text()
    )
    assert docker_claude == json.loads(_CLAUDE_SETTINGS)
    assert (
        _REPO_ROOT / "docker" / "codex-config.toml"
    ).read_text().strip() == _CODEX_CONFIG.strip()
