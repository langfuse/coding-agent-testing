"""A small FastAPI chat service that calls an LLM. NOT yet instrumented with Langfuse."""
import os

from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel

app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
def chat(req: ChatRequest):
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful support assistant."},
            {"role": "user", "content": req.message},
        ],
    )
    return {"reply": completion.choices[0].message.content}


@app.get("/health")
def health():
    return {"status": "ok"}
