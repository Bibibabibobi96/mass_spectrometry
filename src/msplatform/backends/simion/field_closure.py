"""Published model/field data bindings and spatial reuse applicability, no execution."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from msplatform.results.artifacts import OpenedArtifact, open_artifact
from msplatform.io.file_identity import canonical_json_sha256
from .artifacts import CompiledPreparedModel
from .model import model_geometry, require_prepared_model
from .model_execution import _clock_reference


@dataclass(frozen=True)
class FieldModelSource:
    """One verified published unsolved model and its explicit immutable inputs."""
    artifact: OpenedArtifact
    model: CompiledPreparedModel
    native_assets: dict
    clock_authority_reference: dict


def data_record(artifact: OpenedArtifact, key: str) -> dict:
    """Project an already verified product location without hashing large bytes again."""
    record = artifact.data_records[key]
    return dict(record, path=str(artifact.data_locations[key]))


def load_field_model(reference: Mapping | OpenedArtifact, *, field_representation: str | None = None) -> FieldModelSource:
    """Require an actual PreparedModel, original clock pair and full raw/surface closure."""
    source = reference if isinstance(reference, OpenedArtifact) else open_artifact(reference, expected_kind='prepared_model')
    if source.kind != 'prepared_model':
        raise ValueError('field solve requires an actual prepared_model artifact')
    metadata = source.metadata
    if (metadata.get('backend') != 'simion' or metadata.get('drive_configured') is not True
            or metadata.get('geometry_materialized') is not True or metadata.get('field_status') != 'not_solved'
            or metadata.get('source_status') != 'not_requested'):
        raise ValueError('field solve requires the published unsolved, source-independent SIMION model')
    document = json.loads(source.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    model = CompiledPreparedModel(json.dumps(document, allow_nan=False))
    document = require_prepared_model(model)
    role = document['geometry']['frontend_geometry'].get('role')
    if role == 'simion_oa_mr_complete_geometry':
        raise ValueError('OA–MR field solve is not supported')
    sampled = field_representation == 'assembly_sampled_basis_with_collision_geometry'
    if field_representation is not None and not sampled:
        raise ValueError('unsupported explicit field representation')
    if sampled and role != 'simion_ip_mr_complete_geometry':
        raise ValueError('sampled assembly field representation requires complete IP–MR geometry')
    if role == 'simion_ip_mr_complete_geometry' and not sampled:
        raise ValueError('IP–MR field solve requires an implemented common-field binding')
    clock = dict(contract=data_record(source, 'clock_authority'), authority=data_record(source, 'instrument_epoch'))
    clock['data_root'] = str(Path(clock['contract']['path']).parent)
    _clock_reference(document, clock)
    geometry = model_geometry(model).frontend_geometry
    independent_component = geometry.get('role') in {'simion_independent_rf_geometry', 'simion_independent_oa_geometry', 'simion_rf_ip_geometry', 'simion_neutral_world_collision_geometry', 'simion_neutral_multi_domain_collision_geometry'} or sampled
    expected = (set(geometry['domain_order']) if geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry' else {'world'} if geometry.get('role') == 'simion_neutral_world_collision_geometry' else set(geometry['numerical_domains']) if independent_component else
                {'flight_tube', 'reflectron', 'detector', *geometry['numerical_domains']})
    bindings = metadata.get('native_assets')
    if not isinstance(bindings, Mapping) or set(bindings) != expected:
        raise ValueError('prepared model native domains differ from its actual geometry')
    assets, consumed = {}, set()
    for domain, keys in bindings.items():
        fields = ({'raw_geometry', 'fractional_surface', 'surface_witnesses'} if independent_component else
                  {'raw_geometry', 'fractional_surface'} if domain in {'flight_tube', 'detector'} else {'raw_geometry'})
        if (sampled or geometry.get('role') in {'simion_neutral_world_collision_geometry','simion_neutral_multi_domain_collision_geometry'}) and 'surface_state' in keys:
            fields = (fields | {'surface_state'}) if 'fractional_surface' in keys else ((fields - {'fractional_surface'}) | {'surface_state'})
        if set(keys) != fields or any(key in consumed for key in keys.values()):
            raise ValueError('prepared model native closure is incomplete or ambiguous')
        consumed.update(keys.values())
        assets[domain] = dict(raw_record=data_record(source, keys['raw_geometry']),
            surface_records=[data_record(source, keys['fractional_surface'])] if 'fractional_surface' in keys else [])
        if independent_component:
            assets[domain]['witness_record'] = data_record(source, keys['surface_witnesses'])
        if 'surface_state' in keys:
            assets[domain]['state_record'] = data_record(source, keys['surface_state'])
    return FieldModelSource(source, model, assets, clock)


def downstream_identity(model: CompiledPreparedModel, *, raw_assets: Mapping, convergence_v: Mapping,
                        tool_identity: Mapping, builder_identities: Mapping) -> dict:
    """Bind only actual spatial inputs; exclude source, RF phase/frequency and clock."""
    geometry = model_geometry(model, downstream_drive=True)
    roles = {'flight_tube', 'reflectron', 'detector'}
    if set(raw_assets) != roles or set(convergence_v) != roles:
        raise ValueError('downstream spatial identity requires all three physical roles')
    specs = {row['role']: row for row in geometry.downstream_specs}
    records = lambda rows: [dict(bytes=row['bytes'], sha256=str(row['sha256']).upper()) for row in rows]
    result = dict(schema_version=1, role='simion_downstream_spatial_identity',
        raw_geometry={role:records([raw_assets[role]['raw_record'], *raw_assets[role]['surface_records']]) for role in sorted(roles)},
        physical_inputs={role:dict(template_variables=specs[role]['template_variables'],
            grid={key:specs[role]['native_instance'][key] for key in ('nx','ny','nz')}) for role in sorted(roles)},
        convergence_v=dict(convergence_v), tool_identity=dict(tool_identity), builder_identities=dict(builder_identities))
    # Hash the persisted JSON meaning, never Python int-key ordering.
    result = json.loads(json.dumps(result, allow_nan=False))
    return dict(result, identity_sha256=canonical_json_sha256(result))


def require_downstream_reuse(reference: Mapping, expected_identity: Mapping) -> tuple[OpenedArtifact, dict]:
    """Read only a complete published field bundle with an exact spatial operator."""
    source = reference if isinstance(reference, OpenedArtifact) else open_artifact(reference, expected_kind='field_bundle')
    if source.kind != 'field_bundle':
        raise ValueError('downstream reuse requires an actual field_bundle artifact')
    metadata = source.metadata
    if (metadata.get('backend') != 'simion' or metadata.get('field_status') != 'available'
            or metadata.get('downstream_identity') != expected_identity):
        raise ValueError('published downstream fields differ from the actual model spatial operator')
    bindings = metadata.get('native_assets')
    if not isinstance(bindings, Mapping) or set(bindings) != {'flight_tube','reflectron','detector'}:
        raise ValueError('published downstream fields lack exactly three native asset roles')
    assets = {}
    for role, keys in bindings.items():
        if set(keys) != {'carrier','family'} or not isinstance(keys['family'], list):
            raise ValueError('published downstream asset binding differs')
        carrier = data_record(source, keys['carrier'])
        family = [data_record(source, key) for key in keys['family']]
        if role == 'reflectron':
            if family or not carrier['path'].lower().endswith('.pa'):
                raise ValueError('reflectron reuse requires only a detached operating PA')
        elif metadata.get('ground_representation') == 'analytic_zero_on_native_geometry':
            if (metadata.get('ground_boundary_condition') != 'ground_dirichlet_zero_outer_homogeneous_neumann'
                    or metadata.get('ground_refine_calls') != 0 or metadata.get('ground_fly_calls') != 0
                    or not isinstance(metadata.get('ground_source_reference'), Mapping)
                    or len(family) != 1 or not carrier['path'].lower().endswith('.pa')
                    or Path(family[0]['path']) != Path(carrier['path']).with_suffix('.pa-surf')):
                raise ValueError('analytic ground requires its detached carrier and same-stem surface')
        else:
            if (len(family) != 4 or len({row['path'] for row in family}) != 4
                    or carrier not in family or any(Path(row['path']).parent != Path(carrier['path']).parent for row in family)
                    or {Path(row['path']).suffix.lower() for row in family} != {'.pa#','.pa0','.pa1','.pa-surf'}):
                raise ValueError('grounded downstream native family is incomplete or ambiguous')
        assets[role] = dict(carrier_record=carrier, family_records=family)
    return source, assets


def load_reflectron_response_records(reference: Mapping | OpenedArtifact, *,
                                     expected_model_identity_sha256: str,
                                     expected_downstream_identity: Mapping,
                                     expected_grid: Mapping,
                                     expected_symmetry: str) -> list[dict]:
    """Return the verified ordered reflectron response records for compensation.

    Response IDs are the native electrode numbers and their order is contiguous
    from one. Every selected file is revalidated before its record is returned.
    Older bundles without this basis remain usable for detached-carrier tracking,
    but are rejected here rather than treated as an incomplete fitting basis.
    """
    source = reference if isinstance(reference, OpenedArtifact) else open_artifact(reference, expected_kind='field_bundle')
    if source.kind != 'field_bundle':
        raise ValueError('reflectron responses require an actual field_bundle artifact')
    metadata = source.metadata
    basis = metadata.get('reflectron_response_basis')
    fields = {'schema_version','model_identity_sha256','downstream_identity','grid','symmetry','responses'}
    if not isinstance(basis, Mapping) or set(basis) != fields or type(basis['schema_version']) is not int or basis['schema_version'] != 1:
        raise ValueError('published reflectron response basis is missing or has an unknown schema')
    if (not isinstance(expected_model_identity_sha256, str)
            or basis['model_identity_sha256'] != expected_model_identity_sha256
            or metadata.get('model_identity_sha256') != expected_model_identity_sha256):
        raise ValueError('reflectron response basis belongs to a different model')
    if (basis['downstream_identity'] != expected_downstream_identity
            or metadata.get('downstream_identity') != expected_downstream_identity):
        raise ValueError('reflectron response basis belongs to a different downstream spatial operator')
    if basis['grid'] != expected_grid or basis['symmetry'] != expected_symmetry:
        raise ValueError('reflectron response basis grid or symmetry differs')
    responses = basis['responses']
    if not isinstance(responses, list) or not responses:
        raise ValueError('reflectron response basis must contain ordered responses')
    records, keys, paths = [], set(), set()
    for expected_id, response in enumerate(responses, 1):
        if (not isinstance(response, Mapping) or set(response) != {'response_id','data_key'}
                or type(response['response_id']) is not int or response['response_id'] != expected_id
                or not isinstance(response['data_key'], str) or not response['data_key']):
            raise ValueError('reflectron response IDs, order or data bindings differ')
        key = response['data_key']
        if key in keys:
            raise ValueError('reflectron response data keys are duplicated')
        keys.add(key)
        path = source.data_path(key)
        if path.suffix.lower() != '.pa'+str(expected_id) or path in paths:
            raise ValueError('reflectron response filename or location is duplicated or inconsistent')
        paths.add(path)
        records.append(dict(data_record(source, key), response_id=expected_id))
    return records
