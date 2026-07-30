# Test a skill version

The harness can install one skill from an exact commit without changing the
dataset prompt. The commit must be pushed to `langfuse/internal-ax`, but it does
not need to be merged.

Company infrastructure—including Modal, credentials, and the Langfuse
webhook—is maintained centrally. Experiment runners only need access to the
Langfuse dataset and the skill's commit and path. If the company webhook is
unavailable, ask an internal-ax maintainer.

If the experiment also needs new harness code or a starter workspace under
`envs/`, merge and deploy those changes first. A dataset item's
`metadata.env_folder` must exactly match the merged path.

## 1. Push the skill version

Add the version below `runtime-skills/`. The selected directory must contain a
`SKILL.md` with `name` and `description` in its YAML frontmatter:

```text
runtime-skills/
  my-skill/
    SKILL.md
    references/
    scripts/
```

Do not change the dataset prompt to mention the skill. Commit and push the
version, then copy its full SHA:

```bash
git add runtime-skills/my-skill
git commit -m "Add my-skill version for experiment"
git push -u origin HEAD
git rev-parse HEAD
```

Keep the commit available until the experiment finishes.

## 2. Trigger the experiment

In the harness Langfuse project:

1. Open the dataset.
2. Select **Start Experiment** → **Custom Experiment** → the ⚡ trigger.
3. Select the existing company Modal webhook.
4. Paste the run configuration into the **payload** field.

For the prompt-migration experiment on `skill-testing/prompt-migration`:

```json
{
  "run_configs": ["claude-code", "codex"],
  "run_name": "prompt-migration-skill-<short-sha>",
  "skill": {
    "commit": "<full-40-character-sha>",
    "path": "runtime-skills/langfuse"
  },
  "reset_sandbox": true
}
```

`skill.commit` must be the full SHA. `skill.path` is the directory containing
`SKILL.md`. Leave `reset_sandbox` as `true` unless the experiment needs
artifacts from an earlier run.

## 3. Compare the result

To measure the skill's effect, run the same dataset without the `skill` object:

```json
{
  "run_configs": ["claude-code", "codex"],
  "run_name": "prompt-migration-baseline",
  "reset_sandbox": true
}
```

Keep all other settings the same. Click **Run** once per variant. Runs appear
only after their first result is linked, so the **Runs** tab may remain blank
for several minutes.

Results appear as `<run_name>-claude-code` and `<run_name>-codex`. After both
finish, the test branch can be deleted or retained for later experiments.
