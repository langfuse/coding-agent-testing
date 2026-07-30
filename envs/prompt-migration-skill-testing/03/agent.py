import os
from dataclasses import dataclass
from jinja2 import Template
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


@dataclass
class User:
    name: str
    is_premium: bool
    account_id: str


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict


SYSTEM_PROMPT_TEMPLATE = Template("""You are an AI assistant called Nova, helping {{ user.name }}.

{% if user.is_premium %}
You have access to advanced capabilities for this premium user:
- Provide detailed, in-depth analysis when asked.
- Offer proactive suggestions based on their history.
- You may run multi-step tasks autonomously without asking for confirmation at each step.
{% else %}
You are in standard mode:
- Keep responses concise and focused.
- Always ask for confirmation before executing multi-step tasks.
- If the user asks about premium features, briefly explain the upgrade path.
{% endif %}

Always be polite and professional. Cite sources when making factual claims.
Account reference: {{ user.account_id }}""")

TOOL_DESCRIPTION_TEMPLATE = Template("""You have the following tools available:

{% for tool in tools %}
### {{ tool.name }}
{{ tool.description }}
Parameters: {{ tool.parameters | tojson }}

{% endfor %}
When the user's request matches a tool's purpose, call the appropriate tool. If no tool \
is relevant, respond conversationally. Never invent tools that are not listed above.""")


def build_system_message(user: User, tools: list[Tool]) -> str:
    """Render the full system message from templates."""
    persona = SYSTEM_PROMPT_TEMPLATE.render(user=user)
    tool_section = TOOL_DESCRIPTION_TEMPLATE.render(tools=tools)
    return f"{persona}\n\n{tool_section}"


def run_agent(user: User, tools: list[Tool], conversation: list[dict]) -> str:
    """Run a single agent turn: build context, call the model, return the reply."""
    system_message = build_system_message(user, tools)

    messages = [{"role": "system", "content": system_message}]
    messages.extend(conversation)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.5,
        max_tokens=2048,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    demo_user = User(name="Alice", is_premium=True, account_id="ACC-90210")
    demo_tools = [
        Tool(name="web_search", description="Search the web for current information.", parameters={"query": "string"}),
        Tool(name="calculator", description="Evaluate a mathematical expression.", parameters={"expression": "string"}),
    ]

    history = []
    print("Nova agent ready. Type 'quit' to exit.\n")
    while True:
        msg = input("You: ")
        if msg.strip().lower() in ("quit", "exit"):
            break
        history.append({"role": "user", "content": msg})
        reply = run_agent(demo_user, demo_tools, history)
        history.append({"role": "assistant", "content": reply})
        print(f"Nova: {reply}\n")
