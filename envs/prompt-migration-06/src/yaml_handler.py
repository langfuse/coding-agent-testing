import os
import yaml
from openai import OpenAI

client = OpenAI()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "prompts.yaml")


def load_prompt_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def classify_message(message: str) -> str:
    config = load_prompt_config()
    prompt = config["classifier"]["prompt"].format(message=message)

    response = client.chat.completions.create(
        model=config["classifier"]["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content


def analyze_sentiment(text: str) -> str:
    config = load_prompt_config()
    prompt = config["sentiment"]["prompt"].format(text=text)

    response = client.chat.completions.create(
        model=config["sentiment"]["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content
