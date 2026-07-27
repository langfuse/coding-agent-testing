import os
from openai import OpenAI

client = OpenAI()

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "onboarding.md")


def send_onboarding_message(user_name: str, product_name: str) -> str:
    with open(TEMPLATE_PATH) as f:
        template = f.read()

    prompt = template.format(user_name=user_name, product_name=product_name)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a friendly onboarding assistant. Personalize the following welcome message to feel natural and warm, but keep all the information intact."},
            {"role": "user", "content": prompt},
        ],
    )

    return response.choices[0].message.content
