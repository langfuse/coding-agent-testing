"""Resolve a commit-pinned Agent Skill from this repository.

Skills are ordinary directories committed below ``runtime-skills/``. A run
references an exact git commit plus the directory path. Deployed runs fetch the
commit archive from GitHub. The resolved directory is copied into the agent's
normal skill-discovery location before the agent process starts.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import re
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FRONTMATTER_NAME_RE = re.compile(
    r"^---\s*\n(?P<frontmatter>.*?)\n---(?:\s*\n|$)",
    flags=re.DOTALL,
)
SKILL_PATH_ROOT = PurePosixPath("runtime-skills")


@dataclass(frozen=True)
class SkillRef:
    """Immutable reference supplied in the experiment payload."""

    commit: str
    path: str

    def __post_init__(self) -> None:
        if not _COMMIT_RE.fullmatch(self.commit):
            raise ValueError("skill.commit must be a full 40-character git SHA")

        raw = PurePosixPath(self.path)
        if (
            raw.is_absolute()
            or raw.as_posix() != self.path
            or "\\" in self.path
            or "." in raw.parts
            or ".." in raw.parts
        ):
            raise ValueError("skill.path must be a normalized relative path")
        if len(raw.parts) < 2 or raw.parts[0] != SKILL_PATH_ROOT.name:
            raise ValueError(f"skill.path must be below {SKILL_PATH_ROOT}/")
        if any(not part or part.startswith(".") for part in raw.parts):
            raise ValueError("skill.path cannot contain empty or hidden path components")

    @classmethod
    def from_dict(cls, value: object) -> SkillRef | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("skill must be an object with commit and path")
        extra = set(value) - {"commit", "path"}
        if extra:
            raise ValueError(f"unsupported skill fields: {sorted(extra)}")
        return cls(commit=str(value.get("commit", "")), path=str(value.get("path", "")))

    def as_dict(self) -> dict[str, str]:
        return {"commit": self.commit.lower(), "path": self.path}


@dataclass(frozen=True)
class ResolvedSkill:
    """Validated skill materialized in a temporary local directory."""

    ref: SkillRef
    name: str
    digest: str
    root: Path

    def metadata(self) -> dict[str, str]:
        return {
            "skill_name": self.name,
            "skill_commit": self.ref.commit.lower(),
            "skill_path": self.ref.path,
            "skill_digest": self.digest,
        }


def _skill_name(skill_md: Path) -> str:
    import yaml

    text = skill_md.read_text(encoding="utf-8")
    frontmatter = _FRONTMATTER_NAME_RE.match(text)
    if not frontmatter:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    parsed = yaml.safe_load(frontmatter.group("frontmatter"))
    if not isinstance(parsed, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML object")
    name = parsed.get("name")
    description = parsed.get("description")
    if not isinstance(name, str) or not isinstance(description, str) or not description.strip():
        raise ValueError("SKILL.md frontmatter must contain name and description strings")
    if not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid skill name: {name!r}")
    return name


def _validate_and_describe(root: Path, ref: SkillRef) -> ResolvedSkill:
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"{ref.path} at {ref.commit} has no SKILL.md")

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"skill contains a symlink: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"skill contains a non-regular file: {path.relative_to(root)}")
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    return ResolvedSkill(
        ref=ref,
        name=_skill_name(skill_md),
        digest=f"sha256:{digest.hexdigest()}",
        root=root,
    )


def _extract_skill_archive(archive: bytes, ref: SkillRef, destination: Path) -> None:
    """Extract only ``ref.path`` from a git/GitHub tar archive.

    ``git archive`` starts paths at the repository root. GitHub tarballs add one
    generated top-level directory. Both layouts are accepted; links and special
    files are rejected.
    """

    target = PurePosixPath(ref.path).parts
    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tf:
        for member in tf:
            parts = PurePosixPath(member.name).parts
            start = 0 if parts[: len(target)] == target else 1
            if parts[start : start + len(target)] != target:
                continue
            relative_parts = parts[start + len(target) :]
            if not relative_parts:
                continue
            relative = PurePosixPath(*relative_parts)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe path in skill archive: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"skill archive contains a link: {member.name}")
            output = destination.joinpath(*relative.parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"skill archive contains a special file: {member.name}")
            extracted += 1
            source = tf.extractfile(member)
            if source is None:
                raise ValueError(f"could not read skill archive member: {member.name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(source.read())
            output.chmod(member.mode & 0o755 or 0o644)

    if not extracted:
        raise FileNotFoundError(f"{ref.path} not found at commit {ref.commit}")


@contextlib.contextmanager
def resolve_github_skill(ref: SkillRef) -> Iterator[ResolvedSkill]:
    """Fetch a skill at an exact commit from the configured GitHub repository."""

    import httpx

    repository = os.environ.get("SKILL_GITHUB_REPOSITORY", "langfuse/internal-ax")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("SKILL_GITHUB_REPOSITORY must be in owner/repository form")
    token = os.environ.get("SKILL_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repository}/tarball/{ref.commit}"
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        response = client.get(url, headers=headers)
        if response.status_code in {401, 403, 404}:
            raise RuntimeError(
                f"GitHub could not read {repository}@{ref.commit}; configure a valid "
                "SKILL_GITHUB_TOKEN with read-only repository contents access"
            )
        response.raise_for_status()
        archive = response.content

    with tempfile.TemporaryDirectory(prefix="internal-ax-skill-") as tmp:
        root = Path(tmp)
        _extract_skill_archive(archive, ref, root)
        yield _validate_and_describe(root, ref)
