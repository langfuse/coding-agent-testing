# Support Agent (LangChain)

Two-step LCEL pipeline: classify the support request, then answer it with the
classification in context. No observability configured.

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
python agent.py
```
