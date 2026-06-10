"""Modal app: the headless service.

Topology:
  webhook  (web endpoint)  -- receives the Langfuse remote-run POST, authenticates
                              via ?token=, spawns `orchestrate`, returns 2xx fast
                              (Langfuse aborts after 20s).
  orchestrate (function)   -- fetches the dataset, builds the item x run-config
                              matrix, fans out one `run_unit` per cell.
  run_unit (function)      -- executes a single cell via the matching runner;
                              for code agents it creates an isolated Sandbox.

Deploy:  modal deploy -m internal_ax.app
"""

from __future__ import annotations

import datetime as dt
import os

import modal

from internal_ax.config import (
    MODAL_SECRET_NAME,
    IN_PROCESS_RUN_TYPES,
    RunType,
    run_config_by_key,
    select_run_configs,
)
from internal_ax.images import ORCHESTRATOR_IMAGE
from internal_ax.langfuse_helpers import DatasetItem, fetch_dataset_items

app = modal.App("internal-ax")

_SECRET = modal.Secret.from_name(MODAL_SECRET_NAME)


def _dispatch(item: DatasetItem, config, run_name: str):
    """Route one cell to its runner. Imports are local so cold starts stay light."""
    rt = config.run_type
    if rt == RunType.BARE_MODEL:
        from internal_ax.runners import bare_model

        return bare_model.run(item, config, run_name)
    if rt == RunType.SEARCH_MODEL:
        from internal_ax.runners import search_model

        return search_model.run(item, config, run_name)
    if rt == RunType.CLAUDE_CODE:
        from internal_ax.runners import claude_code

        return claude_code.run(item, config, run_name, app)
    if rt == RunType.CODEX:
        from internal_ax.runners import codex

        return codex.run(item, config, run_name, app)
    raise ValueError(f"unknown run type: {rt}")


@app.function(image=ORCHESTRATOR_IMAGE, secrets=[_SECRET], timeout=3600)
def run_unit(unit: dict) -> dict:
    item = DatasetItem(**unit["item"])
    config = run_config_by_key(unit["config_key"])
    if config is None:
        return {"ok": False, "error": f"unknown run config {unit['config_key']}"}
    return _dispatch(item, config, unit["run_name"]).as_dict()


@app.function(image=ORCHESTRATOR_IMAGE, secrets=[_SECRET], timeout=3600)
def orchestrate(payload: dict) -> dict:
    dataset_name = payload["datasetName"]
    cfg = payload.get("payload") or {}  # the user's editable config blob from Langfuse

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_name = cfg.get("run_name") or f"{dataset_name}-{ts}"
    run_configs = select_run_configs(cfg.get("run_configs"))

    items = fetch_dataset_items(dataset_name)
    units = [
        {
            "item": {
                "id": it.id,
                "input": it.input,
                "expected_output": it.expected_output,
                "metadata": it.metadata,
            },
            "config_key": rc.key,
            "run_name": run_name,
        }
        for it in items
        for rc in run_configs
    ]

    results = list(run_unit.map(units))
    summary = {
        "run_name": run_name,
        "dataset": dataset_name,
        "units": len(units),
        "ok": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
    }
    print("internal-ax run complete:", summary)
    return summary


@app.function(image=ORCHESTRATOR_IMAGE, secrets=[_SECRET], timeout=60)
@modal.fastapi_endpoint(method="POST")
async def webhook(request) -> dict:
    """Langfuse remote-run entrypoint.

    Langfuse POSTs {projectId, datasetId, datasetName, payload} with NO signature,
    so we gate on a shared ?token= secret. We accept and return immediately, then
    do the work asynchronously (Langfuse aborts the request after 20s).
    """
    from fastapi.responses import JSONResponse

    token = request.query_params.get("token")
    if not token or token != os.environ.get("WEBHOOK_SECRET"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    payload = await request.json()
    if not payload.get("datasetName"):
        return JSONResponse({"error": "missing datasetName"}, status_code=400)

    call = orchestrate.spawn(payload)
    return {"status": "accepted", "function_call_id": call.object_id}
