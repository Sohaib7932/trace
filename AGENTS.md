<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Session Logs

`.claude/settings.json` runs `.claude/hooks/extract-log.py` on `UserPromptSubmit`, `Stop` and `SubagentStop`, writing prompt + final-response transcripts to `.claude-logs/`. Each session file ends with a "Subagents" section. Always commit `.claude-logs/` with your changes.

`.claude-logs/` is the single log directory for every agent and every teammate (Claude Code, Codex, Cursor, etc.). Never add it to `.gitignore`, and don't create per-agent folders like `.codex-logs/`.
