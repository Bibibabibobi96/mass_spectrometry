"""Shared JSON Schema loading and deterministic validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from common.contracts.file_identity import file_sha256


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
sha256 = file_sha256


class ContractError(ValueError):
    """Raised when a machine contract fails structural or semantic validation."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def schema_registry() -> Registry:
    registry = Registry()
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def validate_schema(instance: Any, schema_name: str) -> None:
    schema = load_json(SCHEMA_DIR / schema_name)
    validator = Draft202012Validator(schema, registry=schema_registry())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    if not errors:
        return
    messages = []
    for error in errors:
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    raise ContractError("; ".join(messages))
