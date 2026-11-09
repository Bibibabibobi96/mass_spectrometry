"""Unsolved model plans and actual Lua consumers with inert workbench objects."""
from __future__ import annotations

import json
import re
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.test_simion_prepared_model import model_inputs, oa_model_inputs, LUA
from msplatform.backends.simion.model import compile_prepared_model, PHYSICS
from msplatform.backends.simion.model_execution import execute_model, _protected_source, _clock_reference
from msplatform.backends.simion.native_plans import plan_model_preparation
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.backends.simion.source import lua_value
from msplatform.io.manifest_records import file_record
from msplatform.execution.resources import resource_path
from msplatform.execution.terminal_publication import publish_terminal_state


class _InertModelSession:
    """Software-only protocol fixture; never a real native execution receipt."""

    def __init__(self, root, source):
        self.run_dir = self.artifact_run_dir = root
        self.input_dir, self.result_dir, self.log_dir = root/'inputs', root/'results', root/'logs'
        self.log_dir.mkdir(parents=True)
        self.artifact_root = root.parent/'consumer_artifacts'
        self.capacity_session = dict(status='active', protected_paths=[str(source)], source_protection_leases=[])
        self.expected_operation_ids = ('materialize_geometry', 'build_model', 'verify_model')
        self.context = SimpleNamespace(tools={'simion': Path('C:/inert/simion.exe')})
        self.operations, self.roles, self.inputs = [], {}, {}

    def canonical_path(self, path):
        return Path(path).resolve()

    def declare_file(self, path, role):
        path = self.canonical_path(path)
        previous = self.roles.setdefault(path, role)
        assert previous == role
        return path

    def add_input(self, name, record):
        from msplatform.io.manifest_records import verify_record
        verify_record(name, record)
        self.inputs[name] = record

    def run_process(self, operation_id, **options):
        # A protocol stub, not a claim that any native format is valid.
        ordinal = self.expected_operation_ids.index(operation_id)+1
        self.operations.append(dict(operation_id=operation_id,
            observation=dict(exit_confirmed=True, returncode=0, process_id=1, process_started_at_utc_ticks=1)))
        if operation_id == 'build_model':
            path = self.run_dir/'simion/geometry/geometry.iob'
            path.write_bytes(b'INERT_SOFTWARE_NOT_NATIVE_IOB')
            path.with_suffix('.fly2').write_text('particles { coordinates = 0 }', encoding='utf-8')
            marker = ('INDEPENDENT_OA_MODEL_' if 'independent_oa_geometry_iob_build' in (self.input_dir/'geometry_iob.lua').read_text(encoding='utf-8') else 'INDEPENDENT_RF_MODEL_' if 'independent_rf_geometry_iob_build' in (self.input_dir/'geometry_iob.lua').read_text(encoding='utf-8') else 'SINGLE_REFLECTION_MODEL_')+'BUILD=PASS'
        elif operation_id == 'verify_model':
            path = self.result_dir/'model_drive_readback.txt'
            path.write_text('INERT_SOFTWARE_NOT_NATIVE_READBACK', encoding='utf-8')
            marker = ('INDEPENDENT_OA_MODEL_' if 'independent_oa_geometry_iob_build' in (self.input_dir/'geometry_iob.lua').read_text(encoding='utf-8') else 'INDEPENDENT_RF_MODEL_' if 'independent_rf_geometry_iob_build' in (self.input_dir/'geometry_iob.lua').read_text(encoding='utf-8') else 'SINGLE_REFLECTION_MODEL_')+'READBACK=PASS'
        else:
            marker = 'INERT_SOFTWARE_COPY'
        (self.log_dir/f'operation_{ordinal:04d}.stdout.log').write_text(marker, encoding='utf-8')


def _inert_small_materialization(copies, *, session, operation_id):
    """Only tiny explicitly inert fixture bytes; production requires the owner callback."""
    records = []
    for row in copies:
        target = Path(row['destination'])
        target.write_bytes(Path(row['source_record']['path']).read_bytes())
        records.append(file_record(target, 'solver_native_binary'))
    session.run_process(operation_id)
    return records


