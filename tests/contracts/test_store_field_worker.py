"""Store-owned PA member cache with actual inert process-owner transport."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.field_worker import run_member
from msplatform.backends.simion.native_plans import plan_solve_fields
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution import owner
from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from tests.contracts.test_simion_field_worker import INERT_WORKER
from tests.contracts.test_simion_geometry_compiler import compiler_inputs


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class StoreFieldWorkerTests(unittest.TestCase):
    def test_store_worker_rejects_receipt_outside_owner_run(self):
        from msplatform.backends.simion import field_worker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root/'run'
            (run/'inputs').mkdir(parents=True)
            outside = root/'outside.json'
            outside.write_text('{"sentinel":true}', encoding='utf8')
            request = run/'inputs/member.json'
            request.write_text(json.dumps(dict(schema_version=1, transport='store_member_v1',
                context={}, immutable_records=[], parameters=dict(run_directory=str(run),
                    log_directory=str(run/'logs/member'), scratch_directory=str(run/'logs/member/scratch'),
                    receipt_path=str(outside)))), encoding='utf8')
            with patch.object(sys, 'argv', ['field_worker', str(request)]):
                with self.assertRaisesRegex(ValueError, 'paths escape'):
                    field_worker.main()
            self.assertEqual(outside.read_text(encoding='utf8'), '{"sentinel":true}')

    def test_fine_member_uses_protected_same_parent_asset(self):
        with tempfile.TemporaryDirectory(prefix='store-pa-fine-') as directory:
            root = Path(directory)
            assembly, numerics, _ = compiler_inputs(root/'author')
            compiled = compile_geometry(assembly, numerics=numerics)
            domains = copy.deepcopy(numerics['frontend_domains'])
            domains['parent']['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
            plan = plan_solve_fields(compiled, assembly['components_resolved'],
                drive=dict(pulse_voltage_policy_id='all_accelerator_electrodes_zero_before_pulse_v1', rf_reference_voltage_v=10000.),
                numerics=dict(boundary_policy='native_zero_neumann', frontend_domains=domains))
            plan['field_design']['domains'].append(dict(plan['field_design']['domains'][0],
                domain_id='entrance_refinement', boundary_policy='parent_dirichlet'))
            resources = dict(operating_builder=native_resource_path('build_dirichlet_patch_operating_pa.lua'),
                exporter=native_resource_path('export_detached_standalone_pa.lua'),
                verifier=native_resource_path('audit_frontend_working_fields.lua'))
            tool = dict(simion_identity=dict(release='SIMION 2020', executable_bytes=Path(sys.executable).stat().st_size,
                executable_sha256=file_sha256(sys.executable)),
                builder_identity={name:file_sha256(resources[name]) for name in ('operating_builder','exporter')})
            raw = root/'raw.pa#'; raw.write_bytes(b'INERT_NOT_GEOMETRY')
            script = root/'inert_worker.py'; script.write_text(INERT_WORKER, encoding='utf8')
            budget = root/'budget.json'; budget.write_text('{}', encoding='utf8')
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            store = ArtifactStore(root/'store')
            reports = []
            def action(session):
                base = dict(field_plan=plan, member_id='carrier_off', tool_identity=tool,
                    raw_geometry_record=file_record(raw, 'solver_native_binary'), resources=resources)
                parent = run_member(session, operation_id='parent', parameters=dict(base, domain_id='parent'), limits={})
                parent_reference = dict(cache_key=parent['cache_key'], record=dict(parent['record'], kind='carrier_off'))
                fine = run_member(session, operation_id='fine', parameters=dict(base,
                    domain_id='entrance_refinement', published_parent=parent_reference), limits={})
                reports.extend([parent, fine])
                return dict(status='success', summary={}, output_paths=[], required_output_paths=[],
                            retention_preserve_paths=[], manifest_extra_fields={})
            original = RunSession.run_process
            def transport(session, operation_id, **kwargs):
                kwargs['arguments'] = ['-I','-B','-X','utf8',str(script),kwargs['arguments'][-1]]
                return original(session, operation_id, **kwargs)
            env = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                       MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ, env), patch.object(RunSession, 'run_process', new=transport):
                result = owner.run_managed_stage(context, descriptor=dict(project='instrument_assembly',mode='field',software=[]),
                    run_id='20261127_120100__test__python__store-fine', payload={},
                    committed_new_bytes=32*1024*1024, commitment_inputs=[file_record(budget,'required_evidence')],
                    retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert fine member'),
                    expected_operation_ids=['parent','fine'], operation_dependencies={'fine':['parent']}, action=action,
                    action_record=file_record(Path(__file__),'required_evidence'), artifact_store=store,
                    completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            self.assertEqual(result['status'], 'success')
            self.assertEqual([row['native_count'] for row in reports], [3, 3])
            metadata = json.loads((Path(reports[1]['generation_directory'])/'member.json').read_text(encoding='utf8'))
            self.assertEqual(metadata['identity']['boundary_policy']['parent_cache_key'], reports[0]['cache_key'])
            self.assertEqual(metadata['identity']['boundary_policy']['parent_working_points'][0]['sha256'], reports[0]['record']['sha256'])
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0], 0)

    def test_miss_hit_missing_member_rebuilds_and_releases(self):
        with tempfile.TemporaryDirectory(prefix='store-pa-') as directory:
            root = Path(directory)
            assembly, numerics, _ = compiler_inputs(root/'author')
            compiled = compile_geometry(assembly, numerics=numerics)
            domains = copy.deepcopy(numerics['frontend_domains'])
            domains['parent']['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.002, pulse_delta=.003)
            plan = plan_solve_fields(compiled, assembly['components_resolved'],
                drive=dict(pulse_voltage_policy_id='all_accelerator_electrodes_zero_before_pulse_v1', rf_reference_voltage_v=10000.),
                numerics=dict(boundary_policy='native_zero_neumann', frontend_domains=domains))
            resources = dict(operating_builder=native_resource_path('build_dirichlet_patch_operating_pa.lua'),
                exporter=native_resource_path('export_detached_standalone_pa.lua'),
                verifier=native_resource_path('audit_frontend_working_fields.lua'))
            tool = dict(simion_identity=dict(release='SIMION 2020', executable_bytes=Path(sys.executable).stat().st_size,
                executable_sha256=file_sha256(sys.executable)),
                builder_identity={name:file_sha256(resources[name]) for name in ('operating_builder','exporter')})
            raw = root/'raw.pa#'; raw.write_bytes(b'INERT_NOT_GEOMETRY')
            script = root/'inert_worker.py'; script.write_text(INERT_WORKER, encoding='utf8')
            budget = root/'budget.json'; budget.write_text('{}', encoding='utf8')
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            store = ArtifactStore(root/'store')
            reports = []
            remaining = []
            selected = {'member': 'carrier_off'}
            def action(session):
                with store._db() as db:
                    before = db.execute('SELECT remaining FROM reservations WHERE id=?',
                        (session.capacity_session['lease_id'],)).fetchone()[0]
                reports.append(run_member(session, operation_id='member', parameters=dict(field_plan=plan,
                    domain_id='parent', member_id=selected['member'], tool_identity=tool,
                    raw_geometry_record=file_record(raw, 'solver_native_binary'), resources=resources), limits={}))
                with store._db() as db:
                    after = db.execute('SELECT remaining FROM reservations WHERE id=?',
                        (session.capacity_session['lease_id'],)).fetchone()[0]
                remaining.append((before, after))
                return dict(status='success', summary={}, output_paths=[], required_output_paths=[],
                            retention_preserve_paths=[], manifest_extra_fields={})
            original = RunSession.run_process
            def transport(session, operation_id, **kwargs):
                kwargs['arguments'] = ['-I','-B','-X','utf8',str(script),kwargs['arguments'][-1]]
                return original(session, operation_id, **kwargs)
            env = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                       MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ, env), patch.object(RunSession, 'run_process', new=transport):
                cases = [('carrier_off', 'miss', 3), ('rf_reference', 'miss', 3),
                         ('carrier_off', 'hit', 0), ('carrier_off', 'miss', 3),
                         ('rf_reference', 'hit', 0), ('rf_reference', 'miss', 3)]
                for i, (selected_member, disposition, native_count) in enumerate(cases):
                    selected['member'] = selected_member
                    if i == 5:
                        raw.write_bytes(b'INERT_CHANGED_GEOMETRY')
                    result = owner.run_managed_stage(context, descriptor=dict(project='instrument_assembly',mode='field',software=[]),
                        run_id=f'20261127_12000{i}__test__python__store-member', payload={},
                        committed_new_bytes=32*1024*1024, commitment_inputs=[file_record(budget,'required_evidence')],
                        retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert store member'),
                        expected_operation_ids=['member'], operation_dependencies={}, action=action,
                        action_record=file_record(Path(__file__),'required_evidence'), artifact_store=store,
                        completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
                    self.assertEqual(result['status'], 'success')
                    self.assertEqual(reports[-1]['cache_disposition'], disposition)
                    self.assertEqual(reports[-1]['native_count'], native_count)
                    self.assertLess(remaining[-1][1], remaining[-1][0])
                    if i == 5:
                        self.assertNotEqual(reports[-1]['cache_key'], reports[-2]['cache_key'])
                        raw.write_bytes(b'INERT_NOT_GEOMETRY')
                    if i == 2:
                        Path(reports[-1]['record']['path']).unlink()
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0], 0)
            self.assertEqual(raw.read_bytes(), b'INERT_NOT_GEOMETRY')
            store.high = 0
            store.low = 0
            with store.reserve(1):
                self.assertFalse(Path(reports[-1]['record']['path']).exists())
