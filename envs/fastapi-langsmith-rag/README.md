# Docs Q&A API (LangSmith)

FastAPI docs-Q&A service traced with LangSmith `@traceable` decorators
(retrieve → generate pipeline). Tracing is enabled via:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_...
```

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn app:app --port 8000
```
