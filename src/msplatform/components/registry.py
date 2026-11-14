"""Explicit immutable provider descriptors for existing Assembly consumers."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from msplatform.contracts.machine_contracts import ContractError

Resolve = Callable[[Mapping[str, Any], str | None], tuple[Mapping[str, Any], Mapping[str, Any]]]
Validate = Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], None]
Members = Callable[[Mapping[str, Any], Mapping[str, Any]], Iterable[Mapping[str, Any]]]
Connections = Callable[[str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], None]


@dataclass(frozen=True)
class ProviderDescriptor:
    """Provider-owned resolution, validation and complete physical geometry."""
    provider_id: str
    project_id: str
    resolve: Resolve
    validate: Validate
    members: Members
    source_closure: tuple[str, ...]
    validate_connections: Connections | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() or value != value.strip()
               for value in (self.provider_id, self.project_id)):
            raise ContractError('provider and project identities must be nonempty')
        if not all(callable(value) for value in (self.resolve, self.validate, self.members)):
            raise ContractError('provider resolve, validation and physical member capabilities are required')
        if self.validate_connections is not None and not callable(self.validate_connections):
            raise ContractError('optional connection validator must be callable')
        if (not isinstance(self.source_closure, tuple) or not self.source_closure
                or any(not isinstance(value, str) or not value
                       or any(not part.isidentifier() for part in value.split('.')) for value in self.source_closure)
                or len(set(self.source_closure)) != len(self.source_closure)):
            raise ContractError('explicit distinct installed source closure required')


_by_provider: dict[str, ProviderDescriptor] = {}
_by_project: dict[str, ProviderDescriptor] = {}


def _rf() -> ProviderDescriptor:
    from msplatform.components.rf_multipole.registration import DESCRIPTOR
    return DESCRIPTOR


def _oa() -> ProviderDescriptor:
    from msplatform.components.orthogonal_accelerator.registration import DESCRIPTOR
    return DESCRIPTOR


def _tof() -> ProviderDescriptor:
    from msplatform.components.single_reflection_oa_tof.registration import DESCRIPTOR
    return DESCRIPTOR


def _ip() -> ProviderDescriptor:
    from msplatform.components.dual_pressure_rectilinear_ion_processor.registration import DESCRIPTOR
    return DESCRIPTOR


def _mr() -> ProviderDescriptor:
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.registration import DESCRIPTOR
    return DESCRIPTOR


def _cone() -> ProviderDescriptor:
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.registration import DESCRIPTOR
    return DESCRIPTOR


# Only the selected provider is imported. External registrations do not change this table.
_BUILTINS = MappingProxyType({
    'rf_multipole': ('rf_multipole_ion_optics', _rf),
    'orthogonal_accelerator': ('orthogonal_accelerator', _oa),
    'single_reflection_oa_tof': ('single_reflection_oa_tof_mass_analyzer', _tof),
    'dual_pressure_rectilinear_ion_processor': ('dual_pressure_rectilinear_ion_processor', _ip),
    'parallel_mirror_dual_stripe_mr_tof': ('parallel_mirror_dual_stripe_mr_tof', _mr),
    'dual_cone_tandem_quadrupole': ('dual_cone_tandem_quadrupole_ion_interface', _cone),
})
_BUILTIN_PROJECTS = MappingProxyType({project: provider for provider, (project, _) in _BUILTINS.items()})


def register_provider(descriptor: ProviderDescriptor) -> None:
    """Register one process-local immutable descriptor; duplicates are errors."""
    if not isinstance(descriptor, ProviderDescriptor):
        raise ContractError('registration requires an immutable ProviderDescriptor')
    if (descriptor.provider_id in _BUILTINS or descriptor.project_id in _BUILTIN_PROJECTS
            or descriptor.provider_id in _by_provider or descriptor.project_id in _by_project):
        raise ContractError('provider or project identity is already registered')
    _by_provider[descriptor.provider_id] = descriptor
    _by_project[descriptor.project_id] = descriptor


def _builtin(provider_id: str) -> ProviderDescriptor:
    selected = _by_provider.get(provider_id)
    if selected is not None:
        return selected
    project, loader = _BUILTINS[provider_id]
    descriptor = loader()
    if not isinstance(descriptor, ProviderDescriptor) or descriptor.provider_id != provider_id or descriptor.project_id != project:
        raise ContractError('builtin descriptor identity differs')
    _by_provider[provider_id] = descriptor
    _by_project[project] = descriptor
    return descriptor


def provider_descriptor(provider_id: str) -> ProviderDescriptor:
    """Return an explicitly registered descriptor, loading a selected builtin."""
    if not isinstance(provider_id, str):
        raise ContractError('provider identity must be a string')
    if provider_id in _BUILTINS:
        return _builtin(provider_id)
    try:
        return _by_provider[provider_id]
    except KeyError:
        raise ContractError(f'unsupported component provider: {provider_id}') from None


def project_descriptor(project_id: str) -> ProviderDescriptor:
    """Return the descriptor bound to one explicit Assembly project identity."""
    if not isinstance(project_id, str):
        raise ContractError('project identity must be a string')
    if project_id in _BUILTIN_PROJECTS:
        return _builtin(_BUILTIN_PROJECTS[project_id])
    try:
        return _by_project[project_id]
    except KeyError:
        raise ContractError(f'unsupported component project: {project_id}') from None


def registered_providers() -> Mapping[str, ProviderDescriptor]:
    """Return descriptors loaded in this process without loading other builtins."""
    return MappingProxyType(dict(_by_provider))
