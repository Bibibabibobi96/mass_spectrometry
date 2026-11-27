"""Public author snapshot and validated scientific recipe, independent of solver."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping


def assembly_name(component_ids: list[str]) -> str:
    """Generate the v1 name of a single ordered sequence, including repeats."""
    if not isinstance(component_ids, list) or not component_ids:
        raise ValueError("a nonempty component sequence is required")
    if any(not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", item) for item in component_ids):
        raise ValueError("component_id must be a lowercase ASCII identifier")
    return "__".join(component_ids)


@dataclass(frozen=True, init=False)
class SimulationRecipe:
    """Validated resolved recipe and optional immutable author byte snapshot.

    ``load_recipe`` supplies source_bytes from its single external read. Source
    bytes are provenance, separate from the resolved scientific identity.
    """
    _document: dict
    source_bytes: bytes | None

    def __init__(self, resolved: Mapping[str, Any], *, source_bytes: bytes | None = None):
        object.__setattr__(self, "_document", validate_recipe(resolved))
        object.__setattr__(self, "source_bytes", source_bytes)

    def to_dict(self) -> dict:
        return copy.deepcopy(self._document)


def validate_recipe(resolved: Mapping[str, Any]) -> dict:
    """Validate using the declared current schema; never infer a backend."""
    if not isinstance(resolved, Mapping):
        raise ValueError("resolved recipe must be a mapping")
    schema = resolved.get("schema_version")
    if type(schema) is not int:
        raise ValueError("recipe schema_version must be an integer")
    if schema == 2:
        from .native import validate_native
        return validate_native(resolved)
    if schema == 3:
        from .reference import validate_reference
        return validate_reference(resolved)
    raise ValueError("unsupported current recipe schema_version")


def load_recipe(path: str | Path) -> SimulationRecipe:
    """Read an author once; parsing, archive and provenance share these bytes."""
    source = Path(path).read_bytes()
    raw = tomllib.loads(source.decode("utf-8"), parse_float=Decimal)
    schema = raw.get("schema_version")
    if type(schema) is not int:
        raise ValueError("recipe schema_version must be an integer")
    if schema == 2:
        from .native import resolve_native
        document = resolve_native(raw, Path(path))
    elif schema == 3:
        from .reference import resolve_reference
        document = resolve_reference(raw)
    else:
        raise ValueError("unsupported current recipe schema_version")
    return SimulationRecipe(document, source_bytes=source)


__all__ = ["SimulationRecipe", "assembly_name", "load_recipe", "validate_recipe"]
