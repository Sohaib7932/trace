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

## Unified transcript setup — 2026-11-05

The native Codex hook definitions remain unchanged. `codex_session_log.py` now also
redacts OAuth callback values, environment assignments and short unquoted secrets.
It still captures only native prompt/final fields; it never falls back to a guessed
answer or silently imports historical JSONL.

Both agents use `.claude-logs/<YYYY-MM-DD_HH-MM-SS>_<session-id>.md`. The required
cohort frontmatter, statistics and PROMPT/RESPONSE markers are retained. Agent
attribution remains `codex` or `claude-code`; Codex is never presented as Claude.

The repository's Claude entry point, `.claude/hooks/extract-log.py`, now delegates
to `scripts/agent_session_logs.py hook --agent claude`. The existing prompt/stop
commands are preserved. Only the old logging `SubagentStop` handler was removed:
new logs must not contain delegated reports. Existing historical logs are retained.
The adapter reads the exact native `transcript_path`, session ID and cwd, not the
most recently modified file. Historical Claude final answers require explicit
terminal metadata; a genuine Stop can confirm only an intact final candidate.
If Claude has not appended a submitted prompt yet, capture remains pending until
the transcript supplies it. No source timestamp or missing answer is invented.

### Explicit transcript recovery

`agent_session_logs.py` provides a separate, opt-in transcript reader:

```powershell
python -B scripts/agent_session_logs.py export --agent codex --session-id SESSION_ID --transcript ABSOLUTE_JSONL_PATH --dry-run
```

Use `--agent claude` for an actual Claude JSONL. Remove `--dry-run` only after
reviewing the selected session. Codex's observed `final_answer` phase and
`task_complete` mirrors are deduplicated by turn ID. Tools, commentary, reasoning,
injected context and subagent/guardian transcripts are excluded. For paginated
Codex sessions, provide every ancestor with repeated `--transcript` arguments;
the recorded byte and ordinal cutoffs must agree. Unrelated branches are rejected.
Related worktree source directories require explicit `--source-cwd` arguments and
must resolve to the same Git common directory as the target project.

Exports identify themselves as transcript exports, not automatic capture. Existing
native/legacy logs, including reconstructed filename variants, are preserved and
reported instead of overwritten or duplicated. Exporter-managed logs are updated
atomically under the same session lock and repeated identical exports do not
rewrite them. There is no background watcher or automatic history scan.

### Scope and installation

The owner explicitly chose **repository-only configuration**. No global Claude or
Codex settings, hook trust records, or Git ignore settings were changed.

An optional installer is included for a future explicitly approved machine setup:

```powershell
python -B scripts/setup_agent_session_logging.py --project ABSOLUTE_REPOSITORY_ROOT
```

This is a dry run. `--apply` would register only explicitly selected checkout
roots, install `~/.claude/extract-log.py`, and merge only UserPromptSubmit/Stop into
`~/.claude/settings.json` while preserving other settings and making a private
backup. That global installation was **not applied**. The repository hooks already
call the shared implementation directly, so the global wrapper is optional.

### Verification and limitations

- Installed versions: Codex `0.166.0-alpha.5.1`, Claude Code `2.1.72`, Python `3.13.5`.
- A fresh, tool-free, read-only Codex CLI session produced the actual final
  `TRACE_CODEX_LOGGING_OK`; native hooks captured its prompt and final in one file.
  A separate read-only transcript extraction confirmed the actual pair. No hook
  trust bypass was used and the test was not manually written into a log.
- The ongoing desktop session's latest three prompts and latest three already
  emitted finals were independently matched to genuine Codex records. A current
  unfinished turn is never given a prewritten final answer.
- Claude is installed but signed out, and its local project transcript directory
  is empty. Claude parser/hook tests are synthetic fixtures only; live Claude
  capture and genuine historical Claude recovery cannot be claimed on this PC.
  After private sign-in, review `/hooks`, submit a harmless prompt, and inspect
  the resulting PROMPT/RESPONSE pair under this checkout's `.claude-logs/`.
- No historical log was rewritten, removed or backfilled by this setup. Existing
  primary-history overlaps and provisional coverage gaps remain available for a
  separate, reviewed recovery task; no duplicate recovery file was created.
- Tests use temporary fixtures for privacy filtering, finality, pagination,
  idempotency, concurrency, scope isolation, global-setting preservation and
  atomic failure. Run `python -B -m unittest discover -s scripts/tests -q`.

