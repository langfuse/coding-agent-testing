"""Nightly summary: asks the model for a one-paragraph digest of open tickets.

Instrumented with Langfuse, but no traces ever show up in the project.
"""

import os

from langfuse import observe, get_client
from openai import OpenAI

client = OpenAI()
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

TICKETS = [
    "Sync stuck at 99% on macOS after sleep",
    "Password reset email never arrives for SSO users",
    "Team plan: audit log export returns 500",
]


@observe(name="nightly-digest")
def build_digest(tickets: list[str]) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Summarize these support tickets into one short paragraph "
                "for the engineering standup.",
            },
            {"role": "user", "content": "\n".join(f"- {t}" for t in tickets)},
        ],
        temperature=0.2,
        max_tokens=200,
    )
    return resp.choices[0].message.content or ""


def main() -> None:
    # Point the SDK at our Langfuse instance.
    os.environ["LANGFUSE_BASE_URL"] = os.environ.get(
        "LANGFUSE_HOST", "https://langfuse.internal.acme.example"
    )
    get_client()
    digest = build_digest(TICKETS)
    print(digest)


if __name__ == "__main__":
    main()
