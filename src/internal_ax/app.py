"""Modal app: the headless service.

Topology:
  webhook  (web endpoint)  -- receives the Langfuse remote-run POST, authenticates
                              via ?token=, spawns `orchestrate`, returns 2xx fast
                              (Langfuse aborts after 20s).
  orchestrate (function)   -- fetches the dataset, builds the item x run-config
                              matrix, fans out one `run_unit` per cell.
  run_unit (function)      -- executes a single cell (one item x one code agent)
                              inside an isolated Modal Sandbox.

Deploy:  modal deploy -m internal_ax.app
"""

from __future__ import annotations

import datetime as dt
import json
import os

import fastapi
import modal

from internal_ax.config import (
    MODAL_SECRET_NAMES,
    RunType,
    run_config_by_key,
    select_run_configs,
)
from internal_ax.images import ORCHESTRATOR_IMAGE
from internal_ax.langfuse_helpers import DatasetItem, fetch_dataset_items
from internal_ax.skills import ResolvedSkill, SkillRef, resolve_github_skill

app = modal.App("internal-ax")

_SECRETS = [modal.Secret.from_name(n) for n in MODAL_SECRET_NAMES]


def _dispatch(
    item: DatasetItem,
    config,
    run_name: str,
    model: str | None,
    *,
    skill: ResolvedSkill | None = None,
    local_docker: bool = False,
):
    """Route one cell to its runner. Imports are local so cold starts stay light."""
    rt = config.run_type
    if rt == RunType.CLAUDE_CODE:
        from internal_ax.runners import claude_code

        return claude_code.run(
            item, config, run_name, app, model=model, skill=skill, local_docker=local_docker
        )
    if rt == RunType.CODEX:
        from internal_ax.runners import codex

        return codex.run(
            item, config, run_name, app, model=model, skill=skill, local_docker=local_docker
        )
    raise ValueError(f"unknown run type: {rt}")


@app.function(image=ORCHESTRATOR_IMAGE, secrets=_SECRETS, timeout=3600)
def run_unit(unit: dict) -> dict:
    try:
        item = DatasetItem(**unit["item"])
        config = run_config_by_key(unit["config_key"])
        if config is None:
            return {"ok": False, "error": f"unknown run config {unit['config_key']}"}
        skill_ref = SkillRef.from_dict(unit.get("skill"))
        if skill_ref is None:
            return _dispatch(item, config, unit["run_name"], unit.get("model")).as_dict()
        with resolve_github_skill(skill_ref) as skill:
            return _dispatch(
                item, config, unit["run_name"], unit.get("model"), skill=skill
            ).as_dict()
    except Exception as exc:  # noqa: BLE001 — map cells must report, not abort the full run
        return {
            "ok": False,
            "run_config": unit.get("config_key"),
            "dataset_item_id": (unit.get("item") or {}).get("id"),
            "error": f"{type(exc).__name__}: {exc}",
        }


@app.function(image=ORCHESTRATOR_IMAGE, secrets=_SECRETS, timeout=3600)
def orchestrate(payload: dict) -> dict:
    dataset_name = payload["datasetName"]
    cfg = payload.get("payload") or {}  # the user's editable config blob from Langfuse
    if isinstance(cfg, str):  # the Langfuse UI delivers the config as a JSON string
        try:
            cfg = json.loads(cfg) or {}
        except json.JSONDecodeError:
            print(f"ignoring unparseable payload config: {cfg!r}")
            cfg = {}

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_run_name = cfg.get("run_name") or f"{dataset_name}-{ts}"
    run_configs = select_run_configs(cfg.get("run_configs"))
    skill_ref = SkillRef.from_dict(cfg.get("skill"))

    # Wipe agent-created artifacts (datasets/prompts/traces) from the scratch
    # project so earlier runs can't contaminate this one. Payload
    # {"reset_sandbox": false} opts out; hard-guarded to sandbox creds only.
    if cfg.get("reset_sandbox", True):
        from internal_ax.langfuse_helpers import reset_sandbox_project

        print("sandbox reset:", reset_sandbox_project())
    # Optional per-agent model override, e.g. {"claude-code": "opus", "codex": "gpt-5.5-codex"}.
    # Unset -> each CLI's default (currently claude-sonnet-4-6 / gpt-5.5).
    models = cfg.get("models") or {}

    items = fetch_dataset_items(dataset_name)
    # One Langfuse experiment (dataset run) PER agent: "<base>-<config key>",
    # so Claude Code and Codex results stay comparable side by side in the UI.
    units = [
        {
            "item": {
                "id": it.id,
                "input": it.input,
                "expected_output": it.expected_output,
                "metadata": it.metadata,
            },
            "config_key": rc.key,
            "run_name": f"{base_run_name}-{rc.key}",
            "model": models.get(rc.key),
            "skill": skill_ref.as_dict() if skill_ref else None,
        }
        for it in items
        for rc in run_configs
    ]

    results = list(run_unit.map(units))
    for r in results:
        if not r.get("ok"):
            print("unit FAILED:", r)
    summary = {
        "run_name": base_run_name,
        "runs": sorted({u["run_name"] for u in units}),
        "dataset": dataset_name,
        "units": len(units),
        "ok": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
    }
    print("internal-ax run complete:", summary)
    return summary


@app.function(image=ORCHESTRATOR_IMAGE, secrets=_SECRETS, timeout=60)
@modal.fastapi_endpoint(method="POST")
async def webhook(request: fastapi.Request) -> dict:
    """Langfuse remote-run entrypoint.

    Langfuse POSTs {projectId, datasetId, datasetName, payload} with NO signature,
    so we gate on a shared ?token= secret. We accept and return immediately, then
    do the work asynchronously (Langfuse aborts the request after 20s).
    """
    token = request.query_params.get("token")
    if not token or token != os.environ.get("WEBHOOK_SECRET"):
        raise fastapi.HTTPException(status_code=401, detail="unauthorized")

    payload = await request.json()
    if not payload.get("datasetName"):
        raise fastapi.HTTPException(status_code=400, detail="missing datasetName")

    call = orchestrate.spawn(payload)
    return {"status": "accepted", "function_call_id": call.object_id}


@app.local_entrypoint()
def smoke_test(
    dataset: str = "code-agent-dataset",
    run_configs: str = "",
    run_name: str = "",
    skill_commit: str = "",
    skill_path: str = "",
):
    """Validate the full agent path without the webhook:

        modal run -m internal_ax.app --dataset code-agent-dataset
        modal run -m internal_ax.app --run-configs claude-code

    Runs synchronously and prints the summary, so failures surface immediately.
    """
    payload: dict = {"datasetName": dataset, "payload": {}}
    if run_configs:
        payload["payload"]["run_configs"] = [k.strip() for k in run_configs.split(",") if k.strip()]
    if run_name:
        payload["payload"]["run_name"] = run_name
    if bool(skill_commit) != bool(skill_path):
        raise ValueError("skill_commit and skill_path must be supplied together")
    if skill_commit:
        payload["payload"]["skill"] = {"commit": skill_commit, "path": skill_path}
    print(orchestrate.remote(payload))
