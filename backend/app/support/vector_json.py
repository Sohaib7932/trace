"""Bounded numerical cache JSON, separate from the integer-only conversational parser."""

import json
import math


def strict_vector_json(raw: str, *, max_bytes: int) -> dict[str, object]:
    def reject_constant(value: str) -> object:
        raise ValueError("Invalid vector cache JSON")

    def pairs(entries: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in entries:
            if key in result:
                raise ValueError("Invalid vector cache JSON")
            result[key] = value
        return result

    def check(value: object, depth: int = 0) -> None:
        if depth > 16:
            raise ValueError("Invalid vector cache JSON")
        if isinstance(value, dict):
            for key, item in value.items():
                str(key).encode("utf-8")
                check(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                check(item, depth + 1)
        elif isinstance(value, str):
            value.encode("utf-8")
        elif type(value) is float:
            if not math.isfinite(value):
                raise ValueError("Invalid vector cache JSON")
        elif value is not None and type(value) not in {int, bool}:
            raise ValueError("Invalid vector cache JSON")

    try:
        if len(raw.encode("utf-8")) > max_bytes:
            raise ValueError("Invalid vector cache JSON")
        parsed = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
        check(parsed)
        if not isinstance(parsed, dict):
            raise ValueError("Invalid vector cache JSON")
        return parsed
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Invalid vector cache JSON") from None
