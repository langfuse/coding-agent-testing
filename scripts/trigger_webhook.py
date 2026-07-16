"""Locally POST a Langfuse-shaped remote-run payload at the webhook.

Reproduces exactly what Langfuse sends ({projectId, datasetId, datasetName,
payload}), so you can exercise the full pipeline without clicking in the UI.

    python scripts/trigger_webhook.py \
        --url "https://<you>--internal-ax-webhook.modal.run?token=$WEBHOOK_SECRET" \
        --dataset code-agent-dataset \
        --run-configs claude-code codex
"""

from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="webhook URL including ?token=...")
    ap.add_argument("--dataset", required=True, help="Langfuse dataset name")
    ap.add_argument("--run-configs", nargs="*", default=None, help="subset of run config keys")
    ap.add_argument("--run-name", default=None)
    args = ap.parse_args()

    inner: dict = {}
    if args.run_configs:
        inner["run_configs"] = args.run_configs
    if args.run_name:
        inner["run_name"] = args.run_name

    body = {
        "projectId": "local-test",
        "datasetId": "local-test",
        "datasetName": args.dataset,
        "payload": inner,
    }
    req = urllib.request.Request(
        args.url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()
