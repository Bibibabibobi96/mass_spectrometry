"""Direct-field planning, real Lua with PA doubles and inert native orchestration."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_single_reflection_preparation import fixture, release_fixture, rename_author_instances
from integrations.tests.test_single_reflection_fields import multipole_source
from msplatform.workflows.single_reflection_flight.field_plan import (
    KINDS, bind_parent_fields, build_field_plan, _bound_source_audit,
)
from msplatform.backends.simion.field_bank import field_bank
from msplatform.backends.simion.field_identity import frontend_field_identity
from msplatform.backends.simion.field_audit import audit_input_identity, write_audit_spec, reusable_audit
from msplatform.workflows.single_reflection_flight.field_evidence import validate_frozen_generation_metadata
from msplatform.workflows.single_reflection_flight.prepare import prepare
from msplatform.io.file_identity import file_sha256
from msplatform.execution.retention import file_record
from msplatform.backends.simion import pa_family_cache
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key, publish_pa_family_cache

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / 'integrations/workflows/single_reflection_flight'
LUA = Path(shutil.which('lua') or shutil.which('lua5.1') or 'C:/Program Files/SIMION-2020/lua.exe')


_FRONTEND_WORKER_DOUBLE = r'''
"""TEST ONLY: inert file producers around the actual selected canonical worker."""
import json,sys
from pathlib import Path
from msplatform.backends.simion import field_worker as worker

request_path,state_path=map(Path,sys.argv[1:3])
sys.argv=['field_worker',str(request_path)]
state=json.loads(state_path.read_text(encoding='utf-8-sig'))
request=json.loads(request_path.read_text(encoding='utf-8-sig'))
parameters=request['parameters']
worker.inherited_host_token=lambda *args,**kwargs:'INERT_NATIVE_TRANSPORT_ONLY'

def save():
    state_path.write_text(json.dumps(state),encoding='utf-8')

actual_advance=worker.cache.advance_pa_family_cache_transaction

def advance(*args,**kwargs):
    if kwargs.get('record_stage_only'):
        state['stage_accounting']+=1;save()
        if state['accounting_failure']:
            raise OSError('INERT accounting write failed')
    handoff=kwargs.get('producer_handoff')
    if handoff is not None:
        assert parameters['member_id']=='pulse_delta' and parameters['domain_id']=='parent'
        assert set(handoff)=={'schema_version','transaction_record','predecessor_manifest','stopped_receipt','capacity_lease_id','capacity_lease_owner'}
        assert handoff['capacity_lease_id']==parameters['capacity_lease_id']
        assert handoff['capacity_lease_owner']==parameters['capacity_lease_owner']
        assert all(Path(handoff[name]['path']).is_relative_to(Path(parameters['run_directory'])/'inputs')
                   for name in ('transaction_record','predecessor_manifest','stopped_receipt'))
        state['handoff_seen']+=1;save()
        if state['handoff_conflict']:
            raise ValueError('PA producer handoff has another active consumer')
        # These records are deliberately inert. The original governed handoff
        # state machine has separate real tests; this checks exact transport.
        kwargs.pop('producer_handoff')
    result=actual_advance(*args,**kwargs)
    return result
worker.cache.advance_pa_family_cache_transaction=advance

def inert(context,operation,**kwargs):
    arguments=operation['arguments']
    state['native'].append(arguments)
    kwargs['observations'].append(dict(operation_id=operation['operation_id'],stage=operation['stage'],
        receipt=dict(fixture='CONTROLLED_PROCESS_FACTS_NOT_NATIVE_EVIDENCE',
            observation=dict(completed=True,exit_code=0,root_process_id=700+len(state['native']),
                             root_process_started_at_utc_ticks=801))))
    save()
    output=[Path(value) for value in operation['outputs']]
    for path in output:path.parent.mkdir(parents=True,exist_ok=True)
    name=operation['operation_id']
    if name.startswith('gem2pa_'):
        domain=next(row for row in parameters['field_plan']['field_design']['domains']
                    if row['domain_id']==parameters['domain_id'])
        size=8
        for axis in 'xyz':size*=domain['dimensions']['n'+axis]
        assert parameters['capacity_session']['committed_new_bytes']>=parameters['reserved_run_payload_bytes']+size
        output[0].write_text('INERT_RAW_NOT_PA')
    elif name.startswith('refine_'):
        assert state['stages'][-1]=='pa_refine'
        if arguments[6]!='zero_neumann':
            assert Path(arguments[6]).name.startswith('frontend.')
            assert 'generations' in Path(arguments[6]).parts and Path(arguments[6]).exists()
            design=parameters['field_plan']['field_design']
            origins=[','.join(format(row['instance_origin_mm'][axis],'.17g') for axis in 'xyz')
                     for row in design['domains'][:2]]
            assert arguments[7:9]==origins
        output[0].write_text('INERT_WORKING:'+arguments[9])
    elif name.startswith('export_'):
        filename=output[0].name
        target=('frontend.pulse_delta.pa' if state['last_member_only'] else
                'frontend_entrance_refinement.rf_reference.pa' if state['fine'] else 'frontend.rf_reference.pa')
        if state['recovery'] and not state['injected_failure'] and filename==target:
            state['injected_failure']=True;save()
            output[0].write_text('PARTIAL_EXPORT')
            raise RuntimeError('INERT native export failed: '+name)
        output[0].write_bytes(Path(arguments[4]).read_bytes())
    elif name.startswith('audit_'):
        if state['prepared_audit_failure']:
            raise RuntimeError('INERT native audit failed: '+name)
        output[0].write_text(json.dumps(dict(status='pass',fixture='NOT_NATIVE_EVIDENCE')))
    else:raise AssertionError('unexpected native operation: '+name)

worker._native_operation=inert
try:worker.main()
finally:save()
'''


def _legacy_frontend_source_fixture(producer: Path, consumer: Path, cache_root: Path, session_path: Path) -> None:
    """Construct the same old schema2 data through a real governed transaction."""
    from msplatform.backends.simion import pa_family_cache as cache
    from msplatform.backends.simion.resources import native_resource_path
    from msplatform.execution.capacity_session import renew_capacity_session
    from msplatform.io.manifest_records import file_record
    from msplatform.io.file_identity import file_sha256
    receipt = json.loads((producer / 'inputs/frontend_working_field_stage_receipt.json').read_text())
    points = receipt['domains'][0]['working_points']
    design_path = consumer / 'inputs/frontend_field_design.json'
    design = json.loads(design_path.read_text())
    identities = [json.loads(Path(point['cache_identity_record']['path']).read_text(encoding='utf-8-sig')) for point in points]
    assert all(item['geometry'] == identities[0]['geometry'] and item['gem'] == identities[0]['gem'] for item in identities)
    identity = dict(identities[0], working_points=[item['working_points'][0] for item in identities],
                    rf_reference_voltage_v=identities[1]['rf_reference_voltage_v'])
    identity['geometry'] = dict(identity['geometry'], physical_samples=design['domains'][0]['physical_samples'])
    identity['builder_identity'] = dict(identity['builder_identity'], audit='A'*64, field_plan='B'*64, field_stage='C'*64)
    filenames = [*[Path(point['path']).name for point in points], 'frontend_working_fields_audit.json']
    key = cache.canonical_pa_family_cache_key(identity)
    session = json.loads(session_path.read_text(encoding='utf-8-sig'))
    renew_capacity_session(session, protected_cache_keys=[key])
    session_path.write_text(json.dumps(session))
    arguments = dict(owner=producer.name, producer_run_config=producer / 'run_config.json', recovery_policy='none',
        published_pin_reason='Retain standalone frontend fields required by saved instrument workbenches.')
    transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, filenames, **arguments)
    for point in points:
        # Every copied byte is explicitly inert fixture data, never a real PA.
        shutil.copyfile(point['path'], transaction.build_directory / Path(point['path']).name)
    audit_text = json.dumps(dict(status='pass', fixture='legacy_native_boundary_is_inert'))
    (transaction.build_directory / filenames[-1]).write_text(audit_text)
    durable_audit = producer / 'inputs/legacy_fixture_audit.json'
    durable_audit.write_text(audit_text)
    transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, filenames, **arguments)
    verifier = native_resource_path('audit_frontend_working_fields.lua')
    evidence = dict(schema_version=1, role='simion_pa_family_verification', status='pass', cache_key=key,
        inventory_sha256=transaction.inventory_sha256, solver_release='SIMION 2020', verifier_path=str(verifier),
        verifier_sha256=file_sha256(verifier), verification_output_path=str(durable_audit),
        verification_output_sha256=file_sha256(durable_audit))
    publication = cache.advance_pa_family_cache_transaction(cache_root, identity, filenames, verification_evidence=evidence, **arguments)
    original_identity = producer / 'inputs/original_legacy_field_identity.json'
    original_identity.write_text(json.dumps(identity))
    frozen_identity = consumer / 'inputs/frontend_field_source_parent_identity.json'
    frozen_identity.write_bytes(original_identity.read_bytes())
    old = dict(schema_version=2, role='single_reflection_frontend_working_fields', status='success',
        rf_reference_voltage_v=identity['rf_reference_voltage_v'], domains=[dict(domain_id='parent', cache_key=key,
        generation_directory=str(publication.generation_directory), cache_identity_record=file_record(original_identity),
        working_points=[{key: point[key] for key in ('path','kind','bytes','sha256','read_only')} for point in points])])
    (consumer / 'inputs/frontend_field_source_receipt.json').write_text(json.dumps(old))
    request_path = consumer / 'inputs/request.json'
    request = json.loads(request_path.read_text(encoding='utf-8-sig'))
    request['providers']['frontend_field_reuse_members'] = ['carrier_off', 'rf_reference']
    request_path.write_text(json.dumps(request))
    design['working_points'][2]['electrode_voltages_v']['17'] += 1e-12
    design['domains'][0]['physical_samples'][0]['label'] += '_new_audit'
    design_path.write_text(json.dumps(design))


def _seal_frontend_source_fixture(producer: Path, consumer: Path) -> None:
    """Publish real small source-owner metadata for explicitly inert PA fixtures."""
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.terminal_publication import publish_terminal_state
    receipt_path = consumer / 'inputs/frontend_field_source_receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    records = {path.name: file_record(path) for path in (producer / 'inputs').iterdir() if path.is_file()}
    for identity in (consumer / 'inputs').glob('frontend_field_source_*_identity.json'):
        original = producer / 'inputs' / ('original_' + identity.name)
        original.write_bytes(identity.read_bytes())
        records[original.name] = file_record(original)
    original_receipt = producer / 'inputs/selected_frontend_source_receipt.json'
    original_receipt.write_bytes(receipt_path.read_bytes())
    records[original_receipt.name] = file_record(original_receipt)
    outputs = []
    for domain in receipt['domains']:
        for member in domain['working_points']:
            generation = Path((member if receipt['schema_version'] == 3 else domain)['generation_directory'])
            outputs.append(file_record(generation / Path(member['path']).name, 'solver_native_binary'))
            if 'audit_record' in member:
                outputs.append(file_record(Path(member['audit_record']['path']), 'required_evidence'))
        if receipt['schema_version'] == 2:
            outputs.append(file_record(Path(domain['generation_directory']) / 'frontend_working_fields_audit.json'))
    for path in (producer / 'logs').rglob('audit.json'):
        records['audit_' + str(len(records))] = file_record(path)
    config = json.loads((producer / 'run_config.json').read_text(encoding='utf-8-sig'))
    manifest = dict(schema_version=2, role='simulation_run_manifest', status='success',
        run_id=producer.name, project=config['project'], mode=config['mode'],
        run_config=file_record(producer / 'run_config.json'), inputs=records, outputs=outputs,
        formal_eligible=False, validation_scope='inert_publication_fixture_only')
    publish_terminal_state(producer, dict(status='success', run_id=producer.name), manifest)
    frozen = consumer / 'inputs/frontend_field_source_manifest.json'
    frozen.write_bytes((producer / 'run_manifest.json').read_bytes())
    provenance_path = consumer / 'inputs/source_provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8-sig'))
    provenance['input_records']['frontend_fields_manifest'] = dict(file_record(frozen),
        source_path=str(producer / 'run_manifest.json'))
    provenance_path.write_text(json.dumps(provenance), encoding='utf-8')


def prepared(root: Path, *, source=None, entrance_refinement=False, local=False) -> tuple[Path, dict]:
    if local:
        request, run, _, _ = release_fixture(root, local=True)
    else:
        request, run, _ = fixture(root, source=source, entrance_refinement=entrance_refinement)
    prepare(request, run)
    return run, build_field_plan(run / 'inputs', Path(sys.executable))['domains'][0]


class DirectFieldPlanTests(unittest.TestCase):
    def test_plan5_real_members_reuse_same_map_and_reject_renumbered_cache_identity(self):
        from integrations.tests.test_single_reflection_geometry import (
            scientific_inputs, candidate_300mm_fixture, source_fixture,
        )
        from msplatform.backends.simion.geometry import compile_frontend_geometry
        from msplatform.backends.simion.fields import prepare_field_design, POLICY

        for source in (source_fixture(), multipole_source('octupole')):
            with tempfile.TemporaryDirectory() as directory:
                root, oatof = Path(directory), candidate_300mm_fixture()
                options, _ = scientific_inputs({'multipole':source}, oatof, root/'providers')
                keys = []
                for index in range(3):
                    case = root/str(index)
                    case.mkdir()
                    current = copy.deepcopy(options)
                    if index == 2:
                        current['electrode_bindings'] = {instance:{group:native+100 for group,native in mapping.items()}
                            for instance,mapping in current['electrode_bindings'].items()}
                    gems, geometry = compile_frontend_geometry({'multipole':source}, oatof, **current)
                    design = prepare_field_design({'multipole':source}, oatof, geometry,variant_id='three_zone_square',
                        pulse_voltage_policy_id=POLICY,boundary_policy='native_zero_neumann',rf_reference_voltage_v=10000.,
                        frontend_domains={'parent':{'refine_convergence_v':dict(carrier_off=.1,rf_reference=.2,pulse_delta=.3)}})
                    for name, gem in gems.items():
                        path = case/('frontend.gem' if name=='parent' else 'frontend_entrance_refinement.gem')
                        path.write_text(gem,encoding='utf-8',newline='\n')
                        next(row for row in design['domains'] if row['domain_id']==name)['gem_sha256'] = file_sha256(path)
                    (case/'frontend_geometry.json').write_text(json.dumps(geometry),encoding='utf-8')
                    (case/'frontend_field_design.json').write_text(json.dumps(design),encoding='utf-8')
                    destination = case/'components/multipole/resolved_design.json'
                    destination.parent.mkdir(parents=True)
                    destination.write_text(json.dumps(source),encoding='utf-8')
                    plan = build_field_plan(case,Path(sys.executable))['domains'][0]
                    self.assertEqual(len(plan['physical_samples']), len(design['domains'][0]['physical_samples']))
                    keys.append([member['cache_key'] for member in plan['members']])
                self.assertEqual(keys[0],keys[1])
                self.assertTrue(all(before != after for before,after in zip(keys[0],keys[2],strict=True)))

    def test_retired_alias_audit_uses_unique_manifest_bound_durable_small_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, plan = prepared(root)
            member = plan['members'][0]
            audit_plan = dict(plan, **member)
            verifier = ROOT/'src/msplatform/backends/simion/resources/audit_frontend_working_fields.lua'
            producer = root/'producer'
            audit = producer/'logs/parent_carrier_off_fields_audit.json'
            audit.parent.mkdir(parents=True)
            audit.write_text(json.dumps(dict(status='pass',
                audit_input_sha256=audit_input_identity(audit_plan),
                audit_verifier_sha256=file_sha256(verifier))))
            durable = file_record(audit)
            stale = dict(durable, path=str(root/'execution_aliases/retired/logs'/audit.name))
            manifest = dict(run_config=dict(path=str(producer/'run_config.json')),
                inputs=dict(field_audit=durable), outputs=[dict(durable, retention_role='lightweight_optional')])
            bound = _bound_source_audit(manifest, stale)
            audit_plan['frozen_field_source'] = dict(audit_record=bound)
            with patch('msplatform.backends.simion.field_audit.load_pa_family_cache_transaction',
                       side_effect=AssertionError('explicit source must not reread cache or PA')):
                self.assertEqual(reusable_audit(audit_plan, root/'unused_generation', verifier)['path'], str(audit))
            for mutation in ('missing', 'identity', 'ambiguous', 'content'):
                with self.subTest(mutation=mutation):
                    changed = copy.deepcopy(manifest)
                    if mutation == 'missing':
                        changed['inputs'] = {}; changed['outputs'] = []
                    elif mutation == 'identity':
                        changed['inputs']['field_audit']['sha256'] = '0'*64
                        changed['outputs'][0]['sha256'] = '0'*64
                    elif mutation == 'ambiguous':
                        changed['outputs'].append(dict(durable, path=str(root/'other'/audit.name)))
                    else:
                        audit.write_text('{}')
                        audit_plan['frozen_field_source']['audit_record'] = _bound_source_audit(changed, stale)
                        with self.assertRaises(AssertionError):
                            reusable_audit(audit_plan, root/'unused_generation', verifier)
                        continue
                    with self.assertRaisesRegex(ValueError, 'uniquely identity-bound'):
                        _bound_source_audit(changed, stale)

    def test_instance_rename_and_reorder_preserve_full_and_local_native_plans(self):
        for local in (False, True):
            with self.subTest(local=local), tempfile.TemporaryDirectory() as directory:
                reference = None
                for renamed in (False, True):
                    case = Path(directory) / str(renamed)
                    case.mkdir()
                    path, run, request, _ = release_fixture(case, local=local)
                    if renamed:
                        rename_author_instances(path, request)
                    prepare(path, run)
                    inputs = run / 'inputs'
                    actual = ((inputs / 'frontend.gem').read_bytes(),
                              (inputs / 'projected_source.csv').read_bytes(),
                              build_field_plan(inputs, Path(sys.executable)))
                    if reference is None:
                        reference = actual
                    else:
                        self.assertEqual(actual, reference)

    def test_frozen_instance_binding_errors_fail_before_native_field_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            run, _ = prepared(Path(directory))
            path = run / 'inputs/frontend_geometry.json'
            original = json.loads(path.read_text())
            edge = original['composition_plan']['recipe']['connections'][0]
            first, second = edge['upstream']['instance_id'], edge['downstream']['instance_id']
            for change in ('missing_instance', 'unknown_instance', 'swapped_instances',
                           'missing_role', 'collision', 'duplicate_solver_id'):
                geometry = copy.deepcopy(original)
                bindings = geometry['electrode_bindings']
                if change == 'missing_instance': del bindings[first]
                elif change == 'unknown_instance': bindings['unselected'] = bindings.pop(first)
                elif change == 'swapped_instances': bindings[first], bindings[second] = bindings[second], bindings[first]
                elif change == 'missing_role': del bindings[second]['accelerator_repeller_id']
                elif change == 'collision': bindings[second]['grounded_shield_id'] = 1
                else: bindings[first]['2'] = bindings[first]['1']
                path.write_text(json.dumps(geometry), encoding='utf-8')
                with self.subTest(change=change), self.assertRaises(ValueError):
                    build_field_plan(run / 'inputs', Path(sys.executable))
            # Physical rod groups are raw electrode sources now.  Reordering
            # their binding records is valid when their solver IDs remain
            # unique; this must not retain the removed PA+ mode restriction.
            valid = copy.deepcopy(original)
            valid_bindings = valid['electrode_bindings'][first]
            valid_bindings['1'], valid_bindings['2'] = valid_bindings['2'], valid_bindings['1']
            path.write_text(json.dumps(valid), encoding='utf-8')
            self.assertTrue(build_field_plan(run / 'inputs', Path(sys.executable))['domains'])

    def test_downstream_moves_preserve_actual_frontend_inputs_and_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = None
            for case in ('baseline', 'detector', 'reflectron'):
                case_root = root / case
                case_root.mkdir()
                request_path, run, request = fixture(case_root)
                provider_path = request_path.parent / 'oatof.json'
                provider = json.loads(provider_path.read_text())
                if case == 'detector':
                    provider['coordinate_convention']['detector_x'] += 1.0
                elif case == 'reflectron':
                    provider['coordinate_convention']['reflectron_axis'][0] += 1.0
                provider_path.write_text(json.dumps(provider), encoding='utf-8')
                request['providers']['instances']['oatof']['resolved_design'] = file_record(provider_path, recorded_path=Path('oatof.json'))
                request_path.write_text(json.dumps(request), encoding='utf-8')
                prepare(request_path, run)
                inputs = run / 'inputs'
                actual = dict(geometry=json.loads((inputs / 'frontend_geometry.json').read_text()),
                    design=json.loads((inputs / 'frontend_field_design.json').read_text()),
                    gem=(inputs / 'frontend.gem').read_bytes(),
                    plan=build_field_plan(inputs, Path(sys.executable)))
                if baseline is None:
                    baseline = actual
                    continue
                with self.subTest(case=case):
                    self.assertEqual([key for key in baseline['geometry']
                        if baseline['geometry'][key] != actual['geometry'][key]], ['downstream_pa_instances'])
                    self.assertEqual(baseline['gem'], actual['gem'])
                    self.assertEqual(baseline['design'], actual['design'])
                    self.assertEqual(baseline['plan'], actual['plan'])

    def test_frontend_gem_mesh_domain_and_audit_samples_change_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run, baseline = prepared(Path(directory))
            inputs = run / 'inputs'
            design_path, geometry_path = inputs / 'frontend_field_design.json', inputs / 'frontend_geometry.json'
            original_design = json.loads(design_path.read_text())
            original_geometry = json.loads(geometry_path.read_text())
            gem_path = inputs / 'frontend.gem'
            original_gem = gem_path.read_bytes()
            for case in ('gem', 'mesh', 'domain', 'sample_position', 'sample_electrode'):
                design, geometry = copy.deepcopy(original_design), copy.deepcopy(original_geometry)
                gem_path.write_bytes(original_gem)
                if case == 'gem':
                    gem_path.write_bytes(original_gem.replace(b'e(1)', b'e(2)', 1))
                    self.assertNotEqual(gem_path.read_bytes(), original_gem)
                    design['domains'][0]['gem_sha256'] = file_sha256(gem_path)
                elif case == 'mesh':
                    design['domains'][0]['cell_mm_xyz']['x'] *= 2
                    geometry['numerical_domains']['parent']['cell_mm_xyz'] = design['domains'][0]['cell_mm_xyz']
                elif case == 'domain':
                    design['domains'][0]['dimensions']['nx'] += 1
                    geometry['numerical_domains']['parent']['dimensions'] = design['domains'][0]['dimensions']
                elif case == 'sample_position':
                    design['domains'][0]['physical_samples'][0]['gu'][0] += 1
                else:
                    samples = design['domains'][0]['physical_samples']
                    samples[0]['electrode_id'], samples[-1]['electrode_id'] = (
                        samples[-1]['electrode_id'], samples[0]['electrode_id'])
                design_path.write_text(json.dumps(design), encoding='utf-8')
                geometry_path.write_text(json.dumps(geometry), encoding='utf-8')
                with self.subTest(case=case):
                    assertion = self.assertEqual if case.startswith('sample_') else self.assertNotEqual
                    assertion([m['cache_key'] for m in baseline['members']],
                        [m['cache_key'] for m in build_field_plan(inputs, Path(sys.executable))['domains'][0]['members']])

    def test_two_rf_sources_preserve_scope_and_bind_explicit_member_boundary(self):
        import hashlib
        from integrations.tests.test_single_reflection_geometry import multi_inputs, quadrupole_source, candidate_300mm_fixture
        from msplatform.backends.simion.geometry import compile_frontend_geometry
        from msplatform.backends.simion.fields import prepare_field_design, POLICY
        from msplatform.workflows.single_reflection_flight.field_plan import _check_source_physics
        from msplatform.backends.simion.field_identity import _member_projection, _parent_boundary
        sources = [quadrupole_source(r0=4., dc=1., frequency_hz=1e6, phase_rad=.1),
                   quadrupole_source(r0=4.5, dc=2., frequency_hz=1.1e6, phase_rad=.2)]
        oatof = candidate_300mm_fixture()
        arguments = multi_inputs(sources, oatof, names=['a', 'b'])
        arguments['numerical_domains']['entrance_refinement'] = copy.deepcopy(arguments['numerical_domains']['parent'])
        arguments['numerical_domains']['entrance_refinement']['guard_cells'] = 1
        gems, geometry = compile_frontend_geometry(dict(zip(['a','b'], sources, strict=True)), oatof, **arguments)
        convergence = dict(carrier_off=.1, rf_reference=.1, pulse_delta=.1)
        design = prepare_field_design(dict(zip(['a','b'], sources, strict=True)), oatof, geometry,
            variant_id='three_zone_square', pulse_voltage_policy_id=POLICY, boundary_policy='native_zero_neumann',
            rf_reference_voltage_v=10000., frontend_domains={
                name: dict(refine_convergence_v=convergence) for name in geometry['numerical_domains']})
        for domain in design['domains']:
            domain['gem_sha256'] = hashlib.sha256(gems[domain['domain_id']].encode()).hexdigest().upper()
        parents = {point.get('working_point_id') or point['kind']: dict(cache_key='A'*64,
            record=dict(kind=point['kind'], working_point_id=point.get('working_point_id'),
                path='frontend.'+(point.get('working_point_id') or point['kind'])+'.pa', bytes=10, sha256='B'*64))
            for point in design['working_points']}
        member_id = 'rf_reference_02'
        identity = dict(frontend_field_identity(design, 'parent', member_id=member_id),
            simion_identity={'pure': True}, builder_identity=dict(operating_builder='C'*64, exporter='D'*64))
        member = dict(member_id=member_id, identity=identity, frozen_field_source=dict(
            identity=copy.deepcopy(identity), physical_point=identity['working_points'][0], source_schema_version=3))
        _check_source_physics(member)
        # Each fine member consumes only its corresponding published parent field.
        boundary_identity = dict(identity, boundary_policy=_parent_boundary(
            design['domains'][0]['instance_origin_mm'], parents[member_id]))
        self.assertEqual(boundary_identity['boundary_policy']['parent_working_points'][0]['name'], 'frontend.rf_reference_02.pa')
        historical = copy.deepcopy(boundary_identity)
        historical['boundary_policy']['parent_working_points'].insert(0,
            dict(kind='rf_reference', working_point_id='rf_reference_01', name='frontend.rf_reference_01.pa',bytes=10,sha256='E'*64))
        self.assertEqual(_member_projection(historical, identity['working_points'][0], member_id=member_id), boundary_identity)
        member['frozen_field_source']['identity']['working_points'][0]['electrode_voltages_v']['1'] = 123.
        with self.assertRaisesRegex(ValueError, 'physical identity'):
            _check_source_physics(member)

    def test_actual_plan_has_only_three_operating_fields_and_no_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            # Fixed bare fixture: 32 real rod pieces plus 25 OA electrodes.
            self.assertEqual(len(plan['physical_samples']), 32 + 25)
            self.assertEqual([p['kind'] for p in plan['working_points']], list(KINDS))
            self.assertEqual(len(plan['members']), 3)
            self.assertTrue(all(len(member['filenames']) == 1 for member in plan['members']))
            self.assertEqual(set(plan['members'][1]['identity']), {'geometry', 'gem', 'working_points', 'mesh', 'grid_phase',
                'surface', 'boundary_policy', 'rf_reference_voltage_v', 'simion_identity', 'builder_identity'})
            self.assertFalse(any(name.endswith(('.pa0', '.pa#', '.pa+')) for member in plan['members'] for name in member['filenames']))
            (run / 'inputs/source.csv').write_text('unrelated source change')
            self.assertEqual(plan, build_field_plan(run / 'inputs', Path(sys.executable))['domains'][0])
            bank = field_bank(json.loads((run/'inputs/frontend_field_design.json').read_text()), ['parent'])['dynamic_roles'][0]
            self.assertEqual(bank['instance_index'], 1)
            self.assertEqual(bank['rf_differential_pa_basenames'], ['frontend.rf_reference.pa'])
            path = run / 'audit.tsv'
            write_audit_spec(plan, run / 'raw.pa#', run, path)
            self.assertEqual(sum(line.startswith('physical\t') for line in path.read_text().splitlines()), 32 + 25)

    def test_actual_voltage_convergence_boundary_and_geometry_change_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            path = run / 'inputs/frontend_field_design.json'
            original = json.loads(path.read_text())
            for field in ('voltage', 'convergence', 'reference'):
                design = copy.deepcopy(original)
                if field == 'voltage': design['working_points'][0]['electrode_voltages_v']['1'] += 1
                elif field == 'convergence': design['domains'][0]['refine_convergence_v']['carrier_off'] *= 2
                else: design['rf_reference_voltage_v'] *= 2
                path.write_text(json.dumps(design))
                self.assertNotEqual([m['cache_key'] for m in plan['members']], [m['cache_key'] for m in build_field_plan(run / 'inputs', Path(sys.executable))['domains'][0]['members']])
            for field in ('boundary', 'grid', 'missing_voltage', 'missing_sample', 'duplicate_sample', 'nonfinite'):
                design = copy.deepcopy(original)
                if field == 'boundary': design['domains'][0]['boundary_policy'] = 'zero_dirichlet'
                elif field == 'grid': design['domains'][0]['dimensions']['nx'] += 1
                elif field == 'missing_voltage': del design['working_points'][1]['electrode_voltages_v']['35']
                elif field == 'missing_sample': design['domains'][0]['physical_samples'].pop(0)
                elif field == 'duplicate_sample': design['domains'][0]['physical_samples'][-1] = design['domains'][0]['physical_samples'][0]
                else: design['domains'][0]['refine_convergence_v']['rf_reference'] = float('nan')
                path.write_text(json.dumps(design))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    build_field_plan(run / 'inputs', Path(sys.executable))

    def test_gem_drift_rejected_and_actual_builder_changes_key(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            module = 'msplatform.workflows.single_reflection_flight.field_plan.file_sha256'
            def changed_builder(path):
                return '0'*64 if Path(path).name == 'build_dirichlet_patch_operating_pa.lua' else file_sha256(path)
            with patch(module, side_effect=changed_builder):
                self.assertNotEqual([m['cache_key'] for m in plan['members']], [m['cache_key'] for m in build_field_plan(run / 'inputs', Path(sys.executable))['domains'][0]['members']])
            with (run / 'inputs/frontend.gem').open('a') as stream:
                stream.write('\n; changed geometry\n')
            with self.assertRaisesRegex(ValueError, 'GEM identity'):
                build_field_plan(run / 'inputs', Path(sys.executable))

    def test_local_plan_keeps_actual_11_to_35_namespace_and_only_off_pulse_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory), local=True)
            self.assertEqual(plan['physical_electrode_ids'], list(range(11, 36)))
            self.assertEqual(len(plan['physical_samples']), 25)
            self.assertEqual([row['kind'] for row in plan['working_points']], ['carrier_off','pulse_delta'])
            self.assertTrue(all('rf_reference_voltage_v' not in member['identity'] for member in plan['members']))
            for point in plan['working_points']:
                indexed = list(map(float, point['voltage_argument'].split(',')))
                self.assertEqual(len(indexed), 35)
                self.assertEqual(indexed[:10], [0.]*10)
                self.assertEqual(indexed[10:], [point['electrode_voltages_v'][str(i)] for i in range(11,36)])
            bank = field_bank(json.loads((run/'inputs/frontend_field_design.json').read_text()), ['parent'])['dynamic_roles'][0]
            self.assertNotIn('rf_reference_voltage_v', bank)
            self.assertNotIn('rf_differential_pa_basename', bank)
            design = json.loads((run/'inputs/frontend_field_design.json').read_text())
            for defect in ('invented_rf_reference','invented_electrode'):
                changed = copy.deepcopy(design)
                if defect == 'invented_rf_reference':
                    changed['rf_reference_voltage_v'] = 1.
                else:
                    changed['working_points'][0]['electrode_voltages_v']['1'] = 0.
                (run/'inputs/frontend_field_design.json').write_text(json.dumps(changed))
                with self.subTest(defect=defect), self.assertRaises(ValueError):
                    build_field_plan(run/'inputs', Path(sys.executable))

    def test_fine_identity_uses_published_parent_and_guard_is_not_a_solve_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, run, _ = fixture(root, entrance_refinement=True)
            prepare(request, run)
            inputs = run / 'inputs'
            bundle = build_field_plan(inputs, Path(sys.executable))
            parent, fine = bundle['domains']
            authority = {member['member_id']: dict(cache_key=member['cache_key'], record=dict(
                kind=member['working_points'][0]['kind'], path='frontend.'+member['member_id']+'.pa',
                bytes=100, sha256='A'*64)) for member in parent['members']}
            bound = bind_parent_fields(fine, authority)
            design = json.loads((inputs/'frontend_field_design.json').read_text())
            for member in bound['members']:
                projected = frontend_field_identity(design, 'entrance_refinement',
                    member_id=member['member_id'], parent_fields=authority)
                self.assertEqual(projected, {key: value for key, value in member['identity'].items()
                    if key not in ('simion_identity', 'builder_identity')})
                self.assertEqual(len(member['identity']['boundary_policy']['parent_working_points']), 1)
            drift = copy.deepcopy(authority)
            drift['rf_reference']['record']['sha256'] = 'B'*64
            changed = bind_parent_fields(fine, drift)
            self.assertEqual(bound['members'][0]['cache_key'], changed['members'][0]['cache_key'])
            self.assertNotEqual(bound['members'][1]['cache_key'], changed['members'][1]['cache_key'])
            self.assertEqual(bound['members'][2]['cache_key'], changed['members'][2]['cache_key'])

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_actual_lua_audit_opens_one_pa_and_rejects_wrong_ids_voltages_mask_and_grid(self):
        for project in ('quadrupole', 'hexapole', 'octupole'):
            with self.subTest(project=project):
                self.check_lua_audit(multipole_source(project))

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_fine_lua_audit_accepts_actual_subset_but_checks_full_voltage_namespace(self):
        self.check_lua_audit(multipole_source('octupole'), entrance_refinement=True)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_public_operating_builder_preserves_sparse_ids_and_does_not_create_padding_metal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root/'sparse.lua'
            harness.write_text(r"""
