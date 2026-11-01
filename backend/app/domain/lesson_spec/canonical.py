"""Pure canonical JSON and content digests for complete validated V1 definitions.

Digest formula: lowercase SHA-256 hex of the canonical UTF-8 serialization of
every definition field except the root ``content_sha256`` field. Canonical JSON
uses sorted object keys, compact separators, ensure_ascii=False and allow_nan=False.
Arrays retain their order, and authored text is neither stripped nor normalized.

These operations do not register, persist, execute, publish or approve a lesson.
Finalization requires a complete definition with a format-valid placeholder or
stale digest; that supplied digest is overwritten, never treated as evidence.
"""

import hashlib
import hmac
import json
from types import MappingProxyType

from .definition import MAX_DEFINITION_BYTES, MAX_JSON_DEPTH, LessonSpecV1, validate_lesson_spec
from .fields import Value

type JSONValue = str | int | bool | None | list[JSONValue] | dict[str, JSONValue]


def _json_value(value: object, depth: int = 0) -> JSONValue:
    """Thaw only permitted values, before any serializer could coerce them."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError("Definition exceeds the JSON nesting limit")
    if value is None:
        return None
    if type(value) is int:
        return value
    if type(value) is bool:
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Definition must contain valid UTF-8 text") from exc
        return value
    if isinstance(value, Value):
        fields = type(value).model_fields
        if set(value.__dict__) - fields.keys():
            raise ValueError("Definition contains undeclared model fields")
        return {name: _json_value(getattr(value, name), depth + 1) for name in fields}
    if isinstance(value, (dict, MappingProxyType)):
        result: dict[str, JSONValue] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("JSON property names must be strings")
            result[key] = _json_value(child, depth + 1)
        return result
    if isinstance(value, (tuple, list)):
        return [_json_value(child, depth + 1) for child in value]
    raise ValueError("Definition contains an unsupported JSON value")


def _fresh_definition(value: object) -> LessonSpecV1:
    # Revalidating an existing model instance directly can reuse the instance.
    # Convert its fields to an ordinary permitted JSON tree for fresh validation.
    try:
        incoming = _json_value(value) if isinstance(value, LessonSpecV1) else value
        return validate_lesson_spec(incoming)
    except (TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Definition cannot be validated for canonical serialization") from exc


def _payload(definition: LessonSpecV1) -> dict[str, JSONValue]:
    if not isinstance(definition, LessonSpecV1):
        raise ValueError("Canonical serialization requires a LessonSpecV1 definition")
    checked = _fresh_definition(definition)
    value = _json_value(checked)
    if not isinstance(value, dict):
        raise ValueError("Definition must serialize to a JSON object")
    return value


def _encode(payload: dict[str, JSONValue]) -> bytes:
    try:
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Definition cannot be serialized as canonical UTF-8 JSON") from exc
    if len(raw) > MAX_DEFINITION_BYTES:
        raise ValueError("Definition exceeds 65536 UTF-8 bytes")
    return raw


def canonical_bytes(definition: LessonSpecV1, *, include_digest: bool = True) -> bytes:
    """Return canonical complete bytes; exclude only the root digest when requested.

    The complete definition must fit 64 KiB even when digest input is requested.
    This is serialization, not a public learner projection.
    """
    if type(include_digest) is not bool:
        raise ValueError("include_digest must be a boolean")
    payload = _payload(definition)
    complete = _encode(payload)
    if include_digest:
        return complete
    del payload["content_sha256"]
    return _encode(payload)


def calculate_digest(definition: LessonSpecV1) -> str:
    """Hash every public and private field except the root digest itself."""
    return hashlib.sha256(canonical_bytes(definition, include_digest=False)).hexdigest()


def verify_digest(definition: LessonSpecV1) -> bool:
    """Compare the supplied digest with a fresh calculation after strict validation."""
    expected = calculate_digest(definition)
    return hmac.compare_digest(definition.content_sha256, expected)


def finalize_definition(value: object) -> LessonSpecV1:
    """Overwrite a complete definition's supplied digest, revalidate and verify it."""
    definition = _fresh_definition(value)
    payload = _payload(definition)
    payload["content_sha256"] = calculate_digest(definition)
    finalized = validate_lesson_spec(payload)
    if not verify_digest(finalized):
        raise ValueError("Finalized definition failed digest verification")
    return finalized
