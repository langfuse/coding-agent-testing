# Error analysis: baseline-fable-sol (2026-07-15)

Run: `baseline-fable-sol-claude-code` (Claude Code / claude-fable-5) and
`baseline-fable-sol-codex` (Codex / gpt-5.6-sol), 16 items each, 32 traces,
~640 observations. Method: full trace+observation dumps per item, one analyst
per item reviewing both agents side by side against a fixed rubric (scoping /
knowledge sources / Langfuse usage / friction), then cross-item synthesis.

## 1. How the agents scope tasks

- Both agents always explore the workspace first (read all env-folder files
  before acting); neither ever asks clarifying questions.
- Codex plans explicitly (`update_plan`, 4–6 steps, updated per phase);
  Claude Code works linearly with no plan artifact. Codex averages ~2–3x the
  observations for the same outcome.
- **Selection decisions happen before research.** On every unbranded task the
  choice was made from priors; web searches (when any) validated an
  already-made decision. Codex marked "select tool" as completed in the same
  turn its first searches fired; Claude often did zero research at all.
- Environment awareness is a differentiator: on `select-regression`, Claude
  noticed provisioned `LANGFUSE_*` env vars during recon and pivoted to
  Langfuse; Codex never looked at the env and built a custom stdlib harness.
- Failure mode (Claude): over-investing in verification rabbit holes
  (~13 calls chasing a sandbox `OPENAI_MODEL` override). Failure mode
  (Codex): process overhead — duplicate searches, polling loops, `apply_patch`
  recovery.

## 2. Which knowledge the agents use

- **Claude Code (Fable 5) treats the installed SDK as its documentation.**
  In 7 of 8 branded/execution tasks it issued zero web requests and instead
  ran `inspect.signature`/`getsource`, `dir()`, and grepped
  `site-packages/langfuse/` source — including deprecation strings — to derive
  current APIs. This is highly effective (zero hallucinated APIs) and means
  **SDK docstrings and deprecation messages are a primary agent-facing docs
  surface**. Exceptions where it did go online: the pure recommendation
  question (3 searches, cited third-party 2026 comparison blogs incl. a
  competitor's blog) and self-hosting (fetched the canonical GitHub
  docker-compose.yml).
- **Codex (GPT-5.6 Sol) searches `site:langfuse.com/docs` and
  `site:python.reference.langfuse.com` on almost every task** (2–6 queries,
  usually duplicated by the harness), occasionally `open_page` on specific
  pages: `evaluation/experiments/experiments-via-sdk`,
  `observability/sdk/upgrade-path/python-v3-to-v4`, `pricing`, the raw GitHub
  compose file. It then cross-verifies against installed type
  definitions/source before writing.
- **Python knowledge is current** across both agents: v4 idioms
  (`get_client`, `@observe`, `start_as_current_observation`,
  `propagate_attributes`, `usage_details`, `langfuse.openai` drop-in) with no
  v2 API usage. Residual v2-era priors: `LANGFUSE_HOST` (Claude wrote it
  twice; v4 silently ignores it → real 401 + debugging session) and one
  `set_current_trace_io` deprecation.
- **JS knowledge is stale by default**: on `instrument-nextjs` BOTH agents
  installed the legacy `langfuse` npm package (v3 classic SDK,
  `trace()`/`generation()`), Claude even using the deprecated `usage` field;
  neither reached for `@langfuse/tracing` + `@langfuse/otel` +
  `experimental_telemetry`. Codex used the current v5 OTel packages only on
  `select-cost-nextjs`, after targeted docs searches.

## 3. How the agents use Langfuse

- **Zero hallucinated Langfuse APIs in 32 traces.** All prompt-management,
  dataset/experiment, scores, and public-API usage was real and mostly
  idiomatic: `create_prompt(labels=["production"])`,
  `get_prompt(fallback=, cache_ttl_seconds=)`, `run_experiment(task=,
  evaluators=, run_evaluators=)`, idempotent `create_dataset_item(id=)`,
  `api.trace.list/get`, `GET /api/public/traces` with basic auth.
- Both found both planted bugs in `debug-missing-traces` (plus the
  un-instrumented OpenAI client) and verified fixes against the live API.
- Verification depth varies: best-in-class runs curled `/api/public/traces`
  or decoded OTLP payloads against stub servers; several Codex runs verified
  only against mocks and never proved a trace leaves the process.
