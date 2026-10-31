"""Actual public wrapper and Python analysis; synthetic CSVs, no native solver."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.write_run_manifest import file_record
from common.contracts.capacity_ledger import initialize_capacity_ledger
from projects.rf_multipole_ion_optics.tests.domain.test_analyze_comsol_transport_metrics import scenario

REPO = Path(__file__).resolve().parents[4]
WRAPPER = REPO / 'projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_comsol.ps1'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def table(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)


def engineering_budget(*, retention_class='solver_review', transient=33554432):
    scope = dict(project_id='rf_multipole_ion_optics', runtime_profile_id='frozen-runtime', stop_stage='transport',
                 design_profile_id='frozen-design', particle_source_profile_id='frozen-source', particle_count=1,
                 solver_numerics_profile_ids=dict(comsol='frozen-comsol', simion='frozen-simion'),
                 allowed_solvers=['comsol'], retention_class=retention_class)
    return dict(schema_version=1, role='multipole_engineering_budget_contract', project_id='rf_multipole_ion_optics',
                contract_id='inert-analysis-budget', preregistered_before_run=True,
                pilot_authorization=dict(authorized=True, scope=scope, limits=dict(
                    wall_clock_seconds_by_solver=dict(comsol=60, simion=60), transient_run_directory_bytes=transient,
                    process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1073741824,
                    compact_final_retained_bytes=8388608, automatic_retry_count=0)),
                full_matrix_authorization=dict(authorized=False, reason='only software analysis'),
                budget_exhaustion_result='stop without retry', claim_limit='inert fixture, no solve authorization')


def parent_fixture(root, *, fault=None):
    artifacts = root/'artifacts'
    artifacts.mkdir()
    run = artifacts/'projects/rf_multipole_ion_optics/runs/20261031_060000__test__python__sealed-csv-parent'
    inputs = run/'inputs'
    outputs = run/'results'
    state, events, resolved, numerics = scenario([(17, 'unknown', 'time_window_end', 'unresolved', 'none')])
    resolved['identity']['project_id'] = 'rf_multipole_ion_optics'
    resolved['resolved_sha256'] = 'A'*64
    for row in state:
        row.update(axial_z_mm='0', transverse_x_mm='0', transverse_y_mm='0', divergence_angle_deg='0',
                   elapsed_time_us='0', velocity_axial_m_s='1', velocity_x_m_s='0', velocity_y_m_s='0', time_us='0')
    scientific = dict(multipole_resolved_design=resolved, solver_numerics=numerics,
                      particle_source_metadata=dict(particle_count=1), engineering_budget=engineering_budget())
    paths = {}
    for name, document in scientific.items():
        path = inputs/(name+'.json')
        write(path, document)
        paths[name] = str(path)
    source = inputs/'particle_source.csv'
    table(source, [dict(particle_id='91' if fault == 'mother' else '17', x_mm='0')])
    paths['particle_source'] = str(source)
    if fault == 'science_fail':
        evidence = inputs/'evidence_contract.json'
        write(evidence, dict(schema_version=1, role='multipole_transport_evidence_contract',
              project_id='rf_multipole_ion_optics', design_profile_id='frozen-design', evaluation='rf_vs_zero_rf',
              thresholds=dict(minimum_primary_transmission=1, minimum_transmission_improvement=0)))
        paths['evidence_contract'] = str(evidence)
    request = inputs/'execution_request.json'
    write(request, dict(capacity=dict(committed_new_bytes=67108864)))
    paths['execution_request'] = str(request)
    task = inputs/'code/projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m'
    task.parent.mkdir(parents=True)
    shutil.copyfile(REPO/'projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m', task)
    paths['comsol_task'] = str(task)
    entry = inputs/'code/projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'
    entry.parent.mkdir(parents=True)
    shutil.copyfile(REPO/'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1', entry)
    inventory = inputs/'code_inventory.json'
    write(inventory, dict(schema_version=1, role='frozen_code_inventory', files=[dict(
        path='projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m', sha256=file_record(task)['sha256']), dict(
        path='projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1', sha256=file_record(entry)['sha256'])]))
    helper = inputs/'code/projects/rf_multipole_ion_optics/comsol/export_finite_3d_particle_outputs.m'
    helper_source = REPO/'projects/rf_multipole_ion_optics/comsol/export_finite_3d_particle_outputs.m'
    if helper_source.exists():
        shutil.copyfile(helper_source, helper)
        document = json.loads(inventory.read_text(encoding='utf-8'))
        document['files'].append(dict(path='projects/rf_multipole_ion_optics/comsol/export_finite_3d_particle_outputs.m', sha256=file_record(helper)['sha256']))
        write(inventory, document)
    paths['code_inventory'] = str(inventory)
    write(request, dict(capacity=dict(committed_new_bytes=67108864),
                        prepared=dict(owner_kind='powershell', entrypoint=file_record(entry))))
    report = run/'logs/comsol_finite_3d_transport.txt'
    report.parent.mkdir(parents=True)
    # Explicit synthetic native-stage boundary fixture, never solver evidence.
    report.write_text('TASK=MULTIPOLE_FINITE_3D_TRANSPORT\nCHECKPOINT=PRIMARY_PARTICLE_CASE_COMPLETE\n'
                      'CHECKPOINT=CONTROL_PARTICLE_CASE_COMPLETE\nRAW_SOLUTION_PERSISTED=true\n'
                      'TIMING_EXTRACT_SECONDS=0\n'+('ERROR=stack literal TIMING_NATIVE_EXPORT_SECONDS=0\nSTATUS=FAIL\n' if fault == 'native_incomplete'
                        else 'TIMING_NATIVE_EXPORT_SECONDS=0\nMODEL_SAVED=true\nSTATUS=PASS\n'), encoding='utf-8')
    if fault == 'legacy_pass_no_timing':
        report.write_text('TASK=MULTIPOLE_FINITE_3D_TRANSPORT\nMODEL_SAVED=true\nSTATUS=PASS\n', encoding='utf-8')
    config = run/'run_config.json'
    write(config, dict(schema_version=1, role='multipole_resolved_comsol_run_config', project='rf_multipole_ion_optics',
                       run_id=run.name, mode='resolved_design_transport', inputs=paths,
                       parameters=dict(stop_stage='transport', runtime_profile_id='frozen-runtime', design_profile_id='frozen-design'),
                       paths=dict(source_root=str(REPO), artifact_root=str(artifacts),
                                  execution_root=str(artifacts/'common/execution_aliases'),
                                  host_resource_state_path=str(root/'host.sqlite3'))))
    if fault == 'bad_plot':
        state[0]['time_us'] = 'NaN'
    table(outputs/'particle_events.csv', events)
    table(outputs/'particle_state__primary.csv', state)
    table(outputs/'particle_state__control.csv', state)
    if fault in {'raw_saved', 'raw_saved_no_mapping'}:
        for path in outputs.iterdir():
            path.unlink()
        (outputs/'finite_3d_transport.mph').write_bytes(b'SYNTHETIC_TEST_MODEL_NEVER_OPEN')
        if fault != 'raw_saved_no_mapping':
            write(outputs/'release_source_mapping.json', dict(native_scope='complete_cohort', native_order=[1], source_ids=[17], source_birth_s=[0]))
        report.write_text('TASK=MULTIPOLE_FINITE_3D_TRANSPORT\nCHECKPOINT=PRIMARY_PARTICLE_CASE_COMPLETE\n'
                          'CHECKPOINT=CONTROL_PARTICLE_CASE_COMPLETE\nTIMING_PERSIST_SECONDS=0 RAW_SOLUTION_PERSISTED=true\nSTATUS=FAIL\n', encoding='utf-8')
    completion = outputs/'execution_completion.json'
    writers = dict(operations=[], resource_releases=[])
    if fault == 'unknown':
        writers['operations'] = [dict(operation_id='unknown-parent', observation=dict(exit_confirmed=False, returncode=None, process_id=999999, process_started_at_utc_ticks=1), resource_release_id='comsol')]
    write(completion, dict(run_id=run.name, project='rf_multipole_ion_optics', writer_completion=writers))
    manifest = run/'run_manifest.json'
    write(manifest, dict(schema_version=1, role='simulation_run_manifest', status='failed', project='rf_multipole_ion_optics',
                         run_id=run.name, mode='resolved_design_transport', run_config=file_record(config),
                         inputs={name:file_record(Path(path)) for name,path in paths.items()},
                         outputs=[file_record(path) for path in outputs.iterdir()]+[file_record(report)]))
    if fault == 'missing':
        (outputs/'particle_state__control.csv').unlink()
    initialize_capacity_ledger(artifacts, objects=[dict(path=run.relative_to(artifacts).as_posix(),
        **{'class': 'light_evidence'}, status='ready', bytes=sum(p.stat().st_size for p in run.rglob('*') if p.is_file()),
        owner='synthetic CSV test fixture')])
    return run, manifest


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
class ComsolAnalysisRecoveryTests(unittest.TestCase):
    def invoke(self, root, manifest, *, transient=33554432, reextract=False):
        budget_path = root/'analysis-budget.json'
        write(budget_path, engineering_budget(retention_class='compact', transient=transient))
        result = root/'analysis-result.json'
        run_id = '20261031_060001__analysis__python__csv-child'
        outcome = subprocess.run(['pwsh', '-NoProfile', '-File', str(WRAPPER), '-AnalyzeOnly', *(['-ReextractFromModel'] if reextract else []),
                                  '-ParentManifestPath', str(manifest), '-EngineeringBudgetPath', str(budget_path), '-PythonExe', sys.executable,
                                  '-RunId', run_id, '-ResultPath', str(result)],
                                 cwd=root, text=True, encoding='utf-8', capture_output=True, timeout=300)
        child = root/'artifacts/projects/rf_multipole_ion_optics/runs'/run_id
        return outcome, result, child

    def test_public_wrapper_creates_analysis_child_with_real_python_without_comsol(self):
        with tempfile.TemporaryDirectory(prefix='rf analysis spaces ') as directory:
            root = Path(directory)
            parent, manifest = parent_fixture(root)
            before = manifest.read_bytes()
            outcome, result_path, child = self.invoke(root, manifest)
            self.assertEqual(outcome.returncode, 0, outcome.stdout+outcome.stderr)
            result = json.loads(result_path.read_text(encoding='utf-8-sig'))
            self.assertEqual(result['status'], 'success')
            completion = json.loads((child/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
            operations = completion['writer_completion']['operations']
            self.assertEqual([item['operation_id'] for item in operations], ['python-analysis-metrics', 'python-analysis-exit_plot'])
            for item in operations:
                self.assertTrue(item['observation']['exit_confirmed'])
                self.assertEqual(item['observation']['returncode'], 0)
                self.assertGreater(item['observation']['process_id'], 0)
                self.assertGreater(item['observation']['process_started_at_utc_ticks'], 0)
            self.assertIn(str(result_path), outcome.stdout)
            for name in ('metrics', 'exit_plot'):
                usage = json.loads((child/f'results/analysis_{name}_resource_usage.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(usage['limits']['wall_clock_seconds'], 60)
                self.assertEqual(usage['limits']['process_tree_working_set_bytes'], 2147483648)
                self.assertIn('wall_clock_seconds', usage)
                self.assertIn('peak_process_tree_working_set_bytes', usage)
            metrics = json.loads((child/'results/finite_3d_transport_metrics.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(metrics['source_binding']['mother_particle_ids'], [17])
            self.assertEqual(metrics['cases']['finite_3d_rf_on']['cohort_census']['counts'], dict(transmitted=0, lost=0, unknown=1))
            self.assertFalse((child/'results/finite_3d_transport.mph').exists())
            self.assertFalse((child/'logs/comsol_launcher_completion.json').exists())
            summary = json.loads((child/'summary.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(summary['exit_state_plot_status'], 'not_applicable')
            self.assertEqual(summary['exit_state_plot_reason'], 'no_supported_exit_state_rows')
            self.assertFalse((child/'results/exit_state_diagnostics.png').exists())
            self.assertEqual(manifest.read_bytes(), before)
            self.assertTrue((parent/'results/particle_state__control.csv').exists())
            session = json.loads((child/'logs/capacity_session.json').read_text(encoding='utf-8-sig'))
            self.assertIn(str(parent/'results/particle_state__control.csv'), session['protected_paths'])
            self.assertIn(str(parent), session['protected_paths'])
            self.assertEqual(session['committed_new_bytes'], 33554432)
            self.assertNotEqual(session['committed_new_bytes'], 67108864)
            forecast = json.loads((child/'results/analysis_payload_forecast.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(forecast['referenced_native_and_csv_new_bytes'], 0)
            self.assertLess(forecast['required_new_bytes'], session['committed_new_bytes'])
            before_child = (child/'run_manifest.json').read_bytes()
            resume = subprocess.run(['pwsh', '-NoProfile', '-File', str(WRAPPER), '-ResumeFinalization',
                                     '-RunId', child.name, '-ResultPath', str(result_path),
                                     '-ArtifactRootPath', str(root/'artifacts'), '-PythonExe', sys.executable],
                                    cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=300)
            self.assertEqual(resume.returncode, 0, resume.stdout+resume.stderr)
            self.assertEqual((child/'run_manifest.json').read_bytes(), before_child)
            self.assertEqual(manifest.read_bytes(), before)


    def test_real_evaluator_scientific_fail_preserves_valid_negative_data_and_nonzero_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest = parent_fixture(root, fault='science_fail')
            before = manifest.read_bytes()
            outcome, result_path, child = self.invoke(root, manifest)
            self.assertNotEqual(outcome.returncode, 0)
            result = json.loads(result_path.read_text(encoding='utf-8-sig'))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['stage'], 'complete')
            self.assertEqual(result['execution_status'], 'completed')
            self.assertEqual(result['data_validity'], 'valid')
            self.assertEqual(result['scientific_result'], 'FAIL')
            self.assertIn(str(result_path), outcome.stdout)
            completion = json.loads((child/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(completion['writer_completion']['operations'][-1]['observation']['returncode'], 1)
            self.assertEqual(result['failure_stage'], 'scientific_evaluation')
            self.assertIn('minimum_primary_transmission', result['failure_reason'])
            self.assertEqual(result['recovery_action'], 'inspect_negative_result_or_start_explicit_new_study')
            summary = json.loads((child/'summary.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(summary['scientific_failed_checks'], ['minimum_primary_transmission'])
            decision = json.loads((child/'results/evidence_evaluation.json').read_text(encoding='utf-8-sig'))
            self.assertIs(decision['checks']['minimum_primary_transmission'], False)
            self.assertIs(decision['checks']['minimum_transmission_improvement'], True)
            self.assertEqual(manifest.read_bytes(), before)
            self.assertFalse((child/'results/finite_3d_transport.mph').exists())

    def test_source_mismatch_fails_real_analysis_without_changing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest = parent_fixture(root, fault='mother')
            before = manifest.read_bytes()
            outcome, result, child = self.invoke(root, manifest)
            self.assertNotEqual(outcome.returncode, 0)
            self.assertIn('source IDs differ from frozen particle source', outcome.stdout+outcome.stderr)
            self.assertEqual(json.loads(result.read_text(encoding='utf-8-sig'))['status'], 'failed')
            self.assertEqual(manifest.read_bytes(), before)
            self.assertFalse((child/'results/finite_3d_transport.mph').exists())

    def test_legacy_whole_native_pass_derives_stage_from_its_original_frozen_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest = parent_fixture(root, fault='legacy_pass_no_timing')
            before = manifest.read_bytes()
            code = r"""
