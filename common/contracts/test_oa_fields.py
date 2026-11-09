"""Independent OA field closure from actual canonical model producers; software only."""
from pathlib import Path
import copy
import inspect
import json
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.test_simion_model_execution import (
    model_plan, _InertModelSession, _inert_small_materialization, _clock_authority_reference,
)
from msplatform.backends.simion import field_closure, field_execution, model_execution, rf_field_execution as family
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from common.contracts.test_simion_rf_fields import InertFieldSession, execute


def produced_model(root: Path, *, component_kind='oa', fractional_witness=None):
    """Use actual model materialization/metadata; never hand-label another geometry."""
    root.mkdir(parents=True)
    model, assets, seed, _ = model_plan(root, independent_oa=component_kind=='oa', independent_rf=component_kind=='rf')
    if fractional_witness is not None:
        for row in assets.values():
            path=Path(row['witness_record']['path'])
            path.write_text('0,0,0,'+str(fractional_witness)+',nil,nil\n',encoding='utf-8')
            row['witness_record']=file_record(path,'required_evidence')
    producer = root/'geometry-producer'
    producer.mkdir()
    compiled = producer/'compiled_geometry.json'
    compiled.write_text(json.dumps(model.document['geometry']), encoding='utf-8')
    records = {'compiled_geometry':file_record(compiled,'required_evidence')}
    bindings = {}
    for domain, row in assets.items():
        bindings[domain] = {}
        for label, record in [('raw_geometry',row['raw_record']),('fractional_surface',row['surface_records'][0]),
                              ('surface_witnesses',row['witness_record'])]:
            key=domain+'_'+label; records[key]=record; bindings[domain][label]=key
    manifest = dict(schema_version=2,role='simulation_run_manifest',run_id='inert-geometry',project='software_fixture',
        mode='inert_protocol',status='success',inputs={},outputs=list(records.values()),products=dict(geometry=dict(
            schema_version=1,kind='geometry_artifact',status='complete',data=records,
            metadata=dict(backend='simion',geometry_materialized=True,field_status='not_solved',source_status='not_requested',native_assets=bindings))))
    publish_terminal_state(producer,{'status':'success'},manifest)
    reference=dict(manifest=file_record(producer/'run_manifest.json'),product_id='geometry')
    session=_InertModelSession(root/'model-producer',producer)
    session.capacity_session['protected_paths'].append(str(root/'source'))
    with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(producer))):
        result=model_execution.execute_model(session,model=model,geometry_reference=reference,seed_record=seed,
            clock_authority_reference=_clock_authority_reference(root),limits={},materialize_geometry=_inert_small_materialization,
            materializer_record=file_record(Path(inspect.getsourcefile(_inert_small_materialization)),'required_evidence'))
    products=result['manifest_extra_fields']['products']
    model_manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-model',project='software_fixture',
        mode='actual_model_action_inert_transport',status='success',inputs={},
        outputs=list(products['model']['data'].values()),products=products)
    publish_terminal_state(session.artifact_run_dir,{'status':'success'},model_manifest)
    return open_artifact(dict(manifest=file_record(session.artifact_run_dir/'run_manifest.json'),product_id='model'),expected_kind='prepared_model')


def field_session(root, source, numerics, reuse=None):
    graph=field_execution.plan_fields_execution(source.model,numerics=numerics,reuse_fields_reference=reuse)
    session=InertFieldSession(root,Path(source.artifact.reference['manifest']['path']).parent,graph)
    geometry=source.model.document['geometry']['frontend_geometry']
    session.labels={name:sorted(values.values()) for name,values in geometry['electrode_bindings'].items()}
    return session


def publish_fields(session,result):
    product=result['manifest_extra_fields']['products']['fields']
    manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-field',project='software_fixture',
        mode='actual_field_action_inert_transport',status='success',inputs={},
        outputs=list(product['data'].values()),products={'fields':product})
    publish_terminal_state(session.artifact_run_dir,{'status':'success'},manifest)
    return dict(manifest=file_record(session.artifact_run_dir/'run_manifest.json'),product_id='fields')


def original_owner(record,**_options):
    return dict(run_directory=str(Path(record['path']).parent))


