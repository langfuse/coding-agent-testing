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


async def arun_agent(
    app, *, prompt: str, env: dict[str, str], setup_cmds: list[str], agent_cmd: str
) -> SandboxResult:
    """Async variant of :func:`run_agent` for use inside an event loop.

    ``dataset.run_experiment`` runs tasks in an asyncio loop; using Modal's blocking
    interfaces there warns and serializes the sandbox calls. Driving the sandbox via
    Modal's ``.aio`` interfaces keeps the loop free so multiple sandbox-based
    experiment items run concurrently (up to the experiment's ``max_concurrency``).
    """
    secrets = [
        modal.Secret.from_name(MODAL_SECRET_NAME),
        modal.Secret.from_dict({**env, "PROMPT": prompt}),
    ]
    sb = await modal.Sandbox.create.aio(
        app=app,
        image=AGENT_IMAGE,
        secrets=secrets,
        timeout=SANDBOX_TIMEOUT_S,
    )
    try:
        for cmd in ["mkdir -p /workspace", *setup_cmds]:
            p = await sb.exec.aio("bash", "-lc", cmd)
            await p.wait.aio()
        proc = await sb.exec.aio("bash", "-lc", f"cd /workspace && {agent_cmd}")
        await proc.wait.aio()
        return SandboxResult(
            stdout=await proc.stdout.read.aio(),
            stderr=await proc.stderr.read.aio(),
            returncode=proc.returncode,
        )
    finally:
        await sb.terminate.aio()
