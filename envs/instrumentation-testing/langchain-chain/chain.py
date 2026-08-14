import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

llm = ChatOpenAI(model=MODEL, temperature=0.3)

rewrite_prompt = ChatPromptTemplate.from_template(
    "Rewrite the following customer question to be clear and self-contained:\n\n{question}"
)

answer_prompt = ChatPromptTemplate.from_template(
    "You are the AcmeSync support assistant. Answer this question concisely:\n\n{question}"
)

chain = (
    {"question": rewrite_prompt | llm | StrOutputParser()}
    | answer_prompt
    | llm
    | StrOutputParser()
)


def run(question: str) -> str:
    return chain.invoke({"question": question})


if __name__ == "__main__":
    print(run("cant get my stuff to show up on my other laptop whats wrong"))
