# internal-ax — code-agent readiness tester

Runs **code agents** (Claude Code and Codex) headlessly in local Docker
containers or on **Modal** against a **Langfuse dataset**, and traces every run
back to **Langfuse**. Deployed runs are triggered by a Langfuse remote dataset
run (or manually). No UI of its own — datasets, triggering, and trace inspection
all live in the Langfuse UI.

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
  in the agent's final answer (deterministic)
- `discovered` / `recommended` / `used_correctly` — only when an item sets
  `expected_output.tool`; scored by an **LLM judge** (claude-opus-4-8) over the
  final answer + activity transcript, with the judge's reasoning attached as
  the score comment. Falls back to the old substring heuristics if the judge
  call fails, so scoring never blocks a run. Lives in `scoring.py`.

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
them, adds the native Langfuse experiment/item attributes, and also links via
`langfuse.api.dataset_run_items.create(run_name=…, dataset_item_id=…,
trace_id=…)` while the legacy dataset-run view remains in use.

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
runtime-skills/
  <name>/             Agent Skills selected by exact commit + path at run time
scripts/
  seed_dataset.py     create the "code-agent-dataset" dataset in Langfuse
  run_local.py        run the same agents locally in disposable Docker containers
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

### Commit-pinned runtime skills

An experiment can install one Agent Skill from an exact commit in this
repository. The commit can be on an unmerged branch. Add the skill as ordinary
files:

```text
runtime-skills/
  langfuse/
    SKILL.md
    references/
    scripts/
```

Then select it in the experiment payload:

```json
{
  "skill": {
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "path": "runtime-skills/langfuse"
  }
}
```

The harness validates and hashes the committed directory, then installs it
before the agent process starts:

- Claude Code: `/root/.claude/skills/<skill-name>/`
- Codex: `/root/.agents/skills/<skill-name>/`

The dataset prompt is passed through unchanged. The harness never mentions or
invokes the skill; deciding whether it is relevant is part of the agent run.
Run metadata records `skill_name`, `skill_commit`, `skill_path`, and
`skill_digest`. After the plugin trace is fully indexed, reads of committed
skill files are represented by explicit `skill.read · <skill>/<file>` children
under the original shell-tool observation. Those derived children reuse the
tool's original start/end timestamps, so they appear where the read happened
in the trace rather than at the end.

---

## Prerequisites

- A **Langfuse Cloud** project (Python SDK v4).
- **Docker Desktop** for local agent runs.
- An **Anthropic** API key for Claude Code. Codex can use either an OpenAI API
  key or an existing local `codex login` session.
- A **Modal** account only for the maintainer who deploys the shared service.

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

## 3. Run agents locally

Local runs use disposable Docker containers and follow the same tracing,
scoring, and Langfuse dataset-linking path as deployed runs. No Modal account
or token is used.

Fill these values in `.env`:

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
ANTHROPIC_API_KEY=sk-ant-...  # when running Claude Code
OPENAI_API_KEY=sk-...         # optional if ~/.codex/auth.json already exists
```

When no `OPENAI_API_KEY` is set, local Codex runs mount the existing
`~/.codex/auth.json` into the disposable container. The file is not copied into
the repository or agent image.

Run one inexpensive dataset item first:

```bash
python scripts/run_local.py \
  --dataset code-agent-dataset \
  --run-configs claude-code \
  --item-limit 1 \
  --run-name local-skill-smoke
```

To test a skill, commit it locally first. The commit does not need to be pushed
for a local run:

```bash
python scripts/run_local.py \
  --dataset code-agent-dataset \
  --run-configs claude-code codex \
  --item-limit 1 \
  --skill-commit "$(git rev-parse HEAD)" \
  --skill-path runtime-skills/my-skill \
  --run-name local-my-skill
