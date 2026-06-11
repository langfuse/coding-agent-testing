"""Heuristics that turn a code-agent run into scores on its Langfuse trace.

Deliberately simple (substring / signal matching) so the pipeline runs
end-to-end. Swap in an LLM-as-judge (e.g. a Langfuse evaluator) where you need
nuance — the score *names* below are the stable contract the Langfuse UI
aggregates on.

Score names:
  - task_completed : fraction of `expected_output.contains` substrings present
                     in the agent's final answer (1.0 when none are specified
                     and the run succeeded)
  - discovered     : (only when an expected tool is set) the tool's name
                     appears in the agent's answer or activity
  - recommended    : the tool is presented as the/an answer, not just mentioned
  - used_correctly : the agent actually installed/imported/used it
"""

from __future__ import annotations

import re


def score_task_completion(output: str, expected_contains: list[str]) -> dict[str, float]:
    """Check the agent's final answer for the substrings the item expects."""
    if not expected_contains:
        return {"task_completed": 1.0 if output.strip() else 0.0}
    text = output or ""
    hits = sum(1 for s in expected_contains if s.lower() in text.lower())
    return {"task_completed": hits / len(expected_contains)}


def _mentions(text: str, tool: str) -> bool:
    return re.search(rf"\b{re.escape(tool)}\b", text, flags=re.IGNORECASE) is not None


def score_tool_usage(output: str, transcript: str, expected_tool: str | None) -> dict[str, float]:
    """Discovery/recommendation/usage scores for items that target a tool.

    `transcript` is the agent's tool/command activity (stdout, file diffs, etc.).
    """
    if not expected_tool:
        return {}
    text = (output or "") + "\n" + (transcript or "")
    discovered = 1.0 if _mentions(text, expected_tool) else 0.0
    # "Recommended" = mentioned near a recommending verb, a crude proxy.
    recommended = 0.0
    if discovered:
        window = re.compile(
            r"(use|try|recommend|install|pick|go with|opt for|reach for)[^.]{0,80}"
            + re.escape(expected_tool),
            flags=re.IGNORECASE,
        )
        recommended = 1.0 if window.search(text) else 0.0
    # Crude "used" signal: the tool name shows up in an install or import/usage
    # command somewhere in the agent's activity. Refine per target tool.
    used = re.search(
        rf"(pip install|npm install|uv add|import|require|from)\s+[^\n]*{re.escape(expected_tool)}",
        transcript or "",
        flags=re.IGNORECASE,
    )
    return {
        "discovered": discovered,
        "recommended": recommended,
        "used_correctly": 1.0 if used else 0.0,
    }


def score_agent_run(
    output: str, transcript: str, *, expected_contains: list[str], expected_tool: str | None
) -> dict[str, float]:
    """All scores for one code-agent run."""
    scores = score_task_completion(output, expected_contains)
    scores.update(score_tool_usage(output, transcript, expected_tool))
    return scores
