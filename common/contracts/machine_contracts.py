"""Shared JSON Schema loading and deterministic validation helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

if __package__:
    from .file_identity import file_sha256
else:
    from file_identity import file_sha256


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
sha256 = file_sha256


class ContractError(ValueError):
    """Raised when a machine contract fails structural or semantic validation."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=1)
def schema_registry() -> Registry:
    """Build the immutable repository schema registry once per Python process."""
    registry = Registry()
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def _schema_path(schema_name: str | Path) -> Path:
    """Resolve a shared schema name or an explicitly owned schema file."""

    path = Path(schema_name)
    return path if path.is_absolute() else SCHEMA_DIR / path


@lru_cache(maxsize=None)
def _schema_validator(schema_path: str) -> Draft202012Validator:
    path = Path(schema_path)
    schema = load_json(path)
    Draft202012Validator.check_schema(schema)
    registry = schema_registry()
    if path.parent != SCHEMA_DIR:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(schema, registry=registry)


def validate_schema(instance: Any, schema_name: str | Path) -> None:
    """Validate against a shared schema name or an explicitly owned schema path."""

    validator = _schema_validator(str(_schema_path(schema_name).resolve()))
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    if not errors:
        return
    messages = []
    for error in errors:
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    raise ContractError("; ".join(messages))
