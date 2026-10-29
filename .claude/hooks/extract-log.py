#!/usr/bin/env python3
"""Extract clean conversation logs from Claude Code sessions.

Based on the company "Agent Session Logs" guide. Local changes (so it runs the same on
Windows, macOS and Linux for every teammate):
  - get_project_session_dir() uses Claude Code's real folder naming (every non-alphanumeric
    character becomes '-') and matches case-insensitively, so `C:\\Users\\x\\repo` finds
    `c--Users-x-repo`. Git Bash style paths (`/c/Users/...`) are converted first.
  - Transcripts are read and logs written as UTF-8 (Windows defaults to cp1252).
"""

import json
import os
import re
import subprocess
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


def user_prompt_text(entry: dict) -> Optional[str]:
    """The text a person typed, or None for meta turns, tool results and harness events.

    The VS Code extension sends prompts as a list of text blocks (prompt plus IDE context),
    the CLI as a plain string; both are handled.
    """
    if entry.get('type') != 'user':
        return None
    if entry.get('isMeta') or entry.get('isSidechain'):
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

    text = _INJECTED_BLOCKS.sub('', content).strip()
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


def extract_clean_log(jsonl_path: Path) -> List[Tuple[str, str, str]]:
    """Extract conversation entries from a JSONL file."""
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
        if prompt:
            entries.append((timestamp, 'user', redact(prompt)))

        elif entry.get('type') == 'assistant':
            text = extract_assistant_text(entry)
            if text:
                entries.append((timestamp, 'assistant', redact(text)))

    return entries


def format_timestamp(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return ''


def dedupe_entries(entries: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    """Keep only the final assistant response before each user prompt."""
    if not entries:
        return []

    result = []
    pending_assistant = None

    for timestamp, role, content in entries:
        if role == 'user':
            if pending_assistant:
                result.append(pending_assistant)
                pending_assistant = None
            result.append((timestamp, role, content))
        elif role == 'assistant':
            pending_assistant = (timestamp, role, content)

    if pending_assistant:
        result.append(pending_assistant)

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


def parse_iso_timestamp(timestamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def calculate_session_stats(entries: List[Tuple[str, str, str]]) -> Dict[str, Any]:
    """Calculate comprehensive session statistics."""
    if not entries:
        return {}

    prompts = [(ts, content) for ts, role, content in entries if role == 'user']
    responses = [(ts, content) for ts, role, content in entries if role == 'assistant']

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
                entries.append((timestamp, 'user', redact(text)))
        elif entry.get('type') == 'assistant' and isinstance(content, list):
            for block in content:
                if block.get('type') == 'tool_use' and block.get('name') == 'SubagentHandback':
                    message = str(block.get('input', {}).get('message', '')).strip()
                    if message:
                        entries.append((timestamp, 'assistant', redact(message)))
                elif block.get('type') == 'text' and block.get('text', '').strip():
                    entries.append((timestamp, 'assistant', redact(block['text'].strip())))
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
        for timestamp, role, content in entries:
            if role == 'user':
                exchange_num += 1
            kind = 'SUBAGENT_PROMPT' if role == 'user' else 'SUBAGENT_RESPONSE'
            lines.append(f"\n[CLAUDE_LOG_ENTRY type={kind} num={exchange_num} session={session_id} agent={agent_id}]")
            lines.append(f"timestamp: {timestamp}")
            lines.append(f"time: {format_timestamp(timestamp)}")
            lines.append(f"chars: {len(content)}")
            lines.append(f"\n{content}\n")
    return lines


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

    latest = max(session_files, key=lambda p: p.stat().st_mtime)
    session_id = latest.stem

    entries = extract_clean_log(latest)
    entries = dedupe_entries(entries)

    if not entries:
        return

    session_stats = calculate_session_stats(entries)

    output_dir = cwd / '.claude-logs'
    output_dir.mkdir(parents=True, exist_ok=True)

    existing_files = list(output_dir.glob(f"*_{session_id}.md"))
    date = datetime.now().strftime('%Y-%m-%d')
    if existing_files:
        output_path = existing_files[0]
    else:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"{timestamp}_{session_id}.md"
        output_path = output_dir / filename

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
    lines.append(f"session_status: {session_status}")
    lines.append(f"last_entry_type: {last_entry_type}")
    lines.append(f"total_exchanges: {len([e for e in entries if e[1] == 'user'])}")
    lines.append(f"generated_at: {datetime.now().isoformat()}")

    for key, value in session_stats.items():
        lines.append(f"{key}: {value}")

    lines.append("---\n")
    lines.append(f"# Claude Session Log - {date}\n")
    lines.append(f"Session: `{session_id}` | Project: `{cwd.name}` | Author: `{author}` | GitHub: `{github_user}`\n")
    lines.append("---\n")

    prompts_data = []
    for timestamp, role, content in entries:
        if role == 'user':
            paste_indicators = detect_paste_indicators(content)
            prompts_data.append({
                'timestamp': timestamp,
                'content': content,
                'chars': len(content),
                'words': len(content.split()),
                'paste_indicators': paste_indicators,
            })

    exchange_num = 0
    prompt_index = 0

    for i, (timestamp, role, content) in enumerate(entries):
        time_str = format_timestamp(timestamp)

        if role == 'user':
            exchange_num += 1
            prompt_data = prompts_data[prompt_index]
            indicators = prompt_data['paste_indicators']

            lines.append(f"\n[CLAUDE_LOG_ENTRY type=PROMPT num={exchange_num} session={session_id}]")
            lines.append(f"timestamp: {timestamp}")
            lines.append(f"time: {time_str}")
            lines.append(f"chars: {prompt_data['chars']}")
            lines.append(f"words: {prompt_data['words']}")
            lines.append(f"has_code_block: {indicators['has_code_block']}")
            lines.append(f"has_file_paths: {indicators['has_file_paths']}")
            lines.append(f"has_urls: {indicators['has_urls']}")
            lines.append(f"likely_pasted: {indicators['likely_pasted']}")
            lines.append(f"\n{content}\n")

            prompt_index += 1
        else:
            lines.append(f"\n[CLAUDE_LOG_ENTRY type=RESPONSE num={exchange_num} session={session_id}]")
            lines.append(f"timestamp: {timestamp}")
            lines.append(f"time: {time_str}")
            lines.append(f"chars: {len(content)}")
            lines.append(f"\n{content}\n")

    subagents = subagent_sections(session_dir, session_id)
    if subagents:
        lines.append("\n---\n")
        lines.append("# Subagents\n")
        lines.append("Dispatch prompts sent to each subagent and the reports it handed back, oldest first.")
        lines.extend(subagents)

    output_path.write_text(redact('\n'.join(lines)), encoding='utf-8')


if __name__ == '__main__':
    main()
