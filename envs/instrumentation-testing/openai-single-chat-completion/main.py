import os

from openai import OpenAI

client = OpenAI()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

ARTICLE = (
    "AcmeSync keeps files in sync across all your devices. Changes made on one "
    "machine appear on the others within seconds, and every version is kept for "
    "30 days so you can roll back mistakes."
)


def summarize(text: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize the text in one sentence."},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=100,
    )
    return response.choices[0].message.content or ""


if __name__ == "__main__":
    print(summarize(ARTICLE))
