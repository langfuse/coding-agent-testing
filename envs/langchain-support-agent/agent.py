"""Two-step LangChain support agent: classify the request, then answer it."""

import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

llm = ChatOpenAI(model=MODEL, temperature=0.2, max_tokens=400)

classify_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Classify the AcmeSync support request into exactly one of: "
            "billing, account, sync-issues, feature-request, other. "
            "Reply with the label only.",
        ),
        ("user", "{question}"),
    ]
)

answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are the support assistant for AcmeSync, a file synchronization "
            "product. The request was classified as: {topic}. Answer briefly and "
            "factually; escalate to support@acmesync.example if unsure.",
        ),
        ("user", "{question}"),
    ]
)

classify_chain = classify_prompt | llm | StrOutputParser()
answer_chain = answer_prompt | llm | StrOutputParser()


def handle_request(question: str, user_id: str = "anonymous") -> dict:
    topic = classify_chain.invoke({"question": question}).strip().lower()
    answer = answer_chain.invoke({"question": question, "topic": topic})
    return {"topic": topic, "answer": answer}


if __name__ == "__main__":
    print(handle_request("How do I reset my password?", user_id="demo-user"))
