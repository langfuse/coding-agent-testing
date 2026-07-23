# Runtime skills

Put Agent Skill directories below this folder. Each skill must have a
`SKILL.md` entrypoint with a simple `name` field in its YAML frontmatter:

```text
runtime-skills/
  my-skill/
    SKILL.md
    references/
    scripts/
```

Experiments select a skill by exact commit and path. The commit may be on an
unmerged branch, but it must exist in the local clone for local Docker runs and
must be pushed to `langfuse/internal-ax` for deployed Modal runs.

The harness only installs the selected directory in the agent environment. It
does not mention, invoke, or otherwise add the skill to the dataset prompt.
