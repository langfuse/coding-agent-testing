import os

from litellm import completion

PROMPT = "In one sentence, what is file synchronization?"

CALLS = [
    {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini")},
    {"model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")},
]


def ask(model: str) -> str:
    response = completion(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=0.3,
        max_tokens=100,
    )
    return response["choices"][0]["message"]["content"]


if __name__ == "__main__":
    for call in CALLS:
        print(f"[{call['model']}] {ask(**call)}")
