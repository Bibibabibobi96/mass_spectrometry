"""Production diagnostic wiring with inert native/lifecycle adapters, not physics evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.write_run_manifest import file_record
from common.contracts.artifact_retention import classify_file, load_policy
from projects.single_reflection_oa_tof_mass_analyzer.analysis.stage_formal_simion_runtime import (
    PROJECT_ID, stage_diagnostic_inputs,
)

ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT/'projects'/PROJECT_ID
CASES = [d+'__'+m for d in ('all','z_only','xy_only','energy_only') for m in
         ('actual','ideal_accel','ideal_stage1','ideal_stage2','ideal_reflectron','ideal_all')]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def source_fixture(root: Path) -> Path:
    source = root/'20261030_120000__test__simion__ideal-field-matrix__n2'
    retention = dict(policy_version=load_policy()['schema_version'], **{'class':'solver_review'}, reason='inert terminal-source fixture')
    config = dict(schema_version=2, artifact_retention=retention, run_id=source.name, project=PROJECT_ID,
                  mode='simion_ideal_field_matrix', particles=2, seed=17)
    write(source/'run_config.json', json.dumps(config))
    outputs = []
    for case in CASES:
        path = source/'logs'/(case+'.log')
        write(path, 'inert diagnostic fixture log\n')
        outputs.append(dict(file_record(path), retention_role=classify_file(path, bytes_count=path.stat().st_size)))
    for distribution in ('all','z_only','xy_only','energy_only'):
        path = source/'simion'/f'ions_{distribution}_N2.ion'
        write(path, '0,524,1,0,0,0,0,0,5,1,0\n'*2)
        outputs.append(dict(file_record(path), retention_role=classify_file(path, bytes_count=path.stat().st_size)))
    # This deliberately unavailable, unconsumed asset must never be scanned.
    write(source/'run_manifest.json', json.dumps(dict(schema_version=2, artifact_retention=retention, status='success',
        run_id=source.name, project=PROJECT_ID, mode=config['mode'],
        run_config=file_record(source/'run_config.json'), inputs=dict(unrelated_formal_pa=
        dict(path=str(root/'unavailable_formal.pa0'), bytes=1000000000, sha256='A'*64)), outputs=outputs)))
    return source


class DiagnosticInputTests(unittest.TestCase):
    def test_freezes_only_actual_records_with_source_controls_and_no_formal_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_fixture(root)
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            result = stage_diagnostic_inputs(source, root/'inputs/source', root/'inputs/receipt.json', CASES)
            self.assertEqual(result['particle_count'], 2)
            self.assertEqual(result['seed'], 17)
            self.assertEqual(len(result['inputs']), 30)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            self.assertFalse(list((root/'inputs').rglob('*.pa*')))

    def test_missing_or_changed_consumed_record_rejects_without_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_fixture(root)
            for change in ('missing','changed'):
                path = source/'logs'/f'{CASES[0]}.log'
                if change == 'missing':
                    path.unlink()
                else:
                    write(path, 'changed')
                with self.subTest(change=change), self.assertRaises(subprocess.CalledProcessError):
                    stage_diagnostic_inputs(source, root/'inputs/source', root/'inputs/receipt.json', CASES)
                self.assertFalse((root/'inputs/source').exists())

    def test_invalid_source_controls_and_authority_fail_before_copy(self):
        for scenario in ('running', 'mode', 'project', 'seed', 'foreign_config'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = source_fixture(root)
                manifest_path = source/'run_manifest.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                config_path = source/'run_config.json'
                config = json.loads(config_path.read_text(encoding='utf-8'))
                if scenario == 'running':
                    manifest['status'] = 'running'
                elif scenario == 'mode':
                    config['mode'] = 'other_workflow'
                elif scenario == 'seed':
                    config.pop('seed')
                elif scenario == 'project':
                    manifest['project'] = 'other_project'
                else:
                    config_path = root/'foreign_run_config.json'
                write(config_path, json.dumps(config))
                manifest['run_config'] = file_record(config_path)
                write(manifest_path, json.dumps(manifest))
                before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
                destination = root/'new-inputs/source'
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    stage_diagnostic_inputs(source, destination, root/'new-inputs/receipt.json', CASES)
                self.assertFalse(destination.exists())
                self.assertEqual(before, {p: p.read_bytes() for p in before})


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell required')
class DiagnosticRunnerTests(unittest.TestCase):
    def fixture(self, root: Path):
        repo = root/'repo'
        project = repo/'projects'/PROJECT_ID
        script = project/'simion/workbench/run_ideal_field_diagnostic.ps1'
        body = (PROJECT/'simion/workbench/run_ideal_field_diagnostic.ps1').read_text(encoding='utf-8')
        write(script, body)
        for name in ('workspace_paths.ps1', 'workspace_paths.py'):
            write(repo/'common/paths'/name, (ROOT/'common/paths'/name).read_text(encoding='utf-8'))
        write(repo/'common/host_execution_lease.ps1', r'''
function Enter-HostExecutionLease {param($Role,$Stage,$StatePath) if($StatePath-cne$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH){throw 'Host state differs'};Add-Content $env:DIAGNOSTIC_TRACE "lease:$Role";return @{role=$Role}}
function Exit-HostExecutionLease {param($Lease)}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) return $Lease}
function Get-HostResourceBudget {param($Role,$Stage) return @{}}
''')
        write(repo/'common/contracts/run_artifact_support.ps1', r'''
. (Join-Path $PSScriptRoot '../host_execution_lease.ps1')
$publicAst=[Management.Automation.Language.Parser]::ParseFile($env:DIAGNOSTIC_PUBLIC_SUPPORT,[ref]$null,[ref]$null)
foreach($name in @('Save-RunEnvironment','Restore-RunEnvironment','Write-RunJson')){
 $node=$publicAst.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
function New-RunPackage {param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,$RetentionClass,$RetentionReason,$AdditionalDirectories,$PathContext,[switch]$RetentionContractEnabled,[switch]$CapacityLedgerLifecycleEnabled)
 if($null-eq$PathContext-or$ArtifactRoot-cne(Join-Path $PathContext.artifact_root ('projects/'+$Project))){throw 'Package roots differ'}
 $run=Join-Path $ArtifactRoot "runs/$RunId";foreach($name in @('inputs','results','logs','simion')){New-Item -ItemType Directory (Join-Path $run $name) -Force|Out-Null}
 $config=Join-Path $run 'run_config.json';Write-RunJson -Path $config -Value @{schema_version=2;run_id=$RunId;project=$Project;mode=$Mode;paths=$PathContext;package_sentinel='keep';artifact_retention=@{};capacity_ledger_lifecycle=@{artifact_root=$PathContext.artifact_root}}
 return @{artifact_run_dir=$run;input_dir=(Join-Path $run 'inputs');result_dir=(Join-Path $run 'results');log_dir=(Join-Path $run 'logs');run_config=$config}
}
function New-RunExecutionAlias {param($TargetDirectory,$AdditionalDirectories,$ExpectedExecutionRelativePaths,$ExecutionRoot) if($ExecutionRoot-cne$env:MASS_SPECTROMETRY_EXECUTION_ROOT){throw 'Execution root differs'};return @{execution_alias=$TargetDirectory}}
function Remove-RunExecutionAlias {param($ExecutionAlias,$TargetDirectory)}
function Write-TerminalRunRecord {param($RunDir,$Status,$Reason,$RepoRoot,$Python,$SummaryRole) Add-Content $env:DIAGNOSTIC_TRACE "failed:$Reason"}
function Enter-RunTerminalConsumptionGuard {param($RunDirectory) Add-Content $env:DIAGNOSTIC_TRACE 'source_guard';$guard=[pscustomobject]@{};$guard|Add-Member ScriptMethod Dispose {};return $guard}
function Start-Process {param($FilePath,$ArgumentList,$WorkingDirectory,$RedirectStandardOutput,$RedirectStandardError,[switch]$NoNewWindow,[switch]$Wait,[switch]$PassThru) Add-Content $env:DIAGNOSTIC_TRACE 'native_fly';'inert'|Set-Content $RedirectStandardOutput;''|Set-Content $RedirectStandardError;return @{ExitCode=0}}
''')
        lifecycle = (PROJECT/'oatof_lifecycle_preflight.ps1').read_text(encoding='utf-8')
        readable_guard = lifecycle[:lifecycle.index('function New-OaTofFormalSimionRuntime')]
        write(project/'config/project.json', json.dumps({'lifecycle_status': 'formal'}))
        write(project/'oatof_lifecycle_preflight.ps1', readable_guard + r'''
function New-OaTofFormalSimionRuntime {param($ProjectRoot,$ArtifactRoot,$PythonExe,$Destination,$Receipt)
 Add-Content $env:DIAGNOSTIC_TRACE 'prepare_runtime';New-Item -ItemType Directory $Destination -Force|Out-Null;'inert'|Set-Content (Join-Path $Destination 'oatof_ideal_grounded.iob');'{}'|Set-Content $Receipt;return $Destination
}
function Remove-OaTofFormalSimionRuntime {param($ArtifactRoot,$RuntimeRoot) Add-Content $env:DIAGNOSTIC_TRACE 'remove_runtime'}
''')
        write(project/'workflows/formal_reference/verify_geometry_contract.ps1', r'''
param($PreparedRuntime,$SimionExe,$RuntimeReportPath)
if(-not$PreparedRuntime-or-not(Test-Path (Join-Path $PreparedRuntime 'oatof_ideal_grounded.iob'))){throw 'validation used another runtime'}
Add-Content $env:DIAGNOSTIC_TRACE 'validate_actual_runtime';'STATUS=PASS'|Set-Content $RuntimeReportPath
''')
        write(project/'simion/workbench/generate_comsol_consistent_ions.ps1', r'''
param($N,$Seed,$HalfWidthXmm,$HalfWidthYmm,$HalfWidthZmm,$EnergyStdEv,$Output,[switch]$AllowNonstandardDiagnosticCount)
Add-Content $env:DIAGNOSTIC_TRACE 'generate_ion';'inert'|Set-Content $Output
''')
        write(project/'simion/workbench/analyze_ideal_field_log.ps1', r'''
param($Log,$IonFile,$Mode,$Distribution,$ParticleCsv)
if(-not(Test-Path $Log)-or-not(Test-Path $IonFile)){throw 'actual consumed records missing'}
'inert'|Set-Content $ParticleCsv
return [pscustomobject]@{Distribution=$Distribution;Mode=$Mode;Hit=0;EfficiencyPct=0;MeanTofUs=$null;StdTofNs=$null;GaussianProxyFwhmTofNs=$null;GaussianProxyTimeEquivalentResolution=$null;MaxCrossingRadiusMm=$null}
''')
        for name in ('artifact_naming.py','write_run_manifest.py','verify_run_manifest.py'):
            write(repo/'common/contracts'/name, '# inert outer lifecycle adapter\n')
        return script, repo

    def environment(self, root: Path, trace: Path):
        return dict(os.environ, PYTHONPATH=str(ROOT), DIAGNOSTIC_TRACE=str(trace),
                    SIMULATION_PYTHON_EXE=sys.executable,
                    DIAGNOSTIC_PUBLIC_SUPPORT=str(ROOT/'common/contracts/run_artifact_support.ps1'),
                    MASS_SPECTROMETRY_ARTIFACT_ROOT=str(root/'artifacts'),
                    MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'configured-execution'),
                    MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'configured-host.sqlite3'))

    def test_analyze_only_never_admits_simion_prepares_runtime_or_generates_particles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, repo = self.fixture(root)
            source = source_fixture(root)
            write(repo/'projects'/PROJECT_ID/'config/project.json', json.dumps({'lifecycle_status': 'formal_revalidation_pending'}))
            trace = root/'trace.txt'
            env = self.environment(root, trace)
            run_id = '20261030_120100__analysis__python__diagnostic-fixture'
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script),'-AnalyzeOnly',
                '-SourceRunPath',str(source),'-RunId',run_id,'-SimionExe',str(root/'missing_simion.exe')],
                cwd=ROOT, timeout=120, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(trace.read_text(encoding="utf-8-sig").splitlines(), ['lease:GATE','source_guard'])
            run = root/'artifacts/projects'/PROJECT_ID/'runs'/run_id
            config = json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'))
            self.assertEqual((config['particles'], config['seed']), (2, 17))
            self.assertTrue(config['analysis_only'])
            self.assertEqual(config['package_sentinel'], 'keep')
            self.assertEqual(config['paths']['artifact_root'], str(root/'artifacts'))
            self.assertEqual(config['paths']['host_resource_state_path'], str(root/'configured-host.sqlite3'))
            self.assertEqual(json.loads((run/'summary.json').read_text(encoding='utf-8-sig'))['cases'], 24)
            self.assertFalse((root/'artifacts/projects'/PROJECT_ID/'formal').exists())
            self.assertFalse(list(run.rglob('*.pa*')))

    def test_analyze_only_missing_bound_record_reports_stable_reason_and_no_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, repo = self.fixture(root)
            source = source_fixture(root)
            (source/'logs'/f'{CASES[0]}.log').unlink()
            trace = root/'trace.txt'
            run_id = '20261030_120400__analysis__python__diagnostic-missing'
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script),'-AnalyzeOnly',
                '-SourceRunPath',str(source),'-RunId',run_id], cwd=ROOT, timeout=60,
                env=self.environment(root, trace),
                capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            events = trace.read_text(encoding='utf-8-sig').splitlines()
            self.assertTrue(any('ACTION=provide_complete_manifest_bound' in event for event in events))
            self.assertNotIn('lease:SIMION', events)
            self.assertNotIn('native_fly', events)
            self.assertNotIn('prepare_runtime', events)
            error_log = root/'artifacts/projects'/PROJECT_ID/'runs'/run_id/'logs/analysis_source_validation.stderr.log'
            details = error_log.read_text(encoding='utf-8-sig')
            self.assertIn('ACTION=provide_complete_manifest_bound', details)
            self.assertIn(CASES[0]+'.log', details)

    def test_normal_run_prepares_and_validates_only_actual_runtime_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, repo = self.fixture(root)
            trace = root/'trace.txt'
            env = self.environment(root, trace)
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script),'-N','2',
                '-RunId','20261030_120200__test__simion__diagnostic-fixture'],
                cwd=ROOT, timeout=120, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            events = trace.read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(events.count('prepare_runtime'), 1)
            self.assertEqual(events.count('validate_actual_runtime'), 1)
            self.assertEqual(events.count('generate_ion'), 4)
            self.assertEqual(events.count('native_fly'), 24)

    def test_nondefault_workspace_context_survives_publication_and_caller_environment_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, repo = self.fixture(root)
            source = source_fixture(root)
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            trace = root/'trace.txt'
            environment = self.environment(root, trace)
            environment['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(root/'unused/../separate-data')
            environment['MASS_SPECTROMETRY_EXECUTION_ROOT'] = str(root/'unused/../short-execution')
            wrapper = root/'invoke.ps1'
            write(wrapper, r'''param($Entry,$Source,$RunId)
$ErrorActionPreference='Stop'
$names=@('SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
$before=@{};foreach($name in $names){$before[$name]=[Environment]::GetEnvironmentVariable($name)}
& $Entry -AnalyzeOnly -SourceRunPath $Source -RunId $RunId
foreach($name in $names){if([Environment]::GetEnvironmentVariable($name)-cne$before[$name]){throw 'Caller environment was not restored'}}
''')
            run_id = '20261030_120500__analysis__python__diagnostic-context'
            result = subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),str(script),str(source),run_id],
                cwd=root, timeout=60, env=environment, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            run = root/'separate-data/projects'/PROJECT_ID/'runs'/run_id
            config = json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(config['package_sentinel'], 'keep')
            self.assertEqual(config['paths']['artifact_root'], str(root/'separate-data'))
            self.assertEqual(config['paths']['execution_root'], str(root/'short-execution'))
            self.assertEqual(config['paths']['source_root'], str(repo))
            self.assertEqual(config['capacity_ledger_lifecycle']['artifact_root'], config['paths']['artifact_root'])
            self.assertFalse((root/'artifacts').exists())
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_normal_pending_formal_assets_reject_before_runtime_or_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, repo = self.fixture(root)
            write(repo/'projects'/PROJECT_ID/'config/project.json', json.dumps({'lifecycle_status': 'formal_revalidation_pending'}))
            trace = root/'trace.txt'
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script),'-N','2',
                '-RunId','20261030_120300__test__simion__diagnostic-pending'],
                cwd=ROOT, timeout=60, env=self.environment(root, trace),
                capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            events = trace.read_text(encoding='utf-8-sig').splitlines()
            self.assertTrue(any('FORMAL_REVALIDATION_REQUIRED' in event for event in events))
            for action in ('prepare_runtime', 'validate_actual_runtime', 'generate_ion', 'native_fly'):
                self.assertNotIn(action, events)

    def test_prepared_geometry_branch_uses_frozen_runtime_and_default_retains_formal_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root/'repo/projects'/PROJECT_ID
            verifier = project/'workflows/formal_reference/verify_geometry_contract.ps1'
            write(verifier, (PROJECT/'workflows/formal_reference/verify_geometry_contract.ps1').read_text(encoding='utf-8'))
            write(project/'oatof_lifecycle_preflight.ps1',
                  "function Assert-OaTofFormalAssetsReadable {param($ProjectRoot) throw 'FORMAL_QUALIFICATION_REQUIRED'}\n")
            write(project/'simion/workbench/verify_iob_runtime_contract.ps1', r'''
param($IobPath,$ExpectedTrajectoryQuality,$ExpectedInstances,$SimionExe)
if(-not(Test-Path $IobPath)-or$ExpectedTrajectoryQuality-ne8-or$ExpectedInstances-ne4){throw 'wrong actual runtime'}
Add-Content $env:DIAGNOSTIC_TRACE 'verify_saved_iob';$global:LASTEXITCODE=0
''')
            native = root/'inert_native.ps1'
            write(native, r'''
if(-not(Test-Path $args[4])-or-not(Test-Path $args[5])){throw 'runtime IOB/resolved missing'}
Add-Content $env:DIAGNOSTIC_TRACE 'verify_actual_fields'
if($env:DIAGNOSTIC_FAIL_NATIVE){'STATUS=FAIL'|Set-Content $args[3]}else{'STATUS=PASS'|Set-Content $args[3]}
$global:LASTEXITCODE=0
''')
            runtime = root/'actual_runtime'
            write(runtime/'oatof_ideal_grounded.iob', 'inert IOB')
            write(runtime/'oatof_resolved.lua', 'inert frozen contract')
            trace = root/'trace.txt'
            env = dict(os.environ, DIAGNOSTIC_TRACE=str(trace))
            command = ['pwsh','-NoProfile','-File',str(verifier),'-PreparedRuntime',str(runtime),
                       '-SimionExe',str(native),'-RuntimeReportPath',str(root/'report.txt')]
            result = subprocess.run(command, cwd=ROOT, timeout=120, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(trace.read_text(encoding="utf-8-sig").splitlines(), ['verify_saved_iob','verify_actual_fields'])
            self.assertIn('PREPARED_RUNTIME_GEOMETRY=PASS', result.stdout)
            result = subprocess.run(command, cwd=ROOT, timeout=120, env=dict(env, DIAGNOSTIC_FAIL_NATIVE='1'), capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('runtime geometry validation failed', result.stderr)
            result = subprocess.run(['pwsh','-NoProfile','-File',str(verifier)], cwd=ROOT, timeout=120, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FORMAL_QUALIFICATION_REQUIRED', result.stderr)


if __name__ == '__main__':
    unittest.main()
