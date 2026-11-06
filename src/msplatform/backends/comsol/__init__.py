"""COMSOL backend operations; compilation and publication start no native process."""
from typing import Any

__all__ = ["compile_request", "finalize", "prepare", "resolve_completed_provider"]


def __getattr__(name: str) -> Any:
    """Load operations on demand without pre-importing the ``-m`` target."""
    if name not in __all__:
        raise AttributeError(name)
    from . import corridor_field
    return getattr(corridor_field, name)
