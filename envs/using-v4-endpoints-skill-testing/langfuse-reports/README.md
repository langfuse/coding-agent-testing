# langfuse-reports (dummy env)

An existing reporting script that queries a Langfuse project. It **already uses the older
read endpoints** (`api.trace.list`, `api.score.get_many`) and pins an **older Langfuse
SDK** in `requirements.txt`.

This is the "mirror the surrounding code" trap: dataset items that ask an agent to extend
or fix this script should still move to the current endpoints (v2/observations,
v3/scores) rather than copying the deprecated pattern — *unless* the prompt explicitly
says to stay on the old SDK / old endpoint.

- `reporting.py` — deprecated `/traces` + `/v2/scores` reads
- `requirements.txt` — pins `langfuse==3.10.0` (pre-v4)
