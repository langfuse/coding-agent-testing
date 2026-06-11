"""Shared helper for running a code agent inside a fresh Modal sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field

import modal

from internal_ax.config import MODAL_SECRET_NAME, SANDBOX_TIMEOUT_S
from internal_ax.images import AGENT_IMAGE


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
) -> SandboxResult:
    """Spin up an isolated sandbox, run setup then the agent command, tear down.

    The prompt is passed as the ``$PROMPT`` env var and referenced quoted in the
    command, so its contents are never interpolated into the shell.
    ``collect_files`` are read back (empty string if missing) before teardown.
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
