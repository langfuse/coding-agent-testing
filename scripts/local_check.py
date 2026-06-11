"""Run the in-process run configs (types 1 & 2) locally as Langfuse dataset experiments.

Local equivalent of the deployed `orchestrate` for the configs that need no Modal
sandbox: bare-claude / bare-gpt (type 1) and search-gpt (type 2). Each selected
config becomes one `run_experiment(...)` call -> a Langfuse dataset experiment run
with traces linked and scores attached automatically (no manual linking).

The sandbox configs (claude-code) are refused here; validate them via the Modal
deploy path.

Usage (env must hold LANGFUSE_*/OPENAI/ANTHROPIC keys, e.g. `set -a && source .env && set +a`):

    python scripts/local_check.py --dataset agent-readiness-demo --limit 1
    python scripts/local_check.py --dataset agent-readiness-demo --run-configs bare-gpt search-gpt
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from internal_ax import experiments
from internal_ax.config import IN_PROCESS_RUN_TYPES, select_run_configs
from internal_ax.langfuse_helpers import client, run_name_for_config

_DEFAULT_CONFIG_KEYS = ["bare-gpt", "bare-claude", "search-gpt"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="Langfuse dataset name")
    ap.add_argument(
        "--run-configs",
        nargs="*",
        default=None,
        help=f"subset of in-process config keys (default: {' '.join(_DEFAULT_CONFIG_KEYS)})",
    )
    ap.add_argument("--limit", type=int, default=None, help="max dataset items to run")
    ap.add_argument("--run-name", default=None, help="override the generated base run name")
    args = ap.parse_args()

    requested = args.run_configs or _DEFAULT_CONFIG_KEYS
    configs = select_run_configs(requested)
    runnable = [c for c in configs if c.run_type in IN_PROCESS_RUN_TYPES]
    skipped = [c for c in configs if c.run_type not in IN_PROCESS_RUN_TYPES]
    if skipped:
        print(
            "Skipping sandbox configs (run via the Modal deploy path, not locally): "
            + ", ".join(c.key for c in skipped)
        )
    if not runnable:
        print("No in-process run configs selected. Nothing to do.")
        return 2

    lf = client()
    base = args.run_name or f"{args.dataset}-local-{dt.datetime.now(dt.timezone.utc):%Y%m%d-%H%M%S}"
    dataset = lf.get_dataset(args.dataset)
    items = list(dataset.items)
    if not items:
        print(f"Dataset '{args.dataset}' has no items (or was not found).")
        return 2
    if args.limit is not None:
        items = items[: args.limit]

    print(
        f"Dataset '{args.dataset}': {len(items)} item(s) x {len(runnable)} config(s); "
        f"base run name '{base}' (one experiment run per config)\n"
    )

    failed = 0
    for config in runnable:
        kwargs = experiments.build_experiment(config, app=None, base_run_name=base)
        print(f"=== experiment run: {kwargs['run_name']} ===")
        try:
            # client.run_experiment(data=<dataset items>) links to the dataset run by run_name.
            result = lf.run_experiment(data=items, **kwargs)
            print(result.format() if hasattr(result, "format") else result)
        except Exception as e:  # noqa: BLE001 - keep going across configs
            failed += 1
            print(f"  FAILED: {e!r}")
        print()

    lf.flush()
    print("Open the dataset in Langfuse -> Runs to inspect/compare these experiment runs:")
    for config in runnable:
        print("   -", run_name_for_config(base, config.key))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
