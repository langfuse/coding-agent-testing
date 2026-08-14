import os

import instructor
from openai import OpenAI
from pydantic import BaseModel, Field

client = instructor.from_openai(OpenAI())

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


class SupportTicket(BaseModel):
    category: str = Field(description="One of: billing, account, sync-issues, other.")
    priority: str = Field(description="One of: low, medium, high.")
    summary: str = Field(description="A one-line summary of the customer's problem.")


def extract_ticket(message: str) -> SupportTicket:
    return client.chat.completions.create(
        model=MODEL,
        response_model=SupportTicket,
        messages=[{"role": "user", "content": message}],
    )


if __name__ == "__main__":
    ticket = extract_ticket(
        "I was charged twice for my Pro plan this month and my files stopped "
        "syncing on my laptop. Please help urgently!"
    )
    print(ticket.model_dump_json(indent=2))
