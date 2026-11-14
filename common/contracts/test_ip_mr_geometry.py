"""Pure selected IP–MR geometry; no solver or flight claim."""
import copy
import json
import subprocess
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.backends.simion.mr_compiler import compile_complete_mr_geometry, _polygon_mirror_witness
from msplatform.backends.simion.compiler import _content_sha256
from msplatform.backends.simion.operations import compile_geometry
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.io.manifest_records import file_record
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from common.contracts.test_dual_cone_iob import HARNESS, LUA
from msplatform.components.geometry_members import assembly_geometry_members
class IpMrGeometryTests(unittest.TestCase):
    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable; no native fallback')
    def test_ip_mr_lua_geometry_roles_and_refusals(self):
        for count in (3,4):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);seed=root/'seed.iob';seed.write_bytes(b'inert-seed')
                output=root/'instrument.iob';control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
                rows=[]
                for index in range(1,count+1):
                    raw=root/f'body{index}.pa#';raw.write_bytes(b'inert-raw')
                    surface=root/f'body{index}.pa-surf';surface.write_bytes(b'inert-surface')
                    witness=root/f'body{index}.csv';witness.write_text('0,0,0,.25,nil,nil\n')
                    rows.append(dict(role=f'body{index}',instance_index=index,priority_number=index,path=str(raw),
                        fractional_surface=str(surface),surface_witnesses=str(witness),response_ids=[1],
                        grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],
                        placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),
                        physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)]))
                spec=dict(schema_version=1,role='ip_mr_geometry_iob_build',instances=rows,seed_iob=str(seed),output_iob=str(output),
                    bootstrap_paths=[str(root/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,count+1)],empty_particle_control=str(control))
                request=root/'spec.lua';script=root/'harness.lua';native_path=root/'path.lua'
                native_path.write_text('return function(path)return path end',encoding='utf8')
                code=(HARNESS.replace('getmetatable(instances).__len=function()return 1 end','getmetatable(instances).__len=function()return #spec.instances end')
                    .replace(" local row=spec.instances[1]\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[1]", " for i,row in ipairs(spec.instances) do\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[i]")
                    .replace(' slots[1]=item\nend',' slots[i]=item\n end\nend')
                    .replace('arg={arg[1],mode,arg[5]}','local resources=arg[5];arg={arg[1],mode,arg[4]}')
                    .replace("arg[3]..'/iob_core.lua'","resources..'/iob_core.lua'")
                    .replace("if mode=='build'or mode=='verify'then", "if failure=='direct' then assert(loadfile(resources..'/iob_core.lua'))()(spec,mode,function(path)return path end) elseif mode=='build'or mode=='verify'then"))
                script.write_text(code,encoding='utf8');resources=native_resource_path('iob_core.lua').parent
                def call(mode,value,failure='valid'):
                    request.write_text('return '+lua_value(value),encoding='utf8')
                    return subprocess.run([str(LUA),str(script),str(request),mode,failure,str(native_path),str(resources)],
                                          cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
                built=call('build_geometry',spec);self.assertEqual(built.returncode,0,built.stderr);self.assertIn('IP_MR_GEOMETRY_IOB=PASS',built.stdout)
                reopened=call('verify_geometry',spec);self.assertEqual(reopened.returncode,0,reopened.stderr);self.assertIn('IP_MR_GEOMETRY_IOB_REOPEN=PASS',reopened.stdout)
                invalid=copy.deepcopy(spec);invalid['instances'][1]['role']=invalid['instances'][0]['role']
                refused=call('verify_geometry',invalid);self.assertNotEqual(refused.returncode,0);self.assertIn('identities must be unique',refused.stderr)
                invalid=copy.deepcopy(spec);invalid['instances']=invalid['instances'][:2]
                refused=call('verify_geometry',invalid);self.assertNotEqual(refused.returncode,0);self.assertIn('three or four',refused.stderr)
                for mode in ('build_fields','verify_fields'):
                    refused=call(mode,spec,failure='direct');self.assertNotEqual(refused.returncode,0)
                    self.assertIn('fields and tracking workbench unsupported',refused.stderr)

    def assert_geometry_plan(self, geometry, count):
        root=Path('C:/ip_mr_geometry_test')
        plan=plan_geometry_build(geometry,run_directory=root,seed_record=file_record(structural_seed_path(count)),
                                 native_path_resource=root/'native_run_path.lua')
        self.assertEqual([row['operation_id'] for row in plan.operations],
                         ['geometry_'+name for name in geometry.frontend_gems]+['build_geometry','verify_geometry'])
        self.assertTrue(all('fly' not in row['arguments'] and 'refine' not in row['arguments'] for row in plan.operations))
        spec=plan.materializations[str(root/'inputs/geometry_iob.lua')]
        self.assertIn('ip_mr_geometry_iob_build',spec)
        for name in geometry.frontend_gems: self.assertIn('role='+json.dumps(name),spec)
        broken=copy.deepcopy(geometry)
        broken.frontend_geometry['asset_components'][next(iter(geometry.frontend_gems))]='unknown'
        with self.assertRaisesRegex(ValueError,'asset roles'):
            plan_geometry_build(broken,run_directory=root,seed_record=file_record(structural_seed_path(count)),
                                native_path_resource=root/'native_run_path.lua')

    def test_bare_rf_ip_mr_geometry_uses_complete_selected_sources(self):
        fixture=json.loads((Path(__file__).parent/'test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        example=json.loads(files('msplatform').joinpath('examples/rf_oatof_functional_v1.json').read_text(encoding='utf8'))
        rf=resolve_component(example['component_requests']['multipole'])
        self.assertEqual(rf.assembly_interface['ports']['mechanical_exit']['center_mm'][2],79.6)
        components={name:resolve_component(request) for name,request in fixture['component_requests'].items()}
        components['multipole']=rf;recipe=copy.deepcopy(fixture['recipe'])
        recipe['instances'].insert(0,dict(instance_id='multipole',project_id='rf_multipole_ion_optics',transform=dict(
            schema_version=1,role='rigid_transform',from_frame_id=rf.assembly_interface['local_frame_id'],
            to_frame_id=recipe['assembly_frame_id'],rotation=[[0,-1,0],[0,0,1],[-1,0,0]],translation_mm=[0,-305.6,3])))
        recipe['connections'].insert(0,dict(connection_id='rf_to_ip',upstream=dict(instance_id='multipole',port_id='mechanical_exit'),
            downstream=dict(instance_id='ion_processor',port_id='guide_inlet'),gap_mm=1.,coupling_mode='monolithic_joint_solve'))
        before=copy.deepcopy((recipe,components,example));assembly=assemble(recipe,components)
        def domain(lo,hi):
            return dict(cell_mm_xyz=dict.fromkeys('xyz',.1),pa_bounds_mm={a+s:(lo if s=='_min' else hi) for a in 'xyz' for s in ('_min','_max')})
        numerics={'domains':{'ip':domain(-10.,220.),'analyzer':domain(-1000.,1000.),
                             'detector':domain(-1000.,1000.),'multipole':{'cell_mm_xyz':dict.fromkeys('xyz',.1)}}}
        result=compile_geometry(assembly,numerics=numerics);meta=result.frontend_geometry
        self.assert_geometry_plan(result,4)
        canonical=assembly_geometry_members(dict(composition_plan=assembly.composition_plan,
            components_resolved=assembly.components_resolved,components_source=assembly.components_source))
        self.assertEqual(set(result.frontend_gems),{'multipole','ion_processor','mrtof_analyzer','mrtof_detector'})
        for name,count in (('multipole',32),('ion_processor',15),('mrtof',24)):
            self.assertEqual(sum(x['instance_id']==name for x in canonical),count)
        self.assertEqual(meta['physical_members']['multipole'],[x for x in canonical if x['instance_id']=='multipole'])
        self.assertEqual(meta['asset_poses']['multipole'],recipe['instances'][0]['transform'])
        self.assertEqual(meta['asset_components'],{'multipole':'multipole','ion_processor':'ion_processor',
                                                   'mrtof_analyzer':'mrtof','mrtof_detector':'mrtof'})
        for name in components:
            identity=result.provider_content_identities[name]
            self.assertEqual(identity['source_content_sha256'],_content_sha256(components[name].source_design))
            self.assertEqual(identity['resolved_content_sha256'],_content_sha256(components[name].resolved_design))
        self.assertEqual(set(meta['electrode_bindings']['multipole']),{row['electrode_group_id'] for row in rf.assembly_interface['component_electrodes']})
        self.assertEqual(meta['field_status'],'not_solved');self.assertEqual((recipe,components,example),before)
        wrong=copy.deepcopy(recipe);wrong['connections'][0]['upstream']['port_id']='mechanical_entrance'
        with self.assertRaises(ValueError): assemble(wrong,components)
        missing=copy.deepcopy(numerics);del missing['domains']['multipole']
        with self.assertRaises(ValueError):compile_complete_mr_geometry(assembly,numerics=missing)
        bad=copy.deepcopy(numerics);bad['electrode_group_native_ids']={'multipole':{}}
        with self.assertRaises(ValueError):compile_complete_mr_geometry(assembly,numerics=bad)

    def test_polygon_witness_respects_holes_edges_and_other_members(self):
        domain={'instance_origin_mm':dict.fromkeys('xyz',-5.),'cell_mm_xyz':dict.fromkeys('xyz',1.),
                'dimensions':dict.fromkeys(('nx','ny','nz'),11)}
        polygon=[[0,0],[4,0],[4,4],[0,4]]
        solid={'x':[-3,3],'polygon_yz_mm':polygon,'holes':[{'x':[-1,1],'polygon_yz_mm':polygon}]}
        gu=_polygon_mirror_witness(solid,domain,[],0)
        self.assertEqual(gu,[3,7,7])
        full=copy.deepcopy(solid);full['holes'][0]['x']=[-3,3]
        self.assertIsNone(_polygon_mirror_witness(full,domain,[],0))
        edge=copy.deepcopy(solid);edge['polygon_yz_mm']=[[0,0],[.2,0],[.2,.2],[0,.2]];edge['holes']=[]
        self.assertIsNone(_polygon_mirror_witness(edge,domain,[],0))
        other=[{'family':'prism','index':0,'bounds_mm':[-5,-5,-5,5,5,5]}]
        self.assertIsNone(_polygon_mirror_witness(solid,domain,other,0))

    def test_complete_ip_mr_selected_geometry(self):
        # Full component requests and recipe captured from the selected canonical
        # IP60/MR case; this fixture supplies inputs, not a second geometry formula.
        fixture=json.loads((Path(__file__).parent/'test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        recipe=fixture['recipe']; components={name:resolve_component(request) for name,request in fixture['component_requests'].items()}
        original=copy.deepcopy((recipe,components,fixture))
        assembly=assemble(recipe,components)
        def domain(lo,hi,pitch):
            return dict(cell_mm_xyz=dict.fromkeys('xyz',pitch),pa_bounds_mm={a+s: (lo if s=='_min' else hi)
                for a in 'xyz' for s in ('_min','_max')})
        numerics={'domains':{'ip':domain(-10.,220.,.1),'analyzer':domain(-1000.,1000.,.1),'detector':domain(-1000.,1000.,.1)}}
        geometry=compile_geometry(assembly,numerics=numerics); result=geometry.frontend_geometry
        self.assert_geometry_plan(geometry,3)
        self.assertEqual(result['role'],'simion_ip_mr_complete_geometry')
        self.assertEqual(len(result['physical_members']['ion_processor']),15)
        self.assertEqual(len(result['electrode_bindings']['ion_processor']),15)
        ip_interface=assembly.composition_plan['components']['ion_processor']['component_electrodes']
        self.assertEqual(result['electrode_group_roles']['ion_processor'],{row['electrode_group_id']:row['role'] for row in ip_interface})
        self.assertEqual(len(result['electrode_bindings']['mrtof']),22)
        mr_interface=assembly.composition_plan['components']['mrtof']['component_electrodes']
        self.assertEqual(set(result['electrode_bindings']['mrtof']),{row['electrode_group_id'] for row in mr_interface})
        self.assertEqual(result['electrode_group_roles']['mrtof'],{row['electrode_group_id']:row['role'] for row in mr_interface})
        closures=assembly.components_resolved['mrtof']['mirror_e_closures']
        self.assertEqual(len(closures),2)
        self.assertEqual(len([row for row in result['physical_members']['mrtof'] if row['family']=='mirror_e_closures']),2)
        canonical=assembly_geometry_members(dict(composition_plan=assembly.composition_plan,
            components_resolved=assembly.components_resolved,components_source=assembly.components_source))
        self.assertEqual(result['physical_members']['ion_processor'],
                         [row for row in canonical if row['instance_id']=='ion_processor'])
        self.assertEqual(sum(row['instance_id']=='mrtof' for row in canonical),24)
        self.assertEqual(result['asset_poses']['ion_processor'],recipe['instances'][0]['transform'])
        self.assertEqual(result['asset_poses']['mrtof_analyzer'],recipe['instances'][1]['transform'])
        self.assertEqual((recipe,components,fixture),original)
        self.assertEqual(result['source_status'],'not_requested'); self.assertEqual(result['field_status'],'not_solved')
        self.assertEqual(set(result['raw_physical_samples']),{'ion_processor','mrtof_analyzer','mrtof_detector'})
        self.assertEqual(len([row for row in result['raw_physical_samples']['ion_processor'] if row.get('metal')]),15)
        ip_names=list(result['electrode_bindings']['ion_processor'])
        mr_names=list(result['electrode_bindings']['mrtof'])
        permutation={'ion_processor':dict(zip(ip_names,reversed(range(1,len(ip_names)+1)),strict=True)),
                     'mrtof':dict(zip(mr_names,reversed(range(1,len(mr_names)+1)),strict=True))}
        remapped=compile_complete_mr_geometry(assembly,numerics={**numerics,'electrode_group_native_ids':permutation}).frontend_geometry
        self.assertEqual(remapped['electrode_bindings'],permutation)
        for asset,component in (('ion_processor','ion_processor'),('mrtof_analyzer','mrtof'),('mrtof_detector','mrtof')):
            old=result['raw_physical_samples'][asset]; new=remapped['raw_physical_samples'][asset]
            for a,b in zip(old,new,strict=True):
                self.assertEqual(a['gu'],b['gu'])
                if a.get('metal') is not False:
                    name=next(k for k,v in result['electrode_bindings'][component].items() if v==a['electrode_id'])
                    self.assertEqual(b['electrode_id'],permutation[component][name])
        modified=copy.deepcopy(components);modified['ion_processor']._source_design['baseline']['geometry']['lp_length_mm']=80
        with self.assertRaises(ValueError): assemble(recipe,modified)
        with self.assertRaises(ValueError): assemble(recipe,{'mrtof':components['mrtof']})
        mr_request=fixture['component_requests']['mrtof']; design=mr_request['design']
        oa=resolve_component(dict(provider_id='orthogonal_accelerator',geometry_profile_id=mr_request['geometry_profile_id'],
            design=dict(requirements=design['accelerator_requirements'],geometry_profile=design['geometry_profile'])))
        with self.assertRaises(ValueError): assemble(recipe,{**components,'extra_oa':oa})
        changed=copy.deepcopy(fixture['component_requests']['ion_processor'])
        changed['design']['baseline']['geometry']['lp_length_mm']=61
        other=dict(components,ion_processor=resolve_component(changed))
        other_geometry=compile_complete_mr_geometry(assemble(recipe,other),numerics=numerics)
        self.assertNotEqual(geometry.frontend_gems['ion_processor'],other_geometry.frontend_gems['ion_processor'])
        self.assertEqual(geometry.frontend_gems['mrtof_analyzer'],other_geometry.frontend_gems['mrtof_analyzer'])
        bad=copy.deepcopy(numerics);bad['domains']['ip']['pa_bounds_mm']['x_max']=100.
        with self.assertRaisesRegex(ValueError,'clips'): compile_complete_mr_geometry(assembly,numerics=bad)
        bad=copy.deepcopy(numerics);bad['electrode_group_native_ids']={'ion_processor':{}}
        with self.assertRaises(ValueError): compile_complete_mr_geometry(assembly,numerics=bad)