def _inert_noop_materialization(copies, *, session, operation_id):
    return []


def _clock_authority_reference(root):
    directory = root/'clock-source'
    return dict(contract=file_record(directory/'clock_authority.json', 'required_evidence'),
                authority=file_record(directory/'inputs/instrument_epoch.json', 'required_evidence'),
                data_root=str(directory))


def model_plan(root, *, independent_oa=False, independent_rf=False):
    if independent_rf:
        from common.contracts.test_simion_geometry_compiler import independent_rf_inputs
        from msplatform.backends.simion import compile_geometry
        from msplatform.backends.simion.model import project_resolved_drive
        assembly, numerics = independent_rf_inputs()
        compiled = compile_geometry(assembly, numerics=numerics)
        drive = project_resolved_drive(compiled, assembly.components_resolved,
            clock=dict(clock_epoch_id='model_fixture_epoch', authority_sha256='A'*64,
                       phase_reference_instrument_time_us=0.))
    else:
        assembly, _, compiled, drive = oa_model_inputs() if independent_oa else model_inputs(root/'author')
    independent_component = independent_oa or independent_rf
    directory = root/'clock-source'
    (directory/'inputs').mkdir(parents=True)
    (directory/'inputs/instrument_epoch.json').write_text(json.dumps(dict(instrument_time_us=0.), indent=2)+'\n',
        encoding='utf-8', newline='\n')
    epoch = file_record(directory/'inputs/instrument_epoch.json', 'required_evidence')
    contract = dict(schema_version=1, role='canonical_clock_authority', clock_epoch_id=drive['clock']['clock_epoch_id'],
        instrument_time_unit='us', canonical_time_basis='instrument_epoch_absolute_time',
        authority=dict(path='inputs/instrument_epoch.json', sha256=epoch['sha256'], field='instrument_time_us'),
        solver_local_time_basis='elapsed_time_from_zero_us',
        adapter_materialization='instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once',
        handoff_policy='preserve_instrument_time_us_and_clock_epoch_id', legacy_new_campaign_allowed=False)
    (directory/'clock_authority.json').write_text(json.dumps(contract, indent=2)+'\n', encoding='utf-8', newline='\n')
    drive['clock']['authority_sha256'] = epoch['sha256']
    from msplatform.backends.simion.model import RF_PHYSICS
    components = assembly.components_resolved if independent_component else assembly['components_resolved']
    model = compile_prepared_model(compiled, components, drive=drive, physics=RF_PHYSICS if independent_component else PHYSICS)
    assets = {}
    source = root/'source'
    source.mkdir()
    for domain in (compiled.frontend_geometry['numerical_domains'] if independent_component else ('parent', 'flight_tube', 'reflectron', 'detector')):
        path = source/(domain+'.pa#')
        path.write_bytes(b'INERT_SOFTWARE_RAW_NOT_NATIVE_PA')
        surfaces = []
        if independent_component or domain in {'flight_tube', 'detector'}:
            surface = path.with_suffix('.pa-surf')
            surface.write_bytes(b'INERT_SOFTWARE_SURFACE_NOT_NATIVE')
            surfaces.append(file_record(surface, 'solver_native_binary'))
        assets[domain] = dict(raw_record=file_record(path, 'solver_native_binary'), surface_records=surfaces)
        if independent_component:
            witnesses = source/(domain+'_surface.csv')
            witnesses.write_bytes(b'0,0,0,nil,nil,nil\n')
            assets[domain]['witness_record'] = file_record(witnesses, 'required_evidence')
    seed = file_record(structural_seed_path(len(assets) if independent_component else 4), 'required_evidence')
    plan = plan_model_preparation(model, geometry_assets=assets, run_directory=root/'run', seed_record=seed,
        native_path_resource=resource_path('native_run_path.lua'))
    return model, assets, seed, plan


