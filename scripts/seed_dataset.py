"""Create a small example dataset in Langfuse to exercise internal-ax.

Each item is a prompt plus the tool we hope gets discovered/recommended/used.

    python scripts/seed_dataset.py            # needs LANGFUSE_* env vars set
"""

from __future__ import annotations

from langfuse import get_client

DATASET_NAME = "agent-readiness-demo"

ITEMS = [
    {
        "input": {"prompt": "I want to add tracing/observability to my LLM app in Python. What should I use and how?"},
        "expected_output": {"tool": "langfuse"},
    },
    {
        "input": {"prompt": "Set up evaluation + tracing for an OpenAI Agents SDK app. Recommend a library and wire it in."},
        "expected_output": {"tool": "langfuse"},
    },
    {
        "input": {"prompt": "I need a fast Python web framework for a small JSON API. Pick one and scaffold a hello-world."},
        "expected_output": {"tool": "fastapi"},
    },
]


def main() -> None:
    lf = get_client()
    lf.create_dataset(name=DATASET_NAME, description="internal-ax agent-readiness demo")
    for item in ITEMS:
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=item["input"],
            expected_output=item["expected_output"],
        )
    lf.flush()
    print(f"Seeded dataset '{DATASET_NAME}' with {len(ITEMS)} items.")


if __name__ == "__main__":
    main()
