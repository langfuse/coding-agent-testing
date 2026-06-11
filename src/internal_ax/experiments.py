"""Dataset experiments via Langfuse v4 ``dataset.run_experiment``.

Every run-config becomes one Langfuse dataset **experiment run**. We hand
``run_experiment`` a ``task`` (produce the output for a dataset item) and
``evaluators`` (turn that output into agent-readiness scores); Langfuse then
creates the dataset run, traces each task execution, links the trace to the
item, and attaches the evaluator scores. This replaces the previous manual
``dataset_run_items.create`` + ``create_score`` wiring in the per-config runners.

- In-process configs (bare / search): the model call happens inside the task, so
  the Langfuse OpenAI drop-in / OpenInference instrumentation nests the
  generation under the item's experiment trace automatically.
- Claude Code: the agent runs in an isolated Modal sandbox. The experiment item's
  trace captures the prompt + final answer + scores; the sandbox's own detailed
  (plugin-produced) trace is recorded via a ``claude_code_user_id`` on the trace
  so you can pull it up in Langfuse. (`item.run()` was removed in v4.)
"""

from __future__ import annotations

import uuid
from typing import Any

from langfuse import Evaluation, get_client

from internal_ax import scoring
from internal_ax.config import RunConfig, RunType
from internal_ax.langfuse_helpers import run_name_for_config
from internal_ax.runners._sandbox import arun_agent

SEARCH_INSTRUCTIONS = (
    "Search the web as needed, then recommend concrete tools/libraries for the "
    "user's task and explain how to use them."
)


def _prompt(inp: Any) -> str:
    if isinstance(inp, str):
        return inp
    if isinstance(inp, dict):
        return str(inp.get("prompt") or inp.get("question") or inp)
    return str(inp)


def _tool(expected_output: Any, metadata: Any) -> str | None:
    if isinstance(expected_output, str) and expected_output:
        return expected_output
    if isinstance(expected_output, dict) and expected_output.get("tool"):
        return str(expected_output["tool"])
    if isinstance(metadata, dict) and metadata.get("expected_tool"):
        return str(metadata["expected_tool"])
    return None


# --- task functions (signature: task(*, item, **kwargs) -> output) ----------


def _bare_task(config: RunConfig):
    from internal_ax.runners.bare_model import SYSTEM, _client_for

    def task(*, item, **kwargs):
        oai = _client_for(config)
        resp = oai.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _prompt(item.input)},
            ],
            max_tokens=1024,  # required by Anthropic's OpenAI-compatible endpoint
        )
        return resp.choices[0].message.content or ""

    return task


def _search_task(config: RunConfig):
    from internal_ax.runners.search_model import _ensure_instrumented

    # Async: run_experiment executes tasks inside an event loop, so Runner.run_sync
    # would raise "event loop is already running" — use the async Runner.run instead.
    async def task(*, item, **kwargs):
        _ensure_instrumented()
        from agents import Agent, Runner, WebSearchTool

        agent = Agent(
            name="search-recommender",
            model=config.model,
            instructions=SEARCH_INSTRUCTIONS,
            tools=[WebSearchTool()],
        )
        result = await Runner.run(agent, _prompt(item.input))
        return str(getattr(result, "final_output", result))

    return task


def _claude_code_task(app, base_run_name: str):
    from internal_ax.runners.claude_code import _parse_result

    async def task(*, item, **kwargs):
        # Unique per-item user_id so the plugin's sandbox-side trace is discoverable.
        user_id = f"axrun-{base_run_name}-claude-code-{item.id}-{uuid.uuid4().hex[:8]}"[:128]
        res = await arun_agent(
            app,
            prompt=_prompt(item.input),
            env={
                "LANGFUSE_USER_ID": user_id,
                "TRACE_TO_LANGFUSE": "true",
                "IS_SANDBOX": "1",  # allow --dangerously-skip-permissions as root
            },
            setup_cmds=[],
            agent_cmd='claude -p "$PROMPT" --output-format json --dangerously-skip-permissions',
        )
        transcript = (res.stdout or "") + "\n" + (res.stderr or "")
        try:
            get_client().update_current_span(
                metadata={"claude_code_user_id": user_id, "sandbox_returncode": res.returncode}
            )
        except Exception:  # noqa: BLE001 - metadata annotation is best-effort
            pass
        # Return answer + transcript so the evaluator can score actual tool *use*.
        return _parse_result(res.stdout) + "\n\n=== agent transcript ===\n" + transcript

    return task


# --- evaluators (signature: (*, input, output, expected_output, metadata, **kwargs)) ---


def _discovery_evaluator(*, output=None, expected_output=None, metadata=None, **kwargs):
    tool = _tool(expected_output, metadata)
    scores = scoring.score_discovery(output or "", tool)
    return [Evaluation(name=name, value=value) for name, value in scores.items()]


def _agent_evaluator(*, output=None, expected_output=None, metadata=None, **kwargs):
    tool = _tool(expected_output, metadata)
    text = output or ""
    scores = scoring.score_agent_usage(text, text, tool)
    return [Evaluation(name=name, value=value) for name, value in scores.items()]


# --- builder ----------------------------------------------------------------


def build_experiment(config: RunConfig, app, base_run_name: str) -> dict:
    """Kwargs for ``dataset.run_experiment`` / ``client.run_experiment`` for one config."""
    common = {
        "name": f"internal-ax: {config.label}",
        "run_name": run_name_for_config(base_run_name, config.key),
        "description": f"Agent-readiness — {config.label}",
        "metadata": {"run_config": config.key, "batch": base_run_name},
    }
    if config.run_type == RunType.BARE_MODEL:
        return {**common, "task": _bare_task(config), "evaluators": [_discovery_evaluator], "max_concurrency": 20}
    if config.run_type == RunType.SEARCH_MODEL:
        return {**common, "task": _search_task(config), "evaluators": [_discovery_evaluator], "max_concurrency": 8}
    if config.run_type == RunType.CLAUDE_CODE:
        return {**common, "task": _claude_code_task(app, base_run_name), "evaluators": [_agent_evaluator], "max_concurrency": 4}
    raise ValueError(f"no experiment builder for run type {config.run_type}")
