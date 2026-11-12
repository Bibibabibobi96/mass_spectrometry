"""Installed SFI source-to-public-track wiring, with an inert field and owner."""
import json
from pathlib import Path
import sys
import sysconfig
from types import SimpleNamespace
from unittest.mock import patch


def run(preparation, run_directory, expected_ids, arm, timer):
    """Exercise actual installed binding and public planning without native actions."""
    from msplatform.backends.simion.compiler import compile_geometry
    from msplatform.backends.simion.model import PHYSICS, compile_prepared_model, project_resolved_drive
    from msplatform.execution.terminal_publication import publish_terminal_state
    from msplatform.io.manifest_records import file_record
    from msplatform.workflows.single_reflection_flight import recorded_birth

    with timer('sfi_saved_field_consumer', str(arm)):
        purelib = Path(sysconfig.get_paths()['purelib']).resolve()
        assert Path(recorded_birth.__file__).resolve() == purelib/'msplatform/workflows/single_reflection_flight/recorded_birth.py'
        run = Path(run_directory)
        request = json.loads((run/'inputs/request.json').read_text(encoding='utf-8-sig'))
        assert request['source']['kind'] == 'recorded_birth' and request['flight']['pulse']['mode'] == 'timed'
        source_records = {**preparation['input_records'], **preparation['outputs']}
        source_manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='installed-sfi-fixture',
            project='instrument_assembly', mode='single_reflection_flight', status='success', inputs=source_records, outputs=[])
        publish_terminal_state(run, {'status':'success'}, source_manifest)
        producer = file_record(run/'run_manifest.json')
        components = {name:json.loads(Path(preparation['input_records']['instance_design__'+name]['path']).read_text())
                      for name in request['providers']['instances']}
        assembly = json.loads((run/'inputs/composition_plan.json').read_text())
        domains = {name:{key:value for key,value in domain.items() if key != 'refine_convergence_v'}
                   for name,domain in request['numerics']['frontend_domains'].items()}
        tof = components['oatof']
        compiled = compile_geometry({'composition_plan':assembly, 'components_resolved':components},
            numerics=dict(frontend_domains=domains, geometry_build=tof['simion_geometry_build'],
                detector_marker=tof['simion_detector_marker'],
                electrode_group_native_ids={name:value['electrode_bindings']
                                            for name,value in request['providers']['instances'].items()}))
        epoch = preparation['input_records']['instrument_epoch']
        drive = project_resolved_drive(compiled, components, pulse=request['flight']['pulse'],
            clock=dict(clock_epoch_id='instrument_clock_epoch_v1', authority_sha256=epoch['sha256'],
                       phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(compiled, components, drive=drive, physics=PHYSICS)
        field_run = run.parent/(run.name+'-inert-field')
        field_run.mkdir()
        model_path = field_run/'compiled_model.json'
        model_path.write_text(json.dumps(model.document), encoding='utf-8')
        data = {'compiled_model':file_record(model_path), 'instrument_epoch':epoch,
                'clock_authority':preparation['input_records']['clock_authority']}
        metadata = dict(backend='simion', field_status='available', source_status='not_requested',
            model_identity_sha256=model.document['model_identity_sha256'], clock=model.document['drive']['clock'],
            fixture_only=True)
        field_manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-field',
            project='instrument_assembly', mode='software-fixture', status='success', inputs=data, outputs=[],
            products={'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=data)})
        publish_terminal_state(field_run, {'status':'success'}, field_manifest)
        field_ref = {'manifest':file_record(field_run/'run_manifest.json'), 'product_id':'fields'}
        context = SimpleNamespace(tools={'simion':Path(sys.executable)})
        stage = {'limits':{'transient_run_directory_bytes':1}, 'artifact_retention':{}}
        with patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
             patch('msplatform.execution.owner.run_managed_stage', return_value={'manifest':{}}) as owner, \
             patch('msplatform.results.artifacts.open_artifact', return_value='installed-public-track'):
            result = recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=field_ref,
                species_id='installed_fixture_species', expected_particle_ids=[int(value) for value in expected_ids],
                observations={'plane_observations':[]}, context=context)
        assert result == 'installed-public-track'
        call = owner.call_args.kwargs
        assert call['payload']['propagation']['scope'] == 'continuous_assembly'
        assert len(call['payload']['particles']['mother']['records']) == len(expected_ids)
        assert {'manifest_record':producer} in call['source_references']
        assert 'source_provenance' in call['payload']['birth_source_authority']['records']
        # Both corruptions are applied only to this private fixture and always restored.
        source_path = Path(preparation['input_records']['particle_source']['path'])
        with patch('msplatform.execution.owner.run_managed_stage') as negative_owner:
            for label, path in (('particle_source', source_path), ('compiled_model', model_path)):
                original = path.read_bytes()
                negative_owner.reset_mock()
                try:
                    path.write_bytes(original + b'\n')
                    try:
                        recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=field_ref,
                            species_id='installed_fixture_species', expected_particle_ids=[int(value) for value in expected_ids],
                            observations={'plane_observations':[]}, context=context)
                    except AssertionError as error:
                        assert 'byte count changed' in str(error) and str(path) in str(error), (label, str(error))
                    else:
                        raise AssertionError('tampered ' + label + ' accepted')
                    negative_owner.assert_not_called()
                finally:
                    path.write_bytes(original)
                assert path.read_bytes() == original
        assert not (run/'simion').exists()
