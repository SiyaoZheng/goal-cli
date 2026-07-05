# goal-cli Skills

`goal-cli` ships two agent-facing skills. They are written for users who can
judge the artifact but do not want to hand-configure the control loop.

## Which Skill to Use

| Skill | Audience | Use it for |
| --- | --- | --- |
| [`goal-cli-project-setup`](../skills/goal-cli-project-setup/SKILL.md) | Non-expert users and their coding agents | Discover the artifact, synthesize the producer, write `goal.toml`, validate setup, and run safe checks. |
| [`goal-cli-template-author`](../skills/goal-cli-template-author/SKILL.md) | Maintainers and advanced users | Add reusable templates, tik oracle scripts, project-family examples, and skill/docs updates. |

Use `goal-cli-project-setup` first for real projects. Use
`goal-cli-template-author` only when improving the reusable material in this
repository.

## One-Click Agent Prompt

Paste this into an agent with access to the target project:

```text
You are configuring this repository for goal-cli.

Read the goal-cli onboarding context from llms.txt if present. Then use the
goal-cli-project-setup skill. Discover the canonical artifact, synthesize a
stable producer command or wrapper, write or update goal.toml, protect generated
outputs, keep tok write scopes narrow, and run validation.

Required checks:
- run the producer directly and prove the artifact exists;
- run goal-cli validate;
- run goal-cli doctor;
- run goal-cli run --dry-run;
- run Codex smoke checks only if the configured providers require them.

Do not edit raw data, generated artifacts, .git/, or .goal/. Ask me only if the
canonical artifact cannot be inferred safely. Finish by reporting the artifact
path, producer command, tik provider, tok write_dirs, generated_dirs, and the
next exact command I should run.
```

## Installing the Skills

If your agent supports local skills, copy the relevant skill directory into the
agent's skill folder. For Codex-style skills, this is commonly:

```bash
mkdir -p "$HOME/.codex/skills"
cp -R skills/goal-cli-project-setup "$HOME/.codex/skills/"
cp -R skills/goal-cli-template-author "$HOME/.codex/skills/"
```

If your agent does not support skill directories, paste the contents of the
needed `SKILL.md` file into the agent's instruction context.

## Expected Project Output

After `goal-cli-project-setup` runs in a target project, the project should
have:

- a canonical artifact path;
- a stable producer command, often `scripts/goal_producer.sh`;
- a `goal.toml` that names the artifact, producer, tik provider, tok write
  scopes, and generated dirs;
- passing `goal-cli validate`;
- a clear `goal-cli doctor` status;
- a dry-run prompt render from `goal-cli run --dry-run`.

Only after those checks should a user run a real heartbeat:

```bash
goal-cli run --max-minutes 30
```
