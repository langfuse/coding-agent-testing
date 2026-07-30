import anthropic

client = anthropic.Anthropic()


def rank_results(query: str, results: list[dict], top_k: int = 5) -> list[dict]:
    formatted_results = "\n".join(
        f"[{i}] Title: {r['title']}\nSnippet: {r['snippet']}" for i, r in enumerate(results)
    )

    ranking_prompt = (
        f"Given the search query: '{query}'\n\n"
        f"Rank the following {len(results)} results by relevance. "
        f"Return only the indices in order of relevance, comma-separated.\n\n"
        f"{formatted_results}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        messages=[{"role": "user", "content": ranking_prompt}],
    )

    indices = [int(x.strip()) for x in response.content[0].text.split(",")]
    return [results[i] for i in indices[:top_k] if i < len(results)]
