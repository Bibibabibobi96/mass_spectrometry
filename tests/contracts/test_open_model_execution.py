"""Real inert child/owner transport and COM doubles; never launches SolidWorks."""
from __future__ import annotations

from functools import partial
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.applications.model_execution import execute_open_model
from msplatform.applications import solidworks_worker
from msplatform.results.artifacts import open_artifact
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import file_record
from msplatform.execution import owner
from msplatform.execution.payload_inputs import materialize_payloads
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession


def inert_worker_entry(request_path, mode):
    """Test-only native COM double; actual Python child keeps its original handle."""
    import json
    from pathlib import Path
    import subprocess
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch
    from msplatform.applications import solidworks, solidworks_worker

    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    root = Path(request['run_directory'])
    exit_signal = root/'inert_child_exit'
    # A finite test child self-exits naturally if cleanup fails; never a vendor
    # timeout or a production permission to terminate a healthy GUI.
    child_code = ('import pathlib,sys,time;p=pathlib.Path(sys.argv[1]);end=time.monotonic()+2;'
                  '\nwhile not p.exists() and time.monotonic()<end:time.sleep(.01)')
    original_popen = subprocess.Popen
    children = []

    def launch(_argv, **_kwargs):
        child = original_popen([sys.executable, '-I', '-c', child_code+('\ntime.sleep(5.2)' if mode == 'delayed_exit_slow' else '\ntime.sleep(.25)' if mode.startswith('delayed_exit') else '')+('\nsys.exit(7)' if mode in {'application_exit7','delayed_exit7'} else ''), str(exit_signal)])
        children.append(child)
        return child

    class ComError(Exception):
        pass

    class App:
        def __init__(self):
            self.docs = []
            self.prefs = {8: 'original-template', 9: 'original-assembly-template', 111: False, 691: False}

        def DocumentVisible(self, visible, kind):
            assert visible is True and kind == 2
            self.creation_visible = True

        @property
        def ActiveDoc(self):
            return self.docs[-1] if self.docs and getattr(self, 'display_setup_done', False) else None

        def ActivateDoc3(self, title, preferences, rebuild_option, errors):
            assert title == 'owned' and preferences is False and rebuild_option == 1
            self.display_setup_done = True
            errors.value = 0
            return self.docs[-1]

        def GetProcessID(self):
            return children[0].pid+(1 if mode == 'wrong_pid' else 0)

        def RevisionNumber(self):
            return '30.5'

        def GetDocumentCount(self):
            if mode.startswith('delayed_exit') and getattr(self, 'shutdown_started', False):
                raise ComError(-2147417848, 'original app closing RPC disconnected')
            if mode in {'application_exit', 'application_exit7'} and children[0].poll() is not None:
                raise ComError(-2147417848, 'native app COM disconnected')
            return len(self.docs)

        def GetDocuments(self):
            if self.docs and not getattr(self, 'display_setup_done', False):
                return tuple(self.docs)
            if mode.startswith('delayed_exit') and self.docs:
                self.shutdown_started = True
                self.docs.clear()
                exit_signal.write_text('original handle closing before exit', encoding='utf-8')
                assert children[0].poll() is None, 'fixture did not expose live native shutdown race'
                return ()
            if mode in {'application_exit', 'application_exit7'} and self.docs:
                exit_signal.write_text('original app naturally exits', encoding='utf-8')
                children[0].wait()
                raise ComError(-2147417848, 'native app COM disconnected')
            if not self.docs:
                raise AttributeError('real empty-document collection unavailable')
            checked = [(key, request[key]) for key in ('source_step', 'controlled_step', 'template_record', 'assembly_template_record')]
            checked.extend(('source_'+kind+'_template', record) for kind, record in request['source_template_records'].items())
            for key, record in checked:
                try:
                    with Path(record['path']).open('ab'):
                        pass
                except OSError:
                    print('INERT_GUARD_BLOCKED='+key, flush=True)
                else:
                    raise AssertionError('live viewer did not guard '+key)
            if mode == 'primary_restore':
                raise ValueError('ORIGINAL_VIEW_PRIMARY')
            if 'geometry_inspection' in request:
                self.inspection_reads = getattr(self, 'inspection_reads', 0)+1
                if self.inspection_reads <= 2:
                    record = request['geometry_inspection']['report_record']
                    try:
                        Path(record['path']).open('ab').close()
                    except OSError:
                        print('INERT_GUARD_BLOCKED=inspection_report', flush=True)
                    else:
                        raise AssertionError('inspection report not guarded')
                    return tuple(self.docs)
            self.docs.clear()  # Observed natural close, not a Save/CloseDoc call.
            return ()

        def GetOpenDocumentByName(self, _):
            return None

        def GetUserPreferenceStringValue(self, key):
            return self.prefs[key]

        def GetUserPreferenceToggle(self, key):
            return self.prefs[key]

        def SetUserPreferenceStringValue(self, key, value):
            if mode == 'primary_restore' and value == 'original-template':
                raise RuntimeError('RESTORE_SECONDARY')
            self.prefs[key] = value
            return True

        def SetUserPreferenceToggle(self, key, value):
            self.prefs[key] = value

        def LoadFile4(self, _path, _args, _data, errors):
            if mode == 'primary_restore':
                raise ValueError('ORIGINAL_VIEW_PRIMARY')
            document = SimpleNamespace(GetType=lambda: 2, GetTitle=lambda: 'owned', Visible=self.creation_visible,
                IsOpenedReadOnly=lambda: False, GetBodies2=lambda *_: [],
                GetPathName=lambda: '', GetComponents=lambda *_: [])
            self.docs.append(document)
            errors.value = 0
            return document

        def CloseDoc(self, _title):
            self.docs.clear()

        def ExitApp(self):
            exit_signal.write_text('original child natural exit', encoding='utf-8')

    app = App()

    def active(_name):
        if not children:
            raise ComError('no existing user application')
        return app

    pc = SimpleNamespace(com_error=ComError, CoInitialize=lambda: None, CoUninitialize=lambda: None,
        VT_BYREF=1, VT_I4=2, VT_DISPATCH=4)
    client = SimpleNamespace(GetActiveObject=active, VARIANT=lambda _kind, value: SimpleNamespace(value=value))
    with patch.object(solidworks, '_com_modules', return_value=(pc, client)), \
            patch.object(solidworks_worker.subprocess, 'Popen', side_effect=launch):
        try:
            solidworks_worker.view_step(request_path)
        finally:
            assert all(child.poll() is not None for child in children), 'worker released a live inert child'


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows source guards and managed process required')
class OpenModelExecutionTests(unittest.TestCase):
    def request(self, root):
        run = root/'run'
        (run/'inputs/view').mkdir(parents=True)
        (run/'results').mkdir()
        source = root/'source.step'
        copied = run/'inputs/view/assembly.step'
        tool = root/'SLDWORKS.exe'
        template = run/'inputs/view/part_template.prtdot'
        assembly = run/'inputs/view/assembly_template.asmdot'
        source_part, source_assembly = root/'clean.prtdot', root/'clean.asmdot'
        for target in (source, copied, tool, template, assembly, source_part, source_assembly):
            target.write_bytes(b'INERT_NOT_STEP_TEMPLATE_OR_EXECUTABLE')
        request = dict(schema_version=2, role='solidworks_model_view_request', run_directory=str(run),
            source_step=file_record(source, 'solver_native_binary'), controlled_step=file_record(copied, 'solver_native_binary'),
            executable_record=file_record(tool, 'required_evidence'), template_record=file_record(template, 'required_evidence'),
            assembly_template_record=file_record(assembly, 'required_evidence'),
            source_template_records=dict(part=file_record(source_part, 'required_evidence'), assembly=file_record(source_assembly, 'required_evidence')),
            com_class='SldWorks.Application.30', lifecycle='document_close',
            ready_path=str(run/'results/model_view_ready.json'), receipt_path=str(run/'results/model_view_receipt.json'))
        path = run/'inputs/model_view_request.json'
        path.write_text(json.dumps(request), encoding='utf-8')
        return path, request

    def test_inspection_report_binding_and_unknown_fields_fail_before_native(self):
        for failure in ('step_sha', 'missing_member', 'unknown_checks', 'unknown_block', 'report_tamper'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                path, request = self.request(Path(directory))
                target = Path(request['run_directory'])/'inputs/view/cad_export_report.json'
                checks = dict(schema_version=1, kind='selected_solid_geometry_v1', selected_step_members=['member_00008'])
                report = dict(schema_version=1, role='owned_assembly_step_export', step_record=dict(request['controlled_step']),
                    projection=dict(schema_version=1, role='assembly_step_projection', representation='physical_solids',
                        length_unit='mm', exported_members=[dict(step_name='member_00008')]))
                if failure == 'step_sha':
                    report['step_record']['sha256'] = '0'*64
                elif failure == 'missing_member':
                    checks['selected_step_members'] = ['member_00099']
                elif failure == 'unknown_checks':
                    checks['arbitrary_oracle'] = True
                target.write_text(json.dumps(report), encoding='utf-8')
                request['geometry_inspection'] = dict(checks=checks, report_record=file_record(target, 'required_evidence'))
                if failure == 'unknown_block':
                    request['geometry_inspection']['unknown'] = True
                elif failure == 'report_tamper':
                    target.write_text('{}', encoding='utf-8')
                path.write_text(json.dumps(request), encoding='utf-8')
                with patch.object(solidworks_worker.subprocess, 'Popen', side_effect=AssertionError('native launched')) as launch:
                    with self.assertRaises((ValueError, AssertionError)):
                        solidworks_worker.view_step(path)
                launch.assert_not_called()
                receipt = json.loads(Path(request['receipt_path']).read_text())
                self.assertFalse(receipt['native_child_started'])
                self.assertTrue(receipt['source_guards_released'])
                self.assertIsNotNone(receipt['primary'])

    def test_actual_rpc_disconnect_precedes_original_child_terminal_zero_or_seven(self):
        for mode in ('delayed_exit0', 'delayed_exit7', 'delayed_exit_slow'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path, request = self.request(Path(directory))
                if mode == 'delayed_exit7':
                    with self.assertRaisesRegex(RuntimeError, 'returned 7'):
                        inert_worker_entry(str(path), mode)
                else:
                    inert_worker_entry(str(path), mode)
                receipt = json.loads(Path(request['receipt_path']).read_text(encoding='utf-8'))
                self.assertEqual(receipt['status'], 'failed' if mode == 'delayed_exit7' else 'success')
                self.assertEqual(receipt['native_returncode'], 7 if mode == 'delayed_exit7' else 0)
                self.assertTrue(receipt['native_exit_confirmed'])
                self.assertTrue(receipt['source_guards_released'])
                self.assertTrue(receipt['application']['template_preferences_restored'])
                self.assertTrue(receipt['application']['owned_documents_closed'])
                self.assertEqual(receipt['application']['cleanup_errors'], [])
                self.assertEqual(receipt['application']['closing_rpc_observations'][0]['hresult'], -2147417848)
                self.assertEqual(receipt['application']['owned_native_handle_exit']['pid'], receipt['native_pid'])
                for name in ('source_step', 'controlled_step', 'template_record', 'assembly_template_record'):
                    with Path(request[name]['path']).open('ab') as stream:
                        stream.write(b'')  # Only after actual same-handle exit and guard release.

    def test_actual_original_child_application_exit_after_early_restore_and_nonzero_failure(self):
        for mode in ('application_exit', 'application_exit7'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path, request = self.request(Path(directory))
                if mode == 'application_exit7':
                    with self.assertRaisesRegex(RuntimeError, 'returned7|returned 7'):
                        inert_worker_entry(str(path), mode)
                else:
                    inert_worker_entry(str(path), mode)
                receipt = json.loads(Path(request['receipt_path']).read_text(encoding='utf-8'))
                self.assertTrue(receipt['native_exit_confirmed'])
                self.assertTrue(receipt['source_guards_released'])
                self.assertTrue(receipt['document_close_observed'])
                self.assertTrue(receipt['application']['template_preferences_restored'])
                self.assertEqual(receipt['application']['original_import_preferences'],
                    {'8':'original-template', '9':'original-assembly-template','111':False,'691':False})
                self.assertEqual(receipt['native_returncode'], 7 if mode.endswith('7') else 0)
                self.assertEqual(receipt['status'], 'failed' if mode.endswith('7') else 'success')
                self.assertEqual(receipt['application']['cleanup_errors'], [])
                self.assertIn('original owned native handle', receipt['application']['application_exit_semantics'])

    def test_actual_inert_child_exit_guards_primary_and_wrong_com_identity(self):
        for mode in ('success', 'primary_restore', 'wrong_pid'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='view 中文 ') as directory:
                path, request = self.request(Path(directory))
                if mode == 'success':
                    inert_worker_entry(str(path), mode)
                else:
                    with self.assertRaisesRegex((ValueError, RuntimeError), 'ORIGINAL_VIEW_PRIMARY|explicitly launched'):
                        inert_worker_entry(str(path), mode)
                report = json.loads(Path(request['receipt_path']).read_text(encoding='utf-8'))
                self.assertEqual(report['request_record'], file_record(path, 'required_evidence'))
                self.assertTrue(report['native_exit_confirmed'])
                self.assertEqual(report['native_returncode'], 0)
                self.assertTrue(report['source_guards_released'])
                self.assertEqual(report['status'], 'success' if mode == 'success' else 'failed')
                if mode == 'success':
                    self.assertTrue(report['document_close_observed'])
                    self.assertTrue(report['application']['template_preferences_restored'])
                    self.assertEqual(report['application']['preference_restoration'], {'8':True,'9':True,'111':True,'691':True})
                elif mode == 'primary_restore':
                    self.assertIn('ORIGINAL_VIEW_PRIMARY', report['primary'])
                    self.assertTrue(any('RESTORE_SECONDARY' in row for row in report['application']['cleanup_errors']))
                # Ordinary write succeeds only after the original child exited.
                for name in ('source_step', 'controlled_step', 'template_record', 'assembly_template_record'):
                    Path(request[name]['path']).write_bytes(b'GUARDS_RELEASED_AFTER_EXIT')
                for record in request['source_template_records'].values():
                    Path(record['path']).write_bytes(b'TEMPLATE_SOURCE_GUARD_RELEASED')
                self.assertEqual((report['refine_calls_requested'], report['fly_calls_requested'], report['save_calls_requested']), (0, 0, 0))

    def test_invalid_receipt_path_and_early_tamper_fail_without_native_launch(self):
        for mode in ('outside_receipt', 'tamper', 'tool_role', 'assembly_tamper', 'source_assembly_tamper', 'assembly_alias', 'legacy_schema'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, request = self.request(root)
                outside = root/'untouched.json'
                outside.write_bytes(b'USER_ASSET')
                if mode == 'outside_receipt':
                    request['receipt_path'] = str(outside)
                elif mode == 'tamper':
                    Path(request['controlled_step']['path']).write_bytes(b'changed')
                elif mode == 'tool_role':
                    request['executable_record'].pop('retention_role')
                elif mode == 'assembly_tamper':
                    Path(request['assembly_template_record']['path']).write_bytes(b'changed assembly copy')
                elif mode == 'source_assembly_tamper':
                    Path(request['source_template_records']['assembly']['path']).write_bytes(b'changed assembly source')
                elif mode == 'assembly_alias':
                    request['source_template_records']['assembly'] = dict(request['assembly_template_record'])
                else:
                    request['schema_version'] = 1
                path.write_text(json.dumps(request), encoding='utf-8')
                with patch.object(solidworks_worker.subprocess, 'Popen', side_effect=AssertionError('native launched')) as launch:
                    with self.assertRaises((ValueError, AssertionError)):
                        solidworks_worker.view_step(path)
                launch.assert_not_called()
                self.assertEqual(outside.read_bytes(), b'USER_ASSET')
                if mode not in {'outside_receipt', 'legacy_schema'}:
                    report = json.loads(Path(request['receipt_path']).read_text())
                    self.assertFalse(report['native_child_started'])
                    self.assertIsNone(report['native_pid'])
                    self.assertIsNotNone(report['primary'])

    def test_real_sole_owner_action_copies_and_waits_inert_document_without_commercial_software(self):
        for checks in (None, dict(schema_version=1, kind='selected_solid_geometry_v1', selected_step_members=['member_00008'])):
            with tempfile.TemporaryDirectory(prefix='open owner 中文 ') as directory:
                root = Path(directory)
                tool, template, assembly = root/'SLDWORKS.exe', root/'clean.prtdot', root/'clean.asmdot'
                tool.write_bytes(b'INERT_NOT_EXECUTABLE')
                template.write_bytes(b'INERT_NOT_TEMPLATE')
                assembly.write_bytes(b'INERT_NOT_ASSEMBLY_TEMPLATE')
                context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                    powershell_executable=Path(shutil.which('pwsh')), tools={'solidworks':tool},
                    host_state_path=root/'private-host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
                authority = root/'budget.json'
                authority.write_text('{"bytes":10485760}', encoding='utf-8')
                base = dict(descriptor=dict(project='instrument_assembly', mode='inert_view', software=[]),
                    payload={'scope':'INERT_SOFTWARE_ONLY'}, committed_new_bytes=10485760,
                    commitment_inputs=[file_record(authority, 'required_evidence')],
                    retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert view transport'),
                    completion_api=lambda:type('NoParticle', (), {'recoverable_batch_logs':staticmethod(lambda _:set())}))

                def publish(session):
                    step = session.declare_file(session.result_dir/'assembly.step', 'solver_native_binary')
                    step.parent.mkdir(parents=True, exist_ok=True)
                    step.write_bytes(b'INERT_PROTOCOL_DATA_NOT_A_VALID_STEP')
                    data = {'step':file_record(step, 'solver_native_binary')}
                    outputs = [str(step)]
                    if checks is not None:
                        report = session.declare_file(session.result_dir/'cad_export_report.json', 'required_evidence')
                        report.write_text(json.dumps(dict(schema_version=1, role='owned_assembly_step_export',
                            step_record=data['step'], projection=dict(schema_version=1, role='assembly_step_projection',
                                representation='physical_solids', length_unit='mm',
                                exported_members=[dict(step_name='member_00008', member_id='segment2')]))), encoding='utf-8')
                        data['report'] = file_record(report, 'required_evidence')
                        outputs.append(str(report))
                    return dict(status='success', summary={'inert':True}, output_paths=outputs, required_output_paths=outputs,
                        retention_preserve_paths=[], manifest_extra_fields={'products':{'cad_geometry':dict(schema_version=1,
                            kind='cad_geometry', status='complete', metadata={'inert':True},
                            data=data)}})

                limits = dict(wall_clock_seconds=60, transient_run_directory_bytes=10485760,
                    process_tree_working_set_bytes=1073741824, minimum_system_available_memory_bytes=1048576,
                    compact_final_retained_bytes=10485760, automatic_retry_count=0)
                materializer = partial(materialize_payloads, limits=limits)
                original_run_process = RunSession.run_process
                code = inspect.getsource(inert_worker_entry)+'\nimport sys;inert_worker_entry(sys.argv[1],"success")'

                def real_inert_view(session, operation_id, **options):
                    if operation_id == 'view_model':
                        session.declare_file(session.artifact_run_dir/'inert_child_exit', 'required_evidence')
                        self.assertEqual(options['arguments'][:5], ['-I', '-X', 'utf8', '-m', 'msplatform.applications.solidworks_worker'])
                        options['arguments'] = ['-I', '-X', 'utf8', '-c', code, options['arguments'][-1]]
                    return original_run_process(session, operation_id, **options)

                environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                    MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
                policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
                with patch.dict(os.environ, environment), patch('msplatform.execution.capacity_admission._capacity_policy', return_value=policy):
                    producer = owner.run_managed_stage(context, run_id='20261104_000001__test__cad__inert-view-source',
                        expected_operation_ids=(), operation_dependencies={}, action=publish,
                        action_record=file_record(Path(__file__), 'required_evidence'), **base)
                    ref = {'manifest':producer['manifest'], 'product_id':'cad_geometry'}
                    source = open_artifact(ref, expected_kind='cad_geometry')
                    action = partial(execute_open_model, model_reference=source, application='solidworks', limits=limits,
                        materialize_payloads=materializer, materializer_record=file_record(Path(inspect.getsourcefile(materialize_payloads)), 'required_evidence'),
                        application_settings=dict(com_class='SldWorks.Application.30', part_template=str(template), assembly_template=str(assembly), lifecycle='document_close'), checks=checks)
                    with patch.object(RunSession, 'run_process', real_inert_view):
                        result = owner.run_managed_stage(context, run_id='20261104_000002__test__cad__inert-view-consumer',
                            expected_operation_ids=('materialize_view', 'view_model'), operation_dependencies={'view_model':('materialize_view',)},
                            action=action, action_record=file_record(Path(inspect.getsourcefile(execute_open_model)), 'required_evidence'),
                            source_references=[{'manifest_record':producer['manifest']}], **base)
                self.assertEqual((result['status'], result['stage'], result['writers_confirmed']), ('success', 'complete', True))
                run = Path(result['run_directory'])
                report = json.loads((run/'results/model_view_receipt.json').read_text(encoding='utf-8'))
                self.assertTrue(report['native_exit_confirmed'])
                self.assertTrue(report['document_close_observed'])
                self.assertEqual(source.data_path('step').read_bytes(), b'INERT_PROTOCOL_DATA_NOT_A_VALID_STEP')
                self.assertIn('INERT_GUARD_BLOCKED=source_step', (run/'logs/operation_0002.stdout.log').read_text())
                for key in ('template_record', 'assembly_template_record', 'source_part_template', 'source_assembly_template'):
                    self.assertIn('INERT_GUARD_BLOCKED='+key, (run/'logs/operation_0002.stdout.log').read_text())
                payload_request = json.loads((run/'inputs/payload_materialize_view/request.json').read_text(encoding='utf-8'))
                self.assertEqual(len(payload_request['copies']), 3)
                self.assertEqual([Path(row['destination']).suffix for row in payload_request['copies']], ['.step','.prtdot','.asmdot'])
                completion = json.loads((run/'results/execution_completion.json').read_text(encoding='utf-8'))
                self.assertEqual(len(completion['writer_completion']['operations']), 2)
                self.assertEqual(len(completion['writer_completion']['resource_releases']), 2)
                if checks is not None:
                    self.assertEqual(report['application']['selected_geometry']['status'], 'incomplete')
                    self.assertIn('INERT_GUARD_BLOCKED=inspection_report', (run/'logs/operation_0002.stdout.log').read_text())
                print('INERT_VIEW_OWNER_PROOF='+json.dumps(dict(status=result['status'], stage=result['stage'],
                    writers_confirmed=result['writers_confirmed'], viewer_receipt=report,
                    writer_completion=completion['writer_completion']), ensure_ascii=True), flush=True)

if __name__ == '__main__':
    unittest.main()
