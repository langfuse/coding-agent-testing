"""Scoring for the skill-testing/reference-file-invocation dataset shape.

Items declare which skill reference file the agent should have opened via
``expected_output.invoked_reference_file``; the evidence is the skill reads
detected on the trace, not the agent's prose.
"""

from __future__ import annotations

from internal_ax.langfuse_helpers import DatasetItem
from internal_ax.scoring import score_reference_file


def item(expected_output) -> DatasetItem:
    return DatasetItem(id="i", input={"prompt": "p"}, expected_output=expected_output, metadata={})


def test_expected_reference_file_read_from_item() -> None:
    assert item({"invoked_reference_file": "cli.md"}).expected_reference_file == "cli.md"


def test_empty_string_is_distinct_from_absent() -> None:
    # "" asserts no reference file should be opened; a missing key means the
    # item does not test this at all and the score must be skipped.
    assert item({"invoked_reference_file": ""}).expected_reference_file == ""
    assert item({"contains": ["x"]}).expected_reference_file is None


def test_scores_one_when_expected_file_was_read() -> None:
    scores = score_reference_file("cli.md", ["SKILL.md", "references/cli.md"])
    assert scores["reference_file_invoked"]["value"] == 1.0
    assert scores["reference_file_invoked"]["comment"] is None


def test_scores_zero_when_a_different_file_was_read() -> None:
    scores = score_reference_file("cli.md", ["SKILL.md", "references/ci-cd.md"])
    assert scores["reference_file_invoked"]["value"] == 0.0
    assert "expected cli.md" in scores["reference_file_invoked"]["comment"]
    assert "references/ci-cd.md" in scores["reference_file_invoked"]["comment"]


def test_scores_zero_when_only_the_entrypoint_was_read() -> None:
    scores = score_reference_file("cli.md", ["SKILL.md"])
    assert scores["reference_file_invoked"]["value"] == 0.0
    assert "read: none" in scores["reference_file_invoked"]["comment"]


def test_entrypoint_alone_satisfies_the_empty_expectation() -> None:
    assert score_reference_file("", ["SKILL.md"])["reference_file_invoked"]["value"] == 1.0
    assert score_reference_file("", [])["reference_file_invoked"]["value"] == 1.0


def test_empty_expectation_fails_when_a_reference_was_opened() -> None:
    scores = score_reference_file("", ["SKILL.md", "references/cli.md"])
    assert scores["reference_file_invoked"]["value"] == 0.0


def test_matching_ignores_the_skills_internal_layout() -> None:
    # Items name a bare filename; the skill may nest it anywhere.
    assert score_reference_file(
        "cli.md", ["deep/nested/cli.md"]
    )["reference_file_invoked"]["value"] == 1.0
    # A basename collision in a different directory still counts as a hit;
    # substring matches must not (e.g. "cli.md" vs "old-cli.md").
    assert score_reference_file(
        "cli.md", ["references/old-cli.md"]
    )["reference_file_invoked"]["value"] == 0.0
