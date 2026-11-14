"""Pure complete IP–MR model: no common field, native operations or flight."""
import copy
import json
import unittest
from pathlib import Path

from msplatform.assembly.factory import assemble
from msplatform.backends.simion.mr_compiler import compile_complete_mr_geometry
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model, model_geometry, require_prepared_model
from msplatform.components.catalog import resolve_component
from msplatform.io.file_identity import file_sha256

ROOT=Path(__file__).resolve().parents[2]


def domain(lo, hi, pitch):
    return dict(cell_mm_xyz=dict.fromkeys('xyz',pitch),pa_bounds_mm={a+s:(lo if s=='_min' else hi)
        for a in 'xyz' for s in ('_min','_max')})


class IpMrModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=json.loads((ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        parts={name:resolve_component(value) for name,value in fixture['component_requests'].items()}
        assembly=assemble(fixture['recipe'],parts)
        cls.compiled=compile_complete_mr_geometry(assembly,numerics={'domains':{
            'ip':domain(-10.,220.,.1),'analyzer':domain(-1000.,1000.,.1),'detector':domain(-1000.,1000.,.1)}})
        identity=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256=file_sha256(ROOT/'src/msplatform/examples/instrument_epoch_v1.json'))
        point=json.loads((ROOT/'projects/dual_pressure_rectilinear_ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
        cls.drive=dict(clock=dict(identity,phase_reference_instrument_time_us=0.),
            ip_schedule=dict(baseline=assembly.components_source['ion_processor']['baseline'],native_operating_point=point,clock=identity),
            mr_authority=dict(source=dict(analyzer_electrode_voltages_v=list(range(1,21))),
                candidate=dict(s1=31.,s2=32.,p1=41.,p2=42.),mirror_voltages_v=[11.,12.,13.,14.,15.],
                detector_voltage_v=50.,mirror_shield_voltages_v=dict(positive_mirror_ground_shield=51.,negative_mirror_ground_shield=52.)))

    def model(self,geometry=None,drive=None,physics=None):
        geometry=self.compiled if geometry is None else geometry
        return compile_prepared_model(geometry,geometry.components_resolved,drive=self.drive if drive is None else drive,
                                      physics=RF_IP_PHYSICS if physics is None else physics)

    def test_complete_selected_geometry_and_explicit_authorities(self):
        before=copy.deepcopy((self.compiled,self.drive));doc=require_prepared_model(self.model())
        self.assertEqual((doc['source_status'],doc['field_status']),('not_requested','not_solved'))
        self.assertEqual(doc['physics'],RF_IP_PHYSICS)
        self.assertNotIn('pulse',doc['drive']);self.assertNotIn('groups',doc['drive'])
        rows=doc['native_drive_rows'];self.assertEqual(len(rows),37)
        self.assertEqual(sum(row['kind']=='ip_schedule' for row in rows),15)
        self.assertEqual(sum(row['kind']=='static' for row in rows),22)
        self.assertEqual(len({(r['native_targets'][0]['domain'],r['native_targets'][0]['electrode_id']) for r in rows}),37)
        detector=next(r for r in rows if r['electrode_group_id']=='detector')
        self.assertEqual(detector['native_targets'][0]['domain'],'mrtof_detector')
        self.assertEqual(detector['voltage_v'],50.)
        self.assertEqual((self.compiled,self.drive),before)
        with self.assertRaisesRegex(ValueError,'IP–MR continuous tracking is not supported'):
            model_geometry(self.model(),downstream_drive=True)

    def test_rejects_missing_clock_policy_and_mutated_authorities(self):
        for name in ('clock','ip_clock','source','detector','shield','boundary','pulse'):
            with self.subTest(case=name):
                drive=copy.deepcopy(self.drive);physics=copy.deepcopy(RF_IP_PHYSICS)
                if name=='clock': drive['clock']['phase_reference_instrument_time_us']=1.
                elif name=='ip_clock': drive['ip_schedule']['clock']['authority_sha256']='0'*64
                elif name=='source': drive['ip_schedule']['baseline']['geometry']['lp_length_mm']=80.
                elif name=='detector': del drive['mr_authority']['detector_voltage_v']
                elif name=='shield': del drive['mr_authority']['mirror_shield_voltages_v']['positive_mirror_ground_shield']
                elif name=='boundary': physics['boundary_policy']='native_zero_neumann'
                else: drive['pulse']={'mode':'held_off'}
                with self.assertRaises((ValueError,TypeError)):self.model(drive=drive,physics=physics)

    def test_rejects_changed_pose_roles_and_duplicate_targets(self):
        for case in ('pose','roles','duplicate','missing','resolved'):
            with self.subTest(case=case):
                geometry=copy.deepcopy(self.compiled);g=geometry.frontend_geometry
                if case=='pose':g['asset_poses']['ion_processor']['translation_mm'][0]+=1.
                elif case=='roles':g['electrode_group_roles']['mrtof']['detector']='mirror'
                elif case=='duplicate':
                    names=[key for key,role in g['electrode_group_roles']['mrtof'].items() if role!='detector']
                    g['electrode_bindings']['mrtof'][names[0]]=g['electrode_bindings']['mrtof'][names[1]]
                elif case=='missing':del g['electrode_bindings']['ion_processor'][next(iter(g['electrode_bindings']['ion_processor']))]
                else:geometry.components_resolved['ion_processor']['projection']['electrodes'][0]['name']='changed'
                with self.assertRaises((ValueError,KeyError)):self.model(geometry=geometry)


class RfIpMrModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from importlib.resources import files
        from msplatform.backends.simion.model import scientific_multipole_drive
        IpMrModelTests.setUpClass()
        fixture=json.loads((ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        example=json.loads(files('msplatform').joinpath('examples/rf_oatof_functional_v1.json').read_text(encoding='utf8'))
        components={name:resolve_component(value) for name,value in fixture['component_requests'].items()}
        rf=resolve_component(example['component_requests']['multipole']);components['multipole']=rf
        recipe=copy.deepcopy(fixture['recipe'])
        recipe['instances'].insert(0,dict(instance_id='multipole',project_id='rf_multipole_ion_optics',transform=dict(
            schema_version=1,role='rigid_transform',from_frame_id=rf.assembly_interface['local_frame_id'],
            to_frame_id=recipe['assembly_frame_id'],rotation=[[0,-1,0],[0,0,1],[-1,0,0]],translation_mm=[0,-305.6,3])))
        recipe['connections'].insert(0,dict(connection_id='rf_to_ip',upstream=dict(instance_id='multipole',port_id='mechanical_exit'),
            downstream=dict(instance_id='ion_processor',port_id='guide_inlet'),gap_mm=1.,coupling_mode='monolithic_joint_solve'))
        assembly=assemble(recipe,components)
        cls.compiled=compile_complete_mr_geometry(assembly,numerics={'domains':{
            'ip':domain(-10.,220.,.1),'analyzer':domain(-1000.,1000.,.1),'detector':domain(-1000.,1000.,.1),
            'multipole':{'cell_mm_xyz':dict.fromkeys('xyz',.1)}}})
        cls.drive=copy.deepcopy(IpMrModelTests.drive)
        cls.drive['groups']={'multipole':scientific_multipole_drive(cls.compiled.components_resolved['multipole'],
            cls.compiled.frontend_geometry['electrode_bindings']['multipole'])}

    def test_full_rf_ip_mr_is_unsolved_and_retains_groups(self):
        before=copy.deepcopy((self.compiled,self.drive))
        result=require_prepared_model(compile_prepared_model(self.compiled,self.compiled.components_resolved,
            drive=self.drive,physics=RF_IP_PHYSICS))
        rows=result['native_drive_rows'];rf=[r for r in rows if r['instance_id']=='multipole']
        self.assertEqual(len(rows),37+len(self.drive['groups']['multipole']))
        self.assertEqual({r['electrode_group_id'] for r in rf},set(self.drive['groups']['multipole']))
        self.assertTrue(all(r['native_targets'][0]['domain']=='multipole' for r in rf))
        self.assertEqual(result['drive']['groups'],self.drive['groups'])
        self.assertEqual((result['field_status'],result['source_status']),('not_solved','not_requested'))
        self.assertEqual((self.compiled,self.drive),before)

    def test_rf_drive_and_source_mismatches_are_refused(self):
        for case in ('missing','changed','clock','source'):
            with self.subTest(case=case):
                drive=copy.deepcopy(self.drive);geometry=copy.deepcopy(self.compiled)
                if case=='missing': del drive['groups']
                elif case=='changed':
                    key=next(k for k,v in drive['groups']['multipole'].items() if v['kind']=='rf')
                    drive['groups']['multipole'][key]['rf_amplitude_v']+=1
                elif case=='clock': drive['clock']['authority_sha256']='0'*64
                else: geometry.provider_content_identities['multipole']['resolved_content_sha256']='0'*64
                with self.assertRaises((ValueError,TypeError,KeyError)):
                    compile_prepared_model(geometry,geometry.components_resolved,drive=drive,physics=RF_IP_PHYSICS)


    def test_tracking_refuses_before_source_or_field_inputs(self):
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        model=compile_prepared_model(self.compiled,self.compiled.components_resolved,
            drive=self.drive,physics=RF_IP_PHYSICS)
        with self.assertRaisesRegex(ValueError,'IP–MR tracking requires an implemented common-field binding'):
            plan_tracking_execution(model,particles=None,clock_records=None,propagation=None,
                observations=None,numerics=None)

    def test_saved_models_recompile_with_identical_rows_and_identity(self):
        for fixture in (IpMrModelTests, RfIpMrModelTests):
            with self.subTest(components=len(fixture.compiled.components_resolved)):
                original=compile_prepared_model(fixture.compiled,fixture.compiled.components_resolved,
                    drive=fixture.drive,physics=RF_IP_PHYSICS)
                saved=require_prepared_model(original)
                restored=model_geometry(original)
                drive=copy.deepcopy(saved['drive'])
                drive['ip_schedule'].pop('native_timing')
                rebuilt=compile_prepared_model(restored,restored.components_resolved,
                    drive=drive,physics=saved['physics'])
                self.assertEqual(require_prepared_model(rebuilt),saved)
