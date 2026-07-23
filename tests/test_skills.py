from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from internal_ax.skills import SkillRef, resolve_local_git_skill


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def test_skill_ref_requires_full_commit_and_runtime_skills_path() -> None:
    ref = SkillRef(commit="a" * 40, path="runtime-skills/example")
    assert ref.as_dict() == {"commit": "a" * 40, "path": "runtime-skills/example"}

    with pytest.raises(ValueError, match="40-character"):
        SkillRef(commit="abc123", path="runtime-skills/example")
    with pytest.raises(ValueError, match="below runtime-skills"):
        SkillRef(commit="a" * 40, path="skills/example")
    with pytest.raises(ValueError, match="normalized"):
        SkillRef(commit="a" * 40, path="runtime-skills/../example")


def test_resolve_local_git_skill_reads_exact_committed_tree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    skill = tmp_path / "runtime-skills" / "example"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Test skill\n---\n\nUse the reference.\n"
    )
    (skill / "references" / "guide.md").write_text("original\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "add skill")
    commit = _git(tmp_path, "rev-parse", "HEAD")

    # Uncommitted changes must not leak into a commit-pinned run.
    (skill / "references" / "guide.md").write_text("working-tree change\n")

    ref = SkillRef(commit=commit, path="runtime-skills/example")
    with resolve_local_git_skill(ref, tmp_path) as resolved:
        assert resolved.name == "example"
        assert resolved.file_count == 2
        assert resolved.digest.startswith("sha256:")
        assert (resolved.root / "references" / "guide.md").read_text() == "original\n"


def test_resolve_local_git_skill_rejects_symlinks(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    skill = tmp_path / "runtime-skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Test skill\n---\n\nInstructions.\n"
    )
    (skill / "linked").symlink_to("SKILL.md")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "add linked skill")
    commit = _git(tmp_path, "rev-parse", "HEAD")

    with (
        pytest.raises(ValueError, match="contains a link"),
        resolve_local_git_skill(
            SkillRef(commit=commit, path="runtime-skills/example"), tmp_path
        ),
    ):
        pass
