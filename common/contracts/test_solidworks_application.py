"""Pure COM doubles for explicit SolidWorks viewing; no native application starts."""

import builtins
import importlib.util
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.applications import solidworks as sw


class Document:
    def __init__(self, title="owned", kind=1):
        self.title, self.kind = title, kind

    def GetTitle(self):
        return self.title

    def GetType(self):
        return self.kind

    def IsOpenedReadOnly(self):
        return False

    def GetBodies2(self, *_):
        return [SimpleNamespace(Name="solid", GetBodyBox=lambda: [0, 0, 0, 1, 2, 3])]

    def GetComponents(self, *_):
        return [
            SimpleNamespace(
                Name2="part",
                Transform2=SimpleNamespace(ArrayData=list(range(16))),
                GetBox=lambda *_: [0, 0, 0, 1, 2, 3],
            )
        ]


class Application:
    def __init__(self):
        self.documents = []
        self.preferences = {8: "old-template", 9: "old-assembly-template", 111: False, 691: False}
        self.closed = []
        self.exited = False
        self.revision = "30.5"
        self.error = 0
        self.import_failure = None
        self.restore_failure = False
        self.existing = None

    def GetDocuments(self):
        return tuple(self.documents)

    def GetDocumentCount(self):
        return len(self.documents)

    def GetProcessID(self):
        return 1234

    def RevisionNumber(self):
        return self.revision

    def GetOpenDocumentByName(self, _):
        return self.existing

    def GetUserPreferenceStringValue(self, key):
        return self.preferences[key]

    def GetUserPreferenceToggle(self, key):
        return self.preferences[key]

    def SetUserPreferenceStringValue(self, key, value):
        if self.restore_failure and value == "old-template":
            raise RuntimeError("restore failed")
        self.preferences[key] = value
        return True

    def SetUserPreferenceToggle(self, key, value):
        self.preferences[key] = value

    def LoadFile4(self, path, args, data, errors):
        self.load_arguments = (path, args, data)
        self.preferences_at_import = dict(self.preferences)
        if self.import_failure:
            raise self.import_failure
        self.document = Document()
        self.documents.append(self.document)
        errors.value = self.error
        return self.document

    def CloseDoc(self, title):
        self.closed.append(title)
        self.documents[:] = [d for d in self.documents if d.title != title]

    def ExitApp(self):
        self.exited = True