param($Repo,$Python,$Manifest)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'),[ref]$null,[ref]$null)
$function=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-ceq'Get-FiniteComsolAnalysisSource'},$true))
if($function.Count-ne1){throw 'source admission function is ambiguous'}
Invoke-Expression $function[0].Extent.Text
$source=Get-FiniteComsolAnalysisSource -ManifestPath $Manifest -Python $Python -RepoRoot $Repo
$source.stage_evidence|ConvertTo-Json -Depth 20 -Compress
"""
            script = root/'read-original-stage.ps1'
            script.write_text(code, encoding='utf-8')
            outcome = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable, str(manifest)],
                                     capture_output=True, text=True, encoding='utf-8', cwd=root, timeout=300)
            self.assertEqual(outcome.returncode, 0, outcome.stdout+outcome.stderr)
            evidence = json.loads(outcome.stdout.strip().splitlines()[-1])
            self.assertEqual(evidence['basis'], 'frozen_producer_whole_native_PASS_MODEL_SAVED_and_bound_exports')
            self.assertEqual(manifest.read_bytes(), before)

    def test_analysis_requires_own_budget_and_rejects_insufficient_new_payload_before_new_run(self):
        absent = subprocess.run(['pwsh', '-NoProfile', '-File', str(WRAPPER), '-AnalyzeOnly',
                                 '-ParentManifestPath', 'must-not-open.json', '-PythonExe', sys.executable],
                                capture_output=True, text=True, encoding='utf-8', cwd=REPO, timeout=300)
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn('requires an explicit EngineeringBudgetPath', absent.stdout+absent.stderr)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest = parent_fixture(root)
            before = manifest.read_bytes()
            outcome, result, child = self.invoke(root, manifest, transient=1)
            self.assertNotEqual(outcome.returncode, 0)
            self.assertIn('new-payload budget is insufficient', outcome.stdout+outcome.stderr)
            self.assertFalse(result.exists())
            self.assertFalse(child.exists())
            self.assertEqual(manifest.read_bytes(), before)

    def test_public_wrapper_rejects_scientific_override_before_parent_or_solver_work(self):
        outcome = subprocess.run(['pwsh', '-NoProfile', '-File', str(WRAPPER), '-AnalyzeOnly',
                                  '-ParentManifestPath', 'must-not-be-opened.json', '-EngineeringBudgetPath', 'not-read-budget.json', '-EvidenceContractPath', 'today.json',
                                  '-PythonExe', sys.executable], capture_output=True, text=True, encoding='utf-8', cwd=REPO, timeout=300)
        self.assertNotEqual(outcome.returncode, 0)
        self.assertIn('parent frozen scientific authority', outcome.stdout+outcome.stderr)

    def test_missing_exports_and_unknown_writer_reject_before_new_run(self):
        for fault, reason in (('missing', 'REEXTRACTION_REQUIRED'), ('unknown', 'completion'),
                              ('native_incomplete', 'TRANSPORT_STAGE_EVIDENCE_MISSING')):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, manifest = parent_fixture(root, fault=fault)
                before = manifest.read_bytes()
                outcome, result, child = self.invoke(root, manifest)
                self.assertNotEqual(outcome.returncode, 0)
                self.assertIn(reason.lower(), (outcome.stdout+outcome.stderr).lower())
                self.assertFalse(child.exists())
                self.assertFalse(result.exists())
                self.assertEqual(manifest.read_bytes(), before)

    def test_observer_unknown_exit_keeps_writer_unknown_and_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root/'unknown-observer.ps1'
            script.write_text(r"""
