"""Admit explicit IP–MR scalar samples; no field, flight or qualification is created."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.backends.comsol.ip_mr_scalar_basis import project_ip_mr_scalar_basis
from .scalar_sample_binding import _read, _small_product, verify_scalar_sample, attach_refinement_windows
from msplatform.io.manifest_records import record_path, validate_file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact


def resolve_ip_mr_scalar_basis(*, model: Any, assembly: Assembly,
                               geometry_artifact: Mapping[str, Any] | OpenedArtifact,
                               operator: Mapping[str, Any],
                               samples: Mapping[str, Mapping[str, Any] | OpenedArtifact],
                               refinement_windows: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Bind all actual carrier/unit/RF products to one complete source-derived model.

    The admission does not assert interpolation coverage or scientific qualification.
    Every basis, including zero-coefficient bases, remains required at runtime.
    """
    producer, product, manifest_path = _small_product(geometry_artifact, 'geometry_artifact', ('projection',))
    meta = product['metadata']
    if meta.get('backend') != 'comsol' or meta.get('scope') != 'geometry_only' or meta.get('native_reopen_verified') is not True:
        raise ValueError('successful reopened public geometry required')
    record = validate_file_record(producer['inputs']['execution_request'], 'geometry execution request')
    path = record_path(record, base_dir=manifest_path.parent)
    verify_record('geometry execution request', record, base_dir=manifest_path.parent)
    frozen = _read(path)
    if frozen.get('role') != 'run_artifact_workflow_request' or frozen['payload'].get('action') != 'build_comsol_geometry':
        raise ValueError('geometry producer action differs')
    projection = _read(record_path(product['data']['projection'], base_dir=manifest_path.parent))
    payload = frozen['payload']
    snapshot = dict(composition_plan=assembly.composition_plan, components_resolved=assembly.components_resolved,
                    components_source=assembly.components_source)
    if payload['assembly'] != snapshot or payload['projection'] != projection:
        raise ValueError('geometry producer Assembly or projection differs')
    plan = project_ip_mr_scalar_basis(model, assembly=assembly, projection=projection, operator=operator)
    expected = {'carrier': plan['carrier']}
    expected.update({'ip_'+str(row['schedule_index']): row['request'] for row in plan['ip_unit_volt']})
    if plan['rf_reference'] is not None:
        expected['rf_reference'] = plan['rf_reference']['request']
    if not isinstance(samples, Mapping) or set(samples) != set(expected):
        raise ValueError('complete explicit scalar basis products required')
    bindings = {}; common_grid = None
    for name, request in expected.items():
        def check_workpoint(actual):
            if actual != request: raise ValueError('scalar workpoint request differs')
        binding = verify_scalar_sample(samples[name], projection, check_workpoint=check_workpoint, resolve_reference=True)
        if common_grid is not None and binding['grid'] != common_grid:
            raise ValueError('scalar basis grids differ')
        common_grid = binding['grid']; bindings[name] = binding
    attach_refinement_windows(bindings, refinement_windows, admit_level=lambda level: resolve_ip_mr_scalar_basis(
        model=model, assembly=assembly, geometry_artifact=geometry_artifact, operator=operator, samples=level))
    reference = ({'manifest': dict(geometry_artifact.reference['manifest'], path=str(manifest_path)),
                  'product_id': geometry_artifact.product_id} if isinstance(geometry_artifact, OpenedArtifact)
                 else copy.deepcopy(dict(geometry_artifact)))
    return dict(schema_version=1, role='ip_mr_scalar_basis_binding', model_identity_sha256=plan['model_identity_sha256'],
        clock=copy.deepcopy(plan['clock']), projection_sha256=plan['projection_sha256'],
        ip_groups=[{key: row[key] for key in ('instance_id', 'electrode_group_id', 'schedule_index', 'coefficient')}
                   for row in plan['ip_unit_volt']],
        rf=({key: value for key, value in plan['rf_reference'].items() if key != 'request'}
            if plan['rf_reference'] is not None else None),
        geometry_reference=reference, geometry_execution_request=dict(record, path=str(path)),
        grid=common_grid, bases=bindings, scope='identity_admission_only_not_coverage_or_qualification')
