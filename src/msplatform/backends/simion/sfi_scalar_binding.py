"""Admit explicit public scalar workpoints for an existing SFI model.

Admission establishes source identities and geometry/drive agreement. It does
not establish interpolation coverage, coupling, convergence or flight validity.
"""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from msplatform.backends.simion.collision_overlay import COLLISION_NOTREFINABLE_FLAG, collision_pa_header
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.comsol.assembly_field_export import _check_report
from msplatform.backends.comsol.assembly_field_solution import validate_solution_readback
from msplatform.backends.comsol.assembly_geometry import _world_bounds, project_assembly_geometry
from msplatform.components.shape_query import shape_relation
from msplatform.backends.simion.frontend import native_frontend_instances
from msplatform.backends.simion.tracking_program import _bound_tracking_model, validate_native_flight
from msplatform.io.manifest_records import record_path, require_completed_terminal_publication, validate_file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact

_NAMES = ('carrier', 'rf_reference', 'pulse_delta')


def _ideal_sheet_projection(projection: Mapping[str, Any], grid: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project canonical world-XY sheets to exact grid-node runs; never snap a plane."""
    origin, pitch, dims = grid['origin_mm'], grid['pitch_mm'], grid['dimensions']
    rows = []
    for member in projection['members']:
        if member['representation_role'] != 'ideal_surface':
            continue
        lo, hi = _world_bounds(member)
        if any(hi[a] < origin[a] or lo[a] > origin[a] + (dims[a]-1)*pitch[a] for a in range(3)):
            continue
        shape, pose = member['shape'], member['transform']
        if shape['kind'] not in ('box', 'annulus'):
            raise ValueError('unsupported intersecting ideal sheet')
        rotation = pose['rotation']
        axes = ([a for a, size in enumerate(shape['size_mm']) if size == 0]
                if shape['kind'] == 'box' else [2])
        if (len(axes) != 1 or abs(rotation[2][axes[0]]) != 1
                or (shape['kind'] == 'annulus' and (shape['z_min_mm'] != shape['z_max_mm']
                                                     or shape['inner_radius_mm'] != 0))):
            raise ValueError('unsupported intersecting ideal sheet orientation or shape')
        normal_axis = axes[0]
        q = (lo[2]-origin[2])/pitch[2]
        k = round(q)
        if lo[2] != hi[2] or not 0 <= k < dims[2] or origin[2]+k*pitch[2] != lo[2]:
            raise ValueError('intersecting ideal sheet is not aligned with scalar grid')
        # Quotient rounding can place a node exactly on an edge just outside
        # ceil/floor bounds. Include its neighbours and let shape_relation
        # decide from the actual reconstructed world-node coordinates.
        imin = max(0, math.ceil((lo[0]-origin[0])/pitch[0])-1)
        imax = min(dims[0]-1, math.floor((hi[0]-origin[0])/pitch[0])+1)
        jmin = max(0, math.ceil((lo[1]-origin[1])/pitch[1])-1)
        jmax = min(dims[1]-1, math.floor((hi[1]-origin[1])/pitch[1])+1)
        translation = pose['translation_mm']
        for j in range(jmin, jmax+1):
            start = end = None
            for i in range(imin, imax+1):
                world = [origin[0]+i*pitch[0], origin[1]+j*pitch[1], lo[2]]
                delta = [world[a]-translation[a] for a in range(3)]
                local = [sum(rotation[a][b]*delta[a] for a in range(3)) for b in range(3)]
                # The verified world plane is the image of this exact local plane.
                local[normal_axis] = shape['center_mm'][normal_axis] if shape['kind'] == 'box' else shape['z_min_mm']
                if shape_relation(shape, local) == 'boundary':
                    if start is None: start = i
                    if end is not None and i != end+1: raise ValueError('ideal sheet row is not contiguous')
                    end = i
            if start is not None:
                rows.append(dict(instance_id=member['instance_id'], electrode_group_id=member['electrode_group_id'],
                                 member_id=member['member_id'], i_min=start, i_max=end,
                                 j_min=j, j_max=j, k=k))
    return rows


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    return value


def _small_product(reference: Mapping[str, Any] | OpenedArtifact, kind: str, names: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Verify only consumed metadata records; native MPH is not read or claimed."""
    if isinstance(reference, OpenedArtifact):
        manifest = dict(reference.reference['manifest'], path=str(reference.manifest_location))
        product_id = reference.product_id
    else:
        if not isinstance(reference, Mapping) or set(reference) != {'manifest', 'product_id'}:
            raise ValueError('explicit published product reference required')
        manifest = validate_file_record(reference['manifest'], 'producer manifest')
        product_id = reference['product_id']
    manifest = validate_file_record(manifest, 'producer manifest')
    if not Path(manifest['path']).is_absolute(): raise ValueError('absolute manifest required')
    path = record_path(manifest)
    verify_record('producer manifest', manifest)
    require_completed_terminal_publication(path)
    owner = _read(path)
    product = owner['products'][product_id]
    if (type(owner.get('schema_version')) is not int or owner['schema_version'] not in (1, 2)
            or owner.get('role') != 'simulation_run_manifest' or owner.get('status') != 'success'
            or owner.get('lifecycle_state') == 'provisional' or type(product.get('schema_version')) is not int
            or product['schema_version'] != 1 or product.get('kind') != kind or product.get('status') != 'complete'
            or not isinstance(product.get('metadata'), dict) or not isinstance(product.get('data'), dict) or not product['data']):
        raise ValueError('successful complete published product required')
    bound = [*owner['inputs'].values(), *owner['outputs']]
    for name in names:
        record = validate_file_record(product['data'][name], name)
        if record not in bound: raise ValueError('product record not bound by producer: ' + name)
        verify_record(name, record, base_dir=path.parent)
    return owner, product, path

def _group_vectors(drive: Mapping[str, Any]) -> tuple[dict[str, dict[tuple[str, str], float]], dict[str, Any]]:
    vectors = {name: {} for name in _NAMES}
    signatures = set()
    for instance, groups in drive['groups'].items():
        for group, item in groups.items():
            kind = item['kind']
            if kind == 'static': values = (item['voltage_v'], 0., 0.)
            elif kind == 'pulse': values = (item['off_voltage_v'], 0., item['on_voltage_v'] - item['off_voltage_v'])
            elif kind == 'rf':
                signatures.add(tuple(item[k] for k in ('frequency_hz', 'phase_rad', 'waveform')))
                values = (item['common_mode_v'] + item['dc_v'], item['polarity'] * item['rf_amplitude_v'], 0.)
            else: raise ValueError('unsupported scientific drive kind')
            if not all(type(x) in (int, float) and math.isfinite(x) for x in values):
                raise ValueError('nonfinite scientific drive')
            for name, value in zip(_NAMES, values, strict=True): vectors[name][(instance, group)] = value
    if len(signatures) != 1: raise ValueError('one common RF phase, waveform and frequency required')
    frequency, phase, waveform = next(iter(signatures))
    if frequency <= 0 or waveform not in ('sine', 'cosine'):
        raise ValueError('unsupported RF coefficient')
    return vectors, dict(frequency_hz=frequency, phase_rad=phase, waveform=waveform)


def resolve_sfi_scalar_basis(*, model: Any, geometry: Mapping[str, Any], field_design: Mapping[str, Any],
                             flight: Mapping[str, Any], geometry_artifact: Mapping[str, Any] | OpenedArtifact,
                             samples: Mapping[str, Mapping[str, Any] | OpenedArtifact]) -> dict[str, Any]:
    """Verify public geometry and three scalar products for the existing SFI model.

    All paths remain owned by their producers; callers must protect returned
    producer references and records through their existing managed owner.
    """
    if not isinstance(samples, Mapping) or set(samples) != set(_NAMES):
        raise ValueError('three explicit named scalar products required')
    flight = validate_native_flight(flight, requires_rf=True)
    upstream, tof = native_frontend_instances(geometry['composition_plan'])
    doc0 = model.document
    document = _bound_tracking_model(model, {k: doc0['components_resolved'][k] for k in upstream},
                                     doc0['components_resolved'][tof], geometry, field_design, flight)
    vectors, rf = _group_vectors(document['drive'])
    producer, geo, geo_manifest = _small_product(geometry_artifact, 'geometry_artifact', ('projection',))
    meta = geo['metadata']
    if meta.get('backend') != 'comsol' or meta.get('scope') != 'geometry_only' or meta.get('native_reopen_verified') is not True:
        raise ValueError('successful reopened public geometry required')
    record = validate_file_record(producer['inputs']['execution_request'], 'geometry execution request')
    path = record_path(record, base_dir=geo_manifest.parent)
    verify_record('geometry execution request', record, base_dir=geo_manifest.parent)
    frozen = _read(path)
    payload = frozen['payload']
    if frozen.get('role') != 'run_artifact_workflow_request' or payload.get('action') != 'build_comsol_geometry':
        raise ValueError('geometry producer action differs')
    snapshot = payload['assembly']; projection = _read(record_path(geo['data']['projection'], base_dir=geo_manifest.parent))
    if snapshot['components_resolved'] != document['components_resolved'] or snapshot['composition_plan'] != geometry['composition_plan']:
        raise ValueError('geometry source components or physical plan differ')
    if payload['projection'] != projection or project_assembly_geometry(snapshot, outer_box_mm=projection['outer_box_mm']) != projection:
        raise ValueError('geometry canonical reprojection differs')
    expected = {(r['instance_id'], r['electrode_group_id']) for r in projection['electrode_groups']}
    if len(expected) != len(projection['electrode_groups']) or any(set(v) != expected for v in vectors.values()):
        raise ValueError('physical group coverage differs')
    bindings = {}; shared_request = None; carrier_exterior = None
    for name in _NAMES:
        item = open_artifact(samples[name], expected_kind='scalar_field_samples')
        meta = item.metadata
        if item.producer.get('status') != 'success' or meta.get('backend') != 'comsol' or meta.get('scope') != 'assembly_world_scalar_samples' or meta.get('field_status') != 'sampled':
            raise ValueError('successful public world scalar samples required')
        if _read(item.data_path('projection')) != projection: raise ValueError('scalar canonical projection differs')
        grid = _read(item.data_path('grid')); request = _read(item.data_path('request'))
        if validate_request(projection, request) != request: raise ValueError('scalar request differs')
        source_manifest = item.data_records['field_solution_manifest']
        source_path = item.data_path('field_solution_manifest')
        source_ref = {'manifest': dict(source_manifest, path=str(source_path)), 'product_id': 'solution'}
        source_owner, source, source_dir = _small_product(source_ref, 'field_solution',
            ('request', 'projection', 'geometry_validation', 'reopen_geometry', 'reopen_solution'))
        smeta = source['metadata']
        if (smeta.get('backend') != 'comsol' or smeta.get('scope') != 'single_stationary_workpoint'
                or smeta.get('field_status') != 'solved' or smeta.get('native_reopen_verified') is not True):
            raise ValueError('solved reopened source workpoint required')
        for key in ('request', 'projection', 'geometry_validation', 'reopen_geometry', 'reopen_solution'):
            selected = item.data_records[key]; original = source['data'][key]
            if any(selected[k] != original[k] for k in ('bytes', 'sha256')):
                raise ValueError('scalar source workpoint copy differs: ' + key)
        solution = smeta['solution']
        reopened = _read(item.data_path('reopen_solution'))
        if reopened.get('solution') != solution: raise ValueError('scalar cold solution differs')
        validate_solution_readback(solution, study_tag=grid['study_tag'], solution_tag=grid['solution_tag'], dataset_tag=grid['dataset_tag'])
        model_record = validate_file_record(source['data']['model'], 'source native model')
        if model_record not in [*source_owner['inputs'].values(), *source_owner['outputs']]:
            raise ValueError('solution model identity not bound to producer')
        sample_manifest = _read(item.manifest_location)
        if sample_manifest['inputs']['field_solution_model'] != model_record:
            raise ValueError('scalar export native model identity differs')
        _check_report(_read(item.data_path('report')), grid=grid,
            baseline=_read(item.data_path('reopen_geometry')), solution_identity=solution,
            model=record_path(model_record, base_dir=source_dir.parent))
        if meta.get('frame_id') != projection['assembly_frame_id'] or grid.get('frame_id') != projection['assembly_frame_id']:
            raise ValueError('scalar frame differs')
        current_grid = {k: grid[k] for k in ('frame_id', 'origin_mm', 'pitch_mm', 'dimensions')}
        rows = request['group_voltages']; actual = {(r['instance_id'], r['electrode_group_id']): r['voltage_v'] for r in rows}
        if len(actual) != len(rows) or actual != vectors[name]: raise ValueError('scalar group workpoint differs')
        exterior = request['exterior']
        if exterior['kind'] != 'potential': raise ValueError('unsupported exterior boundary kind')
        if name == 'carrier': carrier_exterior = exterior['voltage_v']
        elif exterior['voltage_v'] != 0.: raise ValueError('RF and pulse response exterior must be zero')
        other = {k: copy.deepcopy(v) for k, v in request.items() if k != 'group_voltages'}
        other['exterior'] = {'kind': exterior['kind']}
        if shared_request is not None and shared_request != other: raise ValueError('scalar BVP operator or mesh differs')
        shared_request = other
        paths = {key: item.data_path(key) for key in ('field_v', 'field_valid')}
        for path_value in paths.values():
            header = collision_pa_header(path_value)
            if (header.mode != -2 or header.symmetry != 1 or header.raw_mirror != COLLISION_NOTREFINABLE_FLAG
                    or (header.nx, header.ny, header.nz) != tuple(grid['dimensions'])
                    or (header.dx_mm, header.dy_mm, header.dz_mm) != tuple(grid['pitch_mm'])):
                raise ValueError('scalar PA header differs from grid')
        records = {key: dict(item.data_records[key], path=str(paths[key] if key in paths else item.data_locations[key])) for key in ('field_v', 'field_valid', 'grid')}
        if meta.get('conductor_support_policy') is not None:
            if meta['conductor_support_policy'] != 'unique_dirichlet_solid_interiors': raise ValueError('unsupported conductor support policy')
            records['conductor_support'] = dict(item.data_records['conductor_support'], path=str(item.data_path('conductor_support')))
            support = _read(Path(records['conductor_support']['path']))
            if support.get('schema_version') != 1 or support.get('role') != 'assembly_scalar_conductor_support':
                raise ValueError('scalar conductor support authority differs')
            for key in ('grid', 'projection', 'request', 'field_solution_manifest'):
                if support.get(key) != item.data_records[key]:
                    raise ValueError('scalar conductor support lineage differs: ' + key)
        bindings[name] = dict(reference=item.reference, field_solution_reference=source_ref, grid=current_grid, records=records,
                              ideal_sheet_projection=_ideal_sheet_projection(projection, current_grid))
    return dict(model_identity_sha256=document['model_identity_sha256'], clock=copy.deepcopy(document['drive']['clock']),
                pulse=copy.deepcopy(document['drive']['pulse']), rf=rf, carrier_exterior_voltage_v=carrier_exterior,
                geometry_reference=geometry_artifact.reference if isinstance(geometry_artifact, OpenedArtifact) else copy.deepcopy(dict(geometry_artifact)), geometry_execution_request=dict(record, path=str(path)),
                bases=bindings, scope='identity_admission_only_not_coverage_or_qualification')
