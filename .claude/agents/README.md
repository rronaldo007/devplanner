# Project agents

Custom [Claude Code subagents](https://docs.claude.com/en/docs/claude-code/sub-agents)
for the DevPlanner project. Each `*.md` file here defines one agent that can be
launched via the `Task`/`Agent` tool to handle a focused, multi-step job in its
own context.

## File format

```markdown
---
name: my-agent
description: One line on when to use this agent (used for auto-selection).
tools: Read, Glob, Grep, Edit, Write, Bash   # optional; omit to inherit all
model: sonnet                                 # optional: opus | sonnet | haiku
---

System prompt for the agent — its role, what it should do, conventions to
follow, and what to return.
```

- `name` — kebab-case, unique.
- `description` — written so the model knows *when* to delegate to it.
- `tools` — optional allowlist; omit to inherit the full toolset.
- `model` — optional override.

Drop a new `.md` file in this folder and it becomes available as a subagent.

## Agents here
- `django-reviewer.md` — reviews Django changes against this project's conventions.
