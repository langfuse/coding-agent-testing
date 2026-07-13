"""Shared helper for running a code agent inside a fresh Modal sandbox."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import modal

from internal_ax.config import MODAL_SECRET_NAMES, SANDBOX_TIMEOUT_S
from internal_ax.images import AGENT_IMAGE

# Env folder names come from dataset item metadata (user-editable in the
# Langfuse UI) and are interpolated into a shell command — keep them strict.
_ENV_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


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
    ``env_folder`` names a starter workspace baked into AGENT_IMAGE at
    ``/opt/envs/<name>``; its contents are copied into /workspace so the agent
    starts inside a realistic project instead of an empty directory.
    """
    workspace_cmds = ["mkdir -p /workspace"]
    if env_folder:
        if not _ENV_FOLDER_RE.fullmatch(env_folder):
            raise ValueError(f"invalid env_folder name: {env_folder!r}")
        workspace_cmds.append(
            f"test -d /opt/envs/{env_folder} || {{ echo 'env folder not baked into image: {env_folder}' >&2; exit 1; }}"
        )
        workspace_cmds.append(f"cp -a /opt/envs/{env_folder}/. /workspace/")

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
        for cmd in [*workspace_cmds, *setup_cmds]:
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
