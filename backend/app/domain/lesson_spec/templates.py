"""Finite, trusted V1 definition constraints, not an executable adapter registry."""

import ast
from dataclasses import dataclass

from .fields import MappingValue, ValidationCode


@dataclass(frozen=True)
class Template:
    initial: MappingValue
    correct: MappingValue
    outgoing_field: str
    required_path: str
    change_type: str
    fixture_id: str
    response_shape: str
    validation_codes: tuple[ValidationCode, ValidationCode]
    request_source: str
    receiver_source: str


NOTES = Template(
    "body",
    "content",
    "body",
    "/content",
    "rename_payload_field",
    "empty-notes-v1",
    "saved_note",
    ("missing:content", "extra_forbidden:body"),
    'payload = {\n    "title": note.title,\n    "body": note.content,\n}\n'
    'response = client.post("/notes", json=payload)',
    "from pydantic import BaseModel, ConfigDict, Field\n\nclass NoteCreate(BaseModel):\n"
    '    model_config = ConfigDict(extra="forbid")\n'
    "    title: str = Field(min_length=1, max_length=200)\n"
    "    content: str = Field(min_length=1, max_length=2000)",
)
TASKS = Template(
    "flat",
    "nested",
    "priority",
    "/metadata/priority",
    "nest_payload_field",
    "empty-tasks-v1",
    "saved_task",
    ("missing:metadata", "extra_forbidden:priority"),
    'payload = {\n    "title": task.title,\n    "priority": task.priority,\n}\n'
    'response = client.post("/tasks", json=payload)',
    "from typing import Literal\nfrom pydantic import BaseModel, ConfigDict, Field\n\n"
    "class TaskMetadata(BaseModel):\n"
    '    model_config = ConfigDict(extra="forbid")\n'
    '    priority: Literal["low", "normal", "high"]\n\n'
    "class TaskCreate(BaseModel):\n"
    '    model_config = ConfigDict(extra="forbid")\n'
    "    title: str = Field(min_length=1, max_length=200)\n"
    "    metadata: TaskMetadata",
)


def validate_display_schema(source: str) -> None:
    """Accept declarative receiving-model examples, never executable submissions.

    The AST is inspected only. No import, expression, default, method, decorator or
    call is evaluated. Trusted runtime artifacts are instead matched byte-for-byte
    against the constants above. This display grammar is not an exercise executor.
    """
    try:
        module = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError("Retrieval schema must contain model declarations") from exc
    if not 1 <= len(module.body) <= 8:
        raise ValueError("Retrieval schema requires one to eight model declarations")
    known = {"str", "int", "float", "bool", "list", "dict"}

    def annotation(node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in known
        if isinstance(node, ast.Constant):
            return node.value is None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return annotation(node.left) and annotation(node.right)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if node.value.id == "Literal":
                return 1 <= len(arguments) <= 8 and all(
                    isinstance(item, ast.Constant) and type(item.value) in {str, int, bool}
                    for item in arguments
                )
            arity = {"list": 1, "dict": 2}.get(node.value.id)
            return len(arguments) == arity and all(annotation(item) for item in arguments)
        return False

    for node in module.body:
        if (
            not isinstance(node, ast.ClassDef)
            or not node.name.isascii()
            or not node.name.isidentifier()
            or node.name.startswith("_")
            or node.name in known | {"BaseModel", "Literal"}
            or node.decorator_list
            or node.keywords
            or node.type_params
            or len(node.bases) != 1
            or not isinstance(node.bases[0], ast.Name)
            or node.bases[0].id != "BaseModel"
            or not 1 <= len(node.body) <= 32
        ):
            raise ValueError("Only plain BaseModel declarations are supported in retrieval schemas")
        fields: set[str] = set()
        for member in node.body:
            if (
                not isinstance(member, ast.AnnAssign)
                or member.value is not None
                or not isinstance(member.target, ast.Name)
                or not member.target.id.isascii()
                or member.target.id.startswith("_")
                or member.target.id in fields
                or not annotation(member.annotation)
            ):
                raise ValueError("Retrieval schemas accept typed fields without executable content")
            fields.add(member.target.id)
        known.add(node.name)