class OaFieldTests(unittest.TestCase):
    def test_actual_oa_model_product_keeps_complete_independent_fractional_domains(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact=produced_model(Path(directory)/'oa')
            source=field_closure.load_field_model(artifact)
            geometry=source.model.document['geometry']['frontend_geometry']
            self.assertEqual(geometry['role'],'simion_independent_oa_geometry')
            self.assertEqual(set(source.native_assets),{'two','three'})
            for asset in source.native_assets.values():
                self.assertEqual(set(asset),{'raw_record','surface_records','witness_record'})
            self.assertEqual(artifact.metadata['field_status'],'not_solved')
            self.assertEqual(artifact.metadata['source_status'],'not_requested')
            self.assertEqual(artifact.metadata['refine_calls'],0)
            self.assertEqual(artifact.metadata['fly_calls'],0)
            graph=field_execution.plan_fields_execution(source.model,numerics=dict(refine_policy='vendor_default'))
            self.assertEqual(graph['expected_operation_ids'],['materialize_geometry','refine_two','refine_three','audit_fields'])

    def test_actual_rf_and_oa_producers_refine_and_reuse_original_family_without_private_copy(self):
        for kind in ('oa','rf'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                source=field_closure.load_field_model(produced_model(root/'source',component_kind=kind))
                numerics=dict(refine_policy='vendor_default')
                first=field_session(root/'first',source,numerics)
                with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',side_effect=original_owner), \
                     patch('subprocess.Popen',side_effect=AssertionError('no native in inert protocol')):
                    result=execute(first,source,numerics)
                    reference=publish_fields(first,result)
                    original=open_artifact(reference,expected_kind='field_bundle')
                    original_records=copy.deepcopy(original.data_records)
                    expected='producer_owned_oa_fractional_family' if kind=='oa' else family.REPRESENTATION
                    self.assertEqual(original.metadata['field_representation'],expected)
                    self.assertEqual(original.metadata['refine_calls'],2)
                    self.assertEqual(original.metadata['fly_calls'],0)
                    self.assertEqual(original.metadata['sampled_particles'],0)
                    if kind=='oa':
                        self.assertEqual(original.metadata['component_kind'],'orthogonal_accelerator')
                        self.assertEqual(original.metadata['field_domain_coupling'],'independent_component_domains')
                        self.assertEqual(original.metadata['native_audit_format'],'legacy_shared_simion_rf_fractional_field_audit')
                    for index in (1,2):
                        current=field_session(root/('reuse'+str(index)),source,numerics,reference)
                        current.capacity_session['protected_paths'].append(str(first.artifact_run_dir))
                        if index==2:current.capacity_session['protected_paths'].append(str(root/'reuse1'))
                        result=execute(current,source,numerics,reference)
                        product=result['manifest_extra_fields']['products']['fields']
                        self.assertEqual([op for op,_ in current.requests],['audit_fields'])
                        self.assertFalse((current.run_dir/'simion/fields').exists())
                        self.assertEqual(product['metadata']['family_producer_reference'],original.reference)
                        self.assertEqual(product['metadata']['refine_calls'],0)
                        reference=publish_fields(current,result)
                    self.assertEqual(open_artifact(original.reference,expected_kind='field_bundle').data_records,original_records)

    def test_oa_field_plan_query_and_legacy_utility_resources_remain_source_free(self):
        from msplatform.capabilities import capabilities
        from msplatform.backends.simion.resources import native_resource_path
        with tempfile.TemporaryDirectory() as directory:
            source=field_closure.load_field_model(produced_model(Path(directory)/'source'))
            valid=dict(model=source.model,numerics=dict(refine_policy='explicit_convergence',convergence_v=dict(two=.001,three=.002)))
            accepted=capabilities(dict(schema_version=1,operation='solve_fields',arguments=valid))
            self.assertEqual(accepted['contract_status'],'accepted',accepted)
            self.assertEqual(accepted['validator'],'msplatform.backends.simion.field_execution.plan_fields_execution')
            self.assertEqual(accepted['native_qualification'],'not_granted')
            invalid=dict(valid,numerics=dict(refine_policy='explicit_convergence',convergence_v=dict(two=.001)))
            rejected=capabilities(dict(schema_version=1,operation='solve_fields',arguments=invalid))
            self.assertEqual(rejected['contract_status'],'rejected',rejected)
            with self.assertRaises(ValueError):field_execution.plan_fields_execution(**invalid)
            for name in ('refine_rf_field_family.lua','audit_rf_field_family.lua'):
                self.assertTrue(native_resource_path(name).is_file())

    def test_oa_spatial_basis_excludes_explicit_drive_and_clock_but_binds_operator(self):
        from types import SimpleNamespace
        from msplatform.backends.simion import model as model_api
        from msplatform.backends.simion.artifacts import CompiledPreparedModel
        from msplatform.backends.simion.compiler import _content_sha256
        with tempfile.TemporaryDirectory() as directory:
            source=field_closure.load_field_model(produced_model(Path(directory)/'source'))
            kwargs=dict(numerics=dict(refine_policy='vendor_default'),tool_identity=dict(sha256='A'*64),auditor_identity='B'*64)
            original=family.rf_spatial_identity(source,**kwargs)
            self.assertEqual(original['role'],'simion_oa_fractional_spatial_identity')
            document=source.model.document
            drive=copy.deepcopy(document['drive'])
            drive['clock']['clock_epoch_id']='different_explicit_clock'
            for rows in drive['groups'].values(): rows['repeller']['on_voltage_v']+=123.
            compiled=model_api.model_geometry(source.model)
            changed=model_api.compile_prepared_model(compiled,document['components_resolved'],drive=drive,physics=model_api.RF_PHYSICS)
            self.assertEqual(family.rf_spatial_identity(SimpleNamespace(model=changed,native_assets=source.native_assets),**kwargs),original)
            varied=dict(kwargs,numerics=dict(refine_policy='explicit_convergence',convergence_v=dict(two=.001,three=.002)))
            self.assertNotEqual(family.rf_spatial_identity(source,**varied),original)
            assets=copy.deepcopy(source.native_assets);assets['two']['raw_record']['sha256']='C'*64
            self.assertNotEqual(family.rf_spatial_identity(SimpleNamespace(model=source.model,native_assets=assets),**kwargs),original)
            invalid=source.model.document
            invalid.pop('model_identity_sha256')
            invalid['physics']['field_model']='self_consistent_space_charge'
            invalid['model_identity_sha256']=_content_sha256(invalid)
            with self.assertRaisesRegex(ValueError,'linear external'):
                field_execution.plan_fields_execution(CompiledPreparedModel(json.dumps(invalid)),numerics=dict(refine_policy='vendor_default'))
            with self.assertRaises(ValueError):
                field_execution.plan_fields_execution(source.model,numerics=dict(refine_policy='vendor_default',field_coupling='joint'))

    def test_oa_family_missing_members_and_cross_component_reuse_fail_before_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=field_closure.load_field_model(produced_model(root/'oa'))
            numerics=dict(refine_policy='vendor_default')
            incomplete=field_session(root/'incomplete',source,numerics)
            incomplete.incomplete=True
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',side_effect=original_owner):
                with self.assertRaises(ValueError):execute(incomplete,source,numerics)
                self.assertFalse(any(op=='audit_fields' for op,_ in incomplete.requests))
                first=field_session(root/'complete',source,numerics)
                reference=publish_fields(first,execute(first,source,numerics))
                other=field_closure.load_field_model(produced_model(root/'rf',component_kind='rf'))
                refused=field_session(root/'wrong-component',other,numerics,reference)
                refused.capacity_session['protected_paths'].append(str(first.artifact_run_dir))
                with self.assertRaisesRegex(ValueError,'spatial operator'):execute(refused,other,numerics,reference)
                self.assertEqual(refused.requests,[])
            metadata=copy.deepcopy(source.artifact.metadata)
            del metadata['native_assets']['two']['surface_witnesses']
            object.__setattr__(source.artifact,'_metadata',metadata)
            with self.assertRaisesRegex(ValueError,'incomplete'):
                field_closure.load_field_model(source.artifact)

    def test_unchanged_shared_lua_auditor_checks_actual_oa_scope_and_fractional_values(self):
        import subprocess
        from common.contracts.test_simion_prepared_model import LUA
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value
        if not LUA.is_file():self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=field_closure.load_field_model(produced_model(root/'source',fractional_witness=.25))
            numerics=dict(refine_policy='vendor_default')
            session=field_session(root/'fields',source,numerics)
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',side_effect=original_owner):
                execute(session,source,numerics)
            audit_spec=next(Path(options['arguments'][-1]) for op,options in session.requests if op=='audit_fields')
            for mismatch in (False,True):
                output=root/('actual-oa-utility-'+str(mismatch)+'.json')
                spec=root/('utility-'+str(mismatch)+'.lua')
                spec.write_text('local spec=dofile('+lua_value(str(audit_spec))+');spec.output='+lua_value(str(output))+';return spec',encoding='utf-8')
                program='local spec=dofile('+lua_value(str(spec))+')\n'
                program+=r"""
local function pa(path)
 local asset
 for _,a in ipairs(spec.assets) do for _,p in ipairs(a.family_paths) do if p==path then asset=a end end end
 assert(asset,'undeclared family path')
 local p={potential_type='electric',symmetry='3dplanar',electrode_numbers=asset.response_ids}
 for k,v in pairs(asset.grid) do p[k]=v end
 function p:surface_info() return FRACTION,nil,nil end
 function p:point(x,y,z)
  for _,sample in ipairs(asset.physical_samples) do
   if sample.gu[1]==x and sample.gu[2]==y and sample.gu[3]==z then return 10,sample.metal~=false end
  end
  error('undeclared physical sample')
 end
 function p:potentials_minmax() return 0,10000 end
 function p:close() end
 function p:save() error('audit attempted save') end
 function p:refine() error('audit attempted Refine') end
 return p
end
simion={pas={close=function() end,open=function(_,path) return pa(path) end},command=function() error('native command forbidden') end}
""".replace('FRACTION','.5' if mismatch else '.25')
                program+='arg={'+lua_value(str(spec))+'};dofile('+lua_value(str(native_resource_path('audit_rf_field_family.lua')))+')'
                script=root/('auditor-'+str(mismatch)+'.lua');script.write_text(program,encoding='utf-8')
                result=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
                if mismatch:
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('fractional surface readback differs',result.stderr)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    report=json.loads(output.read_text(encoding='utf-8'))
                    self.assertEqual(report['role'],'simion_rf_fractional_field_audit')  # Legacy shared utility format.
                    self.assertEqual(report['checked_domains'],['two','three'])
                    for row in report['checked_assets']:
                        self.assertEqual(row['fractional_witness_count'],1)
                        self.assertEqual(row['nonnil_surface_offsets'],1)
                        expected=source.model.document['geometry']['frontend_geometry']['electrode_bindings'][row['domain_id']]
                        self.assertEqual({r['native_electrode_id'] for r in row['responses']},set(expected.values()))
                        self.assertTrue(any(not item['metal'] for item in row['physical_witnesses']))
