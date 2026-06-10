# internal-ax — agent-readiness tester

Measures, for a given input prompt, how well a target tool gets **discovered,
recommended, and actually used** by LLMs and code agents. Triggered by a
**Langfuse remote dataset run**, executed **headlessly on Modal**, traced back to
**Langfuse**. No UI of its own — datasets, triggering, and trace inspection all
live in the Langfuse UI.

For each dataset item it runs up to four configurations and scores each:

| # | Run config (`key`) | What it measures | Compute |
|---|---|---|---|
| 1 | `bare-claude`, `bare-gpt` | Discovery/recommendation from **training knowledge only** (one model call, no tools) | in-process API call |
| 2 | `search-gpt` | Discovery/recommendation with **web search + reasoning** (OpenAI Agents SDK + WebSearchTool) | in-process API call |
| 3a | `claude-code` | Discovery + recommendation + **correct use** by **Claude Code** | isolated Modal Sandbox |
| 3b | `codex` | Discovery + recommendation + **correct use** by **Codex** | isolated Modal Sandbox |

Scores attached to every trace (the stable contract the Langfuse UI aggregates):
`discovered`, `recommended`, and (code agents only) `used_correctly`. The
heuristics live in `scoring.py` — swap in an LLM-as-judge where you need nuance.

---

## Architecture

The system splits into a lightweight **control plane** and a **data plane** whose
two halves have very different compute needs — which is the whole reason it's on
Modal rather than a single serverless function.

```
Langfuse  ──POST {projectId,datasetId,datasetName,payload}──▶  webhook  (Modal web endpoint)
 (remote dataset run, 20s timeout, no signature)                  │  auth via ?token=, returns 2xx fast
                                                                  ▼
                                                            orchestrate (Modal fn)
                                                       fetch dataset · build item×config matrix
                                                                  │  run_unit.map(...)
                                          ┌───────────────────────┼───────────────────────┐
                                          ▼                       ▼                       ▼
                                    run_unit (1,2)          run_unit (3a)           run_unit (3b)
                                  in-process LLM call    modal.Sandbox: claude    modal.Sandbox: codex
                                  Langfuse SDK trace     -p + Langfuse plugin     exec + Langfuse plugin
                                          │                       │                       │
                                          └──── link trace → dataset item + named run, attach scores ────┘
                                                                  ▼
                                                              Langfuse
```

All four run types converge on one linking call —
`langfuse.api.dataset_run_items.create(run_name=…, dataset_item_id=…, trace_id=…)`
— because Langfuse v4 removed the v3 `dataset_item.run()` context manager and this
API accepts an externally-created `trace_id` (exactly what the sandbox plugins
produce).

### Repo layout

```
src/internal_ax/
  app.py              Modal app: webhook endpoint + orchestrate + run_unit
  images.py           Modal images (orchestrator; agent sandbox w/ CLIs + plugins)
  config.py           settings + the run-config matrix
  langfuse_helpers.py dataset fetch, trace↔run linking, correlation queries, scoring
  scoring.py          discovered / recommended / used_correctly heuristics
  runners/
    bare_model.py     type 1
    search_model.py   type 2
    claude_code.py    type 3a (Sandbox + claude -p + Langfuse plugin)
    codex.py          type 3b (Sandbox + codex exec + Langfuse plugin)
    _sandbox.py       shared sandbox helper
scripts/
  seed_dataset.py     create a demo dataset in Langfuse
  trigger_webhook.py  POST a Langfuse-shaped payload locally
```

---

## Prerequisites

- A **Langfuse Cloud** project (the Python SDK is v4, OpenTelemetry-native).
- A **Modal** account (`pip install modal && modal token new`).
- **Anthropic** and **OpenAI** API keys.

## 1. Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # fill in keys
```

`config.py` reads `ANTHROPIC_MODEL` / `OPENAI_MODEL` from the env (defaults
`claude-sonnet-4-6` / `gpt-4o`) — **verify those IDs against the providers'
current model lists** and set the ones you want to benchmark.

## 2. Seed a dataset

```bash
set -a && source .env && set +a
python scripts/seed_dataset.py     # creates dataset "agent-readiness-demo"
```

Each dataset item is `{"input": {"prompt": "..."}, "expected_output": {"tool": "..."}}`.
`expected_output.tool` (or `metadata.expected_tool`) is what scoring looks for.

## 3. Deploy to Modal (the hosting)

**a. Create the secret** holding everything from `.env`:

```bash
modal secret create internal-ax \
  LANGFUSE_PUBLIC_KEY=pk-lf-... \
  LANGFUSE_SECRET_KEY=sk-lf-... \
  LANGFUSE_BASE_URL=https://cloud.langfuse.com \
  ANTHROPIC_API_KEY=sk-ant-... \
  OPENAI_API_KEY=sk-... \
  ANTHROPIC_MODEL=claude-sonnet-4-6 \
  OPENAI_MODEL=gpt-4o \
  WEBHOOK_SECRET="$(openssl rand -hex 24)"
