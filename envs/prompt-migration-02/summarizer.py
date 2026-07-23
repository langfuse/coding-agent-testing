import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

DEFAULT_MAX_LENGTH = 500


def summarize_document(
    document_text: str,
    language: str = "English",
    max_length: int = DEFAULT_MAX_LENGTH,
) -> str:
    """Summarize a document using Claude, returning the summary in the specified language."""
    system_prompt = (
        f"You are an expert document summarizer. Produce a clear and concise summary "
        f"in {language}. The summary must not exceed {max_length} words. "
        f"Preserve the key arguments, data points, and conclusions from the original text. "
        f"Use bullet points for multi-part documents and a single paragraph for short ones."
    )

    user_prompt = (
        f"Please summarize the following document:\n\n"
        f"---\n{document_text}\n---\n\n"
        f"Remember: the summary should be in {language} and no longer than {max_length} words."
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.content[0].text


def summarize_batch(documents: list[str], language: str = "English") -> list[str]:
    """Summarize a list of documents."""
    return [summarize_document(doc, language=language) for doc in documents]
