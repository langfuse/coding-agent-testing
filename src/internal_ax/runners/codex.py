"""OpenAI Codex, headless, in an isolated Modal sandbox.

Tracing uses the official langfuse/codex-observability-plugin (installed via
``codex plugin marketplace add`` and enabled in /root/.codex/config.toml at
image build). It honours LANGFUSE_CODEX_METADATA / LANGFUSE_CODEX_TAGS, so we
inject the dataset item id + run name and correlate by metadata afterwards.

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

import datetime as dt
import json

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import RunResult
from internal_ax.runners._sandbox import run_agent

_LAST_MESSAGE_PATH = "/tmp/codex-last-message.txt"

_CODEX_SETUP = [
    "printenv OPENAI_API_KEY | codex login --with-api-key",
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
            # < /dev/null: with an open (non-TTY) stdin pipe, codex exec prints
            # "Reading additional input from stdin..." and blocks forever.
            agent_cmd=(
                'codex exec "$PROMPT" --json --skip-git-repo-check '
                "--dangerously-bypass-hook-trust --sandbox danger-full-access "
                f"--output-last-message {_LAST_MESSAGE_PATH} < /dev/null"
            ),
            collect_files=[_LAST_MESSAGE_PATH],
            env_folder=item.env_folder,
        )
        output = res.files.get(_LAST_MESSAGE_PATH, "") or res.stdout
        transcript = res.stdout + "\n" + res.stderr

        trace_ids = lf.find_traces_by_metadata(
            "dataset_item_id", item.id, since=started, retries=10, delay_s=3.0
        )
        scores = scoring.score_agent_run(
            output, transcript, expected_contains=item.expected_contains, expected_tool=item.expected_tool
        )
        for tid in trace_ids:
            for name, value in scores.items():
                lf.score_trace(trace_id=tid, name=name, value=value)
            lf.link_trace_to_run(
                run_name=run_name,
                dataset_item_id=item.id,
                trace_id=tid,
                run_description=f"{config.label} via internal-ax on Modal",
                metadata={"agent": config.key, "harness": "internal-ax"},
            )
        lf.flush()

        ok = bool(trace_ids) and res.returncode == 0
        err = None if ok else f"returncode={res.returncode}, traces_found={len(trace_ids)}, stderr={res.stderr[-500:]}"
        return RunResult(config.key, item.id, ok=ok, trace_ids=trace_ids, scores=scores, error=err)
    except Exception as e:  # noqa: BLE001
        lf.flush()
        return RunResult(config.key, item.id, ok=False, error=repr(e))
