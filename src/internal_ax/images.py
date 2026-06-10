"""Modal image definitions.

Two images:
  * ORCHESTRATOR_IMAGE — runs the webhook + fan-out + in-process model runs
    (types 1 & 2) and talks to Langfuse. No agent CLIs needed.
  * AGENT_IMAGE — the per-run sandbox for code agents (types 3a/3b): Node 22,
    the Claude Code + Codex CLIs, uv (so the Claude plugin's PEP-723 hook
    auto-resolves langfuse>=4,<5), and both Langfuse observability plugins.

NOTE(validate): the exact headless behaviour of the agent CLIs + plugins is the
least-verified part of this scaffold. Specifically confirm in a smoke test
(see README "Validate the agent path"):
  1. that the Codex npm package name and Claude Code package name are current,
  2. that `Stop`/`SessionEnd` hooks fire under headless `claude -p` / `codex exec`,
  3. that the plugin hook registration paths below match the plugin repos.
If hooks don't fire headless, fall back to native OTel export (see README).
"""

from __future__ import annotations

import modal

ORCHESTRATOR_IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "langfuse>=4.0,<5",
        "openai>=1.40",
        "openai-agents>=0.0.10",
        "openinference-instrumentation-openai-agents>=0.1.0",
        "fastapi>=0.110",
        "pydantic>=2.6",
    )
    .add_local_python_source("internal_ax")
)


# Hook config baked into the agent image. Registers the Langfuse plugin hooks so
# they run during non-interactive agent sessions.
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


AGENT_IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("curl", "git", "ca-certificates")
    # Node 22 (Codex CLI is Rust but ships an npm wrapper; the Codex plugin is a
    # Node ESM bundle needing Node >= 22; Claude Code CLI is also distributed via npm).
    .run_commands(
        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
        "apt-get install -y nodejs",
    )
    # uv lets the Claude plugin's PEP-723 hook self-install langfuse>=4,<5.
    .run_commands("curl -LsSf https://astral.sh/uv/install.sh | sh")
    # Agent CLIs. TODO(validate): confirm current package names/versions.
    .run_commands(
        "npm install -g @anthropic-ai/claude-code",
        "npm install -g @openai/codex",
    )
    # Langfuse SDK present for the Claude hook's non-uv fallback path.
    .pip_install("langfuse>=4.0,<5")
    # Bake both Langfuse observability plugins.
    .run_commands(
        "git clone --depth 1 https://github.com/langfuse/Claude-Observability-Plugin /opt/claude-langfuse-plugin",
        "git clone --depth 1 https://github.com/langfuse/codex-observability-plugin /opt/codex-langfuse-plugin",
    )
    # Register the Claude Code hooks globally so they fire in headless runs.
    .run_commands(
        "mkdir -p /root/.claude",
        f"cat > /root/.claude/settings.json <<'EOF'\n{_CLAUDE_SETTINGS}\nEOF",
    )
)
