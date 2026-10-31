"""Analytic CSV/native-boundary fixtures only; never real field/native evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

import pandas as pd

from common.contracts.write_run_manifest import file_record, TERMINAL_JOURNAL_NAME
from integrations.tests import test_cooled_frontend_reference as reference_fixture
from integrations.tests.test_cooled_frontend_field_design import harmonic_response_fixture, design_arguments
from integrations.workflows.cooled_frontend import runtime, field_design, reference
from integrations.workflows.cooled_frontend.prepare import prepare_cooled_frontend

REPO = Path(__file__).resolve().parents[2]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


class StaticProbeReuseTests(unittest.TestCase):
    def setUp(self):
        fixture = reference_fixture.SharedFieldIdentityTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.source = fixture.owner
        self.workspace = fixture.workspace
        self.rows = list(runtime.fields(self.source)['records'].values())
        responses = harmonic_response_fixture()
        responses['pulse_delta'] = responses['hp_common_unit'].copy()
        for frame in responses.values():
            frame['name'] = frame['name'].replace({'well_center': 'well_62', 'oa_entry': 'oa_side_entry'})
        self.responses = responses
        points = responses['carrier_off'][['name', 'x_mm', 'y_mm', 'z_mm']]
        points.to_csv(self.source/'inputs/cooled_probe_points.csv', index=False)
        sampler = self.source/'inputs/code/integrations/workflows/cooled_frontend/sample_field.lua'
        sampler.parent.mkdir(parents=True)
        shutil.copyfile(Path(runtime.__file__).with_name('sample_field.lua'), sampler)
        identity = json.loads(Path(self.rows[0]['cache_identity_record']['path']).read_text())['simion_identity']
        native = self.source/'inputs/native_discovery.json'
        write(native, dict(bytes=identity['executable_bytes'], sha256=identity['executable_sha256'], file_version=identity['file_version']))
        profile = self.source/'inputs/cooled_field_design_profile.json'
        write(profile, dict(native_executed=True, fly_executed=False,
            probe_plan_record=file_record(self.source/'inputs/cooled_probe_plan.json'),
            probe_points_record=file_record(self.source/'inputs/cooled_probe_points.csv'), native_discovery_record=file_record(native)))
        records = {}
        logs = []
        for kind in runtime.KINDS:
            path = self.source/'results/cooled_field_probe'/(kind+'.csv')
            path.parent.mkdir(parents=True, exist_ok=True)
            responses[kind].to_csv(path, index=False)
            records[kind] = file_record(path)
            log = self.source/'logs'/('field_probe_'+kind+'.stdout.log')
            log.parent.mkdir(exist_ok=True)
            log.write_text('COOLED_FIELD_PROBE=PASS samples='+str(len(points))+'\n', encoding='utf-8')
            logs.append(file_record(log))
        design = self.source/'results/cooled_field_design/voltage_design.json'
        write(design, dict(native_probe_records=records, response_projections={row['kind']: dict(
            scale=1., source_member=row, raw_probe_record=records[row['kind']]) for row in self.rows}))
        manifest = json.loads((self.source/'run_manifest.json').read_text())
        manifest['inputs'] = {key: value for key, value in manifest['inputs'].items() if value.get('path') != str(profile.resolve())}
        manifest['inputs'].update(profile=file_record(profile), probe_points=file_record(self.source/'inputs/cooled_probe_points.csv'),
            probe_plan=file_record(self.source/'inputs/cooled_probe_plan.json'), sampler=file_record(sampler), native=file_record(native))
        manifest['outputs'].extend([file_record(design), *records.values(), *logs])
        write(self.source/'run_manifest.json', manifest)
        self.source_manifest = file_record(self.source/'run_manifest.json')
        self.fixture.envelope['source_owner_manifest_record'] = self.source_manifest
        self.fixture.envelope['source_owner_profile_record'] = file_record(profile)
        envelope = self.workspace/'artifacts/probe_source.json'
        write(envelope, self.fixture.envelope)
        self.fixture.request['field_source'] = file_record(envelope)
        write(self.fixture.request_path, self.fixture.request)
        self.run = self.workspace/'artifacts/projects/instrument_assembly/runs/20261031_010000__test__python__probe-reuse'
        prepare_cooled_frontend(self.fixture.request_path, self.run, REPO, self.workspace, run_id=self.run.name)
        shutil.copyfile(self.source/'inputs/cooled_probe_points.csv', self.run/'inputs/cooled_probe_points.csv')
        write(self.run/'inputs/cooled_frontend_field_stage_receipt.json', dict(working_points=self.rows))
        write(self.run/'run_manifest.json', dict(status='checkpoint'))
        self.before = (self.source/'run_manifest.json').read_bytes()

    def plan(self):
        original = runtime.file_sha256
        def checked(path):
            if Path(path).suffix.lower() == '.pa':
                raise AssertionError('protected PA was rehashed')
            return original(path)
        with patch.object(runtime, 'file_sha256', side_effect=checked):
            return runtime.static_probe_reuse_plan(self.run)

    def test_all_reuse_and_single_missing_keep_original_records_and_parent(self):
        selected = self.plan()
        self.assertEqual(selected['missing_members'], [])
        self.assertEqual(set(selected['native_probe_records']), set(runtime.KINDS))
        result = runtime.complete_static_probe_records(self.run, selected)
        self.assertEqual(result['native_probe_records'], selected['native_probe_records'])
        self.assertFalse((self.run/'results/cooled_field_probe').exists())
        refs = runtime.static_probe_source_references(self.run)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['manifest_record'], self.source_manifest)
        self.assertEqual(len(refs[0]['protected_paths']), 7)
        (self.source/'logs/field_probe_pulse_delta.stdout.log').unlink()
        missing = self.plan()
        self.assertEqual(missing['missing_members'], ['pulse_delta'])
        self.assertEqual(len(missing['native_probe_records']), 6)
        self.assertEqual((self.source/'run_manifest.json').read_bytes(), self.before)

    def test_transitive_selection_keeps_original_owner_and_raw_generation(self):
        selected = self.plan()
        intermediate = self.workspace/'artifacts/projects/instrument_assembly/runs/half_scale_owner'
        design = json.loads((self.source/'results/cooled_field_design/voltage_design.json').read_text(encoding='utf-8'))
        for projection in design['response_projections'].values():
            projection['probe_owner_manifest_record'] = self.source_manifest
        design['response_projections']['pulse_delta']['scale'] = .5
        design['response_projections']['pulse_delta']['source_member']['field_scale'] = .5
        path = intermediate/'results/cooled_field_design/voltage_design.json'
        write(path, design)
        config = intermediate/'run_config.json'
        write(config, dict(project='instrument_assembly'))
        intermediate_profile = intermediate/'inputs/cooled_field_design_profile.json'
        write(intermediate_profile, dict(native_executed=False, fly_executed=False))
        manifest = intermediate/'run_manifest.json'
        write(manifest, dict(status='success', run_config=file_record(config), inputs=dict(profile=file_record(intermediate_profile)), outputs=[file_record(path)]))
        envelope = copy.deepcopy(self.fixture.envelope)
        envelope['source_owner_manifest_record'] = file_record(manifest)
        envelope_path = self.workspace/'artifacts/half_scale_source.json'
        write(envelope_path, envelope)
        experiment_path = self.run/'inputs/cooled_experiment.json'
        experiment = json.loads(experiment_path.read_text(encoding='utf-8'))
        experiment['field_source'] = file_record(envelope_path)
        write(experiment_path, experiment)
        rows = copy.deepcopy(self.rows)
        rows[4]['field_scale'] = .25
        write(self.run/'inputs/cooled_frontend_field_stage_receipt.json', dict(working_points=rows))
        actual = self.plan()
        self.assertEqual(actual['missing_members'], [])
        self.assertEqual(actual['native_probe_records'], selected['native_probe_records'])
        self.assertTrue(all(owner == self.source_manifest for owner in actual['probe_owner_manifest_records'].values()))
        references = runtime.static_probe_source_references(self.run)
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]['manifest_record'], self.source_manifest)
        self.assertEqual((self.source/'run_manifest.json').read_bytes(), self.before)

    def test_plan_points_sampler_generation_and_pending_owner_fail_closed(self):
        mutations = ('points', 'sampler', 'generation', 'pending')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                stage_path = self.run/'inputs/cooled_frontend_field_stage_receipt.json'
                points_path = self.run/'inputs/cooled_probe_points.csv'
                sampler = self.source/'inputs/code/integrations/workflows/cooled_frontend/sample_field.lua'
                originals = {p: p.read_bytes() for p in (stage_path, points_path, sampler)}
                if mutation == 'points':
                    points_path.write_text(points_path.read_text()+'\n', encoding='utf-8')
                elif mutation == 'sampler':
                    sampler.write_text(sampler.read_text()+'\n', encoding='utf-8')
                elif mutation == 'generation':
                    rows = copy.deepcopy(self.rows);rows[4]['generation_sha256'] = '0'*64
                    write(stage_path, dict(working_points=rows))
                else:
                    write(self.source/TERMINAL_JOURNAL_NAME, {'test_only': True})
                result = self.plan()
                self.assertEqual(result['missing_members'], ['pulse_delta'] if mutation == 'generation' else list(runtime.KINDS))
                for path, content in originals.items():
                    path.write_bytes(content)
                (self.source/TERMINAL_JOURNAL_NAME).unlink(missing_ok=True)

    def test_real_analysis_references_raw_once_and_rejects_unbound_csv(self):
        selected = self.plan()
        metadata = runtime.complete_static_probe_records(self.run, selected)
        write(self.run/'results/cooled_static_probe_costs.json', metadata)
        # Analytic physics is the same actual analysis consumer used by the runner.
        write(self.run/'inputs/conditioner_contract.json', dict(geometry=dict(trap_center_mr_mm=[0.,28.,32.]), gas=dict(parameters=dict(temperature_k=300.))))
        write(self.run/'inputs/guide_contract.json', dict(drive=dict(frequency_hz=3.7e6, rf_amplitude_v=500.)))
        write(self.run/'inputs/cooled_design_targets.json', dict(thermal_sigma_y_mm=.4, static_release_energy_gain_ev=5.))
        pd.DataFrame([dict(particle_id=1, mass_amu=524., charge_state=1)]).to_csv(self.run/'inputs/release_global.csv', index=False)
        raw = Path(selected['native_probe_records']['pulse_delta']['path']).read_bytes()
        for scale in (.5, .25):
            with self.subTest(scale=scale):
                rows = copy.deepcopy(self.rows);rows[4]['field_scale'] = scale
                write(self.run/'inputs/cooled_frontend_field_stage_receipt.json', dict(working_points=rows))
                with patch.object(field_design, 'project_member_samples', wraps=field_design.project_member_samples) as projected:
                    result = field_design.analyze_field_run(self.run)
                pulse_calls = [call for call in projected.call_args_list if call.args[1] == 'pulse_delta']
                self.assertEqual(len(pulse_calls), 1)
                self.assertEqual(pulse_calls[0].args[2], scale)
                pd.testing.assert_frame_equal(pulse_calls[0].args[0], pd.read_csv(Path(metadata['native_probe_records']['pulse_delta']['path'])))
                self.assertEqual(result['response_projections']['pulse_delta']['scale'], scale)
                self.assertEqual(result['native_probe_records'], metadata['native_probe_records'])
                self.assertEqual(Path(result['native_probe_records']['pulse_delta']['path']).read_bytes(), raw)
                shutil.rmtree(self.run/'results/cooled_field_design')
        bad = copy.deepcopy(metadata)
        bad['probe_owner_manifest_records'].pop('pulse_delta')
        write(self.run/'results/cooled_static_probe_costs.json', bad)
        with self.assertRaises((KeyError, ValueError)):
            field_design.analyze_field_run(self.run)
        self.assertEqual((self.source/'run_manifest.json').read_bytes(), self.before)

    def test_reference_consumer_requires_bound_original_owner(self):
        selected = self.plan()
        intermediate = self.workspace/'artifacts/projects/instrument_assembly/runs/intermediate_probe_owner'
        arguments = design_arguments()
        arguments.update(release_reference_name='well_62', oa_entry_reference_name='oa_side_entry')
        design = field_design.design_voltage_controls(self.responses, **arguments)
        design.update(design_status='proposal_computed', native_probe_records=selected['native_probe_records'],
                      target_record=file_record(self.run/'inputs/cooled_design_targets.json'),
                      response_projections={kind: dict(probe_owner_manifest_record=self.source_manifest)
                                            for kind in runtime.KINDS})
        design_path = intermediate/'results/cooled_field_design/voltage_design.json'
        write(design_path, design)
        manifest = intermediate/'run_manifest.json'
        write(manifest, dict(status='success', outputs=[file_record(design_path)]))
        envelope = self.workspace/'artifacts/intermediate_probe_source.json'
        write(envelope, dict(source_owner_manifest_record=file_record(manifest)))
        experiment_path = self.run/'inputs/cooled_experiment.json'
        experiment = json.loads(experiment_path.read_text(encoding='utf-8'))
        experiment.update(pressure_scale=0, common_pulse_decision=None, field_source=file_record(envelope))
        write(experiment_path, experiment)
        context = dict(records={row['kind']: row for row in self.rows}, receipt=file_record(
            self.run/'inputs/cooled_frontend_field_stage_receipt.json'))
        # Existing tests cover field/source admission; this thin consumer isolates
        # ancestor CSV binding at the actual prepare_reference/calculator boundary.
        before = (self.run/'inputs/release_global.csv').read_bytes()
        with patch.object(runtime, 'fields', return_value=context):
            result = reference.prepare_reference(self.run)
        self.assertEqual(result['native_probe_records'], selected['native_probe_records'])
        self.assertEqual(result['mother_count'], 100)
        self.assertEqual((self.run/'inputs/release_global.csv').read_bytes(), before)
        self.assertEqual((self.source/'run_manifest.json').read_bytes(), self.before)
        design['response_projections']['pulse_delta'].pop('probe_owner_manifest_record')
        write(design_path, design)
        write(manifest, dict(status='success', outputs=[file_record(design_path)]))
        write(envelope, dict(source_owner_manifest_record=file_record(manifest)))
        experiment['field_source'] = file_record(envelope)
        write(experiment_path, experiment)
        with patch.object(runtime, 'fields', return_value=context), self.assertRaisesRegex(ValueError, 'not bound'):
            reference.prepare_reference(self.run)

    def test_actual_powershell_consumer_zero_one_and_unknown_writer(self):
        (self.run/'logs').mkdir(exist_ok=True)
        script = self.workspace/'probe_consumer.ps1'
        script.write_text(r'''param($Repo,$Python,$Run,$Source,$Mode)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/cooled_frontend/execute.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw $errors[0]}
foreach($name in @('Protect-CooledStaticProbeSources','Invoke-CooledFieldDesign')){
 $f=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq$name},$true))
 if($f.Count-ne1){throw "function count $name"};Invoke-Expression $f[0].Extent.Text
}
$script:calls=0;$script:copies=0;$script:removed=0;$script:refs=0;$script:temp=$null
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$SourceReferences)
 $script:refs=@($SourceReferences).Count;return @{session=$Session}}
function Invoke-CooledOrdinaryFieldBuild {param($Package,$FrozenRepoRoot,$Python,$RuntimeModule,$SimionExe,$Limits,$HostLease,$CapacitySession,$NativeOperations,$NativeResourceReleaseId)
 $receipt=Get-Content (Join-Path $Run 'inputs/cooled_frontend_field_stage_receipt.json') -Raw|ConvertFrom-Json -Depth 100
 return @{receipt=$receipt;working_points=@($receipt.working_points);field_directory='not-materialized'}}
function New-ShortPaCopy {param($Source,$Destination,$ExpectedBytes,$ExpectedSha256)
 if($Mode-eq'all'){throw 'UNEXPECTED_COPY'};$script:copies++;$script:temp=Split-Path $Destination
 New-Item -ItemType Directory $script:temp -Force|Out-Null
 [IO.File]::WriteAllText($Destination,'inert native-boundary fixture');return $Destination}
function Confirm-ShortPaCopyIdentity {param($Path)if(-not(Test-Path $Path)){throw 'copy missing'}}
function Remove-ShortPaCopyDirectory {param($Path)$script:removed++;Remove-Item -LiteralPath $Path -Recurse -Force}
function Invoke-CooledNative {param($Package,$RunDirectory,$SimionExe,$Limits,$WorkingDirectory,$NativeOperations,$NativeResourceReleaseId,$Name,$Arguments)
 if($Mode-eq'all'){throw 'UNEXPECTED_NATIVE'};$script:calls++
 if($Name-ne'field_probe_pulse_delta'){throw "unexpected $Name"}
 if($Mode-eq'unknown'){$e=[Exception]::new('ORIGINAL_NATIVE_UNKNOWN');$e.Data['observed_process_exit_confirmed']=$false;throw $e}
 Copy-Item -LiteralPath (Join-Path $Source 'results/cooled_field_probe/pulse_delta.csv') -Destination $Arguments[-1]
}
$package=[pscustomobject]@{artifact_run_dir=$Run;input_dir=(Join-Path $Run 'inputs');result_dir=(Join-Path $Run 'results')}
$hostLease=@{};$session=@{};$readers=[Collections.Generic.List[object]]::new();$failure=$null
try{
 try{$null=Invoke-CooledFieldDesign -Package $package -FrozenRepoRoot $Repo -Python $Python -RuntimeModule unused -SimionExe never.exe -Limits @{} -HostLease ([ref]$hostLease) -CapacitySession ([ref]$session) -SourceReaders $readers}
 catch{$failure=$_.Exception.Message;if($Mode-ne'unknown'){throw}}
 $cost=Get-Content (Join-Path $Run 'results/cooled_static_probe_costs.json') -Raw|ConvertFrom-Json -Depth 100
 [pscustomobject]@{calls=$script:calls;copies=$script:copies;removed=$script:removed;refs=$script:refs;failure=$failure;cost=$cost;temp_exists=($script:temp-and(Test-Path $script:temp));readers=$readers.Count}|ConvertTo-Json -Depth 100 -Compress
}finally{
 foreach($reader in $readers){$reader.Dispose()}
 # No actual native process was launched by this test; its own unknown sentinel
 # is now explicitly resolved, so its private inert test directory can be removed.
 if($script:temp-and(Test-Path $script:temp)){Remove-Item -LiteralPath $script:temp -Recurse -Force}
}
''', encoding='utf-8')
        for mode in ('all', 'one', 'unknown'):
            with self.subTest(mode=mode):
                if mode != 'all':
                    (self.source/'logs/field_probe_pulse_delta.stdout.log').unlink(missing_ok=True)
                completed = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable,
                    str(self.run), str(self.source), mode], cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
                result = json.loads(completed.stdout.strip().splitlines()[-1])
                expected = 0 if mode == 'all' else 1
                self.assertEqual(result['calls'], expected)
                self.assertEqual(result['copies'], expected)
                self.assertEqual(result['removed'], int(mode == 'one'))
                self.assertEqual(result['refs'], 1)
                self.assertGreaterEqual(result['readers'], 1)
                self.assertEqual(result['temp_exists'], mode == 'unknown')
                if mode == 'unknown':
                    self.assertEqual(result['failure'], 'ORIGINAL_NATIVE_UNKNOWN')
                    self.assertEqual(result['cost']['execution_status'], 'writer_completion_unknown')
                else:
                    self.assertEqual(result['cost']['native_probe_calls'], expected)
                    self.assertEqual(result['cost']['reused_probe_count'], 7-expected)
                self.assertEqual((self.source/'run_manifest.json').read_bytes(), self.before)


class ProfileNativeFactTests(unittest.TestCase):
    def test_actual_profile_python_uses_this_runs_observed_operation_count(self):
        text = (REPO/'integrations/workflows/cooled_frontend/execute.ps1').read_text(encoding='utf-8')
        code = text.split("$profileCode=@'", 1)[1].split("'@", 1)[0]
        self.assertIn("$scope,[string]$nativeOperations.Count)", text)
        for scope, count in (('fielddesign_only', 0), ('fielddesign_only', 1), ('local_static_mesh_check', 29)):
            with self.subTest(scope=scope, native_operations=count), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                for name in ('frontend.gem', 'frontend_contract.json', 'cooled_field_plan.json',
                             'cooled_probe_plan.json', 'cooled_probe_points.csv', 'native_discovery.json'):
                    path = run/'inputs'/name
                    path.parent.mkdir(exist_ok=True)
                    path.write_text('inert profile control fixture', encoding='utf-8')
                with patch.object(sys, 'argv', ['profile', str(run), scope, str(count)]):
                    exec(compile(code, 'actual_frozen_profile_code', 'exec'), {})
                profile = json.loads((run/'inputs/cooled_field_design_profile.json').read_text(encoding='utf-8'))
                self.assertIs(profile['native_executed'], count > 0)
                self.assertIs(profile['fly_executed'], False)
                self.assertEqual(profile['role'], 'cooled_frontend_local_mesh_profile' if scope == 'local_static_mesh_check' else 'cooled_frontend_field_design_profile')
