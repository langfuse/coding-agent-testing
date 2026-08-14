import json
import os

from openai import OpenAI

from knowledge_base import DOCS

client = OpenAI()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search the AcmeSync product documentation for relevant passages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "top_k": {"type": "integer", "description": "How many passages to return."},
                },
                "required": ["query"],
            },
        },
    }
]


def search_docs(query: str, top_k: int = 3) -> list[dict]:
    terms = {t.lower() for t in query.split()}
    scored = []
    for doc in DOCS:
        overlap = len(terms & set(doc["text"].lower().split()))
        if overlap:
            scored.append((overlap, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


def answer(question: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "You are the AcmeSync support assistant. Use the search_docs "
            "tool to ground every answer in the documentation.",
        },
        {"role": "user", "content": question},
    ]

    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOLS, temperature=0.2
    )
    message = response.choices[0].message
    messages.append(message)

    for call in message.tool_calls or []:
        args = json.loads(call.function.arguments)
        result = search_docs(**args)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            }
        )

    final = client.chat.completions.create(
        model=MODEL, messages=messages, temperature=0.2
    )
    return final.choices[0].message.content or ""


if __name__ == "__main__":
    print(answer("How long does AcmeSync keep old versions of my files?"))
