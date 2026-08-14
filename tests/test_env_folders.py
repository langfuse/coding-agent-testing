from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from internal_ax.config import RunConfig, RunType
from internal_ax.langfuse_helpers import DatasetItem, ExperimentContext
from internal_ax.runners import _sandbox, claude_code, codex


def test_resolve_nested_env_folder(tmp_path: Path, monkeypatch) -> None:
    environment = tmp_path / "prompt-migration-skill-testing" / "01"
    environment.mkdir(parents=True)
    monkeypatch.setattr(_sandbox, "_ENVS_ROOTS", [tmp_path])

    assert (
        _sandbox._resolve_env_folder("prompt-migration-skill-testing/01")
        == environment
    )


@pytest.mark.parametrize(
    "name",
    [
        "../prompt-migration-skill-testing/01",
        "prompt-migration-skill-testing/../01",
        "/prompt-migration-skill-testing/01",
        "prompt migration/01",
        "prompt-migration-skill-testing//01",
    ],
)
def test_resolve_env_folder_rejects_unsafe_nested_paths(
    name: str, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(_sandbox, "_ENVS_ROOTS", [tmp_path])

    with pytest.raises(ValueError, match="invalid env_folder"):
        _sandbox._resolve_env_folder(name)


def test_resolve_env_folder_raises_specific_error_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(_sandbox, "_ENVS_ROOTS", [tmp_path])

    with pytest.raises(_sandbox.EnvironmentNotFoundError, match="not found"):
        _sandbox._resolve_env_folder("missing-environment")


@pytest.mark.parametrize(
    ("runner", "config"),
    [
        (claude_code, RunConfig("claude-code", RunType.CLAUDE_CODE, "Claude Code")),
        (codex, RunConfig("codex", RunType.CODEX, "Codex")),
    ],
)
def test_runner_records_missing_environment_in_langfuse(runner, config: RunConfig) -> None:
    item = DatasetItem(
        id="item-id",
        input={"prompt": "test"},
        expected_output=None,
        metadata={"env_folder": "missing-environment"},
    )
    experiment = ExperimentContext(
        id="experiment-id",
        name="test-run",
        dataset_id="dataset-id",
        description="test",
    )
    missing = _sandbox.EnvironmentNotFoundError("missing environment")

    with (
        patch.object(runner, "run_agent", side_effect=missing),
        patch.object(
            runner.lf,
            "record_experiment_item_failure",
            return_value="1" * 32,
        ) as record_failure,
        patch.object(runner.lf, "flush"),
    ):
        result = runner.run(item, config, "test-run", app=None, experiment=experiment)

    assert not result.ok
    assert result.trace_ids == ["1" * 32]
    assert result.error == "missing environment"
    record_failure.assert_called_once_with(
        experiment=experiment,
        item=item,
        run_name="test-run",
        run_description=f"{config.label} via internal-ax on Modal",
        run_metadata={
            "agent": config.key,
            "harness": "internal-ax",
            "model": "cli-default",
            "execution": "modal",
        },
        failure_type="environment_not_found",
        message="missing environment",
    )
