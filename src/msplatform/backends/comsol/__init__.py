"""COMSOL backend operations; compilation and publication start no native process."""
from typing import Any

__all__ = ["solve_axisymmetric_gas_flow", "build_ei_model", "build_wehnelt_model", "compile_request", "finalize", "prepare", "resolve_completed_provider"]


def __getattr__(name: str) -> Any:
    """Load operations on demand without pre-importing the ``-m`` target."""
    if name not in __all__:
        raise AttributeError(name)
    if name == "solve_axisymmetric_gas_flow":
        from .gas_flow import solve_axisymmetric_gas_flow
        return solve_axisymmetric_gas_flow
    if name == "build_ei_model":
        from .ei_model import build_ei_model
        return build_ei_model
    if name == "build_wehnelt_model":
        from .wehnelt_model import build_wehnelt_model
        return build_wehnelt_model
    from . import corridor_field
    return getattr(corridor_field, name)
