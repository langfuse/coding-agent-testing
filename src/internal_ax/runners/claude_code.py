"""Claude Code, headless, in an isolated Modal sandbox.

Tracing uses the official langfuse/Claude-Observability-Plugin: Stop/SessionEnd
hooks baked into AGENT_IMAGE re-parse the session transcript and upload a trace.
The plugin sets the Langfuse session_id to the Claude Code session id, and we
dictate that id via ``--session-id`` — so correlation is deterministic: after
the run we look up traces by our own session UUID and link them to the dataset
item + run. A per-run LANGFUSE_USER_ID is set as a fallback handle.

Headless notes:
  * Do NOT add ``--bare`` — it skips hooks/plugins entirely, i.e. no trace.
  * ``IS_SANDBOX=1`` lets ``--dangerously-skip-permissions`` run as root (the
    sandbox container is the isolation boundary).
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
    started = dt.datetime.now(dt.timezone.utc)
    session_id = str(uuid.uuid4())  # we choose it; the plugin reports it to Langfuse
    # Per-cell user_id so the fallback lookup can't match another item's trace.
    user_id = f"internal-ax-{run_name}-{item.id}"[:128]

    try:
        res = run_agent(
            app,
            prompt=item.prompt,
            env={
                "LANGFUSE_USER_ID": user_id,
                "IS_SANDBOX": "1",
                "CLAUDE_SESSION_ID": session_id,
            },
            setup_cmds=[],
            agent_cmd=(
                'claude -p "$PROMPT" --session-id "$CLAUDE_SESSION_ID" '
                "--output-format json --dangerously-skip-permissions"
            ),
            env_folder=item.env_folder,
        )
        output = _parse_result(res.stdout)
        transcript = res.stdout + "\n" + res.stderr

        trace_ids = lf.find_traces_by_session_id(session_id, since=started)
        if not trace_ids:
            trace_ids = lf.find_traces_by_user_id(user_id, since=started, retries=3)
        scores = scoring.score_agent_run(
            output, transcript, expected_contains=item.expected_contains, expected_tool=item.expected_tool
        )
        for tid in trace_ids:
            for name, value in scores.items():
                lf.score_trace(trace_id=tid, name=name, value=value)
            lf.link_trace_to_run(run_name=run_name, dataset_item_id=item.id, trace_id=tid)
        lf.flush()

        ok = bool(trace_ids) and res.returncode == 0
        err = None if ok else f"returncode={res.returncode}, traces_found={len(trace_ids)}, stderr={res.stderr[-500:]}"
        return RunResult(config.key, item.id, ok=ok, trace_ids=trace_ids, scores=scores, error=err)
    except Exception as e:  # noqa: BLE001
        lf.flush()
        return RunResult(config.key, item.id, ok=False, error=repr(e))
