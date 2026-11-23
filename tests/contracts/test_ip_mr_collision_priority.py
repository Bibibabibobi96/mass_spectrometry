"""Synthetic canonical provider priority and collision IOB contracts; no native run."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from tests.contracts.test_support import ip_mr_sampled_field_fixture as fixture
from msplatform.backends.simion.ip_mr_collision_priority import compile_ip_mr_priority,project_ip_mr_collision_iob,render_ip_mr_instance_adjust
from msplatform.backends.simion.native_plans import rigid_iob_placement
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.io.manifest_records import file_record

class CollisionPriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.assembly,cls.geometry,_=fixture._fixture_geometry()

    def make_args(self,root):
        proof=fixture._priority_records(root,self.assembly,self.geometry)
        roles=dict(background='vacuum',rf='multipole',ip='ion_processor',analyzer='mrtof_analyzer',detector='mrtof_detector')
        instances=[dict(role='vacuum',instance_index=1,priority_number=1,rotation=[[1,0,0],[0,1,0],[0,0,1]],grid=dict(nx=1001,ny=1001,nz=1001,dx_mm=1,dy_mm=1,dz_mm=1),placement=dict(x_mm=-400,y_mm=-400,z_mm=-400,az_deg=0,el_deg=0,rt_deg=0,scale=1))]
        geo=self.geometry.frontend_geometry
        for role,index in [('multipole',2),('ion_processor',3),('mrtof_analyzer',4),('mrtof_detector',5)]:
            domain=geo['numerical_domains'][role];pose=geo['asset_poses'][role]
            instances.append(dict(role=role,instance_index=index,priority_number=index,rotation=pose['rotation'],grid={**domain['dimensions'],**{'d'+a+'_mm':domain['cell_mm_xyz'][a] for a in 'xyz'}},placement=rigid_iob_placement(pose,origin_mm=[domain['instance_origin_mm'][a] for a in 'xyz'])))
        return dict(instances=list(reversed(instances)),roles=roles,background_bounds_mm=[[-400,600]]*3,**proof)

    def test_priority_and_negative_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.make_args(Path(tmp)); result=compile_ip_mr_priority(self.geometry,**args)
            self.assertEqual(result['analyzer_slot'],4);self.assertIn('ion_instance ~= 4',render_ip_mr_instance_adjust(result))
            self.assertEqual([r['instance_index'] for r in result['instances']],[1,2,3,4,5])
            for mode in ('duplicate','priority','rotation','grid','background','missing','source'):
                with self.subTest(mode=mode):
                    bad=copy.deepcopy(args);geo=copy.deepcopy(self.geometry);by={r['role']:r for r in bad['instances']}
                    if mode=='duplicate':by['multipole']['instance_index']=1
                    elif mode=='priority':by['mrtof_detector']['priority_number']=1
                    elif mode=='rotation':by['multipole']['rotation'][0][0]=9
                    elif mode=='grid':by['ion_processor']['grid']['nx']+=1
                    elif mode=='background':bad['background_bounds_mm'][0][1]-=1
                    elif mode=='missing':bad['instances'].pop()
                    else:geo.components_resolved['ion_processor']['geometry_mm']={'bad':1}
                    with self.assertRaises((ValueError,KeyError)):compile_ip_mr_priority(geo,**bad)
            from unittest.mock import patch
            path=Path(args['clearance_record']['path']);original=path.read_bytes()
            evidence=json.loads(original);evidence['rows'].pop()
            from msplatform.backends.simion import ip_mr_collision_priority as priority
            original_read=priority._record_json
            def read(name,record):return evidence if name=='priority clearance' else original_read(name,record)
            with patch.object(priority,'_record_json',side_effect=read):
                with self.assertRaisesRegex(ValueError,'complete clearance member coverage'):compile_ip_mr_priority(self.geometry,**args)
            try:
                path.write_bytes(original+b' ')
                with self.assertRaisesRegex(AssertionError,'byte count changed'):compile_ip_mr_priority(self.geometry,**args)
            finally:path.write_bytes(original)

    def test_iob_projector_retains_five_slots_and_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.make_args(root);assets={}
            for role in args['roles'].values():
                pa=root/(role+'.pa');pa.write_bytes(b'INERT');assets[role]={'pa':file_record(pa)}
                if role!=args['roles']['background']:
                    side=pa.with_suffix('.pa-surf');side.write_bytes(b'INERT');w=root/(role+'.csv');w.write_text('0,0,0,.25,nil,nil\n',encoding='utf8')
                    assets[role].update(fractional_surface=file_record(side),surface_witnesses=file_record(w))
            control=root/'empty.fly2';control.write_text('particles{coordinates=0,}',encoding='utf8')
            args.update(asset_records=assets,seed_record=file_record(structural_seed_path(5)),empty_control_record=file_record(control),output_iob=root/'result.iob')
            result=project_ip_mr_collision_iob(self.geometry,**args)
            self.assertEqual([r['role'] for r in result['spec']['instances']],[args['roles'][x] for x in ('background','rf','ip','analyzer','detector')]);self.assertEqual(len(result['immutable_records']),18)
            bad=copy.deepcopy(args);bad['asset_records']['ion_processor']['pa']['sha256']='0'*64
            with self.assertRaisesRegex(AssertionError,'SHA-256 changed'):project_ip_mr_collision_iob(self.geometry,**bad)
            bad=copy.deepcopy(args);del bad['asset_records']['ion_processor']['surface_witnesses']
            with self.assertRaisesRegex(ValueError,'record closure'):project_ip_mr_collision_iob(self.geometry,**bad)
