from openai import OpenAI

client = OpenAI()


def rewrite_query(original_query: str, search_context: str) -> str:
    rewrite_prompt = (
        f"Rewrite the following search query to improve retrieval results. "
        f"The search is being performed over: {search_context}. "
        f"Original query: {original_query}\n\n"
        "Return only the rewritten query, nothing else. Expand abbreviations, "
        "fix typos, and add relevant synonyms in parentheses."
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": rewrite_prompt}],
        temperature=0.3,
        max_tokens=150,
    )

    rewritten = response.choices[0].message.content.strip()
    if len(rewritten) > 500:
        return original_query
    return rewritten
