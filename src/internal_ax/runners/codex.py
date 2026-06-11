"""Run type 3b: OpenAI Codex, headless, in an isolated sandbox.

Tracing uses the official langfuse/codex-observability-plugin (a Stop hook, a
self-contained Node bundle baked into AGENT_IMAGE). Unlike the Claude plugin,
this one honours LANGFUSE_CODEX_METADATA / LANGFUSE_CODEX_TAGS, so we inject the
dataset item id + run name and correlate cleanly by metadata afterwards.

NOTE(verified 2026-06): Codex *execution* works headlessly with the setup below,
but the plugin's **Stop hook does NOT fire under `codex exec`** (verified in a
Modal sandbox: the agent runs and writes a rollout, but no trace / `.langfuse`
sidecar / hook log appears even with the plugin installed+enabled via
`codex plugin add` and `plugin_hooks=true`, and `LANGFUSE_CODEX_FAIL_ON_ERROR`
never trips). `codex exec` appears not to emit the Stop event that plugin hooks
attach to. So `find_traces_by_metadata` returns nothing and this runner reports
ok=False. Until the plugin supports exec-mode hooks, switch type 3b to native
OTel export (see README "Validate the agent path") or drive Codex via a PTY that
emits Stop. Two more things changed in current Codex (0.139): `codex login
--api-key` was removed (pipe the key to `--with-api-key`), and `codex exec` needs
`--skip-git-repo-check` outside a git repo and has no `--json` flag.
"""

from __future__ import annotations

import datetime as dt
import json

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import RunResult
from internal_ax.runners._sandbox import run_agent

# Authenticate Codex and install the tracing plugin the *official* way. A
# hand-copied cache dir (the previous approach) is never registered and never
# loads — `codex plugin add` writes the cache layout + manifest that makes the
# plugin show as "installed, enabled".
_CODEX_SETUP = [
    # `--api-key` was removed; the supported headless auth reads the key from stdin.
    'printf "%s" "$OPENAI_API_KEY" | codex login --with-api-key',
    # Register the cloned repo as a local marketplace, then add the plugin.
    "codex plugin marketplace add /opt/codex-langfuse-plugin",
    "codex plugin add tracing@codex-observability-plugin </dev/null",
    # Enable the plugin-hooks feature (separate gate from the plugin being enabled).
    "printf '\\n[features]\\nplugin_hooks = true\\n' >> /root/.codex/config.toml",
]


def run(item: DatasetItem, config: RunConfig, run_name: str, app) -> RunResult:
    run_name = lf.run_name_for_config(run_name, config.key)
    started = dt.datetime.now(dt.timezone.utc)
    metadata = {"dataset_item_id": item.id, "run_name": run_name, "run_config": config.key}

    try:
        res = run_agent(
            app,
            prompt=item.prompt,
            env={
                "TRACE_TO_LANGFUSE": "true",
                "LANGFUSE_CODEX_METADATA": json.dumps(metadata),
                "LANGFUSE_CODEX_TAGS": json.dumps(["internal-ax", run_name]),
            },
            setup_cmds=_CODEX_SETUP,
            # No --json flag in current Codex; --skip-git-repo-check (untrusted dir)
            # and the bypass flag let it run non-interactively without approval prompts.
            agent_cmd=(
                "codex exec --skip-git-repo-check "
                '--dangerously-bypass-approvals-and-sandbox "$PROMPT"'
            ),
        )
        output = res.stdout
        transcript = res.stdout + "\n" + res.stderr

        trace_ids = lf.find_traces_by_metadata("dataset_item_id", item.id, since=started)
        scores = scoring.score_agent_usage(output, transcript, item.expected_tool)
        for tid in trace_ids:
            for name, value in scores.items():
                lf.score_trace(trace_id=tid, name=name, value=value)
            lf.link_trace_to_run(run_name=run_name, dataset_item_id=item.id, trace_id=tid)
        lf.flush()

        ok = bool(trace_ids) and res.returncode == 0
        err = None if ok else f"returncode={res.returncode}, traces_found={len(trace_ids)}"
        return RunResult(config.key, item.id, ok=ok, trace_ids=trace_ids, scores=scores, error=err)
    except Exception as e:  # noqa: BLE001
        lf.flush()
        return RunResult(config.key, item.id, ok=False, error=repr(e))
