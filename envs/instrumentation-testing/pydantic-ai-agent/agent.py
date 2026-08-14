import os

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

MODEL = os.environ.get("PYDANTIC_AI_MODEL", "openai:gpt-4o-mini")

PLANS = {
    "alice": {"plan": "Pro", "storage_tb": 2, "renews": "2026-09-01"},
    "bob": {"plan": "Free", "storage_tb": 0.005, "renews": None},
}


class BillingAnswer(BaseModel):
    answer: str
    escalate: bool


agent = Agent(
    MODEL,
    output_type=BillingAnswer,
    system_prompt=(
        "You are the AcmeSync billing assistant. Use the get_plan tool to look up "
        "a customer's plan before answering. Set escalate=True if you cannot help."
    ),
)


@agent.tool
def get_plan(ctx: RunContext[None], username: str) -> dict:
    return PLANS.get(username.lower(), {"plan": "unknown"})


if __name__ == "__main__":
    result = agent.run_sync("What plan is alice on and when does it renew?")
    print(result.output)
