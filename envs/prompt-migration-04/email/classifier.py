from openai import OpenAI
import json

client = OpenAI()

CATEGORIES = ["billing", "technical_support", "feature_request", "complaint", "general_inquiry"]


def classify_email(email_body: str, sender_domain: str) -> dict:
    classification_prompt = (
        f"Classify the following email into exactly one of these categories: {', '.join(CATEGORIES)}.\n\n"
        f"Sender domain: {sender_domain}\n"
        f"Email body:\n{email_body}\n\n"
        "Respond with JSON: {\"category\": \"...\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\"}"
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an email classifier. Always respond with valid JSON."},
            {"role": "user", "content": classification_prompt},
        ],
        temperature=0.0,
    )

    result = json.loads(response.choices[0].message.content)
    result["sender_domain"] = sender_domain
    return result
