"""Bound new COMSOL execution to the frozen selected Assembly provenance."""
from __future__ import annotations

import json
from collections.abc import Mapping

from msplatform.assembly.model import Assembly
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.io.manifest_records import record_path, require_completed_terminal_publication, verify_record
from msplatform.results.artifacts import OpenedArtifact


_RETIRED_PROJECT = 'single_reflection_oa_tof_mass_analyzer'


def require_supported_plan(plan: Mapping) -> None:
    """Reject the retired composite by declared project identity only."""
    if not isinstance(plan, Mapping) or not isinstance(plan.get('components'), Mapping) or not plan['components']:
        raise ValueError('COMSOL native execution requires complete Assembly component provenance')
    for component in plan['components'].values():
        if not isinstance(component, Mapping) or not isinstance(component.get('project_id'), str) or not component['project_id']:
            raise ValueError('COMSOL native execution requires explicit component project identities')
        if component['project_id'] == _RETIRED_PROJECT:
            raise ValueError('retired composite project cannot start new COMSOL native execution')


def require_supported_assembly(assembly: Assembly) -> None:
    if not isinstance(assembly, Assembly):
        raise ValueError('COMSOL native execution requires a complete Assembly')
    require_supported_plan(assembly.composition_plan)


def _linked_product(record: dict, product_id: str, kind: str) -> tuple[dict, dict]:
    verify_record('upstream native manifest', record)
    path = record_path(record)
    require_completed_terminal_publication(path)
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    product = manifest.get('products', {}).get(product_id)
    if (manifest.get('status') != 'success' or not isinstance(product, dict) or product.get('kind') != kind
            or product.get('status') != 'complete' or not isinstance(product.get('data'), dict)
            or product.get('metadata', {}).get('backend') != 'comsol'):
        raise ValueError('native upstream product provenance differs')
    return manifest, product['data']


def _bound_link(manifest: dict, data: dict, name: str) -> dict:
    record = data.get(name)
    if not isinstance(record, dict) or record not in [*manifest.get('inputs', {}).values(), *manifest.get('outputs', [])]:
        raise ValueError('native upstream link is not manifest bound: ' + name)
    return record


def require_supported_artifact(artifact: OpenedArtifact) -> None:
    """Trace a native source to its manifest-bound geometry Assembly and verify projection.

    Read only small provenance records: never rehash a large MPH merely to
    classify the project. The existing owner protects the native payload.
    """
    original_projection = json.loads(artifact.data_path('projection').read_text(encoding='utf-8-sig'))
    if artifact.kind == 'field_solution':
        record = artifact.data_records.get('prepared_manifest')
        if not isinstance(record, dict):
            raise ValueError('field solution lacks prepared-model provenance')
        manifest, data = _linked_product(record, 'model', 'prepared_model')
        record = _bound_link(manifest, data, 'geometry_manifest')
        manifest, data = _linked_product(record, 'geometry', 'geometry_artifact')
    elif artifact.kind == 'prepared_model':
        record = artifact.data_records.get('geometry_manifest')
        if not isinstance(record, dict):
            raise ValueError('prepared model lacks geometry provenance')
        manifest, data = _linked_product(record, 'geometry', 'geometry_artifact')
    elif artifact.kind == 'geometry_artifact':
        manifest = json.loads(artifact.manifest_location.read_text(encoding='utf-8-sig'))
        data = artifact.data_records
    else:
        raise ValueError('COMSOL geometry provenance is required')
    config = manifest.get('run_config')
    if not isinstance(config, dict):
        raise ValueError('geometry producer lacks manifest-bound run configuration')
    verify_record('geometry run configuration', config)
    params = json.loads(record_path(config).read_text(encoding='utf-8-sig')).get('parameters')
    if not isinstance(params, dict) or params.get('action') != 'build_comsol_geometry':
        raise ValueError('geometry provenance lacks original native Assembly action')
    snapshot = params.get('assembly')
    if not isinstance(snapshot, Mapping):
        raise ValueError('geometry provenance lacks frozen Assembly')
    require_supported_plan(snapshot.get('composition_plan'))
    projection_record = _bound_link(manifest, data, 'projection')
    verify_record('geometry projection', projection_record)
    projection = json.loads(record_path(projection_record).read_text(encoding='utf-8-sig'))
    if (original_projection != projection or params.get('projection') != projection
            or project_assembly_geometry(snapshot, outer_box_mm=projection['outer_box_mm']) != projection):
        raise ValueError('geometry provenance and published projection differ')
