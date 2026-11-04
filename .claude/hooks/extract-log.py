#!/usr/bin/env python3
"""Extract clean conversation logs from Claude Code sessions.

Based on the company "Agent Session Logs" guide. Local changes (so it runs the same on
Windows, macOS and Linux for every teammate):
  - get_project_session_dir() uses Claude Code's real folder naming (every non-alphanumeric
    character becomes '-') and matches case-insensitively, so `C:\\Users\\x\\repo` finds
    `c--Users-x-repo`. Git Bash style paths (`/c/Users/...`) are converted first.
  - Transcripts are read and logs written as UTF-8 (Windows defaults to cp1252).
  - Only what a person typed is a PROMPT: automatic context summaries and "[Request
    interrupted by user]" markers are not. Pasted text keeps its exact words; only the
    editor's internal <pasted_content> wrapper is removed. Attachments are noted, not stored.
  - Prompt text is written inside a fenced block so it shows exactly as typed on GitHub
    (pasted Markdown can't break the page). Marker lines and metadata are unchanged.
  - The hook uses the session id Claude Code passes on stdin, so parallel sessions each
    update their own file. `--all` rebuilds every session log of this project from the start.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any


# ---------------------------------------------------------------------------
# Redaction. These logs are committed to a PUBLIC repository, so every prompt
# and response passes through redact() before it is written. Patterns cover the
# credentials this project can plausibly touch plus the common cloud formats.
# Keep in sync with scripts/check-secrets.sh and .gitleaks.toml.
# ---------------------------------------------------------------------------

_SECRET_CHARS = r'[A-Za-z0-9_\-]'

REDACTIONS: List[Tuple[re.Pattern, str]] = [
    # Supabase API keys (new format) and personal access tokens
    (re.compile(r'sb_(secret|publishable)_' + _SECRET_CHARS + r'{4,}'), r'sb_\1_[REDACTED]'),
    (re.compile(r'sbp_[A-Za-z0-9]{20,}'), 'sbp_[REDACTED]'),
    # JWTs (Supabase legacy anon/service_role keys, session tokens)
    (re.compile(r'eyJ' + _SECRET_CHARS + r'{10,}\.eyJ' + _SECRET_CHARS + r'{10,}\.' + _SECRET_CHARS + r'{10,}'),
     '[JWT REDACTED]'),
    # Anthropic, OpenAI, Stripe
    (re.compile(r'sk-ant-' + _SECRET_CHARS + r'{12,}'), 'sk-ant-[REDACTED]'),
    (re.compile(r'sk-(?:proj-|live_|test_)' + _SECRET_CHARS + r'{12,}'), 'sk-[REDACTED]'),
    # Resend (invitation email)
    (re.compile(r'\bre_[A-Za-z0-9_]{20,}'), 're_[REDACTED]'),
    # GitHub tokens
    (re.compile(r'\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}'), r'\1_[REDACTED]'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), 'github_pat_[REDACTED]'),
    # AWS, Google, Slack
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), 'AKIA[REDACTED]'),
    (re.compile(r'\bAIza[0-9A-Za-z_\-]{30,}'), 'AIza[REDACTED]'),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9\-]{10,}'), 'xox-[REDACTED]'),
    # Connection strings with embedded passwords
    (re.compile(r'((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[A-Za-z0-9._%\-]+:)[A-Za-z0-9._%+!$*#~\-]{4,}@'), r'\1[REDACTED]@'),
    # Authorization headers
    (re.compile(r'(?i)(bearer\s+)[A-Za-z0-9_\-.=]{16,}'), r'\1[REDACTED]'),
    # PEM private keys
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
     '[PRIVATE KEY REDACTED]'),
    # KEY=value / KEY: value lines whose name says secret and whose value looks real
    # (12+ token characters, not a placeholder like "..." or "<ref>" or "${VAR}")
    (re.compile(
        r'(?im)^(\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE_KEY'
        r'|ACCESS_KEY|CLIENT_SECRET|DATABASE_URL|SERVICE_ROLE)[A-Z0-9_]*\s*[=:]\s*["\']?)'
        r'(?!\[REDACTED\])([A-Za-z0-9_\-+/=.:@]{12,})(?<!\.\.\.)(["\']?\s*(?:#.*)?)$'),
     r'\1[REDACTED]\3'),
    # "password": "..." style literals in JSON/YAML/TS
    (re.compile(r'(?i)(["\']?(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret)["\']?\s*[:=]\s*["\'])([^"\']{8,})(["\'])'),
     r'\1[REDACTED]\3'),
    # Email addresses other than GitHub noreply (children's app: minimise personal data)
    (re.compile(r'[A-Za-z0-9._%+\-]+@(?!users\.noreply\.github\.com\b)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
     '[email redacted]'),
]


def redact(text: str) -> str:
    """Mask credential-shaped strings. Idempotent: redacted text redacts to itself."""
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def mask_email(email: str) -> str:
    """Keep GitHub noreply addresses (already public); mask the local part of anything else."""
    if email.endswith('@users.noreply.github.com') or '@' not in email:
        return email
    local, domain = email.split('@', 1)
    return f"{local[:1]}***@{domain}"


def get_git_author() -> str:
    """Get the author for attribution. Checks CLAUDE_AUTHOR env var first, then git config."""
    if author := os.environ.get('CLAUDE_AUTHOR'):
        return author
    try:
        result = subprocess.run(
            ['git', 'config', 'user.name'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 'unknown'


def get_github_user() -> str:
    """GitHub login for attribution.

    Order: GITHUB_USER env var, then the login embedded in a GitHub noreply commit email
    (the identity that actually authors the commits), then the active `gh` account as a last
    resort. The `gh` account is last because a developer may be signed in to several accounts,
    and these logs are public: attributing a session to whichever account happens to be active
    would publish an unrelated identity.
    """
    if login := os.environ.get('GITHUB_USER'):
        return login
    try:
        configured = subprocess.run(['git', 'config', '--get', 'github.user'],
                                    capture_output=True, text=True, timeout=5)
        if configured.returncode == 0 and configured.stdout.strip():
            return configured.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    noreply = re.match(r'^(?:\d+\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$', get_git_email())
    if noreply:
        return noreply.group(1)
    try:
        result = subprocess.run(
            ['gh', 'api', 'user', '--jq', '.login'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 'unknown'


def get_git_email() -> str:
    """Get the git config user.email for attribution."""
    try:
        result = subprocess.run(
            ['git', 'config', 'user.email'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 'unknown'


def normalize_cwd(raw: str) -> Path:
    """Turn a Git Bash path like /c/Users/x into C:\\Users\\x on Windows; leave others alone."""
    if os.name == 'nt':
        msys = re.match(r'^/([A-Za-z])(/.*)?$', raw)
        if msys:
            raw = f"{msys.group(1).upper()}:{(msys.group(2) or '/')}"
    return Path(raw)


def get_project_session_dir(cwd: Path) -> Path:
    """Get the session directory for a project.

    Claude Code names it after the working directory with every non-alphanumeric character
    replaced by '-': /Users/x/repo -> -Users-x-repo, C:\\Users\\x\\repo -> C--Users-x-repo.
    The drive letter's case can differ between the folder and the env var, so fall back to a
    case-insensitive match.
    """
    claude_dir = Path.home() / '.claude' / 'projects'
    project_hash = re.sub(r'[^A-Za-z0-9]', '-', str(cwd))
    exact = claude_dir / project_hash
    if exact.exists() or not claude_dir.is_dir():
        return exact
    for candidate in claude_dir.iterdir():
        if candidate.is_dir() and candidate.name.lower() == project_hash.lower():
            return candidate
    return exact


# Context the IDE and harness attach to a prompt; not typed by the user.
_INJECTED_BLOCKS = re.compile(
    r'<(ide_opened_file|ide_selection|system-reminder)>[\s\S]*?</\1>\s*'
)
# Harness events delivered as user turns (background-task and agent notifications).
_HARNESS_PREFIXES = ('<command-name>', '<local-command', 'Caveat:', '<task-notification>',
                     'Another Claude session sent a message')
# The editor wraps pasted text in this tag; the words inside are the person's exact prompt.
_PASTE_WRAPPER = re.compile(r'</?pasted_content(?:\s+id="[^"]*")?\s*>\n?')
INTERRUPTED = '[Request interrupted by user'


def attachment_note(entry: dict) -> str:
    """'1 image', '2 images, 1 document' for attachments sent with a prompt ('' if none)."""
    content = entry.get('message', {}).get('content', '')
    if not isinstance(content, list):
        return ''
    counts: Dict[str, int] = {}
    for block in content:
        kind = block.get('type')
        if kind in ('image', 'document'):
            counts[kind] = counts.get(kind, 0) + 1
    return ', '.join(f"{n} {kind}{'s' if n > 1 else ''}" for kind, n in counts.items())


def is_pasted(entry: dict) -> bool:
    content = entry.get('message', {}).get('content', '')
    if isinstance(content, list):
        content = ' '.join(b.get('text', '') for b in content if b.get('type') == 'text')
    return isinstance(content, str) and '<pasted_content' in content


def user_prompt_text(entry: dict) -> Optional[str]:
    """The text a person typed, or None for meta turns, tool results and harness events.

    The VS Code extension sends prompts as a list of text blocks (prompt plus IDE context),
    the CLI as a plain string; both are handled. Automatic context summaries written when a
    long conversation is compacted are not prompts.
    """
    if entry.get('type') != 'user':
        return None
    if entry.get('isMeta') or entry.get('isSidechain') or entry.get('isCompactSummary'):
        return None

    content = entry.get('message', {}).get('content', '')
    if isinstance(content, list):
        if any(block.get('type') == 'tool_result' for block in content):
            return None
        content = '\n\n'.join(
            block.get('text', '') for block in content if block.get('type') == 'text'
        )
    if not isinstance(content, str):
        return None

    text = _PASTE_WRAPPER.sub('', _INJECTED_BLOCKS.sub('', content)).strip()
    if not text or text.startswith(_HARNESS_PREFIXES):
        return None
    return text


def extract_assistant_text(entry: dict) -> Optional[str]:
    """Extract text content from assistant message."""
    if entry.get('type') != 'assistant':
        return None
    if entry.get('isSidechain'):
        return None

    content = entry.get('message', {}).get('content', [])

    if isinstance(content, str):
        return content if content.strip() else None

    if isinstance(content, list):
        texts = []
        for block in content:
            if block.get('type') == 'text':
                text = block.get('text', '').strip()
                if text:
                    texts.append(text)
        return '\n\n'.join(texts) if texts else None

    return None


def extract_clean_log(jsonl_path: Path) -> List[Tuple[str, str, str, Dict[str, Any]]]:
    """Extract conversation entries from a JSONL file.

    Each entry is (timestamp, role, text, info). role is 'user', 'assistant' or 'interrupt'.
    """
    entries = []

    for line in jsonl_path.read_text(encoding='utf-8', errors='replace').strip().split('\n'):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        timestamp = entry.get('timestamp', '')

        prompt = user_prompt_text(entry)
        if prompt and prompt.startswith(INTERRUPTED):
            entries.append((timestamp, 'interrupt', '', {}))
        elif prompt:
            info = {'attachments': attachment_note(entry), 'pasted': is_pasted(entry)}
            entries.append((timestamp, 'user', redact(prompt), info))

        elif entry.get('type') == 'assistant':
            text = extract_assistant_text(entry)
            if text:
                entries.append((timestamp, 'assistant', redact(text), {}))

    return entries


def format_timestamp(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return ''


def dedupe_entries(entries):
    """Keep only the final assistant response before each user prompt.

    An interruption marks the response it cut short (interrupted_by_user) instead of being
    logged as a prompt.
    """
    if not entries:
        return []

    result = []
    pending_assistant = None
    interrupted = False

    def flush():
        nonlocal pending_assistant, interrupted
        if pending_assistant:
            ts, role, content, info = pending_assistant
            result.append((ts, role, content, {**info, 'interrupted_by_user': True} if interrupted else info))
        elif interrupted and result and result[-1][1] == 'user':
            pass  # stopped before any reply text; nothing to attach the flag to
        pending_assistant, interrupted = None, False

    for entry in entries:
        timestamp, role, content, info = entry if len(entry) == 4 else (*entry, {})
        if role == 'user':
            flush()
            result.append((timestamp, role, content, info))
        elif role == 'assistant':
            pending_assistant = (timestamp, role, content, info)
        elif role == 'interrupt':
            interrupted = True

    flush()
    return result


def detect_paste_indicators(content: str) -> Dict[str, bool]:
    """Detect heuristic indicators that content was pasted."""
    indicators = {
        'has_code_block': '```' in content,
        'has_file_paths': bool(re.search(r'[\w\-/]+\.(ts|js|py|tsx|jsx|json|md|txt|yml|yaml):\d+', content)) or
                         bool(re.search(r'(?:^|[\s\(])/[\w\-/]+\.[\w]+', content, re.MULTILINE)),
        'has_urls': bool(re.search(r'https?://', content)),
        'is_long': len(content) > 500,
        'has_stack_trace': bool(re.search(r'at \w+.*:\d+:\d+', content)) or
                          bool(re.search(r'File ".*", line \d+', content)),
        'has_structured_data': bool(re.search(r'^[\s]*[{\[]', content, re.MULTILINE)) and
                              ('{' in content and '}' in content),
    }

    indicator_count = sum(indicators.values())
    indicators['likely_pasted'] = indicator_count >= 2 or indicators['is_long']

    return indicators


def fenced(text: str) -> str:
    """Text in a fence longer than any tilde run inside it, so it renders exactly as typed."""
    longest = max((len(run) for run in re.findall(r'~+', text)), default=0)
    fence = '~' * max(4, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def parse_iso_timestamp(timestamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def calculate_session_stats(entries: List[Tuple[str, str, str]]) -> Dict[str, Any]:
    """Calculate comprehensive session statistics."""
    if not entries:
        return {}

    prompts = [(e[0], e[2]) for e in entries if e[1] == 'user']
    responses = [(e[0], e[2]) for e in entries if e[1] == 'assistant']

    if not prompts:
        return {}

    stats = {}

    first_prompt_dt = parse_iso_timestamp(prompts[0][0])
    last_prompt_dt = parse_iso_timestamp(prompts[-1][0])

    stats['first_prompt_time'] = prompts[0][0]
    stats['last_prompt_time'] = prompts[-1][0]

    if first_prompt_dt and last_prompt_dt:
        duration = (last_prompt_dt - first_prompt_dt).total_seconds() / 60
        stats['session_duration_minutes'] = round(duration, 1)

        if len(prompts) > 1:
            avg_gap = duration / (len(prompts) - 1)
            stats['avg_time_between_prompts_minutes'] = round(avg_gap, 1)

    prompt_chars = [len(content) for _, content in prompts]
    prompt_words = [len(content.split()) for _, content in prompts]

    stats['total_prompt_chars'] = sum(prompt_chars)
    stats['total_prompt_words'] = sum(prompt_words)
    stats['avg_prompt_length_chars'] = round(sum(prompt_chars) / len(prompts), 1)
    stats['avg_prompt_length_words'] = round(sum(prompt_words) / len(prompts), 1)
    stats['longest_prompt_words'] = max(prompt_words)
    stats['shortest_prompt_words'] = min(prompt_words)

    if responses:
        response_chars = [len(content) for _, content in responses]
        stats['total_response_chars'] = sum(response_chars)
        stats['avg_response_length_chars'] = round(sum(response_chars) / len(responses), 1)

        if stats['total_prompt_chars'] > 0:
            stats['response_to_prompt_ratio'] = round(
                stats['total_response_chars'] / stats['total_prompt_chars'], 2
            )

    paste_data = [detect_paste_indicators(content) for _, content in prompts]
    stats['prompts_with_code_blocks'] = sum(1 for p in paste_data if p['has_code_block'])
    stats['prompts_with_file_paths'] = sum(1 for p in paste_data if p['has_file_paths'])
    stats['prompts_with_urls'] = sum(1 for p in paste_data if p['has_urls'])
    stats['prompts_with_long_content'] = sum(1 for p in paste_data if p['is_long'])
    stats['likely_pasted_count'] = sum(1 for p in paste_data if p['likely_pasted'])

    return stats


def extract_subagent_log(jsonl_path: Path) -> List[Tuple[str, str, str]]:
    """Prompts sent to a subagent and its replies.

    Prompts are the plain-text user turns (the dispatch, then any follow-up messages); harness
    reminders are skipped. Replies are the final reports a subagent hands back through the
    SubagentHandback tool, or plain assistant text for agents that answer directly.
    """
    entries = []
    for line in jsonl_path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = entry.get('timestamp', '')
        content = entry.get('message', {}).get('content')

        if entry.get('type') == 'user' and isinstance(content, str):
            text = content.strip()
            if text and not text.startswith('<system-reminder>'):
                entries.append((timestamp, 'user', redact(text), {}))
        elif entry.get('type') == 'assistant' and isinstance(content, list):
            for block in content:
                if block.get('type') == 'tool_use' and block.get('name') == 'SubagentHandback':
                    message = str(block.get('input', {}).get('message', '')).strip()
                    if message:
                        entries.append((timestamp, 'assistant', redact(message), {}))
                elif block.get('type') == 'text' and block.get('text', '').strip():
                    entries.append((timestamp, 'assistant', redact(block['text'].strip()), {}))
    return entries


def subagent_sections(session_dir: Path, session_id: str) -> List[str]:
    """Markdown sections, one per subagent of this session, oldest first."""
    subagent_dir = session_dir / session_id / 'subagents'
    if not subagent_dir.is_dir():
        return []

    agents = []
    for jsonl_path in subagent_dir.glob('agent-*.jsonl'):
        entries = dedupe_entries(extract_subagent_log(jsonl_path))
        if entries:
            agents.append((entries[0][0], jsonl_path, entries))
    agents.sort(key=lambda agent: agent[0])

    lines = []
    for _, jsonl_path, entries in agents:
        meta_path = jsonl_path.with_name(f"{jsonl_path.stem}.meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            meta = {}
        agent_id = jsonl_path.stem.removeprefix('agent-')
        description = redact(str(meta.get('description', ''))) or agent_id

        lines.append(f"\n## Subagent: {description}\n")
        lines.append(f"agent_id: {agent_id} | type: {meta.get('agentType', 'unknown')} | "
                     f"model: {meta.get('model', 'default')} | finished: {meta.get('finished', False)}")
        exchange_num = 0
        for timestamp, role, content, _info in entries:
            if role == 'user':
                exchange_num += 1
            kind = 'SUBAGENT_PROMPT' if role == 'user' else 'SUBAGENT_RESPONSE'
            lines.append(f"\n[CLAUDE_LOG_ENTRY type={kind} num={exchange_num} session={session_id} agent={agent_id}]")
            lines.append(f"timestamp: {timestamp}")
            lines.append(f"time: {format_timestamp(timestamp)}")
            lines.append(f"chars: {len(content)}")
            lines.append(f"\n{fenced(content) if role == 'user' else content}\n")
    return lines


def hook_session() -> Tuple[Optional[str], Optional[Path]]:
    """Session id and transcript path that Claude Code passes to hooks on stdin (if any)."""
    if sys.stdin is None or sys.stdin.isatty():
        return None, None
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except (json.JSONDecodeError, OSError, ValueError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    session = payload.get('session_id')
    transcript = payload.get('transcript_path')
    return (str(session) if session else None), (Path(transcript) if transcript else None)


def write_session_log(cwd: Path, session_dir: Path, transcript: Path) -> Optional[Path]:
    session_id = transcript.stem
    entries = dedupe_entries(extract_clean_log(transcript))
    if not any(e[1] == 'user' for e in entries):
        return None

    session_stats = calculate_session_stats(entries)

    output_dir = cwd / '.claude-logs'
    output_dir.mkdir(parents=True, exist_ok=True)

    existing_files = list(output_dir.glob(f"*_{session_id}.md"))
    date = datetime.now().strftime('%Y-%m-%d')
    if existing_files:
        output_path = existing_files[0]
    else:
        first = parse_iso_timestamp(entries[0][0])
        stamp = (first.astimezone() if first else datetime.now()).strftime('%Y-%m-%d_%H-%M-%S')
        output_path = output_dir / f"{stamp}_{session_id}.md"

    last_entry_type = entries[-1][1] if entries else 'unknown'
    session_status = 'complete' if last_entry_type == 'assistant' else 'awaiting_response'

    author = get_git_author()
    github_user = get_github_user()
    git_email = mask_email(get_git_email())
    lines = ["---"]
    lines.append(f"session_id: {session_id}")
    lines.append(f"date: {date}")
    lines.append(f"author: {author}")
    lines.append(f"github_user: {github_user}")
    lines.append(f"git_email: {git_email}")
    lines.append(f"project: {cwd.name}")
    lines.append(f"agent: claude-code")
    lines.append(f"session_status: {session_status}")
    lines.append(f"last_entry_type: {last_entry_type}")
    lines.append(f"total_exchanges: {len([e for e in entries if e[1] == 'user'])}")
    lines.append(f"generated_at: {datetime.now().isoformat()}")

    for key, value in session_stats.items():
        lines.append(f"{key}: {value}")

    lines.append("---\n")
    lines.append(f"# Claude Session Log - {date}\n")
    lines.append(f"Session: `{session_id}` | Project: `{cwd.name}` | Author: `{author}` | GitHub: `{github_user}`\n")
    lines.append("Each prompt appears exactly as it was typed or pasted, inside a text block. "
                 "Each response is the final answer the agent gave to that prompt. "
                 "Automatic context summaries, tool output and intermediate progress notes are not included.\n")
    lines.append("---\n")

    exchange_num = 0
    for timestamp, role, content, info in entries:
        time_str = format_timestamp(timestamp)

        if role == 'user':
            exchange_num += 1
            indicators = detect_paste_indicators(content)
            lines.append(f"\n### Prompt {exchange_num} · {author} · {time_str} UTC\n")
            lines.append(f"[CLAUDE_LOG_ENTRY type=PROMPT num={exchange_num} session={session_id}]")
            lines.append(f"timestamp: {timestamp}")
            lines.append(f"time: {time_str}")
            lines.append(f"chars: {len(content)}")
            lines.append(f"words: {len(content.split())}")
            lines.append(f"has_code_block: {indicators['has_code_block']}")
            lines.append(f"has_file_paths: {indicators['has_file_paths']}")
            lines.append(f"has_urls: {indicators['has_urls']}")
            lines.append(f"likely_pasted: {indicators['likely_pasted'] or info.get('pasted', False)}")
            if info.get('attachments'):
                lines.append(f"attachments: {info['attachments']}")
            lines.append("")
            if info.get('attachments'):
                lines.append(f"_Attached with this prompt: {info['attachments']} (not stored in the log)._\n")
            lines.append(f"{fenced(content)}\n")
        else:
            lines.append(f"\n### Response {exchange_num} · Claude · {time_str} UTC\n")
            lines.append(f"[CLAUDE_LOG_ENTRY type=RESPONSE num={exchange_num} session={session_id}]")
            lines.append(f"timestamp: {timestamp}")
            lines.append(f"time: {time_str}")
            lines.append(f"chars: {len(content)}")
            if info.get('interrupted_by_user'):
                lines.append("interrupted_by_user: True")
            lines.append(f"\n{content}\n")

    subagents = subagent_sections(session_dir, session_id)
    if subagents:
        lines.append("\n---\n")
        lines.append("# Subagents\n")
        lines.append("Dispatch prompts sent to each subagent and the reports it handed back, oldest first.")
        lines.extend(subagents)

    output_path.write_text(redact('\n'.join(lines)), encoding='utf-8')
    return output_path


def main():
    cwd = normalize_cwd(os.environ.get('CLAUDE_CWD') or os.getcwd())
    session_dir = get_project_session_dir(cwd)

    if not session_dir.exists():
        return

    session_files = [
        f for f in session_dir.glob('*.jsonl')
        if not f.name.startswith('agent-')
    ]

    if not session_files:
        return

    if '--all' in sys.argv[1:]:
        # Rebuild every session log of this project, oldest first.
        for transcript in sorted(session_files, key=lambda p: p.stat().st_mtime):
            written = write_session_log(cwd, session_dir, transcript)
            if written:
                print(f"wrote {written.relative_to(cwd)}")
        return

    session_id, transcript = hook_session()
    if transcript is None or not transcript.is_file():
        transcript = session_dir / f"{session_id}.jsonl" if session_id else None
    if transcript is None or not transcript.is_file():
        transcript = max(session_files, key=lambda p: p.stat().st_mtime)
    write_session_log(cwd, session_dir, transcript)


if __name__ == '__main__':
    main()
