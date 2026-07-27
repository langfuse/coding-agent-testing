from openai import OpenAI

client = OpenAI()

PROMPTS = {
    "summarizer": "You are a document summarizer. Condense the following text into a clear, concise summary that preserves all key points. Keep it under 3 sentences.\n\nText to summarize: {text}",
}

CLASSIFIER_PROMPT = "Classify the following input into one of these categories: {categories}. Respond with only the category name.\n\nInput: {input_text}"


def summarize(text: str) -> str:
    prompt = PROMPTS["summarizer"].format(text=text)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
    )
    return response.choices[0].message.content


def classify(input_text: str, categories: str = "positive, negative, neutral") -> str:
    prompt = CLASSIFIER_PROMPT.format(categories=categories, input_text=input_text)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()