class ModelExecutionTests(unittest.TestCase):
    def test_shared_preparation_accepts_only_exact_original_or_view_operation_graph(self):
        from msplatform.backends.simion.model_execution import _execute_model_preparation
        for graph in ((), ('materialize_geometry',),
                ('materialize_geometry','build_model','verify_model','unrelated'),
                ('materialize_geometry','build_model','verify_model','view_model','extra')):
            with self.subTest(graph=graph), self.assertRaisesRegex(ValueError, 'exactly its three operations'):
                _execute_model_preparation(SimpleNamespace(expected_operation_ids=graph), model=None, assets={},
                    source_manifest_record={}, clock_authority_reference={}, seed_record={}, limits={},
                    materialize_geometry=None, materializer_record={})

    def test_actual_clock_records_reject_tamper_identity_swap_and_nonportable_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for case in ('valid', 'contract_tamper', 'epoch_tamper', 'wrong_identity', 'swapped_path', 'absolute'):
                parent = root/case
                parent.mkdir()
                model, _, _, _ = model_plan(parent)
                reference = _clock_authority_reference(parent)
                document = model.document
                if case == 'contract_tamper':
                    Path(reference['contract']['path']).write_bytes(b'{}')
                elif case == 'epoch_tamper':
                    Path(reference['authority']['path']).write_bytes(b'{"instrument_time_us": 1}')
                elif case == 'wrong_identity':
                    document['drive']['clock']['authority_sha256'] = 'F'*64
                elif case == 'swapped_path':
                    other = parent/'clock-source/other.json'
                    other.write_bytes(Path(reference['authority']['path']).read_bytes())
                    reference['authority'] = file_record(other, 'required_evidence')
                elif case == 'absolute':
                    contract = json.loads(Path(reference['contract']['path']).read_text(encoding='utf-8'))
                    contract['authority']['path'] = reference['authority']['path']
                    Path(reference['contract']['path']).write_text(json.dumps(contract), encoding='utf-8')
                    reference['contract'] = file_record(Path(reference['contract']['path']), 'required_evidence')
                with self.subTest(case=case):
                    if case == 'valid':
                        self.assertEqual(_clock_reference(document, reference), Path('inputs/instrument_epoch.json'))
                    else:
                        with self.assertRaises((AssertionError, ValueError)):
                            _clock_reference(document, reference)

    def test_action_binds_published_geometry_and_rejects_noop_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for noop, wrong_profile, bad_binding in ((False, False, ''), (True, False, ''),
                    (False, True, ''), (False, False, 'missing'), (False, False, 'undeclared')):
                case = root/f'{noop}-{wrong_profile}-{bad_binding}'
                case.mkdir()
                model, assets, seed, _ = model_plan(case)
                producer = case/'producer'
                producer.mkdir()
                for row in assets.values():
                    for record in [row['raw_record'], *row['surface_records']]:
                        target = producer/Path(record['path']).name
                        target.write_bytes(Path(record['path']).read_bytes())
                        record.update(file_record(target, 'solver_native_binary'))
                compiled = producer/'compiled_geometry.json'
                compiled.write_text(json.dumps(model.document['geometry']), encoding='utf-8')
                records = {'compiled_geometry': file_record(compiled, 'required_evidence')}
                names = {}
                for domain, row in assets.items():
                    key = domain+'_raw'
                    records[key] = row['raw_record']
                    names[domain] = {'raw_geometry': key}
                    if row['surface_records']:
                        key = domain+'_surface'
                        records[key] = row['surface_records'][0]
                        names[domain]['fractional_surface'] = key
                if bad_binding == 'missing':
                    names.pop('parent')
                elif bad_binding == 'undeclared':
                    names['parent']['raw_geometry'] = 'not_a_declared_product_record'
                manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-source',
                    project='software_fixture', mode='inert_geometry_contract', status='success', inputs={},
                    outputs=list(records.values()), products={'geometry':dict(schema_version=1,
                        kind='geometry_artifact', status='complete', metadata=dict(native_assets=names, backend='simion',
                            geometry_materialized=True, field_status='available' if wrong_profile else 'not_solved',
                            source_status='not_requested'), data=records)})
                publish_terminal_state(producer, {'status':'success'}, manifest)
                reference = dict(manifest=file_record(producer/'run_manifest.json'), product_id='geometry')
                session = _InertModelSession(case/'owned', producer)
                callback = _inert_noop_materialization if noop else _inert_small_materialization
                with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',
                           return_value=dict(run_directory=str(producer))), \
                     patch('subprocess.Popen', side_effect=AssertionError('no process in this inert protocol fixture')):
                    if bad_binding:
                        with self.assertRaises(ValueError):
                            execute_model(session, model=model, geometry_reference=reference, seed_record=seed,
                                clock_authority_reference=_clock_authority_reference(case), limits={},
                                materialize_geometry=callback, materializer_record=file_record(Path(__file__)))
                        self.assertEqual(session.operations, [])
                    elif wrong_profile:
                        with self.assertRaisesRegex(ValueError, 'unsolved source-independent'):
                            execute_model(session, model=model, geometry_reference=reference, seed_record=seed,
                                clock_authority_reference=_clock_authority_reference(case),
                                limits={}, materialize_geometry=callback, materializer_record=file_record(Path(__file__)))
                        self.assertEqual(session.operations, [])
                    elif noop:
                        with self.assertRaisesRegex(ValueError, 'did not complete its original admitted process'):
                            execute_model(session, model=model, geometry_reference=reference, seed_record=seed,
                                clock_authority_reference=_clock_authority_reference(case),
                                limits={}, materialize_geometry=callback, materializer_record=file_record(Path(__file__)))
                        self.assertEqual(session.operations, [])
                    else:
                        result = execute_model(session, model=model, geometry_reference=reference, seed_record=seed,
                            clock_authority_reference=_clock_authority_reference(case),
                            limits={}, materialize_geometry=callback, materializer_record=file_record(Path(__file__)))
                        self.assertEqual([row['operation_id'] for row in session.operations], list(session.expected_operation_ids))
                        product = result['manifest_extra_fields']['products']['model']
                        self.assertEqual(product['kind'], 'prepared_model')
                        self.assertEqual(product['metadata']['field_status'], 'not_solved')
                        self.assertEqual(product['metadata']['source_status'], 'not_requested')
                        self.assertEqual(product['metadata']['refine_calls'], 0)
                        self.assertIn('source_manifest', product['data'])
                        self.assertIn('resource_model_drive.lua', product['data'])
                        self.assertEqual(len([name for name in product['data'] if name.startswith('geometry_')]), 6)
                        self.assertEqual(set(product['metadata']['native_assets']), set(names))
                        for domain, source_names in names.items():
                            self.assertEqual(set(product['metadata']['native_assets'][domain]), set(source_names))
                            for label, source_key in source_names.items():
                                owned_record = product['data'][product['metadata']['native_assets'][domain][label]]
                                self.assertTrue(Path(owned_record['path']).is_relative_to(session.artifact_run_dir))
                                self.assertEqual((owned_record['bytes'], owned_record['sha256']),
                                                 (records[source_key]['bytes'], records[source_key]['sha256']))
                        self.assertIn('clock_authority', product['data'])
                        self.assertIn('instrument_epoch', product['data'])
                        self.assertEqual(Path(product['data']['clock_authority']['path']).read_bytes(),
                                         Path(_clock_authority_reference(case)['contract']['path']).read_bytes())
                        self.assertEqual(Path(product['data']['instrument_epoch']['path']).read_bytes(),
                                         Path(_clock_authority_reference(case)['authority']['path']).read_bytes())
                        self.assertEqual(len(session.inputs), 16)

    def test_independent_oa_materialization_preserves_both_domains_and_rejects_missing_surface_closure(self):
        self._check_independent_materialization()

    def test_canonical_independent_rf_keeps_model_domain_seed_and_materialization_closure(self):
        self._check_independent_materialization(independent_rf=True)

    def _check_independent_materialization(self, *, independent_rf=False):
        for invalid in ('none', 'surface', 'witness', 'geometry', 'noop'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                model, assets, seed, plan = model_plan(root, independent_oa=not independent_rf, independent_rf=independent_rf)
                self.assertEqual(Path(seed['path']), structural_seed_path(2))
                self.assertEqual(model.document['geometry']['frontend_geometry']['role'],
                    'simion_independent_rf_geometry' if independent_rf else 'simion_independent_oa_geometry')
                producer = root/'producer'
                producer.mkdir()
                records, names = {}, {}
                compiled = producer/'compiled_geometry.json'
                snapshot = model.document['geometry']
                if invalid == 'geometry': snapshot['frontend_gems'][next(iter(assets))] += '#changed'
                compiled.write_text(json.dumps(snapshot), encoding='utf-8')
                records['compiled_geometry'] = file_record(compiled, 'required_evidence')
                for domain, row in assets.items():
                    names[domain] = {}
                    for label, record in (('raw_geometry', row['raw_record']), ('fractional_surface', row['surface_records'][0]),
                                          ('surface_witnesses', row['witness_record'])):
                        key = domain+'_'+label
                        records[key] = record
                        names[domain][label] = key
                if invalid in {'surface', 'witness'}:
                    names[next(iter(names))].pop('fractional_surface' if invalid == 'surface' else 'surface_witnesses')
                manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-oa-source',
                    project='software_fixture', mode='inert_geometry_contract', status='success', inputs={},
                    outputs=list(records.values()), products={'geometry': dict(schema_version=1,
                        kind='geometry_artifact', status='complete', metadata=dict(native_assets=names, backend='simion',
                            geometry_materialized=True, field_status='not_solved', source_status='not_requested'), data=records)})
                publish_terminal_state(producer, {'status':'success'}, manifest)
                reference = dict(manifest=file_record(producer/'run_manifest.json'), product_id='geometry')
                session = _InertModelSession(root/'owned', producer)
                # Explicit tiny inert records; no native PA format is claimed.
                session.capacity_session['protected_paths'].append(str(root/'source'))
                callback = _inert_noop_materialization if invalid == 'noop' else _inert_small_materialization
                with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',
                        return_value=dict(run_directory=str(producer))), patch('subprocess.Popen', side_effect=AssertionError('no native')):
                    arguments = dict(model=model, geometry_reference=reference, seed_record=seed,
                        clock_authority_reference=_clock_authority_reference(root), limits={},
                        materialize_geometry=callback, materializer_record=file_record(Path(__file__)))
                    if invalid != 'none':
                        with self.assertRaises(ValueError): execute_model(session, **arguments)
                        self.assertEqual(session.operations, [])
                    else:
                        result = execute_model(session, **arguments)
                        product = result['manifest_extra_fields']['products']['model']
                        self.assertEqual(set(product['metadata']['native_assets']), set(assets))
                        self.assertEqual(product['metadata']['field_status'], 'not_solved')
                        self.assertEqual(product['metadata']['source_status'], 'not_requested')
                        self.assertEqual([row['operation_id'] for row in session.operations], ['materialize_geometry','build_model','verify_model'])
                        self.assertEqual([row['operation_id'] for row in plan.operations], ['materialize_geometry','build_model','verify_model'])
                        for label in ('refine_calls','fly_calls','gui_calls','sampled_particles'):
                            self.assertEqual(product['metadata'][label], 0)
                        for domain, labels in names.items():
                            self.assertEqual(set(product['metadata']['native_assets'][domain]), set(labels))
                            for label, key in labels.items():
                                owned = product['data'][product['metadata']['native_assets'][domain][label]]
                                self.assertEqual((owned['bytes'],owned['sha256']), (records[key]['bytes'],records[key]['sha256']))
                                self.assertTrue(Path(owned['path']).is_relative_to(session.artifact_run_dir))

    def test_model_plan_requires_owned_complete_raw_family_and_only_explicit_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, assets, seed, plan = model_plan(root)
            self.assertFalse((root/'run').exists())
            self.assertEqual([row['operation_id'] for row in plan.operations],
                             ['materialize_geometry', 'build_model', 'verify_model'])
            self.assertEqual(plan.operations[0]['action'], 'explicit_geometry_payload_callback')
            self.assertEqual([row['role'] for row in plan.operations], ['GATE', 'SIMION', 'SIMION'])
            self.assertEqual(len(plan.input_copies), 7)
            self.assertFalse(any('refine' in value or value == 'fly'
                for row in plan.operations[1:] for value in row['arguments']))
            self.assertEqual([Path(path).name for path in plan.declared_outputs if Path(path).suffix == '.fly2'], ['geometry.fly2'])
            self.assertFalse(any(Path(path).suffix in {'.ion', '.con', '.rec'} for path in plan.declared_outputs))
            for case in ('missing', 'surface', 'family', 'empty'):
                changed = {key: dict(value) for key, value in assets.items()}
                if case == 'missing': changed.pop('parent')
                elif case == 'surface': changed['flight_tube'] = dict(changed['flight_tube'], surface_records=[])
                elif case == 'family': changed['parent'] = dict(changed['parent'], raw_record=dict(changed['parent']['raw_record'], path=str(root/'old.pa1')))
                else: changed['parent'] = dict(changed['parent'], raw_record=dict(changed['parent']['raw_record'], bytes=0))
                with self.subTest(case=case), self.assertRaises(ValueError):
                    plan_model_preparation(model, geometry_assets=changed, run_directory=root/'rejected',
                        seed_record=seed, native_path_resource=resource_path('native_run_path.lua'))

    def test_missing_transport_and_unprotected_source_fail_before_native_or_copy(self):
        with patch('subprocess.Popen', side_effect=AssertionError('no process')):
            with self.assertRaisesRegex(ValueError, 'materializer is required'):
                execute_model(object(), model=None, geometry_reference={}, seed_record={}, limits={},
                    clock_authority_reference={},
                    materialize_geometry=None, materializer_record=None)
            source = Path('C:/explicit/source/run')
            session = SimpleNamespace(artifact_root=Path('C:/explicit/consumer/artifacts'),
                capacity_session=dict(status='active', protected_paths=[], source_protection_leases=[]))
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',
                       return_value=dict(run_directory=str(source))):
                with self.assertRaisesRegex(ValueError, 'no active owner protection'):
                    _protected_source(session, {})
                session.capacity_session['protected_paths'] = [str(source)]
                _protected_source(session, {})
                with self.assertRaisesRegex(ValueError, 'member has no active owner protection'):
                    _protected_source(session, {}, required_paths=[source.parent/'unprotected.pa#'])
                session.capacity_session['protected_paths'] = []
                session.capacity_session['source_protection_leases'] = [dict(status='released', protected_paths=[str(source)])]
                with self.assertRaisesRegex(ValueError, 'no active owner protection'):
                    _protected_source(session, {})

    @unittest.skipUnless(LUA.is_file(), 'standalone Lua interpreter unavailable')
    def test_real_model_wrapper_consumer_and_preload_guards_with_indexed_userdata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for independent_oa, failure in ((oa, fail) for oa in (False, True) for fail in ('none', 'missing', 'wgem', 'hook', 'beam', 'missing_control', 'ambient_fly2')):
                case = root/(str(independent_oa)+'-'+failure)
                case.mkdir()
                model, _, _, plan = model_plan(case, independent_oa=independent_oa)
                for path, text in plan.materializations.items():
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(text, encoding='utf-8')
                for row in plan.input_copies:
                    path = Path(row['destination'])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(Path(row['source_record']['path']).read_bytes())
                frozen = case/'run/inputs/native_sources'
                frozen.mkdir()
                for name in ('model_drive.lua', 'rf_drive.lua', 'single_flight_pulse_hook.lua', 'voltage_waveforms.lua'):
                    (frozen/name).write_bytes(native_resource_path(name).read_bytes())
                (case/'run/results').mkdir(exist_ok=True)
                spec = case/'run/inputs/geometry_iob.lua'
                script = case/'check.lua'
                program = 'local independent_oa='+lua_value(independent_oa)+'\n'+'local spec=dofile('+json.dumps(spec.as_posix())+')\n' + 'local failure='+lua_value(failure)+'\n'+r'''
local commands,changes=0,0
local zero_loaded=false
local function norm(s) return s:gsub('\\','/') end
local function pa()
 local p={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
 function p:size(x,y,z) assert(x==3 and y==3 and z==3);self.nx,self.ny,self.nz=x,y,z end
 function p:save(path) local file=assert(io.open(path,'wb'));file:write('INERT_NOT_PA');file:close() end
 function p:close() end
 function p:surface_info() return nil,nil,nil end
 function p:point(x,y,z)
  for _,row in ipairs(spec.instances) do if norm(row.path)==self.path then
   for _,sample in ipairs(row.physical_samples) do
    if sample.gu[1]==x and sample.gu[2]==y and sample.gu[3]==z then
     return sample.electrode_id or 0,sample.metal~=false
    end
   end
  end end
  error('unbound inert physical sample')
 end
 function p:load()
  changes=changes+1;self.path=norm(self.filename)
  for _,row in ipairs(spec.instances) do if norm(row.path)==self.path then for k,v in pairs(row.grid) do self[k]=v end end end
 end
 return setmetatable(p,{__index=function(t,k) if k=='path' then return rawget(t,'_path') end end,
  __newindex=function(t,k,v) if k=='path' then rawset(t,'_path',norm(v)) else rawset(t,k,v) end end})
end
local slots={};local instances=newproxy(true)
getmetatable(instances).__index=slots;getmetatable(instances).__newindex=slots
getmetatable(instances).__len=function() return #spec.instances end
simion={pas={},wb={instances=instances}}
function simion.pas:open() return pa() end
function simion.pas:close() end
function simion.wb:load_particles(path)
 local file=assert(io.open(path,'rb'));local text=file:read('*a');file:close()
 assert(text:gsub('%s','')=='particles{coordinates=0,}','nonzero source requested')
 zero_loaded=true
end
function simion.wb:save(path)
 assert(zero_loaded,'factory definitions were not explicitly cleared')
 local file=assert(io.open(path,'wb'));file:write('INERT_NOT_IOB');file:close()
 file=assert(io.open(path:gsub('%.iob$','.fly2'),'wb'));file:write('particles { coordinates = 0 }');file:close()
end
function simion.command(command)
 commands=commands+1
 assert(not command:find('refine') and not command:find('fly') and not command:find('fastadj'))
 for index,path in ipairs(spec.bootstrap_paths) do
  local p=pa();p.path=path
  local item={pa=p,ox=0,oy=0,oz=0,_debug_update_size=function() end}
  function item:pa_to_wb_orient(x,y,z)
   local out={};for k=1,3 do out[k]=0;for j,v in ipairs({x,y,z}) do out[k]=out[k]+spec.instances[index].rotation[k][j]*v end end
   return unpack(out)
  end
  function item:pa_to_wb_coords(x,y,z)
   local a,b,c=self:pa_to_wb_orient(x*p.dx_mm,y*p.dy_mm,z*p.dz_mm)
   local placement=spec.instances[index].placement
   return a+placement.x_mm,b+placement.y_mm,c+placement.z_mm
  end
  if command:find('geometry.iob',1,true) then
   local row=spec.instances[index];p.path=row.path
   for k,v in pairs(row.grid) do p[k]=v end
   for property,key in pairs({x='x_mm',y='y_mm',z='z_mm',az='az_deg',el='el_deg',rt='rt_deg',scale='scale'}) do item[property]=row.placement[key] end
  end
  slots[index]=item
 end
end
if failure=='missing' then assert(os.remove(spec.instances[1].path)) end
if failure=='beam' then local file=assert(io.open(spec.empty_particle_control,'wb'));file:write('particles { standard_beam {mass=1} }');file:close() end
if failure=='missing_control' then assert(os.remove(spec.empty_particle_control)) end
if failure=='ambient_fly2' then local file=assert(io.open(spec.output_iob:gsub('%.iob$','.fly2'),'wb'));file:write('particles { standard_beam {mass=1} }');file:close() end
if failure=='wgem' or failure=='hook' then
 local path=spec.output_iob:gsub('%.iob$',failure=='wgem' and '.wgem' or '.lua')
 local file=assert(io.open(path,'wb'));file:write('FORBIDDEN');file:close()
end
arg={SPEC,'build_model',NATIVE_PATH}
local okay,message=pcall(function() dofile(WRAPPER) end)
if failure=='none' then
 assert(okay,message);assert(changes==(independent_oa and 2 or 4))
 arg[2]='verify_model';dofile(WRAPPER)
 local file=assert(io.open(spec.model.report,'rb'));local text=file:read('*a');file:close()
 assert(text:find('PA_ELECTRODE_LABELS_ARE_NOT_VOLTAGES=True',1,true))
 if independent_oa then
  assert(text:find('grounded_shield',1,true) and text:find('intermediate_grid_2',1,true))
  assert(not text:find('frequency_hz=',1,true) and not text:find('reflectron_midgrid',1,true))
 else
  assert(text:find('reflectron_midgrid',1,true) and text:find('frequency_hz=',1,true))
 end
 assert(text:find('not_solved',1,true) and text:find('pulse_mode=',1,true))
else
 assert(not okay,'dangerous profile was accepted');assert(commands==0 and changes==0)
 local needle=failure=='missing' and 'missing before workbench' or failure=='beam' and 'contains a particle'
   or failure=='missing_control' and 'format control missing' or failure=='ambient_fly2' and 'existing FLY2' or 'forbids automatic'
 assert(tostring(message):find(needle),tostring(message))
end
print('INERT_MODEL_PROFILE=PASS CASE='..failure)
'''
                for token, value in (('SPEC', spec), ('NATIVE_PATH', resource_path('native_run_path.lua')),
                                     ('WRAPPER', native_resource_path('build_model_iob.lua'))):
                    program = program.replace(token, json.dumps(value.as_posix()))
                script.write_text(program, encoding='utf-8')
                result = subprocess.run([str(LUA), str(script)], cwd=case, capture_output=True,
                    text=True, encoding='utf-8', timeout=30, check=False)
                with self.subTest(failure=failure):
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIn('INERT_MODEL_PROFILE=PASS', result.stdout)
                    if independent_oa and failure == 'none':
                        readback = (case/'run/results/model_drive_readback.txt').read_text(encoding='utf-8')
                        observed = {}
                        for line in readback.splitlines():
                            match = re.match(r'group="([^"]+)" instance="([^"]+)" domain="([^"]+)" native_label=(\d+) time_us=([^ ]+) voltage_v=([^ ]+) kind="([^"]+)"', line)
                            if match:
                                group, instance, domain, label, time_us, voltage, kind = match.groups()
                                key = instance, group, float(time_us)
                                self.assertNotIn(key, observed)
                                observed[key] = (domain, int(label), float(voltage), kind)
                        rows = model.document['native_drive_rows']
                        self.assertEqual(len(observed), 3*len(rows))
                        for row in rows:
                            target = row['native_targets'][0]
                            for time_us in (0., 10., 12.):
                                expected = row['voltage_v'] if row['kind']=='static' else row['on_voltage_v'] if time_us==10. else row['off_voltage_v']
                                self.assertEqual(observed[row['instance_id'],row['electrode_group_id'],time_us],
                                    (target['domain'],target['electrode_id'],expected,row['kind']))


if __name__ == '__main__':
    unittest.main()
