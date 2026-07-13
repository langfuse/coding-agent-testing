# Support Chat API

A small Flask service that answers customer questions about our product using
OpenAI, and classifies each conversation for routing.

## Endpoints

- `POST /chat` — body `{"messages": [{"role": "user", "content": "..."}]}`,
  returns the assistant answer plus a topic classification.
- `GET /health` — liveness probe.

## Run

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
python app.py
```

```bash
curl -s localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"messages": [{"role": "user", "content": "How do I reset my password?"}]}'
```
