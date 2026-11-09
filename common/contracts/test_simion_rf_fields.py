"""Independent RF field contracts; inert PA bytes never stand for native evidence."""
import copy
import json
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.test_simion_rf_prepared_model import rf_inputs, clock_reference, assets_at
from common.contracts.test_simion_model_execution import _InertModelSession, _inert_small_materialization
from msplatform.backends.simion import model as model_api, rf_field_execution as rf, field_execution, field_closure
from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.backends.simion.source import lua_value
from msplatform.backends.simion.resources import native_resource_path
from common.contracts.test_simion_prepared_model import LUA


def model_source(root):
    compiled, components, drive = rf_inputs()
    clock = clock_reference()
    validated = validate_clock_authority(Path(clock['contract']['path']), Path(clock['data_root']))
    drive['clock'].update(clock_epoch_id=validated['clock_epoch_id'], authority_sha256=validated['authority_sha256'])
    model = model_api.compile_prepared_model(compiled, components, drive=drive, physics=model_api.RF_PHYSICS)
    assets = assets_at(root, compiled)
    records = dict(clock_authority=clock['contract'], instrument_epoch=clock['authority'])
    compiled_path = root/'model.json'
    compiled_path.write_text(json.dumps(model.document))
    records['compiled_model'] = file_record(compiled_path,'required_evidence')
    bindings = {}
    for name, row in assets.items():
        bindings[name] = {}
        for label, record in [('raw_geometry',row['raw_record']), ('fractional_surface',row['surface_records'][0]), ('surface_witnesses',row['witness_record'])]:
            key=name+'_'+label; records[key]=record; bindings[name][label]=key
    manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-RF-model',project='software_fixture',
        mode='explicit_inert_RF_model',status='success',inputs={},outputs=list(records.values()),
        products=dict(model=dict(schema_version=1,kind='prepared_model',status='complete',data=records,
            metadata=dict(backend='simion',drive_configured=True,geometry_materialized=True,
                field_status='not_solved',source_status='not_requested',native_assets=bindings))))
    publish_terminal_state(root,{'status':'success'},manifest)
    return field_closure.load_field_model(dict(manifest=file_record(root/'run_manifest.json'),product_id='model'))


class InertFieldSession(_InertModelSession):
    """Only in-memory owner protocol, explicitly not SIMION or valid PA output."""
    def __init__(self,root,source,graph):
        super().__init__(root,source)
        self.expected_operation_ids=tuple(graph['expected_operation_ids'])
        self.operation_dependencies=graph['operation_dependencies']
        tool=root/'inert_tool/simion.exe'
        tool.parent.mkdir(parents=True);tool.write_bytes(b'INERT_NOT_EXECUTABLE')
        self.context.tools['simion']=tool
        self.domains=graph['numerical_domains']
        self.requests=[]
        self.incomplete=False
        self.omit_marker=False
    def run_process(self,operation_id,**options):
        self.requests.append((operation_id,options))
        self.operations.append(dict(operation_id=operation_id,observation=dict(exit_confirmed=True,returncode=0,
            process_id=1,process_started_at_utc_ticks=1)))
        if operation_id.startswith('refine_'):
            name=operation_id.removeprefix('refine_')
            raw=self.run_dir/'simion/fields'/name/(name+'.pa#')
            # Deliberate tiny fixture representation. Native verification remains separate.
            for eid in ([0] if self.incomplete else [0,*self.labels[operation_id.removeprefix('refine_')]]):
                raw.with_suffix('.pa'+str(eid)).write_bytes(b'INERT_SOFTWARE_NOT_NATIVE_RESPONSE')
        if operation_id=='audit_fields':
            (self.run_dir/'results/rf_field_audit.json').write_text(json.dumps(dict(role='simion_rf_fractional_field_audit',
                status='success',checked_domains=self.domains)))
        ordinal=self.expected_operation_ids.index(operation_id)+1
        marker='INDEPENDENT_RF_REFINE=PASS' if operation_id.startswith('refine_') else ('' if self.omit_marker else 'INDEPENDENT_RF_FIELDS_READBACK=PASS')
        (self.log_dir/f'operation_{ordinal:04d}.stdout.log').write_text(marker)


