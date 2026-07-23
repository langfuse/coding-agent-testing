"""Langfuse dataset, experiment, trace-correlation, and scoring helpers.

The code-agent plugins create detailed traces inside isolated sandboxes. After
each trace lands, the harness adds the native Langfuse experiment attributes to
an experiment-item observation in that same trace. A legacy DatasetRunItem is
also created during the migration period so older dataset views keep working.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from langfuse import get_client
from langfuse._client.attributes import LangfuseOtelSpanAttributes
from opentelemetry import trace as otel_trace_api

from internal_ax.skills import ResolvedSkill


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


@dataclass(frozen=True)
class ExperimentContext:
    """Identity shared by every item in one native Langfuse experiment."""

    id: str
    name: str
    dataset_id: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "dataset_id": self.dataset_id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, value: object) -> ExperimentContext | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("experiment must be an object")
        required = {"id", "name", "dataset_id", "description"}
        if set(value) != required:
            raise ValueError(f"experiment fields must be exactly {sorted(required)}")
        return cls(**{key: str(value[key]) for key in required})


def fetch_dataset(dataset_name: str) -> tuple[str, list[DatasetItem]]:
    """Fetch a hosted dataset's ID and active items."""
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
    return ds.id, items


def fetch_dataset_items(dataset_name: str) -> list[DatasetItem]:
    """Compatibility wrapper for callers that only need dataset items."""
    _, items = fetch_dataset(dataset_name)
    return items


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _set_scalar_attribute(otel_span, name: str, value: Any) -> None:
    if isinstance(value, (str, bool, int, float)):
        otel_span.set_attribute(name, value)


def _datetime_to_ns(value: datetime) -> int:
    """Convert without the sub-millisecond drift of float timestamps."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value.astimezone(timezone.utc) - epoch
    return (
        (delta.days * 86_400 + delta.seconds) * 1_000_000_000
        + delta.microseconds * 1_000
    )


def _trace_observations(trace_id: str) -> list[Any]:
    response = client().api.observations.get_many(
        trace_id=trace_id,
        fields="basic,io,metadata,time",
        limit=1000,
    )
    return list(response.data)


def _agent_root_observation_id(observations: list[Any]) -> str | None:
    """Find the plugin's logical root even when it has a synthetic remote parent."""
    ids = {observation.id for observation in observations}
    candidates = [
        observation
        for observation in observations
        if not observation.parent_observation_id
        or observation.parent_observation_id not in ids
    ]
    agents = [observation for observation in candidates if observation.type == "AGENT"]
    selected = agents[:1]
    return selected[0].id if selected else None


_RUNTIME_SKILL_FILE_RE = re.compile(
    r"/root/\.(?:agents|claude)/skills/"
    r"(?P<skill>[A-Za-z0-9][A-Za-z0-9_-]{0,63})/"
    r"(?P<file>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
)


def detect_skill_reads(observations: list[Any], skill: ResolvedSkill) -> list[tuple[Any, str]]:
    """Detect committed skill files read by generic shell-tool observations."""
    allowed_files = {
        path.relative_to(skill.root).as_posix()
        for path in skill.root.rglob("*")
        if path.is_file()
    }
    detected: list[tuple[Any, str]] = []
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        if observation.type != "TOOL":
            continue
        value = observation.input
        text = value if isinstance(value, str) else _json(value)
        for match in _RUNTIME_SKILL_FILE_RE.finditer(text):
            relative = match.group("file")
            key = (observation.id, relative)
            if (
                match.group("skill") == skill.name
                and relative in allowed_files
                and key not in seen
            ):
                seen.add(key)
                detected.append((observation, relative))
    return detected


