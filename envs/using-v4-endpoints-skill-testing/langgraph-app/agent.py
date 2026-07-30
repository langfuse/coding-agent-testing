"""A tiny LangGraph agent. NOT yet instrumented with Langfuse."""
import os
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.environ.get("OPENAI_API_KEY"))


class State(TypedDict):
    question: str
    answer: str


def answer_node(state: State) -> State:
    resp = llm.invoke(state["question"])
    return {"question": state["question"], "answer": resp.content}


builder = StateGraph(State)
builder.add_node("answer", answer_node)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({"question": "What is Langfuse?"})
    print(result["answer"])
