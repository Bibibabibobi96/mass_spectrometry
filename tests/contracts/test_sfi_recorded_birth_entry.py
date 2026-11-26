"""Historical recorded-birth entry rejects retired composite execution before owner."""
import copy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.examples import load_example
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.model import PHYSICS, compile_prepared_model, project_resolved_drive
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.workflows.single_reflection_flight import recorded_birth
from msplatform.workflows.single_reflection_flight.prepare import prepare
from tests.workflows.single_reflection.test_single_reflection_preparation import scientific_preparation_fixture, write_json


def historical_fixture(root):
    """Frozen old-format inputs and inert FieldBundle, never a native run."""
    request_path, run, request = scientific_preparation_fixture(root, recorded_birth=True)
    request['flight'] = dict(pulse=load_example('rf_oatof_functional_v1').drive['pulse'],
        maximum_flight_us=200., maximum_step_us=.001, trajectory_quality=17, rf_steps_per_period=80)
    write_json(request_path, request)
    receipt = prepare(request_path, run)
    records = {**receipt['input_records'], **receipt['outputs']}
    publish_terminal_state(run, {'status':'success'}, dict(schema_version=2, role='simulation_run_manifest',
        run_id='historical-fixture', project='instrument_assembly', mode='single_reflection_flight',
        status='success', inputs=records, outputs=[]))
    components = {name:json.loads(Path(receipt['input_records']['instance_design__'+name]['path']).read_text())
                  for name in request['providers']['instances']}
    plan = json.loads((run/'inputs/composition_plan.json').read_text())
    domains = {name:{k:v for k,v in row.items() if k!='refine_convergence_v'}
               for name,row in request['numerics']['frontend_domains'].items()}
    tof = components['oatof']
    geometry = compile_geometry(dict(composition_plan=plan,components_resolved=components),
        numerics=dict(frontend_domains=domains,geometry_build=tof['simion_geometry_build'],
            detector_marker=tof['simion_detector_marker'],electrode_group_native_ids={
                name:value['electrode_bindings'] for name,value in request['providers']['instances'].items()}))
    epoch = receipt['input_records']['instrument_epoch']
    drive = project_resolved_drive(geometry,components,pulse=request['flight']['pulse'],
        clock=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256=epoch['sha256'],
                   phase_reference_instrument_time_us=0.))
    model = compile_prepared_model(geometry,components,drive=drive,physics=PHYSICS)
    field_dir=root/'inert-field';field_dir.mkdir();model_path=field_dir/'compiled_model.json'
    model_path.write_text(json.dumps(model.document),encoding='utf8')
    data=dict(compiled_model=file_record(model_path),instrument_epoch=epoch,
              clock_authority=receipt['input_records']['clock_authority'])
    metadata=dict(backend='simion',field_status='available',source_status='not_requested',
        model_identity_sha256=model.document['model_identity_sha256'],clock=model.document['drive']['clock'],fixture_only=True)
    publish_terminal_state(field_dir,{'status':'success'},dict(schema_version=2,role='simulation_run_manifest',
        run_id='inert-field',project='instrument_assembly',mode='software-fixture',status='success',inputs=data,outputs=[],
        products={'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=data)}))
    with (run/'inputs/projected_source.csv').open(encoding='utf8',newline='') as stream:
        ids=[int(row['particle_id']) for row in csv.DictReader(stream)]
    return dict(preparation_manifest=file_record(run/'run_manifest.json'),
        fields={'manifest':file_record(field_dir/'run_manifest.json'),'product_id':'fields'},
        species_id='inert_fixture_species',expected_particle_ids=ids,observations={'plane_observations':[]},
        context=SimpleNamespace(tools={'simion':Path(sys.executable)})), receipt, model_path


class RecordedBirthEntryTests(unittest.TestCase):
    def test_old_request_parameter_is_rejected_before_entry(self):
        script = Path(__file__).resolve().parents[2] / 'src/msplatform/workflows/resources/single_reflection_flight.ps1'
        command = [shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File', str(script),
                   '-PreparationManifest', 'unused', '-FieldsReference', 'unused', '-SpeciesId', 'unused',
                   '-ExpectedParticleIds', 'unused', '-Observations', 'unused', '-Environment', 'unused',
                   '-Workspace', 'unused', '-Profile', 'unused', '-Request', 'old.json']
        result = subprocess.run(command, cwd=script.parents[4], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Request', result.stderr)
        self.assertNotIn('OWNER_RETURNED=', result.stdout)

    def invoke_historical_entry(self, root, selected, *, recovery=None):
        def save(name, value):
            path=root/(name+'.json');path.write_text(json.dumps(value),encoding='utf8');return str(path)
        args=['entry','--preparation-manifest',selected['preparation_manifest']['path'],
              '--fields-reference',save('fields',selected['fields']),
              '--species-id',selected['species_id'],'--expected-particle-ids',save('ids',selected['expected_particle_ids']),
              '--observations',save('observations',selected['observations']),
              '--environment',str(root/'unused-env.json'),'--workspace',str(root),'--profile','fixture']
        if recovery is not None:args.extend(['--recovery-reference',save('recovery',recovery)])
        with patch('msplatform.execution.load_environment',return_value=selected['context']), patch.object(sys,'argv',args):
            recorded_birth.main()

    def test_historical_entry_refuses_before_owner_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            selected, receipt, model_path = historical_fixture(Path(directory))
            with patch('msplatform.execution.owner.run_managed_stage') as owner:
                with self.assertRaisesRegex(ValueError,'legacy composite.*read-only'):
                    self.invoke_historical_entry(Path(directory),selected)
                owner.assert_not_called()
                source=Path(receipt['input_records']['particle_source']['path'])
                for path in (source,model_path):
                    original=path.read_bytes()
                    try:
                        path.write_bytes(original+b'\\n')
                        with self.assertRaisesRegex(AssertionError,'byte count changed'):
                            recorded_birth.track_recorded_birth(**selected)
                        owner.assert_not_called()
                    finally:path.write_bytes(original)

    def test_historical_recovery_reference_does_not_enable_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            selected, _, _ = historical_fixture(Path(directory))
            selected=copy.copy(selected)
            selected['recovery_reference']={'path':str(Path(directory)/'unused-recovery-manifest.json')}
            with patch('msplatform.execution.owner.run_managed_stage') as owner:
                with self.assertRaisesRegex(ValueError,'legacy composite.*read-only'):
                    self.invoke_historical_entry(Path(directory),selected,recovery=selected['recovery_reference'])
                owner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
