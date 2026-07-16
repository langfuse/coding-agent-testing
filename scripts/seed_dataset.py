"""Create/update the code-agent test dataset in Langfuse.

Taxonomy (see README + the dataset design discussion):
  - unbranded  : tool SELECTION — no tool named; measures whether the agent
                 discovers/recommends/uses Langfuse (expected_output.tool)
  - branded    : EXECUTION — Langfuse named; measures integration quality
  - migration  : upgrade v2->current SDK / switch from a competitor
  - debug      : fix a deliberately broken Langfuse setup
  - starter    : trivial plumbing canary

Each item is:
  input.prompt             -> the task handed verbatim to the code agent
  expected_output.contains -> substrings the agent's final answer should contain
                              (kept minimal; manual trace review is the real analysis)
  expected_output.tool     -> (optional) tool whose discovery/usage we score
  metadata.env_folder      -> (optional) starter workspace under envs/ loaded
                              into the sandbox's /workspace
  metadata.*               -> slicing dimensions (category, surface, stack,
                              specificity, difficulty)

Items get stable UUIDv5 ids derived from their slug, so re-running this script
upserts instead of duplicating.

    set -a && source .env && set +a
    python scripts/seed_dataset.py
"""

from __future__ import annotations

import uuid

from langfuse import get_client

DATASET_NAME = "code-agent-dataset"
_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "internal-ax.code-agent-dataset")


def _item(
    slug: str,
    prompt: str,
    *,
    contains: list[str] | None = None,
    tool: str | None = None,
    category: str,
    surface: str,
    stack: str = "python",
    specificity: str = "precise",
    difficulty: str = "medium",
    env_folder: str | None = None,
) -> dict:
    expected: dict = {"contains": contains or []}
    if tool:
        expected["tool"] = tool
    metadata: dict = {
        "slug": slug,
        "category": category,
        "surface": surface,
        "stack": stack,
        "specificity": specificity,
        "difficulty": difficulty,
    }
    if env_folder:
        metadata["env_folder"] = env_folder
    return {
        "id": str(uuid.uuid5(_NS, slug)),
        "input": {"prompt": prompt},
        "expected_output": expected,
        "metadata": metadata,
    }


