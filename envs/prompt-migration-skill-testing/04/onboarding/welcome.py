from openai import OpenAI

client = OpenAI()


def generate_welcome_message(user_name: str, plan_name: str) -> str:
    welcome_prompt = (
        f"Generate a warm, enthusiastic welcome message for {user_name} who just signed up "
        f"for the {plan_name} plan. Mention one key benefit of their plan. "
        "Keep it to 2-3 sentences. Don't use excessive exclamation marks."
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": welcome_prompt}],
        max_tokens=150,
    )
    return response.choices[0].message.content


def generate_tutorial_prompt(feature_name: str, user_experience_level: str) -> str:
    tutorial_prompt = f"Create a brief, step-by-step tutorial introduction for the '{feature_name}' feature. The user is a {user_experience_level} user. Use simple language, and limit to 3-4 steps. Start with what they'll learn."

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": tutorial_prompt}],
        max_tokens=300,
    )
    return response.choices[0].message.content