param($Repo,$Root)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'),[ref]$null,[ref]$null)
$function=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-ceq'Invoke-FiniteComsolAnalysis'},$true))
if($function.Count-ne1){throw 'Actual shared analysis function missing'}
Invoke-Expression $function[0].Extent.Text
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$RedirectStandardOutput,$RedirectStandardError)
 $failure=[Exception]::new('ACTUAL_OBSERVER_EXIT_UNKNOWN')
 $failure.Data['observed_process_exit_confirmed']=$false
 $failure.Data['observed_process_returncode']=$null
 throw $failure
}
$ownerContext=@{run_directory=$Root;result_path=(Join-Path $Root 'stable-result.json')}
$ownerState=@{writer_unknown=$false;timer=[Diagnostics.Stopwatch]::StartNew()}
$codeRoot=$Repo;$python='not-started';$events='unused';$primaryState='unused';$controlState='unused';$resolved='unused';$numerics='unused'
try{Invoke-FiniteComsolAnalysis -OwnerContext $ownerContext -OwnerState $ownerState -CodeRoot $Repo -Python $python -ResultDir $Root -Summary unused -AnalysisLimits ([pscustomobject]@{wall_clock_seconds=60})}catch{$primary=$_.Exception.Message}
if($primary-cne'ACTUAL_OBSERVER_EXIT_UNKNOWN'){throw "Original observer error masked: $primary"}
if(-not$ownerState.writer_unknown){throw 'Unknown Python exit became stopped'}
if($ownerState.analysis_operations.Count){throw 'Unknown Python exit fabricated completion'}
Write-Output 'UNKNOWN_WRITER_PRESERVED'
""", encoding='utf-8')
            outcome = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), str(root)],
                                     capture_output=True, text=True, encoding='utf-8', cwd=REPO, timeout=300)
            self.assertEqual(outcome.returncode, 0, outcome.stdout+outcome.stderr)
            self.assertIn('UNKNOWN_WRITER_PRESERVED', outcome.stdout)

    def test_saved_solution_admission_uses_raw_stage_without_csv_and_requires_original_mapping(self):
        for fault, valid in [('raw_saved', True), ('raw_saved_no_mapping', False)]:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, manifest = parent_fixture(root, fault=fault)
                before = manifest.read_bytes()
                script = root/'read-raw-stage.ps1'
                script.write_text(r"""
