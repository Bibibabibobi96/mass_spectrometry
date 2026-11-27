"""Shared frozen OA static-model metadata for field and pulse consumers."""
from __future__ import annotations

import json
import math
from pathlib import Path

from msplatform.io.manifest_records import record_path
from msplatform.execution.retention import verify_record
from msplatform.execution.retention import file_record
from msplatform.io.manifest_records import require_completed_terminal_publication
from msplatform.results.single_reflection_source import published_producer_input

# Read-only plan3 renderer projection. The source correspondence is the
# versioned frontend protocol in simion/tof_electrode_mapping.py; this is
# limited to its three-zone OA field domain, not the entire ground assembly.
_LEGACY_OA_ROLES = {
    'common_ground': 'grounded_shield_id',
    'accelerator_repeller': 'accelerator_repeller_id',
    'accelerator_intermediate_grid_1': 'accelerator_grid1_id',
    'accelerator_intermediate_grid_2': 'accelerator_intermediate2_id',
    'accelerator_exit_grid': 'accelerator_grid2_id',
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _role_voltages(plan: dict) -> dict:
    """Project a versioned OA-only frontend binding to ordered physical voltages."""
    try:
        composition = plan['composition_plan']['schema_version']
        if type(composition) is not int or composition not in (3, 5):
            raise ValueError('unsupported composition version')
        if plan['accelerator_variant'] != 'three_zone_square':
            raise ValueError('unsupported accelerator variant')
        bindings = plan['native_geometry_compilation']['electrode_bindings'][plan['oatof_instance_id']]
        if not isinstance(bindings, dict):
            raise ValueError('electrode bindings must be a mapping')
        if composition == 3:
            if set(bindings) != set(_LEGACY_OA_ROLES.values()) | {'accelerator_ring_ids'}:
                raise ValueError('legacy electrode binding shape differs')
            rings = bindings['accelerator_ring_ids']
            if not isinstance(rings, list):
                raise ValueError('legacy ring IDs must be ordered')
            fixed = {role: bindings[key] for role, key in _LEGACY_OA_ROLES.items()}
        else:
            fixed = {role: bindings[role] for role in _LEGACY_OA_ROLES}
            ring_names = sorted(set(bindings) - set(fixed))
            if ring_names != [f'accelerator_ring_{index:04d}' for index in range(1, len(ring_names) + 1)]:
                raise ValueError('canonical ring identities must be consecutive')
            rings = [bindings[name] for name in ring_names]
        identifiers = [*fixed.values(), *rings]
        if not rings or any(type(value) is not int or value <= 0 for value in identifiers) or len(set(identifiers)) != len(identifiers):
            raise ValueError('electrode IDs must be distinct positive integers')
        table = plan['static_on_electrode_voltages_v']
        if not isinstance(table, dict) or set(table) != {str(value) for value in identifiers}:
            raise ValueError('voltage table must cover exactly the OA electrodes')
        values = [table[str(value)] for value in identifiers]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise ValueError('electrode voltages must be finite')
        if table[str(fixed['common_ground'])] != 0:
            raise ValueError('OA shield must be grounded')
        electrical = plan['accelerator_electrical']['operating_voltages_v']
        expected = [electrical[key] for key in ('shield', 'repeller', 'grid1', 'intermediate2', 'grid2')]
        if not isinstance(electrical['rings'], list) or values != expected + electrical['rings']:
            raise ValueError('electrode voltages conflict with the frozen electrical design')
        return {**{role: table[str(identifier)] for role, identifier in fixed.items()},
                'accelerator_rings': [table[str(identifier)] for identifier in rings]}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'saved COMSOL field common BVP differs: {exc}') from exc



