# Codex cohort session logging

Claude Code and Codex share exactly one canonical repository directory:

`.claude-logs/<timestamp>_<session-id>.md`

Codex retains the cohort frontmatter, statistics, and exact entry markers:

`[CLAUDE_LOG_ENTRY type=PROMPT num=N session=SESSION_ID]`

`[CLAUDE_LOG_ENTRY type=RESPONSE num=N session=SESSION_ID]`

The header attributes the actual agent as `agent: codex`. No `.codex-logs/`,
`codex-logs/`, background watcher, or other repository transcript directory is used.

## Native integration

The project-level `.codex/hooks.json` registers only `UserPromptSubmit` and `Stop`.
Its command resolves the Git root before loading `scripts/codex_session_log.py`.
Windows uses `python`; macOS/Linux use `python3`. The Windows command was checked
from a project subdirectory with an explicitly rejected smoke-test event.

The handler reads the actual JSON object provided on stdin:

- `UserPromptSubmit`: `session_id`, `turn_id`, `prompt`, `cwd`, optional `model`.
- `Stop`: `session_id`, `turn_id`, `last_assistant_message`, `cwd`, optional `model`.
- An event-provided timestamp is retained when supplied. Otherwise capture time
  is recorded in UTC, explicitly labelled `timestamp_source: hook_capture_time_utc`.

Only those text fields are captured. Extra fields such as tool output, reasoning,
environment values, or transcript paths are ignored. Subagent events and known
injected context, including the app-generated suggested-next-message envelope,
are rejected. Common secrets and private contact addresses are
redacted; a masked Git email is explicitly marked as redacted.

The adapter does not parse internal Codex JSONL, discover old sessions, read pasted
attachments, or backfill history. `Stop` without a previously captured matching
prompt reports a failure instead of inventing or recovering a prompt. A missing
`last_assistant_message` never becomes a guessed final answer.

Official lifecycle contract: <https://developers.openai.com/codex/hooks>

## One stable session file

Both handlers update the same session file. A native prompt gets its exchange
number; the final response joins it by turn ID, including if Stop events arrive
out of order. Replayed events leave the file unchanged. Conflicting repeats fail
without replacing the original. Entries have character counts, so quoted marker
text in a user prompt cannot be mistaken for another recorded exchange.

Updates hold an OS advisory lock for the checkout/session, then write a complete
UTF-8 temporary file and atomically replace the Markdown file. Lock files contain
one byte, live in the OS temporary directory, and are not transcripts. Process
failure releases the lock. Unique session IDs keep different developers' files
separate; identity checks reject mixing developers within one session. Existing
files attributed to another agent are never overwritten.

## Both developers

Each checkout requires Python 3.10+ and Git/GitHub CLI. This machine was checked
with Python 3.13.5, Codex 0.165.0-alpha.1.2, and GitHub CLI 2.83.1.

Each developer signs into their own GitHub CLI account and configures their own
Git author name/email. No teammate-specific username is hardcoded in tracked
configuration. On a session's first capture, the adapter checks `gh auth status`
and verifies the active account through `gh api user`. Subsequent events reuse
that session's verification only while both the active account and Git identity
still match. Authentication tokens are never written to the log.

Both developers clone/pull the same hook and script files; each runs them in their
own checkout. Logs belong to that checkout's `.claude-logs/` directory. Neither a
repository owner's name nor a connected app's unrelated identity is substituted.
A teammate's machine has not been tested by the setup on this machine.

## Human trust and live acceptance

New or changed native hook definitions require review/trust through `/hooks`.
No hook trust record is edited by this implementation, and no bypass option is used.
These hook command definitions were already reviewed by the user and remain unchanged.

A configuration or handler test is not a real human session test. To accept this
integration, observe an actual submitted prompt, its actual emitted final answer,
and a later real exchange in one stable file, without excluded content. Never
prewrite an anticipated final answer or call a manually invoked test automatic.

For a fresh desktop test: fully quit Codex, reopen it, return to the existing Trace
chat, and type a real project prompt. Then inspect capture and repeat with another
real prompt. The user completed a full desktop restart on 2026-10-31; the first
genuine prompt after that restart was automatically captured.

