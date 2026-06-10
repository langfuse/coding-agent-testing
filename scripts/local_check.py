"""Run the in-process run types (1 & 2) locally — no Modal — for quick validation.

Loads .env, checks Langfuse auth, then runs the selected in-process configs
against the first N dataset items, printing trace ids + scores. The code-agent
run types (3a/3b) need Modal sandboxes and are not covered here.

    python scripts/local_check.py --dataset agent-readiness-demo --limit 1
    python scripts/local_check.py --dataset agent-readiness-demo --run-configs bare-gpt
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env before the Langfuse client initialises

from internal_ax.config import RunType, default_run_configs  # noqa: E402
from internal_ax.langfuse_helpers import client, fetch_dataset_items  # noqa: E402
from internal_ax.runners import bare_model, search_model  # noqa: E402

IN_PROCESS = {RunType.BARE_MODEL: bare_model, RunType.SEARCH_MODEL: search_model}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--run-configs", nargs="*", default=None)
    ap.add_argument("--run-name", default="local-check")
    args = ap.parse_args()

    assert client().auth_check(), "Langfuse auth_check failed — check LANGFUSE_* env vars"
    print("Langfuse auth OK")

    items = fetch_dataset_items(args.dataset)[: args.limit]
    configs = [c for c in default_run_configs() if c.run_type in IN_PROCESS]
    if args.run_configs:
        wanted = set(args.run_configs)
        configs = [c for c in configs if c.key in wanted]

    for item in items:
        for cfg in configs:
            res = IN_PROCESS[cfg.run_type].run(item, cfg, args.run_name)
            print(res.as_dict())


if __name__ == "__main__":
    main()
