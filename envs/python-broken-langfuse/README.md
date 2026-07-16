# Nightly Digest (Langfuse — traces missing)

Short-lived CLI script that summarizes support tickets with OpenAI, traced
with the Langfuse Python SDK (`@observe`). It runs fine and prints the digest,
**but no traces ever appear in the Langfuse project**.

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-... LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-...
python report.py
```