local helper=arg[1]
local store={};local refinements=0
local function clone(points)
 local result={};for k,v in pairs(points) do result[k]={v[1],v[2]} end;return result
end
store['raw.pa#']={['0,0,0']={11,true},['1,1,1']={12,true},['2,2,2']={35,true}}
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path)
 local points=clone(assert(store[path]))
 local pa={nx=3,ny=3,nz=3,dx_mm=.25,dy_mm=.25,dz_mm=.05}
 function pa:point(x,y,z,value,metal)
  local key=x..','..y..','..z
  if value~=nil then points[key]={value,metal};return end
  local item=points[key] or {0,false};return item[1],item[2]
 end
 function pa:save(name) store[name]=clone(points) end
 function pa:close() end
 function pa:refine(options)
  refinements=refinements+1;assert(options.convergence==.003)
  assert(points['0,0,0'][1]==0 and points['1,1,1'][1]==2140 and points['2,2,2'][1]==372)
 end
 return pa
end
local volts={};for i=1,35 do volts[i]=0 end;volts[12]=2140;volts[35]=372
arg={'raw.pa#','working.pa0','zero_neumann','0,0,0','0,0,0',table.concat(volts,','),'.003'}
dofile(helper)
assert(refinements==1)
local metal=0
for _,point in pairs(store['working.pa0']) do if point[2] then metal=metal+1 end end
assert(metal==3,'padding parameter slots must never create physical electrodes')
assert(store['raw.pa#']['1,1,1'][1]==12,'raw IDs changed')
""",encoding='utf-8',newline='\n')
            result = subprocess.run([str(LUA),str(harness),
                str(ROOT/'src/msplatform/backends/simion/resources/build_dirichlet_patch_operating_pa.lua')],
                cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_local_lua_audit_uses_sparse_real_ids_without_a_zero_rf_member(self):
        self.check_lua_audit(None, local=True)

    def check_lua_audit(self, source, *, entrance_refinement=False, local=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, plan = prepared(root, source=source, entrance_refinement=entrance_refinement, local=local)
            if entrance_refinement:
                plan = build_field_plan(run / 'inputs', Path(sys.executable))['domains'][1]
            spec = root / 'spec.tsv'
            write_audit_spec(plan, root / 'raw.pa#', root, spec)
            # Feed every actual provider piece / voltage table to a bounded PA double.
            rows = []
            for sample in plan['physical_samples']:
                rows.append("['"+','.join(map(str, sample['gu']))+"']="+str(sample['electrode_id']))
            tables = []
            for point in plan['working_points']:
                tables.append("['"+point['kind']+"']={"+point['voltage_argument']+"}")
            harness = root / 'audit.lua'
            harness.write_text("local ids={"+','.join(rows)+"}\nlocal volts={"+','.join(tables)+"}\n"+r'''
local helper,spec,report,fault=arg[1],arg[2],arg[3],arg[4]
local active=0
simion={pas={}}
function simion.pas:close() assert(active==0) end
function simion.pas:open(path)
 active=active+1;assert(active==1,'audit must not retain multiple fields')
 local kind=path:match('frontend[^/\\\\]*%.([^%.]+)%.pa$')
 local pa={potential_type='electric',nx=NX,ny=NY,nz=NZ,dx_mm=DX,dy_mm=DY,dz_mm=DZ}
 if fault=='grid' and kind then pa.nx=pa.nx+1 end
 function pa:point(x,y,z)
  local id=assert(ids[x..','..y..','..z])
  local value=kind and volts[kind][id] or id
  if fault=='roundoff' and kind then value=value+1e-12 end
  if fault=='id' and not kind then value=value+1 end
  if fault=='voltage' and kind then value=value+1 end
  if fault=='nonfinite' and kind then value=0/0 end
  return value,not(fault=='mask' and kind)
 end
 function pa:close() active=active-1 end
 return pa
end
arg={spec,report};dofile(helper);assert(active==0)
'''.replace('NX', str(plan['grid'][0])).replace('NY', str(plan['grid'][1])).replace('NZ', str(plan['grid'][2]))
                .replace('DX', repr(plan['grid'][3])).replace('DY', repr(plan['grid'][4])).replace('DZ', repr(plan['grid'][5])),
                encoding='utf-8', newline='\n')
            for point in plan['working_points']:
                single = dict(plan, working_points=[point])
                write_audit_spec(single, root/'raw.pa#', root, spec)
                for fault in ('none', 'roundoff', 'id', 'voltage', 'mask', 'grid', 'nonfinite'):
                    result = subprocess.run([str(LUA), str(harness), str(ROOT / 'src/msplatform/backends/simion/resources/audit_frontend_working_fields.lua'),
                        str(spec), str(root / 'audit.json'), fault], cwd=root, capture_output=True,
                        text=True, encoding='utf-8', timeout=30, check=False)
                    with self.subTest(fault=fault):
                        self.assertEqual(result.returncode == 0, fault in ('none', 'roundoff'), result.stderr)
            self.assertEqual(json.loads((root / 'audit.json').read_text())['physical_samples'],
                             len(plan['physical_samples']))

    def test_held_off_to_timed_adds_only_pulse_cache_member(self):
        plans = []
        for held in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                path, run, request = fixture(Path(directory))
                request['flight'] = dict(pulse={'mode':'held_off'} if held else {'mode':'timed','time_us':10.,'width_us':3.},
                    maximum_flight_us=200.,maximum_step_us=.001,trajectory_quality=10,rf_steps_per_period=40)
                request['numerics']['frontend_domains']['parent']['refine_convergence_v']['pulse_delta'] = .9 if held else .003
                path.write_text(json.dumps(request))
                prepare(path,run)
                design=json.loads((run/'inputs/frontend_field_design.json').read_text())
                domain=build_field_plan(run/'inputs',Path(sys.executable))['domains'][0]
                plans.append({m['member_id']:m['cache_key'] for m in domain['members']})
                row=field_bank(design,['parent'])['dynamic_roles'][0]
                self.assertEqual('pulse_delta_pa_basename' in row,not held)
        self.assertEqual(plans[0],{k:v for k,v in plans[1].items() if k!='pulse_delta'})
        self.assertEqual(set(plans[1])-set(plans[0]),{'pulse_delta'})


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell Core unavailable')
class FrozenFieldSourcePlanTests(unittest.TestCase):
    def _declare_frozen_parent_source(self, inputs: Path, plan: dict) -> dict:
        identity = copy.deepcopy(plan['members'][0]['identity'])
        identity['working_points'] = [member['identity']['working_points'][0] for member in plan['members']]
        if 'rf_reference_voltage_v' in plan['members'][1]['identity']:
            identity['rf_reference_voltage_v'] = plan['members'][1]['identity']['rf_reference_voltage_v']
        identity['geometry']['physical_samples'] = copy.deepcopy(plan['physical_samples'])
        identity['builder_identity'].update(field_plan='A'*64, field_stage='B'*64, audit='C'*64)
        filenames = [point['filename'] for point in plan['working_points']] + ['frontend_working_fields_audit.json']
        identity_path = inputs / 'frontend_field_source_parent_identity.json'
        identity_path.write_text(json.dumps(identity), encoding='utf-8')
        payload = inputs.parent.parent / 'source_payload'
        payload.mkdir()
        for index, filename in enumerate(filenames):
            (payload / filename).write_bytes(bytes([index]))
        publication = publish_pa_family_cache(inputs.parent.parent / 'source_cache', identity,
            payload, filenames, recovery_policy='none')
        inventory = {row['name']: row for row in publication.manifest['files']}
        records = [dict(kind=point['kind'], path=f'C:/producer/simion/frontend_working_fields/{point["filename"]}',
                        bytes=inventory[point['filename']]['bytes'], sha256=inventory[point['filename']]['sha256'], read_only=True)
                   for point in plan['working_points']]
        receipt = dict(schema_version=2, role='single_reflection_frontend_working_fields', status='success',
            **({'rf_reference_voltage_v': identity['rf_reference_voltage_v']} if 'rf_reference_voltage_v' in identity else {}), domains=[dict(domain_id='parent',
                cache_key=canonical_pa_family_cache_key(identity), generation_directory=str(publication.generation_directory),
                working_points=records, cache_identity_record=file_record(identity_path))])
        (inputs / 'frontend_field_source_receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        manifest_path = inputs / 'frontend_field_source_manifest.json'
        manifest_path.write_text(json.dumps(
            dict(role='simulation_run_manifest', outputs=[file_record(identity_path)])),
            encoding='utf-8')
        provenance_path = inputs / 'source_provenance.json'
        provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
        provenance.setdefault('input_records', {})['frontend_fields_manifest'] = {
            **file_record(manifest_path), 'source_path': 'C:/producer/run_manifest.json'}
        provenance_path.write_text(json.dumps(provenance), encoding='utf-8')
        request_path = inputs / 'request.json'
        request = json.loads(request_path.read_text())
        request['providers']['frontend_fields'] = {'path': 'declared-source.json', 'bytes': 1, 'sha256': 'E' * 64}
        request_path.write_text(json.dumps(request), encoding='utf-8')
        return identity

    def test_explicit_frozen_source_preserves_producer_identity_and_allows_orchestration_hash_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            identity = self._declare_frozen_parent_source(run / 'inputs', plan)
            actual = build_field_plan(run / 'inputs', Path(sys.executable))
            self.assertTrue(actual['frozen_field_source'])
            self.assertEqual(actual['domains'][0]['members'][0]['frozen_field_source']['identity'], identity)
            self.assertEqual(actual['domains'][0]['members'][0]['frozen_field_source']['cache_key'], canonical_pa_family_cache_key(identity))

    def test_explicit_members_reuse_exact_carrier_rf_but_never_changed_pulse(self):
        with tempfile.TemporaryDirectory() as directory:
            run, original = prepared(Path(directory))
            source_identity = self._declare_frozen_parent_source(run/'inputs', original)
            design_path = run/'inputs/frontend_field_design.json'
            design = json.loads(design_path.read_text())
            # Audit sample presentation and sampling do not change solved PA physics.
            design['domains'][0]['physical_samples'][0]['label'] += '_new'
            design['domains'][0]['physical_samples'][0]['gu'][0] += 1
            design['working_points'][2]['electrode_voltages_v']['17'] += 1e-12
            design_path.write_text(json.dumps(design))
            with self.assertRaisesRegex(ValueError, 'pulse_delta.*physical identity'):
                build_field_plan(run/'inputs', Path(sys.executable))
            request_path = run/'inputs/request.json'
            request = json.loads(request_path.read_text())
            request['providers']['frontend_field_reuse_members'] = ['carrier_off', 'rf_reference']
            request_path.write_text(json.dumps(request))
            current = build_field_plan(run/'inputs', Path(sys.executable))['domains'][0]
            for index in (0, 1):
                member = current['members'][index]
                source = member['frozen_field_source']
                self.assertEqual(source['cache_key'], canonical_pa_family_cache_key(source_identity))
                self.assertEqual(member['identity'], original['members'][index]['identity'])
            self.assertNotIn('frozen_field_source', current['members'][2])
            self.assertNotEqual(current['members'][2]['cache_key'], original['members'][2]['cache_key'])
            before = dict(original, identity=original['members'][0]['identity'], working_points=[original['working_points'][0]])
            after = dict(current, identity=current['members'][0]['identity'], working_points=[current['working_points'][0]])
            self.assertNotEqual(audit_input_identity(before), audit_input_identity(after))
            after['physical_samples'] = copy.deepcopy(before['physical_samples'])
            after['physical_samples'][0]['label'] += '_only_display'
            self.assertEqual(audit_input_identity(before), audit_input_identity(after))

    def test_frozen_source_is_selected_only_by_declared_provider_and_rejects_drift_or_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory), local=True)
            inputs = run / 'inputs'
            # An undeclared stray receipt cannot change the route.
            (inputs / 'frontend_field_source_receipt.json').write_text('{}', encoding='utf-8')
            self.assertFalse(build_field_plan(inputs, Path(sys.executable))['frozen_field_source'])
            identity = self._declare_frozen_parent_source(inputs, plan)
            identity['builder_identity']['operating_builder'] = 'F' * 64
            identity_path = inputs / 'frontend_field_source_parent_identity.json'
            identity_path.write_text(json.dumps(identity), encoding='utf-8')
            receipt_path = inputs / 'frontend_field_source_receipt.json'
            receipt = json.loads(receipt_path.read_text())
            receipt['domains'][0]['cache_key'] = canonical_pa_family_cache_key(identity)
            receipt['domains'][0]['cache_identity_record'] = file_record(identity_path)
            receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'cache key|physical identity'):
                build_field_plan(inputs, Path(sys.executable))
            identity_path.unlink()
            with self.assertRaisesRegex(ValueError, 'identity copy differs'):
                build_field_plan(inputs, Path(sys.executable))

    def test_frozen_generation_metadata_uses_public_metadata_without_reading_pa_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, plan = prepared(root)
            self._declare_frozen_parent_source(run / 'inputs', plan)
            source_plan = build_field_plan(run / 'inputs', Path(sys.executable))['domains'][0]['members'][0]
            source_plan = dict(source_plan['frozen_field_source'], filenames=source_plan['frozen_field_source']['cache_filenames'],
                frozen_field_source=dict(working_points=[source_plan['frozen_field_source']['record']]))
            generation = Path(source_plan['generation_directory'])
            with patch.object(pa_family_cache, 'file_sha256', side_effect=AssertionError('PA payload read')):
                manifest = validate_frozen_generation_metadata(source_plan, generation)
            self.assertEqual(manifest['cache_key'], source_plan['cache_key'])


class DirectFieldStageTests(unittest.TestCase):
    def test_missing_member_topup_uses_exact_stage_floor_and_does_not_repeat_when_sufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'commitment.ps1'
            script.write_text(r'''
param($Source)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$blocks=@($ast.FindAll({param($node)
 $node-is[Management.Automation.Language.IfStatementAst]-and
 $node.Clauses[0].Item1.Extent.Text-eq'[long]$CapacitySession.Value.committed_new_bytes-lt$memberCommitment'
},$true))
if($blocks.Count-ne1){throw 'missing-member capacity boundary must be unique'}
$operation=[scriptblock]::Create($blocks[0].Extent.Text)
$script:renewals=@()
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
 $script:renewals+=,$RemainingCommittedNewBytes
 $Session.committed_new_bytes=$RemainingCommittedNewBytes
 [pscustomobject]@{session=$Session}
}
$Python='unused';$RepoRoot='unused'
# Observed N2 metadata-only accounting: two 56-byte PA headers, two
# generation manifests and their pointers, beyond the exact 8*N arrays.
[long]$array=679L*150L*6456L*8L
[long]$ReservedRunPayloadBytes=104060026
[long]$initial=$ReservedRunPayloadBytes+5L*$array
[long]$published=2L*$array+56L*2L+2830L+2929L+181L*2L
[long]$memberCommitment=$ReservedRunPayloadBytes+3L*$array
$session=[pscustomobject]@{committed_new_bytes=($initial-$published)}
$CapacitySession=[ref]$session
$shortfall=$memberCommitment-$session.committed_new_bytes
&$operation
if($shortfall-ne6233-or$script:renewals.Count-ne1-or$script:renewals[0]-ne15885106426L){throw 'incorrect real N2 topup'}
&$operation
if($script:renewals.Count-ne1){throw 'sufficient commitment was renewed again'}
[pscustomobject]@{shortfall=$shortfall;committed=$session.committed_new_bytes;updates=$script:renewals.Count}|ConvertTo-Json
''', encoding='utf-8', newline='\n')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(script), str(WORKFLOW / 'execute.ps1')],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(shortfall=6233, committed=15885106426, updates=1))

    def test_explicit_source_two_domains_reuses_six_members_without_probe_or_native(self):
        self.run_stage_fixture(recovery=False, fine=True, frozen_source=True)

    def test_legacy_source_reuses_exact_carrier_rf_and_builds_only_changed_pulse(self):
        self.run_stage_fixture(recovery=False, frozen_source=True, legacy_partial=True)

    def test_changed_audit_only_reserves_raw_before_native_and_releases_to_zero(self):
        self.run_stage_fixture(recovery=False, frozen_source=True, audit_refresh=True, reserve_failure=True)

    def test_miss_then_hit_real_public_transaction_without_private_copies(self):
        self.run_stage_fixture(recovery=False)

    def test_partial_export_stays_in_scratch_and_retry_rebuilds_only_missing_fields(self):
        self.run_stage_fixture(recovery=True)

    def test_two_ready_members_are_not_refined_when_only_last_member_needs_completion(self):
        self.run_stage_fixture(recovery=True, last_member_only=True)

    def test_failed_stage_accounting_defers_capacity_without_masking_native_error(self):
        self.run_stage_fixture(recovery=True, accounting_failure=True)

    def test_prepared_audit_failure_does_not_repeat_accounting_or_defer(self):
        self.run_stage_fixture(recovery=False, prepared_audit_failure=True)

    def test_complete_transaction_reentry_does_not_charge_existing_generation_twice(self):
        self.run_stage_fixture(recovery=False, prepared_resume=True)

    def test_two_domains_use_same_kind_common_parent_and_hit_without_native(self):
        self.run_stage_fixture(recovery=False, fine=True)

    def test_producer_handoff_routes_only_first_begin_with_current_lease(self):
        self.run_stage_fixture(recovery=False, producer_handoff=True)

    def test_handoff_conflict_is_not_masked_by_empty_domain_cleanup(self):
        self.run_stage_fixture(recovery=False, producer_handoff=True, handoff_conflict=True)

    def test_partial_fine_export_reuses_parent_and_complete_fine_members(self):
        self.run_stage_fixture(recovery=True, fine=True)

    def test_retry_rejects_damaged_common_parent_before_fine_native(self):
        self.run_stage_fixture(recovery=True, fine=True, private_damage=True)

    def test_local_two_fields_use_the_same_cache_and_have_zero_native_on_hit(self):
        self.run_stage_fixture(recovery=False, local=True)

    def test_parent_hit_fine_miss_preserves_parent_key_and_cumulative_capacity(self):
        self.run_stage_fixture(recovery=False, fine=True, fine_change=True)

    def test_capacity_topup_rejection_stops_before_any_native(self):
        self.run_stage_fixture(recovery=False, fine=True, budget_failure=True)

    def test_zero_private_reservation_publishes_common_fields(self):
        self.run_stage_fixture(recovery=False, fine=True, reserve_failure=True)

    def test_unknown_or_missing_native_receipt_retains_owned_geometry_and_primary_failure(self):
        for fault in ('unknown', 'missing'):
            with self.subTest(completion_fault=fault):
                self.run_stage_fixture(recovery=False, completion_fault=fault)

    def run_stage_fixture(self, *, recovery, prepared_resume=False, fine=False, fine_change=False,
                          budget_failure=False, reserve_failure=False, private_damage=False, local=False,
                          frozen_source=False, legacy_partial=False, audit_refresh=False, producer_handoff=False,
                          handoff_conflict=False, accounting_failure=False, prepared_audit_failure=False,
                          last_member_only=False, completion_fault=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = prepared(root, entrance_refinement=fine, local=local)
            (run / 'logs').mkdir(exist_ok=True)
            from msplatform.execution.inputs import enumerate_python_sources, freeze_file
            from msplatform.execution.capacity_ledger import initialize_capacity_ledger, record_capacity_object
            from msplatform.execution.capacity_session import create_capacity_session
            artifact_root = root / 'artifacts'
            destination = artifact_root / 'projects/instrument_assembly/runs/20261110_120000__test__python__frontend-first'
            destination.parent.mkdir(parents=True)
            shutil.move(run, destination)
            run = destination
            cache_root = artifact_root / 'common/simion/pa_family_cache'
            initialize_capacity_ledger(artifact_root, objects=[])
            config = dict(schema_version=2, project='instrument_assembly', run_id=run.name, mode='inert_frontend',
                capacity_ledger_lifecycle=dict(schema_version=1, enabled=True, artifact_root=str(artifact_root),
                                               light_evidence_budget_bytes=1048576))
            (run / 'run_config.json').write_text(json.dumps(config))
            record_capacity_object(artifact_root, path=run, object_class='rebuildable_payload', bytes_count=0,
                status='writing', owner='current-workflow-owner', review_deadline='2099-12-31', recovery_reason='Controlled inert frontend fixture')
            session = create_capacity_session(artifact_root, run, owner='current-workflow-owner', committed_new_bytes=1024**4)
            (root / 'capacity.json').write_text(json.dumps(session))
            snapshot = run / 'inputs/runtime_snapshot'
            for relative in enumerate_python_sources(ROOT, package_roots=['src/msplatform'],
                    resource_suffixes=['.json','.ps1','.lua','.gem','.m','.iob','.pa0','.pa']):
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                freeze_file(ROOT / relative, target)
            bootstrap = "import sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv.pop(3))\n"
            (root / 'inert_frontend_worker.py').write_text(bootstrap + _FRONTEND_WORKER_DOUBLE, encoding='utf-8')
            import inspect
            source_bootstrap = "import sys,json\nfrom pathlib import Path\nsys.path.insert(0,sys.argv.pop(3))\n"
            (root / 'seal_source_fixture.py').write_text(source_bootstrap + inspect.getsource(_seal_frontend_source_fixture)
                + "\n_seal_frontend_source_fixture(Path(sys.argv[1]),Path(sys.argv[2]))\n", encoding='utf-8')
            legacy_bootstrap = "import sys,json,shutil\nfrom pathlib import Path\nsys.path.insert(0,sys.argv.pop(5))\n"
            (root / 'legacy_source_fixture.py').write_text(legacy_bootstrap + inspect.getsource(_legacy_frontend_source_fixture)
                + "\n_legacy_frontend_source_fixture(*map(Path,sys.argv[1:5]))\n", encoding='utf-8')
            if prepared_audit_failure:
                from msplatform.execution.capacity_session import renew_capacity_session
                plan = build_field_plan(run / 'inputs', Path(sys.executable))['domains'][0]['members'][0]
                renew_capacity_session(session, protected_cache_keys=[plan['cache_key']])
                arguments = dict(owner=run.name, producer_run_config=run / 'run_config.json', recovery_policy='none',
                    published_pin_reason='Retain standalone frontend fields required by saved instrument workbenches.')
                transaction = pa_family_cache.advance_pa_family_cache_transaction(cache_root, plan['identity'], plan['filenames'], **arguments)
                (transaction.build_directory / plan['filenames'][0]).write_text('INERT_ALREADY_ACCOUNTED_PAYLOAD')
                transaction = pa_family_cache.advance_pa_family_cache_transaction(cache_root, plan['identity'], plan['filenames'], **arguments)
                self.assertEqual((transaction.status, transaction.action_required), ('building', 'verify'))
                (root / 'capacity.json').write_text(json.dumps(session))
            if producer_handoff:
                request_path = run / 'inputs/request.json'
                request = json.loads(request_path.read_text())
                request['continuation'] = dict(frontend_field_transactions=[
                    dict(domain_id='parent', member_id='pulse_delta')])
                request_path.write_text(json.dumps(request))
                provenance_path = run / 'inputs/source_provenance.json'
                provenance = json.loads(provenance_path.read_text())
                for name in ('continuation_parent_manifest', 'continuation_stopped_receipt', 'continuation_field_transaction_001'):
                    evidence = run / 'inputs' / (name + '.json')
                    evidence.write_text(json.dumps(dict(fixture=name)))
                    provenance['input_records'][name] = file_record(evidence)
                provenance_path.write_text(json.dumps(provenance))
            script = root / 'stage.ps1'
            script.write_text(r'''
param($Repo,$Python,$Run,$Cache,$Recovery,$PreparedResume,$FineChange,$BudgetFailure,$Fine,$PrivateDamage,$FrozenSource,$LegacyPartial,$AuditRefresh,$ProducerHandoff,$AccountingFailure,$PreparedAuditFailure,$LastMemberOnly,$FixtureRoot,$Snapshot,$CompletionFault)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$function=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-SingleReflectionFrontendFieldStage'},$true))
if($function.Count-ne1){throw 'Actual frontend owner boundary is not unique'}
Invoke-Expression $function[0].Extent.Text
$factAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1'),[ref]$null,[ref]$null)
$factNode=$factAst.Find({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Add-FrontendNativeOperation'},$true)
Invoke-Expression $factNode.Extent.Text
$Repo=$Snapshot
$env:MASS_SPECTROMETRY_HOST_CONTEXT_JSON=(@{workspace=$FixtureRoot;host_state_path=(Join-Path $FixtureRoot 'not-used.sqlite3');policy_path=(Join-Path $Repo 'src/msplatform/execution/resources/host_resource_policy.json')}|ConvertTo-Json -Compress)
# This fixture owns field transactions; real transport is covered separately.
function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool) @{run_dir=$Package.artifact_run_dir;projected_paths=@($Paths);environment=@{}}}
function Project-RunPath {param($Paths,$ArtifactRunDir,$RunDir,$Python) return $Paths}

$script:native=@();$script:stages=@();$script:scopes=@();$script:workerFiles=@();$script:injectedFailure=$false;$script:handoffSeen=0;$script:stageAccounting=0
$WarningPreference='SilentlyContinue'
function Invoke-RunToolRootContext {
 param($RepoRoot,$Operation)
 $previous=$env:PYTHONPATH
 $env:PYTHONPATH=(Join-Path $RepoRoot src)+[IO.Path]::PathSeparator+$RepoRoot
 Push-Location $RepoRoot
 try { &$Operation } finally { Pop-Location; $env:PYTHONPATH=$previous }
}
function Write-RunJson {param($Path,$Value,$Depth) [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth $Depth),[Text.UTF8Encoding]::new($false))}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedCacheKeys,$RemainingCommittedNewBytes)
 if($script:sourceOnly-and@($ProtectedCacheKeys|Where-Object{$_}).Count){throw 'explicit source cache was incorrectly pinned at target owner'}
 $script:scopes+=,@(@($Session.protected_cache_keys)+@($ProtectedCacheKeys)|Select-Object -Unique)
 if($BudgetFailure-eq'1'-and$PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')-and$RemainingCommittedNewBytes-gt$Session.committed_new_bytes){throw 'INERT public capacity admission rejected'}
 if($PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')-and$RemainingCommittedNewBytes-lt$requiredReserve){throw 'cache handoff consumed reserved downstream/private payload'}
 $packet=Join-Path $FixtureRoot 'capacity-update.json'
 Write-RunJson -Path $packet -Depth 100 -Value @{session=$Session;keys=@($ProtectedCacheKeys|Where-Object{$_});remaining=$(if($PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')){$RemainingCommittedNewBytes}else{$null})}
 $code=@'
import json,sys
from pathlib import Path
from msplatform.execution.capacity_session import renew_capacity_session
value=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'));session=value['session']
# Controlled admission double only; the production PS pressure route is unchanged.
renew_capacity_session(session,protected_cache_keys=value['keys'],remaining_committed_new_bytes=value['remaining'],admission=lambda _current:dict(satisfied=True))
print(json.dumps(session))
'@
 $updated=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {&$Python -B -c $code $packet;if($LASTEXITCODE-ne0){throw 'controlled public session renewal failed'}}
 $current=$updated|ConvertFrom-Json -Depth 100
 Write-RunJson -Path (Join-Path $FixtureRoot 'capacity.json') -Depth 100 -Value $current
 [pscustomobject]@{session=$current}
}
function Get-HostResourceBudget {param($Role,$Stage) @{} }
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) $script:stages+=$Stage;return $Lease}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError,[switch]$RequireImmutableInputDrain)
 if(-not$RequireImmutableInputDrain){throw 'worker boundary omitted actual descendant drain request'}
 if($ArgumentList[-2]-ne'msplatform.backends.simion.field_worker'){throw 'unexpected worker transport'}
 $statePath=Join-Path $FixtureRoot 'worker-state.json'
 $state=@{native=$script:native;stages=$script:stages;injected_failure=$script:injectedFailure;
   handoff_seen=$script:handoffSeen;stage_accounting=$script:stageAccounting;
   recovery=($Recovery-eq'1');fine=($Fine-eq'1');last_member_only=($LastMemberOnly-eq'1');
   accounting_failure=($AccountingFailure-eq'1');prepared_audit_failure=($PreparedAuditFailure-eq'1');handoff_conflict=($ProducerHandoff-eq'2')}
 Write-RunJson -Path $statePath -Depth 100 -Value $state
 &$Python -B -X utf8 (Join-Path $FixtureRoot 'inert_frontend_worker.py') $ArgumentList[-1] $statePath (Join-Path $Repo src) 1>$RedirectStandardOutput 2>$RedirectStandardError
 $code=$LASTEXITCODE
 $updated=Get-Content -LiteralPath $statePath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 $script:native=@($updated.native);$script:injectedFailure=$updated.injected_failure
 $script:handoffSeen=$updated.handoff_seen;$script:stageAccounting=$updated.stage_accounting
 $packet=Get-Content -LiteralPath $ArgumentList[-1] -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 $bound=@{}
 foreach($item in @{request=$ArgumentList[-1];receipt=$packet.parameters.receipt_path}.GetEnumerator()){
   if(Test-Path -LiteralPath $item.Value){$bound[$item.Key]=@{path=$item.Value;bytes=(Get-Item -LiteralPath $item.Value).Length;sha256=(Get-FileHash -LiteralPath $item.Value -Algorithm SHA256).Hash}}
 }
 $script:workerFiles+=@($bound)
 if($CompletionFault-eq'unknown'){
  $controlled=Get-Content -LiteralPath $packet.parameters.receipt_path -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $controlled.native_operations[0].receipt.observation.completed=$false
  $controlled.native_operations[0].receipt.observation.exit_code=$null
  Write-RunJson -Path $packet.parameters.receipt_path -Value $controlled -Depth 100
  $code=1
 }elseif($CompletionFault-eq'missing'){
  Move-Item -LiteralPath $packet.parameters.receipt_path -Destination ($packet.parameters.receipt_path+'.inert-evidence')
  $code=1
 }
 # Explicit controlled facts for the inert unit boundary, not vendor observations.
 return [pscustomobject]@{exit_code=$code;root_process_id=901+$script:workerFiles.Count;root_process_started_at_utc_ticks=1001L;resource_budget_exceeded=$false}
}
$hostLease=[pscustomobject]@{id='inert'}
$capacity=Get-Content -LiteralPath (Join-Path $FixtureRoot 'capacity.json') -Raw|ConvertFrom-Json -Depth 100
$limits=[pscustomobject]@{wall_clock_seconds=120}
$script:resumePrepared=$false
$script:sourceOnly=$false
$elapsed=[Diagnostics.Stopwatch]::StartNew()
$failed=$false;$payloadAfterFailure=@();$nativeAfterFailure=@()
$requiredReserve=if($BudgetFailure-eq'2'){[long]0}else{[long](100GB)}
if($CompletionFault){
 $operations=[Collections.Generic.List[object]]::new();$caught=$null
 try{
  $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -NativeOperations $operations -NativeResourceReleaseId controlled-owner
 }catch{$caught=$_}
 if($null-eq$caught-or$caught.Exception.Message-notlike'Frontend field worker failed:*'){throw 'Original worker failure was replaced'}
 if(-not$caught.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-or$caught.Exception.Data['simion_wave_writer_completion_confirmed']-ne$false){throw 'Unknown native writer lost original owner lease-retention fact'}
 $owned=Join-Path $Run 'simion/frontend_working_fields/parent_audit_geometry'
 foreach($name in @('frontend.pa#','frontend.gem')){if(-not(Test-Path -LiteralPath (Join-Path $owned $name))){throw 'Unknown or missing writer evidence lost owned scratch'}}
 if($CompletionFault-eq'unknown'-and@($operations|Where-Object {-not$_.observation.exit_confirmed}).Count-ne1){throw 'Unknown native fact was overridden by outer drain'}
 if($CompletionFault-eq'missing'-and-not$capacity.PSObject.Properties['defer_capacity_finalization']){throw 'Missing receipt released accounting'}
 [pscustomobject]@{scratch_retained=$true;primary=$caught.Exception.Message;lease_id=$capacity.lease_id}|ConvertTo-Json
 exit 0
}
if($BudgetFailure-eq'1'){
 $capacity.committed_new_bytes=100GB
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
   throw 'expected admission rejection'
 }catch{
   $expected=if($BudgetFailure-eq'2'){'*below all required private fields*'}else{'*INERT public capacity admission rejected*'}
   if($_.Exception.Message-notlike$expected){throw}
   if($script:native.Count-ne0){throw 'budget rejection followed native invocation'}
 }
 [pscustomobject]@{budget_rejected=$true;native_count=$script:native.Count}|ConvertTo-Json
 exit 0
}

if($PreparedAuditFailure-eq'1'){
 try {
  $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
  throw 'expected prepared audit rejection'
 } catch {
  if($_.Exception.Message-notlike'*Frontend field worker failed: parent_carrier_off'){throw}
  $failedReport=Get-Content -LiteralPath $_.Exception.Data['frontend_worker_receipt'] -Raw|ConvertFrom-Json -AsHashtable
  if($failedReport.exception.message-notlike'*INERT native audit failed:*'){throw 'original audit failure cause lost'}
  if($script:stageAccounting-ne0-or$capacity.PSObject.Properties['defer_capacity_finalization']){throw 'prepared audit repeated stage accounting'}
  [pscustomobject]@{prepared_audit_rejected=$true;stage_accounting=$script:stageAccounting}|ConvertTo-Json
  exit 0
 }
}
if($Recovery-eq'1'){
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -StageElapsed $elapsed
 }catch{
   if($_.Exception.Message-notlike'*Frontend field worker failed:*'){throw}
   $failedReport=Get-Content -LiteralPath $_.Exception.Data['frontend_worker_receipt'] -Raw|ConvertFrom-Json -AsHashtable -Depth 100
   $expectedExport=if($LastMemberOnly-eq'1'){'*export_parent_pulse_delta'}elseif($Fine-eq'1'){'*export_entrance_refinement_rf_reference'}else{'*export_parent_rf_reference'}
   if($failedReport.exception.message-notlike$expectedExport){throw 'original export failure cause lost'}
   $failed=$true
   if($AccountingFailure-eq'1'){
     if(-not$capacity.defer_capacity_finalization){throw 'accounting failure did not defer finalization'}
     [pscustomobject]@{deferred=$true;primary_error=$failedReport.exception.message;stage_accounting=$script:stageAccounting;committed_bytes=$capacity.committed_new_bytes}|ConvertTo-Json
     exit 0
   }
   $payloadAfterFailure=@(Get-ChildItem -LiteralPath (Join-Path $Cache '.transactions') -Recurse -Filter '*.pa'|Where-Object{$_.Directory.Name-eq'payload'}|ForEach-Object{$_.Name})
   $nativeAfterFailure=@($script:native)
 }
 if(-not$failed){throw 'partial exporter failure was not propagated'}
}
if($PrivateDamage-eq'1'){
 $damaged=@(Get-ChildItem -LiteralPath $Cache -Recurse -Filter 'frontend.carrier_off.pa'|Where-Object{$_.FullName-like'*generations*'})[0].FullName
 [IO.File]::SetAttributes($damaged,[IO.FileAttributes]::Normal)
 [IO.File]::WriteAllText($damaged,'DAMAGED_PRIVATE_PARENT')
 [IO.File]::SetAttributes($damaged,[IO.FileAttributes]::ReadOnly)
 $before=$script:native.Count
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
   throw 'expected private parent rejection'
 }catch{
   if($_.Exception.Message-notmatch'length|identity|differs|corrupt'){throw}
   if($script:native.Count-ne$before){throw 'damaged private parent reached native'}
 }
 [pscustomobject]@{private_damage_rejected=$true}|ConvertTo-Json
 exit 0
}
if($ProducerHandoff-eq'2'){
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -StageElapsed $elapsed
   throw 'expected handoff rejection'
 }catch{
   if($_.Exception.Message-notlike'*Frontend field worker failed: parent_pulse_delta'){throw}
   $diagnostic=(Get-Content -LiteralPath $_.Exception.Data['frontend_worker_receipt'] -Raw|ConvertFrom-Json -AsHashtable -Depth 100).exception.message
   if($diagnostic-notlike'*another active consumer*'){throw 'original handoff cause lost'}
 }
 [pscustomobject]@{handoff_conflict_retained=$true;empty_domain_exists=(Test-Path -LiteralPath (Join-Path $Run 'simion/frontend_working_fields/parent_audit_geometry'))}|ConvertTo-Json
 exit 0
}
$one=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$Run;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -StageElapsed $elapsed
$firstCount=$script:native.Count
$secondRun=Join-Path (Split-Path $Run) '20261110_120000__test__python__frontend-hit'
if($PreparedResume-eq'1'){$secondRun=$Run}
if($PreparedResume-ne'1'){
New-Item -ItemType Directory -Path (Join-Path $secondRun 'inputs'),(Join-Path $secondRun 'logs')|Out-Null
Copy-Item -LiteralPath (Join-Path $Run inputs) -Destination $secondRun -Recurse -Force
$registerCode=@'
import json,sys
from pathlib import Path
from msplatform.execution.capacity_ledger import record_capacity_object
run,original=map(Path,sys.argv[1:3]);config=json.loads((original/'run_config.json').read_text());config['run_id']=run.name
(run/'run_config.json').write_text(json.dumps(config))
root=Path(config['capacity_ledger_lifecycle']['artifact_root'])
record_capacity_object(root,path=run,object_class='rebuildable_payload',bytes_count=0,status='writing',owner='current-workflow-owner',review_deadline='2099-12-31',recovery_reason='Controlled inert frontend fixture')
from msplatform.execution.capacity_session import renew_capacity_session
session_path=Path(sys.argv[3]);session=json.loads(session_path.read_text())
renew_capacity_session(session,protected_paths=[run])
session_path.write_text(json.dumps(session))
'@
$null=Invoke-RunToolRootContext -RepoRoot $Repo -Operation {&$Python -B -c $registerCode $secondRun $Run (Join-Path $FixtureRoot 'capacity.json');if($LASTEXITCODE-ne0){throw 'second controlled run registration failed'}}
$Repo=Join-Path $secondRun 'inputs/runtime_snapshot'
$capacity=Get-Content -LiteralPath (Join-Path $FixtureRoot 'capacity.json') -Raw|ConvertFrom-Json -Depth 100
}
$oneReceipt=Get-Content -LiteralPath $one.cache_receipt -Raw|ConvertFrom-Json -Depth 80
$oneDomain=$oneReceipt.domains[0].working_points[0]
$script:completedGeneration=$oneDomain.generation_directory
$script:resumePrepared=($PreparedResume-eq'1')
if($PreparedResume-eq'1'){Remove-Item -LiteralPath (Join-Path (Join-Path $Cache $oneDomain.cache_key) 'current_generation.json')}
$secondPrepared=$secondRun
if($FrozenSource-eq'1'){
 Get-ChildItem -LiteralPath (Join-Path $Run 'inputs') -File|ForEach-Object{
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $secondRun 'inputs')
 }
 foreach($domain in $oneReceipt.domains){
  foreach($record in $domain.working_points){
   $member=if($record.PSObject.Properties.Name-contains'working_point_id'){$record.working_point_id}else{$record.kind}
   Copy-Item -LiteralPath $record.cache_identity_record.path -Destination (Join-Path $secondRun ('inputs/frontend_field_source_{0}_{1}_identity.json' -f $domain.domain_id,$member))
   $record.path=Join-Path $Run ('simion/frontend_working_fields/'+[IO.Path]::GetFileName([string]$record.path))
   if(Test-Path -LiteralPath $record.path){throw 'source fixture unexpectedly retained private PA'}
  }
 }
 Write-RunJson -Path (Join-Path $secondRun 'inputs/frontend_field_source_receipt.json') -Value $oneReceipt -Depth 100
 $producerOutputs=@(foreach($domain in $oneReceipt.domains){foreach($record in $domain.working_points){@{path=$record.path;bytes=$record.bytes;sha256=$record.sha256};$record.audit_record}})
 Write-RunJson -Path (Join-Path $secondRun 'inputs/frontend_field_source_manifest.json') -Value @{role='simulation_run_manifest';run_config=@{path=(Join-Path $Run 'run_config.json')};outputs=$producerOutputs} -Depth 100
 $sourceManifest=Join-Path $secondRun 'inputs/frontend_field_source_manifest.json'
 $provenance=Get-Content -LiteralPath (Join-Path $secondRun 'inputs/source_provenance.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 $provenance.input_records.frontend_fields_manifest=@{path=$sourceManifest;bytes=(Get-Item -LiteralPath $sourceManifest).Length;sha256=(Get-FileHash -LiteralPath $sourceManifest -Algorithm SHA256).Hash;source_path=(Join-Path $Run 'run_manifest.json')}
 Write-RunJson -Path (Join-Path $secondRun 'inputs/source_provenance.json') -Value $provenance -Depth 100
 $request=Get-Content -LiteralPath (Join-Path $secondRun 'inputs/request.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 $request.providers.frontend_fields=@{path='explicit-producer-receipt'}
 Write-RunJson -Path (Join-Path $secondRun 'inputs/request.json') -Value $request -Depth 100
 $secondPrepared=$secondRun
 $script:sourceOnly=$LegacyPartial-ne'1'
 if($LegacyPartial-eq'1'){
  $null=Invoke-RunToolRootContext -RepoRoot $Repo -Operation {
    &$Python -B (Join-Path $FixtureRoot 'legacy_source_fixture.py') $Run $secondRun $Cache (Join-Path $FixtureRoot 'capacity.json') (Join-Path $Repo src)
    if($LASTEXITCODE-ne0){throw 'legacy governed fixture construction failed'}
  }
  $capacity=Get-Content -LiteralPath (Join-Path $FixtureRoot 'capacity.json') -Raw|ConvertFrom-Json -Depth 100
 }
}
if($FrozenSource-eq'1'){
 $null=Invoke-RunToolRootContext -RepoRoot $Repo -Operation {&$Python -B (Join-Path $FixtureRoot 'seal_source_fixture.py') $Run $secondRun (Join-Path $Repo src);if($LASTEXITCODE-ne0){throw 'controlled source terminal publication failed'}}
}
if($AuditRefresh-eq'1'){
 $designPath=Join-Path $secondRun 'inputs/frontend_field_design.json'
 $design=Get-Content -LiteralPath $designPath -Raw|ConvertFrom-Json -Depth 100
 $design.domains[0].physical_samples[0].gu[0]+=1
 Write-RunJson -Path $designPath -Value $design -Depth 100
}
if($FineChange-eq'1'){
 foreach($name in @('frontend_field_design.json','frontend_geometry.json','frontend.gem','frontend_entrance_refinement.gem')){
  Copy-Item -LiteralPath (Join-Path (Join-Path $Run 'inputs') $name) -Destination (Join-Path (Join-Path $secondRun 'inputs') $name)
 }
 $secondPrepared=$secondRun
 $designPath=Join-Path $secondRun 'inputs/frontend_field_design.json'
 $design=Get-Content -LiteralPath $designPath -Raw|ConvertFrom-Json -Depth 100
 $design.domains[1].refine_convergence_v.pulse_delta*=2
 Write-RunJson -Path $designPath -Value $design -Depth 100
}
if($FineChange-eq'1'-or$LegacyPartial-eq'1'-or$PreparedResume-eq'1'){$capacity.committed_new_bytes=1TB}
$commitmentBefore=$capacity.committed_new_bytes
$copiesBeforeSecond=$global:MassSpectrometryShortPaCopies.Count
$sourceLeaseRejections=0
if($FrozenSource-eq'1'-and$LegacyPartial-ne'1'-and$AuditRefresh-ne'1'){
 $originalCapacity=$capacity
 foreach($binding in @('missing','unrelated')){
  $leaseCode=@'
import json,sys
from pathlib import Path
from msplatform.execution.capacity_session import create_capacity_session
value=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
if sys.argv[3]=='missing':
    value['lease_id']='missing-original-source-lease'
else:
    value=create_capacity_session(Path(value['artifact_root']),Path(sys.argv[2]),owner=value['owner'],
        committed_new_bytes=value['committed_new_bytes'],protected_cache_keys=value['protected_cache_keys'])
print(json.dumps(value))
'@
  Write-RunJson -Path (Join-Path $FixtureRoot 'source-original-session.json') -Depth 100 -Value $originalCapacity
  $bad=Invoke-RunToolRootContext -RepoRoot $Repo -Operation {&$Python -B -c $leaseCode (Join-Path $FixtureRoot 'source-original-session.json') $secondRun $binding;if($LASTEXITCODE-ne0){throw 'controlled source lease construction failed'}}
  $capacity=$bad|ConvertFrom-Json -Depth 100
  $before=$script:native.Count
  try{
   try{
    $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$secondRun;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $secondRun -PreparedDirectory $secondPrepared -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
    throw 'wrong original source protection binding accepted'
   }catch{
    if(-not$_.Exception.Data.Contains('frontend_worker_receipt')){throw}
    $rejected=Get-Content -LiteralPath $_.Exception.Data['frontend_worker_receipt'] -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    if($rejected.exception.message-notlike'*original-session source protection binding*'){throw 'wrong source lease rejection cause'}
    if($script:native.Count-ne$before-or$rejected.native_count-ne0){throw 'invalid source lease reached native action'}
    $sourceLeaseRejections++
   }
  }finally{
   if($binding-eq'unrelated'){
    Write-RunJson -Path (Join-Path $FixtureRoot 'unrelated-source-session.json') -Depth 100 -Value $capacity
    $close='import json,sys;from pathlib import Path;from msplatform.execution.capacity_session import exit_capacity_session;exit_capacity_session(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")))'
    $null=Invoke-RunToolRootContext -RepoRoot $Repo -Operation {&$Python -B -c $close (Join-Path $FixtureRoot 'unrelated-source-session.json');if($LASTEXITCODE-ne0){throw 'controlled unrelated lease cleanup failed'}}
   }
   $capacity=$originalCapacity
  }
 }
}
$stagesBeforeSecond=$script:stages.Count
$two=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$secondRun;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $secondRun -PreparedDirectory $secondPrepared -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
$copiesAfterSecond=$global:MassSpectrometryShortPaCopies.Count
$sourceMissingRejected=$false
if($FrozenSource-eq'1'-and$LegacyPartial-ne'1'-and$AuditRefresh-ne'1'){
 $manifestPath=Join-Path $oneDomain.generation_directory 'cache_manifest.json'
 $hiddenManifest=$manifestPath+'.fixture-hidden'
 Move-Item -LiteralPath $manifestPath -Destination $hiddenManifest
 try{
  try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Package ([pscustomobject]@{artifact_run_dir=$secondRun;python=$Python}) -Python $Python -RepoRoot $Repo -RunDirectory $secondRun -PreparedDirectory $secondPrepared -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
   throw 'missing explicit generation was accepted'
  }catch{
   if($_.Exception.Message-notlike'Frontend scientific projection failed: frontend_working_plan_*'){throw}
   $failure=Get-Content -LiteralPath $_.Exception.Data['frontend_projection_stderr'] -Raw
   if($failure-notlike'*PA cache manifest is missing*'){throw 'wrong source failure'}
   $sourceMissingRejected=$true
  }
 }finally{Move-Item -LiteralPath $hiddenManifest -Destination $manifestPath}
}
$transactions=@(Get-ChildItem -LiteralPath (Join-Path $Cache '.transactions') -Recurse -Filter transaction.json)
$transaction=Get-Content -LiteralPath $transactions[0].FullName -Raw|ConvertFrom-Json -Depth 80
$manifest=Get-Content -LiteralPath (Join-Path $oneDomain.generation_directory 'cache_manifest.json') -Raw|ConvertFrom-Json -Depth 80
[pscustomobject]@{first=$one;second=$two;native=$script:native;first_count=$firstCount;second_native_count=($script:native.Count-$firstCount);
 stages_after_second=@($script:stages|Select-Object -Skip $stagesBeforeSecond);stages=$script:stages;scopes=$script:scopes;transaction=$transaction;manifest=$manifest;failed=$failed;payload_after_failure=$payloadAfterFailure;native_after_failure=$nativeAfterFailure;handoff_seen=$script:handoffSeen;stage_accounting=$script:stageAccounting;
 worker_files=$script:workerFiles;protected_keys=$capacity.protected_cache_keys;commitment_before_second=$commitmentBefore;commitment_after_second=$capacity.committed_new_bytes;
 source_lease_rejections=$sourceLeaseRejections;source_missing_rejected=$sourceMissingRejected;copies_before_second=$copiesBeforeSecond;copies_after_second=$copiesAfterSecond;disposable_copies=$global:MassSpectrometryShortPaCopies.Count;guards=$global:MassSpectrometryShortPaSourceGuards.Count}|ConvertTo-Json -Depth 100
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(ROOT), sys.executable,
                str(run), str(cache_root), '1' if recovery else '0', '1' if prepared_resume else '0', '1' if fine_change else '0', '2' if reserve_failure else ('1' if budget_failure else '0'), '1' if fine else '0', '1' if private_damage else '0', '1' if frozen_source else '0', '1' if legacy_partial else '0', '1' if audit_refresh else '0', '2' if handoff_conflict else ('1' if producer_handoff else '0'), '1' if accounting_failure else '0', '1' if prepared_audit_failure else '0', '1' if last_member_only else '0', str(root), str(snapshot), completion_fault or ''], cwd=ROOT, capture_output=True, text=True,
                encoding='utf-8', timeout=180, check=False)
            diagnostics = '\n'.join(path.read_text(encoding='utf-8-sig', errors='replace')
                for path in root.rglob('*.stderr.log')) if result.returncode else ''
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr+'\n'+diagnostics)
            data = json.loads(result.stdout)
            if completion_fault:
                self.assertTrue(data['scratch_retained'])
                self.assertIn('Frontend field worker failed:', data['primary'])
                self.assertEqual(data['lease_id'], session['lease_id'])
                return
            if prepared_audit_failure:
                self.assertTrue(data['prepared_audit_rejected'])
                self.assertEqual(data['stage_accounting'], 0)
                return
            if accounting_failure:
                self.assertTrue(data['deferred'])
                self.assertEqual(data['stage_accounting'], 1)
                self.assertGreater(data['committed_bytes'], 0)
                self.assertIn('export_parent_rf_reference', data['primary_error'])
                return
            if handoff_conflict:
                self.assertTrue(data['handoff_conflict_retained'])
                self.assertTrue(data['empty_domain_exists'])
                return
            if private_damage:
                self.assertTrue(data['private_damage_rejected'])
                return
            if budget_failure:
                self.assertTrue(data['budget_rejected'])
                self.assertEqual(data['native_count'], 0)
                return
            self.assertEqual(data['handoff_seen'], int(producer_handoff))
            expected_first = (23 if fine else 13) if recovery else (20 if fine else (7 if local else 10))
            self.assertEqual(data['first_count'], expected_first)
            if recovery:
                self.assertEqual(data['stage_accounting'], 1)
                self.assertTrue(data['failed'])
                # Carrier belongs to its published single-member generation;
                # failed RF export never appears as a completed payload.
                self.assertEqual(data['payload_after_failure'], [])
                retries = [args for args in data['native'][len(data['native_after_failure']):]
                           if len(args)>9 and args[3].endswith('build_dirichlet_patch_operating_pa.lua')]
                self.assertEqual(len(retries), 1 if last_member_only else 2)
            self.assertEqual(data['copies_before_second'], data['copies_after_second'])
            self.assertEqual(data['second_native_count'], 6 if legacy_partial else 4 if fine_change or audit_refresh else 0)
            if not prepared_resume and (data['second_native_count'] == 0 or audit_refresh):
                self.assertNotIn('pa_refine', data['stages_after_second'])
            if frozen_source and not legacy_partial and not audit_refresh:
                self.assertTrue(data['source_missing_rejected'])
                self.assertEqual(data['source_lease_rejections'], 2)
            self.assertEqual(data['commitment_after_second'], 0 if reserve_failure else 100*1024**3)
            if prepared_resume:
                self.assertEqual(len(list((cache_root/data['manifest']['cache_key']/'generations').iterdir())), 1)
            if fine_change:
                first = json.loads(Path(data['first']['cache_receipt']).read_text())
                second = json.loads(Path(data['second']['cache_receipt']).read_text())
                self.assertEqual([row['cache_key'] for row in first['domains'][0]['working_points']],
                                 [row['cache_key'] for row in second['domains'][0]['working_points']])
                for index in (0, 1):
                    self.assertEqual(first['domains'][1]['working_points'][index]['cache_key'],
                                     second['domains'][1]['working_points'][index]['cache_key'])
                self.assertNotEqual(first['domains'][1]['working_points'][2]['cache_key'],
                                    second['domains'][1]['working_points'][2]['cache_key'])
                self.assertGreater(data['commitment_before_second']-data['commitment_after_second'], 0)
            elif legacy_partial:
                second = json.loads(Path(data['second']['cache_receipt']).read_text())
                points = second['domains'][0]['working_points']
                self.assertEqual([point['refine_performed'] for point in points], [False,False,True])
                self.assertEqual([point['source_schema_version'] for point in points], [2,2,3])
                self.assertEqual(points[0]['generation_directory'], points[1]['generation_directory'])
                self.assertNotEqual(points[1]['generation_directory'], points[2]['generation_directory'])
                second_native = data['native'][data['first_count']:]
                refinements = [args for args in second_native if len(args)>9 and args[3].endswith('build_dirichlet_patch_operating_pa.lua')]
                self.assertEqual(len(refinements), 1)
                frozen_design = json.loads(((run.parent/'20261110_120000__test__python__frontend-hit/inputs/frontend_field_design.json')).read_text())
                pulse_voltages = frozen_design['working_points'][2]['electrode_voltages_v']
                # Native voltage vectors span numeric IDs, including unbound holes;
                # zero entries for missing IDs do not create physical electrodes.
                expected_voltages = ','.join(format(pulse_voltages.get(str(eid), 0.), '.17g')
                    for eid in range(1, max(map(int, pulse_voltages)) + 1))
                self.assertEqual(refinements[0][9], expected_voltages)
            elif audit_refresh:
                self.assertEqual(data['commitment_before_second'], data['commitment_after_second'])
                second_native = data['native'][data['first_count']:]
                self.assertFalse(any(len(args)>9 and args[3].endswith('build_dirichlet_patch_operating_pa.lua') for args in second_native))
            elif not prepared_resume:
                self.assertEqual(data['commitment_before_second']-data['commitment_after_second'], 0)
            self.assertEqual(len({row['request']['path'] for row in data['worker_files']}), len(data['worker_files']))
            self.assertEqual(len({row['receipt']['path'] for row in data['worker_files']}), len(data['worker_files']))
            for invocation in data['worker_files']:
                for record in invocation.values():
                    self.assertEqual(Path(record['path']).stat().st_size, record['bytes'])
                    self.assertEqual(file_sha256(record['path']).upper(), record['sha256'].upper())
                worker_report = json.loads(Path(invocation['receipt']['path']).read_text())
                self.assertEqual(Path(worker_report['request']['path']), Path(invocation['request']['path']))
                self.assertEqual(worker_report['request']['sha256'].upper(), invocation['request']['sha256'].upper())
            self.assertEqual(data['disposable_copies'], 0)
            self.assertEqual(data['guards'], 0)
            self.assertEqual(len(data['manifest']['files']), 1)
            self.assertEqual(data['transaction']['published_pin_reason'],
                             'Retain standalone frontend fields required by saved instrument workbenches.')
            for case in ('first', 'second'):
                receipt = json.loads(Path(data[case]['cache_receipt']).read_text())
                self.assertEqual(receipt['role'], 'single_reflection_frontend_working_fields')
                self.assertEqual(receipt['schema_version'], 3)
                self.assertEqual(len(receipt['domains']), 2 if fine else 1)
                for domain in receipt['domains']:
                    self.assertEqual([point['kind'] for point in domain['working_points']],
                                     ['carrier_off', 'pulse_delta'] if local else list(KINDS))
                    for point in domain['working_points']:
                        self.assertEqual(Path(point['path']).parent, Path(point['generation_directory']))
                        self.assertIn(Path(point['path']).name, point['cache_filenames'])
                        self.assertTrue(Path(point['path']).is_file())
                        self.assertTrue(point['read_only'])
                        audit = json.loads(Path(point['audit_record']['path']).read_text())
                        self.assertIn('audit_input_sha256', audit)
                        identity = json.loads(Path(point['cache_identity_record']['path']).read_text())
                        if point['source_schema_version']==3:
                            self.assertEqual(len(identity['working_points']), 1)
                            self.assertNotIn('physical_samples', identity['geometry'])
                from msplatform.workflows.single_reflection_flight.field_evidence import _frontend_fields
                actual_design = json.loads(((run.parent/'20261110_120000__test__python__frontend-hit' if fine_change or legacy_partial or audit_refresh else run)/'inputs/frontend_field_design.json').read_text())
                if case == 'first':
                    actual_design = json.loads((run/'inputs/frontend_field_design.json').read_text())
                _frontend_fields(Path(data[case]['cache_receipt']), actual_design)
                self.assertFalse(receipt['fly_performed'])
            self.assertFalse(any(path.name == 'build-scratch' for path in (root / 'cache/.transactions').rglob('*')))


if __name__ == '__main__':
    unittest.main()

class FrontendProducerProjectionTests(unittest.TestCase):
    def test_canonical_projection_keeps_original_plan_and_source_free_member_authority(self):
        from msplatform.workflows.single_reflection_flight.frontend_fields import prepare_stage, domain_members
        with tempfile.TemporaryDirectory() as directory:
            run, original = prepared(Path(directory), entrance_refinement=True)
            (run / 'run_config.json').write_text('{}')
            before = build_field_plan(run / 'inputs', Path(sys.executable))
            from msplatform.workflows.single_reflection_flight.prepare import FROZEN_NAMES
            self.assertTrue((run / 'inputs/projected_source.csv').is_file())
            source_keys = ('particle_source', 'metadata', 'release_spec', 'release_receipt',
                           'pre_pulse_collection', 'pulse_decision', 'producer_manifest',
                           'pre_pulse_source_geometry', 'pre_pulse_source_states',
                           'pre_pulse_source_provenance', 'clock_authority', 'instrument_epoch')
            for name in [*(FROZEN_NAMES[key] for key in source_keys), 'projected_source.csv',
                         'source_states.csv', 'source_provenance.json', 'request.json']:
                (run / 'inputs' / name).unlink(missing_ok=True)
            stage = prepare_stage(run / 'inputs', Path(sys.executable), run)
            self.assertEqual(stage['bundle'], before)
            projected = domain_members(stage, 0, [])
            self.assertEqual(projected['domain_id'], 'parent')
            self.assertEqual(len(projected['members']), len(original['members']))
            with self.assertRaisesRegex(ValueError, 'completed predecessor'):
                domain_members(stage, 1, [])
            with self.assertRaisesRegex(ValueError, 'every actual same-member parent'):
                domain_members(stage, 1, [dict(domain_id='parent', working_points=[])])
            for actual, member in zip(projected['members'], original['members'], strict=True):
                self.assertEqual(actual['identity'], member['identity'])
                self.assertEqual(actual['cache_key'], member['cache_key'])
                self.assertEqual(actual['working_points'], member['working_points'])
            for name, record in stage['resources'].items():
                self.assertTrue(Path(record['path']).is_relative_to(run / 'inputs'))
                self.assertEqual(file_sha256(record['path']), file_sha256(ROOT / 'src/msplatform/backends/simion/resources' / Path(record['path']).name))
            design = run / 'inputs/frontend_field_design.json'
            design.write_text(design.read_text() + ' ')
            with self.assertRaisesRegex((ValueError, AssertionError), 'byte|identity|size|changed'):
                domain_members(stage, 0, [])

    def test_actual_manager_selection_is_revalidated_without_second_probe_or_raw_work(self):
        from msplatform.workflows.single_reflection_flight.frontend_fields import prepare_stage, domain_members, assess_member
        from msplatform.backends.simion.field_worker import _selected_cache_probe
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = prepared(root)
            (run / 'run_config.json').write_text('{}')
            stage = prepare_stage(run / 'inputs', Path(sys.executable), run)
            member = domain_members(stage, 0, [])['members'][0]
            cache_root = root / 'artifacts/common/simion/pa_family_cache'
            assessment = assess_member(stage, member, cache_root)
            self.assertEqual(assessment['selection']['probe']['disposition'], 'miss')
            self.assertEqual(assessment['required_extra_bytes'], member['grid'][0]*member['grid'][1]*member['grid'][2]*24)
            self.assertFalse((run / 'simion').exists())
            with patch.object(pa_family_cache, 'probe_pa_family_cache', side_effect=AssertionError('second policy decision')):
                actual = _selected_cache_probe(cache_root, member['identity'], member['filenames'][0], assessment['selection'])
                self.assertEqual(actual.disposition.value, 'miss')
                pointer = cache_root / member['cache_key'] / pa_family_cache.POINTER_NAME
                pointer.parent.mkdir(parents=True)
                pointer.write_text('{}')
                with self.assertRaisesRegex(ValueError, 'changed after selection.*replan'):
                    _selected_cache_probe(cache_root, member['identity'], member['filenames'][0], assessment['selection'])
            self.assertFalse((run / 'simion').exists())
