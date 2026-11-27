"""Real Store stopped owner with one complete synthetic tracking unit.

The child is inert Python, not SIMION; its TRACE wire is only a software fixture.
"""
import json
import os
from dataclasses import replace
from functools import partial
from pathlib import Path
import sys

from msplatform.backends.simion.tracking_units import tracking_applicability
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import run_managed_stage
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from tests.contracts.test_execution_runtime import NormalOwnerTests
from tests.contracts.test_simion_tracking_units import INERT


def stopped_tracking_action(session, *, plan, status):
    unit=plan['units'][0]
    script=session.declare_file(session.input_dir/'inert_tracking.py','required_evidence')
    script.write_text(INERT,encoding='utf-8',newline='\n')
    payload=session.declare_file(session.input_dir/'inert_tracking.json','required_evidence')
    payload.write_text(json.dumps({'kind':'fly','native_run':unit['key'],
        'rows':plan['rows'][:unit['source_row_range'][1]]}),encoding='utf-8')
    inputs=[]
    for name,path in (('inert_script',script),('inert_payload',payload)):
        record=file_record(session.canonical_path(path),'required_evidence')
        session.add_input(name,record);inputs.append(record)
    session.run_process('track_fly__unit_0001',executable=Path(sys.executable),
        arguments=['-I','-B',str(script),str(payload)],role='GATE',stage='software_tests',limits=None,
        immutable_input_records=inputs)
    stdout=session.log_dir/'operation_0001.stdout.log'
    process=session.log_dir/'operation_0001.process.json'
    rows=[]
    for unit in plan['units']:
        row={key:unit[key] for key in ('key','source_row_range','expected_particle_ids')}
        row['complete']=unit['key']=='unit_0001'
        if row['complete']:
            row['build_metadata']={'terminal_evidence':{'schema_version':1,'native_run':unit['key']}}
            row['stdout_record']=file_record(session.canonical_path(stdout),'required_evidence')
            row['process_record']=file_record(session.canonical_path(process),'required_evidence')
        rows.append(row)
    binary=file_record(Path(sys.executable),'solver_native_binary')
    index=session.declare_file(session.log_dir/'tracking_units.json','required_evidence')
    index.write_text(json.dumps({'schema_version':1,'role':'simion_tracking_units',
        'applicability_sha256':tracking_applicability(plan),
        'native_executable_identity':{key:binary[key] for key in ('bytes','sha256')},
        'immutable_inputs':inputs,'units':rows}),encoding='utf-8')
    paths=[str(index),str(stdout),str(process)]
    if status=='failed':
        error=RuntimeError('inert tracking failed after complete first unit')
        error.failure_output_paths=paths
        raise error
    products={}
    if status=='success':
        marker=session.declare_file(session.result_dir/'trajectory.dat','required_evidence')
        marker.write_bytes(b'inert trajectory marker')
        paths.append(str(marker))
        products={'trajectory':{'schema_version':1,'kind':'trajectory_result','status':'complete',
                                'metadata':{},'data':{'marker':file_record(marker,'required_evidence')}}}
    return dict(status=status,summary={'fixture':'INERT_ONLY'},output_paths=paths,
                required_output_paths=paths,retention_preserve_paths=[],manifest_extra_fields={'products':products})


def create_stopped_tracking(root, plan, *, status='failed'):
    """Return (store, manifest record, context) for an explicit inert owner status."""
    if status not in {'failed','interrupted','success'}:
        raise ValueError('fixture status must be failed, interrupted or success')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    helper=NormalOwnerTests();policy=root/'capacity.json'
    policy.write_text(json.dumps(helper._policy()),encoding='utf-8')
    context=replace(helper._context(root),capacity_policy_path=policy,
        host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']))
    context.workspace.mkdir(parents=True,exist_ok=True)
    action=partial(stopped_tracking_action,plan=plan,status=status)
    args=helper._arguments(root,action)
    args.update(run_id='20261127_160000__test__python__tracking-'+status,
        expected_operation_ids=('track_fly__unit_0001',),operation_dependencies={},
        action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
    store=ArtifactStore(root/'store')
    if status=='failed':
        try:run_managed_stage(context,artifact_store=store,**args)
        except RuntimeError as exc:
            if str(exc)!='inert tracking failed after complete first unit': raise
        else:raise AssertionError('failed fixture unexpectedly succeeded')
        manifest=next(store.root.glob('assets/native_stage/*/*/runs/*/run_manifest.json'))
        reference=file_record(manifest,'required_evidence')
    else:
        reference=run_managed_stage(context,artifact_store=store,**args)['manifest']
    return store, reference, context
