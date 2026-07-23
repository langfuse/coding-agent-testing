"""Local Docker execution backend matching the Modal agent sandbox."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from internal_ax.config import SANDBOX_TIMEOUT_S
from internal_ax.images import CLAUDE_PLUGIN_REV, CODEX_PLUGIN_REV
from internal_ax.skills import ResolvedSkill

_REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_AGENT_IMAGE = os.environ.get("LOCAL_AGENT_IMAGE", "internal-ax-agent:local")
_PROVIDER_ENV_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def build_local_agent_image(*, force: bool = False) -> str:
    """Build the Docker equivalent of ``AGENT_IMAGE`` when it is absent."""

    if not force:
        inspect = subprocess.run(
            ["docker", "image", "inspect", LOCAL_AGENT_IMAGE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if inspect.returncode == 0:
            return LOCAL_AGENT_IMAGE

    command = [
        "docker",
        "build",
        "--file",
        str(_REPO_ROOT / "docker" / "agent.Dockerfile"),
        "--tag",
        LOCAL_AGENT_IMAGE,
        "--build-arg",
        f"CLAUDE_PLUGIN_REV={CLAUDE_PLUGIN_REV}",
        "--build-arg",
        f"CODEX_PLUGIN_REV={CODEX_PLUGIN_REV}",
        str(_REPO_ROOT),
    ]
    subprocess.run(command, check=True)
    return LOCAL_AGENT_IMAGE


def _copy_workspace(source: Path | None, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if source is None:
        return
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, symlinks=True)
        else:
            shutil.copy2(child, target, follow_symlinks=False)


def run_agent_docker(
    *,
    prompt: str,
    env: dict[str, str],
    setup_cmds: list[str],
    agent_cmd: str,
    collect_files: list[str] | None,
    env_src: Path | None,
    skill: ResolvedSkill | None,
    skill_home: str | None,
):
    """Run one agent in a disposable local Docker container."""

    # Imported lazily to avoid a circular import at module import time.
    from internal_ax.runners._sandbox import SandboxResult

    build_local_agent_image()
    container_name = f"internal-ax-{uuid.uuid4().hex[:12]}"
    with (
        tempfile.TemporaryDirectory(prefix="internal-ax-workspace-") as workspace_tmp,
        tempfile.TemporaryDirectory(prefix="internal-ax-output-") as output_tmp,
    ):
        workspace = Path(workspace_tmp)
        output = Path(output_tmp)
        _copy_workspace(env_src, workspace)

        copy_commands = []
        for index, path in enumerate(collect_files or []):
            copy_commands.append(
                f"cp {shlex.quote(path)} /internal-ax-output/{index} 2>/dev/null || true"
            )
        setup = "\n".join(
            f"({cmd}) || {{ setup_rc=$?; echo 'sandbox setup failed' >&2; exit $setup_rc; }}"
            for cmd in setup_cmds
        )
        script = (
            "set -o pipefail\n"
            "mkdir -p /workspace\n"
            "cd /workspace\n"
            f"{setup}\n"
            f"({agent_cmd})\n"
            "agent_rc=$?\n"
            f"{chr(10).join(copy_commands)}\n"
            "exit $agent_rc\n"
        )

        container_env = {
            **{key: os.environ[key] for key in _PROVIDER_ENV_KEYS if key in os.environ},
            **env,
            "PROMPT": prompt,
        }
        command = [
            "docker",
            "run",
            "--rm",
            "--init",
            "--name",
            container_name,
            "--volume",
            f"{workspace}:/workspace",
            "--volume",
            f"{output}:/internal-ax-output",
        ]
        codex_auth = Path.home() / ".codex" / "auth.json"
        if "OPENAI_API_KEY" not in container_env and codex_auth.is_file():
            command.extend(
                [
                    "--volume",
                    f"{codex_auth}:/root/.codex/auth.json:ro",
                ]
            )
        if skill is not None:
            if not skill_home:
                raise ValueError("skill_home is required when a skill is supplied")
            command.extend(
                [
                    "--volume",
                    f"{skill.root}:{skill_home}/{skill.name}:ro",
                ]
            )
        for key in sorted(container_env):
            command.extend(["--env", key])
        command.extend([LOCAL_AGENT_IMAGE, "bash", "-lc", script])

        process_env = {**os.environ, **container_env}
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env=process_env,
                timeout=SANDBOX_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            raise

        files: dict[str, str] = {}
        for index, path in enumerate(collect_files or []):
            collected = output / str(index)
            files[path] = collected.read_text(errors="replace") if collected.exists() else ""
        return SandboxResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            files=files,
        )