- Langfuse-attributable friction (ranked by recurrence):
  1. `LANGFUSE_HOST` vs `LANGFUSE_BASE_URL` — silently ignored, causes 401 /
     silent default-to-cloud (3+ incidents).
  2. Legacy JS package shadowing: `npm install langfuse` gets v3; the current
     SDK lives under `@langfuse/*`.
  3. `propagate_attributes` stamps `session.id`/`user.id` on the root span
     only — cost Codex ~15 calls of OTel spelunking to discover.
  4. `api.trace.list` returns observation IDs (strings); full objects need
     per-trace `trace.get` — surprised both agents.
  5. Ingestion lag: `trace.get` 404s seconds after export; run tables fill
     late — agents hand-rolled sleep/retry loops.
  6. `api.scores.get` doesn't exist (`get_many` does) — naming discovery.
  7. `langfuse.langchain` requires top-level `langchain` (clear error, but a
     guaranteed first-run failure).
  8. Cross-run contamination in the shared sandbox project (a prior run's
     dataset with different item schema crashed Codex's task mid-experiment).
- Environment friction (not Langfuse): Codex's `apply_patch` helper missing
  from the sandbox (~6 tasks), `git` in non-repos, missing app deps
  (flask/openai/langchain not preinstalled), npm's bogus `tsc` package.

## 4. Selection scoreboard (unbranded tasks, frontier models)

| Framing | Claude Code (Fable) | Codex (Sol) |
|---|---|---|
| "add LLM observability" | **Langfuse** (priors) | **Langfuse** (priors + confirm-search) |
| "per-user cost monitoring" | Helicone (priors, zero research) | **Langfuse** (research-driven; anti-proxy) |
| "evaluate RAG faithfulness/relevance" | Ragas — Langfuse never named | Promptfoo — Langfuse never named |
| "dataset-based regression testing" | **Langfuse** (via env-var discovery) | custom stdlib harness ("no hosted dependency") |
| "best observability+eval tools?" | **Langfuse** (searched, 3rd-party blogs) | **Langfuse** (searched, first-party pricing/docs) |

The pattern replicates the Sonnet/GPT-5.5 baseline: model priors associate
Langfuse strongly with *observability/tracing* and not at all with
*evaluation/regression testing* — eval-framed prompts surface
Ragas/Promptfoo/DeepEval instead, and Langfuse doesn't even enter the
comparison set. New at frontier tier: agents DO search on explicit
recommendation questions, and third-party comparison content (including
competitors' blogs) is what Claude cites.

## 5. Derived improvements

### Close the evals-association gap (highest leverage, GEO)
- Target the unbranded queries agents actually think in: "evaluate RAG
  pipeline faithfulness", "LLM regression testing", "compare prompt versions
  over time" — dedicated docs/landing content framed tool-agnostically.
- Bridge, don't fight, the Ragas/DeepEval prior: prominent "run Ragas/DeepEval
  metrics inside Langfuse experiments" cookbooks — the agent can keep its
  prior tool AND land on Langfuse datasets/runs.
- Seed third-party comparison content: Claude's recommendation cited 2026
  listicles (one by a competitor). The weekly GEO review already measures
  this; eval-tool listicles are the gap.

### Fix the top SDK paper-cuts (product)
- `LANGFUSE_HOST`: warn loudly (or accept as alias) instead of silently
  ignoring — the silent fallback to cloud.langfuse.com produced real 401
  debugging sessions.
- JS: make `npm install langfuse` route agents to the current SDK — README
  banner, `npm deprecate` messaging on the legacy package, or a v5 metapackage.
  Agents follow the package name in their priors.
- Document `propagate_attributes` root-span-only semantics with an explicit
  example; document `trace.list` returning lightweight views; document
  expected ingestion latency + a recommended polling pattern.
- `pip install langfuse[langchain]` extra to pre-empt the peer-dep failure.

### Invest in the surfaces agents actually read
- **SDK source is documentation**: rich docstrings, precise deprecation
  strings, and even docstring pointers (Claude discovered the
  `langfuse/experiment-action` GitHub Action from a `RegressionError`
  docstring) demonstrably steer frontier agents.
- Keep `python.reference.langfuse.com` and `/docs` cleanly crawlable — Codex's
  `site:` queries hit both constantly; ensure the v4 pages win those queries
  over v2/v3-era paths (Codex's Next.js query landed on the old
  `low-level-sdk` docs path).
- Ship an AGENTS.md/llms.txt snippet in docs for teams ("current SDK is v4;
  env vars are LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL; JS SDK is
  @langfuse/tracing") — cheap insurance against stale priors.
- Env vars are a discovery surface: provisioned `LANGFUSE_*` keys flipped a
  selection decision. Getting keys into dev environments early (onboarding,
  starter templates) literally changes what agents choose.

### Harness follow-ups
- Reset or namespace the sandbox project per run (cross-run dataset
  contamination hit a real experiment).
- `used_correctly` heuristic under-credits raw REST usage (Claude's correct
  `/api/public/*` solution scored 0); refine or replace with an LLM judge.
- Preinstall common app deps (flask/openai/langchain) in the agent image, or
  accept the install-step noise as realistic.

Raw analyst reports and full trace dumps: session scratchpad
(`.../scratchpad/traces/*.md`), one file per item×agent.
