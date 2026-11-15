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

def _ideal_sheet_projection(projection: Mapping[str, Any], grid: Mapping[str, Any], *, allow_partial: bool = False) -> list[dict[str, Any]]:
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
            if not allow_partial:
                raise ValueError('intersecting ideal sheet is not aligned with scalar grid')
            # Conservative bounds retain the true canonical plane; never snap it.
            rows.append(dict(instance_id=member['instance_id'], electrode_group_id=member['electrode_group_id'],
                             member_id=member['member_id'], unsupported_bounds_mm=[
                                 [math.nextafter(lo[a], -math.inf), math.nextafter(hi[a], math.inf)] for a in range(3)]))
            continue
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

def original_sample_source(item: OpenedArtifact) -> OpenedArtifact | None:
    """Verify the flattened raw producer for an explicitly derived sample."""
    meta = item.metadata
    derived = meta.get('derivation') == 'offline_from_published_raw_samples'
    reference = meta.get('original_samples_reference')
    if not derived:
        if reference is not None: raise ValueError('original source reference requires derived samples')
        return None
    if reference is None: raise ValueError('derived samples require original source reference')
    original = open_artifact(reference, expected_kind='scalar_field_samples')
    if original.producer.get('status') != 'success':
        raise ValueError('original samples producer must be successful')
    if (original.metadata.get('derivation') is not None
            or original.metadata.get('original_samples_reference') is not None):
        raise ValueError('original samples source must be flattened')
    raw = ('sampled_field_v', 'sampled_field_valid')
    if not all(k in original.data_records for k in raw):
        if any(k in original.data_records for k in raw) or original.metadata.get('conductor_support_policy') is not None:
            raise ValueError('original samples have incomplete raw pair')
        raw = ('field_v', 'field_valid')
    pairs = [('sampled_field_v', raw[0]), ('sampled_field_valid', raw[1])]
    names = ('grid','projection','request','geometry_validation','reopen_geometry',
             'reopen_solution','report','field_solution_manifest')
    pairs += [(name, name) for name in names]
    for name in ('writer', 'writer_manifest'):
        if name in item.data_records or name in original.data_records:
            pairs.append((name, name))
    for selected, source in pairs:
        if selected not in item.data_records or source not in original.data_records:
            raise ValueError('derived sample source record missing: ' + selected)
        a, b = item.data_records[selected], original.data_records[source]
        if (any(a.get(key) != b.get(key) for key in ('bytes','sha256','retention_role'))
                or item.data_path(selected).resolve(strict=True) != original.data_path(source).resolve(strict=True)):
            raise ValueError('derived sample source record differs: ' + selected)
    return original


def verify_scalar_sample(reference: Mapping[str, Any] | OpenedArtifact,
                         projection: Mapping[str, Any], *,
                         check_workpoint: Callable[[dict[str, Any]], None],
                         resolve_reference: bool = False, allow_partial_sheets: bool = False) -> dict[str, Any]:
    """Verify one public export and its cold-reopened source, without reading the MPH."""
    item = open_artifact(reference, expected_kind='scalar_field_samples')
    meta = item.metadata
    original = original_sample_source(item)
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
    native_owner = original if original is not None else item
    if _read(native_owner.manifest_location)['inputs']['field_solution_model'] != model_record:
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
    binding = dict(reference=selected_reference, field_solution_reference=source_ref, grid=geometry, records=records,
                   ideal_sheet_projection=_ideal_sheet_projection(projection, geometry, allow_partial=allow_partial_sheets))
    if original is not None:
        binding['original_samples_reference'] = original.reference
    return binding


def _validate_window_halo(grid: Mapping[str, Any], box: Any, label: str) -> None:
    """Apply the existing adapter halo rule to an already validated grid and box."""
    for i, (lo, hi) in enumerate(box):
        qlo=(lo-grid['origin_mm'][i])/grid['pitch_mm'][i]
        qhi=(hi-grid['origin_mm'][i])/grid['pitch_mm'][i]
        if math.floor(qlo)-1 < 0 or math.ceil(qhi)+1 >= grid['dimensions'][i]:
            raise ValueError('scalar refinement active box lacks support halo: ' + label)


