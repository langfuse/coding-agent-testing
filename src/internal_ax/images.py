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

import modal

ORCHESTRATOR_IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "langfuse>=4.0,<5",
        "fastapi>=0.110",
        "pydantic>=2.6",
    )
    .add_local_python_source("internal_ax")
)


# Hook config baked into the agent image. Mirrors the plugin's own hooks.json
# (Stop + SessionEnd are the only hooks it registers) but points at the baked
# clone, so headless `claude -p` runs trace without a marketplace install.
_CLAUDE_SETTINGS = r"""
{
  "hooks": {
    "Stop": [
      {"hooks": [{"type": "command",
        "command": "if command -v uv >/dev/null 2>&1; then exec uv run --quiet --script /opt/claude-langfuse-plugin/hooks/langfuse_hook.py; else exec python3 /opt/claude-langfuse-plugin/hooks/langfuse_hook.py; fi"}]}
    ],
    "SessionEnd": [
      {"hooks": [{"type": "command",
        "command": "if command -v uv >/dev/null 2>&1; then exec uv run --quiet --script /opt/claude-langfuse-plugin/hooks/langfuse_hook.py; else exec python3 /opt/claude-langfuse-plugin/hooks/langfuse_hook.py; fi"}]}
    ]
  }
}
"""

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
        "git clone --depth 1 https://github.com/langfuse/Claude-Observability-Plugin /opt/claude-langfuse-plugin",
        "mkdir -p /root/.claude",
        f"cat > /root/.claude/settings.json <<'EOF'\n{_CLAUDE_SETTINGS}\nEOF",
        'echo \'{"hasCompletedOnboarding": true}\' > /root/.claude.json',
    )
    # Codex: official marketplace install of the Langfuse plugin + config.
    .run_commands(
        "mkdir -p /root/.codex",
        f"cat > /root/.codex/config.toml <<'EOF'\n{_CODEX_CONFIG}\nEOF",
        "codex plugin marketplace add langfuse/codex-observability-plugin",
    )
)
