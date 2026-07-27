import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

MODEL = "gpt-4o"


def get_chat_response(user_name: str, company: str, user_message: str) -> str:
    """Send a message to the chatbot and return the assistant's reply."""
    system_prompt = (
        f"You are a friendly and professional virtual assistant for {company}. "
        f"You are currently helping {user_name}. Always greet them by name and "
        f"maintain a warm, helpful tone throughout the conversation. "
        f"If you don't know the answer to a question, be honest about it and "
        f"offer to connect them with a human representative from {company}."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=512,
    )
    return response.choices[0].message.content


def main():
    user_name = input("What's your name? ")
    company = os.getenv("COMPANY_NAME", "Acme Corp")
    print(f"Hi {user_name}, welcome to {company} support! Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ")
        if user_input.strip().lower() in ("quit", "exit"):
            print("Goodbye!")
            break
        reply = get_chat_response(user_name, company, user_input)
        print(f"Assistant: {reply}\n")


if __name__ == "__main__":
    main()
