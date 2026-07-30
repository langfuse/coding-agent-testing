import os
from openai import OpenAI

client = OpenAI()

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def load_system_prompt() -> str:
    with open(os.path.join(PROMPTS_DIR, "system.txt")) as f:
        system_prompt = f.read()
    return system_prompt


def handle_support_ticket(customer_message: str, customer_name: str) -> str:
    system_prompt = load_system_prompt()

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Customer ({customer_name}): {customer_message}"},
        ],
    )

    return response.choices[0].message.content
