"""Shared helper for running a code agent inside a fresh Modal sandbox."""

from __future__ import annotations

from dataclasses import dataclass

import modal

from internal_ax.config import MODAL_SECRET_NAME, SANDBOX_TIMEOUT_S
from internal_ax.images import AGENT_IMAGE


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    returncode: int | None


def run_agent(app, *, prompt: str, env: dict[str, str], setup_cmds: list[str], agent_cmd: str) -> SandboxResult:
    """Spin up an isolated sandbox, run setup then the agent command, tear down.

    The prompt is passed as the ``$PROMPT`` env var and referenced quoted in the
    command, so its contents are never interpolated into the shell.
    """
    secrets = [
        modal.Secret.from_name(MODAL_SECRET_NAME),
        modal.Secret.from_dict({**env, "PROMPT": prompt}),
    ]
    sb = modal.Sandbox.create(
        app=app,
        image=AGENT_IMAGE,
        secrets=secrets,
        timeout=SANDBOX_TIMEOUT_S,
    )
    try:
        for cmd in ["mkdir -p /workspace", *setup_cmds]:
            p = sb.exec("bash", "-lc", cmd)
            p.wait()
        proc = sb.exec("bash", "-lc", f"cd /workspace && {agent_cmd}")
        proc.wait()
        return SandboxResult(
            stdout=proc.stdout.read(),
            stderr=proc.stderr.read(),
            returncode=proc.returncode,
        )
    finally:
        sb.terminate()
