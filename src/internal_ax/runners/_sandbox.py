"""Shared helper for running a code agent inside a fresh Modal sandbox."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import modal

from internal_ax.config import MODAL_SECRET_NAMES, SANDBOX_TIMEOUT_S
from internal_ax.images import AGENT_IMAGE
from internal_ax.skills import ResolvedSkill

_LF_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


def _langfuse_env() -> dict[str, str]:
    """Two-project credential split for the sandbox.

    - Plain LANGFUSE_* (what agent task code sees): the SANDBOX_LANGFUSE_*
      scratch project if configured, else the harness project. Keeps the
      agents' own datasets/prompts/test traces out of the harness project.
    - CC_LANGFUSE_* / LANGFUSE_CODEX_*: always the harness project — the
      observability plugins read these (Codex natively prefers the prefix;
      the Claude hook command remaps them in images.py) so execution traces
      keep landing where the dataset runs live.
    """
    harness = {k: os.environ[k] for k in _LF_KEYS if k in os.environ}
    env = {k: os.environ.get(f"SANDBOX_{k}", v) for k, v in harness.items()}
    for k, v in harness.items():
        env[f"CC_{k}"] = v
        env[k.replace("LANGFUSE_", "LANGFUSE_CODEX_")] = v
    return env


# Env folder paths come from dataset item metadata (user-editable in the
# Langfuse UI). Allow nested groups, but keep every path component strict.
_ENV_FOLDER_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:/[A-Za-z0-9][A-Za-z0-9_-]*)*$"
)

# Starter workspaces: /opt/envs inside the orchestrator container (shipped with
# ORCHESTRATOR_IMAGE), the repo's envs/ when running locally.
_ENVS_ROOTS = [Path("/opt/envs"), Path(__file__).resolve().parents[3] / "envs"]


class EnvironmentNotFoundError(FileNotFoundError):
    """A dataset item references an environment unavailable to the runner."""


def _resolve_env_folder(name: str) -> Path:
    if not _ENV_FOLDER_RE.fullmatch(name):
        raise ValueError(f"invalid env_folder name: {name!r}")
    for root in _ENVS_ROOTS:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    raise EnvironmentNotFoundError(
        f"env_folder {name!r} not found under {[str(r) for r in _ENVS_ROOTS]}"
    )


def _upload_dir(sb: modal.Sandbox, src: Path, dest: str) -> None:
    """Copy a local directory tree into the sandbox (parent dirs auto-created)."""
    for p in sorted(src.rglob("*")):
        if p.is_file():
            sb.filesystem.copy_from_local(p, str(Path(dest) / p.relative_to(src)))


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    returncode: int | None
    files: dict[str, str] = field(default_factory=dict)  # path -> contents


def run_agent(
    app,
    *,
    prompt: str,
    env: dict[str, str],
    setup_cmds: list[str],
    agent_cmd: str,
    collect_files: list[str] | None = None,
    env_folder: str | None = None,
    skill: ResolvedSkill | None = None,
    skill_home: str | None = None,
) -> SandboxResult:
    """Spin up an isolated sandbox, run setup then the agent command, tear down.

    The prompt is passed as the ``$PROMPT`` env var and referenced quoted in the
    command, so its contents are never interpolated into the shell.
    ``collect_files`` are read back (empty string if missing) before teardown.
    ``env_folder`` names a starter workspace under the repo's ``envs/``
    directory (shipped with the orchestrator image at /opt/envs); its files are
    uploaded into /workspace so the agent starts inside a realistic project
    instead of an empty directory.
    """
    env_src = _resolve_env_folder(env_folder) if env_folder else None
    if skill is not None and not skill_home:
        raise ValueError("skill_home is required when a skill is supplied")

    secrets = [
        *[modal.Secret.from_name(n) for n in MODAL_SECRET_NAMES],
        # Last wins: the credential split, then per-runner overrides.
        modal.Secret.from_dict({**_langfuse_env(), **env, "PROMPT": prompt}),
    ]
    sb = modal.Sandbox.create(
        app=app,
        image=AGENT_IMAGE,
        secrets=secrets,
        timeout=SANDBOX_TIMEOUT_S,
    )
    try:
        if env_src is not None:
            _upload_dir(sb, env_src, "/workspace")
        if skill is not None:
            sb.exec("mkdir", "-p", f"{skill_home}/{skill.name}").wait()
            _upload_dir(sb, skill.root, f"{skill_home}/{skill.name}")
        for cmd in ["mkdir -p /workspace", *setup_cmds]:
            p = sb.exec("bash", "-lc", cmd)
            p.wait()
            if p.returncode != 0:
                raise RuntimeError(f"sandbox setup failed ({p.returncode}): {cmd}\n{p.stderr.read()}")
        proc = sb.exec("bash", "-lc", f"cd /workspace && {agent_cmd}")
        proc.wait()
        files: dict[str, str] = {}
        for path in collect_files or []:
            cat = sb.exec("bash", "-lc", f"cat {path} 2>/dev/null || true")
            cat.wait()
            files[path] = cat.stdout.read()
        return SandboxResult(
            stdout=proc.stdout.read(),
            stderr=proc.stderr.read(),
            returncode=proc.returncode,
            files=files,
        )
    finally:
        sb.terminate()
