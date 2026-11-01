"""Strict bounded conversational JSON parsing; generation keeps its own admission gates."""

import json


def strict_json_object(text: str, *, max_bytes: int = 16384) -> dict[str, object]:
    def reject_constant(value: str) -> object:
        raise ValueError("Invalid conversational output")

    def pairs(entries: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in entries:
            if key in result:
                raise ValueError("Invalid conversational output")
            result[key] = value
        return result

    def check(value: object, depth: int = 0) -> None:
        if depth > 16:
            raise ValueError("Invalid conversational output")
        if isinstance(value, dict):
            for key, item in value.items():
                str(key).encode("utf-8")
                check(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                check(item, depth + 1)
        elif isinstance(value, str):
            value.encode("utf-8")
        elif value is not None and type(value) not in {bool, int}:
            raise ValueError("Invalid conversational output")

    try:
        if len(text.encode("utf-8")) > max_bytes:
            raise ValueError("Invalid conversational output")
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
        check(value)
        if not isinstance(value, dict):
            raise ValueError("Invalid conversational output")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Invalid conversational output") from None
