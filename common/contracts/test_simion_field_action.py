"""Actual public-example field action/owner with explicitly inert native transports."""
from functools import partial
from importlib.resources import files
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.test_simion_field_worker import INERT_WORKER
from common.contracts.test_simion_fields_execution import INERT_DOWNSTREAM
from msplatform import api
from msplatform.backends.simion.field_execution import execute_fields, plan_fields_execution
from msplatform.backends.simion.field_closure import load_field_model
from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.execution import owner
from msplatform.execution.artifact_reader import open_artifact
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.manifest_records import file_record
from msplatform.execution.payload_inputs import materialize_payloads
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession


def public_case():
    case = api.load_example('rf_oatof_functional_v1')
    components = {name:api.resolve_component(value) for name,value in case.component_requests.items()}
    assembly = api.compile_assembly(case.recipe, components)
    geometry = api.compile_geometry(assembly, backend='simion', numerics=case.geometry_numerics)
    root = Path(str(files('msplatform.examples')))
    contract = root/'instrument_clock_authority_v1.json'
    authority = validate_clock_authority(contract, root)
    clock = dict(clock_epoch_id=authority['clock_epoch_id'], authority_sha256=authority['authority_sha256'], **case.drive['clock'])
    selected = {name:geometry.components_resolved[name] for name in geometry.frontend_geometry['composition_plan']['scope']['instance_ids']}
    drive = project_resolved_drive(geometry, selected, pulse=case.drive['pulse'], clock=clock)
    model = compile_prepared_model(geometry, selected, drive=drive, physics=case.physics)
    numerics = dict(frontend_domains=case.geometry_numerics['frontend_domains'], rf_reference_voltage_v=10000.,
        downstream_convergence_v=dict(flight_tube=.001, detector=.001, reflectron=.001))
    for domain in numerics['frontend_domains'].values():
        domain['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.001, pulse_delta=.001)
    return model, numerics, contract, root


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class FieldActionTests(unittest.TestCase):
    def test_public_example_real_owner_cold_then_explicit_published_reuse_without_refine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, numerics, contract_path, clock_root = public_case()
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'private-host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            budget = root/'budget.json'
            budget.write_text('{"bytes":104857600}', encoding='utf-8')
            scripts = {'member':root/'inert_member.py', 'downstream':root/'inert_downstream.py'}
            scripts['member'].write_text(INERT_WORKER, encoding='utf-8')
            scripts['downstream'].write_text(INERT_DOWNSTREAM, encoding='utf-8')
            limits = dict(reserved_run_payload_bytes=1048576)
            materializer = partial(materialize_payloads, limits=limits)
            materializer_record = file_record(Path(inspect.getsourcefile(materialize_payloads)), 'required_evidence')
            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            base = dict(descriptor=dict(project='instrument_assembly', mode='inert_field_action', software=[]),
                payload={}, committed_new_bytes=104857600, commitment_inputs=[file_record(budget, 'required_evidence')],
                retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert software field action'),
                action_record=file_record(Path(__file__), 'required_evidence'),
                completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))

            def publish_model(session):
                records = {}
                def put(key, target, *, data=None, source=None, role='required_evidence'):
                    session.declare_file(target, role)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source is None: target.write_bytes(data)
                    else: freeze_file(Path(source), target)
                    record = file_record(target, role)
                    records[key] = record
                    return record
                put('compiled_model', session.input_dir/'compiled_model.json', data=json.dumps(model.document).encode())
                put('clock_authority', session.input_dir/'clock/clock_authority.json', source=contract_path)
                contract = json.loads(contract_path.read_text(encoding='utf-8'))
                epoch = contract['authority']['path']
                put('instrument_epoch', session.input_dir/'clock'/epoch, source=clock_root/epoch)
                put('structural_seed', session.input_dir/'seed.iob', source=structural_seed_path(4))
                assets = {}
                for domain in ('parent','flight_tube','reflectron','detector'):
                    key = domain+'_raw'
                    put(key, session.result_dir/(domain+'.pa#'), data=b'INERT_PUBLIC_EXAMPLE_NOT_RAW_PA', role='solver_native_binary')
                    assets[domain] = dict(raw_geometry=key)
                    if domain in {'flight_tube','detector'}:
                        key = domain+'_surface'
                        put(key, session.result_dir/(domain+'.pa-surf'), data=b'INERT_PUBLIC_EXAMPLE_NOT_SURFACE_PA', role='solver_native_binary')
                        assets[domain]['fractional_surface'] = key
                metadata = dict(backend='simion', drive_configured=True, geometry_materialized=True,
                    field_status='not_solved', source_status='not_requested', native_assets=assets,
                    fixture='INERT_PROTOCOL_NOT_NATIVE_QUALIFICATION')
                return dict(status='success', summary=metadata, output_paths=[row['path'] for row in records.values()],
                    required_output_paths=[row['path'] for row in records.values()], retention_preserve_paths=[],
                    manifest_extra_fields={'products':{'model':dict(schema_version=1, kind='prepared_model',status='complete',metadata=metadata,data=records)}})

            actual_process = RunSession.run_process
            def inert_transport(session, operation_id, **kwargs):
                if operation_id.startswith('frontend_') or operation_id == 'downstream_fields':
                    script = scripts['downstream' if operation_id == 'downstream_fields' else 'member']
                    kwargs['arguments'] = ['-I','-B','-X','utf8',str(script),kwargs['arguments'][-1]]
                elif operation_id in {'build_fields','verify_fields'}:
                    path = session.run_dir/'simion/fields/fields.iob'
                    marker = 'SINGLE_REFLECTION_FIELD_IOB'+('_REOPEN' if operation_id == 'verify_fields' else '')+'=PASS'
                    code = "from pathlib import Path;p=Path("+repr(str(path))+");p.parent.mkdir(parents=True,exist_ok=True);"
                    if operation_id == 'build_fields':
                        code += "p.write_bytes(b'INERT_NOT_NATIVE_FIELD_IOB');p.with_suffix('.fly2').write_text('particles { coordinates = 0 }');"
                    else: code += "assert p.is_file();"
                    code += 'print('+repr(marker)+')'
                    kwargs['arguments'] = ['-c',code]
                try:
                    return actual_process(session, operation_id, **kwargs)
                except BaseException as failure:
                    failure.add_note('INERT_PHASE='+case+' OP='+operation_id+' COMPLETED='+json.dumps(session._completed))
                    for path in session.log_dir.rglob('*.stderr.log'):
                        failure.add_note('INERT_STDERR='+path.read_text(encoding='utf-8'))
                    raise
            with patch.dict(os.environ, environment), patch.object(owner, '_capacity_policy', return_value=policy), patch(
                    'msplatform.execution.capacity_admission._capacity_policy', return_value=policy), patch.object(
                    RunSession, 'run_process', new=inert_transport):
                published = owner.run_managed_stage(context, **base,
                    run_id='20261104_120000__test__python__field-model-source', expected_operation_ids=[],
                    operation_dependencies={}, action=publish_model)
                model_ref = dict(manifest=published['manifest'], product_id='model')
                self.assertEqual(load_field_model(model_ref).model.document, model.document)
                field_refs, outcomes = [], []
                for case in ('cold','reuse'):
                    reuse = field_refs[0] if field_refs else None
                    graph = plan_fields_execution(model, numerics=numerics, reuse_fields_reference=reuse)
                    def action(session):
                        for name,path in scripts.items(): session.add_input('inert_'+name, file_record(path,'required_evidence'))
                        return execute_fields(session, model_reference=model_ref, numerics=numerics, limits=limits,
                            materialize_geometry=materializer, materializer_record=materializer_record,
                            reuse_fields_reference=reuse)
                    references = [dict(manifest_record=model_ref['manifest'])]
                    if reuse: references.append(dict(manifest_record=reuse['manifest']))
                    result = owner.run_managed_stage(context, **base,
                        run_id='20261104_120000__test__python__field-action-'+case,
                        expected_operation_ids=graph['expected_operation_ids'], operation_dependencies=graph['operation_dependencies'],
                        source_references=references, action=action)
                    reference = dict(manifest=result['manifest'], product_id='fields')
                    artifact = open_artifact(reference, expected_kind='field_bundle')
                    print('INERT_FIELD_PHASE_COMPLETE='+json.dumps(dict(case=case,
                        completed_operations=len(graph['expected_operation_ids']),
                        frontend_children=artifact.metadata['frontend_native_operations'],
                        downstream_children=artifact.metadata['downstream_native_operations'])), flush=True)
                    field_refs.append(reference)
                    outcomes.append(artifact)
                    self.assertEqual(artifact.metadata['model_identity_sha256'], model.document['model_identity_sha256'])
                    self.assertEqual(artifact.metadata['source_status'], 'not_requested')
                    self.assertEqual(artifact.metadata['fly_calls'], 0)
                    self.assertEqual(artifact.metadata['sampled_particles'], 0)
                    self.assertEqual(artifact.metadata['scientific_qualification'], 'not_granted')
                    self.assertEqual(set(artifact.metadata['native_assets']), {'flight_tube','reflectron','detector'})
                    self.assertTrue(all(Path(record['path']).is_relative_to(Path(result['run_directory']))
                                        for record in artifact.data_records.values()))
                    self.assertEqual(len(artifact.metadata['frontend_members']['parent']), 3)
                    self.assertEqual(json.loads(artifact.data_path('compiled_model').read_text()), model.document)
                    completion = json.loads((Path(result['run_directory'])/'results/execution_completion.json').read_text())
                    self.assertEqual(len(completion['writer_completion']['operations']), len(graph['expected_operation_ids']))
                    self.assertEqual(len(completion['writer_completion']['resource_releases']), len(graph['expected_operation_ids']))
                self.assertEqual(outcomes[0].metadata['frontend_native_operations'], 9)
                self.assertEqual(outcomes[0].metadata['downstream_native_operations'], 5)
                self.assertEqual(outcomes[1].metadata['frontend_native_operations'], 0)
                self.assertEqual(outcomes[1].metadata['downstream_native_operations'], 0)
                self.assertTrue(outcomes[1].metadata['downstream_reused'])
