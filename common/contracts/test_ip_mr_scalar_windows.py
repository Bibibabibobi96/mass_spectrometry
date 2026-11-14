"""Shared ordered scalar windows: finite software contract only."""
import copy
import unittest
from msplatform.backends.simion.scalar_sample_binding import attach_refinement_windows


def level(tag):
    return dict(field_solution_reference={'manifest':{'bytes':3,'sha256':tag}},
                grid={'origin_mm':[-2.,-2.,-2.], 'pitch_mm':[1.,1.,1.], 'dimensions':[7,7,7]}, records={})


class ScalarWindowTests(unittest.TestCase):
    def test_seventeen_levels_preserve_order_and_source(self):
        keys=['carrier',*['ip_'+str(n) for n in range(1,16)],'rf_reference']
        bases={key:level(key) for key in keys}
        windows=[dict(name=name,active_box_mm=[[0.,.5]]*3,samples=name) for name in ('fine_a','fine_b')]
        def admit(name):return {'bases':{key:dict(level(key),marker=name) for key in keys}}
        attach_refinement_windows(bases,windows,admit_level=admit)
        for base in bases.values():
            self.assertEqual([w['name'] for w in base['refinement_windows']],['fine_a','fine_b'])
            self.assertEqual([w['marker'] for w in base['refinement_windows']],['fine_a','fine_b'])

    def test_bad_coverage_source_halo_and_intervals_refused(self):
        base={'carrier':level('source'),'ip_1':level('ip')}
        window=dict(name='fine',active_box_mm=[[0.,.5]]*3,samples='x')
        def check(w, levels, message):
            with self.assertRaisesRegex(ValueError,message):
                attach_refinement_windows(copy.deepcopy(base),[w],admit_level=lambda _: {'bases':levels})
        check(window,{'carrier':level('source')},'basis coverage')
        check(window,{'carrier':level('wrong'),'ip_1':level('ip')},'source workpoint')
        bad=copy.deepcopy(window);bad['active_box_mm'][0]=[-2.,-1.]
        check(bad,copy.deepcopy(base),'support halo')
        bad=copy.deepcopy(window);bad['active_box_mm'][0]=[0.,0.]
        check(bad,copy.deepcopy(base),'ordered intervals')
        with self.assertRaisesRegex(ValueError,'unique'):
            attach_refinement_windows(copy.deepcopy(base),[window,window],admit_level=lambda _: {'bases':copy.deepcopy(base)})

    def test_actual_joint_published_refinement(self):
        from common.contracts import test_ip_mr_scalar_binding as joint
        import json
        from msplatform.backends.simion.standalone_pa_composition import PaHeader
        from msplatform.results.artifacts import open_artifact
        from msplatform.backends.simion.ip_mr_scalar_binding import resolve_ip_mr_scalar_basis
        joint.IpMrScalarAdmissionTests.setUpClass()
        case=joint.IpMrScalarAdmissionTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        def sample_level(name, ref):
            item=open_artifact(ref,expected_kind='scalar_field_samples');data={}
            for key in item.data_records:
                if key=='field_solution_manifest':continue
                path=item.data_path(key)
                data[key]=path.read_bytes() if key in ('field_v','field_valid') else json.loads(path.read_text(encoding='utf8'))
            grid=data['grid'];grid.update(origin_mm=[-2.,-2.,-2.],pitch_mm=[1.,1.,1.],dimensions=[7,7,7],point_count=343,maximum_mm=[4.,4.,4.])
            data['report'].update(grid);data['report']['fem_valid']=343;data['report']['invalid_count']=0
            pa=PaHeader(-2,1,10000.,7,7,7,1<<28,1.,1.,1.).pack()+bytes(343*8)
            data['field_v']=pa;data['field_valid']=pa
            manifest=json.loads(item.manifest_location.read_text(encoding='utf8'))
            return case.fixture.publish(name,'scalar_field_samples',data,item.metadata,
                linked={'field_solution_manifest':item.data_records['field_solution_manifest'],
                        'field_solution_model':manifest['inputs']['field_solution_model']})
        from importlib.resources import files
        from common.contracts import test_ip_mr_model as model_fixture
        from msplatform.assembly.factory import assemble
        from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
        from msplatform.backends.comsol.ip_mr_scalar_basis import project_ip_mr_scalar_basis
        from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
        from msplatform.components.catalog import resolve_component
        from pathlib import Path
        model_fixture.RfIpMrModelTests.setUpClass()
        fixture=json.loads((model_fixture.ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        example=json.loads(files('msplatform').joinpath('examples/rf_oatof_functional_v1.json').read_text(encoding='utf8'))
        parts={name:resolve_component(value) for name,value in fixture['component_requests'].items()}
        rf=resolve_component(example['component_requests']['multipole']);parts['multipole']=rf
        recipe=copy.deepcopy(fixture['recipe'])
        recipe['instances'].insert(0,dict(instance_id='multipole',project_id='rf_multipole_ion_optics',transform=dict(
            schema_version=1,role='rigid_transform',from_frame_id=rf.assembly_interface['local_frame_id'],
            to_frame_id=recipe['assembly_frame_id'],rotation=[[0,-1,0],[0,0,1],[-1,0,0]],translation_mm=[0,-305.6,3])))
        recipe['connections'].insert(0,dict(connection_id='rf_to_ip',upstream=dict(instance_id='multipole',port_id='mechanical_exit'),
            downstream=dict(instance_id='ion_processor',port_id='guide_inlet'),gap_mm=1.,coupling_mode='monolithic_joint_solve'))
        assembly=assemble(recipe,parts);compiled=model_fixture.RfIpMrModelTests.compiled
        model=compile_prepared_model(compiled,compiled.components_resolved,drive=model_fixture.RfIpMrModelTests.drive,physics=RF_IP_PHYSICS)
        case.fixture.snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
        case.fixture.projection=project_assembly_geometry(case.fixture.snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
        case.fixture.root=Path(case.temp.name)/'full';case.fixture.root.mkdir()
        geometry=case.fixture.make_geometry()
        plan=project_ip_mr_scalar_basis(model,assembly=assembly,projection=case.fixture.projection,operator=case.operator)
        requests={'carrier':plan['carrier'],'rf_reference':plan['rf_reference']['request']}
        requests.update({'ip_'+str(row['schedule_index']):row['request'] for row in plan['ip_unit_volt']})
        samples={name:case.sample(name,request) for name,request in requests.items()}
        levels={name:sample_level('window-'+name,ref) for name,ref in samples.items()}
        windows=[dict(name='first',active_box_mm=[[0.,.5]]*3,samples=levels),
                 dict(name='second',active_box_mm=[[0.,.5]]*3,samples=levels)]
        def resolve(ws):
            return resolve_ip_mr_scalar_basis(model=model,assembly=assembly,geometry_artifact=geometry,
                operator=case.operator,samples=samples,refinement_windows=ws)
        result=resolve(windows)
        self.assertEqual(len(result['bases']),17)
        for item in result['bases'].values():
            self.assertEqual([x['name'] for x in item['refinement_windows']],['first','second'])
        bad=copy.deepcopy(windows);bad[0]['samples'].pop('rf_reference')
        with self.assertRaisesRegex(ValueError,'complete explicit'): resolve(bad)
        bad=copy.deepcopy(windows);bad[0]['samples']['ip_1']=bad[0]['samples']['ip_2']
        with self.assertRaises(ValueError): resolve(bad)
        bad=copy.deepcopy(windows);bad[0]['active_box_mm'][0]=[-2.,-1.]
        with self.assertRaisesRegex(ValueError,'support halo'): resolve(bad)
        bad=copy.deepcopy(windows);bad[1]['name']='first'
        with self.assertRaisesRegex(ValueError,'unique'): resolve(bad)
        mask=open_artifact(levels['carrier'],expected_kind='scalar_field_samples').data_path('field_valid')
        original=mask.read_bytes()
        try:
            mask.write_bytes(original[:-1]+bytes([original[-1]^1]))
            with self.assertRaisesRegex(AssertionError, 'field_valid SHA-256 changed'): resolve(windows)
        finally: mask.write_bytes(original)
