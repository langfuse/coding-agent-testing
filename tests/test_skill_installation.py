from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from internal_ax.config import RunConfig, RunType
from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.runners import claude_code, codex
from internal_ax.runners._sandbox import SandboxResult
from internal_ax.skills import ResolvedSkill, SkillRef


@pytest.fixture
def resolved_skill(tmp_path: Path) -> ResolvedSkill:
    (tmp_path / "SKILL.md").write_text(
        "---\nname: example\ndescription: Test skill\n---\n\nInstructions.\n"
    )
    return ResolvedSkill(
        ref=SkillRef(commit="a" * 40, path="runtime-skills/example"),
        name="example",
        digest="sha256:test",
        root=tmp_path,
    )


@pytest.mark.parametrize(
    ("runner", "config", "stdout", "skill_home"),
    [
        (
            claude_code,
            RunConfig("claude-code", RunType.CLAUDE_CODE, "Claude Code"),
            '{"result":"done"}',
            "/root/.claude/skills",
        ),
        (
            codex,
            RunConfig("codex", RunType.CODEX, "Codex"),
            '{"type":"done"}',
            "/root/.agents/skills",
        ),
    ],
)
def test_runner_installs_skill_without_changing_prompt(
    runner,
    config: RunConfig,
    stdout: str,
    skill_home: str,
    resolved_skill: ResolvedSkill,
) -> None:
    item = DatasetItem(
        id="item-1",
        input={"prompt": "Do the original task exactly."},
        expected_output={"contains": []},
        metadata={},
    )
    sandbox_result = SandboxResult(
        stdout=stdout,
        stderr="",
        returncode=0,
        files={"/tmp/codex-last-message.txt": "done"},
    )

    with (
        patch.object(runner, "run_agent", return_value=sandbox_result) as run_agent,
        patch.object(runner.lf, "wait_for_trace", return_value=True),
        patch.object(runner.lf, "annotate_skill_reads", return_value=[]),
        patch.object(runner.lf, "register_native_experiment_item", return_value=None),
        patch.object(runner.lf, "score_trace"),
        patch.object(runner.lf, "link_trace_to_run"),
        patch.object(runner.lf, "flush"),
        patch.object(
            runner.scoring,
            "score_agent_run",
            return_value={"task_completed": {"value": 1.0, "comment": None}},
        ),
    ):
        result = runner.run(
            item,
            config,
            "test-run",
            app=None,
            skill=resolved_skill,
        )

    assert result.ok
    assert run_agent.call_args.kwargs["prompt"] == item.prompt
    assert run_agent.call_args.kwargs["skill"] is resolved_skill
    assert run_agent.call_args.kwargs["skill_home"] == skill_home
    assert "example" not in run_agent.call_args.kwargs["agent_cmd"]
