from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from internal_ax.skills import (
    SkillRef,
    _extract_skill_archive,
    _validate_and_describe,
    resolve_github_skill,
)


def _archive(files: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        if symlink:
            member = tarfile.TarInfo(symlink)
            member.type = tarfile.SYMTYPE
            member.linkname = "SKILL.md"
            archive.addfile(member)
    return output.getvalue()


def test_skill_ref_requires_full_commit_and_runtime_skills_path() -> None:
    ref = SkillRef(commit="a" * 40, path="runtime-skills/example")
    assert ref.as_dict() == {"commit": "a" * 40, "path": "runtime-skills/example"}

    with pytest.raises(ValueError, match="40-character"):
        SkillRef(commit="abc123", path="runtime-skills/example")
    with pytest.raises(ValueError, match="below runtime-skills"):
        SkillRef(commit="a" * 40, path="skills/example")
    with pytest.raises(ValueError, match="normalized"):
        SkillRef(commit="a" * 40, path="runtime-skills/../example")


def test_extract_github_archive_reads_only_selected_skill(tmp_path: Path) -> None:
    ref = SkillRef(commit="a" * 40, path="runtime-skills/example")
    archive = _archive(
        {
            "repo-sha/runtime-skills/example/SKILL.md": (
                b"---\nname: example\ndescription: Test skill\n---\n\nUse the reference.\n"
            ),
            "repo-sha/runtime-skills/example/references/guide.md": b"original\n",
            "repo-sha/runtime-skills/other/SKILL.md": (
                b"---\nname: other\ndescription: Other skill\n---\n"
            ),
        }
    )

    _extract_skill_archive(archive, ref, tmp_path)
    resolved = _validate_and_describe(tmp_path, ref)

    assert resolved.name == "example"
    assert resolved.digest.startswith("sha256:")
    assert (resolved.root / "references" / "guide.md").read_text() == "original\n"
    assert not (resolved.root / "other").exists()


def test_extract_skill_archive_rejects_symlinks(tmp_path: Path) -> None:
    ref = SkillRef(commit="a" * 40, path="runtime-skills/example")
    archive = _archive(
        {
            "repo-sha/runtime-skills/example/SKILL.md": (
                b"---\nname: example\ndescription: Test skill\n---\n\nInstructions.\n"
            )
        },
        symlink="repo-sha/runtime-skills/example/linked",
    )

    with pytest.raises(ValueError, match="contains a link"):
        _extract_skill_archive(archive, ref, tmp_path)


def test_resolve_github_skill_fetches_exact_commit(monkeypatch) -> None:
    ref = SkillRef(commit="a" * 40, path="runtime-skills/example")
    archive = _archive(
        {
            "repo-sha/runtime-skills/example/SKILL.md": (
                b"---\nname: example\ndescription: Test skill\n---\n\nInstructions.\n"
            )
        }
    )
    requests = []

    class Response:
        status_code = 200
        content = archive

        @staticmethod
        def raise_for_status() -> None:
            return None

    class Client:
        def __init__(self, **kwargs) -> None:
            assert kwargs == {"follow_redirects": True, "timeout": 60}

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, *, headers):
            requests.append((url, headers))
            return Response()

    monkeypatch.setenv("SKILL_GITHUB_REPOSITORY", "langfuse/internal-ax")
    monkeypatch.setenv("SKILL_GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr("httpx.Client", Client)

    with resolve_github_skill(ref) as resolved:
        assert resolved.name == "example"
        assert resolved.ref == ref

    assert requests == [
        (
            f"https://api.github.com/repos/langfuse/internal-ax/tarball/{ref.commit}",
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": "Bearer secret-token",
            },
        )
    ]