param($Repo,$Python,$Manifest)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'),[ref]$null,[ref]$null)
$function=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-ceq'Get-FiniteComsolAnalysisSource'},$true))
Invoke-Expression $function[0].Extent.Text
$source=Get-FiniteComsolAnalysisSource -ManifestPath $Manifest -Python $Python -RepoRoot $Repo -ReextractFromModel
$source.stage_evidence|ConvertTo-Json -Depth 20 -Compress
""", encoding='utf-8')
                outcome = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable, str(manifest)], capture_output=True, text=True, encoding='utf-8', cwd=REPO, timeout=300)
                if valid:
                    self.assertEqual(outcome.returncode, 0, outcome.stdout+outcome.stderr)
                    evidence = json.loads(outcome.stdout.strip().splitlines()[-1])
                    self.assertEqual(evidence['basis'], 'frozen_producer_two_cases_and_raw_save')
                else:
                    self.assertNotEqual(outcome.returncode, 0)
                    self.assertIn('SAVED_SOLUTION_REEXTRACTION_DEPENDENCY_MISSING', outcome.stdout+outcome.stderr)
                self.assertEqual(manifest.read_bytes(), before)
                self.assertFalse((parent/'results/particle_events.csv').exists())

    def test_saved_extraction_uses_real_wrapper_observation_and_explicit_context_without_native_solver(self):
        # Only commercial launcher is inert; actual owner function, Python science
        # projection, process observer, host release and writer proof are exercised.
        with tempfile.TemporaryDirectory(prefix='cold extraction spaces ') as directory:
            root = Path(directory)
            run = root/('deep-'+'a'*65)/('deep-'+'b'*65)/('deep-'+'c'*65)/'run'
            code = run/'inputs/code'
            for relative in ('projects/rf_multipole_ion_optics/core/interface_geometry.py',
                             'projects/rf_multipole_ion_optics/runtime/finite_extraction_context.py',
                             'common/host_execution_lease.ps1', 'common/host_resource_policy.json',
                             'common/host_resource_scheduler.py', 'common/require_powershell7.ps1'):
                target = code/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO/relative, target)
            (run/'inputs').mkdir(parents=True, exist_ok=True)
            (run/'results').mkdir()
            (run/'logs').mkdir()
            write(run/'run_config.json', dict(inputs={}, provenance={}))
            design = dict(role='multipole_resolved_design_do_not_edit', resolved_sha256='FROZEN',
                          particle_source=dict(charge_state=1), axial_drive=dict(topology='none'),
                          drive=dict(waveform='cosine', frequency_Hz=123, phase_rad=.7),
                          geometry_mm=dict(rod_z_min=2, rod_z_max=8, enclosure=dict(model='bare'),
                            numerical_domain=dict(working_region_radius_mm=3),
                            observations=dict(release_plane_z_mm=1, handoff_plane_z_mm=9, census_plane_z_mm=10, acceptance_radius_mm=4),
                            enclosure_layout=dict(ports={name:dict(center_mm=[0, 0, z], cross_section=dict(shape='open_rod_envelope', inscribed_radius_mm=5))
                                                         for name, z in [('mechanical_entrance', 2), ('mechanical_exit', 8)]})))
            metadata = dict(role='multipole_canonical_particle_source_metadata', parent_resolved_design_sha256='FROZEN',
                            particle_count=1, mass_amu=100, charge_state=1)
            frozen = {}
            for name, value in [('multipole_resolved_design', design), ('solver_numerics', dict(role='multipole_comsol_solver_numerics', trajectory=dict(rf_steps_per_period=80, maximum_global_time_us=8))), ('particle_source_metadata', metadata)]:
                frozen[name] = str(root/(name+'.json'))
                write(Path(frozen[name]), value)
            source = root/'source.csv'
            table(source, [dict(particle_id=17, birth_time_s=0)])
            mapping = root/'mapping.json'
            write(mapping, dict(native_scope='complete_cohort', native_order=[1], source_ids=[17], source_birth_s=[0]))
            model = root/'original.mph'
            model.write_bytes(b'INERT_NATIVE_BOUNDARY_SENTINEL_NEVER_OPEN')
            before = model.read_bytes()
            fixture = dict(frozen=frozen, source=dict(inputs=dict(particle_source=dict(path=str(source))),
                           exports=dict(model=dict(path=str(model)), mapping=dict(path=str(mapping)))))
            write(root/'fixture.json', fixture)
            launcher = code/'common/comsol/run_comsol_r2025b.ps1'
            launcher.parent.mkdir(parents=True)
            launcher.write_text(r"""
