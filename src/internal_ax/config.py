"""Configuration and the run matrix.

A *run config* is one code agent that executes a dataset item's task. Each
dataset item is executed against every selected run config; each execution
becomes one Langfuse trace linked to the dataset item + named run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class RunType(str, Enum):
    """The code agents we benchmark. Each runs in an isolated Modal Sandbox."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


@dataclass(frozen=True)
class RunConfig:
    key: str  # stable identifier, used in score/run names
    run_type: RunType
    label: str  # human-readable, shown as the Langfuse trace name


def default_run_configs() -> list[RunConfig]:
    """The full matrix executed per dataset item unless the webhook narrows it."""
    return [
        RunConfig("claude-code", RunType.CLAUDE_CODE, "Claude Code"),
        RunConfig("codex", RunType.CODEX, "Codex"),
    ]


def run_config_by_key(key: str) -> RunConfig | None:
    return {c.key: c for c in default_run_configs()}.get(key)


def select_run_configs(keys: list[str] | None) -> list[RunConfig]:
    """Filter the matrix by the optional `run_configs` list in the webhook payload."""
    configs = default_run_configs()
    if not keys:
        return configs
    wanted = set(keys)
    return [c for c in configs if c.key in wanted or c.run_type.value in wanted]


# Per-run sandbox wall-clock budget for code-agent runs (seconds).
SANDBOX_TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "900"))

# Name of the Modal Secret holding the env vars in .env.example.
MODAL_SECRET_NAME = os.environ.get("MODAL_SECRET_NAME", "internal-ax")
