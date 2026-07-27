from openai import OpenAI

client = OpenAI()

VIOLATION_THRESHOLD = 0.85


def moderate_message(message: str, channel_rules: str) -> dict:
    moderation_prompt = (
        f"You are a content moderator. Review the following message against these channel rules:\n\n"
        f"Rules: {channel_rules}\n\n"
        f"Message: {message}\n\n"
        "Respond with a JSON object containing 'allowed' (bool), 'reason' (string), and 'confidence' (float 0-1)."
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a strict but fair content moderator. Always respond in valid JSON."},
            {"role": "user", "content": moderation_prompt},
        ],
        temperature=0.1,
    )

    import json
    result = json.loads(response.choices[0].message.content)
    result["flagged"] = result.get("confidence", 0) >= VIOLATION_THRESHOLD
    return result