```

The first run builds `internal-ax-agent:local`; later runs reuse the image.
Results appear in Langfuse under **Experiments** and under the dataset's
**Runs** tab as `<run-name>-claude-code` and/or `<run-name>-codex`, with
`execution=local-docker` and the skill identity in run metadata.

## 4. Deploy to Modal

Two layered secrets (later wins on key conflicts), so switching the Langfuse
project never requires re-entering the agent API keys:

- `internal-ax` (base, one-time): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `internal-ax-project`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
  `LANGFUSE_BASE_URL`, `WEBHOOK_SECRET`, a read-only `SKILL_GITHUB_TOKEN`,
  and optionally `SANDBOX_LANGFUSE_*`

**Two Langfuse projects** (recommended): the harness project holds the dataset
+ the execution traces; a separate scratch project is what agents see as
`LANGFUSE_*` inside the sandbox, so datasets/prompts/test traces that tasks
tell agents to create don't pollute the harness project. Configure it via
`SANDBOX_LANGFUSE_*` in `.env` — the runner passes it to the sandbox as plain
`LANGFUSE_*`, while the observability plugins get the harness project via
prefixed vars (`LANGFUSE_CODEX_*` natively; `CC_LANGFUSE_*` via an env remap
in the baked hook command, since the Claude hook checks plain vars first).
Unset = agents share the harness project (previous behavior).

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

Because `langfuse/internal-ax` is an internal repository, the deployed service
needs one centrally managed `SKILL_GITHUB_TOKEN` with read-only repository
contents access. Individual experiment users do not need Modal or GitHub API
credentials; they only push their skill commit to this repository and select
it in Langfuse.

**c. Smoke-test the full path synchronously** (no webhook involved — failures
surface in your terminal):

```bash
modal run -m internal_ax.app --dataset code-agent-dataset --run-configs claude-code
modal run -m internal_ax.app --dataset code-agent-dataset --run-configs codex
```

Then check Langfuse: the dataset's **Runs** tab should show one run with a
linked, scored trace per item.

## 5. Wire up the Langfuse remote dataset run

In Langfuse: open the dataset → **Start Experiment** → **Custom Experiment** →
the ⚡ (lightning) icon → set the **webhook URL** to your Modal endpoint **with
the token appended**:

```
https://<workspace>--internal-ax-webhook.modal.run?token=<WEBHOOK_SECRET>
```

Optionally set a default **payload** (JSON) to narrow the matrix, name the run,
or pin per-agent models (unset = each CLI's default; currently
`claude-sonnet-4-6` for Claude Code, `gpt-5.5` for Codex — the model used is
recorded per generation in the trace and as run metadata):

```json
{
  "run_configs": ["claude-code", "codex"],
  "run_name": "baseline-2026-06",
  "models": { "claude-code": "opus", "codex": "gpt-5.5-codex" },
  "skill": {
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "path": "runtime-skills/langfuse"
  },
  "reset_sandbox": true
}
```

`reset_sandbox` (default **true**) wipes agent-created artifacts — dataset
items/runs, prompts, traces — from the **sandbox** Langfuse project before the
run, so leftovers from earlier runs can't contaminate this one (empty dataset
shells remain; the API has no dataset delete). Hard-guarded to the
`SANDBOX_LANGFUSE_*` credentials: it refuses to run against the harness
project. Set `false` to keep prior artifacts (e.g. for multi-run scenarios).

> Langfuse's remote-run webhook sends **no signature/auth header** and **no
> `runName`** — hence the `?token=` gate and the auto-generated run name. The
> custom config blob arrives as a JSON **string** inside `payload`, which
> `orchestrate` parses defensively. Langfuse also **aborts after 20s**, so the
> endpoint only ACKs and spawns; the experiment runs asynchronously.

Now click **Run** in the Langfuse dataset UI. Or trigger it yourself:

```bash
python scripts/trigger_webhook.py \
  --url "https://<workspace>--internal-ax-webhook.modal.run?token=$WEBHOOK_SECRET" \
  --dataset code-agent-dataset \
  --skill-commit 0123456789abcdef0123456789abcdef01234567 \
  --skill-path runtime-skills/langfuse
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
