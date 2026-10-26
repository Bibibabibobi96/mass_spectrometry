"""Shared frozen OA static-model metadata for field and pulse consumers."""
from __future__ import annotations

import json
from pathlib import Path

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from integrations.runtime.single_flight_source import published_producer_input


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


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
    def comsol_inputs(plan: dict) -> dict:
        # An explicitly selected MPH already contains its geometry and mesh.
        # SIMION pitch/raster and numeric electrode IDs are not COMSOL inputs.
        instance = plan['oatof_instance_id']
        port = plan['composition_plan']['components'][instance]['ports']['side_entry']
        bindings = plan['native_geometry_compilation']['electrode_bindings'][instance]
        voltages = plan['static_on_electrode_voltages_v']
        roles = ('grounded_shield_id', 'accelerator_repeller_id', 'accelerator_grid1_id',
                 'accelerator_intermediate2_id', 'accelerator_grid2_id')
        return dict(
            **{name: plan[name] for name in ('schema_version', 'accelerator_variant', 'oatof_instance_id',
                                           'coordinate_frame', 'accelerator_electrical')},
            numerical_domain={key: value for key, value in plan['numerical_domain'].items() if key != 'cell_mm_xyz'},
            accelerator_geometry={key: value for key, value in plan['accelerator_geometry'].items() if key not in (
                'numerical_port_width_mm', 'numerical_port_height_mm', 'accelerator_port_aperture_discretization')},
            side_opening=dict(center_mm=port['center_mm'], **{key: port['cross_section'][key] for key in (
                'shape', 'width_mm', 'height_mm')}),
            role_voltages={**{role: voltages[str(bindings[role])] for role in roles},
                           'accelerator_ring_ids': [voltages[str(value)] for value in bindings['accelerator_ring_ids']]})
    borrowed = None
    if not any(record_path(row, base_dir=base) == (base/'comsol/comsol_field_solution.json').resolve() for row in records):
        # An export consumer declares its source explicitly. Follow its flat
        # model provenance directly, never an inferred ancestor/history chain.
        consumer_plan = read(record_path(bound(base/'inputs/bvp/paired_accelerator_static_field_plan.json')))
        if (consumer_plan.get('schema_version') != 2 or expected_plan is not None and (
                expected_plan.get('schema_version') != 2 or comsol_inputs(consumer_plan) != comsol_inputs(expected_plan))):
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
    if previous.get('schema_version') != 2 or (expected_plan is not None and (
            expected_plan.get('schema_version') != 2 or comsol_inputs(previous) != comsol_inputs(expected_plan))):
        raise ValueError('saved COMSOL field common BVP differs')
    # Original points are not an ES input: export-only may sample a new exact set.
    model = bound(base/'comsol/paired_accelerator_static.mph', verify=False)
    if (Path(checkpoint.get('plan_path', '')).resolve() != source_plan.resolve()
            or Path(checkpoint.get('model_path', '')).resolve() != record_path(model, base_dir=base)):
        raise ValueError('native COMSOL fact does not bind the source plan/model')
    backend = Path('projects')/'single_reflection_oa_tof_mass_analyzer'/'comsol/build_and_export_paired_accelerator_field.m'
    old_backend = bound(base/'inputs/runtime_snapshot'/backend)
    result = dict(manifest=dict(file_record(manifest_snapshot.resolve()), source_path=str(manifest_path)), solution=solution_record, source_stage=source_stage,
        plan=plan_record, model=model, backend=old_backend)
    if borrowed is not None and source_identity(borrowed) != source_identity(result):
        raise ValueError('export consumer changed its original COMSOL model source')
    return result