param($TaskScript,$ReportPath,$StartupAttempts,$RunId,$CompletionPath,$ResourceBudgets)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../host_execution_lease.ps1')
$request=Get-Content -LiteralPath $env:RF_FINITE_REEXTRACTION_REQUEST -Raw|ConvertFrom-Json
if($ResourceBudgets.solver.memory_bytes-ne2147483648){throw 'EXPLICIT_HOST_BUDGET_LOST'}
if($request.context.acceptance.exit_interface.cross_section.shape-cne'open_rod_envelope'){throw 'OPEN_PORT_CHANGED'}
if($request.context.geometry.census_plane_z-ne10){throw 'FROZEN_GEOMETRY_LOST'}
if(-not(Test-Path -LiteralPath $TaskScript)){throw 'FROZEN_TASK_MISSING'}
if($TaskScript.Length-gt260-or$ReportPath.Length-gt260-or$env:RF_FINITE_REEXTRACTION_REQUEST.Length-gt260){throw 'NATIVE_PATH_NOT_PROJECTED'}
foreach($path in $request.context.outputs.PSObject.Properties.Value){if($path.Length-gt260){throw 'OUTPUT_PATH_NOT_PROJECTED'}}
$lease=Enter-HostResourceStage -Role COMSOL -Stage postprocess -RunId $RunId -Budget $ResourceBudgets.postprocess
foreach($path in $request.context.outputs.PSObject.Properties.Value){Set-Content -LiteralPath $path -Value 'INERT_COMMERCIAL_BOUNDARY_OUTPUT'}
Set-Content -LiteralPath $ReportPath -Value "TASK=MULTIPOLE_FINITE_SAVED_EXTRACTION`nCHECKPOINT=PARTICLE_EXPORT_COMPLETE`nNATIVE_SOLVES=0`nPARENT_MODEL_SAVED=false`nSTATUS=PASS"
$release=Exit-HostResourceStage -Lease $lease -PassThru
@{schema_version=1;role='comsol_launcher_completion';run_id=$RunId;operations=@();host_release=@{inherited=$false;token=$lease.token;result=$release;error=$null}}|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $CompletionPath
""", encoding='utf-8')
            script = root/'exercise-cold.ps1'
            script.write_text(r"""
