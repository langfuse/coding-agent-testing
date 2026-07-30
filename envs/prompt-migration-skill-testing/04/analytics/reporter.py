import anthropic
import json

client = anthropic.Anthropic()


def generate_insight(metric_name: str, data_summary: str, time_range: str) -> str:
    insight_prompt = (
        f"You are a senior data analyst. Analyze the following metric data and provide "
        f"a clear, actionable insight in 2-3 sentences.\n\n"
        f"Metric: {metric_name}\n"
        f"Time range: {time_range}\n"
        f"Data summary:\n{data_summary}\n\n"
        "Focus on trends, anomalies, and what action the team should take."
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": insight_prompt}],
    )

    return response.content[0].text


def format_report(insights: list[str]) -> str:
    return "\n\n---\n\n".join(insights)
