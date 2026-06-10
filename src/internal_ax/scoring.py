"""Heuristics that turn a run's output into agent-readiness scores.

These are deliberately simple (substring / signal matching) so the scaffold runs
end-to-end. Swap in an LLM-as-judge (e.g. a Langfuse evaluator or a small model
call) where you need nuance — the score *names* below are the stable contract
the Langfuse UI aggregates on.

Score names:
  - discovered     : the tool's name appears anywhere in the output
  - recommended    : the tool is presented as the/an answer, not just mentioned
  - used_correctly : (code agents only) the agent actually installed/used it
"""

from __future__ import annotations

import re


def _mentions(text: str, tool: str) -> bool:
    return re.search(rf"\b{re.escape(tool)}\b", text, flags=re.IGNORECASE) is not None


def score_discovery(output: str, expected_tool: str | None) -> dict[str, float]:
    """Scores for run types 1 and 2 (recommendation only)."""
    if not expected_tool:
        return {}
    text = output or ""
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
    return {"discovered": discovered, "recommended": recommended}


def score_agent_usage(
    output: str, transcript: str, expected_tool: str | None
) -> dict[str, float]:
    """Scores for run type 3 (code agents): discovery + actual correct use.

    `transcript` is the agent's tool/command activity (stdout, file diffs, etc.).
    """
    if not expected_tool:
        return {}
    scores = score_discovery(output + "\n" + transcript, expected_tool)
    # Crude "used" signal: the tool name shows up in an install or import/usage
    # command somewhere in the agent's activity. Refine per target tool.
    used = re.search(
        rf"(pip install|npm install|uv add|import|require|from)\s+[^\n]*{re.escape(expected_tool)}",
        transcript,
        flags=re.IGNORECASE,
    )
    scores["used_correctly"] = 1.0 if used else 0.0
    return scores
