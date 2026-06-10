"""Run executors, one per RunType.

Each ``run(...)`` is self-contained: it executes the prompt, produces a Langfuse
trace, links that trace to the dataset item + named run, attaches scores, and
returns a small RunResult summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunResult:
    run_config_key: str
    dataset_item_id: str
    ok: bool
    trace_ids: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_config": self.run_config_key,
            "dataset_item_id": self.dataset_item_id,
            "ok": self.ok,
            "trace_ids": self.trace_ids,
            "scores": self.scores,
            "error": self.error,
        }
