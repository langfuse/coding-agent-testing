from openai import OpenAI

client = OpenAI()


def generate_summary(text: str, style: str = "executive") -> str:
    """Generate a summary of the given text in the specified style."""
    summary_prompt = (
        f"Summarize the following text in an {style} style. "
        "An executive summary should be 2-3 sentences highlighting key takeaways. "
        "A detailed summary should be a paragraph covering all main points.\n\n"
        f"Text:\n{text}"
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": summary_prompt}],
        max_tokens=300,
    )
    return response.choices[0].message.content


def truncate_text(text: str, max_length: int = 4000) -> str:
    return text[:max_length] if len(text) > max_length else text
