"""Synthetic real CLI adapter tests, not native field qualification."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from msplatform.contracts.rigid_transform import RigidTransform

ROOT = Path(__file__).resolve().parents[2]


def authority():
    metadata = dict(source={'id':'explicit-fixture'}, bvp={'ground_V':0.}, frame_id='world',
        units={'length':'mm','electric_field':'V/m','potential':'V'},potential_reference='ground')
    left = dict(metadata=metadata, transform=RigidTransform.identity('world').to_contract(),
                status_by_point_id={'001':'valid','1':'valid','NA':'valid'})
    right=copy.deepcopy(left); right['metadata']['frame_id']='local'
    right['transform']=RigidTransform('local','world',((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)),(4.,1.,0.)).to_contract()
    right['status_by_point_id']={'001':'valid','2':'excluded','NA':'valid'}
    return {'reference':left,'candidate':right}


class StaticFieldConsumersTests(unittest.TestCase):
    def test_oa_static_cli_reports_transformed_and_incomplete_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); header='point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
            (root/'a.csv').write_text(header+'001,1,2,3,0,2,0\n1,0,0,0,0,0,0\nNA,1,2,3,0,2,0\n',encoding='utf-8')
            (root/'b.csv').write_text(header+'001,1,3,3,2,0,0\n2,0,0,0,0,0,0\nNA,1,3,3,2,0,0\n',encoding='utf-8')
            data=authority();data['reference']['metadata']['potential_reference']=None;data['candidate']['metadata']['potential_reference']=None
            data.update(schema_version=1,role='static_field_comparison_authority',coordinate_tolerance_mm=0.);(root/'authority.json').write_text(json.dumps(data),encoding='utf-8')
            result=subprocess.run([sys.executable,'-B','-m','projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples',
                str(root/'a.csv'),str(root/'b.csv'),'--output',str(root/'out'),'--static-comparison-authority',str(root/'authority.json')],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            value=json.loads((root/'out/static_field_comparison.json').read_text(encoding='utf-8'))
            self.assertEqual(value['schema_version'],1);self.assertEqual(value['role'],'static_field_sample_comparison')
            self.assertEqual(value['status'],'DESCRIPTIVE_ONLY');self.assertEqual(value['paired_valid_count'],2)
            self.assertEqual(value['coverage_counts']['total_union'],4);self.assertEqual(value['coverage_counts']['candidate']['excluded'],1)
            self.assertEqual({row['point_id'] for row in value['coverage']},{'001','1','2','NA'})
            self.assertEqual(value['metrics']['field_vector']['rms_difference_V_per_m'],0.)

    def test_rf_offline_cli_reports_transformed_and_incomplete_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); h='sample_id,region,field_case,x_mm,y_mm,z_mm,potential_V,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
            a=''.join(f'001,rod,{case},1,2,3,0,0,2,0\n1,rod,{case},0,0,0,0,0,0,0\nNA,rod,{case},1,2,3,0,0,2,0\n' for case in ('differential','static'))
            b=''.join(f'001,rod,{case},1,3,3,0,2,0,0\n2,rod,{case},0,0,0,0,0,0,0\nNA,rod,{case},1,3,3,0,2,0,0\n' for case in ('differential','static'))
            (root/'a.csv').write_text(h+a,encoding='utf-8');(root/'b.csv').write_text(h+b,encoding='utf-8')
            value={'schema_version':1,'role':'multipole_static_field_comparison_authority','differential':authority(),'static':authority(),'coordinate_tolerance_mm':0.}
            (root/'authority.json').write_text(json.dumps(value),encoding='utf-8')
            result=subprocess.run([sys.executable,'-B','-m','projects.rf_multipole_ion_optics.analysis.stationary_field_sampling',
                'compare','--reference',str(root/'a.csv'),'--candidate',str(root/'b.csv'),'--output',str(root/'out.json'),
                '--comparison-authority',str(root/'authority.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            value=json.loads((root/'out.json').read_text(encoding='utf-8'))
            self.assertEqual(value['schema_version'],1);self.assertEqual(value['role'],'multipole_static_field_comparison')
            self.assertEqual(value['status'],'DESCRIPTIVE_ONLY')
            for case in ('differential','static'):
                self.assertEqual(value['field_cases'][case]['paired_valid_count'],2)
                self.assertEqual(value['field_cases'][case]['coverage_counts']['total_union'],4)
                self.assertEqual(value['field_cases'][case]['coverage_counts']['candidate']['excluded'],1)
                self.assertEqual({row['point_id'] for row in value['field_cases'][case]['coverage']},{'001','1','2','NA'})


    def test_authority_versions_and_unknown_keys_rejected_by_real_cli(self):
        for mode in ("oa", "rf"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                if mode=="oa":
                    header='point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
                    payload=header+'001,1,2,3,0,2,0\n'
                    doc=authority();doc['candidate']=copy.deepcopy(doc['reference'])
                    doc.update(schema_version=1,role='static_field_comparison_authority',coordinate_tolerance_mm=0.)
                    module='projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples'
                    args=[str(root/'a.csv'),str(root/'b.csv'),'--output',str(root/'output'),'--static-comparison-authority',str(root/'authority.json')]
                else:
                    header='sample_id,region,field_case,x_mm,y_mm,z_mm,potential_V,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
                    payload=header+''.join(f'001,rod,{case},1,2,3,0,0,2,0\n' for case in ('differential','static'))
                    pair=authority();pair['candidate']=copy.deepcopy(pair['reference'])
                    doc={'schema_version':1,'role':'multipole_static_field_comparison_authority','differential':pair,'static':copy.deepcopy(pair),'coordinate_tolerance_mm':0.}
                    module='projects.rf_multipole_ion_optics.analysis.stationary_field_sampling'
                    args=['compare','--reference',str(root/'a.csv'),'--candidate',str(root/'b.csv'),'--output',str(root/'output.json'),'--comparison-authority',str(root/'authority.json')]
                for name in ('a.csv','b.csv'):(root/name).write_text(payload,encoding='utf-8')
                for mutation in ('missing_version','unsupported_version','unknown_outer','unknown_side'):
                    bad=copy.deepcopy(doc)
                    if mutation=='missing_version':del bad['schema_version']
                    elif mutation=='unsupported_version':bad['schema_version']=2
                    elif mutation=='unknown_outer':bad['unexpected']=True
                    else:(bad['reference'] if mode=='oa' else bad['static']['reference'])['unexpected']=True
                    (root/'authority.json').write_text(json.dumps(bad),encoding='utf-8')
                    result=subprocess.run([sys.executable,'-B','-m',module,*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
                    self.assertNotEqual(result.returncode,0,(mode,mutation,result.stdout))
                    self.assertIn('authority',result.stderr)
                    self.assertFalse((root/'output').exists());self.assertFalse((root/'output.json').exists())

    def test_oa_generic_cli_rejects_trajectory_identity_even_with_point_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);payload='point_id,particle_id,time_us,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n001,1,0,1,2,3,0,2,0\n'
            for name in ('a.csv','b.csv'):(root/name).write_text(payload,encoding='utf-8')
            doc=authority();doc['candidate']=copy.deepcopy(doc['reference']);doc.update(schema_version=1,role='static_field_comparison_authority',coordinate_tolerance_mm=0.)
            (root/'authority.json').write_text(json.dumps(doc),encoding='utf-8')
            result=subprocess.run([sys.executable,'-B','-m','projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples',
                str(root/'a.csv'),str(root/'b.csv'),'--output',str(root/'out'),'--static-comparison-authority',str(root/'authority.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
            self.assertNotEqual(result.returncode,0);self.assertIn('rejects trajectory',result.stderr);self.assertFalse((root/'out').exists())

    def test_rf_generic_cli_rejects_each_source_case_identity_mismatch(self):
        h='sample_id,region,field_case,x_mm,y_mm,z_mm,potential_V,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
        rows='001,rod,differential,1,2,3,0,0,2,0\n001,rod,static,1,2,3,0,0,2,0\n'
        for mutation in ('coordinates','region','missing','duplicate'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);broken=rows
                if mutation=='coordinates':broken=broken.replace('001,rod,static,1,2,3','001,rod,static,2,2,3')
                elif mutation=='region':broken=broken.replace('001,rod,static','001,other,static')
                elif mutation=='missing':broken=broken.splitlines(keepends=True)[0]
                else:broken+=broken.splitlines(keepends=True)[0]
                (root/'a.csv').write_text(h+broken,encoding='utf-8');(root/'b.csv').write_text(h+rows,encoding='utf-8')
                pair=authority();pair['candidate']=copy.deepcopy(pair['reference']);doc={'schema_version':1,'role':'multipole_static_field_comparison_authority','differential':pair,'static':copy.deepcopy(pair),'coordinate_tolerance_mm':0.}
                (root/'authority.json').write_text(json.dumps(doc),encoding='utf-8')
                result=subprocess.run([sys.executable,'-B','-m','projects.rf_multipole_ion_optics.analysis.stationary_field_sampling','compare',
                    '--reference',str(root/'a.csv'),'--candidate',str(root/'b.csv'),'--output',str(root/'out.json'),'--comparison-authority',str(root/'authority.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
                self.assertNotEqual(result.returncode,0,(mutation,result.stdout));self.assertIn('StationaryFieldContractError',result.stderr)
                self.assertFalse((root/'out.json').exists())


    def test_both_new_cli_paths_reject_duplicate_authority_keys(self):
        for mode in ("oa", "rf"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                if mode=="oa":
                    payload='point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n001,1,2,3,0,2,0\n'
                    module='projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples'
                    args=[str(root/'a.csv'),str(root/'b.csv'),'--output',str(root/'out'),'--static-comparison-authority',str(root/'authority.json')]
                else:
                    payload='sample_id,region,field_case,x_mm,y_mm,z_mm,potential_V,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
                    payload+=''.join(f'001,rod,{case},1,2,3,0,0,2,0\n' for case in ('differential','static'))
                    module='projects.rf_multipole_ion_optics.analysis.stationary_field_sampling'
                    args=['compare','--reference',str(root/'a.csv'),'--candidate',str(root/'b.csv'),'--output',str(root/'out.json'),'--comparison-authority',str(root/'authority.json')]
                for name in ('a.csv','b.csv'):(root/name).write_text(payload,encoding='utf-8')
                (root/'authority.json').write_text('{"schema_version":1,"schema_version":1}',encoding='utf-8')
                result=subprocess.run([sys.executable,'-B','-m',module,*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
                self.assertNotEqual(result.returncode,0);self.assertIn("duplicate JSON key 'schema_version'",result.stderr)
                self.assertFalse((root/'out').exists());self.assertFalse((root/'out.json').exists())


if __name__=='__main__':unittest.main()
