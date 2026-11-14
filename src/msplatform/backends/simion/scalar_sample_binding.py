"""Shared public scalar sample lineage and grid validation."""
import copy
import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from msplatform.backends.simion.collision_overlay import COLLISION_NOTREFINABLE_FLAG, collision_pa_header
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.comsol.assembly_field_export import _check_report
from msplatform.backends.comsol.assembly_field_solution import validate_solution_readback
from msplatform.backends.comsol.assembly_geometry import _world_bounds
from msplatform.components.shape_query import shape_relation
from msplatform.io.manifest_records import record_path, require_completed_terminal_publication, validate_file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact

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

def verify_scalar_sample(reference: Mapping[str, Any] | OpenedArtifact,
                         projection: Mapping[str, Any], *,
                         check_workpoint: Callable[[dict[str, Any]], None],
                         resolve_reference: bool = False) -> dict[str, Any]:
    """Verify one public export and its cold-reopened source, without reading the MPH."""
    item = open_artifact(reference, expected_kind='scalar_field_samples')
    meta = item.metadata
    if (item.producer.get('status') != 'success' or meta.get('backend') != 'comsol'
            or meta.get('scope') != 'assembly_world_scalar_samples' or meta.get('field_status') != 'sampled'):
        raise ValueError('successful public world scalar samples required')
    if _read(item.data_path('projection')) != projection:
        raise ValueError('scalar canonical projection differs')
    grid = _read(item.data_path('grid'))
    request = _read(item.data_path('request'))
    if validate_request(projection, request) != request:
        raise ValueError('scalar request differs')
    source_record = item.data_records['field_solution_manifest']
    source_ref = {'manifest': dict(source_record, path=str(item.data_path('field_solution_manifest'))), 'product_id': 'solution'}
    owner, source, source_path = _small_product(source_ref, 'field_solution',
        ('request', 'projection', 'geometry_validation', 'reopen_geometry', 'reopen_solution'))
    smeta = source['metadata']
    if (smeta.get('backend') != 'comsol' or smeta.get('scope') != 'single_stationary_workpoint'
            or smeta.get('field_status') != 'solved' or smeta.get('native_reopen_verified') is not True):
        raise ValueError('solved reopened source workpoint required')
    for key in ('request', 'projection', 'geometry_validation', 'reopen_geometry', 'reopen_solution'):
        if any(item.data_records[key][k] != source['data'][key][k] for k in ('bytes', 'sha256')):
            raise ValueError('scalar source workpoint copy differs: ' + key)
    solution = smeta['solution']
    if _read(item.data_path('reopen_solution')).get('solution') != solution:
        raise ValueError('scalar cold solution differs')
    validate_solution_readback(solution, study_tag=grid['study_tag'], solution_tag=grid['solution_tag'], dataset_tag=grid['dataset_tag'])
    model_record = validate_file_record(source['data']['model'], 'source native model')
    if model_record not in [*owner['inputs'].values(), *owner['outputs']]:
        raise ValueError('solution model identity not bound to producer')
    if _read(item.manifest_location)['inputs']['field_solution_model'] != model_record:
        raise ValueError('scalar export native model identity differs')
    _check_report(_read(item.data_path('report')), grid=grid,
        baseline=_read(item.data_path('reopen_geometry')), solution_identity=solution,
        model=record_path(model_record, base_dir=source_path.parent))
    if meta.get('frame_id') != projection['assembly_frame_id'] or grid.get('frame_id') != projection['assembly_frame_id']:
        raise ValueError('scalar frame differs')
    geometry = {k: copy.deepcopy(grid[k]) for k in ('frame_id', 'origin_mm', 'pitch_mm', 'dimensions')}
    check_workpoint(request)
    paths = {key: item.data_path(key) for key in ('field_v', 'field_valid')}
    for path in paths.values():
        header = collision_pa_header(path)
        if (header.mode != -2 or header.symmetry != 1 or header.raw_mirror != COLLISION_NOTREFINABLE_FLAG
                or (header.nx, header.ny, header.nz) != tuple(grid['dimensions'])
                or (header.dx_mm, header.dy_mm, header.dz_mm) != tuple(grid['pitch_mm'])):
            raise ValueError('scalar PA header differs from grid')
    records = {key: dict(item.data_records[key], path=str(paths[key] if key in paths else item.data_locations[key]))
               for key in ('field_v', 'field_valid', 'grid')}
    if meta.get('conductor_support_policy') is not None:
        if meta['conductor_support_policy'] != 'unique_dirichlet_solid_interiors':
            raise ValueError('unsupported conductor support policy')
        records['conductor_support'] = dict(item.data_records['conductor_support'], path=str(item.data_path('conductor_support')))
        support = _read(item.data_path('conductor_support'))
        if support.get('schema_version') != 1 or support.get('role') != 'assembly_scalar_conductor_support':
            raise ValueError('scalar conductor support authority differs')
        for key in ('grid', 'projection', 'request', 'field_solution_manifest'):
            if support.get(key) != item.data_records[key]:
                raise ValueError('scalar conductor support lineage differs: ' + key)
    selected_reference = ({'manifest': dict(item.reference['manifest'], path=str(item.manifest_location)),
                           'product_id': item.product_id} if resolve_reference else item.reference)
    return dict(reference=selected_reference, field_solution_reference=source_ref, grid=geometry, records=records,
                ideal_sheet_projection=_ideal_sheet_projection(projection, geometry))
