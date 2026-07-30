from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from internal_ax import langfuse_helpers as lf
from internal_ax.langfuse_helpers import DatasetItem, ExperimentContext
from internal_ax.skills import ResolvedSkill, SkillRef


def _skill(tmp_path) -> ResolvedSkill:
    (tmp_path / "references").mkdir()
    (tmp_path / "SKILL.md").write_text("skill")
    (tmp_path / "references" / "guide.md").write_text("guide")
    return ResolvedSkill(
        ref=SkillRef(commit="a" * 40, path="runtime-skills/example"),
        name="example",
        digest="sha256:test",
        root=tmp_path,
    )


def test_detect_skill_reads_from_generic_tool_input(tmp_path) -> None:
    skill = _skill(tmp_path)
    observations = [
        SimpleNamespace(
            id="tool-1",
            type="TOOL",
            name="exec_command",
            input={
                "cmd": "sed -n '1,200p' /root/.agents/skills/example/SKILL.md; "
                "cat /root/.agents/skills/example/references/guide.md"
            },
        ),
        SimpleNamespace(
            id="generation-1",
            type="GENERATION",
            name="LLM",
            input="/root/.agents/skills/example/SKILL.md",
        ),
    ]

    detected = lf.detect_skill_reads(observations, skill)

    assert [(source.id, relative) for source, relative in detected] == [
        ("tool-1", "SKILL.md"),
        ("tool-1", "references/guide.md"),
    ]


def test_detect_claude_skill_tool_as_entrypoint_read(tmp_path) -> None:
    skill = _skill(tmp_path)
    observations = [
        SimpleNamespace(
            id="skill-tool",
            type="TOOL",
            name="Tool: Skill",
            input='{"skill": "example"}',
        ),
        SimpleNamespace(
            id="other-skill-tool",
            type="TOOL",
            name="Tool: Skill",
            input={"skill": "unrelated"},
        ),
    ]

    detected = lf.detect_skill_reads(observations, skill)

    assert [(source.id, relative) for source, relative in detected] == [
        ("skill-tool", "SKILL.md"),
    ]


def test_agent_root_does_not_fall_back_to_partial_tool_tree() -> None:
    observations = [
        SimpleNamespace(
            id="tool-1",
            parent_observation_id="generation-not-indexed-yet",
            type="TOOL",
        )
    ]

    assert lf._agent_root_observation_id(observations) is None


def test_claude_conversational_turn_is_an_agent_root() -> None:
    observations = [
        SimpleNamespace(
            id="claude-root",
            name="Conversational Turn",
            parent_observation_id="synthetic-parent",
            type="SPAN",
        )
    ]

    assert lf._agent_root_observation_id(observations) == "claude-root"


class _OtelSpan:
    def __init__(self) -> None:
        self.attributes = {}

    def set_attribute(self, name, value) -> None:
        self.attributes[name] = value


class _Span:
    id = "experiment-span-id"

    def __init__(self) -> None:
        self._otel_span = _OtelSpan()
        self.ended = False

    def end(self) -> None:
        self.ended = True


def test_native_experiment_attributes_are_added_to_agent_trace() -> None:
    span = _Span()
    fake_client = SimpleNamespace(start_observation=lambda **kwargs: span)
    observations = [
        SimpleNamespace(
            id="agent-root",
            parent_observation_id="synthetic-parent",
            type="AGENT",
        )
    ]
    experiment = ExperimentContext(
        id="experiment-id",
        name="native-test-codex",
        dataset_id="dataset-id",
        description="Native test",
    )
    item = DatasetItem(
        id="item-id",
        input={"prompt": "test"},
        expected_output={"answer": "expected"},
        metadata={"case_id": "01"},
    )

    with (
        patch.object(lf, "client", return_value=fake_client),
        patch.object(lf, "_trace_observations", return_value=observations),
    ):
        observation_id = lf.register_native_experiment_item(
            experiment=experiment,
            item=item,
            trace_id="1" * 32,
            output="actual",
            run_metadata={"agent": "codex"},
        )

    assert observation_id == "experiment-span-id"
    assert span.ended
    assert span._otel_span.attributes == {
        "langfuse.experiment.id": "experiment-id",
        "langfuse.experiment.name": "native-test-codex",
        "langfuse.experiment.dataset.id": "dataset-id",
        "langfuse.experiment.description": "Native test",
        "langfuse.environment": "experiment",
        "langfuse.experiment.item.id": "item-id",
        "langfuse.experiment.item.root_observation_id": "experiment-span-id",
        "langfuse.experiment.item.expected_output": '{"answer":"expected"}',
        "langfuse.experiment.metadata.agent": "codex",
        "langfuse.experiment.item.metadata.case_id": "01",
    }


def test_sandbox_reset_uses_api_client_without_registering_langfuse_client(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-harness")
    monkeypatch.setenv("SANDBOX_LANGFUSE_PUBLIC_KEY", "pk-sandbox")
    monkeypatch.setenv("SANDBOX_LANGFUSE_SECRET_KEY", "sk-sandbox")
    monkeypatch.setenv(
        "SANDBOX_LANGFUSE_BASE_URL", "https://sandbox.langfuse.example"
    )
    empty_page = SimpleNamespace(data=[])
    fake_api = SimpleNamespace(
        datasets=SimpleNamespace(list=lambda **kwargs: empty_page),
        prompts=SimpleNamespace(list=lambda **kwargs: empty_page),
        trace=SimpleNamespace(list=lambda **kwargs: empty_page),
    )

    with patch(
        "langfuse.api.client.LangfuseAPI", return_value=fake_api
    ) as api_client:
        stats = lf.reset_sandbox_project()

    assert stats == {
        "dataset_runs": 0,
        "dataset_items": 0,
        "prompts": 0,
        "traces": 0,
        "errors": 0,
    }
    api_client.assert_called_once_with(
        base_url="https://sandbox.langfuse.example",
        username="pk-sandbox",
        password="sk-sandbox",
        x_langfuse_sdk_name="internal-ax",
        x_langfuse_public_key="pk-sandbox",
    )
