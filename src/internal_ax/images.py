"""Modal image definitions.

Two images:
  * ORCHESTRATOR_IMAGE — runs the webhook + fan-out and talks to Langfuse.
    No agent CLIs needed.
  * AGENT_IMAGE — the per-run sandbox for the code agents: Node 22, the Claude
    Code + Codex CLIs, uv (so the Claude plugin's PEP-723 hook self-installs
    langfuse>=4,<5), and both official Langfuse observability plugins:
      - https://github.com/langfuse/Claude-Observability-Plugin (Stop/SessionEnd
        hooks, registered globally in /root/.claude/settings.json)
      - https://github.com/langfuse/codex-observability-plugin (installed via
        `codex plugin marketplace add`, enabled in /root/.codex/config.toml)
"""

from __future__ import annotations

import json
from pathlib import Path

import modal

# Starter workspaces for dataset items (metadata.env_folder). Shipped with the
# ORCHESTRATOR image at /opt/envs and uploaded into each sandbox's /workspace
# by the runner. They must ride with the orchestrator (not AGENT_IMAGE):
# AGENT_IMAGE is hydrated inside the remote run_unit container, where repo-local
# add_local_dir sources don't exist.
_ENVS_DIR = Path(__file__).resolve().parents[2] / "envs"

# Pinned revisions of the official Langfuse observability plugins. Bump these
# to pull a newer plugin — a changed SHA invalidates the image layer cache, so
# the update is explicit and reproducible (an unpinned clone would silently
# freeze at whatever HEAD was when the layer was first built).
CLAUDE_PLUGIN_REV = "d654237fdf3fbbb3013c828280e9d4d80537f9a2"  # 2026-07-13, deterministic trace ids (PR #23)
CODEX_PLUGIN_REV = "030d69d1f40679c8205202158807c79b56438cbd"  # 2026-07-13, deterministic trace ids (PR #24)

ORCHESTRATOR_IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "langfuse>=4.0,<5",
        "fastapi>=0.110",
        "pydantic>=2.6",
    )
    .add_local_python_source("internal_ax")
    .add_local_dir(str(_ENVS_DIR), "/opt/envs")
)


# Hook config baked into the agent image. Mirrors the plugin's own hooks.json
# (Stop + SessionEnd are the only hooks it registers) but points at the baked
# clone, so headless `claude -p` runs trace without a marketplace install.
#
# The env remap at the start of the command routes the PLUGIN's upload at the
# harness Langfuse project (CC_LANGFUSE_*) even when the agent-visible plain
# LANGFUSE_* vars point at the separate sandbox project. Needed because the
# hook script checks plain vars BEFORE the CC_-prefixed ones (unlike the Codex
# plugin, where the prefix takes precedence natively). Falls back to plain
# vars when CC_* is unset.
_CLAUDE_HOOK_CMD = (
    'export LANGFUSE_PUBLIC_KEY="${CC_LANGFUSE_PUBLIC_KEY:-$LANGFUSE_PUBLIC_KEY}" '
    'LANGFUSE_SECRET_KEY="${CC_LANGFUSE_SECRET_KEY:-$LANGFUSE_SECRET_KEY}" '
    'LANGFUSE_BASE_URL="${CC_LANGFUSE_BASE_URL:-$LANGFUSE_BASE_URL}"; '
    "if command -v uv >/dev/null 2>&1; "
    "then exec uv run --quiet --script /opt/claude-langfuse-plugin/hooks/langfuse_hook.py; "
    "else exec python3 /opt/claude-langfuse-plugin/hooks/langfuse_hook.py; fi"
)

_CLAUDE_SETTINGS = json.dumps(
    {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": _CLAUDE_HOOK_CMD}]}],
            "SessionEnd": [{"hooks": [{"type": "command", "command": _CLAUDE_HOOK_CMD}]}],
        }
    },
    indent=2,
)

# Codex config: enable plugin hooks + the Langfuse tracing plugin, and prefer
# API-key auth (the sandbox has OPENAI_API_KEY, no ChatGPT login).
_CODEX_CONFIG = """
preferred_auth_method = "apikey"

[features]
plugin_hooks = true

[plugins."tracing@codex-observability-plugin"]
enabled = true
"""


AGENT_IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("curl", "git", "ca-certificates")
    # Node 22: required by the Codex plugin bundle; both CLIs ship via npm.
    .run_commands(
        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
        "apt-get install -y nodejs",
    )
    # uv lets the Claude plugin's PEP-723 hook self-install langfuse>=4,<5.
    .run_commands("curl -LsSf https://astral.sh/uv/install.sh | sh")
    .run_commands(
        "npm install -g @anthropic-ai/claude-code",
        "npm install -g @openai/codex",
    )
    # Langfuse SDK present for the Claude hook's non-uv fallback path.
    .pip_install("langfuse>=4.0,<5")
    # Claude Code: bake the plugin clone, register its hooks globally, and mark
    # onboarding done so headless runs don't stall on first-run prompts.
    .run_commands(
        "git clone https://github.com/langfuse/Claude-Observability-Plugin /opt/claude-langfuse-plugin"
        f" && git -C /opt/claude-langfuse-plugin checkout {CLAUDE_PLUGIN_REV}",
        "mkdir -p /root/.claude",
        f"cat > /root/.claude/settings.json <<'EOF'\n{_CLAUDE_SETTINGS}\nEOF",
        'echo \'{"hasCompletedOnboarding": true}\' > /root/.claude.json',
    )
    # Codex: official marketplace install of the Langfuse plugin + config.
    # marketplace add always installs HEAD; the echoed rev is a cache-buster so
    # bumping CODEX_PLUGIN_REV forces a fresh install of the current plugin.
    .run_commands(
        "mkdir -p /root/.codex",
        f"cat > /root/.codex/config.toml <<'EOF'\n{_CODEX_CONFIG}\nEOF",
        f"echo 'codex plugin rev {CODEX_PLUGIN_REV}'"
        " && codex plugin marketplace add langfuse/codex-observability-plugin",
    )
)