def paired_comsol_inputs(plan: dict) -> dict:
    # An explicitly selected MPH already contains its geometry and mesh.
    # SIMION pitch/raster and numeric electrode IDs are not COMSOL inputs.
    instance = plan['oatof_instance_id']
    port = plan['composition_plan']['components'][instance]['ports']['side_entry']
    return dict(
        **{name: plan[name] for name in ('schema_version', 'accelerator_variant', 'oatof_instance_id',
                                       'coordinate_frame', 'accelerator_electrical')},
        numerical_domain={key: value for key, value in plan['numerical_domain'].items() if key != 'cell_mm_xyz'},
        accelerator_geometry={key: value for key, value in plan['accelerator_geometry'].items() if key not in (
            'numerical_port_width_mm', 'numerical_port_height_mm', 'accelerator_port_aperture_discretization')},
        side_opening=dict(center_mm=port['center_mm'], **{key: port['cross_section'][key] for key in (
            'shape', 'width_mm', 'height_mm')}),
        role_voltages=_role_voltages(plan))

def load_paired_static_model_source(
    manifest_path: Path, manifest_snapshot: Path, *, expected_plan: dict | None = None,
) -> dict:
    """Bind a frozen paired model using its small published scientific records.

    No model payload is opened or hashed here. The executing owner must verify
    the returned model record before native consumption. A preparer may derive
    from the source plan directly, or compare explicitly supplied ES inputs.
    """
    require_completed_terminal_publication(manifest_path)
    manifest = read(manifest_snapshot)
    if (manifest.get('role') != 'simulation_run_manifest' or manifest.get('status') not in ('success', 'failed', 'interrupted')
            or manifest.get('project') != 'instrument_assembly'):
        raise ValueError('terminal instrument_assembly COMSOL producer required')
    base = manifest_path.parent
    records = [*manifest['inputs'].values(), *manifest['outputs']]
    def bound(path: Path, *, verify: bool = True) -> dict:
        matches = [row for row in records if record_path(row, base_dir=base) == path.resolve()]
        if not matches or any(row['bytes'] != matches[0]['bytes'] or row['sha256'] != matches[0]['sha256'] for row in matches):
            raise ValueError(f'COMSOL source record not consistently manifest-bound: {path}')
        if verify:
            verify_record(path.name, matches[0], base_dir=base)
        return matches[0]
    borrowed = None
    if not any(record_path(row, base_dir=base) == (base/'comsol/comsol_field_solution.json').resolve() for row in records):
        # An export consumer declares its source explicitly. Follow its flat
        # model provenance directly, never an inferred ancestor/history chain.
        consumer_plan = read(record_path(bound(base/'inputs/bvp/paired_accelerator_static_field_plan.json')))
        _role_voltages(consumer_plan)
        if (consumer_plan.get('schema_version') != 2 or expected_plan is not None and (
                expected_plan.get('schema_version') != 2 or paired_comsol_inputs(consumer_plan) != paired_comsol_inputs(expected_plan))):
            raise ValueError('saved COMSOL field common BVP differs')
        expected_plan = consumer_plan
        borrowed = read(record_path(bound(base/'inputs/comsol_source.json')))
        source_snapshot = bound(base/'inputs/comsol_source_manifest.json')
        def source_identity(source: dict) -> tuple:
            try:
                origin = source['manifest']
                return (source['source_stage'], str(Path(origin['source_path']).resolve()),
                    origin['bytes'], origin['sha256'].upper(),
                    *((str(record_path(source[key], base_dir=base)), source[key]['bytes'],
                       source[key]['sha256'].upper()) for key in ('solution', 'plan', 'model', 'backend')))
            except (KeyError, TypeError, AttributeError) as exc:
                raise ValueError('explicit flat COMSOL model source required') from exc
        borrowed_identity = source_identity(borrowed)
        if all(source_snapshot[key] == borrowed['manifest'][key] for key in ('bytes', 'sha256')):
            # Historical embedded execution aliases are provenance only.
            selected = published_producer_input(manifest, borrowed['manifest'])
            if record_path(selected) != record_path(source_snapshot):
                raise ValueError('COMSOL source manifest is not the declared frozen input')
        else:
            # A second export still carries the same original model source.
            # Check the one declared parent's flat receipt, without recursion.
            parent = read(record_path(source_snapshot))
            parent_base = record_path(parent['run_config']).parent
            claims = [row for row in parent['inputs'].values()
                      if record_path(row, base_dir=parent_base) == parent_base/'inputs/comsol_source.json']
            if len(claims) != 1:
                raise ValueError('declared export parent lacks its single model source')
            verify_record('declared export parent model source', claims[0], base_dir=parent_base)
            if source_identity(read(record_path(claims[0], base_dir=parent_base))) != borrowed_identity:
                raise ValueError('export consumer changed its original COMSOL model source')
        manifest_path = Path(borrowed['manifest']['source_path']).resolve()
        require_completed_terminal_publication(manifest_path)
        verify_record('original COMSOL producer manifest', dict(borrowed['manifest'], path=str(manifest_path)))
        manifest_snapshot = manifest_path
        manifest = read(manifest_snapshot)
        if (manifest.get('role') != 'simulation_run_manifest' or manifest.get('project') != 'instrument_assembly'
                or manifest.get('status') not in ('success', 'failed', 'interrupted')):
            raise ValueError('terminal instrument_assembly COMSOL producer required')
        base = manifest_path.parent
        records = [*manifest['inputs'].values(), *manifest['outputs']]
    solution_path = base/'comsol/comsol_field_solution.json'
    solution_record = bound(solution_path)
    checkpoint = read(record_path(solution_record, base_dir=base))
    source_stage = checkpoint.get('status')
    tetrahedra = checkpoint.get('tetrahedra')
    if (checkpoint.get('schema_version') != 1
            or checkpoint.get('role') != 'oatof_paired_accelerator_static_field_solution'
            or source_stage not in ('prepared_saved', 'solved_saved')
            or checkpoint.get('solution_present') is not (source_stage == 'solved_saved')
            or checkpoint.get('solution_tag') != 'sol1'
            or (source_stage == 'prepared_saved' and (
                checkpoint.get('mesh_complete') is not True
                or not (type(tetrahedra) is int or type(tetrahedra) is float and tetrahedra.is_integer())
                or tetrahedra <= 0
                or checkpoint.get('study_tag') != 'std1'))):
        raise ValueError('explicit prepared/saved or solved/saved native COMSOL fact required')
    plan_record = bound(base/'inputs/bvp/paired_accelerator_static_field_plan.json')
    source_plan = record_path(plan_record, base_dir=base)
    previous = read(source_plan)
    _role_voltages(previous)
    if previous.get('schema_version') != 2 or (expected_plan is not None and (
            expected_plan.get('schema_version') != 2 or paired_comsol_inputs(previous) != paired_comsol_inputs(expected_plan))):
        raise ValueError('saved COMSOL field common BVP differs')
    # Original points are not an ES input: export-only may sample a new exact set.
    model = bound(base/'comsol/paired_accelerator_static.mph', verify=False)
    if (Path(checkpoint.get('plan_path', '')).resolve() != source_plan.resolve()
            or Path(checkpoint.get('model_path', '')).resolve() != record_path(model, base_dir=base)):
        raise ValueError('native COMSOL fact does not bind the source plan/model')
    backend_candidates = [
        Path('projects/single_reflection_oa_tof_mass_analyzer/comsol/build_and_export_paired_accelerator_field.m'),
        Path('src/msplatform/backends/comsol/matlab/build_and_export_paired_accelerator_field.m'),
    ]
    backend_matches = [path for path in backend_candidates if any(
        record_path(row, base_dir=base) == (base/'inputs/runtime_snapshot'/path).resolve() for row in records)]
    if len(backend_matches) != 1:
        raise ValueError('COMSOL source requires exactly one manifest-bound backend resource location')
    old_backend = bound(base/'inputs/runtime_snapshot'/backend_matches[0])
    result = dict(manifest=dict(file_record(manifest_snapshot.resolve()), source_path=str(manifest_path)), solution=solution_record, source_stage=source_stage,
        plan=plan_record, model=model, backend=old_backend)
    if borrowed is not None and source_identity(borrowed) != source_identity(result):
        raise ValueError('export consumer changed its original COMSOL model source')
    return result