A supported native CLI continuation of this same chat is also available:

```powershell
codex -C "C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1" resume 01a18c8a-4fc7-70a0-bf35-3113cfa88f29
```

Enter genuine project prompts yourself. Do not run simultaneous turns for this
same session in the desktop and CLI. This command resumes existing history; the
capture adapter itself does not export it.

## Checks performed and live verification

- Original company guide read from the supplied Downloads path.
- Actual repository/session root: `C:\Users\soore\OneDrive\Dokumen\ChatGPT\Trace-v1`.
- Surface: Codex Desktop; local transcript metadata reports the bundled CLI version
  `0.165.0-alpha.1.2`. Python executes the hook command on Windows.
- Effective native config layers inspected: system, user, and this project.
  Only this project's two hook definitions were discovered. Both are enabled and
  trusted; no duplicate definitions, config errors, or managed-only hook restriction
  appeared. User hook-trust state and unrelated notification settings are preserved.
- Local developer attribution was verified as Soorej S / SoorejS. The handler now
  verifies each developer itself and does not require the previous custom local
  `codexLogging.*` attribution keys.
- Twenty-three handler tests pass, covering native payload pairs, repeated events,
  a second exchange, Unicode, timestamps, redaction, wrong-agent collisions,
  developer identity changes, out-of-order replies, and concurrent processes/replays.
  All synthetic test records were written only to temporary fixture directories.
- Existing `.claude/settings.json`, `.claude/hooks/extract-log.py`, and the tracked
  Claude session log are unchanged. Their existing behavior is not rewritten.
- Confirmed old-code defect: it ignored the documented prompt/final fields and
  required internal rollout data. That dependency has been removed completely.
- The old desktop processes predated the hook file and produced no Codex cohort
  file. On 2026-10-31 the user restarted the app: the parent process started at
  10:23:15 IST and new native processes started at 10:23:26 and 10:24:04 IST.
  The installed desktop package also changed during this restart, so restart alone
  is not established as the cause of the earlier failure.
- The genuine `logging check` prompt was automatically captured at 10:25:36 IST in
  `.claude-logs/2026-10-31_10-25-36_01a18c8a-4fc7-70a0-bf35-3113cfa88f29.md`.
  It has the native turn ID, Codex attribution, cohort statistics and PROMPT marker.
  No handler was manually invoked to create this record; no history was backfilled.
- At 10:26 IST, the same stable file contained two genuine `logging check` prompts
  and the first turn's actual emitted final answer. Read-only comparison with the
  local session record confirmed the captured final exactly matches the emitted
  final, and both prompts exactly match the submitted text. The first prompt and
  final share their native turn ID; the second prompt has a new turn ID and exchange
  number. Frontmatter reports two exchanges and one response. The second turn's
  final had not been emitted at inspection time.
- Both native lifecycle handlers are now verified on this machine across genuine
  turns. The file contains only prompts and final-answer text: no commentary,
  tool output, reasoning, injected Page context, or recovered historical messages.
  These real records were created by automatic hooks, not by the validation script.

Run the isolated handler tests with:

`python -B -m unittest discover -s scripts/tests -v`

## Final commit audit finding (2026-10-31)

The final review found four separate Codex files containing only the app-generated
suggested-next-message envelope. Those are not human session records. Their original
files remain untouched and untracked; they are excluded from the reviewed commit.
The genuine session file ending `01a18c8a-4fc7-70a0-bf35-3113cfa88f29.md`
contains actual prompts and emitted final answers and is included. The adapter now
rejects that observed envelope; one added regression test also confirms ordinary
human requests for suggestions remain valid. The original 23 tests are preserved.
Hook definitions and hook trust state are unchanged. This tests the known envelope,
not every possible future app-generated message format. Historical Claude logging
behaviour and its already-tracked session record are preserved as originally stored.

Keep `.claude-logs/` tracked and include it with any user-authorized commit.
This logging task itself does not authorize committing or pushing.