param($Repo,$Python,$Root)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
. (Join-Path $Repo 'common/resource_budget_support.ps1')
. (Join-Path $Repo 'common/host_execution_lease.ps1')
$env:SIMULATION_PYTHON_EXE=$Python
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $Root 'host.sqlite3'
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'),[ref]$null,[ref]$null)
$ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object{Invoke-Expression $_.Extent.Text}
$fixture=Get-Content -LiteralPath (Join-Path $Root 'fixture.json') -Raw|ConvertFrom-Json -AsHashtable
$state=@{native_attempted=$false;wrapper_observation=$null;host_lease=$null;writer_unknown=$false;phase_timings=@{};timer=[Diagnostics.Stopwatch]::StartNew()}
$run=Get-ChildItem -LiteralPath $Root -Directory -Recurse|Where-Object{$_.Name-eq'run'}|Select-Object -ExpandProperty FullName
$package=[pscustomobject]@{artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;python=$Python;path_context=@{execution_root=(Join-Path $Root 'e');artifact_root=$Root;host_resource_state_path=$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH}}
$context=@{run_directory=$run;package=$package}
$limits=[pscustomobject]@{wall_clock_seconds=60;process_tree_working_set_bytes=2147483648L;minimum_system_available_memory_bytes=1;transient_run_directory_bytes=33554432}
$result=Invoke-FiniteComsolSavedExtraction -Context $context -State $state -Source $fixture.source -Frozen $fixture.frozen -CodeRoot (Join-Path $run 'inputs/code') -Python $Python -RunId 'inert-cold-wiring' -Limits $limits
$completion=Get-FiniteComsolWriterCompletion -State $state -RunId 'inert-cold-wiring'
$alias=$package.execution_alias
Remove-RunPackageExecutionAlias -Package $package
@{completion=$completion;state=$state;result=$result;removed_alias=$alias;alias_exists=(Test-Path -LiteralPath $alias)}|ConvertTo-Json -Depth 30 -Compress
""", encoding='utf-8')
            outcome = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable, str(root)],
                                     capture_output=True, text=True, encoding='utf-8', cwd=root, timeout=300)
            self.assertEqual(outcome.returncode, 0, outcome.stdout+outcome.stderr)
            result = json.loads(outcome.stdout.strip().splitlines()[-1])
            observation = result['completion']['operations'][0]['observation']
            self.assertTrue(observation['exit_confirmed'])
            self.assertEqual(observation['returncode'], 0)
            self.assertGreater(observation['process_id'], 0)
            self.assertGreater(observation['process_started_at_utc_ticks'], 0)
            self.assertEqual(model.read_bytes(), before)
            self.assertFalse(result['alias_exists'])
            self.assertTrue(result['removed_alias'])
            self.assertFalse((run/'inputs/saved_extraction_native_request.json').exists())
            request = json.loads((run/'inputs/saved_extraction_request.json').read_text(encoding='utf-8-sig'))
            self.assertNotIn(result['removed_alias'], json.dumps(request))
            self.assertEqual(request['context']['outputs']['events'], str(run/'results/particle_events.csv'))
            self.assertEqual(request['context']['source_ids'], [17])
            self.assertEqual(request['context']['drive'], design['drive'])
            task = (run/'inputs/reextract_saved_finite_solution.m').read_text(encoding='utf-8-sig')
            self.assertIn('reextract_finite_3d_transport(request,fid)', task)
            self.assertNotIn('runAll', task)
            self.assertNotIn('model.save', task)

    def test_public_saved_extraction_requires_mapping_before_run_or_commercial_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest = parent_fixture(root, fault='raw_saved_no_mapping')
            before = manifest.read_bytes()
            outcome, result, child = self.invoke(root, manifest, reextract=True)
            self.assertNotEqual(outcome.returncode, 0)
            self.assertIn('SAVED_SOLUTION_REEXTRACTION_DEPENDENCY_MISSING', outcome.stdout+outcome.stderr)
            self.assertFalse(child.exists())
            self.assertFalse(result.exists())
            self.assertEqual(manifest.read_bytes(), before)

    def test_completed_cold_child_reanalysis_uses_csv_without_native_payload_and_rejects_incomplete_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, original_manifest = parent_fixture(root, fault='raw_saved')
            child = parent.parent/'20261031_060002__analysis__comsol__sealed-cold-fixture'
            inputs, outputs = child/'inputs', child/'results'
            inputs.mkdir(parents=True)
            outputs.mkdir()
            paths = {}
            native_config = json.loads((parent/'run_config.json').read_text(encoding='utf-8'))
            for name in ('multipole_resolved_design', 'solver_numerics', 'particle_source_metadata', 'engineering_budget'):
                target = inputs/(name+'.json')
                shutil.copyfile(native_config['inputs'][name], target)
                paths[name] = str(target)
            inventory = []
            for relative in ('runtime/run_finite_3d_transport.ps1', 'comsol/reextract_finite_3d_transport.m', 'comsol/export_finite_3d_particle_outputs.m', 'comsol/validate_finite_extraction_context.m'):
                relative = 'projects/rf_multipole_ion_optics/'+relative
                target = inputs/'code'/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO/relative, target)
                inventory.append(dict(path=relative, sha256=file_record(target)['sha256']))
            write(inputs/'code_inventory.json', dict(files=inventory))
            paths['code_inventory'] = str(inputs/'code_inventory.json')
            entry = inputs/'code/projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'
            write(inputs/'execution_request.json', dict(prepared=dict(owner_kind='powershell', entrypoint=file_record(entry))))
            paths['execution_request'] = str(inputs/'execution_request.json')
            task = inputs/'reextract_saved_finite_solution.m'
            task.write_text('receipt=reextract_finite_3d_transport(request,fid);\nassert(receipt.native_solves==0 && ~receipt.parent_model_saved);\n', encoding='utf-8')
            paths['saved_extraction_task'] = str(task)
            destinations = dict(events=str(outputs/'particle_events.csv'), primary_canonical=str(outputs/'particle_state__primary.csv'), control_canonical=str(outputs/'particle_state__control.csv'))
            write(inputs/'saved_extraction_request.json', dict(model_path=str(parent/'results/finite_3d_transport.mph'), mapping_path=str(parent/'results/release_source_mapping.json'), source_path=native_config['inputs']['particle_source'], context=dict(outputs=destinations)))
            paths['saved_extraction_request'] = str(inputs/'saved_extraction_request.json')
            for path in destinations.values():
                Path(path).write_text('SYNTHETIC_BOUND_EXPORT_STAGE_FIXTURE\n', encoding='utf-8')
            report = child/'logs/comsol_saved_extraction.txt'
            report.parent.mkdir()
            report.write_text('TASK=MULTIPOLE_FINITE_SAVED_EXTRACTION\nCHECKPOINT=PARTICLE_EXPORT_COMPLETE\nNATIVE_SOLVES=0\nPARENT_MODEL_SAVED=false\nSTATUS=PASS\n', encoding='utf-8')
            # Deliberately synthetic lifecycle fact; real observer identity is
            # separately covered by the inert-launcher behavior method above.
            write(outputs/'execution_completion.json', dict(project='rf_multipole_ion_optics', run_id=child.name, writer_completion=dict(operations=[dict(operation_id='comsol-wrapper', observation=dict(exit_confirmed=True, returncode=0, process_id=1, process_started_at_utc_ticks=1))])))
            config = child/'run_config.json'
            write(config, dict(project='rf_multipole_ion_optics', run_id=child.name, mode='finite_comsol_analysis', parameters=dict(reextract_from_model=True), inputs=paths, provenance=dict(parent_manifest_record=file_record(original_manifest))))
            manifest = child/'run_manifest.json'
            document = dict(schema_version=1, role='simulation_run_manifest', status='failed', project='rf_multipole_ion_optics', run_id=child.name, run_config=file_record(config), inputs={name:file_record(Path(path)) for name,path in paths.items()}, outputs=[file_record(path) for path in outputs.iterdir()]+[file_record(report)])
            write(manifest, document)
            original_before = original_manifest.read_bytes()
            # Already exported CSV does not depend on retaining the original MPH.
            (parent/'results/finite_3d_transport.mph').unlink()
            script = root/'admit-child.ps1'
            script.write_text(r"""
