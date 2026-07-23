from openai import OpenAI
from dataclasses import dataclass

client = OpenAI()


@dataclass
class Tool:
    name: str
    description: str


AVAILABLE_TOOLS = [
    Tool("search", "Search the knowledge base"),
    Tool("calculator", "Perform math calculations"),
    Tool("calendar", "Manage calendar events"),
]


def route_request(user_input: str, tools: list[Tool] = AVAILABLE_TOOLS) -> dict:
    system_prompt = f"You are an intelligent request router. You have {len(tools)} tools available: {', '.join(tool.name for tool in tools)}. Analyze the user's request and determine which tool to use. Respond with JSON containing 'tool' and 'reasoning'."

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.0,
    )

    import json
    return json.loads(response.choices[0].message.content)


def build_tool_description(tool: Tool, verbosity: str = "concise") -> str:
    desc_prompt = "Describe the following tool in a {verbosity} manner. Tool name: {name}, base description: {description}. Return only the description text.".format(
        verbosity=verbosity, name=tool.name, description=tool.description
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": desc_prompt}],
        max_tokens=100,
    )
    return response.choices[0].message.content
