"""Field-stage data/identity and actual owned inert-process transport, no SIMION."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.test_simion_model_execution import model_plan
from common.contracts.test_simion_prepared_model import model_inputs
from msplatform.backends.simion.downstream_fields_worker import DOWNSTREAM_RESOURCES, run_downstream
from msplatform.backends.simion.field_closure import downstream_identity
from msplatform.backends.simion.field_execution import plan_fields_execution
from msplatform.backends.simion.model import compile_prepared_model, PHYSICS
from msplatform.backends.simion.native_plans import _plan_downstream_solve_with_assets
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution import owner
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import file_record
from msplatform.execution.payload_inputs import materialize_payloads
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.execution.processes import ProcessExecutionError
from msplatform.io.file_identity import file_sha256


def field_case(root):
    model, assets, _seed, _plan = model_plan(root)
    _assembly, numerical, _compiled, _drive = model_inputs(root/'numerical-author')
    domains = copy.deepcopy(numerical['frontend_domains'])
    for value in domains.values():
        value['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
    numerics = dict(frontend_domains=domains, rf_reference_voltage_v=10000.,
        downstream_convergence_v=dict(flight_tube=.001, detector=.002, reflectron=.003))
    assets = {role:assets[role] for role in ('flight_tube','reflectron','detector')}
    resources = {name:native_resource_path(name) for name in DOWNSTREAM_RESOURCES}
    tool = dict(release='SIMION 2020', executable_bytes=Path(sys.executable).stat().st_size,
        executable_sha256=file_sha256(sys.executable))
    # The tool is deliberately Python for the inert transport fixture, not a
    # statement that a native SIMION executable or numerical result was tested.
    identity = downstream_identity(model, raw_assets=assets, convergence_v=numerics['downstream_convergence_v'],
        tool_identity=tool, builder_identities={name:file_sha256(path) for name,path in resources.items()})
    return model, assets, numerics, resources, identity


class FieldExecutionPlanningTests(unittest.TestCase):
    def test_declared_downstream_resources_cover_real_literal_loads_without_lua(self):
        """Keep declaration coverage on CI where the plain Lua test is skipped."""
        import re
        from msplatform.backends.simion.field_execution import FIELD_RESOURCES
        pending=list(DOWNSTREAM_RESOURCES)
        seen=set()
        while pending:
            name=pending.pop()
            if name in seen:continue
            seen.add(name)
            self.assertIn(name,DOWNSTREAM_RESOURCES)
            self.assertIn(name,FIELD_RESOURCES)
            text=native_resource_path(name).read_text(encoding='utf-8')
            pending.extend(re.findall(r"(?:loadfile|dofile)\(resource_dir\s*\.\.\s*['\"]/([^'\"]+)['\"]",text))
        self.assertIn('gem2pa_geometry.lua',seen)

    @unittest.skipUnless(Path('C:/Program Files/SIMION-2020/lua.exe').is_file(),'plain Lua interpreter unavailable')
    def test_all_actual_downstream_builders_load_frozen_transitive_closure_before_native(self):
        """Execute real builder prefixes, stopping at the first native PA call.

        This is not a replacement/inert builder: its real loadfile/dofile and
        physical projection validation execute. No SIMION/PA API is executed.
        """
        from msplatform.backends.simion.field_execution import FIELD_RESOURCES
        from msplatform.backends.simion.source import lua_value
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            model,assets,numerics,resources,identity=field_case(root/'author')
            frozen=root/'frozen';frozen.mkdir()
            for name in DOWNSTREAM_RESOURCES:
                (frozen/name).write_bytes(resources[name].read_bytes())
            plan,_assets=_plan_downstream_solve_with_assets(model,raw_geometry_assets=assets,
                working_directory=root/'work',convergence_v=numerics['downstream_convergence_v'],
                exporter_resource=frozen/'export_standalone_pa.lua',verifier_resource=frozen/'audit_downstream_fields.lua')
            for path,text in plan.materializations.items():
                target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(text,encoding='utf-8',newline='\n')
            def invoke(operation):
                arguments=operation['arguments']
                script=root/(operation['operation_id']+'.lua')
                script.write_text('arg='+lua_value(arguments[4:])+"\n"+
                    "local entered=false\nsimion={pas={close=function() entered=true;error('EXPECTED_NATIVE_BOUNDARY') end}}\n"+
                    'local okay,message=pcall(function() dofile('+lua_value(str(frozen/Path(arguments[3]).name))+') end)\n'+
                    "assert(not okay and entered and tostring(message):find('EXPECTED_NATIVE_BOUNDARY',1,true),tostring(message))\nprint('ACTUAL_BUILDER_CLOSURE_PASS')\n",
                    encoding='utf-8',newline='\n')
                return subprocess.run(['C:/Program Files/SIMION-2020/lua.exe',str(script)],cwd=root,
                    capture_output=True,text=True,encoding='utf-8',timeout=30)
            builders=[operation for operation in plan.operations if operation['operation_id'].startswith('solve_')]
            self.assertEqual(len(builders),3)
            for operation in builders:
                with self.subTest(builder=operation['operation_id']):
                    result=invoke(operation)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertIn('ACTUAL_BUILDER_CLOSURE_PASS',result.stdout)
            self.assertIn('gem2pa_geometry.lua',FIELD_RESOURCES)
            original=resources['gem2pa_geometry.lua'].read_bytes()
            (frozen/'gem2pa_geometry.lua').unlink()
            for operation in builders:
                with self.subTest(missing='gem2pa_geometry.lua',builder=operation['operation_id']):
                    result=invoke(operation)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('gem2pa_geometry.lua',result.stderr)
                    self.assertNotIn('ACTUAL_BUILDER_CLOSURE_PASS',result.stdout)
            changed={name:file_sha256(path) for name,path in resources.items()}
            changed['gem2pa_geometry.lua']='F'*64
            self.assertNotEqual(identity,downstream_identity(model,raw_assets=assets,
                convergence_v=numerics['downstream_convergence_v'],tool_identity=identity['tool_identity'],builder_identities=changed))
            self.assertEqual(native_resource_path('gem2pa_geometry.lua').read_bytes(),original)

    def test_graph_has_real_member_downstream_copy_and_source_free_workbench_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, _assets, numerics, _resources, _identity = field_case(root)
            before = copy.deepcopy(numerics)
            plan = plan_fields_execution(model, numerics=numerics)
            self.assertEqual(numerics, before)
            ids = plan['expected_operation_ids']
            self.assertEqual(ids, ['materialize_geometry', 'frontend_parent_carrier_off',
                'frontend_parent_rf_reference', 'frontend_parent_pulse_delta', 'downstream_fields',
                'materialize_field_responses', 'build_fields', 'verify_fields'])
            self.assertEqual(plan['operation_dependencies']['materialize_field_responses'], ids[1:5])
            self.assertEqual(plan['operation_dependencies']['verify_fields'], ['build_fields'])
            reused = plan_fields_execution(model, numerics=numerics,
                reuse_fields_reference={'manifest':{}, 'product_id':'fields'})
            self.assertEqual(reused['expected_operation_ids'], ids)
            self.assertTrue(reused['reuse_requested'])
            self.assertFalse(plan['reuse_requested'])
            for invalid in ({}, {**numerics,'ignored_mesh_override':1},
                            {**numerics,'downstream_convergence_v':dict(flight_tube=0)}):
                with self.assertRaises((ValueError, KeyError)):
                    plan_fields_execution(model, numerics=invalid)

    def test_downstream_identity_excludes_temporal_drive_but_binds_actual_spatial_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            model, assets, numerics, resources, identity = field_case(Path(directory))
            document = model.document
            drive = copy.deepcopy(document['drive'])
            drive['pulse']['time_us'] += 1
            for groups in drive['groups'].values():
                for group in groups.values():
                    if group['kind'] == 'rf':
                        group['frequency_hz'] *= 2
                        group['phase_rad'] += .1
            from msplatform.backends.simion.model import model_geometry
            changed = compile_prepared_model(model_geometry(model), document['components_resolved'], drive=drive, physics=PHYSICS)
            kwargs = dict(raw_assets=assets, convergence_v=numerics['downstream_convergence_v'],
                tool_identity=identity['tool_identity'], builder_identities={name:file_sha256(path) for name,path in resources.items()})
            self.assertEqual(downstream_identity(changed, **kwargs), identity)
            for field in ('raw_assets','convergence_v','tool_identity','builder_identities'):
                broken = copy.deepcopy(kwargs)
                if field == 'raw_assets': broken[field]['detector']['raw_record']['sha256'] = 'F'*64
                elif field == 'convergence_v': broken[field]['reflectron'] *= 2
                elif field == 'tool_identity': broken[field]['executable_sha256'] = 'F'*64
                else: broken[field]['build_reflectron_variant.lua'] = 'F'*64
                with self.subTest(field=field):
                    self.assertNotEqual(downstream_identity(model, **broken), identity)


INERT_DOWNSTREAM = r'''
"""TEST ONLY: real Python processes producing inert protocol bytes, never PA data."""
import json
from msplatform.backends.simion import downstream_fields_worker as worker
original=worker._native_operation
def inert(context,op,**kwargs):
    audit=op['operation_id']=='audit_downstream'
    text=json.dumps({'status':'success','fixture':'INERT_NOT_NATIVE_EVIDENCE',
        'checked_assets':[{'role':role} for role in ('flight_tube','reflectron','detector')]}) if audit else 'INERT_NOT_SOLVED_PA'
    code="from pathlib import Path;outputs="+repr(op['outputs'])+";text="+repr(text)+"\nfor p in outputs:\n path=Path(p);path.parent.mkdir(parents=True,exist_ok=True)\n if not path.exists(): path.write_text(text,encoding='utf-8')\nprint("+repr(op['success_marker'])+")"
    return original(context,dict(op,arguments=['-c',code]),**kwargs)
worker._native_operation=inert
worker.main()
'''


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class DownstreamWorkerTests(unittest.TestCase):
    def test_actual_public_execution_alias_reaches_the_same_owned_worker_and_original_release(self):
        actual_owner = owner.run_managed_stage
        observations = []
        def managed(*args, **options):
            original_action = options['action']
            def action(session):
                alias = session.run_dir
                canonical = session.artifact_run_dir.resolve()
                self.assertNotEqual(alias, canonical)
                self.assertEqual(alias.resolve(), canonical)
                self.assertEqual(Path(session.package['execution_alias']), alias)
                result = original_action(session)
                request_path = canonical/'inputs/downstream_fields.json'
                request = json.loads(request_path.read_text(encoding='utf-8'))
                parameters = request['parameters']
                work = Path(parameters['working_directory'])
                self.assertNotEqual(work, work.resolve())
                self.assertTrue(work.is_relative_to(alias))
                self.assertTrue(work.resolve().is_relative_to(canonical))
                self.assertEqual(Path(parameters['run_directory']), canonical)
                self.assertEqual(Path(parameters['log_directory']), canonical/'logs/downstream_fields')
                self.assertEqual(Path(parameters['receipt_path']), canonical/'results/downstream_fields.json')
                report = json.loads(Path(parameters['receipt_path']).read_text(encoding='utf-8'))
                self.assertEqual(report['request']['path'], str(request_path))
                self.assertEqual(report['native_count'], 5)
                observations.append(dict(alias=str(alias), canonical=str(canonical),
                    request_record=report['request'], working_directory=str(work),
                    worker_native_observations=report['native_operations']))
                return result
            options.update(action=action, use_short_execution_path=True)
            return actual_owner(*args, **options)
        with patch.object(owner, 'run_managed_stage', side_effect=managed):
            # Reuse all original scientific/protocol/source-byte/release assertions.
            self.test_actual_worker_uses_owned_raw_surface_closure_and_one_outer_release()
        self.assertEqual(len(observations), 1)
        self.assertFalse(Path(observations[0]['alias']).exists())
        print('INERT_DOWNSTREAM_ALIAS_PROOF='+json.dumps(observations, ensure_ascii=True), flush=True)

    def test_real_worker_rejects_relative_and_outside_working_paths_preserving_primary_and_secondary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'))
            actual_process = RunSession.run_process
            def inert_preflight(session, operation_id, **options):
                options.update(role='GATE', stage='inert_downstream_preflight')
                return actual_process(session, operation_id, **options)
            for case in ('relative', 'outside'):
                with self.subTest(case=case):
                    run = root/case
                    for name in ('inputs','results','logs'):
                        (run/name).mkdir(parents=True, exist_ok=True)
                    (run/'run_config.json').write_text('{"inputs":{}}', encoding='utf-8')
                    session = RunSession(context=context, artifact_root=root/'not-used-artifact-root',
                        run_id='inert-downstream-path-'+case, project='software_fixture', mode='analysis',
                        package=dict(run_dir=str(run), artifact_run_dir=str(run)), capacity_session={},
                        execution_request=run/'not-used.json', result_path=run/'result.json',
                        expected_operation_ids=('downstream_fields',))
                    work = Path('relative/downstream') if case == 'relative' else root/'outside-owned-run'
                    parameters = dict(compiled_model_record={}, raw_geometry_assets={}, owned_geometry_records=[],
                        working_directory=work, convergence_v={}, resources={}, spatial_identity={})
                    with patch.object(session, 'renew_capacity', return_value={}), \
                            patch.object(RunSession, 'run_process', inert_preflight):
                        with self.assertRaises(ProcessExecutionError) as caught:
                            run_downstream(session, parameters=parameters, limits={})
                    self.assertTrue(caught.exception.observed_process_exit_confirmed)
                    self.assertTrue(session.writers_stopped)
                    self.assertEqual(session.operations[0]['observation']['returncode'], 1)
                    self.assertEqual(len(session.resource_releases), 1)
                    error = (run/'logs/operation_0001.stderr.log').read_text(encoding='utf-8')
                    primary = 'ValueError: downstream stage paths escape the original run'
                    secondary = 'Downstream request binding preservation failed:'
                    self.assertIn(primary, error)
                    self.assertIn(secondary, error)
                    self.assertLess(error.index(primary), error.index(secondary))
                    self.assertFalse((run/'results/downstream_fields.json').exists())
                    self.assertFalse((root/'outside-owned-run').exists())
                    print('INERT_DOWNSTREAM_PATH_REFUSAL='+json.dumps(dict(case=case,
                        operations=session.operations, releases=session.resource_releases), ensure_ascii=True), flush=True)

    def test_large_executable_evidence_role_preserves_bytes_sha_and_avoids_pa_reader(self):
        from msplatform.backends.simion import downstream_fields_worker as worker
        from msplatform.io import manifest_records
        if not os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN'):
            self.skipTest('public GATE lease required for no-launch downstream preflight')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            model,assets,numerics,resources,identity=field_case(root)
            run=root/'run';run.mkdir()
            model_path=run/'compiled_model.json'
            model_path.write_text(json.dumps(model.document),encoding='utf-8')
            record=file_record(model_path,'required_evidence')
            context=ExecutionContext(workspace=root,python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable)},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'))
            for case in ('valid_tool_bad_builder','tool_sha','tool_bytes'):
                changed=copy.deepcopy(identity)
                if case=='tool_sha':changed['tool_identity']['executable_sha256']='F'*64
                elif case=='tool_bytes':changed['tool_identity']['executable_bytes']+=1
                else:changed['builder_identities']['build_detector_variant.lua']='F'*64
                expected='spatial identity differs' if case=='valid_tool_bad_builder' else 'SHA-256 changed' if case=='tool_sha' else 'byte count changed'
                with self.subTest(case=case), patch.object(manifest_records,'_UNBUFFERED_SOLVER_PAYLOAD_BYTES',1), patch.object(
                        manifest_records,'file_sha256_unbuffered',side_effect=AssertionError('exe is not a solver PA')) as unbuffered, patch.object(
                        worker,'_native_operation',side_effect=AssertionError('no native launch')) as native:
                    with self.assertRaisesRegex((ValueError,AssertionError),expected):
                        worker.execute_downstream(context,compiled_model_record=record,raw_geometry_assets=assets,
                            owned_geometry_records=[],run_directory=run,working_directory=run/'simion/downstream',
                            log_directory=run/'logs/downstream',receipt_path=run/'results/receipt.json',
                            convergence_v=numerics['downstream_convergence_v'],resources=resources,spatial_identity=changed,limits={})
                    unbuffered.assert_not_called()
                    native.assert_not_called()
                    self.assertFalse((run/'results/receipt.json').exists())

    def test_actual_worker_uses_owned_raw_surface_closure_and_one_outer_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, assets, numerics, resources, identity = field_case(root)
            source_before = {Path(row['path']):Path(row['path']).read_bytes() for asset in assets.values()
                             for row in [asset['raw_record'],*asset['surface_records']]}
            script = root/'inert_downstream.py'
            script.write_text(INERT_DOWNSTREAM, encoding='utf-8')
            budget = root/'budget.json'
            budget.write_text('{"bytes":10485760}', encoding='utf-8')
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'private.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            actual = RunSession.run_process
            def inert_transport(session, operation_id, **kwargs):
                if operation_id == 'downstream_fields':
                    self.assertEqual(kwargs['arguments'][4:6], ['-m','msplatform.backends.simion.downstream_fields_worker'])
                    kwargs['arguments'] = ['-I','-B','-X','utf8',str(script),kwargs['arguments'][-1]]
                try:
                    return actual(session, operation_id, **kwargs)
                except BaseException as failure:
                    for path in session.log_dir.glob('*.stderr.log'):
                        failure.add_note('INERT_STDERR='+path.read_text(encoding='utf-8'))
                    raise
            reports = []
            def action(session):
                model_path = session.declare_file(session.input_dir/'compiled_model.json', 'required_evidence')
                model_path.write_text(json.dumps(model.document), encoding='utf-8')
                record = file_record(model_path, 'required_evidence')
                session.add_input('compiled_model', record)
                session.add_input('inert_fixture', file_record(script, 'required_evidence'))
                work = session.run_dir/'simion/downstream'
                plan, bindings = _plan_downstream_solve_with_assets(model, raw_geometry_assets=assets,
                    working_directory=work, convergence_v=numerics['downstream_convergence_v'],
                    exporter_resource=resources['export_standalone_pa.lua'], verifier_resource=resources['audit_downstream_fields.lua'])
                for path in plan.declared_outputs:
                    session.declare_file(path, 'required_evidence' if path.endswith('.json') else 'solver_native_binary')
                for path in plan.materializations:
                    session.declare_file(path, 'required_evidence')
                copied = materialize_payloads(plan.input_copies, session=session, limits={})
                report = run_downstream(session, parameters=dict(compiled_model_record=record,
                    raw_geometry_assets=assets, owned_geometry_records=copied, working_directory=work,
                    convergence_v=numerics['downstream_convergence_v'], resources=resources, spatial_identity=identity), limits={})
                reports.append(report)
                self.assertEqual([row['role'] for row in report['assets']], [row['role'] for row in bindings])
                return dict(status='success', summary=dict(fixture='INERT_ONLY'), output_paths=plan.declared_outputs,
                    required_output_paths=plan.declared_outputs, retention_preserve_paths=[], manifest_extra_fields={})
            private = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            with patch.dict(os.environ, private), patch(
                    'msplatform.execution.capacity_admission._capacity_policy', return_value=policy), patch.object(
                    RunSession, 'run_process', new=inert_transport):
                result = owner.run_managed_stage(context,
                    descriptor=dict(project='instrument_assembly', mode='inert_downstream', software=[]),
                    run_id='20261104_120000__test__python__downstream-worker', payload={}, committed_new_bytes=10485760,
                    commitment_inputs=[file_record(budget, 'required_evidence')],
                    retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert native family fixture'),
                    expected_operation_ids=['materialize_geometry','downstream_fields'],
                    operation_dependencies={'downstream_fields':['materialize_geometry']}, action=action,
                    action_record=file_record(Path(__file__), 'required_evidence'),
                    completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            self.assertEqual(result['stage'], 'complete')
            self.assertEqual(reports[0]['native_count'], 5)
            self.assertEqual(reports[0]['refine_calls'], 3)
            self.assertEqual([len(row['family_records']) for row in reports[0]['assets']], [4,4,0])
            completion = json.loads((Path(result['run_directory'])/'results/execution_completion.json').read_text())
            self.assertEqual(len(completion['writer_completion']['operations']), 2)
            self.assertEqual(len(completion['writer_completion']['resource_releases']), 2)
            outer = completion['writer_completion']['resource_releases'][1]['completion_receipt']['host_release']
            self.assertFalse(outer['inherited'])
            for row in reports[0]['native_operations']:
                self.assertTrue(row['receipt']['host_release']['inherited'])
                self.assertEqual(row['receipt']['host_release']['token'], outer['token'])
            for path, before in source_before.items():
                self.assertEqual(path.read_bytes(), before)
