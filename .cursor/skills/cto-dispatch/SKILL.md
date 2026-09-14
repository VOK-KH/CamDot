---
name: cto-dispatch
description: CTO manager workflow that reads .cursor/job.json, assigns jobs to specialist subagents, and writes status back. Use when the user mentions job.json, dispatch, CTO, manager agent, subagents, assign task, or run queued jobs.
---

# CTO dispatch

Parent agent = **CTO**. Specialists do the work. The queue is `.cursor/job.json`. Schema notes: [schema.md](schema.md).

## When invoked

1. Read `.cursor/job.json`.
2. Summarize: id, title, assignee, status, priority, blockers.
3. If `policy.auto_start` is false, wait for the user to say run/dispatch unless they already did.
4. Select work: lowest `priority` number first among `pending` jobs whose `depends_on` ids are all `status: done`. Cap parallel launches at `policy.max_parallel`.
5. For each selected job, Task-launch `job.assignee` (must match a file in `.cursor/agents/`). Prompt must include: job id, title, acceptance, files, and the full `prompt` field. Independent jobs: one message, multiple Task calls.
6. After a subagent returns, patch that job in `job.json` (`in_progress` while running; then `done`, `blocked`, or `pending` with notes). Never rewrite unrelated jobs.
7. Report to the user: what ran, what is next, what is blocked.

## Assignee map

| assignee | Use for |
| --- | --- |
| `explorer` | Read-only map of files, flows, ownership |
| `gui-engineer` | PySide6, widgets, dialogs, theme, shortcuts |
| `core-engineer` | collect, download, scrape, urls, store, yt-dlp |
| `qa-tester` | unittest, reproduce, regression |
| `reviewer` | Read-only review of a finished job |
| `cto` | Planning only; do not implement product code |

## Do not

- Implement a specialist job in the parent when a matching subagent exists.
- Launch a job whose dependencies are not `done`.
- Change `policy` unless the user asked.
