from openai import OpenAI

client = OpenAI()


def compose_email(recipient_name: str, topic: str, tone: str) -> dict:
    body_prompt = (
        f"Write a professional email to {recipient_name} about {topic}. "
        f"Use a {tone} tone. Include a proper greeting and sign-off. "
        "The email should be concise — no more than 3 short paragraphs."
    )

    subject_prompt = f"Generate a clear, concise email subject line for an email about {topic} to {recipient_name}. Return only the subject line, no quotes."

    subject_response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": subject_prompt}],
        max_tokens=60,
    )

    body_response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": body_prompt}],
        max_tokens=500,
    )

    return {
        "subject": subject_response.choices[0].message.content.strip(),
        "body": body_response.choices[0].message.content.strip(),
        "to": recipient_name,
    }