def session_for(root,source,numerics,reuse=None):
    graph=rf.plan_rf_fields(source.model,numerics=numerics,reuse_fields_reference=reuse)
    session=InertFieldSession(root,source.artifact.data_path('compiled_model').parent,graph)
    geometry=model_api.model_geometry(source.model).frontend_geometry
    session.labels={name:sorted(set(values.values())) for name,values in geometry['electrode_bindings'].items()}
    return session


def execute(session,source,numerics,reuse=None):
    return field_execution.execute_fields(session,model_reference=source.artifact.reference,numerics=numerics,
        limits=dict(reserved_run_payload_bytes=1),materialize_geometry=_inert_small_materialization,
        materializer_record=file_record(Path(_inert_small_materialization.__code__.co_filename),'required_evidence'),
        allow_asynchronous_io=False,reuse_fields_reference=reuse)


class RfFieldTests(unittest.TestCase):
    def test_plan_vendor_default_and_explicit_per_real_domain_are_source_free(self):
        compiled,components,drive=rf_inputs()
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        for values in [dict(refine_policy='vendor_default'),dict(refine_policy='explicit_convergence',convergence_v=dict(first=.001,second=.002))]:
            before=copy.deepcopy(values)
            plan=field_execution.plan_fields_execution(model,numerics=values)
            self.assertEqual(values,before)
            self.assertEqual(plan['expected_operation_ids'],['materialize_geometry','refine_first','refine_second','audit_fields'])
            self.assertEqual(plan['operation_dependencies']['audit_fields'],['refine_first','refine_second'])
            reused=field_execution.plan_fields_execution(model,numerics=values,reuse_fields_reference={})
            self.assertEqual(reused['expected_operation_ids'],['audit_fields'])
            self.assertEqual(reused['operation_dependencies'],{'audit_fields':[]})
    def test_bad_numerics_do_not_silently_select_a_default(self):
        compiled,components,drive=rf_inputs()
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        for values in [{},{'refine_policy':'auto'},{'refine_policy':'vendor_default','convergence_v':{}},
                {'refine_policy':'explicit_convergence','convergence_v':{'first':1}},
                *[{'refine_policy':'explicit_convergence','convergence_v':dict(first=value,second=1)} for value in [True,0,-1,float('nan'),float('inf')]]]:
            with self.subTest(values=values),self.assertRaises(ValueError):rf.plan_rf_fields(model,numerics=values)
    def test_published_model_requires_original_fractional_witness_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            source=model_source(Path(directory)/'source')
            self.assertEqual(set(source.native_assets),{'first','second'})
            for row in source.native_assets.values():self.assertIn('witness_record',row)
            damaged=copy.deepcopy(source.artifact.metadata)
            del damaged['native_assets']['first']['surface_witnesses']
            object.__setattr__(source.artifact,'_metadata',damaged)
            with patch.object(field_closure,'open_artifact',return_value=source.artifact),self.assertRaisesRegex(ValueError,'incomplete'):
                field_closure.load_field_model(source.artifact.reference)
    def test_fresh_action_refines_only_owned_raw_and_guards_all_cold_members(self):
        for policy in ['vendor_default','explicit_convergence']:
            with self.subTest(policy=policy),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=model_source(root/'source')
                values=dict(refine_policy=policy)
                if policy=='explicit_convergence':values['convergence_v']=dict(first=.001,second=.002)
                session=session_for(root/'run',source,values)
                with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(root/'source'))),patch('subprocess.Popen',side_effect=AssertionError('inert test cannot launch native')):
                    result=execute(session,source,values)
                product=result['manifest_extra_fields']['products']['fields']
                self.assertEqual(product['metadata']['refine_calls'],2)
                self.assertEqual(product['metadata']['sampled_particles'],0)
                self.assertEqual(product['metadata']['fly_calls'],0)
                self.assertEqual(product['metadata']['field_representation'],rf.REPRESENTATION)
                self.assertNotIn('family_producer_reference',product['metadata'])
                for op,options in session.requests:
                    if op.startswith('refine_'):
                        self.assertTrue(Path(options['arguments'][-1]).is_relative_to(root/'run'))
                        overrides=['convergence_v'] if 'convergence_v' in Path(options['arguments'][-1]).read_text() else []
                        self.assertEqual(bool(overrides),policy=='explicit_convergence')
                        self.assertNotIn('immutable_input_records',options)
                    elif op=='audit_fields':
                        protected={row['path'] for row in options['immutable_input_records']}
                        expected={record['path'] for name,record in product['data'].items() if '_family_' in name or name.endswith('_surface_witnesses')}
                        self.assertEqual(protected,expected)
                        self.assertTrue(all(Path(path).is_relative_to(root/'run') for path in protected))
                self.assertTrue(all('fly' not in op.lower() for op,_ in session.requests))
    def test_incomplete_refine_family_and_missing_cold_marker_fail_closed(self):
        for incomplete in [True,False]:
            with self.subTest(incomplete=incomplete),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=model_source(root/'source');values=dict(refine_policy='vendor_default')
                session=session_for(root/'run',source,values);session.incomplete=incomplete;session.omit_marker=not incomplete
                with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(root/'source'))),self.assertRaises((ValueError,FileNotFoundError)):
                    execute(session,source,values)
                self.assertEqual(any(op=='audit_fields' for op,_ in session.requests),not incomplete)
    def test_source_without_active_protection_rejects_before_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=model_source(root/'source');values=dict(refine_policy='vendor_default')
            session=session_for(root/'run',source,values);session.capacity_session['protected_paths']=[]
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(root/'source'))),self.assertRaisesRegex(ValueError,'active owner protection'):
                execute(session,source,values)
            self.assertEqual(session.requests,[])

    def test_explicit_reuse_and_second_reuse_keep_original_family_without_copy_or_refine(self):
        def publish(session,result):
            product=result['manifest_extra_fields']['products']['fields']
            manifest=dict(schema_version=2,role='simulation_run_manifest',run_id=session.run_dir.name,
                project='software_fixture',mode='explicit_inert_RF_fields',status='success',inputs={},
                outputs=list(product['data'].values()),products=dict(fields=product))
            publish_terminal_state(session.run_dir,{'status':'success'},manifest)
            return dict(manifest=file_record(session.run_dir/'run_manifest.json'),product_id='fields')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=model_source(root/'source');values=dict(refine_policy='vendor_default')
            first=session_for(root/'producer',source,values)
            resolver=lambda record,**kw:dict(run_directory=str(Path(record['path']).parent))
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',side_effect=resolver),patch('subprocess.Popen',side_effect=AssertionError('no native in inert fixture')):
                first_ref=publish(first,execute(first,source,values))
                original=open_artifact(first_ref,expected_kind='field_bundle')
                original_data=copy.deepcopy(original.data_records)
                selected=first_ref
                for index in [1,2]:
                    current=session_for(root/('reuse'+str(index)),source,values,reuse=selected)
                    current.capacity_session['protected_paths']=[str(root)]
                    result=execute(current,source,values,reuse=selected)
                    metadata=result['manifest_extra_fields']['products']['fields']['metadata']
                    self.assertEqual(metadata['family_producer_reference'],first_ref)
                    self.assertEqual(metadata['refine_calls'],0)
                    self.assertEqual([row[0] for row in current.requests],['audit_fields'])
                    self.assertFalse((current.run_dir/'simion/fields').exists())
                    actual={r['path'] for r in current.requests[0][1]['immutable_input_records']}
                    expected={record['path'] for name,record in original_data.items() if '_family_' in name or name.endswith('_surface_witnesses')}
                    self.assertEqual(actual,expected)
                    selected=publish(current,result)
                self.assertEqual(open_artifact(first_ref,expected_kind='field_bundle').data_records,original_data)

    def test_spatial_identity_excludes_drive_clock_and_source_but_binds_numerics_and_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            source=model_source(Path(directory)/'source')
            args=dict(numerics=dict(refine_policy='vendor_default'),tool_identity=dict(sha256='A'*64),auditor_identity='B'*64)
            identity=rf.rf_spatial_identity(source,**args)
            compiled,components,drive=rf_inputs()
            for row in drive['groups']['first'].values():
                if row['kind']=='rf':row['phase_rad']+=.3
            changed=SimpleNamespace(model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS),native_assets=source.native_assets)
            self.assertEqual(rf.rf_spatial_identity(changed,**args),identity)
            varied=copy.deepcopy(args);varied['numerics']=dict(refine_policy='explicit_convergence',convergence_v=dict(first=.001,second=.001))
            self.assertNotEqual(rf.rf_spatial_identity(source,**varied),identity)
            assets=copy.deepcopy(source.native_assets);assets['first']['raw_record']['sha256']='C'*64
            self.assertNotEqual(rf.rf_spatial_identity(SimpleNamespace(model=source.model,native_assets=assets),**args),identity)

    def test_capability_uses_same_field_plan_and_refuses_bad_policy(self):
        from msplatform.capabilities import capabilities
        compiled,components,drive=rf_inputs()
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        arguments=dict(model=model,numerics=dict(refine_policy='vendor_default'))
        result=capabilities(dict(schema_version=1,operation='solve_fields',arguments=arguments))
        self.assertEqual(result['contract_status'],'accepted')
        self.assertEqual(result['validator'],'msplatform.backends.simion.field_execution.plan_fields_execution')
        self.assertEqual(result['native_qualification'],'not_granted')
        arguments['numerics']={}
        self.assertEqual(capabilities(dict(schema_version=1,operation='solve_fields',arguments=arguments))['contract_status'],'rejected')

    def test_reuse_rejects_missing_family_chains_and_unconfirmed_refine_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=model_source(root/'source');values=dict(refine_policy='vendor_default')
            first=session_for(root/'producer',source,values)
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(root/'source'))):
                product=execute(first,source,values)['manifest_extra_fields']['products']['fields']
            manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-producer',project='software_fixture',
                mode='explicit_inert_RF_fields',status='success',inputs={},outputs=list(product['data'].values()),products=dict(fields=product))
            publish_terminal_state(first.run_dir,{'status':'success'},manifest)
            reference=dict(manifest=file_record(first.run_dir/'run_manifest.json'),product_id='fields')
            original=open_artifact(reference,expected_kind='field_bundle')
            geometry=model_api.model_geometry(source.model).frontend_geometry
            identity=product['metadata']['spatial_identity']
            for mutation,reason in [('missing','exact same-producer'),('chain','original producer'),('receipt','successful actual Refine')]:
                damaged=copy.copy(original)
                metadata=copy.deepcopy(original.metadata)
                if mutation=='missing':metadata['native_assets']['first']['family'].pop()
                elif mutation=='chain':metadata['family_producer_reference']=reference
                else:
                    receipt=first.input_dir/'bad_receipts.json'
                    receipt.write_text(json.dumps([dict(operation_id='refine_'+name,observation=dict(exit_confirmed=True,returncode=0,process_id=0,process_started_at_utc_ticks=1)) for name in geometry['numerical_domains']]))
                    object.__setattr__(damaged,'_paths',dict(original._paths,field_native_receipts=receipt))
                    object.__setattr__(damaged,'_records',dict(original._records,field_native_receipts=file_record(receipt,'required_evidence')))
                object.__setattr__(damaged,'_metadata',metadata)
                with self.subTest(mutation=mutation),patch.object(rf,'open_artifact',return_value=damaged),self.assertRaisesRegex(ValueError,reason):
                    rf.require_rf_reuse(reference,identity=identity,geometry=geometry)

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_official_refine_command_keeps_default_and_explicit_convergence_distinct(self):
        for convergence in [None,.001]:
            with self.subTest(convergence=convergence),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                spec=dict(input=str(root/'owned.pa#'))
                if convergence is not None:spec['convergence_v']=convergence
                path=root/'spec.lua';path.write_text('return '+lua_value(spec))
                resource=native_resource_path('refine_rf_field_family.lua')
                script='simion={command=function(s) print(s) end,pas={close=function() end}};arg={'+lua_value(str(path))+'};dofile('+lua_value(str(resource))+')'
                result=subprocess.run([str(LUA),'-e',script],cwd=root,text=True,capture_output=True,timeout=30,check=True)
                self.assertIn('refine --resume=0',result.stdout)
                self.assertEqual('--convergence=' in result.stdout,convergence is not None)
                self.assertIn('INDEPENDENT_RF_REFINE=PASS',result.stdout)

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_native_auditor_exact_surface_and_scope_checks_with_read_only_inert_pas(self):
        for mismatch in [False,True]:
            with self.subTest(mismatch=mismatch),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);paths=[]
                for suffix in ['.pa#','.pa0','.pa1','.pa-surf']:
                    path=root/('inert'+suffix);path.write_bytes(b'INERT_NOT_NATIVE');paths.append(str(path))
                witness=root/'surface.csv';witness.write_text('0,0,0,0.25,nil,nil\n')
                output=root/'audit.json'
                spec=dict(output=str(output),assets=[dict(domain_id='real_domain',carrier_path=paths[1],family_paths=paths,
                    response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=.2,dy_mm=.3,dz_mm=.4),
                    physical_samples=[dict(gu=[0,0,0],metal=True),dict(gu=[1,0,0],metal=False)],surface_witnesses=str(witness))])
                path=root/'spec.lua';path.write_text('return '+lua_value(spec))
                script='local pa={potential_type="electric",symmetry="3dplanar",nx=3,ny=3,nz=3,dx_mm=.2,dy_mm=.3,dz_mm=.4,electrode_numbers={1}}; '
                script+='function pa:surface_info() return '+('.5' if mismatch else '.25')+' end; '
                script+='function pa:point(x) return 10,x==0 end;function pa:potentials_minmax() return 0,10000 end;function pa:close() end;function pa:save() error("audit wrote PA") end; '
                script+='simion={pas={close=function() end,open=function() return pa end}};arg={'+lua_value(str(path))+'};dofile('+lua_value(str(native_resource_path('audit_rf_field_family.lua')))+')'
                result=subprocess.run([str(LUA),'-e',script],cwd=root,text=True,capture_output=True,timeout=30)
                if mismatch:
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('RF fractional surface readback differs',result.stderr)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    report=json.loads(output.read_text())
                    self.assertEqual(report['checked_domains'],['real_domain'])
                    self.assertEqual(report['checked_assets'][0]['fractional_witness_count'],1)
                    self.assertEqual(report['checked_assets'][0]['nonnil_surface_offsets'],1)
                    self.assertEqual(report['checked_assets'][0]['responses'],[dict(native_electrode_id=1,minimum_v=0,maximum_v=10000)])
                    self.assertEqual(report['checked_assets'][0]['physical_witnesses'][1]['metal'],False)
                    self.assertIn('INDEPENDENT_RF_FIELDS_READBACK=PASS',result.stdout)

    def test_public_dispatch_protects_both_selected_bundle_and_original_producer(self):
        from msplatform.backends.simion.operations import solve_fields
        from msplatform.execution import owner, stage_policy
        from msplatform.results import artifacts
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=model_source(root/'source');values=dict(refine_policy='vendor_default')
            session=session_for(root/'inert',source,values)
            producer_file=root/'original_manifest.json';producer_file.write_text('INERT_ORIGINAL_MANIFEST')
            selected_file=root/'selected_manifest.json';selected_file.write_text('INERT_SELECTED_MANIFEST')
            producer_reference=dict(manifest=file_record(producer_file),product_id='fields')
            selected_reference=dict(manifest=file_record(selected_file),product_id='fields')
            reused=SimpleNamespace(reference=selected_reference,metadata=dict(field_representation=rf.REPRESENTATION,
                family_producer_reference=producer_reference))
            sentinel=object()
            with patch.object(owner,'run_managed_stage',return_value=dict(manifest=producer_reference['manifest'])) as managed,patch.object(stage_policy,'read_stage_policy',return_value=(dict(runtime={},limits=dict(transient_run_directory_bytes=1),artifact_retention={}),{})),patch.object(artifacts,'open_artifact',side_effect=[reused,sentinel]):
                actual=solve_fields(source.artifact.reference,numerics=values,context=session.context,reuse_fields=selected_reference)
            self.assertIs(actual,sentinel)
            call=managed.call_args.kwargs
            self.assertEqual(call['source_references'],[dict(manifest_record=source.artifact.reference['manifest']),
                dict(manifest_record=selected_reference['manifest']),dict(manifest_record=producer_reference['manifest'])])
            self.assertEqual(call['expected_operation_ids'],('audit_fields',))
            self.assertIs(call['action'].func,field_execution.execute_fields)
            self.assertEqual(call['action'].keywords['reuse_fields_reference'],selected_reference)


if __name__=='__main__':unittest.main()
