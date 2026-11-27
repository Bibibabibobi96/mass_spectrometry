"""Installed IP–MR public tracking admission and planning; no native execution."""
import copy
import json
import sys
import sysconfig
from pathlib import Path
from unittest.mock import patch


def run(fixture):
    from msplatform.backends.simion import operations, tracking_execution, rf_tracking_execution
    from msplatform.backends.simion import ip_mr_tracking_admission, rf_tracking_collection
    from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.resources import resource_path
    from msplatform.contracts.gas import BoxDomain
    from importlib.resources import files
    from msplatform.io.manifest_records import file_record
    from msplatform import examples, particle_release

    purelib=Path(sysconfig.get_paths()['purelib']).resolve()
    for module in (operations,tracking_execution,rf_tracking_execution,ip_mr_tracking_admission,rf_tracking_collection):
        assert Path(module.__file__).resolve().is_relative_to(purelib), module.__file__
    for name in ('rf_tracking.lua','ip_mr_scalar_field.lua','scalar_field_adapter.lua','rf_ip_tracking_hs1.lua','iob_core.lua','build_tracking_iob.lua'):
        assert native_resource_path(name).resolve().is_relative_to(purelib), name
    assert structural_seed_path(5).resolve().is_relative_to(purelib)
    reference=fixture['reference']
    admission=ip_mr_tracking_admission.admit_ip_mr_tracking_fields(reference)
    assert len(admission['basis']['bases'])==17 and len(admission['priority']['instances'])==5
    box=lambda lo,hi:BoxDomain(lo,hi,(True,True,True),(True,True,True))
    c=fixture['context'];context=ExecutionContext(workspace=Path(c['workspace'])/('installed-ip-mr-'+fixture['arm']),
        python_executable=Path(sys.executable),powershell_executable=Path(c['powershell_executable']),
        tools={'simion':Path(sys.executable)},host_state_path=Path(c['host_state_path']),policy_path=resource_path('host_resource_policy.json'),
        capacity_policy_path=Path(c['capacity_policy_path']),stage_policy_path=Path(c['stage_policy_path']))
    context.workspace.mkdir(parents=True,exist_ok=True)
    author=json.loads(files('msplatform').joinpath('components/ion_processor/config/gas_environment.json').read_text(encoding='utf8'))
    author['outer_state']=dict(pressure_pa=4,temperature_k=300,bulk_velocity_m_s=[1,2,3])
    env=context.workspace/'test_hs1_environment.json';env.write_text(json.dumps(author),encoding='utf8')
    request=dict(bath_domain=box((0,-10,-10),(211,10,10)),outer_domain=box((-10000,-10000,-10000),(10000,10000,10000)),
        environment_record=file_record(env),environment_instance_id='ion_processor',
        vendor_record=file_record(Path(fixture['vendor_path'])),numerics=dict(seed=40,hs1_steps_per_mfp=20))
    packet=particle_release.sample_release(examples.load_example('rf_oatof_functional_v1').release).to_dict()
    propagation=dict(schema_version=1,scope='continuous_assembly',dynamics=dict(kinematics='nonrelativistic',collisions='hs1',space_charge='none'),
        end_policy=dict(maximum_particle_age_us=200.),consumed_plane_events=[],stop=None)
    numerics=dict(maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80,grouped=0)
    options=dict(propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context,hs1_request=request)
    class ReachedOwner(Exception): pass
    def planned(*args,**kwargs):
        assert kwargs['payload']['fields']==reference
        assert len(kwargs['source_references'])>1
        assert kwargs['expected_operation_ids']==('build_tracking_iob','verify_tracking_iob','track_fly')
        raise ReachedOwner()
    with patch('msplatform.execution.owner.run_managed_stage',side_effect=planned) as owner:
        try:operations.track(reference,packet,**options)
        except ReachedOwner:pass
        else:raise AssertionError('installed public tracking did not reach owner')
        assert owner.call_count==1
        bad=copy.deepcopy(reference);bad['manifest']['sha256']='0'*64
        try:operations.track(bad,packet,**options)
        except AssertionError as exc:assert 'SHA-256 changed' in str(exc)
        else:raise AssertionError('tampered field manifest accepted')
        try:operations.track(reference,packet,scalar_field_basis={},**options)
        except ValueError as exc:assert 'already published' in str(exc)
        else:raise AssertionError('replacement sampled basis accepted')
        try:operations.track(reference,packet,recovery_reference={'path':'relative'},**options)
        except ValueError as exc:assert 'absolute predecessor' in str(exc)
        else:raise AssertionError('relative recovery accepted')
        assert owner.call_count==1
    print('INSTALLED_IP_MR_PUBLIC_ADMISSION=PASS basis=17 priority=5 negatives=3 owner=planning_only',flush=True)
