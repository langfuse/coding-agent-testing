import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def handle_support_message(product_name: str, conversation_history: list[dict], new_message: str) -> str:
    """Process an incoming customer support message and return the agent's response."""
    system_prompt = (
        f"You are a knowledgeable customer support agent specializing in {product_name}. "
        f"Follow these guidelines:\n"
        f"- Be empathetic and patient with every customer.\n"
        f"- When troubleshooting, walk the customer through steps one at a time.\n"
        f"- If a refund or escalation is needed, collect the order number first.\n"
        f"- Never make promises about timelines you cannot guarantee.\n"
        f"- End each response by asking if there's anything else you can help with."
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.4,
        max_tokens=1024,
    )
    return response.choices[0].message.content
