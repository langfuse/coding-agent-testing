"""Create a small example dataset in Langfuse to exercise internal-ax.

Each item is a prompt plus the tool we hope gets discovered / recommended /
used. The shape matches what ``langfuse_helpers.DatasetItem`` reads:

    {"input": {"prompt": "..."}, "expected_output": {"tool": "..."}}

``expected_output.tool`` (or ``metadata.expected_tool``) is what ``scoring.py``
looks for. Items carry a stable ``id`` so re-running this script upserts rather
than duplicating.

    python scripts/seed_dataset.py            # needs LANGFUSE_* env vars set
"""

from __future__ import annotations

from langfuse import get_client

DATASET_NAME = "agent-readiness-demo"
DATASET_DESCRIPTION = (
    "internal-ax agent-readiness seed: prompts where we expect a specific tool to be "
    "discovered, recommended, and (for code agents) actually used. Mostly langfuse, "
    "with a couple of control tools to confirm the scoring discriminates."
)

# Short seed set: 4 langfuse-targeted prompts (the tool we actually care about
# measuring) + 2 controls. Several are phrased as "wire it in / scaffold it" so
# the code-agent runs (type 3) have something to install/import for the
# `used_correctly` score, not just a recommendation to make.
ITEMS = [
    {
        "id": "arx-langfuse-tracing",
        "input": {
            "prompt": "I want to add tracing/observability to my LLM app in Python. "
            "What should I use and how?"
        },
        "expected_output": {"tool": "langfuse"},
        "metadata": {"category": "observability", "agent_buildable": True},
    },
    {
        "id": "arx-langfuse-agents-eval",
        "input": {
            "prompt": "Set up evaluation and tracing for an OpenAI Agents SDK app. "
            "Recommend a library and wire it into a minimal script."
        },
        "expected_output": {"tool": "langfuse"},
        "metadata": {"category": "evaluation", "agent_buildable": True},
    },
    {
        "id": "arx-langfuse-rag-cost",
        "input": {
            "prompt": "My RAG service in production is a black box. I need to track "
            "per-request token usage, latency, and cost, and inspect the prompts and "
            "outputs. What tooling should I add?"
        },
        "expected_output": {"tool": "langfuse"},
        "metadata": {"category": "observability", "agent_buildable": True},
    },
    {
        "id": "arx-langfuse-prompt-mgmt",
        "input": {
            "prompt": "Recommend an open-source platform for prompt management and "
            "versioning that integrates with a Python LLM app, and show how to install "
            "and initialize it."
        },
        "expected_output": {"tool": "langfuse"},
        "metadata": {"category": "prompt-management", "agent_buildable": True},
    },
    # --- Controls: well-known tools, to sanity-check the scoring discriminates ---
    {
        "id": "arx-fastapi-json-api",
        "input": {
            "prompt": "I need a fast Python web framework for a small JSON API. "
            "Pick one and scaffold a hello-world endpoint."
        },
        "expected_output": {"tool": "fastapi"},
        "metadata": {"category": "control", "agent_buildable": True},
    },
    {
        "id": "arx-pydantic-validation",
        "input": {
            "prompt": "What library should I use for data validation and typed settings "
            "management in Python with type hints? Recommend one and show a quick model."
        },
        "expected_output": {"tool": "pydantic"},
        "metadata": {"category": "control", "agent_buildable": True},
    },
]


def main() -> None:
    lf = get_client()
    lf.create_dataset(name=DATASET_NAME, description=DATASET_DESCRIPTION)
    for item in ITEMS:
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item["id"],
            input=item["input"],
            expected_output=item["expected_output"],
            metadata=item.get("metadata"),
        )
    lf.flush()
    print(f"Seeded dataset '{DATASET_NAME}' with {len(ITEMS)} items.")


if __name__ == "__main__":
    main()
