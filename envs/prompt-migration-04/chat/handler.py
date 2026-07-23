from openai import OpenAI

client = OpenAI()


def handle_chat(user_message: str, username: str, conversation_history: list):
    system_prompt = f"You are a helpful customer support agent for Acme Corp. The user's name is {username}. Be concise, friendly, and always offer to escalate to a human agent if the issue is complex."

    greeting_prompt = f"Generate a short, friendly greeting for {username} who is returning to our support chat. Reference that we're happy to help them again. Keep it under 2 sentences."

    if not conversation_history:
        greeting_response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": greeting_prompt}],
        )
        conversation_history.append({"role": "assistant", "content": greeting_response.choices[0].message.content})

    conversation_history.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "system", "content": system_prompt}] + conversation_history,
    )

    assistant_reply = response.choices[0].message.content
    conversation_history.append({"role": "assistant", "content": assistant_reply})
    return assistant_reply, conversation_history