def _validate_representation_grid(projection: Mapping[str, Any], grid: Mapping[str, Any]) -> None:
    if not isinstance(grid, Mapping) or grid.get('frame_id') != projection.get('assembly_frame_id') or not isinstance(grid.get('frame_id'), str) or not grid['frame_id']:
        raise ValueError('scalar representation grid frame differs')
    for key in ('origin_mm', 'pitch_mm', 'dimensions'):
        if not isinstance(grid.get(key), (list, tuple)) or len(grid[key]) != 3:
            raise ValueError('scalar representation grid requires three axes')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in grid['origin_mm']):
        raise ValueError('scalar representation origin must be finite')
    if any(type(x) not in (int,float) or not math.isfinite(x) or x <= 0 for x in grid['pitch_mm']):
        raise ValueError('scalar representation pitch must be finite and positive')
    if any(type(x) is not int or x < 2 for x in grid['dimensions']):
        raise ValueError('scalar representation dimensions must be integer and at least two')


def preflight_scalar_representation(projection: Mapping[str, Any], base_grid: Mapping[str, Any],
                                    windows: list[Mapping[str, Any]], *, allow_partial_sheets: bool) -> dict[str, Any]:
    """Report planned sheet representation and ordered halo; no mask or flight claim."""
    if type(allow_partial_sheets) is not bool: raise ValueError('explicit partial sheet policy required')
    if not isinstance(projection, Mapping) or not isinstance(projection.get('members'), list):
        raise ValueError('canonical projection members required')
    if not isinstance(windows, list): raise ValueError('ordered scalar refinement windows must be a list')
    _validate_representation_grid(projection,base_grid)
    def sheet_rows(grid):
        try:
            return _ideal_sheet_projection(projection,grid,allow_partial=allow_partial_sheets)
        except (KeyError, TypeError) as exc:
            raise ValueError('malformed or unsupported canonical sheet bounds') from exc
    def capabilities(grid):
        return dict(any_supported_stencil=all(n >= 3 for n in grid['dimensions']))
    levels=[dict(name='base',ideal_sheet_projection=sheet_rows(base_grid),**capabilities(base_grid))]
    names=set()
    for window in windows:
        if not isinstance(window,Mapping) or set(window)!={'name','active_box_mm','grid'}:raise ValueError('planned window requires name, active box and grid')
        name=window['name'];box=window['active_box_mm'];grid=window['grid']
        if not isinstance(name,str) or not name.strip() or name in names:raise ValueError('scalar refinement window names must be nonempty and unique')
        names.add(name)
        if (not isinstance(box,(list,tuple)) or len(box)!=3 or any(not isinstance(axis,(list,tuple)) or len(axis)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in axis) or axis[0]>=axis[1] for axis in box)):
            raise ValueError('scalar refinement active box must contain three finite ordered intervals')
        _validate_representation_grid(projection,grid);_validate_window_halo(grid,box,name)
        levels.append(dict(name=name,active_box_mm=copy.deepcopy(box),ideal_sheet_projection=sheet_rows(grid),**capabilities(grid)))
    return dict(scope='representation_only_no_mask_or_trajectory_claim',allow_partial_sheets=allow_partial_sheets,levels=levels)


def attach_refinement_windows(bindings: dict[str, Any], refinement_windows: list[Mapping[str, Any]] | None, *,
                              admit_level: Callable[[Any], dict[str, Any]]) -> None:
    """Apply the existing ordered named windows to every admitted basis."""
    if refinement_windows is None:
        return
    if not isinstance(refinement_windows, list): raise ValueError('ordered scalar refinement windows must be a list')
    names = set()
    for window in refinement_windows:
        if not isinstance(window, Mapping) or set(window) != {'name', 'active_box_mm', 'samples'}:
            raise ValueError('scalar refinement window requires name, active box and samples')
        label = window['name']; box = window['active_box_mm']
        if not isinstance(label, str) or not label.strip() or label in names:
            raise ValueError('scalar refinement window names must be nonempty and unique')
        names.add(label)
        if (not isinstance(box, (list, tuple)) or len(box) != 3 or
            any(not isinstance(axis, (list, tuple)) or len(axis) != 2 or
                any(type(value) not in (int, float) or not math.isfinite(value) for value in axis) or axis[0] >= axis[1] for axis in box)):
            raise ValueError('scalar refinement active box must contain three finite ordered intervals')
        levels = admit_level(window['samples'])['bases']
        if set(levels) != set(bindings): raise ValueError('scalar refinement basis coverage differs')
        for name, base in bindings.items():
            level = levels[name]
            left, right = base['field_solution_reference']['manifest'], level['field_solution_reference']['manifest']
            if any(left[k] != right[k] for k in ('bytes', 'sha256')):
                raise ValueError('scalar refinement source workpoint differs: ' + name)
            grid = level['grid']
            _validate_window_halo(grid,box,label)
            level.update(name=label, active_box_mm=copy.deepcopy(box))
            base.setdefault('refinement_windows', []).append(level)
