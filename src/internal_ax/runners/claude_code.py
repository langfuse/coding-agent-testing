"""Run type 3a: Claude Code, headless, in an isolated sandbox.

Tracing uses the official langfuse/Claude-Observability-Plugin (a Stop/SessionEnd
hook baked into AGENT_IMAGE). That plugin creates its OWN trace and exposes no
custom-metadata hook -- the only externally-settable handle is LANGFUSE_USER_ID.
Since each sandbox is 1:1 with a run, we set a unique per-run user_id, then query
Langfuse for the trace(s) it emitted and link them to the dataset item + run.

NOTE(validate): confirm Stop/SessionEnd hooks fire under headless `claude -p`. If
they don't, switch this runner to native OTel export (CLAUDE_CODE_ENABLE_TELEMETRY
+ OTEL_EXPORTER_OTLP_ENDPOINT -> Langfuse /api/public/otel) with TRACEPARENT
propagated from a Langfuse root span. See README "Validate the agent path".
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import RunResult
from internal_ax.runners._sandbox import run_agent


def _parse_result(stdout: str) -> str:
    try:
        return str(json.loads(stdout).get("result", stdout))
    except (json.JSONDecodeError, AttributeError):
        return stdout


def run(item: DatasetItem, config: RunConfig, run_name: str, app) -> RunResult:
    run_name = lf.run_name_for_config(run_name, config.key)
    started = dt.datetime.now(dt.timezone.utc)
    # Encode the run into user_id; this is our only correlation handle for Claude.
    user_id = f"axrun-{run_name}-{item.id}-{uuid.uuid4().hex[:8]}"[:128]

    try:
        res = run_agent(
            app,
            prompt=item.prompt,
            # IS_SANDBOX=1 lets `--dangerously-skip-permissions` run as root (the
            # sandbox's only user); without it Claude Code refuses for security.
            env={
                "LANGFUSE_USER_ID": user_id,
                "TRACE_TO_LANGFUSE": "true",
                "IS_SANDBOX": "1",
            },
            setup_cmds=[],
            agent_cmd='claude -p "$PROMPT" --output-format json --dangerously-skip-permissions',
        )
        output = _parse_result(res.stdout)
        transcript = res.stdout + "\n" + res.stderr

        trace_ids = lf.find_traces_by_user_id(user_id, since=started)
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
