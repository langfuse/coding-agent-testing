"""Shared helper for running a code agent inside a fresh Modal sandbox."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import modal

from internal_ax.config import MODAL_SECRET_NAMES, SANDBOX_TIMEOUT_S
from internal_ax.images import AGENT_IMAGE

# Env folder names come from dataset item metadata (user-editable in the
# Langfuse UI) and end up in shell commands/paths — keep them strict.
_ENV_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Starter workspaces: /opt/envs inside the orchestrator container (shipped with
# ORCHESTRATOR_IMAGE), the repo's envs/ when running locally.
_ENVS_ROOTS = [Path("/opt/envs"), Path(__file__).resolve().parents[3] / "envs"]


def _resolve_env_folder(name: str) -> Path:
    if not _ENV_FOLDER_RE.fullmatch(name):
        raise ValueError(f"invalid env_folder name: {name!r}")
    for root in _ENVS_ROOTS:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"env_folder {name!r} not found under {[str(r) for r in _ENVS_ROOTS]}")


def _upload_dir(sb: modal.Sandbox, src: Path, dest: str) -> None:
    """Copy a local directory tree into the sandbox via the sandbox FS API."""
    files = [p for p in sorted(src.rglob("*")) if p.is_file()]
    subdirs = {str(Path(dest) / p.parent.relative_to(src)) for p in files}
    mkdir = sb.exec("mkdir", "-p", *sorted(subdirs))
    mkdir.wait()
    if mkdir.returncode != 0:
        raise RuntimeError(f"mkdir for env folder failed: {mkdir.stderr.read()}")
    for p in files:
        with sb.open(str(Path(dest) / p.relative_to(src)), "wb") as fh:
            fh.write(p.read_bytes())


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

    secrets = [
        *[modal.Secret.from_name(n) for n in MODAL_SECRET_NAMES],
        modal.Secret.from_dict({**env, "PROMPT": prompt}),
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
