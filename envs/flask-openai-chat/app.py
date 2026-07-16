"""Support chat API: answers product questions and classifies the conversation."""

import os

from flask import Flask, jsonify, request
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = (
    "You are the support assistant for AcmeSync, a file synchronization product. "
    "Answer briefly and factually. If you don't know, say so and suggest "
    "contacting support@acmesync.example."
)

TOPICS = ["billing", "account", "sync-issues", "feature-request", "other"]


def answer_question(messages: list[dict]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        temperature=0.3,
        max_tokens=400,
    )
    return response.choices[0].message.content or ""


def classify_topic(messages: list[dict]) -> str:
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": f"Classify the support request into exactly one of: {', '.join(TOPICS)}. "
                "Reply with the label only.",
            },
            {"role": "user", "content": last_user},
        ],
        temperature=0,
        max_tokens=10,
    )
    label = (response.choices[0].message.content or "other").strip().lower()
    return label if label in TOPICS else "other"


@app.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    messages = body.get("messages")
    if not messages:
        return jsonify({"error": "messages required"}), 400

    answer = answer_question(messages)
    topic = classify_topic(messages)
    return jsonify({"answer": answer, "topic": topic})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
