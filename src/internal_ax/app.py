"""Modal app: the headless service.

Topology:
  webhook (web endpoint)     -- receives the Langfuse remote-run POST, authenticates
                                via ?token=, spawns `orchestrate`, returns 2xx fast
                                (Langfuse aborts after 20s).
  orchestrate (function)     -- one experiment run per selected run-config: spawns a
                                `run_config_experiment` per config and waits for them.
  run_config_experiment (fn) -- runs `dataset.run_experiment(...)` for one config over
                                the whole dataset. Langfuse creates the dataset run,
                                traces each item, links the trace, and attaches the
                                evaluator scores — no manual trace<->run linking.

Deploy:  modal deploy -m internal_ax.app
"""

from __future__ import annotations

import datetime as dt
import os

import modal
from fastapi import Request

from internal_ax.config import MODAL_SECRET_NAME, run_config_by_key, select_run_configs
from internal_ax.images import ORCHESTRATOR_IMAGE

app = modal.App("internal-ax")

_SECRET = modal.Secret.from_name(MODAL_SECRET_NAME)


@app.function(image=ORCHESTRATOR_IMAGE, secrets=[_SECRET], timeout=3600)
def run_config_experiment(dataset_name: str, config_key: str, base_run_name: str) -> dict:
    """Run one run-config as a Langfuse dataset experiment over the whole dataset."""
    from internal_ax import experiments
    from internal_ax.langfuse_helpers import client

    config = run_config_by_key(config_key)
    if config is None:
        return {"ok": False, "config": config_key, "error": f"unknown run config {config_key}"}

    lf = client()
    dataset = lf.get_dataset(dataset_name)
    kwargs = experiments.build_experiment(config, app, base_run_name)
    try:
        dataset.run_experiment(**kwargs)
        lf.flush()
        return {"ok": True, "config": config_key, "run_name": kwargs["run_name"]}
    except Exception as e:  # noqa: BLE001 - surface per-config failures, keep the batch alive
        lf.flush()
        return {"ok": False, "config": config_key, "run_name": kwargs["run_name"], "error": repr(e)}


@app.function(image=ORCHESTRATOR_IMAGE, secrets=[_SECRET], timeout=3600)
def orchestrate(payload: dict) -> dict:
    dataset_name = payload["datasetName"]
    cfg = payload.get("payload") or {}  # the user's editable config blob from Langfuse

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_run_name = cfg.get("run_name") or f"{dataset_name}-{ts}"
    run_configs = select_run_configs(cfg.get("run_configs"))

    # One experiment run per config, fanned out concurrently.
    calls = [
        run_config_experiment.spawn(dataset_name, rc.key, base_run_name) for rc in run_configs
    ]
    results = [c.get() for c in calls]

    summary = {
        "base_run_name": base_run_name,
        "dataset": dataset_name,
        "ok": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "runs": results,
    }
    print("internal-ax run complete:", summary)
    return summary


@app.function(image=ORCHESTRATOR_IMAGE, secrets=[_SECRET], timeout=60)
@modal.fastapi_endpoint(method="POST")
async def webhook(request: Request) -> dict:
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
