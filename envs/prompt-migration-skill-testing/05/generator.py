from openai import OpenAI

client = OpenAI()


def generate_content(user_input: str, content_type: str, audience: str) -> str:
    prompt = (
        "You are a content generation assistant specialized in " + content_type + ".\n"
        + "Your target audience is: " + audience + ".\n"
        + "Guidelines: Be engaging, accurate, and appropriate for the audience.\n\n"
        + f"User request: {user_input}"
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )
    return response.choices[0].message.content


def generate_outline(topic: str, num_sections: int, style: str) -> str:
    outline_prompt = f"""Create a detailed content outline for the following topic.

Topic: {topic}
Number of sections: {num_sections}
Writing style: {style}

For each section, provide a title and 2-3 bullet points of key content to cover.
Ensure logical flow between sections and a strong introduction and conclusion."""

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": outline_prompt}],
        max_tokens=600,
    )
    return response.choices[0].message.content
