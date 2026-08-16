"""Scores attached to each code-agent run's Langfuse trace.

Two layers:
  - task_completed : substring heuristic against expected_output.contains —
                     the stable, deterministic part of the item contract.
  - discovered / recommended / used_correctly : LLM-as-judge (only when the
    item sets expected_output.tool). The old substring heuristics mis-scored
    legitimate variation (e.g. a correct raw REST /api/public/* solution got
    used_correctly=0 because no `pip install`/`import` string appeared) —
    judging the final answer + activity transcript fixes that. The judge
    falls back to the old heuristics on any API failure so a scoring outage
    never fails a run.

Score names are the stable contract the Langfuse UI aggregates on. Each score
is returned as {"value": float, "comment": str|None}.
"""

from __future__ import annotations

import json
import re

JUDGE_MODEL = "claude-opus-4-8"

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "discovered": {
            "type": "boolean",
            "description": "The agent identified/considered the tool at any point",
        },
        "recommended": {
            "type": "boolean",
            "description": "The agent presented the tool as its choice/answer (not just a mention)",
        },
        "used_correctly": {
            "type": "boolean",
            "description": "The agent actually integrated/called the tool (SDK, REST API, "
            "config — any legitimate interface counts) in a way consistent with the "
            "tool's current, non-deprecated usage",
        },
        "reasoning": {"type": "string", "description": "One dense sentence per score"},
    },
    "required": ["discovered", "recommended", "used_correctly", "reasoning"],
    "additionalProperties": False,
}


def score_task_completion(output: str, expected_contains: list[str]) -> dict[str, dict]:
    """Check the agent's final answer for the substrings the item expects."""
    if not expected_contains:
        return {"task_completed": {"value": 1.0 if output.strip() else 0.0, "comment": None}}
    text = output or ""
    hits = [s for s in expected_contains if s.lower() in text.lower()]
    missing = [s for s in expected_contains if s.lower() not in text.lower()]
    return {
        "task_completed": {
            "value": len(hits) / len(expected_contains),
            "comment": f"missing substrings: {missing}" if missing else None,
        }
    }


def score_reference_file(expected_file: str, files_read: list[str]) -> dict[str, dict]:
    """Did the agent open the skill reference file the item expects?

    Evidence is the skill reads detected on the trace (see
    ``langfuse_helpers.detect_skill_reads``), not the final answer — the point
    is which file the skill actually reached for, which an agent frequently
    never names in its output.

    ``expected_file`` is matched on basename, so an item can say
    ``"cli.md"`` without pinning the skill's internal layout. An empty
    ``expected_file`` inverts the check: the item asserts the entrypoint alone
    should suffice, so reading *any* reference file scores 0.
    """
    references = [f for f in files_read if f != "SKILL.md"]
    read_list = ", ".join(references) if references else "none"

    if not expected_file:
        return {
            "reference_file_invoked": {
                "value": 0.0 if references else 1.0,
                "comment": f"expected no reference file; read: {read_list}",
            }
        }

    wanted = expected_file.rsplit("/", 1)[-1]
    hit = any(f.rsplit("/", 1)[-1] == wanted for f in references)
    return {
        "reference_file_invoked": {
            "value": 1.0 if hit else 0.0,
            "comment": None if hit else f"expected {wanted}; read: {read_list}",
        }
    }


def _judge_tool_usage(
    task_prompt: str, output: str, transcript: str, tool: str
) -> dict[str, dict] | None:
    """LLM judge for the tool-readiness scores. Returns None on any failure."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        user_msg = (
            f"Target tool: {tool}\n\n"
            f"## Task given to the coding agent\n{task_prompt[:3000]}\n\n"
            f"## Agent's final answer\n{(output or '(empty)')[:8000]}\n\n"
            f"## Agent activity transcript (may be partial — stdout/stderr only)\n"
            f"{(transcript or '(empty)')[-12000:]}"
        )
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1024,
            system=(
                "You judge whether a coding agent discovered, recommended, and correctly "
                "used a target tool during a task. Judge only from the evidence given. "
                "used_correctly must credit ANY legitimate interface to the tool (SDK, "
                "raw REST API, CLI, config files) as long as the usage is real and "
                "plausibly correct; it must be false if the tool was merely mentioned "
                "but never integrated, or if the usage is clearly broken/hallucinated. "
                "The transcript can be truncated — absence of evidence in the transcript "
                "alone should not override clear evidence in the final answer."
            ),
            output_config={
                "format": {"type": "json_schema", "schema": _JUDGE_SCHEMA}
            },
            messages=[{"role": "user", "content": user_msg}],
        )
        if response.stop_reason == "refusal":
            return None
        text = next(b.text for b in response.content if b.type == "text")
        verdict = json.loads(text)
        comment = f"judge({JUDGE_MODEL}): {verdict['reasoning']}"
        return {
            name: {"value": 1.0 if verdict[name] else 0.0, "comment": comment}
            for name in ("discovered", "recommended", "used_correctly")
        }
    except Exception:  # noqa: BLE001 — judge is best-effort; caller falls back
        return None


def _mentions(text: str, tool: str) -> bool:
    return re.search(rf"\b{re.escape(tool)}\b", text, flags=re.IGNORECASE) is not None


def _heuristic_tool_usage(output: str, transcript: str, tool: str) -> dict[str, dict]:
    """Legacy substring heuristics — fallback when the judge is unavailable."""
    text = (output or "") + "\n" + (transcript or "")
    discovered = 1.0 if _mentions(text, tool) else 0.0
    recommended = 0.0
    if discovered:
        window = re.compile(
            r"(use|try|recommend|install|pick|go with|opt for|reach for)[^.]{0,80}"
            + re.escape(tool),
            flags=re.IGNORECASE,
        )
        recommended = 1.0 if window.search(text) else 0.0
    used = re.search(
        rf"(pip install|npm install|uv add|import|require|from)\s+[^\n]*{re.escape(tool)}",
        text,
        flags=re.IGNORECASE,
    )
    note = "heuristic fallback (judge unavailable)"
    return {
        "discovered": {"value": discovered, "comment": note},
        "recommended": {"value": recommended, "comment": note},
        "used_correctly": {"value": 1.0 if used else 0.0, "comment": note},
    }


def score_agent_run(
    output: str,
    transcript: str,
    *,
    expected_contains: list[str],
    expected_tool: str | None,
    task_prompt: str = "",
) -> dict[str, dict]:
    """All scores for one code-agent run: {name: {value, comment}}."""
    scores = score_task_completion(output, expected_contains)
    if expected_tool:
        judged = _judge_tool_usage(task_prompt, output, transcript, expected_tool)
        scores.update(judged or _heuristic_tool_usage(output, transcript, expected_tool))
    return scores
