"""Paired static SIMION Store path with actual inert process-owner calls."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion.paired_static_store import run_paired_static_simion
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution import owner
from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore

INERT = r'''
import json,sys
from pathlib import Path
from msplatform.backends.simion import paired_static_store as w
original=w._run_native
request=json.loads(Path(sys.argv[-1]).read_text(encoding='utf8'))
def inert(context,*,name,arguments,directory,run_directory,limits,records,marker=None):
    outputs=[]
    if name=='gem2pa': outputs=[arguments[-1]]
    elif name=='refine': outputs=[arguments[5]]
    elif name=='detach': outputs=[arguments[-1]]
    if name=='sample':
        p=request['parameters']; code=("import csv\nfrom pathlib import Path\np="+repr(p)+"\n"
            "rows=list(csv.DictReader(open(p['points_record']['path'],encoding='utf8')))\n"
            "fields=['point_id','x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']\n"
            "f=open(p['samples_path'],'w',encoding='utf8',newline='');w=csv.DictWriter(f,fieldnames=fields);w.writeheader()\n"
            "for r in rows: w.writerow(dict(r,Ex_V_per_m=1,Ey_V_per_m=2,Ez_V_per_m=3))\n"
            "f.close();Path(p['facts_path']).write_text('backend=SIMION\\napi=pa:field_vc\\nnative_field_unit=V/gu\\nexport_field_unit=V/m\\nfield_sign=negative_potential_gradient\\npoint_count='+str(len(rows))+'\\n',encoding='utf8')\n")
    else:
        code="from pathlib import Path;outputs="+repr(outputs)+"\nfor p in outputs: Path(p).write_bytes(b'INERT_NOT_PA')\n"
    code += "print("+repr(marker or 'GEM2PA_INERT_PASS')+")"
    return original(context,name=name,arguments=['-c',code],directory=directory,run_directory=run_directory,
        limits=limits,records=records,marker=marker)
w._run_native=inert
w.main()
'''

@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class PairedStaticStoreTests(unittest.TestCase):
    def test_cached_verification_binds_all_consumed_bytes(self):
        from msplatform.backends.simion.paired_static_store import _valid_cache_evidence
        from msplatform.io.file_identity import file_sha256
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            contents={'paired_static_on.pa':'PA', 'verification_points.csv':'point_id,x_mm,y_mm,z_mm\n1,0,0,0\n',
                'verification_samples.csv':'point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n1,0,0,0,1,2,3\n',
                'verification_facts.txt':'backend=SIMION\napi=pa:field_vc\nnative_field_unit=V/gu\nexport_field_unit=V/m\nfield_sign=negative_potential_gradient\npoint_count=1\n',
                'verification_task.lua':'INERT'}
            for name,text in contents.items(): (root/name).write_text(text,encoding='utf8')
            proof=dict(schema_version=1,role='paired_static_pa_sample_verification',
                pa_sha256=file_sha256(root/'paired_static_on.pa'),points_sha256=file_sha256(root/'verification_points.csv'),
                samples_sha256=file_sha256(root/'verification_samples.csv'),facts_sha256=file_sha256(root/'verification_facts.txt'),
                task_sha256=file_sha256(root/'verification_task.lua'),sampler_sha256='A'*64,point_count=1)
            (root/'verification.json').write_text(json.dumps(proof),encoding='utf8')
            self.assertTrue(_valid_cache_evidence(root))
            (root/'verification_samples.csv').write_text('tampered',encoding='utf8')
            self.assertFalse(_valid_cache_evidence(root))
            (root/'verification_samples.csv').write_text(contents['verification_samples.csv'],encoding='utf8')
            proof['point_count']=2
            (root/'verification.json').write_text(json.dumps(proof),encoding='utf8')
            self.assertFalse(_valid_cache_evidence(root))

    def test_plan_gem_mismatch_rejected_before_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); original=root/'original.gem'; original.write_text('A',encoding='utf8')
            changed=root/'different.gem'; changed.write_text('B',encoding='utf8')
            points=root/'points.csv'; points.write_text('point_id,x_mm,y_mm,z_mm\n1,0,0,0\n',encoding='utf8')
            plan=root/'plan.json';plan.write_text(json.dumps(dict(role='oatof_paired_accelerator_static_field_plan',
                native_geometry_compilation=dict(gem_record=file_record(original,'required_evidence')),
                sample_points=dict(path=str(points),count=1))),encoding='utf8')
            store=object(); session=SimpleNamespace(expected_operation_ids=('paired',))
            with patch('msplatform.backends.simion.paired_static_store.current_managed_native_store',return_value={'store':store}), \
                 patch('msplatform.backends.simion.paired_static_store.current_native_artifact_scope',return_value={'store':store}):
                with self.assertRaisesRegex(ValueError,'GEM differs'):
                    run_paired_static_simion(session,operation_id='paired',plan_record=file_record(plan,'required_evidence'),
                        gem_record=file_record(changed,'required_evidence'),points_record=file_record(points,'required_evidence'),
                        resources={'builder':original,'exporter':original,'sampler':original},limits={})

    def test_miss_hit_and_missing_pa_rebuild_with_complete_sample(self):
        with tempfile.TemporaryDirectory(prefix='paired-store-') as directory:
            root=Path(directory);points=root/'points.csv'
            points.write_text('point_id,x_mm,y_mm,z_mm\n1,0,0,0\n2,1,0,0\n',encoding='utf8')
            gem=root/'paired.gem';gem.write_text('INERT_GEM',encoding='utf8')
            grid=dict(dimensions=dict(nx=2,ny=2,nz=2),cell_mm_xyz=dict(x=1.,y=1.,z=1.),
                      instance_origin_mm=dict(x=0.,y=0.,z=0.))
            plan=dict(role='oatof_paired_accelerator_static_field_plan',accelerator_geometry=dict(role='inert'),
                numerical_domain=dict(boundary_policy='native_zero_neumann'),
                native_geometry_compilation=dict(grid=grid,gem_record=file_record(gem,'required_evidence')),
                static_on_electrode_voltages_v={'1':1.,'2':0.},sample_points=dict(path=str(points),count=2))
            plan_path=root/'plan.json';plan_path.write_text(json.dumps(plan),encoding='utf8')
            resources=dict(builder=native_resource_path('build_dirichlet_patch_operating_pa.lua'),
                exporter=native_resource_path('export_detached_standalone_pa.lua'),
                sampler=native_resource_path('export_paired_accelerator_field.lua'))
            script=root/'inert.py';script.write_text(INERT,encoding='utf8'); budget=root/'budget.json';budget.write_text('{}',encoding='utf8')
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3',policy_path=resource_path('host_resource_policy.json'))
            store=ArtifactStore(root/'store');reports=[]
            def action(session):
                reports.append(run_paired_static_simion(session,operation_id='paired',
                    plan_record=file_record(plan_path,'required_evidence'),gem_record=file_record(gem,'required_evidence'),
                    points_record=file_record(points,'required_evidence'),resources=resources,limits={}))
                return dict(status='success',summary={},output_paths=[Path(reports[-1]['sample_record']['path'])],
                    required_output_paths=[Path(reports[-1]['sample_record']['path'])],retention_preserve_paths=[],manifest_extra_fields={})
            actual=RunSession.run_process
            def transport(session,operation_id,**kwargs):
                kwargs['arguments']=['-I','-B',str(script),kwargs['arguments'][-1]]
                return actual(session,operation_id,**kwargs)
            env=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                     MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,env),patch.object(RunSession,'run_process',new=transport):
                for i,(disposition,count) in enumerate((('miss',4),('hit',1),('miss',4))):
                    result=owner.run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='paired',software=[]),
                        run_id=f'20261127_14000{i}__test__python__paired-store',payload={},committed_new_bytes=16*1024*1024,
                        commitment_inputs=[file_record(budget,'required_evidence')],
                        retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert paired sample'),
                        expected_operation_ids=['paired'],operation_dependencies={},action=action,
                        action_record=file_record(Path(__file__),'required_evidence'),artifact_store=store,
                        completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
                    self.assertEqual(result['status'],'success')
                    self.assertEqual((reports[-1]['cache_disposition'],reports[-1]['native_count']),(disposition,count))
                    self.assertTrue(Path(reports[-1]['sample_record']['path']).is_file())
                    if i==1:
                        with store.claim_verified(reports[-1]['asset_id']) as asset:
                            (asset/'paired_static_on.pa').unlink()
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0],0)
