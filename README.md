# internal-ax — code-agent readiness tester

Runs **code agents** (Claude Code and Codex) headlessly **on Modal** against a
**Langfuse dataset**, and traces every run back to **Langfuse**. Triggered by a
Langfuse **remote dataset run** (or manually). No UI of its own — datasets,
triggering, and trace inspection all live in the Langfuse UI.

> Scope note: bare-model and model+search checks are intentionally **not** part
> of this project — those can be run directly in the Langfuse UI via dataset
> experiments. This repo only covers what the UI can't: executing real code
> agents in isolated sandboxes.

| Run config (`key`) | Agent | Tracing |
|---|---|---|
| `claude-code` | Claude Code (`claude -p`) | [Claude-Observability-Plugin](https://github.com/langfuse/Claude-Observability-Plugin) (Stop/SessionEnd hooks) |
| `codex` | Codex (`codex exec`) | [codex-observability-plugin](https://github.com/langfuse/codex-observability-plugin) (Stop hook) |

Scores attached to every trace (the stable contract the Langfuse UI aggregates):

- `task_completed` — fraction of `expected_output.contains` substrings present
  in the agent's final answer
- `discovered` / `recommended` / `used_correctly` — only when an item sets
  `expected_output.tool` (for tool-readiness items you add later)

The heuristics live in `scoring.py` — swap in an LLM-as-judge where you need nuance.

---

## Architecture

```
Langfuse  ──POST {projectId,datasetId,datasetName,payload}──▶  webhook  (Modal web endpoint)
 (remote dataset run, 20s timeout, no signature)                  │  auth via ?token=, returns 2xx fast
                                                                  ▼
                                                            orchestrate (Modal fn)
                                                       fetch dataset · build item×agent matrix
                                                                  │  run_unit.map(...)
                                          ┌───────────────────────┴───────────────────────┐
                                          ▼                                               ▼
                                    run_unit (claude-code)                        run_unit (codex)
                                 modal.Sandbox: claude -p                    modal.Sandbox: codex exec
                                 + Langfuse plugin (hooks)                   + Langfuse plugin (hooks)
                                          │                                               │
                                          └── link trace → dataset item + named run, attach scores ──┘
                                                                  ▼
                                                              Langfuse
```

The plugins create traces *from inside the sandbox*; the runner then locates
them and links via `langfuse.api.dataset_run_items.create(run_name=…,
dataset_item_id=…, trace_id=…)` (the v4 API that accepts externally-created
trace ids).

### Repo layout

```
src/internal_ax/
  app.py              Modal app: webhook + orchestrate + run_unit + smoke_test entrypoint
  images.py           Modal images (orchestrator; agent sandbox w/ CLIs + plugins + envs/)
  config.py           settings + the run-config matrix (claude-code, codex)
  langfuse_helpers.py dataset fetch, trace↔run linking, correlation queries
  scoring.py          task_completed + tool-readiness heuristics
  runners/
    claude_code.py    Sandbox + claude -p + Claude-Observability-Plugin
    codex.py          Sandbox + codex exec + codex-observability-plugin
    _sandbox.py       shared sandbox helper (incl. env-folder materialization)
envs/
  <name>/             starter workspaces; dataset items reference them via
                      metadata.env_folder and the folder is copied into the
                      sandbox's /workspace before the agent starts
scripts/
  seed_dataset.py     create the "code-agent-dataset" dataset in Langfuse
  bootstrap_modal.sh  create the project secret, deploy, print the webhook URL
  trigger_webhook.py  POST a Langfuse-shaped payload at the deployed webhook
```

### Env folders (realistic starting workspaces)

Some tasks need more than a prompt — "instrument *this application* with
Langfuse" only makes sense if there is an application. Those items set
`metadata.env_folder` to the name of a directory under `envs/`:

1. `envs/` is baked into the agent image at `/opt/envs` (`copy=True`, so a
   changed folder just triggers an image rebuild on the next deploy).
2. When a dataset item carries `metadata.env_folder`, the runner copies
   `/opt/envs/<name>/.` into the sandbox's `/workspace` before launching the
   agent — the agent wakes up inside the project.
3. Items without `env_folder` start in an empty `/workspace` as before.

Folder names are validated (`[A-Za-z0-9][A-Za-z0-9_-]*`) since metadata is
editable in the Langfuse UI and ends up in a shell command.

---

## Prerequisites

- A **Langfuse Cloud** project (Python SDK v4).
- A **Modal** account (`pip install modal && modal token new`).
- **Anthropic** (Claude Code) and **OpenAI** (Codex) API keys.

## 1. Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # fill in keys
```

## 2. Seed the dataset

```bash
set -a && source .env && set +a
python scripts/seed_dataset.py     # creates dataset "code-agent-dataset"
```

One trivial plumbing check (FizzBuzz) plus one realistic branded task
(instrument `envs/flask-openai-chat` with Langfuse). Item shape:

```json
{ "input":            {"prompt": "the task handed verbatim to the agent"},
  "expected_output":  {"contains": ["substrings", "the answer must include"],
                       "tool": "optional-tool-to-score-discovery-of"},
  "metadata":         {"env_folder": "optional-starter-workspace-under-envs/"} }
```

Add more sophisticated items in the Langfuse UI once the setup works — no code
change needed as long as they follow this shape.

## 3. Deploy to Modal

Two layered secrets (later wins on key conflicts), so switching the Langfuse
project never requires re-entering the agent API keys:

- `internal-ax` (base, one-time): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `internal-ax-project`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
  `LANGFUSE_BASE_URL`, `WEBHOOK_SECRET`

**a. Base secret** (once):

```bash
modal secret create internal-ax ANTHROPIC_API_KEY=sk-ant-... OPENAI_API_KEY=sk-...
```

**b. Project secret + deploy + webhook URL** — one command, reads `.env`,
generates and persists `WEBHOOK_SECRET` if missing:

```bash
bash scripts/bootstrap_modal.sh
```

It prints the exact webhook URL to paste into Langfuse
(`https://<workspace>--internal-ax-webhook.modal.run?token=...`). Re-run it any
time you point at a different Langfuse project.

**c. Smoke-test the full path synchronously** (no webhook involved — failures
surface in your terminal):

```bash
modal run -m internal_ax.app --dataset code-agent-dataset --run-configs claude-code
modal run -m internal_ax.app --dataset code-agent-dataset --run-configs codex
```

Then check Langfuse: the dataset's **Runs** tab should show one run with a
linked, scored trace per item.

## 4. Wire up the Langfuse remote dataset run

In Langfuse: open the dataset → **Start Experiment** → **Custom Experiment** →
the ⚡ (lightning) icon → set the **webhook URL** to your Modal endpoint **with
the token appended**:

```
https://<workspace>--internal-ax-webhook.modal.run?token=<WEBHOOK_SECRET>
```

Optionally set a default **payload** (JSON) to narrow the matrix or name the run:

```json
{ "run_configs": ["claude-code", "codex"], "run_name": "baseline-2026-06" }
```

> Langfuse's remote-run webhook sends **no signature/auth header** and **no
> `runName`** — hence the `?token=` gate and the auto-generated run name. The
> custom config blob arrives as a JSON **string** inside `payload`, which
> `orchestrate` parses defensively. Langfuse also **aborts after 20s**, so the
> endpoint only ACKs and spawns; the experiment runs asynchronously.

Now click **Run** in the Langfuse dataset UI. Or trigger it yourself:

```bash
python scripts/trigger_webhook.py \
  --url "https://<workspace>--internal-ax-webhook.modal.run?token=$WEBHOOK_SECRET" \
  --dataset code-agent-dataset
```

Results appear under the dataset's **Runs** tab: **one experiment run per
agent**, named `<base run name>-<config key>` (e.g. `baseline-2026-06-claude-code`
and `baseline-2026-06-codex`), each carrying `{agent, harness}` run metadata —
so agents stay directly comparable side by side. Linking uses the low-level
`dataset_run_items.create` API (not `run_experiment`, which assumes the task
executes in-process; our traces come from plugins inside the sandboxes).

---

## How tracing + correlation works per agent

Both agents are traced by their **official Langfuse observability plugins**,
which run as agent hooks *inside the sandbox* and create their own traces.

**Trace ids are deterministic** — both plugins support a trace seed
(Claude Code: `CC_LANGFUSE_TRACE_SEED`, PR #23; Codex:
`LANGFUSE_CODEX_TRACE_SEED`, PR #24) from which the turn-N trace id derives as
`create_trace_id(f"{seed}:{N}")` (= `sha256[:32]`). Each runner generates a
per-cell seed, precomputes the id (headless runs are exactly one turn), and
after the agent exits just confirms the trace exists (`GET /traces/{id}`,
polling briefly since plugin export is async) before attaching scores and the
dataset-run link. There is no discovery machinery — the plugins must be at
least at the pinned revisions in `images.py` for the seed to be honoured.

Per-agent headless notes:

- **Claude Code** — we generate a UUID used as both `--session-id` and the
  trace seed; the plugin reports it as the Langfuse `session_id`. Important:
  never add `--bare` to the command — it skips hooks/plugins entirely, i.e. no
  trace. `IS_SANDBOX=1` is set so `--dangerously-skip-permissions` works as
  root inside the container.
- **Codex** — the plugin honours `LANGFUSE_CODEX_METADATA` /
  `LANGFUSE_CODEX_TAGS`, so we also inject `{dataset_item_id, run_name}` as
  trace metadata. `TRACE_TO_LANGFUSE=true` is the plugin's opt-in switch.
  Headless requirements: `--dangerously-bypass-hook-trust` (Codex silently
  skips untrusted plugin hooks otherwise), `--sandbox danger-full-access`
  (Codex's Landlock sandbox isn't available in containers; the Modal sandbox is
  the isolation boundary), stdin redirected from /dev/null, and the manual
  post-exec hook invocation (see rough edge #4). Auth is
  `codex login --with-api-key` from `OPENAI_API_KEY`.

## Known rough edges / product feedback (you're at Langfuse 🙂)

1. **Claude Code plugin** can't carry per-run **metadata/tags** (unlike the
   Codex plugin) — only `user_id`/`session_id` are settable from outside, and it
   emits one trace per turn. Session-id correlation works but metadata would be
   cleaner.
2. **Remote-run webhook** has **no HMAC/signature** and omits **`runName`** — we
   work around both, but a signature + `runName` would let services authenticate
   the call and adopt the run name Langfuse shows in the UI.
   Also: the custom config blob is delivered as a JSON **string** inside
   `payload` rather than as a JSON object — every consumer has to double-parse.
3. Claude Code's `--bare` flag (slated to become the `-p` default at some point)
   skips hooks/plugins; if a CLI update changes the default, traces silently
   stop. Pin or watch the CLI version in `images.py`.
4. **Codex `exec` mode never fires plugin Stop hooks** (observed with
   codex-cli 0.139.0, `plugin_hooks = true`, `--dangerously-bypass-hook-trust`;
   the plugin cache materializes but no hook process ever starts — interactive
   TUI only?). The runner works around it by piping
   `{"transcript_path": ...}` into the plugin's `dist/index.mjs` manually after
   `codex exec` finishes. Worth reporting to the codex-observability-plugin
   team: headless `codex exec` is exactly the CI/benchmark use case.
5. Two `codex exec` headless quirks: it blocks forever reading an open
   non-TTY stdin (fixed with `< /dev/null`), and `trace.list` metadata filters
   require the `type: "stringObject"` discriminator or return 400.

## Ops notes

- The Langfuse observability plugins are **pinned by commit SHA** in
  `images.py` (`CLAUDE_PLUGIN_REV`, `CODEX_PLUGIN_REV`). To pull a newer
  plugin, bump the SHA and redeploy — the changed layer forces a fresh
  install. Unpinned clones would silently freeze at build-time HEAD.
- Modal scales `run_unit` to zero between runs — you pay per second of execution
  only. Cap fan-out with `max_containers` on `run_unit` to bound concurrency/spend.
- Per-run sandbox budget is `SANDBOX_TIMEOUT_S` (default 900s).
- Everything is keyed off the `internal-ax` Modal secret; rotate `WEBHOOK_SECRET`
  by updating the secret and the URL registered in Langfuse.