The guide's agent-specific transcript assumptions were adapted to the installed
schemas. Current lifecycle references: [Codex hooks](https://learn.chatgpt.com/docs/hooks)
and [Claude Code hooks](https://code.claude.com/docs/en/hooks).

## Authorized primary-conversation completion — 2026-11-05

The owner subsequently authorized recovery of every genuine input and emitted
final in this particular conversation. The existing canonical file remains
`.claude-logs/2026-10-31_10-25-36_01a18c8a-4fc7-70a0-bf35-3113cfa88f29.md`.
No additional file for that session was created. Older reconstructed history and
its index remain unchanged as dated snapshots; they must not be counted as new
conversations or added again to the canonical totals.

At the bounded recovery checkpoint, the canonical file contains **131 actual
human input messages and 102 emitted final answers**. This includes 28 genuine
question-reply messages and 22 additional inputs sharing an existing native turn.
All 176 original native entries and 24 historical snapshot entries retain their
text, timestamps, native turn IDs and capture provenance. Another 33 previously
missing entries are explicitly labelled `CodexTranscriptRecovery`. Presentation
numbers now follow the human-input sequence; previous native exchange numbers
are retained as metadata. Every actual source message has its own source message
ID and ordinal, rather than being collapsed into a single prompt per turn.

Two genuine native prompts survived in older parent tails that are outside the
current pagination chain. They remain intact with `source_coverage: native_hook_only`;
no replacement source identity was invented. One actual final came from a native
`resume_interrupted_task` without a new user input. It is preserved as an explicit
unpaired RESPONSE (`num=0`, `unpaired_final: true`), with no fabricated prompt.
Interrupted turns without an emitted final remain unanswered. The final response
to the current request cannot be prewritten; the real Stop hook captures it only
after it is emitted, so the counts above are a verification checkpoint.

`scripts/complete_codex_conversation.py` is an explicit recovery command, **not a
hook**. It requires owner-selected primary JSONL segments, the existing canonical
file and approved source checkouts belonging to the same Git repository. Dry-run
is the default. Application requires a verified byte-for-byte backup outside the
repository, holds the native session lock, validates the rendered log in memory,
then replaces it atomically and reads it back. Repeating the authorized completion
leaves both bytes and modification time unchanged. Original JSONL, other logs,
global settings, databases and application files are not modified.

Native hooks retain their original definitions. The renderer supports chronological
recovery metadata and Stop still associates the final with the primary input of
its native turn. Future automatic capture of several distinct human inputs sharing
one turn is not guaranteed by the one-prompt-per-turn native payload handler;
explicit transcript completion is available to reconcile those inputs accurately.
No global installer, background watcher or trust bypass was activated.


## Company guide alignment on this checkout, 2026-11-05

The owner explicitly chose the company policy: primary prompts/finals **plus
subagent briefs and final reports**. This supersedes the primary-only policy in
older dated sections above. Tool operations/results, reasoning, commentary and
injected editor context remain excluded. There is one canonical session file in
`.claude-logs/`; delegated entries appear under `# Subagents` using the company
`SUBAGENT_PROMPT` and `SUBAGENT_RESPONSE` markers. They do not inflate primary
conversation statistics.

Both repository hook configurations now include `SubagentStop`. Claude reads only
its exact parent transcript and its session-specific subagents directory. Codex
keeps native primary payload capture and uses the explicit child transcript from
the subagent event, requiring matching child/parent IDs and project ancestry.
Unknown child transcript schemas fail closed. No general tool hooks were added.
Handback tool messages are retained as reports; tool arguments/results from other
operations and closing narration after a handback are excluded.

Claude parsing now follows attachment/meta ancestry without logging those nodes,
and accepts cwd changes inside this checkout. GitHub CLI is absent on this PC;
that no longer suppresses logging. Git identity remains recorded, email is masked,
and GitHub identity is explicitly `unknown` unless a noreply Git identity is
available. No GitHub verification is invented. Existing verified sessions still
reject an identity change.

The existing Claude canonical file ending `ac502e61-757d-4998-a421-8b1428fcceb3.md`
was explicitly reconciled from its genuine local JSONL: **100 prompts, 87 proven
final responses, one delegated brief and one final report**. Interrupted or
unproven answers remain absent. This was manual source-based reconciliation, not
automatic capture. Its original bytes were backed up and verified outside the
repository under the local user's `.codex/log-repair-backups/`. The canonical file
records the prior SHA-256 and recovery provenance. Future normal Claude hooks can
update this managed file; the previous legacy file had been preserved without
updates by the exporter.

Historical reconstruction files and the four old suggested-message artifacts are
preserved, as required by the project's history policy. They are **not additional
canonical conversations** and do not establish current capture. Their source
sessions belong to another checkout; this review does not claim to reconcile all
historical files. The current Codex transcript also lacks the record ordinals
required by the older full-history completion utility; no history was fabricated
to bypass that check.

Validation: 177 isolated script tests pass, including footer round trips,
redaction, concurrent primary capture, replay idempotence, parent/child scope,
handback handling, changing directories and excluding IDE context. Genuine local
Claude extraction was checked separately. These tests do not prove new hook
activation. **Review the changed definitions in `/hooks`**, then verify a genuine
prompt and emitted final across subsequent turns. Trust settings and global agent
settings were not modified. Earlier live-verification claims in this document
refer to their dated machine/session, not this checkout's new definitions.

References: [Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[Claude hooks](https://code.claude.com/docs/en/hooks#subagentstop).
