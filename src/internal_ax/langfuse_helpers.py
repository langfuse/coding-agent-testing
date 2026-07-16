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


# --- Sandbox project reset -------------------------------------------------------
# Agents create datasets/prompts/traces in the scratch project; leftovers from
# earlier runs contaminate later ones (a stale dataset with a different item
# schema crashed a real experiment). Best-effort wipe before each run.


def reset_sandbox_project() -> dict:
    """Delete agent-created artifacts from the SANDBOX Langfuse project.

    Hard guards: only ever uses SANDBOX_LANGFUSE_* credentials, and refuses to
    run if they are missing or identical to the harness project keys — the
    harness project (datasets, runs, execution traces) must never be touched.
    Dataset shells can't be deleted via the API; their items and runs are
    removed, which is what matters for contamination.
    """
    import os

    from langfuse import Langfuse

    pk = os.environ.get("SANDBOX_LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("SANDBOX_LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        return {"skipped": "no sandbox project configured"}
    if pk == os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return {"skipped": "sandbox keys identical to harness keys — refusing to reset"}

    sandbox = Langfuse(
        public_key=pk,
        secret_key=sk,
        host=os.environ.get("SANDBOX_LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        tracing_enabled=False,
    )
    api = sandbox.api
    stats = {"dataset_runs": 0, "dataset_items": 0, "prompts": 0, "traces": 0, "errors": 0}

    def guarded(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            stats["errors"] += 1
            return None

    datasets = guarded(api.datasets.list, limit=100)
    for ds in getattr(datasets, "data", None) or []:
        runs = guarded(api.datasets.get_runs, ds.name)
        for run in getattr(runs, "data", None) or []:
            if guarded(api.datasets.delete_run, ds.name, run.name) is not None:
                stats["dataset_runs"] += 1
        for _ in range(50):  # bounded pagination; re-list after deleting a page
            items = guarded(api.dataset_items.list, dataset_name=ds.name, limit=100)
            data = getattr(items, "data", None) or []
            if not data:
                break
            deleted = sum(
                1 for it in data if guarded(api.dataset_items.delete, it.id) is not None
            )
            stats["dataset_items"] += deleted
            if deleted == 0:  # nothing succeeded — bail instead of spinning
                break

    # prompts.delete via the SDK breaks on names containing "/" (path segment
    # not URL-encoded) — delete via raw HTTP with an encoded name instead.
    import urllib.parse

    import httpx

    base = os.environ.get("SANDBOX_LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/")
    prompts = guarded(api.prompts.list, limit=100)
    for p in getattr(prompts, "data", None) or []:
        enc = urllib.parse.quote(p.name, safe="")
        resp = guarded(httpx.delete, f"{base}/api/public/v2/prompts/{enc}", auth=(pk, sk), timeout=30)
        if resp is not None and resp.status_code < 300:
            stats["prompts"] += 1
        elif resp is not None:
            stats["errors"] += 1

    # Traces delete asynchronously server-side: collect ids first (paged),
    # then fire the deletes once — re-listing after delete would return the
    # same not-yet-processed traces and double-fire.
    trace_ids: list[str] = []
    for page in range(1, 21):  # bounded: up to 20 pages x 100
        traces = guarded(api.trace.list, page=page, limit=100)
        ids = [t.id for t in getattr(traces, "data", None) or []]
        if not ids:
            break
        trace_ids.extend(ids)
    for i in range(0, len(trace_ids), 100):
        if guarded(api.trace.delete_multiple, trace_ids=trace_ids[i : i + 100]) is not None:
            stats["traces"] += len(trace_ids[i : i + 100])

    return stats
