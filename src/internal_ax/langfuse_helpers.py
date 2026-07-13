"""Langfuse v4 helpers: dataset fetch, trace<->dataset-run linking, correlation
queries, and scoring.

All linking goes through ``langfuse.api.dataset_run_items.create(...)`` because
v4 removed the v3 ``dataset_item.run()`` context manager. That single API
accepts an externally-created ``trace_id``, which is exactly what we need for
the code-agent runs (the Langfuse plugin creates the trace inside the sandbox;
we link it after the fact).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from langfuse import get_client


def client():
    """Process-wide Langfuse client (reads LANGFUSE_* env vars)."""
    return get_client()


@dataclass
class DatasetItem:
    id: str
    input: Any
    expected_output: Any
    metadata: dict[str, Any]

    @property
    def prompt(self) -> str:
        """The instruction we feed to the model/agent.

        Accepts either a bare string input or ``{"prompt": "..."}``.
        """
        if isinstance(self.input, str):
            return self.input
        if isinstance(self.input, dict):
            return str(self.input.get("prompt") or self.input.get("question") or self.input)
        return str(self.input)

    @property
    def expected_contains(self) -> list[str]:
        """Substrings the agent's final answer should contain (task completion)."""
        eo = self.expected_output
        if isinstance(eo, dict) and isinstance(eo.get("contains"), list):
            return [str(s) for s in eo["contains"]]
        return []

    @property
    def env_folder(self) -> str | None:
        """Name of a starter workspace under this repo's ``envs/`` directory.

        Set via ``metadata.env_folder``. The folder ships with the orchestrator
        image at ``/opt/envs/<name>`` and is uploaded into the sandbox's
        /workspace before the agent starts, so the prompt can reference "this
        application".
        """
        name = self.metadata.get("env_folder")
        return str(name) if name else None

    @property
    def expected_tool(self) -> str | None:
        """The tool we expect to be discovered/recommended/used.

        Looked up in expected_output (string or {"tool": ...}) then metadata.
        """
        eo = self.expected_output
        if isinstance(eo, str) and eo:
            return eo
        if isinstance(eo, dict) and eo.get("tool"):
            return str(eo["tool"])
        if self.metadata.get("expected_tool"):
            return str(self.metadata["expected_tool"])
        return None


def fetch_dataset_items(dataset_name: str) -> list[DatasetItem]:
    ds = client().get_dataset(dataset_name)
    items: list[DatasetItem] = []
    for it in ds.items:
        items.append(
            DatasetItem(
                id=it.id,
                input=it.input,
                expected_output=getattr(it, "expected_output", None),
                metadata=dict(getattr(it, "metadata", None) or {}),
            )
        )
    return items


def link_trace_to_run(
    *,
    run_name: str,
    dataset_item_id: str,
    trace_id: str,
    run_description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Create the DatasetRunItem that ties a trace to a dataset item + named run."""
    kwargs: dict[str, Any] = {
        "run_name": run_name,
        "dataset_item_id": dataset_item_id,
        "trace_id": trace_id,
    }
    if run_description is not None:
        kwargs["run_description"] = run_description
    if metadata is not None:
        kwargs["metadata"] = metadata
    client().api.dataset_run_items.create(**kwargs)


def score_trace(*, trace_id: str, name: str, value: float | str, comment: str | None = None) -> None:
    """Attach a score to a trace by id (works outside any active span context)."""
    client().create_score(trace_id=trace_id, name=name, value=value, comment=comment)


# --- Correlation ----------------------------------------------------------------
# Both observability plugins support a trace seed (CC_LANGFUSE_TRACE_SEED /
# LANGFUSE_CODEX_TRACE_SEED) and derive the turn-N trace id from it, so the
# runners precompute the id and only confirm the (async) upload landed.


def deterministic_trace_id(seed: str) -> str:
    """The seeded trace id formula shared with the observability plugins:
    Langfuse.create_trace_id(seed) == sha256(seed).hexdigest()[:32]."""
    try:
        from langfuse import Langfuse

        tid = Langfuse.create_trace_id(seed=seed)
        if isinstance(tid, str) and len(tid) == 32:
            return tid
    except Exception:  # noqa: BLE001 — fall through to the equivalent manual formula
        pass
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def wait_for_trace(trace_id: str, *, retries: int = 30, delay_s: float = 3.0) -> bool:
    """Poll until a known trace id is queryable (plugin export is async)."""
    api = client().api
    for _ in range(retries):
        try:
            api.trace.get(trace_id)
            return True
        except Exception:  # noqa: BLE001 — not-found or transient; retry either way
            time.sleep(delay_s)
    return False


def flush() -> None:
    client().flush()
