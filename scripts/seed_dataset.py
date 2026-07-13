"""Create the code-agent test dataset in Langfuse.

One trivial plumbing check plus one realistic branded task that exercises the
env-folder mechanism (a starter workspace copied into the agent's sandbox).

Each item is:
  input.prompt             -> the task handed verbatim to the code agent
  expected_output.contains -> substrings the agent's final answer should contain
  expected_output.tool     -> (optional) tool whose discovery/usage we score
  metadata.env_folder      -> (optional) folder under envs/ loaded into the
                              sandbox's /workspace before the agent starts

    set -a && source .env && set +a
    python scripts/seed_dataset.py
"""

from __future__ import annotations

from langfuse import get_client

DATASET_NAME = "code-agent-dataset"

ITEMS = [
    {
        "input": {
            "prompt": (
                "Write a Python script fizzbuzz.py that prints the numbers 1 to 20, "
                "replacing multiples of 3 with 'Fizz', multiples of 5 with 'Buzz', and "
                "multiples of both with 'FizzBuzz'. Run it and show the output."
            )
        },
        "expected_output": {"contains": ["FizzBuzz", "Fizz", "Buzz", "14"]},
        "metadata": {"category": "starter", "difficulty": "trivial"},
    },
    {
        "input": {
            "prompt": (
                "Instrument this application with Langfuse so that every request to the "
                "/chat endpoint produces one trace containing both LLM calls (the answer "
                "and the topic classification) with model, token usage, and input/output "
                "captured. Use the Langfuse Python SDK; assume LANGFUSE_PUBLIC_KEY, "
                "LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL are provided as environment "
                "variables. Update requirements.txt accordingly. When you are done, "
                "briefly summarize what you changed and why."
            )
        },
        "expected_output": {"contains": ["langfuse"], "tool": "langfuse"},
        "metadata": {
            "category": "branded",
            "task_type": "instrumentation",
            "difficulty": "medium",
            "env_folder": "flask-openai-chat",
        },
    },
]


def main() -> None:
    lf = get_client()
    assert lf.auth_check(), "Langfuse auth_check failed — check LANGFUSE_* env vars"
    lf.create_dataset(
        name=DATASET_NAME,
        description=(
            "internal-ax: realistic tasks executed by code agents (Claude Code, Codex) "
            "on Modal. metadata.env_folder links a starter workspace from the repo's "
            "envs/ directory."
        ),
    )
    for item in ITEMS:
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=item["input"],
            expected_output=item["expected_output"],
            metadata=item["metadata"],
        )
    lf.flush()
    print(f"Seeded dataset '{DATASET_NAME}' with {len(ITEMS)} items.")


if __name__ == "__main__":
    main()
