"""Read-only admission of one explicitly selected native SIMION FieldBundle."""
from __future__ import annotations

import json
import copy
from collections.abc import Mapping
from typing import Any

from msplatform.backends.simion.artifacts import CompiledPreparedModel
from msplatform.backends.simion.field_bank import field_bank
from msplatform.backends.simion.field_closure import data_record, require_downstream_reuse
from msplatform.backends.simion.field_identity import working_point_member_id
from msplatform.backends.simion.model import compile_prepared_model, model_geometry, require_prepared_model
from msplatform.backends.simion.model_execution import _clock_reference
from msplatform.backends.simion.native_plans import plan_solve_fields
from msplatform.io.file_identity import canonical_json_sha256
from msplatform.results.artifacts import OpenedArtifact, open_artifact
from msplatform import assembly, components


def _json(value: Any) -> Any:
    """Compare exactly the persisted, finite JSON meaning including numeric keys."""
    return json.loads(json.dumps(value, allow_nan=False, sort_keys=True))


def admit_simion_field_reference(study: Mapping[str, Any], *, reference: Mapping[str, Any],
                                 clock_authority: Mapping[str, Any], expected_model: CompiledPreparedModel,
                                 field_numerics: Mapping[str, Any], artifact: OpenedArtifact | None = None) -> OpenedArtifact:
    """Verify frozen field identity and science, without writing or solving.

    The caller owns the native-source guard for the whole consumption lifetime.
    Explicitly missing, incomplete or mismatched assets fail; no recomputation is
    attempted. The originating implementation remains provenance of this field.
    """
    ref = reference
    if artifact is not None:
        if not isinstance(artifact, OpenedArtifact):
            raise ValueError('supplied field source must be an opened artifact')
        selected = artifact.reference
        if (selected['product_id'] != ref['product_id'] or any(
                str(selected['manifest'][key]).upper() != str(ref['manifest'][key]).upper() for key in ('bytes','sha256'))):
            raise ValueError('guarded field artifact differs from the frozen reference')
    selected = open_artifact(artifact if artifact is not None else ref, expected_kind='field_bundle')
    meta = selected.metadata
    if (meta.get('backend') != 'simion' or meta.get('field_status') != 'available'
            or meta.get('source_status') != 'not_requested'
            or meta.get('field_representation') not in (None, 'native_domain_composition')):
        raise ValueError('field reference must be a complete source-independent SIMION native field')
    providers = {name: components.resolve_component(request) for name, request in study['component_requests'].items()}
    instrument = assembly.assemble(study['recipe'], providers)
    from msplatform.backends import simion
    compiled = simion.compile_geometry(instrument, numerics=study['numerics']['geometry'])
    drive = copy.deepcopy(study['drive'])
    drive.pop('clock_authority')
    drive['clock'].update(clock_epoch_id=clock_authority['clock_epoch_id'], authority_sha256=clock_authority['authority']['sha256'])
    requested = compile_prepared_model(compiled, instrument.components_resolved, drive=drive, physics=study['physics'])
    expected = require_prepared_model(expected_model)
    if _json(expected) != _json(require_prepared_model(requested)):
        raise ValueError('expected model differs from the frozen recipe assembly, drive, geometry or physics')
    if expected['geometry']['frontend_geometry'].get('role') != 'simion_split_oa_tof_geometry':
        raise ValueError('explicit native field reference requires the supported split geometry')
    actual = CompiledPreparedModel(selected.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    document = require_prepared_model(actual)
    if (_json(document) != _json(expected) or meta.get('model_identity_sha256') != expected['model_identity_sha256']
            or meta.get('clock') != expected['drive']['clock']):
        raise ValueError('field model, physical inputs, drive or clock differs from the requested model')
    if not isinstance(field_numerics, Mapping) or _json(field_numerics) != _json(study['numerics']['fields']):
        raise ValueError('field numerics argument differs from the frozen study')
    read = lambda name: json.loads(selected.data_path(name).read_text(encoding='utf-8-sig'))
    if _json(read('field_numerics')) != _json(field_numerics):
        raise ValueError('field numerics differ from the requested study')
    numerical = dict(field_numerics)
    convergence = numerical.pop('downstream_convergence_v', None)
    expected_design = plan_solve_fields(expected_model, numerics=numerical)['field_design']
    design = read('field_design')
    if _json(design) != _json(expected_design):
        raise ValueError('field working-point design differs from the requested model and numerics')
    domains = [row['domain_id'] for row in expected_design['domains']]
    if _json(read('field_bank')) != _json(field_bank(expected_design, domains)):
        raise ValueError('field bank differs from the complete expected working-point design')
    bindings = meta.get('frontend_members')
    members = {working_point_member_id(point) for point in expected_design['working_points']}
    if (not isinstance(bindings, Mapping) or set(bindings) != set(domains)
            or any(not isinstance(rows, Mapping) or set(rows) != members for rows in bindings.values())):
        raise ValueError('field bundle lacks expected domain working-point members')
    consumed = set()
    for domain, rows in bindings.items():
        for member, row in rows.items():
            if not isinstance(row, Mapping) or not isinstance(row.get('data_key'), str):
                raise ValueError('field member binding is incomplete')
            key = row['data_key']
            if key in consumed:
                raise ValueError('field members cannot reuse one payload identity')
            consumed.add(key)
            data_record(selected, key)
            stem = 'frontend' if domain == 'parent' else 'frontend_entrance_refinement'
            if selected.data_path(key).name != stem + '.' + member + '.pa':
                raise ValueError('field member filename differs from the native bank contract')
    identity = meta.get('downstream_identity')
    if not isinstance(identity, dict) or not isinstance(identity.get('identity_sha256'), str):
        raise ValueError('field bundle lacks the downstream spatial identity')
    unhashed = {key: value for key, value in identity.items() if key != 'identity_sha256'}
    if identity['identity_sha256'] != canonical_json_sha256(unhashed) or identity.get('convergence_v') != convergence:
        raise ValueError('downstream identity or convergence differs from the study')
    specs = {row['role']: row for row in model_geometry(expected_model).downstream_specs}
    expected_physical = {role: dict(template_variables=spec['template_variables'],
        grid={key: spec['native_instance'][key] for key in ('nx','ny','nz')}) for role, spec in specs.items()}
    if _json(identity.get('physical_inputs')) != _json(expected_physical):
        raise ValueError('downstream geometry or numerical grid differs from the model')
    require_downstream_reuse(selected, identity)
    for key in ('downstream_audit','workbench','zero_particle_format_control','clock_authority','instrument_epoch'):
        selected.data_path(key)
    workbench = selected.data_path('workbench')
    if selected.data_path('zero_particle_format_control').resolve() != workbench.with_suffix('.fly2').resolve():
        raise ValueError('field workbench zero-particle control differs')
    clocks = dict(contract=data_record(selected,'clock_authority'), authority=data_record(selected,'instrument_epoch'),
                  data_root=str(selected.data_path('clock_authority').parent))
    _clock_reference(expected, clocks)
    return selected