class SolidWorksApplicationTests(unittest.TestCase):
    def test_explicit_cold_viewer_requests_visible_creation_and_activates_only_original_document(self):
        calls = []
        self.app.DocumentVisible = lambda visible, kind: calls.append((visible, kind))
        original = self.app.LoadFile4
        def load(*args):
            document = original(*args)
            document.kind = 2
            document.Visible = True
            return document
        self.app.LoadFile4 = load
        self.app.ActiveDoc = None
        def activate(title, use_preferences, option, errors):
            self.assertEqual((title, use_preferences, option), ('owned', False, 1))
            self.app.ActiveDoc = self.app.document
            errors.value = 2
            return self.app.document
        self.app.ActivateDoc3 = activate
        with self.session(session_mode='owned_child', owned_process_id=1234, display_owned_document=True) as session:
            self.assertEqual(calls, [(True, 2)])
            self.assertTrue(session.receipt['assembly_creation_visibility_requested'])
            self.assertTrue(session.receipt['display_observation']['active_identity_matches'])
            self.assertEqual(session.receipt['display_observation']['activation_errors'], 2)
            self.assertFalse(session.receipt['display_observation']['rebuild_requested'])
            self.assertTrue(session.receipt['template_preferences_restored'])

    def test_cold_viewer_rejects_ambiguous_foreign_or_hidden_document_without_adoption(self):
        for failure in ('duplicate', 'foreign', 'hidden', 'activation_error', 'existing'):
            with self.subTest(failure=failure):
                self.app = Application()
                self.app.DocumentVisible = lambda *_: None
                self.app.ActiveDoc = None
                original = self.app.LoadFile4
                def load(*args):
                    document = original(*args)
                    document.kind = 2
                    document.Visible = failure != 'hidden'
                    if failure == 'duplicate':
                        self.app.documents.append(Document('owned', 2))
                    return document
                self.app.LoadFile4 = load
                def activate(_title, _preferences, _option, errors):
                    errors.value = 1 if failure == 'activation_error' else 0
                    if failure == 'foreign':
                        user = Document('USER_FOREIGN', 2)
                        self.app.documents.append(user)
                        return user
                    self.app.ActiveDoc = self.app.document
                    return self.app.document
                self.app.ActivateDoc3 = activate
                if failure == 'existing':
                    self.app.documents.append(Document('USER_PREEXISTING'))
                with self.assertRaises(sw.SolidWorksApplicationError):
                    with self.session(session_mode='owned_child', owned_process_id=1234, display_owned_document=True):
                        self.fail('unsupported display accepted')
                self.assertNotIn('USER_FOREIGN', self.app.closed)
                self.assertNotIn('USER_PREEXISTING', self.app.closed)
                if failure == 'duplicate':
                    self.assertEqual(self.app.closed, [])
                    self.assertFalse(self.app.exited)

    def test_rpc_closing_wait_never_accepts_other_errors_unknown_handles_or_unrestored_preferences(self):
        for failure in ('other_hresult', 'unrestored', 'wrong_pid', 'unknown_wait'):
            with self.subTest(failure=failure):
                calls = []
                def observe(*, wait=False):
                    calls.append(wait)
                    return dict(pid=9999 if failure == 'wrong_pid' else 1234,
                                returncode=None if failure == 'unknown_wait' or not wait else 0)
                receipt = dict(session_mode='owned_child', native_pid=1234,
                               template_preferences_restored=failure != 'unrestored')
                session = sw.StepSession(object(), object(), receipt, observe)
                error = RuntimeError(-2147417848 if failure != 'other_hresult' else -123, 'not generalized')
                self.assertIsNone(session._observe_rpc_closing_exit(error))
                if failure in {'other_hresult', 'unrestored', 'wrong_pid'}:
                    self.assertNotIn(True, calls)
                self.assertNotIn('owned_native_handle_exit', receipt)

    def test_post_close_dynamic_count_unavailability_waits_actual_original_child_exit(self):
        for code in (0, 7):
            with self.subTest(code=code), TemporaryDirectory() as directory:
                signal = Path(directory)/'exit_signal'
                command = ('import pathlib,sys,time;p=pathlib.Path(sys.argv[1]);'
                    '\nwhile not p.exists():time.sleep(.01)'
                    '\ntime.sleep(.15);sys.exit(int(sys.argv[2]))')
                child = subprocess.Popen([sys.executable, '-I', '-c', command, str(signal), str(code)],
                    cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                waits = []
                class ClosingApplication(Application):
                    closing = False
                    count_reads = 0
                    @property
                    def GetDocumentCount(self):
                        if self.closing:
                            self.count_reads += 1
                            if self.count_reads == 3:
                                if child.poll() is not None:
                                    raise AssertionError('original child exited before getter race')
                                signal.write_text('natural original shutdown', encoding='utf8')
                                raise AttributeError('SldWorks.Application.30.GetDocumentCount') from RuntimeError('lazy lookup unavailable')
                        return lambda: len(self.documents)
                    def GetProcessID(self):
                        return child.pid
                self.app = ClosingApplication()
                def observe(*, wait=False):
                    waits.append(wait)
                    return dict(pid=child.pid, returncode=child.wait(timeout=5) if wait else child.poll())
                try:
                    with self.session(session_mode='owned_child', owned_process_id=child.pid,
                                      owned_process_exit_observer=observe) as session:
                        self.app.documents.clear()
                        self.app.closing = True
                    self.assertIn(True, waits)
                    self.assertEqual(child.poll(), code)
                    self.assertEqual(session.receipt['owned_native_handle_exit'], dict(pid=child.pid, returncode=code))
                    self.assertTrue(session.receipt['application_exited'])
                    self.assertTrue(session.receipt['template_preferences_restored'])
                    self.assertEqual(session.receipt['cleanup_errors'], [])
                    self.assertFalse(self.app.exited)  # No ExitApp call to unavailable COM.
                    diagnostic = session.receipt['post_close_count_observation']
                    self.assertEqual(diagnostic['error']['type'], 'AttributeError')
                    self.assertEqual(diagnostic['error']['args'], ['SldWorks.Application.30.GetDocumentCount'])
                    self.assertIsNone(diagnostic['error']['hresult'])
                    self.assertEqual(diagnostic['error']['chain'][0]['type'], 'RuntimeError')
                    self.assertEqual(diagnostic['native_exit'], dict(pid=child.pid, returncode=code))
                finally:
                    signal.touch()
                    child.wait(timeout=5)

    def test_post_close_count_candidate_rejects_other_errors_or_unconfirmed_preconditions(self):
        for failure in ('other_attribute', 'other_type', 'not_owned', 'unrestored', 'not_closed',
                        'foreign_remaining', 'prior_cleanup', 'wrong_pid', 'unknown_wait'):
            with self.subTest(failure=failure):
                receipt = dict(session_mode='owned_child', native_pid=1234,
                    template_preferences_restored=True, owned_documents_closed=True, cleanup_errors=[])
                if failure == 'not_owned':
                    receipt['session_mode'] = 'attach'
                if failure == 'unrestored':
                    receipt['template_preferences_restored'] = False
                if failure == 'not_closed':
                    receipt['owned_documents_closed'] = False
                if failure == 'prior_cleanup':
                    receipt['cleanup_errors'] = ['original cleanup failure']
                calls = []
                def observe(*, wait=False):
                    calls.append(wait)
                    return dict(pid=9999 if failure == 'wrong_pid' else 1234, returncode=None)
                session = sw.StepSession(object(), object(), receipt, observe)
                error = (RuntimeError('SldWorks.Application.30.GetDocumentCount') if failure == 'other_type'
                    else AttributeError('SldWorks.Application.30.OtherProperty' if failure == 'other_attribute'
                                        else 'SldWorks.Application.30.GetDocumentCount'))
                self.assertIsNone(session._observe_post_close_count_exit(error,
                    [object()] if failure == 'foreign_remaining' else []))
                if failure != 'unknown_wait':
                    self.assertNotIn(True, calls)
                self.assertNotIn('owned_native_handle_exit', receipt)

    def test_confirmed_restoration_is_not_repeated_after_yield(self):
        with self.session() as session:
            self.assertTrue(session.receipt['template_preferences_restored'])
            self.app.GetUserPreferenceStringValue = lambda *_: (_ for _ in ()).throw(RuntimeError('COM gone'))
            self.app.GetUserPreferenceToggle = self.app.GetUserPreferenceStringValue
        self.assertTrue(session.receipt['template_preferences_restored'])
        self.assertEqual(session.receipt['cleanup_errors'], [])

    def test_known_original_handle_exit_only_skips_dead_com_after_preferences_restored(self):
        for code in (0, 7):
            with self.subTest(code=code):
                self.app = Application()
                observed = dict(pid=1234, returncode=None)
                with self.session(session_mode='owned_child', owned_process_id=1234,
                                  owned_process_exit_observer=lambda: dict(observed)) as session:
                    self.assertTrue(session.receipt['template_preferences_restored'])
                    observed['returncode'] = code
                    self.app.GetDocuments = lambda: (_ for _ in ()).throw(RuntimeError('dead COM'))
                    self.assertFalse(session.document_is_open())
                self.assertTrue(session.receipt['owned_documents_closed'])
                self.assertTrue(session.receipt['application_exited'])
                self.assertEqual(session.receipt['owned_native_handle_exit'], dict(pid=1234, returncode=code))
                self.assertFalse(self.app.exited)  # No ExitApp call fabricated.
        for observation, restored in ((dict(pid=1234, returncode=None), True),
                (dict(pid=1234, returncode=0), False), (dict(pid=9999, returncode=0), True),
                (dict(pid=1234, returncode=True), True), (None, True)):
            receipt = dict(session_mode='owned_child', native_pid=1234, template_preferences_restored=restored)
            app = SimpleNamespace(GetDocumentCount=lambda: (_ for _ in ()).throw(RuntimeError('unconfirmed COM')))
            session = sw.StepSession(app, object(), receipt, lambda: observation)
            with self.subTest(observation=observation, restored=restored), self.assertRaises((RuntimeError, sw.SolidWorksApplicationError)):
                session.document_is_open()

    def test_import_preferences_are_restored_and_exact_snapshot_exposed_before_yield(self):
        original = dict(self.app.preferences)
        with self.session() as session:
            self.assertTrue(session.receipt['template_preferences_restored'])
            self.assertEqual(self.app.preferences, original)
            self.assertEqual(session.receipt['original_import_preferences'], {str(k):v for k,v in original.items()})
            self.assertIs(type(session.receipt['original_import_preferences']['111']), bool)
            self.assertIs(type(session.receipt['original_import_preferences']['8']), str)

    def test_selected_step_names_are_report_literals_with_exact_vendor_suffixes(self):
        names = ('multipole.segment_0001.rod_0002.rf_group_2','oatof.accelerator.ring_0001','member_00008')
        report = dict(schema_version=1,role='owned_assembly_step_export',projection=dict(schema_version=1,
            role='assembly_step_projection',representation='physical_solids',length_unit='mm',
            exported_members=[dict(step_name=name,member_id='unchanged-source-'+str(i)) for i,name in enumerate(names)]))
        checks = dict(schema_version=1,kind='selected_solid_geometry_v1',selected_step_members=list(names))
        self.assertEqual(set(sw.validate_geometry_checks(checks,report)),set(names))
        for name in names:
            for suffix in ('','.step','-1','.step-2'):
                self.assertEqual(sw._imported_step_name('assembly.step-1/'+name+suffix,names),name)
            self.assertIsNone(sw._imported_step_name(name+'foreign-1',names))
        for leaf, expected in (('part-1',('part','part-1')),('part.step-1',('part','part.step'))):
            with self.subTest(leaf=leaf),self.assertRaisesRegex(ValueError,'ambiguous'):
                sw._imported_step_name(leaf,expected)
        complete_report = dict(report,projection=dict(report['projection'],exported_members=[
            dict(step_name='part',member_id='selected-physical-part'),
            dict(step_name='part-1',member_id='unselected-physical-part')]))
        subset = dict(checks,selected_step_members=['part'])
        document = SimpleNamespace(GetComponents=lambda *_:[SimpleNamespace(Name2='assembly/part-1')])
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            sw._inspect_selected_geometry(document,complete_report,subset)
        with self.assertRaisesRegex(ValueError,'missing or ambiguous'):
            sw.validate_geometry_checks(dict(checks,selected_step_members=['foreign']),report)
        report['projection']['exported_members'].append(dict(step_name=names[0],member_id='other'))
        with self.assertRaisesRegex(ValueError,'missing or ambiguous'):
            sw.validate_geometry_checks(checks,report)

    def test_selected_native_property_dispatch_getters_do_not_invoke_default_members(self):
        from types import SimpleNamespace
        class DispatchValue:
            _oleobj_ = object()
            def __call__(self):
                raise AssertionError('COM default member must not be invoked')
        checks = dict(schema_version=1, kind='selected_solid_geometry_v1', selected_step_members=['member_00008'])
        report = dict(schema_version=1, role='owned_assembly_step_export', projection=dict(
            schema_version=1, role='assembly_step_projection', representation='physical_solids', length_unit='mm',
            exported_members=[dict(step_name='member_00008', member_id='segment2')]))
        pc, _ = sw._com_modules()
        pc.VT_VARIANT = 8
        for style in ('surface_dispatch', 'all_readonly_properties'):
            with self.subTest(style=style):
                surface = DispatchValue()
                surface.IsCylinder = True
                surface.CylinderParams = [0, 0, .02, 0, 0, 1, .002]
                curve = DispatchValue()
                curve.IsCircle = True
                curve.CircleParams = [0, 0, .02, 0, 0, 1, .002]
                edge = SimpleNamespace(GetCurve=curve)
                face = SimpleNamespace(GetSurface=surface, FaceInSurfaceSense=True,
                    GetUVBounds=[0, 6.28, 0, .0196], GetEdges=[edge])
                body = SimpleNamespace(GetFaces=[face],
                    GetMassProperties=lambda *_: [0, 0, .0298, 1e-6, 2e-6, 0, 0, 0, 0, 0, 0, 0])
                if style == 'surface_dispatch':
                    body.GetFaces = lambda: [face]
                def bodies(_kind, info):
                    info.value = [0]
                    return [body]
                component = SimpleNamespace(Name2='assembly.step-1/member_00008.step-1',
                    GetBodies3=bodies, Transform2=SimpleNamespace(ArrayData=list(range(16))))
                result = sw._inspect_selected_geometry(SimpleNamespace(GetComponents=lambda *_: [component]), report, checks)
                self.assertEqual(result['status'], 'observations_only')
                row = result['members'][0]['bodies'][0]['faces'][0]
                self.assertTrue(row['is_cylinder'])
                self.assertTrue(row['opposite_surface_normal'])
                self.assertEqual(row['cylinder']['radius_mm'], 2)
                self.assertEqual(row['circular_edges'][0]['center_mm'], [0, 0, 20])
                self.assertNotIn('error', row)

    def test_selected_native_getters_preserve_units_errors_caps_and_report_names(self):
        from types import SimpleNamespace
        checks = dict(schema_version=1, kind='selected_solid_geometry_v1', selected_step_members=['member_00008'])
        report = dict(schema_version=1, role='owned_assembly_step_export', projection=dict(
            schema_version=1, role='assembly_step_projection', representation='physical_solids', length_unit='mm',
            exported_members=[dict(step_name='member_00008', member_id='segment2')]))
        pc, _ = sw._com_modules()
        pc.VT_VARIANT = 8
        curve = SimpleNamespace(IsCircle=lambda: True, CircleParams=[0, 0, .02, 0, 0, 1, .002])
        face = SimpleNamespace(GetSurface=lambda: SimpleNamespace(IsCylinder=lambda: True,
            CylinderParams=[0, 0, .02, 0, 0, 1, .002]), FaceInSurfaceSense=lambda: True,
            GetUVBounds=lambda: [0, 6.28, 0, .0196], GetEdges=lambda: [SimpleNamespace(GetCurve=lambda: curve)])
        body = SimpleNamespace(GetMassProperties=lambda density: [0, 0, .0298, 1e-6, 2e-6, 0, 0, 0, 0, 0, 0, 0],
            GetFaces=lambda: [face])
        def bodies(_kind, info):
            self.assertEqual(_kind, 0)
            info.value = [0]
            return [body]
        component = SimpleNamespace(Name2='assembly.step-1/member_00008.step-1', GetBodies3=bodies,
            Transform2=SimpleNamespace(ArrayData=list(range(16))))
        document = SimpleNamespace(GetComponents=lambda *_: [component])
        result = sw._inspect_selected_geometry(document, report, checks)
        observed = result['members'][0]['bodies'][0]
        self.assertEqual(observed['mass_properties']['volume_mm3'], 1000)
        self.assertEqual(observed['mass_properties']['center_of_mass_local_mm'][2], 29.8)
        self.assertEqual(observed['faces'][0]['cylinder']['radius_mm'], 2)
        self.assertTrue(observed['faces'][0]['opposite_surface_normal'])
        self.assertEqual(observed['faces'][0]['circular_edges'][0]['center_mm'], [0, 0, 20])
        self.assertEqual(result['qualification'], 'not_granted')
        with patch.object(component, 'GetBodies3', new=lambda *_: [body]*129):
            self.assertEqual(sw._inspect_selected_geometry(document, report, checks)['status'], 'incomplete')
        with patch.object(face, 'GetSurface', new=lambda: (_ for _ in ()).throw(RuntimeError('GETTER_UNAVAILABLE'))):
            partial = sw._inspect_selected_geometry(document, report, checks)
            self.assertEqual(partial['status'], 'incomplete')
            self.assertIn('GETTER_UNAVAILABLE', partial['members'][0]['bodies'][0]['faces'][0]['error'])
        for bad in (dict(checks, extra=True), dict(checks, schema_version=True),
                    dict(checks, selected_step_members=['member_00008']*2),
                    dict(checks, selected_step_members=['member_00099']), dict(checks, selected_step_members=[])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sw.validate_geometry_checks(bad, report)

    def test_selected_checks_use_original_unsaved_root_without_document_lookup(self):
        checks = dict(schema_version=1, kind='selected_solid_geometry_v1', selected_step_members=['member_00008'])
        report = dict(schema_version=1, role='owned_assembly_step_export', projection=dict(
            schema_version=1, role='assembly_step_projection', representation='physical_solids',
            length_unit='mm', exported_members=[dict(step_name='member_00008', member_id='actual-source-segment2')]))
        with self.session() as session:
            owned = session._document
            owned.kind = 2
            owned.GetPathName = lambda: ''
            owned.GetComponents = lambda *_: []
            self.app.documents = [Document('assembly') for _ in range(73)]+[owned]
            with patch.object(self.app, 'GetOpenDocumentByName', side_effect=AssertionError('second lookup')):
                result = session.inspect(checks=checks, export_report=report)
            self.assertEqual(result['document_path_observed'], '')
            self.assertEqual(result['selected_geometry']['status'], 'incomplete')
            self.assertEqual(result['selected_geometry']['qualification'], 'not_granted')
            self.assertEqual(len(self.app.documents), 74)

    def test_interconnect_argument_and_template_diagnostics_bind_actual_inputs(self):
        from msplatform.execution.manifest_records import file_record

        with self.session(session_mode="owned_child", owned_process_id=1234) as session:
            receipt = session.receipt
            self.assertEqual(self.app.load_arguments[1], "")
            self.assertEqual(receipt["load_argument_string"], "")
            self.assertEqual(receipt["import_preference_readback"], {"111": True, "691": True})
            self.assertEqual(receipt["import_process_id"], 1234)
            self.assertTrue(receipt["native_pid_matches_before_import"])
            for name, key, path in (("part", "8", self.paths[2]), ("assembly", "9", self.paths[3])):
                self.assertEqual(receipt["template_records"][name], file_record(path, "required_evidence"))
                self.assertEqual(receipt["template_metadata"][name]["modified_time_ns"], path.stat().st_mtime_ns)
                self.assertEqual(receipt["template_preference_binding"][key], dict(
                    configured=str(path.resolve()), setter_accepted=True, readback=str(path.resolve())))
        self.assertTrue(receipt["template_preferences_restored"])

    def test_changed_com_pid_before_import_is_rejected_without_load(self):
        process_ids = iter((1234, 9876))
        with patch.object(self.app, "GetProcessID", new=lambda: next(process_ids)):
            with self.assertRaisesRegex(sw.SolidWorksApplicationError, "process changed") as caught:
                with self.session(session_mode="owned_child", owned_process_id=1234):
                    self.fail("changed process accepted")
        self.assertFalse(hasattr(self.app, "load_arguments"))
        self.assertFalse(caught.exception.solidworks_receipt["native_pid_matches_before_import"])
        self.assertFalse(caught.exception.solidworks_receipt["template_preferences_restored"])
        self.assertFalse(self.app.exited)
        self.assertEqual(caught.exception.solidworks_receipt["application_retained_reason"],
                         "native_pid_mismatch_before_import")

    def test_explicit_template_pair_is_bound_and_individually_restored(self):
        original = dict(self.app.preferences)
        with self.session() as session:
            self.assertEqual(self.app.preferences_at_import[8], str(self.paths[2].resolve()))
            self.assertEqual(self.app.preferences_at_import[9], str(self.paths[3].resolve()))
            self.assertTrue(self.app.preferences_at_import[111])
            self.assertTrue(self.app.preferences_at_import[691])
        self.assertEqual(self.app.preferences, original)
        self.assertEqual(session.receipt['preference_restoration'], {'8':True,'9':True,'111':True,'691':True})

    def test_assembly_binding_setter_or_readback_failure_prevents_import_and_restores_pair(self):
        for failure in ('setter_false', 'ignored_setter'):
            with self.subTest(failure=failure):
                self.app = Application()
                original = dict(self.app.preferences)
                setter = self.app.SetUserPreferenceStringValue
                def set_preference(key, value):
                    if key == 9 and value != original[9]:
                        return failure == 'ignored_setter'
                    return setter(key, value)
                with patch.object(self.app, 'SetUserPreferenceStringValue', side_effect=set_preference):
                    with self.assertRaisesRegex(sw.SolidWorksApplicationError, 'template preference 9') as caught:
                        with self.session():
                            self.fail('invalid assembly preference accepted')
                self.assertFalse(hasattr(self.app, 'load_arguments'))
                self.assertEqual(self.app.preferences, original)
                self.assertTrue(caught.exception.solidworks_receipt['template_preferences_restored'])

    def test_assembly_restore_failure_keeps_primary_and_restores_other_preferences(self):
        for failure in ('raise', 'readback'):
            with self.subTest(failure=failure):
                self.app = Application()
                original = dict(self.app.preferences)
                setter = self.app.SetUserPreferenceStringValue
                def set_preference(key, value):
                    if key == 9 and value == original[9]:
                        if failure == 'raise':
                            raise RuntimeError('ASSEMBLY_RESTORE_SECONDARY')
                        self.app.preferences[9] = 'incorrect-restoration'
                        return True
                    return setter(key, value)
                self.app.import_failure = ValueError('ORIGINAL_CALLER_FAILURE')
                with patch.object(self.app, 'SetUserPreferenceStringValue', side_effect=set_preference):
                    with self.assertRaisesRegex(ValueError, 'ORIGINAL_CALLER_FAILURE') as caught:
                        with self.session():
                            self.fail('failed import unexpectedly yielded')
                receipt = caught.exception.solidworks_receipt
                self.assertEqual(receipt['preference_restoration'], {'8':True,'9':False,'111':True,'691':True})
                self.assertFalse(receipt['template_preferences_restored'])
                self.assertTrue(any('restore preference 9' in row for row in receipt['cleanup_errors']))
                self.assertTrue(caught.exception.__notes__)
                self.assertFalse(self.app.exited)

    def test_missing_assembly_template_is_not_guessed_and_initializes_no_com(self):
        self.paths[3].unlink()
        with self.assertRaisesRegex(ValueError, 'assembly template'):
            with self.session():
                self.fail('missing assembly accepted')
        self.assertEqual(self.calls, [])

    def test_owned_child_uses_single_empty_document_cleanup_and_exact_pid(self):
        with self.session(session_mode='owned_child', owned_process_id=1234) as session:
            self.assertTrue(session.document_is_open())
            self.app.documents.clear()  # User closes the imported document.
        self.assertTrue(self.app.exited)
        self.assertTrue(session.receipt['owned_documents_closed'])
        self.assertTrue(session.receipt['template_preferences_restored'])
        self.assertEqual(self.app.closed, [])
        self.assertEqual(self.calls[1], ('attach', 'SldWorks.Application.30'))

    def test_owned_child_pid_mismatch_never_changes_other_application(self):
        with self.assertRaisesRegex(sw.SolidWorksApplicationError, 'original owned child') as caught:
            with self.session(session_mode='owned_child', owned_process_id=9876):
                self.fail('Wrong COM application accepted')
        self.assertEqual(self.app.preferences, {8: 'old-template', 9: 'old-assembly-template', 111: False, 691: False})
        self.assertEqual(self.app.closed, [])
        self.assertFalse(self.app.exited)
        self.assertEqual(caught.exception.solidworks_receipt['application_retained_reason'], 'native_pid_mismatch')

    def test_owned_child_retains_concurrent_documents_and_rejects_pid_without_launch_mode(self):
        with self.session(session_mode='owned_child', owned_process_id=1234) as session:
            self.app.documents.append(Document('user-added'))
        self.assertEqual(self.app.closed, ['owned'])
        self.assertFalse(self.app.exited)
        self.assertEqual(session.receipt['application_retained_reason'], 'nonowned_documents_remain')
        for options in ({'session_mode': 'owned_child', 'owned_process_id': True}, {'owned_process_id': 1234}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                with self.session(**options):
                    self.fail('invalid owner accepted')

    def test_empty_native_document_count_does_not_query_unavailable_collection(self):
        class NativeApplication:
            count = 0

            def GetDocumentCount(self):
                return self.count

            @property
            def GetDocuments(self):
                raise AttributeError("native collection unavailable")

        app = NativeApplication()
        self.assertEqual(sw._documents(app), [])
        app.count = 1
        with self.assertRaisesRegex(AttributeError, "unavailable"):
            sw._documents(app)

    def test_dispatch_object_property_is_not_invoked_as_a_default_method(self):
        class Transform:
            _oleobj_ = object()
            ArrayData = tuple(range(16))

            def __call__(self):
                raise AssertionError("COM object property has no default method")

        component = SimpleNamespace(Name2="part", Transform2=Transform(),
            GetBox=lambda *_: [0, 0, 0, 1, 2, 3])
        document = SimpleNamespace(GetType=lambda: 2, GetComponents=lambda *_: [component])
        actual = sw._geometry(document)
        self.assertEqual(actual["components"][0]["transform_array"], list(range(16)))
        self.assertEqual(actual["components"][0]["box_m"], [0, 0, 0, 1, 2, 3])
        self.assertNotIn("unavailable", actual["components"][0])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = [root / "view.step", root / "SLDWORKS.exe", root / "clean.prtdot", root / "clean.asmdot"]
        for path in self.paths:
            path.write_bytes(b"inert fixture")
        self.app = Application()
        self.calls = []
        pc = SimpleNamespace(
            VT_BYREF=1,
            VT_I4=2,
            VT_DISPATCH=4,
            CoInitialize=lambda: self.calls.append("initialize"),
            CoUninitialize=lambda: self.calls.append("uninitialize"),
        )
        client = SimpleNamespace(
            DispatchEx=lambda name: self.start("new", name),
            GetActiveObject=lambda name: self.start("attach", name),
            VARIANT=lambda kind, value: SimpleNamespace(value=value),
        )
        self.patch = patch.object(sw, "_com_modules", return_value=(pc, client))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def start(self, mode, name):
        self.calls.append((mode, name))
        return self.app

    def session(self, **kwargs):
        return sw.open_step_session(
            self.paths[0],
            executable=self.paths[1],
            part_template=self.paths[2],
            assembly_template=self.paths[3],
            com_class="SldWorks.Application.30",
            **kwargs,
        )

    def test_module_import_never_imports_optional_com(self):
        original_import = builtins.__import__

        def reject_com(name, *args, **kwargs):
            if name.split(".")[0] in {"pythoncom", "win32com"}:
                raise AssertionError("COM imported during module import")
            return original_import(name, *args, **kwargs)

        spec = importlib.util.spec_from_file_location("lazy_solidworks_probe", sw.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch("builtins.__import__", side_effect=reject_com):
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.open_step_session))

    def test_new_import_reports_native_facts_and_restores_without_save(self):
        with self.session() as session:
            self.assertTrue(session.document_is_open())
            receipt = session.inspect()
            self.assertEqual(receipt["geometry"]["body_count"], 1)
            self.assertEqual(receipt["geometry"]["bodies"][0]["box_m"], [0, 0, 0, 1, 2, 3])
            self.assertEqual(receipt["native_pid"], 1234)
            self.assertFalse(receipt["native_is_opened_read_only"])
            self.assertIsNone(receipt["load_warnings"])
        self.assertEqual(self.app.preferences, {8: "old-template", 9: "old-assembly-template", 111: False, 691: False})
        self.assertEqual(self.app.closed, ["owned"])
        self.assertTrue(self.app.exited)
        self.assertTrue(receipt["template_preferences_restored"])
        self.assertEqual(self.calls[-1], "uninitialize")

    def test_attach_retains_user_documents_and_app(self):
        user = Document("user")
        self.app.documents.append(user)
        with self.session(session_mode="attach") as session:
            self.app.document.kind = 2
            self.assertEqual(session.inspect()["geometry"]["component_count"], 1)
        self.assertEqual(self.app.documents, [user])
        self.assertFalse(self.app.exited)
        self.assertEqual(self.calls[1], ("attach", "SldWorks.Application.30"))

    def test_concurrent_user_document_is_not_owned(self):
        with self.session() as session:
            self.app.documents.append(Document("new-user"))
        self.assertEqual(self.app.closed, ["owned"])
        self.assertFalse(self.app.exited)
        self.assertEqual(session.receipt["application_retained_reason"], "nonowned_documents_remain")

    def test_load_error_closes_only_returned_document(self):
        self.app.error = 7
        with self.assertRaises(sw.SolidWorksApplicationError) as caught:
            with self.session():
                self.fail("must reject")
        self.assertEqual(caught.exception.solidworks_receipt["load_errors"], 7)
        self.assertEqual(self.app.closed, ["owned"])
        self.assertTrue(self.app.exited)

    def test_primary_survives_restore_failure(self):
        self.app.restore_failure = True
        self.app.import_failure = ValueError('caller primary')
        with self.assertRaisesRegex(ValueError, "caller primary") as caught:
            with self.session():
                self.fail('failed import unexpectedly yielded')
        self.assertTrue(caught.exception.solidworks_receipt["cleanup_errors"])
        self.assertFalse(self.app.exited)
        self.assertTrue(caught.exception.__notes__)

    def test_cleanup_failure_without_primary_is_error(self):
        self.app.restore_failure = True
        with self.assertRaises(sw.SolidWorksApplicationError):
            with self.session():
                self.fail('restore failure unexpectedly yielded')

    def test_unknown_import_ownership_retains_application(self):
        self.app.import_failure = RuntimeError("import primary")
        with self.assertRaisesRegex(RuntimeError, "import primary") as caught:
            with self.session():
                pass
        self.assertFalse(self.app.exited)
        self.assertEqual(self.app.closed, [])
        self.assertEqual(
            caught.exception.solidworks_receipt["application_retained_reason"], "import_ownership_unconfirmed"
        )

    def test_wrong_version_rejected_and_own_empty_app_exited(self):
        self.app.revision = "31.0"
        with self.assertRaisesRegex(sw.SolidWorksApplicationError, "revision30"):
            with self.session():
                pass
        self.assertTrue(self.app.exited)

    def test_existing_document_is_never_closed(self):
        self.app.existing = Document("existing")
        self.app.documents = [self.app.existing]
        with self.assertRaisesRegex(sw.SolidWorksApplicationError, "already open"):
            with self.session():
                pass
        self.assertEqual(self.app.closed, [])
        self.assertFalse(self.app.exited)

    def test_invalid_inputs_do_not_initialize_com(self):
        for changes in ({"session_mode": "fallback"}, {"visible": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                with self.session(**changes):
                    pass
        self.assertEqual(self.calls, [])

    def test_attach_failure_has_no_dispatch_fallback(self):
        pc, client = sw._com_modules()
        client.GetActiveObject = lambda _: (_ for _ in ()).throw(RuntimeError("no active app"))
        with self.assertRaisesRegex(RuntimeError, "no active app"):
            with self.session(session_mode="attach"):
                pass
        self.assertNotIn(("new", "SldWorks.Application.30"), self.calls)


if __name__ == "__main__":
    unittest.main()
