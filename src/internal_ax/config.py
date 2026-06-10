"""Configuration and the run matrix.

A *run config* is one way to answer a dataset item's prompt. Each dataset item
is executed against every selected run config; each execution becomes one
Langfuse trace linked to the dataset item + named run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class RunType(str, Enum):
    """The three things we measure (Codex is a second flavour of type 3)."""

    BARE_MODEL = "bare_model"  # type 1: single model call, no tools
    SEARCH_MODEL = "search_model"  # type 2: model + web search + reasoning
    CLAUDE_CODE = "claude_code"  # type 3a: code agent (Claude Code)
    CODEX = "codex"  # type 3b: code agent (Codex)


#: Run types that execute in-process (just API calls) vs. those that need an
#: isolated sandbox with a real filesystem + the agent CLI installed.
IN_PROCESS_RUN_TYPES = {RunType.BARE_MODEL, RunType.SEARCH_MODEL}
SANDBOX_RUN_TYPES = {RunType.CLAUDE_CODE, RunType.CODEX}


@dataclass(frozen=True)
class RunConfig:
    key: str  # stable identifier, used in score/run names
    run_type: RunType
    label: str  # human-readable, shown as the Langfuse trace name
    model: str  # model id (or "" where the agent picks its own)


def _anthropic_model() -> str:
    # Verify against the current Anthropic model list before relying on it.
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def _openai_model() -> str:
    # gpt-4o is a safe known default; set OPENAI_MODEL to your preferred frontier model.
    return os.environ.get("OPENAI_MODEL", "gpt-4o")


def default_run_configs() -> list[RunConfig]:
    """The full matrix executed per dataset item unless the webhook narrows it."""
    return [
        RunConfig("bare-claude", RunType.BARE_MODEL, "Bare model (Claude)", _anthropic_model()),
        RunConfig("bare-gpt", RunType.BARE_MODEL, "Bare model (GPT)", _openai_model()),
        RunConfig("search-gpt", RunType.SEARCH_MODEL, "Model + search (GPT)", _openai_model()),
        RunConfig("claude-code", RunType.CLAUDE_CODE, "Claude Code", ""),
        RunConfig("codex", RunType.CODEX, "Codex", ""),
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


@dataclass(frozen=True)
class Settings:
    langfuse_base_url: str

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            langfuse_base_url=os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )


# Per-run sandbox wall-clock budget for code-agent runs (seconds).
SANDBOX_TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "900"))

# Name of the Modal Secret holding the env vars in .env.example.
MODAL_SECRET_NAME = os.environ.get("MODAL_SECRET_NAME", "internal-ax")
