import os

from openai import OpenAI

client = OpenAI()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def stream_answer(question: str) -> str:
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": question},
        ],
        temperature=0.5,
        max_tokens=400,
        stream=True,
    )

    chunks: list[str] = []
    for event in stream:
        delta = event.choices[0].delta.content or ""
        chunks.append(delta)
        print(delta, end="", flush=True)
    print()
    return "".join(chunks)


if __name__ == "__main__":
    stream_answer("Explain what a file synchronization conflict is in two sentences.")
