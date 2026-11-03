"""Reject obvious credentials and direct email identifiers before public AI requests."""

import re

_SENSITIVE = re.compile(
    r"-----BEGIN .*PRIVATE KEY|\b(?:AIza[\w-]{20,}|sk-[\w-]{20,}|"
    r"gh[pousr]_[\w]{20,}|github_pat_[\w]{20,}|sb_secret_[\w-]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}\b)|"
    r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}|"
    r"\b(?:[a-z][a-z0-9_]*_)?(?:password|api[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|secret(?:[_ -]?key)?|service[_ -]?role(?:[_ -]?key)?|"
    r"aws[_ -]?(?:secret[_ -]?access[_ -]?key|session[_ -]?token)|github[_ -]?token)"
    r"[\"']?\s*[:=]\s*[\"']?\S{6,}|"
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    re.I,
)


def public_ai_question(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Questions must use valid UTF-8") from None
    if _SENSITIVE.search(value):
        raise ValueError("Remove credentials and personal email addresses from the question")
    return value
