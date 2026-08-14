import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

llm = ChatOpenAI(model=MODEL, temperature=0.3)
draft_prompt = ChatPromptTemplate.from_template(
    "You are the AcmeSync support assistant. Draft an answer to:\n\n{question}"
)
draft_chain = draft_prompt | llm | StrOutputParser()

raw_client = OpenAI()


def polish(draft: str) -> str:
    response = raw_client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Rewrite the draft to be friendlier and remove any promises "
                "we can't keep. Return only the improved answer.",
            },
            {"role": "user", "content": draft},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content or ""


def handle(question: str) -> str:
    draft = draft_chain.invoke({"question": question})
    return polish(draft)


if __name__ == "__main__":
    print(handle("How do I share a folder with my teammate?"))
