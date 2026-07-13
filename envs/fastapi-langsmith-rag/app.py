"""Docs Q&A API, instrumented with LangSmith."""

import os

from fastapi import FastAPI
from langsmith import traceable
from openai import OpenAI
from pydantic import BaseModel

app = FastAPI(title="AcmeSync Docs Q&A")
client = OpenAI()
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SNIPPETS = [
    "Password reset links expire after 30 minutes.",
    "Sync conflicts keep both copies; the older file gets a '(conflict)' suffix.",
    "Pro plan: 2 TB storage, unlimited devices, 180 days version history.",
    "Selective sync frees local disk space only, not cloud storage.",
]


class Question(BaseModel):
    question: str
    user_id: str = "anonymous"


@traceable(name="retrieve")
def retrieve(question: str) -> list[str]:
    words = set(question.lower().split())
    scored = sorted(SNIPPETS, key=lambda s: -len(words & set(s.lower().split())))
    return scored[:2]


@traceable(name="generate", run_type="llm")
def generate(question: str, context: list[str]) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Answer from the context only.\n\n" + "\n".join(context),
            },
            {"role": "user", "content": question},
        ],
        temperature=0.2,
        max_tokens=300,
    )
    return resp.choices[0].message.content or ""


@traceable(name="docs-qa")
def docs_qa(question: str) -> str:
    return generate(question, retrieve(question))


@app.post("/ask")
def ask(q: Question):
    return {"answer": docs_qa(q.question)}
