"""Q&A over the AcmeSync help center articles using retrieval + OpenAI."""

import json
import math
import os
from pathlib import Path

from openai import OpenAI

client = OpenAI()
EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

ARTICLES = [
    {
        "title": "Resetting your password",
        "body": "Go to Settings > Account > Security and click 'Reset password'. A reset "
        "link is emailed to you and expires after 30 minutes. SSO users must reset "
        "through their identity provider instead.",
    },
    {
        "title": "Sync conflicts",
        "body": "When two devices edit the same file offline, AcmeSync keeps both copies. "
        "The newer file keeps the original name; the older one is renamed with a "
        "'(conflict)' suffix. Conflicts older than 90 days are archived.",
    },
    {
        "title": "Pricing and plans",
        "body": "Free plan: 5 GB and 2 devices. Pro ($8/month): 2 TB, unlimited devices, "
        "version history for 180 days. Team ($15/user/month): everything in Pro plus "
        "admin controls, SSO, and audit logs.",
    },
    {
        "title": "Selective sync",
        "body": "To exclude folders from a device, open Preferences > Sync > Selective "
        "Sync and uncheck them. Excluded folders stay in the cloud and on other "
        "devices. This does not free cloud storage, only local disk space.",
    },
]


def _embed(texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb)


_article_embeddings: list[list[float]] | None = None


def retrieve(question: str, k: int = 2) -> list[dict]:
    global _article_embeddings
    if _article_embeddings is None:
        _article_embeddings = _embed([a["body"] for a in ARTICLES])
    q = _embed([question])[0]
    ranked = sorted(
        zip(ARTICLES, _article_embeddings), key=lambda p: _cosine(q, p[1]), reverse=True
    )
    return [a for a, _ in ranked[:k]]


def answer(question: str) -> str:
    context = "\n\n".join(f"# {a['title']}\n{a['body']}" for a in retrieve(question))
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Answer the user's question using ONLY the provided help "
                "articles. If the articles don't cover it, say so.\n\n" + context,
            },
            {"role": "user", "content": question},
        ],
        temperature=0.2,
        max_tokens=300,
    )
    return resp.choices[0].message.content or ""


if __name__ == "__main__":
    questions = json.loads(Path(__file__).with_name("eval_questions.json").read_text())
    for item in questions[:2]:
        print("Q:", item["question"])
        print("A:", answer(item["question"]))
        print()
