"""Serialize frozen scientific values into data-only Lua companions."""
from typing import Any
import json


def lua_literal(value: Any) -> str:
    """Serialize frozen JSON values into a data-only Lua companion."""
    if isinstance(value, dict):
        return "{" + ",".join("[" + json.dumps(k) + "]=" + lua_literal(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "{" + ",".join(map(lua_literal, value)) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    return json.dumps(value, allow_nan=False)
