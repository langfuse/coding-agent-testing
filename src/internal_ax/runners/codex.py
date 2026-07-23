"""OpenAI Codex, headless, in an isolated Modal sandbox.

Tracing uses the official langfuse/codex-observability-plugin (installed via
``codex plugin marketplace add`` and enabled in /root/.codex/config.toml at
image build). LANGFUSE_CODEX_TRACE_SEED makes the turn's trace id
deterministic, so we precompute it; LANGFUSE_CODEX_METADATA / _TAGS annotate
the trace with the dataset item id + run name for context.

Headless notes:
  * ``TRACE_TO_LANGFUSE=true`` is the plugin's opt-in switch (Codex only).
  * ``--dangerously-bypass-hook-trust`` is required headlessly — without it
    Codex silently skips untrusted plugin hooks, i.e. no trace.
  * ``--sandbox danger-full-access`` because Codex's own Landlock sandbox is
    unavailable inside the container; the Modal sandbox is the isolation
    boundary.
  * No ``--ephemeral`` — the plugin reads the persisted rollout file.
  * Auth: ``codex login --with-api-key`` from the OPENAI_API_KEY in the secret.
"""

from __future__ import annotations

import json
import os
import traceback
import uuid

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import RunResult
from internal_ax.runners._sandbox import run_agent
from internal_ax.skills import ResolvedSkill

_LAST_MESSAGE_PATH = "/tmp/codex-last-message.txt"

_CODEX_SETUP = [
    "printenv OPENAI_API_KEY | codex login --with-api-key",
]


def run(
    item: DatasetItem,
    config: RunConfig,
    run_name: str,
    app,
    model: str | None = None,
    *,
    skill: ResolvedSkill | None = None,
    local_docker: bool = False,
) -> RunResult:
    metadata = {"dataset_item_id": item.id, "run_name": run_name, "run_config": config.key}
    if skill:
        metadata.update(skill.metadata())
    # The plugin (>= PR #24) derives main-thread trace ids from
    # LANGFUSE_CODEX_TRACE_SEED as createTraceId(f"{seed}:{turn}"); one
    # `codex exec` prompt is one turn, so the trace id is known upfront.
    trace_seed = str(uuid.uuid4())
    trace_id = lf.deterministic_trace_id(f"{trace_seed}:1")

    env = {
        "TRACE_TO_LANGFUSE": "true",
        "LANGFUSE_CODEX_TRACE_SEED": trace_seed,
        "LANGFUSE_CODEX_METADATA": json.dumps(metadata),
        "LANGFUSE_CODEX_TAGS": json.dumps(["internal-ax", run_name]),
    }
    # Payload-provided model rides in as an env var so it's never shell-interpolated.
    model_flag = ""
    if model:
        env["AGENT_MODEL"] = model
        model_flag = ' --model "$AGENT_MODEL"'

    try:
        setup_cmds = (
            []
            if local_docker and not os.environ.get("OPENAI_API_KEY")
            else _CODEX_SETUP
        )
        res = run_agent(
            app,
            prompt=item.prompt,
            env=env,
            setup_cmds=setup_cmds,
            # < /dev/null: with an open (non-TTY) stdin pipe, codex exec prints
            # "Reading additional input from stdin..." and blocks forever.
            # Codex (>= 0.139 exec mode) never fires plugin Stop hooks, so we
            # invoke the Langfuse tracing hook manually over each rollout the
            # session wrote; the plugin's sidecar files dedupe repeat uploads.
            agent_cmd=(
                f'codex exec "$PROMPT" --json --skip-git-repo-check{model_flag} '
                "--dangerously-bypass-hook-trust --sandbox danger-full-access "
                f"--output-last-message {_LAST_MESSAGE_PATH} < /dev/null; rc=$?; "
                'HOOK=$(find /root/.codex -path "*/tracing*/dist/index.mjs" 2>/dev/null | head -1); '
                'for r in $(find /root/.codex/sessions -name "rollout-*.jsonl" 2>/dev/null | sort); do '
                'printf \'{"transcript_path": "%s"}\' "$r" | node "$HOOK"; '
                "done; exit $rc"
            ),
            collect_files=[_LAST_MESSAGE_PATH],
            env_folder=item.env_folder,
            skill=skill,
            skill_home="/root/.agents/skills",
            local_docker=local_docker,
        )
        output = res.files.get(_LAST_MESSAGE_PATH, "") or res.stdout
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
            run_metadata = {
                "agent": config.key,
                "harness": "internal-ax",
                "model": model or "cli-default",
            }
            if skill:
                run_metadata.update(skill.metadata())
            execution = "local Docker" if local_docker else "Modal"
            run_metadata["execution"] = "local-docker" if local_docker else "modal"
            lf.link_trace_to_run(
                run_name=run_name,
                dataset_item_id=item.id,
                trace_id=tid,
                run_description=f"{config.label} via internal-ax on {execution}",
                metadata=run_metadata,
            )
        lf.flush()

        ok = bool(trace_ids) and res.returncode == 0
        err = None if ok else f"returncode={res.returncode}, traces_found={len(trace_ids)}, stderr={res.stderr[-500:]}"
        return RunResult(config.key, item.id, ok=ok, trace_ids=trace_ids, scores=scores, error=err)
    except Exception as e:  # noqa: BLE001
        lf.flush()
        tb = traceback.format_exc(limit=8)
        return RunResult(config.key, item.id, ok=False, error=f"{e!r}\n{tb[-1500:]}")
