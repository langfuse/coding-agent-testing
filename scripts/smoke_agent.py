"""Local Sandbox smoke test for AGENT_IMAGE (STEP 6 validation).

Mirrors runners/_sandbox.py::run_agent exactly: create a modal.Sandbox from
AGENT_IMAGE and run commands via `sb.exec("bash", "-lc", ...)`. Runs entirely on
your machine (no `modal run`), so nothing imports internal_ax inside the sandbox
— the sandbox only ever runs shell, just like production.

Verifies:
  1. node/uv present; `claude --version`, `codex --version` (CLIs installed).
  2. plugin repos cloned + the hook paths the image config references.
  3. headless `claude -p` + `codex exec` run, then whether the baked Langfuse
     plugin hooks fired (trace tagged with our user_id / metadata shows up).

Run:  set -a && source .env && set +a && .venv/bin/python scripts/smoke_agent.py
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import modal

from internal_ax import langfuse_helpers as lf
from internal_ax.config import MODAL_SECRET_NAME
from internal_ax.images import AGENT_IMAGE


def sh(sb: modal.Sandbox, cmd: str, label: str) -> tuple[int | None, str, str]:
    p = sb.exec("bash", "-lc", cmd)
    p.wait()
    out, err = p.stdout.read(), p.stderr.read()
    print(f"\n### {label}  (rc={p.returncode})")
    print(f"$ {cmd}")
    if out.strip():
        print(out[-4000:])
    if err.strip():
        print("[stderr]", err[-2000:])
    return p.returncode, out, err


def main() -> None:
    app = modal.App.lookup("internal-ax-smoke", create_if_missing=True)
    user_id = f"smoke-claude-{uuid.uuid4().hex[:8]}"
    codex_item = f"smoke-codex-{uuid.uuid4().hex[:8]}"
    started = dt.datetime.now(dt.timezone.utc)
    print(f"claude user_id={user_id}  codex dataset_item_id={codex_item}")

    with modal.enable_output():
        sb = modal.Sandbox.create(
            app=app,
            image=AGENT_IMAGE,
            secrets=[modal.Secret.from_name(MODAL_SECRET_NAME)],
            timeout=480,
        )
    try:
        # 1 + 2: versions and plugin layout
        sh(sb, "node --version && npm --version", "node/npm")
        sh(sb, "command -v uv && uv --version || echo NO_UV", "uv")
        sh(sb, "timeout 60 claude --version </dev/null", "claude --version")
        sh(sb, "timeout 60 codex --version </dev/null", "codex --version")
        sh(sb, "ls -la /opt/claude-langfuse-plugin && echo '--- *.py ---' && "
               "find /opt/claude-langfuse-plugin -maxdepth 3 -name '*.py'", "claude plugin layout")
        sh(sb, "cat /root/.claude/settings.json", "claude settings.json (baked hooks)")
        sh(sb, "ls -la /opt/codex-langfuse-plugin && echo '--- tree ---' && "
               "find /opt/codex-langfuse-plugin -maxdepth 4 | head -60", "codex plugin layout")

        # 3a: headless Claude Code with our per-run user_id (env inline; hook is a child proc and inherits it)
        sh(sb,
           f'mkdir -p /workspace && cd /workspace && '
           f'LANGFUSE_USER_ID={user_id} TRACE_TO_LANGFUSE=true '
           f'timeout 150 claude -p "say hi in one word" --output-format json '
           f'--dangerously-skip-permissions </dev/null',
           "claude -p headless")

        # 3b: Codex setup (mirrors runners/codex.py::_CODEX_SETUP) + headless exec with metadata
        codex_meta = json.dumps({"dataset_item_id": codex_item, "run_name": "smoke"})
        sh(sb,
           "mkdir -p /root/.codex/plugins/cache/codex-observability-plugin/tracing/0.1.0 && "
           "cp -r /opt/codex-langfuse-plugin/plugins/tracing/* "
           "/root/.codex/plugins/cache/codex-observability-plugin/tracing/0.1.0/ 2>&1; "
           "printf '%s\\n' '[features]' 'plugin_hooks = true' "
           "'[plugins.\"tracing@codex-observability-plugin\"]' 'enabled = true' "
           "> /root/.codex/config.toml; echo '--- config.toml ---'; cat /root/.codex/config.toml",
           "codex setup")
        sh(sb,
           f"cd /workspace && TRACE_TO_LANGFUSE=true LANGFUSE_CODEX_METADATA='{codex_meta}' "
           f'timeout 150 codex exec "say hi in one word" --json </dev/null',
           "codex exec headless")
    finally:
        sb.terminate()

    # Correlation: did the plugin hooks export traces we can find?
    print("\n=== Langfuse correlation (polling) ===")
    ctids = lf.find_traces_by_user_id(user_id, since=started)
    print(f"claude  user_id={user_id}  -> traces: {ctids or 'NONE (hook did not fire / export failed)'}")
    xtids = lf.find_traces_by_metadata("dataset_item_id", codex_item, since=started)
    print(f"codex   dataset_item_id={codex_item}  -> traces: {xtids or 'NONE (hook did not fire / export failed)'}")


if __name__ == "__main__":
    main()
