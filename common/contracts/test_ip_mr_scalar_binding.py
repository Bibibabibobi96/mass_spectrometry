"""Published joint scalar admission; synthetic artifacts, no native or qualification."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts import test_ip_mr_model as model_fixture
from common.contracts import test_sfi_scalar_binding as scalar_fixture
from msplatform.assembly.factory import assemble
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.ip_mr_scalar_basis import project_ip_mr_scalar_basis
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
from msplatform.backends.simion.ip_mr_scalar_binding import resolve_ip_mr_scalar_basis
from msplatform.components.catalog import resolve_component
from msplatform.results.artifacts import open_artifact


class IpMrScalarAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_fixture.IpMrModelTests.setUpClass()
        fixture=json.loads((model_fixture.ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        cls.assembly=assemble(fixture['recipe'],{name:resolve_component(req) for name,req in fixture['component_requests'].items()})
        compiled=model_fixture.IpMrModelTests.compiled
        cls.model=compile_prepared_model(compiled,compiled.components_resolved,drive=model_fixture.IpMrModelTests.drive,physics=RF_IP_PHYSICS)
        cls.snapshot=dict(composition_plan=cls.assembly.composition_plan,components_resolved=cls.assembly.components_resolved,components_source=cls.assembly.components_source)
        cls.projection=project_assembly_geometry(cls.snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
        cls.operator=dict(relative_permittivity=1., exterior={'kind':'potential','voltage_v':0.},
                          mesh={'global_automatic_level':9,'electrode_hmax_mm':5.}, study={'kind':'stationary'})
        cls.plan=project_ip_mr_scalar_basis(cls.model,assembly=cls.assembly,projection=cls.projection,operator=cls.operator)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        # Reuse the existing real manifest publisher and report fixture without inheriting its test class.
        self.fixture=scalar_fixture.SfiScalarAdmissionTests(methodName='runTest')
        self.fixture.root=Path(self.temp.name);self.fixture.projection=self.projection;self.fixture.snapshot=self.snapshot
        self.geometry_ref=self.fixture.make_geometry()
        self.requests={'carrier':self.plan['carrier']}
        self.requests.update({'ip_'+str(row['schedule_index']):row['request'] for row in self.plan['ip_unit_volt']})
        self.samples={name:self.sample(name,request) for name,request in self.requests.items()}

    def sample(self,name,request):
        # The inherited fixture constructs valid solved/sample manifests; all vectors have zero exterior.
        self.fixture.vectors={name:{(r['instance_id'],r['electrode_group_id']):r['voltage_v'] for r in request['group_voltages']}}
        # Its carrier convention is 7 V; an arbitrary non-carrier label selects zero exterior and one grid.
        label='basis_'+name
        self.fixture.vectors[label]=self.fixture.vectors.pop(name)
        return self.fixture.make_sample(label)

    def resolve(self,samples=None):
        return resolve_ip_mr_scalar_basis(model=self.model,assembly=self.assembly,geometry_artifact=self.geometry_ref,
                                         operator=self.operator,samples=self.samples if samples is None else samples)

    def test_all_sixteen_public_products_and_no_mutation(self):
        before=copy.deepcopy(self.samples);result=self.resolve()
        self.assertEqual(len(result['bases']),16);self.assertEqual(self.samples,before)
        self.assertEqual(result['model_identity_sha256'],self.model.document['model_identity_sha256'])
        self.assertEqual(result['ip_groups'],[{k:r[k] for k in ('instance_id','electrode_group_id','schedule_index','coefficient')} for r in self.plan['ip_unit_volt']])
        self.assertIsNone(result['rf'])
        self.assertEqual(result['scope'],'identity_admission_only_not_coverage_or_qualification')

    def test_full_rf_ip_mr_seventeen_products(self):
        from importlib.resources import files
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
        self.fixture.snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
        self.fixture.projection=project_assembly_geometry(self.fixture.snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
        # Distinct owner directories in this same private fixture.
        self.fixture.root=Path(self.temp.name)/'full';self.fixture.root.mkdir()
        geometry=self.fixture.make_geometry()
        plan=project_ip_mr_scalar_basis(model,assembly=assembly,projection=self.fixture.projection,operator=self.operator)
        requests={'carrier':plan['carrier'],'rf_reference':plan['rf_reference']['request']}
        requests.update({'ip_'+str(row['schedule_index']):row['request'] for row in plan['ip_unit_volt']})
        samples={name:self.sample(name,request) for name,request in requests.items()}
        result=resolve_ip_mr_scalar_basis(model=model,assembly=assembly,geometry_artifact=geometry,operator=self.operator,samples=samples)
        self.assertEqual(len(result['bases']),17)
        self.assertEqual(result['rf'],{k:v for k,v in plan['rf_reference'].items() if k!='request'})
        self.assertEqual(result['ip_groups'],[{k:r[k] for k in ('instance_id','electrode_group_id','schedule_index','coefficient')} for r in plan['ip_unit_volt']])
        missing=dict(samples);del missing['rf_reference']
        with self.assertRaisesRegex(ValueError,'complete explicit'):
            resolve_ip_mr_scalar_basis(model=model,assembly=assembly,geometry_artifact=geometry,operator=self.operator,samples=missing)
    def test_changed_operator_clock_and_each_pa_header_rejected(self):
        changed=copy.deepcopy(self.operator);changed['mesh']['electrode_hmax_mm']=4.
        with self.assertRaisesRegex(ValueError,'workpoint'):
            resolve_ip_mr_scalar_basis(model=self.model,assembly=self.assembly,geometry_artifact=self.geometry_ref,operator=changed,samples=self.samples)
        other=copy.deepcopy(self.model.document);other['drive']['clock']['authority_sha256']='0'*64
        from msplatform.backends.simion.artifacts import CompiledPreparedModel
        with self.assertRaises(ValueError):
            resolve_ip_mr_scalar_basis(model=CompiledPreparedModel(json.dumps(other)),assembly=self.assembly,geometry_artifact=self.geometry_ref,operator=self.operator,samples=self.samples)
        item=open_artifact(self.samples['carrier'],expected_kind='scalar_field_samples')
        for key in ('field_v','field_valid'):
            with self.subTest(bad_header=key):
                data={}
                for name in item.data_records:
                    if name=='field_solution_manifest': continue
                    path=item.data_path(name)
                    data[name]=path.read_bytes() if name in ('field_v','field_valid') else json.loads(path.read_text(encoding='utf8'))
                # Header dimensions differ while the new product manifest is valid.
                raw=bytearray(data[key]);raw[16:20]=(4).to_bytes(4,'little',signed=True);data[key]=bytes(raw)
                ref=self.fixture.publish('bad-'+key,'scalar_field_samples',data,item.metadata,
                    linked={'field_solution_manifest':item.data_records['field_solution_manifest'],
                            'field_solution_model':json.loads(item.manifest_location.read_text(encoding='utf8'))['inputs']['field_solution_model']})
                bad=dict(self.samples,carrier=ref)
                with self.assertRaises((ValueError,AssertionError)):self.resolve(bad)
    def test_missing_swapped_and_tampered_products_rejected(self):
        missing=dict(self.samples);missing.pop('ip_1')
        with self.assertRaisesRegex(ValueError,'complete explicit'):self.resolve(missing)
        item=open_artifact(self.samples['ip_1'],expected_kind='scalar_field_samples')
        data={}
        for name in item.data_records:
            if name=='field_solution_manifest': continue
            source=item.data_path(name)
            data[name]=source.read_bytes() if name in ('field_v','field_valid') else json.loads(source.read_text(encoding='utf8'))
        for name in ('grid','report'):
            data[name]['origin_mm'][0]+=1.
            data[name]['maximum_mm'][0]+=1.
        manifest=json.loads(item.manifest_location.read_text(encoding='utf8'))
        moved=self.fixture.publish('different-grid','scalar_field_samples',data,item.metadata,
            linked={'field_solution_manifest':item.data_records['field_solution_manifest'],
                    'field_solution_model':manifest['inputs']['field_solution_model']})
        with self.assertRaisesRegex(ValueError,'grids differ'):
            self.resolve(dict(self.samples,ip_1=moved))
        swapped=dict(self.samples);swapped['ip_1'],swapped['ip_2']=swapped['ip_2'],swapped['ip_1']
        with self.assertRaisesRegex(ValueError,'workpoint'):self.resolve(swapped)
        path=Path(self.samples['carrier']['manifest']['path']);old=path.read_bytes()
        try:
            path.write_bytes(old+b' ')
            with self.assertRaises((AssertionError,ValueError)):self.resolve()
        finally:path.write_bytes(old)
