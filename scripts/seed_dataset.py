"""Create the code-agent test dataset in Langfuse.

Two deliberately simple starter tasks so the Modal + tracing plumbing can be
validated end-to-end; swap in more sophisticated items once the setup works.

Each item is:
  input.prompt             -> the task handed verbatim to the code agent
  expected_output.contains -> substrings the agent's final answer should contain
  expected_output.tool     -> (optional) tool whose discovery/usage we score

    set -a && source .env && set +a
    python scripts/seed_dataset.py
"""

from __future__ import annotations

from langfuse import get_client

DATASET_NAME = "code-agent-readiness"

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
                "Create a file count_words.py with a function count_words(text) that "
                "returns a dict mapping each word to its count (case-insensitive, "
                "ignoring punctuation). Demonstrate it on the sentence "
                "'The quick brown fox jumps over the lazy dog. The dog sleeps.' "
                "and print the result."
            )
        },
        "expected_output": {"contains": ["'the': 3", "'dog': 2"]},
        "metadata": {"category": "starter", "difficulty": "trivial"},
    },
]


def main() -> None:
    lf = get_client()
    assert lf.auth_check(), "Langfuse auth_check failed — check LANGFUSE_* env vars"
    lf.create_dataset(
        name=DATASET_NAME,
        description="internal-ax: tasks executed by code agents (Claude Code, Codex) on Modal",
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
