"""Scientific providers and their explicit, acyclic component dependencies."""
from collections.abc import Mapping, Sequence
from types import MappingProxyType


PROVIDER_DEPENDENCIES = MappingProxyType({
    "rf_multipole": (),
    "orthogonal_accelerator": (),
    "apertured_tube_electron_impact_ion_source": (),
    "transverse_helical_filament_wehnelt_electron_gun": (),
    "dual_cone_tandem_quadrupole_ion_interface": ("rf_multipole",),
    # OA owns the acceleration model; RF's existing grounded-shield validator
    # supplies the same physical zero-potential constraint, not another RF body.
    "single_reflection_oa_tof": ("orthogonal_accelerator", "rf_multipole"),
})


def validate_provider_dependencies(dependencies: Mapping[str, Sequence[str]]) -> None:
    """Reject unresolved provider references and cycles before resolving a design."""
    active, visited = set(), set()

    def visit(provider: str) -> None:
        if provider not in dependencies:
            raise ValueError(f"undeclared component dependency: {provider}")
        if provider in active:
            raise ValueError(f"component dependency cycle at {provider}")
        if provider in visited:
            return
        active.add(provider)
        children = dependencies[provider]
        if isinstance(children, str) or len(set(children)) != len(children):
            raise ValueError(f"invalid component dependencies: {provider}")
        for child in children:
            visit(child)
        active.remove(provider)
        visited.add(provider)

    for provider in dependencies:
        visit(provider)


validate_provider_dependencies(PROVIDER_DEPENDENCIES)

from .model import ResolvedComponent as ResolvedComponent
from .catalog import resolve_component as resolve_component
