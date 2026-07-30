# fastapi-service (dummy env)

A minimal FastAPI LLM chat service. **Not instrumented with Langfuse** and no Langfuse
dependency yet — this is the starting point for instrumentation / SDK-setup dataset items.

- `main.py` — `/chat` endpoint calling OpenAI, plus `/health`
- `requirements.txt` — no `langfuse` entry