def annotate_skill_reads(*, trace_id: str, skill: ResolvedSkill | None) -> list[str]:
    """Add explicit skill-read children at the original tool-call times.

    Agent plugins expose file reads as generic shell tools. These small spans
    make the invocation visible beneath the source tool while retaining its
    original timing and avoiding duplicated skill contents.

    Langfuse's public observation helper does not accept historical start
    times, so this uses its OpenTelemetry tracer directly. The surrounding
    observation creation still goes through Langfuse to retain its normal
    attribute serialization and export behavior.
    """
    if skill is None:
        return []
    observations = _trace_observations(trace_id)

    created: list[str] = []
    for source, relative in detect_skill_reads(observations, skill):
        kind = "entrypoint" if relative == "SKILL.md" else "reference"
        langfuse = client()
        remote_parent = langfuse._create_remote_parent_span(
            trace_id=trace_id,
            parent_span_id=source.id,
        )
        start_time_ns = _datetime_to_ns(source.start_time)
        end_time = source.end_time or source.start_time
        with otel_trace_api.use_span(cast(otel_trace_api.Span, remote_parent)):
            otel_span = langfuse._otel_tracer.start_span(
                name=f"skill.read · {skill.name}/{relative}",
                start_time=start_time_ns,
            )
            otel_span.set_attribute(LangfuseOtelSpanAttributes.AS_ROOT, True)
            span = langfuse._create_observation_from_otel_span(
                otel_span=otel_span,
                as_type="span",
                input={"skill": skill.name, "file": relative, "kind": kind},
                metadata={
                    "derived": True,
                    "source_observation_id": source.id,
                    "source_tool_name": source.name,
                    "skill_name": skill.name,
                    "skill_file": relative,
                    "skill_file_kind": kind,
                },
            )
        span.end(end_time=_datetime_to_ns(end_time))
        created.append(span.id)
    return created


def register_native_experiment_item(
    *,
    experiment: ExperimentContext | None,
    item: DatasetItem,
    trace_id: str,
    output: Any,
    run_metadata: dict[str, Any],
) -> str | None:
    """Attach native experiment attributes to an item root in an agent trace.

    The official code-agent plugins own the detailed trace, so the harness
    cannot establish experiment baggage before those plugin spans start. It
    instead appends one logical experiment-item root to the same trace and sets
    the raw OpenTelemetry attributes documented by Langfuse.
    """
    if experiment is None:
        return None
    observations = _trace_observations(trace_id)
    agent_root_id = _agent_root_observation_id(observations)
    trace_context: dict[str, str] = {"trace_id": trace_id}
    if agent_root_id:
        trace_context["parent_span_id"] = agent_root_id

    span = client().start_observation(
        trace_context=trace_context,
        name="experiment item",
        as_type="span",
        input=item.input,
        output=output,
        metadata={
            "native_experiment": True,
            "agent_root_observation_id": agent_root_id,
            **run_metadata,
        },
    )
    otel_span = span._otel_span
    attributes = {
        "langfuse.experiment.id": experiment.id,
        "langfuse.experiment.name": experiment.name,
        "langfuse.experiment.dataset.id": experiment.dataset_id,
        "langfuse.experiment.description": experiment.description,
        "langfuse.environment": "experiment",
        "langfuse.experiment.item.id": item.id,
        "langfuse.experiment.item.root_observation_id": span.id,
        "langfuse.experiment.item.expected_output": _json(item.expected_output),
    }
    for name, value in attributes.items():
        _set_scalar_attribute(otel_span, name, value)
    for key, value in run_metadata.items():
        _set_scalar_attribute(otel_span, f"langfuse.experiment.metadata.{key}", value)
    for key, value in item.metadata.items():
        _set_scalar_attribute(otel_span, f"langfuse.experiment.item.metadata.{key}", value)
    span.end()
    return span.id


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


def score_trace(
    *,
    trace_id: str,
    name: str,
    value: float | str,
    comment: str | None = None,
) -> None:
    """Attach a score to a trace by id (works outside any active span context)."""
    client().create_score(
        trace_id=trace_id,
        name=name,
        value=value,
        comment=comment,
    )


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
    """Poll until the plugin's completed agent root is queryable.

    A trace can become queryable while its observations are still being
    indexed. Waiting for the ended AGENT root prevents post-processing from
    reading a partial tree and parenting derived observations to an arbitrary
    early tool span.
    """
    api = client().api
    for _ in range(retries):
        try:
            api.trace.get(trace_id)
            observations = _trace_observations(trace_id)
            root_id = _agent_root_observation_id(observations)
            root = next(
                (observation for observation in observations if observation.id == root_id),
                None,
            )
            if root is not None and root.end_time is not None:
                return True
        except Exception:  # noqa: BLE001 — not-found or transient; retry either way
            pass
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
