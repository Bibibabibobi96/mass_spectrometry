"""Compatibility imports for the unique installed Lua boundary validator."""
from msplatform.backends.simion.tracking_program import (
    BoundaryContractError as BoundaryContractError,
    _FORBIDDEN_LUA_PATTERNS as _FORBIDDEN_LUA_PATTERNS,
    validate_pure_lua_component_source as validate_pure_lua_component_source,
)
