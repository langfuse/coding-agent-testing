# Temporary runtime skills

This folder is a staging area for skill experiments. Skill versions committed
here are temporary test inputs and are not intended to be merged into the
repository's target branch.

To run an experiment, add the skill below this folder on a temporary branch.
Each skill must have a `SKILL.md` entrypoint with `name` and `description`
fields in its YAML frontmatter:

```text
runtime-skills/
  my-skill/
    SKILL.md
    references/
    scripts/
```

Commit and push the skill, then select it by its exact commit and path in the
experiment payload. The branch does not need to be merged, but the commit must
be available from `langfuse/internal-ax` while the experiment runs.

The harness only installs the selected directory in the agent environment. It
does not mention, invoke, or otherwise add the skill to the dataset prompt.
After testing, the temporary branch can be deleted.
