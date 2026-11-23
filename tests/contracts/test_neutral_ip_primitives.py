import copy,json,unittest
import importlib.util
from pathlib import Path
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.backends.simion import assembly_geometry as target
from msplatform.backends.simion.ip_geometry import _primitive
from msplatform.backends.simion.operations import compile_geometry

REPO=Path(__file__).resolve().parents[2]

class CanonicalIpNeutralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=json.loads((REPO/'tests/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        cls.component=resolve_component(fixture['component_requests']['ion_processor'])
        recipe=copy.deepcopy(fixture['recipe']);recipe['instances']=recipe['instances'][:1];recipe['connections']=[]
        cls.assembly=assemble(recipe,{'ion_processor':cls.component})
        cls.snapshot=dict(composition_plan=cls.assembly.composition_plan,components_resolved=cls.assembly.components_resolved,components_source=cls.assembly.components_source)
        cls.members=assembly_geometry_members(cls.snapshot)
    def test_all_real_primitives_and_pose_bounds(self):
        self.assertEqual(len(self.members),15)
        transform=RigidTransform.from_contract(self.members[0]['transform'])
        identity=RigidTransform.identity(transform.from_frame_id)
        counts={}
        for member in self.members:
            def visit(shape):
                if shape['kind']=='union':
                    for part in shape['parts']:visit(part)
                elif shape['kind']=='difference':
                    visit(shape['base'])
                    for part in shape['tools']:visit(part)
                else:
                    k=shape['kind'];counts[k]=counts.get(k,0)+1
                    local={'shape':k[3:],**{a:b for a,b in shape.items() if a!='kind'}}
                    a,b=shape_bounds(local)
                    text,lo,hi=target._world_primitive(shape,identity,[])
                    self.assertEqual(text,_primitive(local));self.assertEqual(lo,a);self.assertEqual(hi,b)
                    _,lo,hi=target._world_primitive(shape,transform,[])
                    for i in range(3):
                        j=next(j for j in range(3) if transform.rotation[i][j])
                        values=[transform.rotation[i][j]*v+transform.translation_mm[i] for v in (a[j],b[j])]
                        self.assertAlmostEqual(lo[i],min(values));self.assertAlmostEqual(hi[i],max(values))
            visit(member['shape'])
        self.assertEqual(counts,{'ip_box':385,'ip_cylinder_x':9})
    def compile_complete(self,assembly):
        import itertools
        from msplatform.components.shape_query import query_members
        from msplatform.contracts.rigid_transform import FramedPosition
        snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
        members=assembly_geometry_members(snapshot)
        frame=snapshot['composition_plan']['recipe']['assembly_frame_id']
        witnesses=[]
        for member in members:
            key=(member['instance_id'],member['electrode_group_id'])
            for _,_,low,high in target._pieces(member['shape'],RigidTransform.from_contract(member['transform']),[]):
                found=False
                for fractions in itertools.product((.05,.2,.5,.8,.95),repeat=3):
                    point=[round((a+(b-a)*f)*10)/10 for a,b,f in zip(low,high,fractions,strict=True)]
                    if query_members(members,point,frame_id=frame)=={'status':'interior','group':key}:
                        witnesses.append(dict(instance_id=key[0],electrode_group_id=key[1],
                                              gu=[round((v+1000)*10) for v in point]));found=True;break
                if found:break
            else:self.fail('no canonical point witness for '+str(key))
        ip=next(member for member in members if member['instance_id']=='ion_processor')
        pose=RigidTransform.from_contract(ip['transform'])
        hole=pose.transform_position(FramedPosition(ip['local_frame_id'],(190.2,0.,0.))).coordinates_mm
        hole_gu=[round((value+1000)*10) for value in hole]
        numerics=dict(representation='neutral_world_collision',domain=dict(frame_id=frame,minimum_mm=[-1000,-1000,-1000],maximum_mm=[1000,1000,1000]),pitch_mm=.1,boundary='native_zero_neumann',metal_witnesses=witnesses,void_witnesses=[[0,0,0],hole_gu])
        return compile_geometry(assembly,numerics=numerics)
    def test_complete_public_neutral_compile_with_real_group_witnesses(self):
        compiled=self.compile_complete(self.assembly)
        self.assertEqual(len(compiled.frontend_geometry['members']),15)
        self.assertEqual(len(compiled.frontend_geometry['electrode_mapping']),15)
        self.assertEqual(len(compiled.frontend_geometry['physical_samples']),17)
    def test_connected_rf_ip_public_neutral_compile(self):
        from importlib.resources import files
        example=json.loads(files('msplatform').joinpath('examples/rf_oatof_functional_v1.json').read_text(encoding='utf8'))
        rf=resolve_component(example['component_requests']['multipole'])
        recipe=copy.deepcopy(self.assembly.composition_plan['recipe'])
        recipe['instances'].insert(0,dict(instance_id='multipole',project_id='rf_multipole_ion_optics',transform=dict(
            schema_version=1,role='rigid_transform',from_frame_id=rf.assembly_interface['local_frame_id'],
            to_frame_id=recipe['assembly_frame_id'],rotation=[[0,-1,0],[0,0,1],[-1,0,0]],translation_mm=[0,-305.6,3])))
        recipe['connections']=[dict(connection_id='rf_to_ip',upstream=dict(instance_id='multipole',port_id='mechanical_exit'),
            downstream=dict(instance_id='ion_processor',port_id='guide_inlet'),gap_mm=1.,coupling_mode='monolithic_joint_solve')]
        actual=assemble(recipe,{'ion_processor':self.component,'multipole':rf})
        compiled=self.compile_complete(actual)
        self.assertEqual(len(compiled.frontend_geometry['members']),47)
        self.assertEqual(len(compiled.frontend_geometry['electrode_mapping']),23)
    def test_bounded_full_ip_compile_preserves_all_witnesses(self):
        large=self.compile_complete(self.assembly)
        old=large.frontend_geometry['metal_witnesses'];delta=[9960,7745,9990]
        selected=[dict(instance_id=row['instance_id'],electrode_group_id=row['electrode_group_id'],
                       gu=[value-offset for value,offset in zip(row['gu'],delta,strict=True)]) for row in old]
        frame=self.snapshot['composition_plan']['recipe']['assembly_frame_id']
        numerics=dict(representation='neutral_world_collision',domain=dict(frame_id=frame,minimum_mm=[-4,-225.5,-1],maximum_mm=[4,-34,7]),
            pitch_mm=.1,boundary='native_zero_neumann',metal_witnesses=selected,void_witnesses=[[0,0,0],[40,1907,40]])
        result=compile_geometry(self.assembly,numerics=numerics)
        self.assertEqual(result.frontend_geometry['dimensions'],[81,1916,81])
        self.assertEqual(len(result.frontend_geometry['metal_witnesses']),15)
        self.assertEqual(len(result.frontend_geometry['physical_samples']),17)
    def test_invalid_ip_shapes_and_rotation_refuse(self):
        import math
        identity=RigidTransform.identity('world')
        for shape in (dict(kind='ip_box',min_mm=[0,0,0],max_mm=[0,1,1]),dict(kind='ip_cylinder_x',x_min_mm=0,x_max_mm=1,center_y_mm=0,center_z_mm=0,radius_mm=-1),dict(kind='ip_unknown')):
            with self.subTest(shape=shape),self.assertRaises(ValueError):target._world_primitive(shape,identity,[])
        c=math.sqrt(.5)
        rotated=RigidTransform('world','world',((c,-c,0),(c,c,0),(0,0,1)),(0,0,0))
        with self.assertRaisesRegex(ValueError,'signed axis-permutation'):
            target._world_primitive(dict(kind='ip_box',min_mm=[0,0,0],max_mm=[1,1,1]),rotated,[])
    def test_overlapping_different_groups_still_refuse(self):
        member=copy.deepcopy(self.members[0]);other=copy.deepcopy(member);other['electrode_group_id']='other'
        frame=self.snapshot['composition_plan']['recipe']['assembly_frame_id']
        domain=dict(frame_id=frame,minimum_mm=[-1000,-1000,-1000],maximum_mm=[1000,1000,1000])
        with self.assertRaisesRegex((ValueError,RuntimeError), 'overlap' if importlib.util.find_spec('cadquery') else 'optional cad-step'):
            target._render_assembly_members_gem(self.snapshot,[member,other],domain=domain,pitch_mm=1,boundary='native_zero_neumann')
