import json
from pathlib import Path
from unittest.mock import patch

from msplatform.execution import owner
from msplatform.io.manifest_records import file_record
from tests.contracts.test_owner_failed_recovery import FailedRecoveryTests


class TraceRecoveryTests(FailedRecoveryTests):
    def setUp(self):
        super().setUp()
        self.context.execution_root = self.root.parent
        native = self.root/'inputs/native_sources/msplatform/backends/comsol/native_execution.py'
        native.parent.mkdir(parents=True); native.write_text('native', encoding='utf8')
        installed_root = self.workspace/'installed/msplatform'
        installed = installed_root/'backends/comsol/native_execution.py'
        installed.parent.mkdir(parents=True); installed.write_text('native', encoding='utf8')
        live = installed.parent/'assembly_particle_tracing.py';live.write_text('frozen', encoding='utf8')
        self.model = self.workspace/'borrowed.mph';self.model.write_text('borrowed', encoding='utf8')
        self.outputs = {n:self.root/'results'/n for n in owner._TRACE_RECOVERY_OUTPUTS}
        for p in self.outputs.values(): p.write_text(p.name, encoding='utf8')
        action=file_record(self.action,'required_evidence');source=file_record(live,'required_evidence')
        model = file_record(self.model,'solver_native_binary')
        manifest = self.workspace/'field-manifest.json'
        product = {'kind':'field_solution','status':'complete','data':{'model':model}}
        self._write(manifest, {'status':'success','products':{'background':product,'on':product}})
        manifest_record = file_record(manifest,'required_evidence')
        background = {'model':model,'reference':{'manifest':manifest_record,'product_id':'background'}}
        on = {'model':model,'reference':{'manifest':manifest_record,'product_id':'on'}}
        self.request.update(package={'run_id':'test-run','project':'instrument_assembly','mode':'comsol_assembly_pulse'},
            payload={'action':'trace_assembly_particles','plan':{'background':background,'on':on}},
            expected_operation_ids=['trace_assembly_particles'],operation_dependencies={},prepared={'entrypoint':action,'source_entrypoint':source})
        self.request['capacity']['source_references']=[{'manifest_record':manifest_record}]
        self.request['paths']['execution_root']=str(self.context.execution_root)
        self._write(self.root/'inputs/execution_request.json',self.request)
        config={'run_id':'test-run','inputs':{'execution_request':str(self.root/'inputs/execution_request.json'),
            'owner_authority_0':str(self.action),'native_backend':str(native),'borrowed_model':str(self.model)}}
        self._write(self.root/'run_config.json',config)
        self.process['observation']['exit_code']=0;self.process['guards']=[str(native)]
        self._write(self.root/'logs/operation_0001.process.json',self.process)
        self.launcher['runtime_storage']['run_directory']=str(self.root/'comsol_runtime/trace_assembly_particles')
        self._write(self.root/'logs/particle.launcher.json',self.launcher)
        (self.root/'logs/reopen_pulse_basis.launcher.json').unlink()
        self.result['exception']={'type':'ValueError','message':'Run contains an undeclared file: '+str(self.outputs['initial_states.parquet']),'notes':[]}
        self._write(self.result_path,self.result)
        role_paths=[p for p in self.root.rglob('*') if p.is_file() and p not in self.outputs.values()]
        self.original_roles={str(p.resolve()):'required_evidence' for p in role_paths}
        self.original_roles[str(self.model.resolve())]='solver_native_binary'
        journal=self.root/'logs/file_roles.json';self.original_roles[str(journal)]='required_evidence'
        self._write(journal,{'role':'run_session_file_roles','run_id':'test-run','file_roles':self.original_roles})
        self.native=native
    def arguments(self):
        paths={'result':self.result_path,'request':self.root/'inputs/execution_request.json',
               'run_config':self.root/'run_config.json','frozen_action':self.action,
               'process':self.root/'logs/operation_0001.process.json','launcher':self.root/'logs/particle.launcher.json',
               'journal':self.root/'logs/file_roles.json'}
        evidence={k:file_record(v,'required_evidence') for k,v in paths.items()}
        evidence['role_authority']={'version':1,'frozen_action_sha256':self.request['prepared']['entrypoint']['sha256'],
                                    'basis':'trace_after_stop_output_and_source_capture'}
        evidence['outputs']={k:file_record(v,'required_evidence') for k,v in self.outputs.items()}
        evidence['sources']={str(self.native.resolve()):file_record(self.native,'required_evidence')}
        return {'explicit_file_roles':{**self.original_roles,**{str(p.resolve()):'required_evidence' for p in self.outputs.values()}},'role_evidence':evidence,'completion_api':lambda: None}
    def test_trace_failed_evidence_keeps_borrowed_role_and_guards(self):
        args=self.arguments()
        def finish(session,request,completion,**kwargs):
            self.assertEqual(session.file_roles[str(self.model.resolve())],'solver_native_binary')
            for path in [*self.outputs.values(), self.action, Path(request['prepared']['source_entrypoint']['path'])]:
                with self.assertRaises(PermissionError):path.write_text('tamper')
            return completion
        with patch.object(owner,'_require_capacity_accounted'),patch.object(owner,'_finalize',side_effect=finish):
            out=owner.recover_failed_finalization(self.context,self.result_path,**args)
        self.assertEqual(out['status'],'failed');self.assertEqual(out['manifest_extra_fields'],{})
        self.assertEqual(len(out['output_paths']),6)
    def test_real_finalize_retention_and_published_failure_evidence(self):
        import base64
        from msplatform.backends.comsol.assembly_particle_tracing import _comsol_batch_completion_api

        retention={'policy_version':1,'class':'compact','reason':None}
        self.request['retention']=retention
        self.request['package']['software']=['COMSOL','MATLAB']
        self.request['prepared']['owner_kind']='managed_action'
        self._write(self.root/'inputs/execution_request.json',self.request)
        config_path=self.root/'run_config.json'
        config=json.loads(config_path.read_text(encoding='utf8'))
        config.update(schema_version=2,project='instrument_assembly',mode='comsol_assembly_pulse',artifact_retention=retention)
        self._write(config_path,config)
        journal_path=self.root/'logs/file_roles.json'
        self._write(self.root/'summary.json',{'status':'checkpoint'})
        self._write(self.root/'run_manifest.json',{'status':'checkpoint'})
        self.original_roles[str(self.root/'summary.json')]='required_evidence'
        self.original_roles[str(self.root/'run_manifest.json')]='required_evidence'
        self._write(journal_path,{'schema_version':1,'role':'run_session_file_roles','run_id':'test-run','file_roles':self.original_roles})
        args=self.arguments();args['completion_api']=_comsol_batch_completion_api
        result_before=self.result_path.read_bytes()
        journal_before=journal_path.read_bytes()
        with patch.object(owner,'_require_capacity_accounted'), \
             patch('msplatform.execution.manifest_publication.validate_run_id'), \
             patch.object(owner.lifecycle,'finalize_ready',return_value={}), \
             patch.object(owner,'exit_capacity_session'), \
             patch.object(owner,'remove_execution_alias'):
            result=owner.recover_failed_finalization(self.context,self.result_path,**args)
        self.assertEqual(result['status'],'failed')
        self.assertTrue((self.root/'retention_actions.json').is_file())
        manifest=json.loads((self.root/'run_manifest.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['status'],'failed')
        self.assertNotIn('products',manifest)
        output_records={Path(x['path']).name:x for x in manifest['outputs']}
        for path in self.outputs.values():
            self.assertEqual(output_records[path.name]['retention_role'],'required_evidence')
            self.assertEqual(output_records[path.name]['sha256'],file_record(path)['sha256'])
        self.assertEqual(manifest['inputs']['borrowed_model']['retention_role'],'solver_native_binary')
        recovery=json.loads((self.root/'results/failed_finalization_recovery.json').read_text(encoding='utf8'))
        self.assertEqual(base64.b64decode(recovery['original_result_bytes_base64']),result_before)
        self.assertEqual(base64.b64decode(recovery['original_journal_bytes_base64']),journal_before)

    def test_trace_rejects_wrong_role_unknown_sources_or_active_token(self):
        for case in ('role','unknown','source','source_recaptured','token','active_writer'):
            with self.subTest(case=case):
                args=self.arguments();extra=self.root/'unknown.dat'
                original=self.native.read_bytes()
                try:
                    if case=='role':args['explicit_file_roles'][str(self.model.resolve())]='required_evidence'
                    if case=='unknown':extra.write_text('unexpected')
                    if case in ('source','source_recaptured'):
                        self.native.write_text('modified')
                        if case=='source_recaptured':
                            args['role_evidence']['sources'][str(self.native.resolve())]=file_record(self.native,'required_evidence')
                    if case=='active_writer':
                        data=json.loads(self.result_path.read_text());data['writers_confirmed']=False;self._write(self.result_path,data)
                        args['role_evidence']['result']=file_record(self.result_path,'required_evidence')
                    if case=='token':
                        import sqlite3
                        from contextlib import closing
                        with closing(sqlite3.connect(self.context.host_state_path)) as db:
                            db.execute('UPDATE state SET document=? WHERE id=1',(json.dumps({'schema_version':1,'records':[{'token':'token'}]}),));db.commit()
                    with self.assertRaises((AssertionError,ValueError)):self.invoke(**args)
                finally:
                    if extra.exists():extra.unlink()
                    self.native.write_bytes(original)
                    if case=='active_writer':self._write(self.result_path,self.result)
                    if case=='token':
                        import sqlite3
                        from contextlib import closing
                        with closing(sqlite3.connect(self.context.host_state_path)) as db:
                            db.execute('UPDATE state SET document=? WHERE id=1',(json.dumps({'schema_version':1,'records':[]}),));db.commit()

# The inherited basis-only tests use a different fixture; run the focused trace methods only.
for _name in ('test_observed_failed_exit_becomes_failed_completion_without_action',
              'test_missing_forged_and_unclassified_evidence_fails_closed'):
    setattr(TraceRecoveryTests, _name, None)
