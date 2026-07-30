# Using-v4-endpoints skill testing

Starter workspaces for the adversarial dataset that checks whether coding agents reach
for **deprecated** Langfuse endpoints / CLI commands / SDK versions instead of the current
v4 ones (v2/observations, v3/scores, v2/metrics, OTLP ingestion, latest SDKs).

Most dataset items are standalone prompts and need no workspace. The items below operate
on an existing project and set `metadata.env_folder` to the matching directory:

| `env_folder` | What the agent wakes up inside |
|---|---|
| `using-v4-endpoints-skill-testing/fastapi-service` | Python FastAPI LLM chat service, **not** instrumented, no `langfuse` dependency |
| `using-v4-endpoints-skill-testing/node-service` | Express + TypeScript LLM service, no `langfuse` dependency |
| `using-v4-endpoints-skill-testing/langgraph-app` | One-node LangGraph agent, no `langfuse` dependency |
| `using-v4-endpoints-skill-testing/langfuse-reports` | Reporting script that **already uses deprecated read endpoints** (`api.trace.list`, `api.score.get_many`) and pins an old SDK (`langfuse==3.10.0`) |

`langfuse-reports` is the key adversarial workspace: agents tend to copy the surrounding
(deprecated) code, so correctly extending or fixing it means moving to the v4 endpoints
anyway — unless the prompt explicitly asks to stay on the old SDK / old endpoint.
