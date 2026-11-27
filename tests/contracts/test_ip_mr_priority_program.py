"""Pure existing priority Program and sampled-owner boundary; inert Lua only."""
import copy
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from msplatform.backends.simion import rf_tracking_program as subject
from msplatform.backends.simion.rf_tracking_execution import plan_ip_mr_tracking_workbench

class PriorityProgramTests(unittest.TestCase):
    def test_priority_world_pose_boundary_and_refusals(self):
        roles=dict(background='bg',rf='rf',ip='ip',analyzer='analyzer',detector='detector')
        names=[None,'rf','ip','analyzer','detector']
        policy=dict(role='ip_mr_collision_priority',roles=roles,
            instances=[dict(role=name,instance_index=i,priority_number=i) for i,name in enumerate(roles.values(),1)],
            analyzer_slot=4,ip_box=dict(pose=dict(rotation=[[0,0,-1],[1,0,0],[0,-1,0]],translation_mm=[0,-225,3]),
                                       bounds=[[0,2],[0,4],[0,6]]))
        program=subject._ip_mr_priority_program(policy,names)
        lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not lua:self.skipTest('standalone Lua not available')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'query.lua'
            path.write_text('segment={}\n'+program+'''\nlocal function check(slot,x,y,z,expected)
 ion_instance=slot;ion_px_mm=x;ion_py_mm=y;ion_pz_mm=z;segment.instance_adjust();assert(ion_instance==expected)
end
check(4,-3,-224,1,0)
check(4,0,-225,3,0)
check(4,-3,-222,1,4)
check(2,-3,-224,1,2)
check(5,-3,-224,1,5)
''',encoding='utf8')
            run=subprocess.run([str(lua),str(path)],cwd=directory,capture_output=True,text=True,encoding='utf8',timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
        for change in ('role','order','analyzer'):
            bad=copy.deepcopy(policy)
            if change=='role':bad['roles']['rf']='wrong'
            if change=='order':bad['instances'][1]['instance_index']=3
            if change=='analyzer':bad['analyzer_slot']=5
            with self.subTest(change=change),self.assertRaises(ValueError):subject._ip_mr_priority_program(bad,names)

    def test_sampled_workbench_refuses_missing_priority_metadata(self):
        for metadata in (None,{},dict(collision_priority_applied=False)):
            with self.subTest(metadata=metadata),self.assertRaisesRegex(ValueError,'priority Program'):
                plan_ip_mr_tracking_workbench(None,admission=None,run_directory=Path('unused'),
                    program='-- inert',program_metadata=metadata,native_source_rows=[{}],native_path_resource=Path('unused'))

    def test_actual_program_reports_applied_priority(self):
        from tests.contracts.test_ip_mr_tracking_program import IpMrProgramTests
        IpMrProgramTests.setUpClass()
        self.addCleanup(IpMrProgramTests.tearDownClass)
        with tempfile.TemporaryDirectory() as directory:
            instance=IpMrProgramTests(methodName='test_four_asset_callback')
            instance.model=IpMrProgramTests.model
            basis,names,plan,resources=instance.fixture(Path(directory))
            doc=instance.model.document
            geometry=doc['geometry']['frontend_geometry']
            projects=geometry['composition_plan']['components']
            rf=next(k for k,v in projects.items() if v['project_id']=='rf_multipole_ion_optics')
            ip=next(k for k,v in projects.items() if v['project_id']=='ion_processor')
            mr=next(k for k,v in projects.items() if v['project_id']=='multi_reflection_tof')
            roles=dict(background='background',rf=rf,ip=ip,analyzer=mr+'_analyzer',detector=mr+'_detector')
            policy=dict(role='ip_mr_collision_priority',roles=roles,
                instances=[dict(role=name,instance_index=i,priority_number=i) for i,name in enumerate(roles.values(),1)],
                analyzer_slot=4,ip_box=dict(pose=geometry['asset_poses'][ip],bounds=[[0,2],[0,4],[0,6]]))
            plan['collision_priority']=policy
            plan['scalar_field_basis']=basis
            result=subject.render_rf_controls(instance.model,plan,assets={},native_sources=resources,
                scalar_bindings=basis,slot_domains=[None,rf,ip,mr+'_analyzer',mr+'_detector'])
            self.assertIs(result['build_metadata']['collision_priority_applied'],True)
            self.assertEqual(result['program'].count('function segment.instance_adjust()'),1)
            self.assertIn('ip_mr_priority_adjust()',result['program'])
            from msplatform.backends.simion.tracking_execution import _render_tracking_controls
            controls=_render_tracking_controls(instance.model,plan,field_design=None,stored_bank=None,
                frontend_records={},downstream_assets={},downstream_receipt=None,native_sources=resources)
            self.assertEqual(controls['program'],result['program'])
            self.assertIs(controls['build_metadata']['collision_priority_applied'],True)
            from unittest.mock import patch
            with patch.object(subject,'render_rf_controls',return_value={'build_metadata':{'collision_priority_applied':False}}):
                with self.assertRaisesRegex(ValueError,'priority Program'):
                    _render_tracking_controls(instance.model,plan,field_design=None,stored_bank=None,
                        frontend_records={},downstream_assets={},downstream_receipt=None,native_sources=resources)
