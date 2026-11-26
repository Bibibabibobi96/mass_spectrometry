import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.execution import owner
from msplatform.io.manifest_records import file_record


class AdditionalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        w = Path(self.tmp.name); self.w = w
        self.root = w/'artifacts/assemblies/instrument_assembly/runs'/owner._CPT_RECOVERY_RUN
        for d in ('inputs/owner', 'inputs/native_sources/msplatform/backends/comsol/matlab', 'logs', 'results'):
            (self.root/d).mkdir(parents=True)
        self.result = w/'result.json'
        self.context = SimpleNamespace(workspace=w, host_state_path=w/'host.sqlite', execution_root=w/'aliases')
        with closing(sqlite3.connect(self.context.host_state_path)) as db:
            db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY, document TEXT)')
            db.execute('INSERT INTO state VALUES (1, ?)', (json.dumps({'schema_version': 1, 'records': []}),)); db.commit()
        r=self.root
        self.paths={'result':self.result,'request':r/'inputs/execution_request.json','config':r/'run_config.json',
                    'completion':r/'results/execution_completion.json','action':r/'inputs/owner/action.py',
                    'matlab':r/'inputs/native_sources/msplatform/backends/comsol/matlab/trace_assembly_particles.m',
                    'task':r/'inputs/particle_task.m','process':r/'logs/operation_0001.process.json',
                    'launcher':r/'logs/particle.launcher.json','capacity':r/'logs/capacity_session.json',
                    'journal':r/'logs/file_roles.json','release':r/'results/assembly_release.txt',
                    'facts':r/'results/assembly_particle_facts.json','csv':r/'results/assembly_particles.csv'}
        for name in ('action','matlab','task','release','csv'): self.paths[name].write_text(name)
        self.write('facts',{'comsol_version':'COMSOL Multiphysics 6.4 (Build: 293)', 'study_completed':True, 'particle_count':3, 'stored_times_us':[0,90], 'boundary_policy':'metal_and_outer_freeze_ideal_pass'})
        action=file_record(self.paths['action'],'required_evidence')
        self.request={'role':'run_artifact_workflow_request','package':{'run_id':r.name,'project':'instrument_assembly','mode':'sim'},
            'payload':{'action':'trace_assembly_particles','plan':{'source':{'rows':[1,2,3]},'observation_times_us':[0,90]}},'expected_operation_ids':['trace_assembly_particles'],
            'operation_dependencies':{},'prepared':{'entrypoint':action,'source_entrypoint':action},
            'capacity':{'commitment_inputs':[]},'retention':{'policy_version':1,'class':'compact','reason':None},
            'paths':{'artifact_root':str(w/'artifacts'),'host_resource_state_path':str(self.context.host_state_path),'execution_root':str(self.context.execution_root)}}
        self.write('request',self.request);self.write('config',{'schema_version':2,'run_id':r.name,'artifact_retention':{'policy_version':1,'class':'compact','reason':None}})
        release={'inherited':False,'token':'token','result':{'status':'released','token':'token'},'error':None}
        obs={'exit_confirmed':True,'returncode':0,'process_id':21,'process_started_at_utc_ticks':123}
        self.writer={'operations':[{'operation_id':'trace_assembly_particles','observation':obs,'resource_release_id':'host-resource-1'}],
                     'resource_releases':[{'release_id':'host-resource-1','completion_receipt':{'host_release':release}}]}
        self.write('process',{'error':None,'observation':{'exit_code':0,'root_process_id':21,'root_process_started_at_utc_ticks':123},'host_release':release})
        self.write('launcher',{'role':'comsol_launcher_completion','run_id':r.name,'operations':[{'operation_id':'launcher-attempt-1','observation':{'exit_confirmed':True,'returncode':0,'process_id':22,'process_started_at_utc_ticks':124}}],'host_release':{'inherited':True,'token':'token','result':None,'error':None}})
        cap={'status':'active','owner':'run-artifact-workflow:instrument_assembly:'+r.name,'artifact_root':str(w/'artifacts'),'lease_id':'lease'}
        self.write('capacity',cap)
        failure={'type':'ValueError','message':'COMSOL native facts differ from the frozen plan or supported version','notes':[]}
        roles={str(p):'required_evidence' for p in r.rglob('*') if p.is_file() and p!=self.paths['release']}
        for name in ('completion','journal'): roles[str(self.paths[name])]='required_evidence'
        self.completion={'run_id':r.name,'project':'instrument_assembly','status':'failed','output_paths':[],'required_output_paths':[],
            'retention_preserve_paths':[],'manifest_extra_fields':{},'exception':failure,'writer_completion':self.writer,
            'execution_request':file_record(self.paths['request'],'required_evidence'),'run_config':file_record(self.paths['config'],'required_evidence'),
            'file_roles':roles,'package':{'run_dir':str(r),'artifact_run_dir':str(r)}}
        self.write('completion',self.completion);self.write('journal',{'schema_version':1,'role':'run_session_file_roles','run_id':r.name,'file_roles':roles})
        self.write('result',{'role':'run_artifact_workflow_result','status':'failed','stage':'finalization','writers_confirmed':True,
            'resume_action':'resume_finalization','run_directory':str(r),'execution_request':str(self.paths['request']),'capacity_session':cap,
            'exception':dict(failure,notes=['Workflow finalization failed: Run contains an undeclared file: assembly_release.txt'])})
        self.patches=[]
        for name,key in [('_CPT_RECOVERY_ACTION_SHA','action'),('_CPT_RECOVERY_MATLAB_SHA','matlab'),('_CPT_RECOVERY_TASK_SHA','task'),('_CPT_RECOVERY_COMPLETION_SHA','completion')]:
            x=patch.object(owner,name,file_record(self.paths[key],'required_evidence')['sha256']);x.start();self.addCleanup(x.stop)
    def write(self,name,value): self.paths[name].write_text(json.dumps(value),encoding='utf8')
    def evidence(self): return {k:file_record(v,'required_evidence') for k,v in self.paths.items()}
    def invoke(self,evidence):
        with patch.object(owner,'_require_capacity_accounted'), patch.object(owner,'_finalize',side_effect=lambda s,r,c,**k:(s,c)):
            return owner.resume_failed_evidence_finalization(self.context,self.result,evidence=evidence)
    def test_success_keeps_original_failed_completion_and_binds_evidence(self):
        before=self.paths['completion'].read_bytes();s,c=self.invoke(self.evidence())
        self.assertEqual(before,self.paths['completion'].read_bytes());self.assertEqual(c['status'],'failed')
        self.assertEqual(c['manifest_extra_fields'],{});self.assertIn(self.paths['release'],s._additional_failed_evidence)
        self.assertTrue((self.root/'logs/failed_evidence_recovery.json').exists())
    def test_native_evidence_denies_writes_until_finalization_returns(self):
        def finalize(session, request, completion, **kwargs):
            for name in ('release', 'facts', 'csv'):
                with self.assertRaises(PermissionError):
                    self.paths[name].write_text('tamper', encoding='utf8')
            return completion
        with patch.object(owner, '_require_capacity_accounted'), patch.object(owner, '_finalize', side_effect=finalize):
            result = owner.resume_failed_evidence_finalization(self.context, self.result, evidence=self.evidence())
        self.assertEqual(result['status'], 'failed')
        self.paths['release'].write_text('writable after guard', encoding='utf8')

    def test_rejects_unexpected_or_tampered_inputs(self):
        for case in ('unknown','hash','active','token','capacity','source','success','extra_process'):
            with self.subTest(case=case):
                ev=self.evidence(); saved={k:v.read_bytes() for k,v in self.paths.items()}
                extra=self.root/'unknown'
                try:
                    if case in ('unknown','extra_process'):
                        extra=self.root/('logs/operation_0002.process.json' if case=='extra_process' else 'unknown');extra.write_text('x')
                    if case=='hash': ev['task']['sha256']='0'*64
                    if case=='source': self.paths['matlab'].write_text('changed');ev['matlab']=file_record(self.paths['matlab'],'required_evidence')
                    if case=='active':
                        with closing(sqlite3.connect(self.context.host_state_path)) as db:db.execute('UPDATE state SET document=? WHERE id=1',(json.dumps({'schema_version':1,'records':[{'token':'token'}]}),));db.commit()
                    if case=='token':
                        d=json.loads(self.paths['launcher'].read_text());d['host_release']['token']='wrong';self.write('launcher',d);ev['launcher']=file_record(self.paths['launcher'],'required_evidence')
                    if case=='capacity':
                        d=json.loads(self.paths['capacity'].read_text());d['lease_id']='wrong';self.write('capacity',d);ev['capacity']=file_record(self.paths['capacity'],'required_evidence')
                    if case=='success':
                        d=json.loads(self.paths['completion'].read_text());d['status']='success';self.write('completion',d);ev['completion']=file_record(self.paths['completion'],'required_evidence')
                    with self.assertRaises((ValueError,AssertionError)):self.invoke(ev)
                finally:
                    if extra.exists():extra.unlink()
                    for k,b in saved.items():self.paths[k].write_bytes(b)
                    with closing(sqlite3.connect(self.context.host_state_path)) as db:db.execute('UPDATE state SET document=? WHERE id=1',(json.dumps({'schema_version':1,'records':[]}),));db.commit()
    def test_real_finalize_requires_native_policy_and_resumes_exact_partial(self):
        from msplatform.backends.comsol.assembly_particle_tracing import _comsol_batch_completion_api
        evidence = self.evidence()
        before = self.paths['completion'].read_bytes()
        with patch.object(owner, '_require_capacity_accounted'):
            with self.assertRaisesRegex(ValueError, 'explicit completion policy'):
                owner.resume_failed_evidence_finalization(self.context, self.result, evidence=evidence)
        recovery = self.root/'logs/failed_evidence_recovery.json'
        self.assertTrue(recovery.is_file())
        recovery_bytes = recovery.read_bytes()
        def publish(completion_path, session_path, wait_path, **kwargs):
            outputs = kwargs['additional_output_paths']
            self.assertTrue(all(self.paths[name] in outputs for name in ('release', 'facts', 'csv')))
            (self.root/'run_manifest.json').write_text('{}', encoding='utf8')
            return {}
        with patch.object(owner, '_require_capacity_accounted'), \
             patch.object(owner, 'publish_workflow_terminal', side_effect=publish), \
             patch.object(owner.lifecycle, 'finalize_ready', return_value={}), \
             patch.object(owner, 'exit_capacity_session'):
            result = owner.resume_failed_evidence_finalization(
                self.context, self.result, evidence=evidence, completion_api=_comsol_batch_completion_api)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.paths['completion'].read_bytes(), before)
        self.assertEqual(recovery.read_bytes(), recovery_bytes)
        self.assertTrue((self.root/'retention_actions.json').is_file())

    def test_retry_rejects_modified_recovery_snapshot(self):
        evidence = self.evidence()
        self.invoke(evidence)
        path = self.root/'logs/failed_evidence_recovery.json'
        doc = json.loads(path.read_text(encoding='utf8'))
        doc['original_result_bytes_base64'] = 'eA=='
        path.write_text(json.dumps(doc), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'snapshot differs'):
            self.invoke(evidence)

    def test_retry_refuses_changed_journal(self):
        self.invoke(self.evidence())
        with self.assertRaises(ValueError):self.invoke(self.evidence())

if __name__=='__main__':unittest.main()
