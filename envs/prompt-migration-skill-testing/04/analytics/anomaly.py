from openai import OpenAI

client = OpenAI()


def describe_anomaly(metric_name: str, expected_value: float, actual_value: float, context: str) -> str:
    deviation_pct = abs(actual_value - expected_value) / expected_value * 100

    anomaly_prompt = (
        f"An anomaly was detected in the metric '{metric_name}'. "
        f"Expected value: {expected_value}, Actual value: {actual_value} "
        f"(deviation: {deviation_pct:.1f}%).\n\n"
        f"Context: {context}\n\n"
        "Write a brief, non-technical explanation of this anomaly suitable for a "
        "product manager. Suggest 2 possible root causes."
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": anomaly_prompt}],
        max_tokens=250,
    )

    return response.choices[0].message.content
