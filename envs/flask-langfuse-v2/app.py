"""Support chat API, instrumented with Langfuse (SDK v2)."""

import os

from flask import Flask, jsonify, request
from langfuse import Langfuse
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()
langfuse = Langfuse()  # reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = (
    "You are the support assistant for AcmeSync, a file synchronization product. "
    "Answer briefly and factually."
)


@app.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    messages = body.get("messages")
    user_id = body.get("user_id", "anonymous")
    if not messages:
        return jsonify({"error": "messages required"}), 400

    trace = langfuse.trace(
        name="support-chat",
        user_id=user_id,
        input=messages,
        tags=["support"],
    )

    generation = trace.generation(
        name="answer",
        model=MODEL,
        input=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        temperature=0.3,
        max_tokens=400,
    )
    answer = response.choices[0].message.content or ""
    generation.end(
        output=answer,
        usage={
            "input": response.usage.prompt_tokens,
            "output": response.usage.completion_tokens,
        },
    )

    trace.update(output=answer)
    return jsonify({"answer": answer})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