```

**b. Deploy** (builds both images; the agent image installs Node 22, the Claude
Code + Codex CLIs, `uv`, and both Langfuse observability plugins):

```bash
modal deploy -m internal_ax.app
```

Modal prints the web endpoint URL, e.g.
`https://<workspace>--internal-ax-webhook.modal.run`.

**c. Validate the agent path before relying on it** — see the section below.

## 4. Wire up the Langfuse remote dataset run

In Langfuse: open the dataset → **Start Experiment** → **Custom Experiment** →
the ⚡ (lightning) icon → set the **webhook URL** to your Modal endpoint **with
the token appended**:

```
https://<workspace>--internal-ax-webhook.modal.run?token=<WEBHOOK_SECRET>
```

Optionally set a default **payload** (JSON) to narrow the matrix or name the run:

```json
{ "run_configs": ["bare-claude", "bare-gpt", "search-gpt", "claude-code", "codex"],
  "run_name": "baseline-2026-06" }
```

> Langfuse's remote-run webhook sends **no signature/auth header** and **no
> `runName`** — hence the `?token=` gate and the auto-generated run name. It also
> **aborts after 20s**, so the endpoint only ACKs and spawns; the experiment runs
> asynchronously.

Now click **Run** in the Langfuse dataset UI. Or trigger it yourself:

```bash
python scripts/trigger_webhook.py \
  --url "https://<workspace>--internal-ax-webhook.modal.run?token=$WEBHOOK_SECRET" \
  --dataset agent-readiness-demo --run-configs bare-claude codex
```

Results appear under the dataset's **Runs** in Langfuse, one trace per item×config.

---

## Validate the agent path (smoke test)

The code-agent runners depend on a few things this scaffold could **not** verify
from primary sources. Confirm them once, in a Modal shell, before trusting type 3:

```bash
modal shell --image-from-ref internal_ax.images::AGENT_IMAGE   # or: modal run an ad-hoc fn
```

1. **CLI package names/versions** install cleanly (`claude --version`, `codex --version`).
2. **Stop/SessionEnd hooks fire headlessly.** Run
   `LANGFUSE_USER_ID=test-123 TRACE_TO_LANGFUSE=true claude -p "say hi" --output-format json --dangerously-skip-permissions`
   then check Langfuse for a trace with `user_id=test-123`. Repeat for
   `codex exec "say hi"` and check for the injected `LANGFUSE_CODEX_METADATA`.
3. **Codex plugin path** in `runners/codex.py::_CODEX_SETUP` matches the plugin
   repo's expected cache layout/version.

**If hooks don't fire under `-p`/`exec`:** switch type 3 to **native OTel export**
instead of the plugins — set in the sandbox env
`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_EXPORTER_OTLP_ENDPOINT=<host>/api/public/otel`,
`OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64(pk:sk)>"` — and propagate
`TRACEPARENT` from a Langfuse root span so the agent's spans nest into a trace you
already linked to the dataset item. (Langfuse OTLP ingestion is HTTP only, no gRPC.)

---

## How tracing + linking works per run type

- **Types 1 & 2 (in-process):** a Langfuse span wraps the call; the OpenAI drop-in
  / OpenInference instrumentation records the generation; we read
  `get_current_trace_id()`, then `link_trace_to_run(...)` and attach scores.
- **Type 3a Claude Code:** the official plugin creates its own trace and exposes
  **no metadata hook** — only `LANGFUSE_USER_ID`. Each sandbox is 1:1 with a run,
  so we set a unique per-run `user_id`, then `find_traces_by_user_id(...)` and link.
- **Type 3b Codex:** the official plugin **does** honour `LANGFUSE_CODEX_METADATA`
  / `LANGFUSE_CODEX_TAGS`, so we inject `{dataset_item_id, run_name}` and correlate
  cleanly via `find_traces_by_metadata(...)`.

Plugin export is asynchronous (it flushes on the Stop hook), so the correlation
queries poll briefly after the run finishes.

## Known rough edges / product feedback (you're at Langfuse 🙂)

These surfaced during the build and are candidates for product improvements:

1. **Claude Code plugin** can't carry per-run **metadata/tags/session** or adopt an
   external `trace_id`/`TRACEPARENT`; only `LANGFUSE_USER_ID` is settable, and it
   emits **one trace per turn**. That makes dataset-run correlation hacky (vs. the
   Codex plugin, which supports metadata/tags cleanly).
2. **Remote-run webhook** has **no HMAC/signature** and omits **`runName`** — we
   work around both, but a signature + `runName` would let services authenticate
   the call and adopt the run name Langfuse shows in the UI.
3. **OpenAI Responses API + `web_search`** has no documented `langfuse.openai`
   drop-in example; type 2 uses the OpenAI Agents SDK integration instead.

## Ops notes

- Modal scales `run_unit` to zero between runs — you pay per second of execution
  only. Cap fan-out with `max_containers` on `run_unit` if you want to bound
  concurrency / spend.
- Per-run sandbox budget is `SANDBOX_TIMEOUT_S` (default 900s).
- Everything is keyed off the `internal-ax` Modal secret; rotate `WEBHOOK_SECRET`
  by updating the secret and the URL registered in Langfuse.
