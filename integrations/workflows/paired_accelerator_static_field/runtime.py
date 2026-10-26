"""Vendor task preparation for the paired OA-only static-field workflow.

The public PowerShell entry owns runs, capacity and processes. PA lifecycle is
owned entirely by common.simion.pa_family_cache; this module adds no states.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from common.contracts.file_identity import file_sha256
from common.contracts.frozen_inputs import freeze_file
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.simion.pa_family_cache import (
    advance_pa_family_cache_transaction, canonical_pa_family_cache_key,
    load_pa_family_cache_transaction,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples import _require_static_samples
from common.analysis.field_comparison import merge_complete_samples
from integrations.runtime.paired_accelerator_model import load_paired_static_model_source
from .prepare import prepare

PROJECT = 'single_reflection_oa_tof_mass_analyzer'
ROLE = 'oatof_paired_accelerator_static_field_plan'
PA_NAME = 'paired_static_on.pa'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path: Path, value: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    return value


def prepare_run(run: Path) -> dict:
    """Compile from verified run-local small sources, retaining original binding."""
    source = Path(read(run/'run_config.json')['parameters']['request_source_path'])
    return prepare(run/'inputs/request.json', run/'inputs/bvp', source_snapshot_root=run/'inputs/sources',
                   source_base_dir=source.parent)


def cache_plan(run: Path, code: Path, native: Path, cache_root: Path) -> dict:
    """Use the public non-RF working-field identity; sampling/COMSOL mesh are absent."""
    plan = read(run/'inputs/bvp/paired_accelerator_static_field_plan.json')
    grid = plan['native_geometry_compilation']['grid']
    builders = {name: code/'common/simion'/name for name in (
        'build_dirichlet_patch_operating_pa.lua', 'export_detached_standalone_pa.lua')}
    executable = file_record(native)
    identity = dict(geometry=plan['accelerator_geometry'], gem=file_sha256(run/'inputs/bvp/paired_accelerator.gem'),
        working_points=[dict(kind='static_on', voltages_v=plan['static_on_electrode_voltages_v'],
                            refine_policy='installed_default')],
        mesh=grid['cell_mm_xyz'], grid_phase=grid['instance_origin_mm'], surface='none',
        boundary_policy=plan['numerical_domain']['boundary_policy'],
        simion_identity=dict(release='SIMION 2020', executable_bytes=executable['bytes'], executable_sha256=executable['sha256']),
        builder_identity={name: file_sha256(path) for name, path in builders.items()})
    write(run/'inputs/pa_cache_identity.json', identity)
    return dict(cache_root=str(cache_root), cache_key=canonical_pa_family_cache_key(identity), identity=identity,
                filenames=[PA_NAME], verifier_path=str(code/'projects'/PROJECT/'simion/export_paired_accelerator_field.lua'))


def advance_cache(run: Path, plan: dict, verification: Path | None = None, *,
                  capacity_session: dict | None = None,
                  producer_stopped_receipt: Path | None = None) -> dict:
    """Advance the existing owner; cross-run continuation requires a terminal producer."""
    root, key = Path(plan['cache_root']), plan['cache_key']
    transaction_path = root/'.transactions'/key/'transaction.json'
    arguments = {}
    owner = 'paired-static:'+read(run/'run_config.json')['run_id']
    transaction = load_pa_family_cache_transaction(root, key) if transaction_path.exists() else None
    if transaction is None:
        arguments.update(owner=owner, producer_run_config=run/'run_config.json')
    elif transaction['status'] in ('building', 'prepared'):
        producer = Path(transaction['producer']['run_config_path']).resolve().parent
        if producer != run.resolve():
            manifest_path = producer/'run_manifest.json'
            require_completed_terminal_publication(manifest_path)
            manifest = read(manifest_path)
            if manifest.get('status') not in ('success', 'failed', 'interrupted'):
                raise ValueError('original PA producer is not terminal')
            verify_record('producer config', manifest['run_config'], base_dir=producer)
            original = producer/'inputs/pa_cache_identity.json'
            records = list(manifest['inputs'].values())
            bound = [record for record in records if record_path(record, base_dir=producer) == original]
            if len(bound) != 1:
                raise ValueError('original field producer identity is not manifest-bound')
            verify_record('producer field identity', bound[0], base_dir=producer)
            if read(original) != plan['identity']:
                raise ValueError('original field producer scientific identity differs')
            if transaction['status'] == 'building' and not transaction['inventory_sha256']:
                if producer_stopped_receipt is None or capacity_session is None:
                    raise ValueError('PA producer handoff requires an explicit public stopped receipt and capacity session')
                handoff = dict(schema_version=1,
                    transaction_record=freeze_file(transaction_path, run/'inputs/pa_previous_transaction.json'),
                    predecessor_manifest=freeze_file(manifest_path, run/'inputs/pa_predecessor_manifest.json'),
                    stopped_receipt=freeze_file(producer_stopped_receipt, run/'inputs/pa_producer_stopped_receipt.json'),
                    capacity_lease_id=capacity_session['lease_id'],
                    capacity_lease_owner=capacity_session['owner'])
                arguments.update(owner=owner, producer_run_config=run/'run_config.json', producer_handoff=handoff)
            else:
                write(run/'inputs/pa_original_producer.json', dict(manifest=file_record(manifest_path),
                    run_config=manifest['run_config'], identity=bound[0], owner=transaction['owner'],
                    inventory_sha256=transaction['inventory_sha256']))
    if verification is not None:
        if transaction is None or not transaction['inventory_sha256']:
            raise ValueError('public prepared inventory required before native verification')
        arguments['verification_evidence'] = dict(schema_version=1, role='simion_pa_family_verification', status='pass',
            cache_key=key, inventory_sha256=transaction['inventory_sha256'], solver_release='SIMION 2020',
            verifier_path=plan['verifier_path'], verifier_sha256=file_sha256(plan['verifier_path']),
            verification_output_path=str(verification), verification_output_sha256=file_sha256(verification))
    result = advance_pa_family_cache_transaction(root, plan['identity'], plan['filenames'],
                                                recovery_policy='none', **arguments)
    return json.loads(json.dumps(asdict(result), default=str))


def validate_samples(plan: dict, path: Path) -> None:
    """Require the actual complete common point set; make no tolerance decision."""
    actual = pd.read_csv(path, float_precision='round_trip')
    _require_static_samples(actual, 'native')
    expected = pd.read_csv(plan['sample_points']['path'], float_precision='round_trip')
    columns = ['point_id', 'x_mm', 'y_mm', 'z_mm']
    merge_complete_samples(expected, actual, keys=columns, left_label='prepared', right_label='native')


def comsol_reuse(run: Path, manifest_path: Path) -> dict:
    """Verify the selected payload once at the actual field execution boundary."""
    source = load_paired_static_model_source(
        manifest_path, run/'inputs/comsol_source_manifest.json',
        expected_plan=read(run/'inputs/bvp/paired_accelerator_static_field_plan.json'))
    verify_record('COMSOL source model', source['model'], base_dir=manifest_path.parent)
    return write(run/'inputs/comsol_source.json', source)

def materialize_tasks(run: Path, code: Path, pa: Path, *, saved_model: Path | None = None,
                      saved_model_stage: str = 'solved_saved') -> dict:
    """Write only vendor-required Lua/MATLAB tasks; transport the existing plan."""
    # Run execution junctions are removed at terminal publication. Native model
    # facts must name enduring scientific paths before MATLAB saves them.
    run = run.resolve(strict=True)
    code = code.resolve(strict=True)
    if saved_model is not None:
        saved_model = saved_model.resolve(strict=True)
    plan_path = run/'inputs/bvp/paired_accelerator_static_field_plan.json'
    plan = read(plan_path)
    grid = plan['native_geometry_compilation']['grid']
    # A fixed adapter interface, not a general Lua serializer or another plan.
    quote = lambda path: json.dumps(str(path).replace('\\', '/'), ensure_ascii=False)
    p, o, n = grid['cell_mm_xyz'], grid['instance_origin_mm'], grid['dimensions']
    lua = ("local export=dofile(%s)\n"
           "local plan={schema_version=1,role='%s',coordinate_frame='oatof_global',"
           "native_geometry_compilation={grid={dimensions={nx=%s,ny=%s,nz=%s},"
           "cell_mm_xyz={x=%s,y=%s,z=%s},instance_origin_mm={x=%s,y=%s,z=%s}}},"
           "sample_points={path=%s,count=%s}}\n"
           "local count=export(%s,plan,%s,%s)\nprint('PAIRED_FIELD_EXPORT=PASS samples='..count)\n") % (
               quote(code/'projects'/PROJECT/'simion/export_paired_accelerator_field.lua'), ROLE,
               n['nx'], n['ny'], n['nz'], repr(p['x']), repr(p['y']), repr(p['z']),
               repr(o['x']), repr(o['y']), repr(o['z']),
               quote(run/'inputs/bvp/paired_accelerator_field_points.csv'), plan['sample_points']['count'],
               quote(pa), quote(run/'results/simion_field_samples.csv'), quote(run/'logs/simion_field_native_facts.txt'))
    lua_path = run/'inputs/export_simion_field.lua'; lua_path.write_text(lua, encoding='utf-8', newline='\n')
    def matlab(path: Path | str) -> str:
        return "'"+str(path).replace('\\', '/').replace("'", "''")+"'"
    task_path = run/'inputs/run_comsol_field.m'
    if saved_model_stage not in ('prepared_saved', 'solved_saved') or (saved_model is None and saved_model_stage != 'solved_saved'):
        raise ValueError('explicit prepared/saved or solved/saved model stage required')
    stage_argument = ", 'prepared_saved'" if saved_model_stage == 'prepared_saved' else ''
    task_path.write_text(
        f"addpath({matlab(code/'projects'/PROJECT/'comsol')});\n"
        f"build_and_export_paired_accelerator_field({matlab(plan_path)},{matlab(run/'comsol')},"
        f"{matlab(saved_model) if saved_model is not None else chr(39)+chr(39)}{stage_argument});\n", encoding='utf-8', newline='\n')
    return dict(lua=str(lua_path), matlab=str(task_path))


def field_build_arguments(plan: dict) -> dict:
    """Transport the provider ON map and grid origin to the public Lua builder."""
    o = plan['native_geometry_compilation']['grid']['instance_origin_mm']
    on = {int(key): value for key, value in plan['static_on_electrode_voltages_v'].items()}
    voltage_list = ','.join(format(on.get(index, 0.), '.17g') for index in range(1, max(on)+1))
    return dict(voltages=voltage_list,
                origin=','.join(format(o[axis], '.17g') for axis in 'xyz'))
