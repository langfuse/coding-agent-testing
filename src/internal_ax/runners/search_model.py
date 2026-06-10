"""Run type 2: a model with web search + reasoning.

Implemented with the OpenAI Agents SDK + its hosted WebSearchTool, traced via the
OpenInference instrumentation that exports into Langfuse's tracer provider
(Langfuse Python v4 is OpenTelemetry-native, so instrumenting once routes spans
to Langfuse).

NOTE(validate): confirm the OpenInference -> Langfuse v4 tracer-provider wiring
emits a trace in your account; if not, instrument with an explicit
LangfuseSpanProcessor on the global provider. A Claude-with-search variant is a
straightforward addition (Anthropic web_search tool + the same instrumentation).
"""

from __future__ import annotations

from langfuse import propagate_attributes

from internal_ax import langfuse_helpers as lf
from internal_ax import scoring
from internal_ax.config import RunConfig
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import RunResult

_INSTRUMENTED = False


def _ensure_instrumented() -> None:
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return
    # Initialise Langfuse first so its OTel tracer provider is the global one.
    lf.client()
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

    OpenAIAgentsInstrumentor().instrument()
    _INSTRUMENTED = True


def run(item: DatasetItem, config: RunConfig, run_name: str) -> RunResult:
    client = lf.client()
    try:
        _ensure_instrumented()
        from agents import Agent, Runner, WebSearchTool

        agent = Agent(
            name="search-recommender",
            model=config.model,
            instructions=(
                "Search the web as needed, then recommend concrete tools/libraries "
                "for the user's task and explain how to use them."
            ),
            tools=[WebSearchTool()],
        )

        with client.start_as_current_observation(as_type="span", name=config.label):
            with propagate_attributes(
                trace_name=config.label,
                session_id=run_name,
                metadata={"dataset_item_id": item.id, "run_config": config.key},
            ):
                result = Runner.run_sync(agent, item.prompt)
                output = str(getattr(result, "final_output", result))
            trace_id = client.get_current_trace_id()

        scores = scoring.score_discovery(output, item.expected_tool)
        for name, value in scores.items():
            lf.score_trace(trace_id=trace_id, name=name, value=value)
        lf.link_trace_to_run(run_name=run_name, dataset_item_id=item.id, trace_id=trace_id)
        lf.flush()
        return RunResult(config.key, item.id, ok=True, trace_ids=[trace_id], scores=scores)
    except Exception as e:  # noqa: BLE001
        lf.flush()
        return RunResult(config.key, item.id, ok=False, error=repr(e))
