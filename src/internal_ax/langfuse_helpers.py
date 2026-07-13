"""Langfuse v4 helpers: dataset fetch, trace<->dataset-run linking, correlation
queries, and scoring.

All linking goes through ``langfuse.api.dataset_run_items.create(...)`` because
v4 removed the v3 ``dataset_item.run()`` context manager. That single API
accepts an externally-created ``trace_id``, which is exactly what we need for
the code-agent runs (the Langfuse plugin creates the trace inside the sandbox;
we link it after the fact).
"""

from __future__ import annotations

import datetime as dt
import json
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


# --- Correlation: find the trace a sandbox-side plugin created ------------------
# The plugins create their own trace ids, so after a code-agent run we locate the
# trace(s) it emitted and link them. Codex lets us tag traces with metadata; for
# Claude Code we dictate the CLI session id (--session-id) and the plugin sets it
# as the Langfuse session_id.


def _utc(t: dt.datetime) -> dt.datetime:
    """The v4 API client requires a tz-aware datetime (it serializes it itself)."""
    return t.astimezone(dt.timezone.utc)


def find_traces_by_session_id(
    session_id: str, *, since: dt.datetime, retries: int = 10, delay_s: float = 3.0
) -> list[str]:
    """Used for Claude Code: query traces by the per-run session id we chose.

    Plugin export is asynchronous (it flushes on the Stop/SessionEnd hook), so we
    poll for a short window after the run finishes.
    """
    api = client().api
    for _ in range(retries):
        resp = api.trace.list(session_id=session_id, from_timestamp=_utc(since), limit=50)
        ids = [t.id for t in getattr(resp, "data", [])]
        if ids:
            return ids
        time.sleep(delay_s)
    return []


def find_traces_by_user_id(
    user_id: str, *, since: dt.datetime, retries: int = 6, delay_s: float = 2.0
) -> list[str]:
    """Fallback correlation: query traces by a per-run user_id."""
    api = client().api
    for _ in range(retries):
        resp = api.trace.list(user_id=user_id, from_timestamp=_utc(since), limit=50)
        ids = [t.id for t in getattr(resp, "data", [])]
        if ids:
            return ids
        time.sleep(delay_s)
    return []


def find_traces_by_metadata(
    key: str, value: str, *, since: dt.datetime, retries: int = 6, delay_s: float = 2.0
) -> list[str]:
    """Used for Codex: query traces by an injected metadata key/value."""
    api = client().api
    filt = json.dumps([{"column": "metadata", "operator": "=", "key": key, "value": value}])
    for _ in range(retries):
        resp = api.trace.list(filter=filt, from_timestamp=_utc(since), limit=50)
        ids = [t.id for t in getattr(resp, "data", [])]
        if ids:
            return ids
        time.sleep(delay_s)
    return []


def flush() -> None:
    client().flush()
