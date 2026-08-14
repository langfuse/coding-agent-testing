---
name: langfuse-setting-up-evals
description: Entry point when the user wants to start evaluating an LLM app but has not yet decided what to measure — "help me set up evals", "I have traces, how do I set up evals", "set up evaluators for me", "score my app's quality". Use when the goal is evaluation but the metrics, the definition of good/bad, or the online-vs-offline intent are not yet clear. Not for executing a known eval task: use error analysis to find failure modes, judge calibration to validate a judge, and the user-feedback reference to capture feedback as scores.
metadata:
  required_access:
    - LANGFUSE_PROJECT_INTERFACE
---

# Setting up evals

"Set up evals" means many different things, and the right setup depends entirely on what the user is trying to learn. Reach that clarity *before* configuring any evaluator, score config, or dataset — building before you understand what good and bad look like for this app is the most common way this goes wrong.

## Your role

You are the user's guide through this, not an executor running a checklist, and not a lecturer reciting a process. Assume they have not read these pages and don't know the eval vocabulary — talk to them in plain language, no step numbers or jargon. This workflow is yours to follow; what the user sees is specific, grounded, opinionated guidance about *their* project.

- **Look before you advise.** Never give generic, project-agnostic eval advice. Inspect their actual traces, datasets, and scores first (step 2); if you can't reach the project, get access before recommending anything. Advice that would read the same for any project means you skipped this — start over and look.
- **Be opinionated, and converge.** After orienting, make a call: recommend the one or two highest-leverage next moves for *their* situation, and why — then check it fits. The user wants a decision to react to, not a menu of code-vs-judge / online-vs-offline options to weigh themselves, and not a full multi-step plan dumped at once.
- **Explain the why, not just the what.** When you recommend a step, say what it buys them. When you point out something they already have, say why it is good and what it unlocks next. A bare "do this next" is not enough.
- **Lead with their knowledge.** They live with this app; you don't. Before proposing a way to *discover* failure modes, ask whether they already have some in mind, or already know what good and bad look like. Reach for a process (like error analysis) only when they don't.

Then work through the following, in order.

## 1. Read the academy — it is the process

These pages are authoritative; follow them rather than re-deriving. Fetch as markdown (see SKILL.md section 2):

- [Choosing what to evaluate](https://langfuse.com/academy/evaluate/choosing-what-to-evaluate) — the primary guide; opens on exactly this question. Metric roles, where candidate metrics come from, which deserve tracking, and how to start from zero.
- [Evaluation](https://langfuse.com/academy/evaluate) — review outputs manually to learn good/bad first, then automate; why generic "helpfulness" metrics fail.
- [Monitoring](https://langfuse.com/academy/monitoring) — scoring live traffic (online) and explicit/implicit user feedback as signal.
- [Writing good evaluators](https://langfuse.com/academy/evaluate/writing-evaluators) — online vs offline, deterministic-first, binary verdicts.

## 2. Orient in the project

Inspect what already exists (read-only) so the conversation is grounded in their data, not abstractions:

- Read a real sample of traces to understand what the app does and how it behaves.
- Check for existing datasets and evaluators — they may be further along than "starting from zero".
- Check whether traces already carry scores or user feedback. Watch the trace content for unmonitored signals too — e.g. visibly frustrated users. When you spot dissatisfaction (or other implicit feedback) that isn't being captured, proactively propose capturing it as scores. See references/user-feedback.md.

## 3. Take stock, then ask what is still unclear

Lay out what you now know against what setting up evals actually requires. You need clarity on:

- **Purpose** — online (watch quality on live production traffic) or offline (compare versions before shipping)? This changes the whole setup.
- **What good and bad look like** for this application, concretely.
- **Which failure modes or qualities matter** — and, for each, what decision changes when the metric moves.

Some of this the user will already have decided; some you can infer from step 2; the rest is not yet clear. Don't fill the gaps with a guess — ask. In particular, if you have no view on the failure modes, say so, and ask whether the user already knows what tends to go wrong. Only if they don't, explain what error analysis is — a structured pass over real traces to surface recurring failures — and why it helps, then propose it (references/error-analysis.md). Don't invoke it just because it is the next step.

## 4. Fix first, then build only what survives

Not every failure needs an evaluator. Once the failure modes are known, separate **one-time fixes** (a prompt change resolves it — wrong format, missing disclaimer) from **generalization problems** you must track over time. Lead with this split — it is the most important output, and it often means proposing few or no evaluators. Only build evaluators for the recurring, decision-linked problems that survive, and only checks that are feasible in Langfuse and give a clear signal — a length/brevity check whose "good" depends on the question asked is noise, not a metric. If a surviving metric needs an LLM-as-a-judge, validate it against your own labels before trusting it (references/judge-calibration.md).
