"""Run type 1: a single model call, no tools. Pure training-knowledge recall.

Uses the Langfuse OpenAI drop-in for both providers:
  * GPT  -> the OpenAI API directly,
  * Claude -> Anthropic's OpenAI-compatible endpoint (one code path, auto-traced).
"""

from __future__ import annotations

import os

from langfuse import propagate_attributes

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import RunResult

SYSTEM = (
    "You are a helpful engineering assistant. Recommend concrete tools/libraries "
    "for the user's task and briefly explain how you'd use them."
)


def _client_for(config: RunConfig):
    # langfuse.openai is a drop-in: importing it auto-traces .chat.completions.create
    from langfuse.openai import OpenAI

    if config.model.startswith("claude"):
        return OpenAI(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url="https://api.anthropic.com/v1/",
        )
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def run(item: DatasetItem, config: RunConfig, run_name: str) -> RunResult:
    client = lf.client()
    try:
        with client.start_as_current_observation(as_type="span", name=config.label):
            with propagate_attributes(
                trace_name=config.label,
                session_id=run_name,
                metadata={"dataset_item_id": item.id, "run_config": config.key},
            ):
                oai = _client_for(config)
                resp = oai.chat.completions.create(
                    model=config.model,
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": item.prompt},
                    ],
                )
                output = resp.choices[0].message.content or ""
            trace_id = client.get_current_trace_id()

        scores = scoring.score_discovery(output, item.expected_tool)
        for name, value in scores.items():
            lf.score_trace(trace_id=trace_id, name=name, value=value)
        lf.link_trace_to_run(
            run_name=run_name, dataset_item_id=item.id, trace_id=trace_id
        )
        lf.flush()
        return RunResult(config.key, item.id, ok=True, trace_ids=[trace_id], scores=scores)
    except Exception as e:  # noqa: BLE001 - surface per-unit failures, keep the batch alive
        lf.flush()
        return RunResult(config.key, item.id, ok=False, error=repr(e))
