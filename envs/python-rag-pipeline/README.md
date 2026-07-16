# Help Center RAG

Answers questions about AcmeSync from the help-center articles embedded in
`rag.py` (naive in-memory retrieval + OpenAI). `eval_questions.json` contains
labeled Q&A pairs collected from support.

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
python rag.py
```
