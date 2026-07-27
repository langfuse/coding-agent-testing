from openai import OpenAI

client = OpenAI()


def chat_with_assistant(user_message: str, history: list, user_tier: str) -> str:
    messages = [
        {
            "role": "system",
            "content": f"You are a knowledgeable product assistant for TechFlow. You help users with questions about our platform. The user is on the {user_tier} tier, so tailor feature suggestions to their plan. Be helpful but concise. If you don't know something, say so honestly.",
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4",
        messages=messages,
        temperature=0.7,
    )

    return response.choices[0].message.content
