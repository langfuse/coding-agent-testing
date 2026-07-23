"""Run dataset items in disposable local Docker containers.

This follows the same runner, tracing, scoring, and dataset-linking path as the
Modal deployment. A commit-pinned skill can be installed in the container, but
the original dataset prompt is passed to the agent unchanged.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from internal_ax.config import RunConfig, RunType, select_run_configs
from internal_ax.langfuse_helpers import (
    ExperimentContext,
    client,
    fetch_dataset,
)
from internal_ax.runners import RunResult
from internal_ax.runners._docker import build_local_agent_image
from internal_ax.skills import ResolvedSkill, SkillRef, resolve_local_git_skill

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _require_environment(run_types: set[RunType]) -> None:
    required = {"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"}
    if RunType.CLAUDE_CODE in run_types:
        required.add("ANTHROPIC_API_KEY")
    codex_auth = Path.home() / ".codex" / "auth.json"
    if RunType.CODEX in run_types and not codex_auth.is_file():
        required.add("OPENAI_API_KEY")
    missing = sorted(key for key in required if not os.environ.get(key))
    if missing:
        raise SystemExit(f"missing required environment variables: {', '.join(missing)}")
    if not client().auth_check():
        raise SystemExit("Langfuse authentication failed; check LANGFUSE_* in .env")


def _run_local(
    item,
    config: RunConfig,
    run_name: str,
    model: str | None,
    skill: ResolvedSkill | None,
    experiment: ExperimentContext,
) -> RunResult:
    if config.run_type == RunType.CLAUDE_CODE:
        from internal_ax.runners import claude_code

        return claude_code.run(
            item,
            config,
            run_name,
            app=None,
            model=model,
            skill=skill,
            experiment=experiment,
            local_docker=True,
        )
    if config.run_type == RunType.CODEX:
        from internal_ax.runners import codex

        return codex.run(
            item,
            config,
            run_name,
            app=None,
            model=model,
            skill=skill,
            experiment=experiment,
            local_docker=True,
        )
    raise ValueError(f"unsupported local run type: {config.run_type}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="code-agent-dataset")
    parser.add_argument(
        "--run-configs",
        nargs="+",
        default=["claude-code", "codex"],
        help="one or both of: claude-code codex",
    )
    parser.add_argument("--run-name")
    parser.add_argument("--skill-commit", help="full commit SHA containing the skill")
    parser.add_argument("--skill-path", help="path below runtime-skills/ at that commit")
    parser.add_argument("--item-id", help="run only this Langfuse dataset item id")
    parser.add_argument("--item-limit", type=int, help="run only the first N selected items")
    parser.add_argument("--claude-model")
    parser.add_argument("--codex-model")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--force-build", action="store_true")
    args = parser.parse_args()

    load_dotenv(_REPO_ROOT / args.env_file)
    configs = select_run_configs(args.run_configs)
    if not configs or {config.key for config in configs} != set(args.run_configs):
        raise SystemExit(f"unknown run config in: {args.run_configs}")
    _require_environment({config.run_type for config in configs})
    if bool(args.skill_commit) != bool(args.skill_path):
        raise SystemExit("--skill-commit and --skill-path must be supplied together")
    skill_ref = (
        SkillRef(commit=args.skill_commit, path=args.skill_path) if args.skill_commit else None
    )

    print(f"Preparing local agent image {build_local_agent_image(force=args.force_build)}")
    dataset_id, items = fetch_dataset(args.dataset)
    if args.item_id:
        items = [item for item in items if item.id == args.item_id]
        if not items:
            raise SystemExit(f"dataset item not found: {args.item_id}")
    if args.item_limit is not None:
        if args.item_limit < 1:
            raise SystemExit("--item-limit must be at least 1")
        items = items[: args.item_limit]

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_run_name = args.run_name or f"{args.dataset}-local-{timestamp}"
    models = {
        "claude-code": args.claude_model,
        "codex": args.codex_model,
    }
    experiments = {
        config.key: ExperimentContext(
            id=str(uuid.uuid4()),
            name=f"{base_run_name}-{config.key}",
            dataset_id=dataset_id,
            description=f"{config.label} via internal-ax on local Docker",
        )
        for config in configs
    }
    skill_context = (
        resolve_local_git_skill(skill_ref, _REPO_ROOT)
        if skill_ref
        else contextlib.nullcontext(None)
    )

    results = []
    with skill_context as skill:
        if skill:
            print(
                f"Installing skill {skill.name} from {skill.ref.commit}:{skill.ref.path} "
                f"({skill.digest})"
            )
        for item in items:
            for config in configs:
                run_name = f"{base_run_name}-{config.key}"
                print(f"Running {config.key} on dataset item {item.id}")
                result = _run_local(
                    item,
                    config,
                    run_name,
                    models[config.key],
                    skill,
                    experiments[config.key],
                )
                results.append(result.as_dict())
                print(json.dumps(result.as_dict(), indent=2))

    summary = {
        "run_name": base_run_name,
        "runs": [f"{base_run_name}-{config.key}" for config in configs],
        "experiment_ids": {
            config.key: experiments[config.key].id for config in configs
        },
        "dataset": args.dataset,
        "units": len(results),
        "ok": sum(bool(result["ok"]) for result in results),
        "failed": sum(not result["ok"] for result in results),
    }
    print(json.dumps(summary, indent=2))
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