param($Repo,$Python,$Manifest)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'),[ref]$null,[ref]$null)
$function=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-ceq'Get-FiniteComsolAnalysisSource'},$true))
Invoke-Expression $function[0].Extent.Text
$source=Get-FiniteComsolAnalysisSource -ManifestPath $Manifest -Python $Python -RepoRoot $Repo
$source|ConvertTo-Json -Depth 100 -Compress
""", encoding='utf-8')
            command = ['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable, str(manifest)]
            outcome = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', cwd=REPO, timeout=300)
            self.assertEqual(outcome.returncode, 0, outcome.stdout+outcome.stderr)
            source = json.loads(outcome.stdout.strip().splitlines()[-1])
            self.assertEqual(source['stage_evidence']['basis'], 'completed_saved_extraction_child_bound_task_report_and_original_native_owner')
            self.assertEqual(source['inputs']['particle_source']['path'], native_config['inputs']['particle_source'])
            self.assertEqual(source['ancestor_references'][0]['manifest_record']['path'], str(original_manifest))
            report.write_text('TASK=MULTIPOLE_FINITE_SAVED_EXTRACTION\nSTATUS=FAIL\n', encoding='utf-8')
            document['outputs'] = [file_record(path) for path in outputs.iterdir()]+[file_record(report)]
            write(manifest, document)
            refused = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', cwd=REPO, timeout=300)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('SAVED_EXTRACTION_STAGE_EVIDENCE_MISSING', refused.stdout+refused.stderr)
            self.assertEqual(original_manifest.read_bytes(), original_before)

    def test_public_shared_analysis_plot_rejects_invalid_source_fields_and_publishes_failed_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest = parent_fixture(root, fault='bad_plot')
            before = manifest.read_bytes()
            outcome, result_path, child = self.invoke(root, manifest)
            self.assertNotEqual(outcome.returncode, 0)
            self.assertIn('COMSOL exit-state diagnostic plot failed', outcome.stdout+outcome.stderr)
            self.assertIn('finite', outcome.stdout+outcome.stderr)
            result = json.loads(result_path.read_text(encoding='utf-8-sig'))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failure_stage'], 'analysis')
            self.assertNotEqual(result['scientific_result'], 'PASS')
            summary = json.loads((child/'summary.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(summary['status'], 'failed')
            self.assertEqual(summary['failure_stage'], 'analysis')
            self.assertFalse((child/'results/exit_state_diagnostics.png').exists())
            self.assertFalse((child/'results/finite_3d_transport.mph').exists())
            self.assertEqual(manifest.read_bytes(), before)
