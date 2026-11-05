"""Remove known editor envelopes, retaining the user's request verbatim."""

import re


def clean_prompt(text: str) -> str:
    if text.startswith("# Context from my IDE setup:") and "\n## My request:\n" in text:
        text = text.split("\n## My request:\n", 1)[1].strip()
    return re.sub(
        r"<(ide_opened_file|ide_selection|system-reminder|environment_context)>[\s\S]*?</\1>\s*",
        "",
        text,
    )
