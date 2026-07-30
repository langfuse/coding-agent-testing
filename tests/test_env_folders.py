from __future__ import annotations

from pathlib import Path

import pytest

from internal_ax.runners import _sandbox


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