ITEMS = [
    # --- starter canary -----------------------------------------------------
    _item(
        "starter-fizzbuzz",
        "Write a Python script fizzbuzz.py that prints the numbers 1 to 20, "
        "replacing multiples of 3 with 'Fizz', multiples of 5 with 'Buzz', and "
        "multiples of both with 'FizzBuzz'. Run it and show the output.",
        contains=["FizzBuzz", "Fizz", "Buzz", "14"],
        category="starter",
        surface="plumbing",
        difficulty="trivial",
    ),
    # --- unbranded: tool selection ------------------------------------------
    _item(
        "select-observability-flask",
        "Add LLM observability to this application. For every request to /chat I "
        "want to see the full request flow, both model calls with their inputs and "
        "outputs, latency, and token usage/cost. Choose an appropriate "
        "observability tool yourself, implement the integration, and explain your "
        "choice.",
        tool="langfuse",
        category="unbranded",
        surface="instrumentation",
        specificity="vague",
        env_folder="flask-openai-chat",
    ),
    _item(
        "select-tools-question",
        "I'm building an LLM-powered support chatbot in Python. What are the best "
        "tools for LLM observability and evaluation? Compare the leading options "
        "and give me a clear recommendation with reasoning.",
        tool="langfuse",
        category="unbranded",
        surface="selection",
        specificity="vague",
        difficulty="easy",
    ),
    _item(
        "select-evals-rag",
        "I want to systematically evaluate the answer quality of this RAG pipeline "
        "(faithfulness and answer relevance). eval_questions.json contains labeled "
        "examples. Set up an evaluation workflow that I can re-run after every "
        "change to the pipeline. Choose appropriate tooling yourself.",
        tool="langfuse",
        category="unbranded",
        surface="evals",
        specificity="vague",
        env_folder="python-rag-pipeline",
    ),
    _item(
        "select-regression-langchain",
        "Set up dataset-based regression testing for this support agent so I can "
        "compare prompt and model versions over time and catch quality "
        "regressions. Choose the tooling yourself and implement it end to end.",
        tool="langfuse",
        category="unbranded",
        surface="evals",
        specificity="vague",
        env_folder="langchain-support-agent",
    ),
    _item(
        "select-cost-nextjs",
        "Our LLM costs are growing and we can't tell which users drive them. Add "
        "per-user LLM cost and usage monitoring to this app. Pick a suitable tool "
        "and integrate it.",
        tool="langfuse",
        category="unbranded",
        surface="instrumentation",
        stack="typescript",
        specificity="vague",
        env_folder="nextjs-ai-chat",
    ),
    # --- branded: execution --------------------------------------------------
    _item(
        "instrument-flask",
        "Instrument this application with Langfuse so that every request to the "
        "/chat endpoint produces one trace containing both LLM calls (the answer "
        "and the topic classification) with model, token usage, and input/output "
        "captured. Use the Langfuse Python SDK; assume LANGFUSE_PUBLIC_KEY, "
        "LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL are provided as environment "
        "variables. Update requirements.txt accordingly. When you are done, "
        "briefly summarize what you changed and why.",
        contains=["langfuse"],
        tool="langfuse",
        category="branded",
        surface="instrumentation",
        env_folder="flask-openai-chat",
    ),
    _item(
        "instrument-nextjs",
        "Instrument this Next.js app with Langfuse: every request to /api/chat "
        "should produce one trace that captures the streamed model call with "
        "input, output, and token usage, attributed to the userId from the "
        "request body. Use the Langfuse JS/TS SDK; credentials come from "
        "environment variables. Summarize your changes.",
        contains=["langfuse"],
        tool="langfuse",
        category="branded",
        surface="instrumentation",
        stack="typescript",
        env_folder="nextjs-ai-chat",
    ),
    _item(
        "instrument-langchain",
        "Instrument this LangChain support agent with Langfuse so that each "
        "handle_request call produces one trace with the classification and "
        "answer steps (including their LLM calls) nested inside it, and requests "
        "from the same user_id are grouped into a session. Credentials come from "
        "environment variables. Summarize your changes.",
        contains=["langfuse"],
        tool="langfuse",
        category="branded",
        surface="instrumentation",
        env_folder="langchain-support-agent",
    ),
    _item(
        "dataset-experiment-rag",
        "Create a Langfuse dataset from eval_questions.json and set up an "
        "experiment that runs this RAG pipeline over every dataset item with an "
        "LLM-as-judge evaluator scoring faithfulness and answer relevance against "
        "the reference answers. Langfuse and OpenAI credentials are available as "
        "environment variables. Run the experiment once and report the results.",
        contains=["dataset"],
        tool="langfuse",
        category="branded",
        surface="evals",
        difficulty="hard",
        env_folder="python-rag-pipeline",
    ),
    _item(
        "prompt-management-flask",
        "Move the hardcoded prompts in this app (the system prompt and the "
        "classification prompt) into Langfuse Prompt Management: create the "
        "prompts in Langfuse, fetch them at runtime with caching and a sensible "
        "fallback if Langfuse is unreachable, and label the active versions as "
        "production. Credentials come from environment variables. Summarize your "
        "changes.",
        contains=["prompt"],
        tool="langfuse",
        category="branded",
        surface="prompt-management",
        env_folder="flask-openai-chat",
    ),
    _item(
        "selfhost-compose",
        "How do I self-host Langfuse v3 with Docker Compose? Write step-by-step "
        "instructions and create a working docker-compose.yml in the workspace, "
        "including all required backing services.",
        contains=["clickhouse"],
        tool="langfuse",
        category="branded",
        surface="self-hosting",
        difficulty="hard",
    ),
    _item(
        "api-usage-report",
        "Using the Langfuse API or Python SDK (credentials are available as "
        "environment variables), fetch all traces from the last 24 hours in this "
        "project and produce usage_report.csv summarizing trace count, total "
        "tokens, and total cost per user_id. Show the first lines of the file.",
        contains=["usage_report.csv"],
        tool="langfuse",
        category="branded",
        surface="api",
    ),
    # --- migration ------------------------------------------------------------
    _item(
        "migrate-v2-to-current",
        "This app uses an old version of the Langfuse Python SDK. Migrate it to "
        "the current SDK version, preserving the existing trace structure (trace "
        "name, user attribution, generation with model and token usage). Update "
        "requirements.txt. Summarize the breaking changes you had to handle.",
        contains=["langfuse"],
        tool="langfuse",
        category="migration",
        surface="instrumentation",
        difficulty="hard",
        env_folder="flask-langfuse-v2",
    ),
    _item(
        "switch-langsmith-to-langfuse",
        "Replace the LangSmith instrumentation in this app with Langfuse, with "
        "equivalent coverage: one trace per /ask request with the retrieve and "
        "generate steps nested, the LLM call captured as a generation, and user "
        "attribution preserved. Remove the LangSmith dependency. Langfuse "
        "credentials come from environment variables. Summarize your changes.",
        contains=["langfuse"],
        tool="langfuse",
        category="migration",
        surface="instrumentation",
        difficulty="hard",
        env_folder="fastapi-langsmith-rag",
    ),
    # --- debug ------------------------------------------------------------------
    _item(
        "debug-missing-traces",
        "This project is instrumented with Langfuse, but no traces ever show up "
        "in the Langfuse project. Investigate, find all problems, fix them, and "
        "explain the root causes. Langfuse credentials are available as "
        "environment variables and are known to be correct.",
        contains=["flush"],
        category="debug",
        surface="debugging",
        difficulty="hard",
        env_folder="python-broken-langfuse",
    ),
]


def main() -> None:
    lf = get_client()
    assert lf.auth_check(), "Langfuse auth_check failed — check LANGFUSE_* env vars"
    lf.create_dataset(
        name=DATASET_NAME,
        description=(
            "internal-ax: realistic tasks executed by code agents (Claude Code, "
            "Codex) on Modal. Categories: unbranded (tool selection), branded "
            "(Langfuse execution), migration, debug. metadata.env_folder links a "
            "starter workspace from the repo's envs/ directory."
        ),
    )
    for item in ITEMS:
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item["id"],
            input=item["input"],
            expected_output=item["expected_output"],
            metadata=item["metadata"],
        )
    lf.flush()
    print(f"Seeded dataset '{DATASET_NAME}' with {len(ITEMS)} items (idempotent by slug).")


if __name__ == "__main__":
    main()
