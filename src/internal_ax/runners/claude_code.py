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

import json
import traceback
import uuid

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem, ExperimentContext
from internal_ax.runners import RunResult
from internal_ax.runners._sandbox import EnvironmentNotFoundError, run_agent
from internal_ax.skills import ResolvedSkill


def _parse_result(stdout: str) -> str:
    try:
        return str(json.loads(stdout).get("result", stdout))
    except (json.JSONDecodeError, AttributeError):
        return stdout


def run(
    item: DatasetItem,
    config: RunConfig,
    run_name: str,
    app,
    model: str | None = None,
    *,
    skill: ResolvedSkill | None = None,
    experiment: ExperimentContext | None = None,
) -> RunResult:
    session_id = str(uuid.uuid4())  # we choose it; the plugin reports it to Langfuse
    # Shown as the trace's user in the Langfuse UI — pure annotation.
    user_id = f"internal-ax-{run_name}-{item.id}"[:128]
    # The plugin (>= PR #23) derives trace ids from CC_LANGFUSE_TRACE_SEED as
    # create_trace_id(f"{seed}:{turn}"); `claude -p` is exactly one turn, so the
    # trace id is known before the agent even starts — no discovery queries.
    trace_id = lf.deterministic_trace_id(f"{session_id}:1")

    env = {
        "TRACE_TO_LANGFUSE": "true",  # repo hook ignores it; docs' manual hook requires it
        "LANGFUSE_USER_ID": user_id,
        "IS_SANDBOX": "1",
        "CLAUDE_SESSION_ID": session_id,
        "CC_LANGFUSE_TRACE_SEED": session_id,
    }
    # Payload-provided model rides in as an env var so it's never shell-interpolated.
    model_flag = ""
    if model:
        env["AGENT_MODEL"] = model
        model_flag = ' --model "$AGENT_MODEL"'

    try:
        res = run_agent(
            app,
            prompt=item.prompt,
            env=env,
            setup_cmds=[],
            agent_cmd=(
                'claude -p "$PROMPT" --session-id "$CLAUDE_SESSION_ID" '
                f"--output-format json --dangerously-skip-permissions{model_flag} < /dev/null"
            ),
            env_folder=item.env_folder,
            skill=skill,
            skill_home="/root/.claude/skills",
        )
        output = _parse_result(res.stdout)
        transcript = res.stdout + "\n" + res.stderr

        # Confirm the plugin's (async) upload of the precomputed trace id landed.
        trace_ids = [trace_id] if lf.wait_for_trace(trace_id) else []
        scores = scoring.score_agent_run(
            output,
            transcript,
            expected_contains=item.expected_contains,
            expected_tool=item.expected_tool,
            task_prompt=item.prompt,
        )
        for tid in trace_ids:
            for name, s in scores.items():
                lf.score_trace(trace_id=tid, name=name, value=s["value"], comment=s.get("comment"))
            metadata = {
                "agent": config.key,
                "harness": "internal-ax",
                "model": model or "cli-default",
            }
            if skill:
                metadata.update(skill.metadata())
            metadata["execution"] = "modal"
            skill_read_ids = lf.annotate_skill_reads(trace_id=tid, skill=skill)
            metadata["skill_reads_detected"] = len(skill_read_ids)
            lf.register_native_experiment_item(
                experiment=experiment,
                item=item,
                trace_id=tid,
                output=output,
                run_metadata=metadata,
            )
            lf.link_trace_to_run(
                run_name=run_name,
                dataset_item_id=item.id,
                trace_id=tid,
                run_description=f"{config.label} via internal-ax on Modal",
                metadata=metadata,
            )
        lf.flush()

        ok = bool(trace_ids) and res.returncode == 0
        err = None if ok else f"returncode={res.returncode}, traces_found={len(trace_ids)}, stderr={res.stderr[-500:]}"
        return RunResult(config.key, item.id, ok=ok, trace_ids=trace_ids, scores=scores, error=err)
    except EnvironmentNotFoundError as e:
        metadata = {
            "agent": config.key,
            "harness": "internal-ax",
            "model": model or "cli-default",
            "execution": "modal",
        }
        if skill:
            metadata.update(skill.metadata())
        trace_ids: list[str] = []
        error = str(e)
        try:
            trace_ids.append(
                lf.record_experiment_item_failure(
                    experiment=experiment,
                    item=item,
                    run_name=run_name,
                    run_description=f"{config.label} via internal-ax on Modal",
                    run_metadata=metadata,
                    failure_type="environment_not_found",
                    message=error,
                )
            )
        except Exception as trace_error:  # noqa: BLE001
            error = f"{error}; failed to record Langfuse error span: {trace_error!r}"
        lf.flush()
        return RunResult(config.key, item.id, ok=False, trace_ids=trace_ids, error=error)
    except Exception as e:  # noqa: BLE001
        lf.flush()
        tb = traceback.format_exc(limit=8)
        return RunResult(config.key, item.id, ok=False, error=f"{e!r}\n{tb[-1500:]}")
