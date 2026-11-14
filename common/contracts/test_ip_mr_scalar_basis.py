"""Pure explicit IP–MR stationary requests; no COMSOL or field qualification."""
import copy
import json
import unittest
from importlib.resources import files

from common.contracts import test_ip_mr_model as fixtures
from msplatform.assembly.model import Assembly
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.ip_mr_scalar_basis import project_ip_mr_scalar_basis
from msplatform.backends.simion.compiler import _content_sha256
from msplatform.backends.simion.artifacts import CompiledPreparedModel
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model, require_prepared_model
from msplatform.components.catalog import resolve_component

class IpMrScalarBasisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.RfIpMrModelTests.setUpClass()
        fixture=json.loads((fixtures.ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        parts={name:resolve_component(request) for name,request in fixture['component_requests'].items()}
        rf_request=json.loads(files('msplatform').joinpath('examples/rf_oatof_functional_v1.json').read_text(encoding='utf8'))['component_requests']['multipole']
        cls.cases=[]
        for cls_model, with_rf in ((fixtures.IpMrModelTests,False),(fixtures.RfIpMrModelTests,True)):
            selected=dict(parts)
            if with_rf: selected['multipole']=resolve_component(rf_request)
            geometry=cls_model.compiled;assembly=Assembly(geometry.frontend_geometry['composition_plan'],selected)
            model=compile_prepared_model(geometry,geometry.components_resolved,drive=cls_model.drive,physics=RF_IP_PHYSICS)
            snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,
                          components_source=assembly.components_source)
            projection=project_assembly_geometry(snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
            cls.cases.append((assembly,model,projection))
        cls.operator=dict(relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},
                          mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})

    def test_exact_group_vectors_and_immutability(self):
        for assembly,model,projection in self.cases:
            before=copy.deepcopy((assembly,model.document,projection,self.operator))
            result=project_ip_mr_scalar_basis(model,assembly=assembly,projection=projection,operator=self.operator)
            rows=require_prepared_model(model)['native_drive_rows']; groups=projection['electrode_groups']
            keys=[(row['instance_id'],row['electrode_group_id']) for row in groups]
            self.assertEqual(len(result['ip_unit_volt']),15)
            self.assertEqual(len(keys),45 if 'multipole' in assembly.components else 37)
            self.assertEqual(result['status'],'not_solved_not_qualified')
            carrier={(r['instance_id'],r['electrode_group_id']):r['voltage_v'] for r in result['carrier']['group_voltages']}
            by={(r['instance_id'],r['electrode_group_id']):r for r in rows}
            for key in keys:
                row=by[key]
                expected=0. if row['kind']=='ip_schedule' else row['voltage_v'] if row['kind']=='static' else row['common_mode_v']+row['dc_v']
                self.assertEqual(carrier[key],expected)
            for basis in result['ip_unit_volt']:
                vector={(r['instance_id'],r['electrode_group_id']):r['voltage_v'] for r in basis['request']['group_voltages']}
                self.assertEqual({k for k,v in vector.items() if v!=0},{(basis['instance_id'],basis['electrode_group_id'])})
                self.assertEqual(vector[(basis['instance_id'],basis['electrode_group_id'])],1.)
                self.assertEqual(basis['coefficient'],'model_drive.evaluate_at.voltage_v')
            if 'multipole' in assembly.components:
                rf=result['rf_reference'];vector={(r['instance_id'],r['electrode_group_id']):r['voltage_v'] for r in rf['request']['group_voltages']}
                for key,row in by.items():
                    self.assertEqual(vector[key],row['polarity']*row['rf_amplitude_v'] if row['kind']=='rf' else 0.)
            else:self.assertIsNone(result['rf_reference'])
            self.assertEqual((assembly,model.document,projection,self.operator),before)

    def test_mismatched_geometry_source_clock_and_operator_refuse(self):
        assembly,model,projection=self.cases[-1]
        wrong=copy.deepcopy(projection);wrong['members'][0]['member_id']+='tampered'
        with self.assertRaises(ValueError):project_ip_mr_scalar_basis(model,assembly=assembly,projection=wrong,operator=self.operator)
        snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,
                      components_source=assembly.components_source)
        outer=copy.deepcopy(projection['outer_box_mm']);outer['max'][0]+=1
        alternate=project_assembly_geometry(snapshot,outer_box_mm=outer)
        self.assertEqual(len(project_ip_mr_scalar_basis(model,assembly=assembly,projection=alternate,operator=self.operator)['ip_unit_volt']),15)
        for change in ('clock','source','rf'):
            doc=copy.deepcopy(model.document);doc.pop('model_identity_sha256')
            if change=='clock':doc['drive']['ip_schedule']['clock']['authority_sha256']='0'*64
            elif change=='source':doc['geometry']['provider_content_identities']['ion_processor']['source_content_sha256']='0'*64
            else:next(r for r in doc['native_drive_rows'] if r['kind']=='rf')['phase_rad']+=.1
            doc['model_identity_sha256']=_content_sha256(doc)
            forged=CompiledPreparedModel(json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False))
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):
                project_ip_mr_scalar_basis(forged,assembly=assembly,projection=projection,operator=self.operator)
        for mutate in (lambda x:x['mesh'].__setitem__('electrode_hmax_mm',float('nan')),
                       lambda x:x['exterior'].__setitem__('voltage_v',1.)):
            bad=copy.deepcopy(self.operator);mutate(bad)
            with self.assertRaises(ValueError):project_ip_mr_scalar_basis(model,assembly=assembly,projection=projection,operator=bad)
