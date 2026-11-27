"""Continuous RF-to-IP consumer using the public SIMION stages."""
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.backends.simion import operations
from msplatform.backends.simion.tracking_execution import validate_birth_source
from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
from msplatform.contracts.machine_contracts import validate_schema
from msplatform.ion_release.authoring import ReleaseRealization

HS1_SCHEMA = Path(__file__).with_name("continuous_hs1.schema.json")
COMPONENT_SCOPES = {
    "rf_ip": {"rf_multipole_ion_optics", "ion_processor"},
    "rf_ip_mr": {"rf_multipole_ion_optics", "ion_processor",
                 "multi_reflection_tof"},
}


def _admit_component_scope(fields: Any, expected_scope: str) -> Any:
    from msplatform.backends.simion.artifacts import CompiledPreparedModel
    from msplatform.backends.simion.model import require_prepared_model
    from msplatform.results import artifacts as artifact_reader
    from msplatform.results.artifacts import OpenedArtifact

    source = fields if isinstance(fields, OpenedArtifact) else artifact_reader.open_artifact(
        fields, expected_kind="field_bundle")
    model = CompiledPreparedModel(source.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    document = require_prepared_model(model)
    plan = document["geometry"]["frontend_geometry"]["composition_plan"]
    selected = plan["scope"]["instance_ids"]
    projects = {plan["components"][instance]["project_id"] for instance in selected}
    if set(selected) != set(document["components_resolved"]) or projects != COMPONENT_SCOPES[expected_scope]:
        raise ValueError(f"continuous tracking requires the exact {expected_scope} component scope")
    return source


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
                          dispatch_profiles: tuple[Mapping[str, Any], ...] = (),
                          expected_component_scope: str | None = None) -> Any:
    """Track original births in an explicitly selected complete joint field."""
    _birth(particles, hs1_request, propagation)
    if expected_component_scope is not None:
        fields = _admit_component_scope(fields, expected_component_scope)
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


def load_hs1_request(path: Path) -> dict[str, Any]:
    """Load explicit bath, outer gas and original vendor inputs for continuous RF-IP."""
    import json
    from msplatform.io.manifest_records import file_record, verify_record

    path = path.resolve()
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_schema(document, HS1_SCHEMA)

    def box(value: Mapping[str, Any]) -> BoxDomain:
        return BoxDomain(tuple(value["minimum_mm"]), tuple(value["maximum_mm"]),
                         tuple(value["lower_closed"]), tuple(value["upper_closed"]))

    outer = document["outer"]
    source = outer["source"]
    state = outer["uniform_state"]
    vendor = Path(document["vendor_path"])
    if not vendor.is_absolute():
        vendor = path.parent / vendor
    vendor_record = file_record(vendor.resolve())
    verify_record("continuous RF-IP vendor", vendor_record)
    return dict(
        bath_domain=box(document["bath_domain"]),
        outer=GasFieldSpec(
            field_id=outer["field_id"], frame_id=outer["frame_id"], representation="uniform",
            composition_id=outer["composition_id"],
            composition=tuple(GasSpecies(item["species_id"], item["mass_amu"], item["mole_fraction"])
                              for item in outer["species"]),
            domain=box(outer["domain"]),
            source=GasSource(source["kind"], source["source_id"], tuple(source["assumptions"]),
                             source.get("reference")),
            uniform_state=GasState(state["status"], state["pressure_pa"], state["temperature_k"],
                                   tuple(state["bulk_velocity_m_s"]))),
        vendor_record=vendor_record,
        numerics=dict(document["numerics"]))


def main() -> None:
    """Track original births through an explicitly selected complete RF-IP field."""
    import argparse
    import json
    from msplatform.execution import load_environment
    from msplatform.ion_release import sample_release

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-request", type=Path, required=True)
    parser.add_argument("--fields-reference", type=Path, required=True)
    parser.add_argument("--propagation", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--numerics", type=Path, required=True)
    parser.add_argument("--hs1-request", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--recovery-reference", type=Path)
    parser.add_argument("--dispatch-profiles", type=Path)
    parser.add_argument("--unit-size", type=int)
    parser.add_argument("--expected-component-scope", choices=tuple(COMPONENT_SCOPES), default="rf_ip")
    args = parser.parse_args()

    def document(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    result = track_existing_fields(
        fields=document(args.fields_reference), particles=sample_release(document(args.release_request)),
        propagation=document(args.propagation), observations=document(args.observations),
        tracking_numerics=document(args.numerics), hs1_request=load_hs1_request(args.hs1_request),
        context=load_environment(args.environment, workspace=args.workspace, profile=args.profile),
        recovery_reference=document(args.recovery_reference) if args.recovery_reference else None,
        dispatch_profiles=document(args.dispatch_profiles) if args.dispatch_profiles else (),
        unit_size=args.unit_size, expected_component_scope=args.expected_component_scope)
    print("OWNER_RETURNED=" + json.dumps(result.reference, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
