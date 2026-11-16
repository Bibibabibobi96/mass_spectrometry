"""Continuous RF-to-IP consumer using the public SIMION stages."""
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.backends.simion import operations
from msplatform.backends.simion.tracking_execution import validate_birth_source
from msplatform.ion_release.authoring import ReleaseRealization


def _birth(particles: Any, hs1_request: Mapping[str, Any], propagation: Mapping[str, Any]) -> None:
    if (not isinstance(propagation, Mapping) or propagation.get('scope') != 'continuous_assembly'
            or 'stop' not in propagation or propagation['stop'] is not None):
        raise ValueError('continuous RF-IP requires continuous_assembly without an interface cut stop')
    packet = particles.to_dict() if isinstance(particles, ReleaseRealization) else particles
    if not isinstance(packet, Mapping) or packet.get('role') not in {
        'canonical_release_realization', 'canonical_recorded_birth_realization'
    } or packet.get('state_kind') != 'source_birth':
        raise ValueError('continuous RF-IP requires an original birth realization')
    clock = packet.get('clock')
    if not isinstance(clock, Mapping) or not clock.get('clock_epoch_id') or not clock.get('authority_sha256'):
        raise ValueError('continuous RF-IP requires the birth clock identity')
    validate_birth_source(packet)
    if not isinstance(hs1_request, Mapping) or set(hs1_request) != {'bath_domain', 'outer', 'vendor_record', 'numerics'}:
        raise ValueError('continuous RF-IP requires explicit HS1 inputs')


def track_existing_fields(*, fields: Any, particles: Any, propagation: Mapping[str, Any],
                          observations: Mapping[str, Any], tracking_numerics: Mapping[str, Any],
                          hs1_request: Mapping[str, Any], context: Any, birth_source_authority: Mapping[str, Any] | None = None,
                          unit_size: int | None = None, recovery_reference: Mapping[str, Any] | None = None,
                          dispatch_profiles: tuple[Mapping[str, Any], ...] = ()) -> Any:
    """Track original births in an explicitly selected complete joint field."""
    _birth(particles, hs1_request, propagation)
    return operations.track(fields, particles, propagation=propagation, observations=observations,
                            numerics=tracking_numerics, hs1_request=hs1_request, context=context,
                            birth_source_authority=birth_source_authority, unit_size=unit_size,
                            recovery_reference=recovery_reference, dispatch_profiles=dispatch_profiles)


def run_continuous(*, assembly: Assembly, geometry_numerics: Mapping[str, Any],
                   drive: Mapping[str, Any], physics: Mapping[str, Any], field_numerics: Mapping[str, Any],
                   particles: Any, propagation: Mapping[str, Any], observations: Mapping[str, Any],
                   tracking_numerics: Mapping[str, Any], hs1_request: Mapping[str, Any], context: Any, birth_source_authority: Mapping[str, Any] | None = None,
                          unit_size: int | None = None, recovery_reference: Mapping[str, Any] | None = None,
                          dispatch_profiles: tuple[Mapping[str, Any], ...] = (),
                   scalar_field_basis: Mapping[str, Any] | None = None,
                   reuse_collision_geometry: Any | None = None) -> Any:
    """Build and solve one complete RF-IP design, then track its original births."""
    _birth(particles, hs1_request, propagation)
    if not isinstance(assembly, Assembly):
        raise ValueError('continuous RF-IP requires a complete Assembly')
    if not isinstance(drive, Mapping) or not drive.get('clock') or not drive.get('clock_authority'):
        raise ValueError('continuous RF-IP requires explicit model clock authority')
    compiled = operations.compile_geometry(assembly, numerics=geometry_numerics)
    geometry = operations.build_geometry(compiled, context=context)
    model = operations.prepare_model(geometry, drive=drive, physics=physics, context=context)
    fields = operations.solve_fields(model, numerics=field_numerics, context=context,
        **({'scalar_field_basis': scalar_field_basis} if scalar_field_basis is not None else {}),
        **({'reuse_collision_geometry': reuse_collision_geometry} if reuse_collision_geometry is not None else {}))
    return track_existing_fields(fields=fields, particles=particles, propagation=propagation,
        observations=observations, tracking_numerics=tracking_numerics, hs1_request=hs1_request, context=context,
                            birth_source_authority=birth_source_authority, unit_size=unit_size,
                            recovery_reference=recovery_reference, dispatch_profiles=dispatch_profiles)
