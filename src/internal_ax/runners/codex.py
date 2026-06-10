"""Run type 3b: OpenAI Codex, headless, in an isolated sandbox.

Tracing uses the official langfuse/codex-observability-plugin (a Stop hook, a
self-contained Node bundle baked into AGENT_IMAGE). Unlike the Claude plugin,
this one honours LANGFUSE_CODEX_METADATA / LANGFUSE_CODEX_TAGS, so we inject the
dataset item id + run name and correlate cleanly by metadata afterwards.

NOTE(validate): confirm (1) the Codex plugin cache path / version dir written in
setup below matches the plugin repo, and (2) that the Stop hook fires under the
non-interactive `codex exec` subcommand. See README "Validate the agent path".
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

# Place the baked plugin where Codex looks for it, and enable it. TODO(validate)
# the version dir ("0.1.0") and plugin id against the plugin repo's current layout.
_CODEX_SETUP = [
    "mkdir -p /root/.codex/plugins/cache/codex-observability-plugin/tracing/0.1.0",
    "cp -r /opt/codex-langfuse-plugin/plugins/tracing/* "
    "/root/.codex/plugins/cache/codex-observability-plugin/tracing/0.1.0/",
    "printf '%s\\n' "
    "'[features]' 'plugin_hooks = true' "
    "'[plugins.\"tracing@codex-observability-plugin\"]' 'enabled = true' "
    "> /root/.codex/config.toml",
]


def run(item: DatasetItem, config: RunConfig, run_name: str, app) -> RunResult:
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
            # TODO(validate) exact codex exec flags for non-interactive structured output.
            agent_cmd='codex exec "$PROMPT" --json',
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
