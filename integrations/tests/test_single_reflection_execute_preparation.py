"""Public preparation freezes the actual executable closure in a managed run."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from integrations.tests.test_single_reflection_preparation import fixture

REPO = Path(__file__).resolve().parents[2]
EXECUTE = REPO / 'integrations/workflows/single_reflection_flight/execute.ps1'


from integrations.tests.test_support.single_reflection_execute_fixture import SingleReflectionExecuteFixture

@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is required')
class SingleReflectionExecuteTests(SingleReflectionExecuteFixture):
    def test_saved_replay_budget_failure_reports_unknown_writer(self):
        script = r'''param($Owner)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$branch=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$replay.resource_budget_exceeded'},$true)
if($null-eq$branch){throw 'replay guard missing'}
$replay=@{resource_budget_exceeded=$true}
try{. ([scriptblock]::Create($branch.Extent.Text));throw 'missing failure'}catch{
 if(-not$_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-or$_.Exception.Data['simion_wave_writer_completion_confirmed']){throw}
}
exit 0
'''
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'replay_guard.ps1'
            wrapper.write_text(script, encoding='utf-8')
            for owner in (EXECUTE, REPO / 'integrations/workflows/paired_accelerator_pulse/execute.ps1'):
                result = subprocess.run(['pwsh', '-NoProfile', '-File', str(wrapper), str(owner)],
                    cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_frontend_owners_keep_unknown_writer_resources_and_primary_error(self):
        script = r'''param($Owner,$Kind,$FailureKind,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$needle=if($Kind-eq'execute'){'Invoke-FrontendFlightPhase'}elseif($Kind-eq'run'){'execute_frozen_workflow'}else{'terminal_publication'}
$body=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally-and$n.Body.Extent.Text.Contains($needle)},$false))[0]
if($null-eq$body){throw 'Owner lifecycle missing'}
$handler=[scriptblock]::Create(($body.CatchClauses[0].Body.Statements.Extent.Text-join"`n"))
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
$writerUnknown=$false;$terminalized=$false;$package=@{result_dir=$Root};$resultDirectory=$Root
$stageName='flight';$stage='flight';$lease=@{};$capacity=@{};$paGuards=@('guard');$failure=$null
$script:written=0;$script:released=0
function Write-RunJson {param($Path,$Value) if($Value.status-ne'unknown'){throw 'bad status'};$script:written++}
function Exit-HostResourceStage {$script:released++};function Exit-HostExecutionLease {$script:released++}
function Exit-ArtifactWorkflowCapacitySession {$script:released++};function Unprotect-ImmutablePaSource {$script:released++}
function Remove-RunPackageExecutionAlias {$script:released++};function Complete-FailedRun {throw 'unexpected terminal'}
try {
 try {try{throw 'wave failed'}catch{
   if($FailureKind-eq'first'){$_.Exception.Data['simion_first_batch_drain_error']='drain failed'}
   else{$_.Exception.Data['simion_wave_writer_completion_confirmed']=$false}
   throw
 }} catch {. $handler}
}catch{if($_.Exception.Message-ne'wave failed'){throw}}
finally{. $finalizer}
if(-not$writerUnknown-or$script:written-ne1-or$script:released-ne0){throw 'unknown writer cleanup escaped'}
exit 0
'''
        owners = (
            (EXECUTE, 'execute'),
            (EXECUTE.with_name('run.ps1'), 'run'),
            (REPO / 'integrations/workflows/paired_accelerator_pulse/execute.ps1', 'pulse'),
        )
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'writer_guard.ps1'
            wrapper.write_text(script, encoding='utf-8')
            for owner, kind in owners:
                for failure in ('first', 'wave'):
                    with self.subTest(owner=kind, failure=failure):
                        result = subprocess.run(['pwsh', '-NoProfile', '-File', str(wrapper), str(owner), kind, failure, directory],
                            cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_iob_copy_initializer_hands_off_guard_before_capacity_debit(self):
        from common.contracts.write_run_manifest import file_record
        from common.simion.test_short_pa_path_support import PA_HASH_READ_COUNTERS

        for mode in ('fresh', 'capacity_failure', 'existing_good', 'existing_bad'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, destination = root / 'source.pa', root / 'copy.pa'
                source.write_bytes(b'fixed-PA')
                if mode.startswith('existing'):
                    destination.write_bytes(b'wrong-PA' if mode == 'existing_bad' else source.read_bytes())
                prepared = root / 'prepared.json'
                prepared.write_text(json.dumps({'iob_pa_copies': [
                    {'source_record': file_record(source), 'destination': str(destination)}
                ]}), encoding='utf-8', newline='\n')
                script = r'''
. (Join-Path $env:TEST_REPO 'common/simion/short_pa_path_support.ps1')
''' + PA_HASH_READ_COUNTERS + r'''
$ast=[Management.Automation.Language.Parser]::ParseFile($env:TEST_EXECUTE,[ref]$null,[ref]$null)
$definition=$ast.Find({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Initialize-InstrumentIobPaCopies'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$Python='fixture';$RepoRoot=$env:TEST_REPO;$capacity=@{committed_new_bytes=0}
$paGuards=[Collections.Generic.List[string]]::new();$script:updates=0
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
 $script:updates++
 if($script:updates-eq2-and$env:TEST_MODE-eq'capacity_failure'){throw 'CAPACITY_DEBIT_FAILED'}
 $Session.committed_new_bytes=$RemainingCommittedNewBytes
 return @{session=$Session}
}
$caught=''
try{Initialize-InstrumentIobPaCopies (Get-Content $env:TEST_PREPARED -Raw|ConvertFrom-Json -AsHashtable)}
catch{$caught=$_.Exception.Message}
$checks=@($script:paHashReads);$guardCount=$paGuards.Count
foreach($path in $paGuards){
 if(-not$global:MassSpectrometryImmutablePaSourceGuards[$path].stream.CanRead){throw 'transferred guard lost'}
 Unprotect-ImmutablePaSource -Source $path|Out-Null
 [IO.File]::SetAttributes($path,[IO.FileAttributes]::Normal)
}
if($global:MassSpectrometryShortPaCopies.Count-or$global:MassSpectrometryShortPaSourceGuards.Count-or$global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'copy owner leaked'}
@{caught=$caught;guards=$guardCount;reads=$checks;updates=$script:updates}|ConvertTo-Json -Depth 5 -Compress
'''
                completed = subprocess.run(
                    ['pwsh', '-NoProfile', '-Command', script], cwd=REPO,
                    capture_output=True, text=True, encoding='utf-8', check=False, timeout=30,
                    env={**os.environ, 'TEST_REPO': str(REPO), 'TEST_EXECUTE': str(EXECUTE),
                         'TEST_MODE': mode, 'TEST_PREPARED': str(prepared)},
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result['guards'], 0 if mode == 'existing_bad' else 1)
                self.assertEqual(len(result['reads']), 1 if mode.startswith('existing') else 2)
                if mode == 'capacity_failure':
                    self.assertEqual(result['caught'], 'CAPACITY_DEBIT_FAILED')
                elif mode == 'existing_bad':
                    self.assertIn('SHA256 differs', result['caught'])
                else:
                    self.assertEqual(result['caught'], '')


    def test_public_prepare_registers_field_continuation_frozen_closure(self):
        from common.contracts.write_run_manifest import file_record
        from integrations.tests.test_single_reflection_preparation import (
            frontend_field_source_fixture, downstream_field_source_fixture, write_json,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, _, request = fixture(root)
            frontend_field_source_fixture(root, request_path, request, fine=False)
            downstream_field_source_fixture(root, request_path, request)
            request['providers']['frontend_field_reuse_members'] = ['carrier_off', 'rf_reference']
            parent = root / 'parent'
            parent.mkdir()
            write_json(parent / 'run_config.json', dict(schema_version=2, project='instrument_assembly',
                run_id='parent', mode='single_reflection_fly'))
            write_json(parent / 'run_manifest.json', dict(schema_version=2, role='simulation_run_manifest',
                project='instrument_assembly', run_id='parent', mode='single_reflection_fly', status='checkpoint',
                run_config=file_record(parent / 'run_config.json'), inputs={}, outputs=[]))
            transaction, stopped = root / 'transaction.json', root / 'stopped.json'
            write_json(transaction, dict(fixture='transaction source'))
            write_json(stopped, dict(schema_version=1, role='run_capacity_lifecycle_receipt', action='seal_stopped_payload',
                status='ready', run_status='checkpoint', run_directory=str(parent.resolve()),
                run_config=file_record(parent / 'run_config.json')))
            request['continuation'] = dict(predecessor_run_manifest=file_record(parent / 'run_manifest.json'),
                stopped_receipt=file_record(stopped), frontend_field_transactions=[dict(domain_id='parent',
                    member_id='pulse_delta', transaction_record=file_record(transaction))])
            write_json(request_path, request)
            script = root / 'prepare.ps1'
            script.write_text(r'''
param($Repo,$Python,$Root,$Request)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$package=New-RunPackage -Python $Python -RepoRoot $Repo -ArtifactRoot (Join-Path $Root 'packages') `
  -RunId '20261025_010000__analysis__python__field-continuation-test' -Project instrument_assembly `
  -Mode single_reflection_preparation -Software @('Python 3.11')
$ownerSession=[pscustomobject]@{status='active';committed_new_bytes=17;lease_id='prepare-only-unused'}
& (Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1') `
  -Request $Request -PrepareOnly -OutputDirectory $package.run_dir -RepoRoot $Repo -Python $Python -WorkflowCapacitySession $ownerSession
if($ownerSession.status-ne'active'-or$ownerSession.committed_new_bytes-ne17){throw 'PrepareOnly changed the owner capacity session'}
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable,
                str(root), str(request_path)], cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = next((root / 'packages/runs').iterdir())
            config = json.loads((run / 'run_config.json').read_text())
            receipt = json.loads((run / 'results/single_reflection/preparation_receipt.json').read_text())
            for name, record in receipt['input_records'].items():
                self.assertEqual(config['inputs'][name], record['path'])
                self.assertTrue(Path(record['path']).is_relative_to(run / 'inputs'))
            self.assertTrue(Path(config['inputs']['code_inventory']).is_file())
            self.assertTrue(Path(config['inputs']['dependency_contract']).is_file())
            for name, original in (('continuation_stopped_receipt', stopped),
                                   ('continuation_field_transaction_001', transaction)):
                expected = original.read_bytes()
                original.unlink()
                self.assertEqual(Path(config['inputs'][name]).read_bytes(), expected)


    def test_declared_downstream_publication_skips_native_and_evidence_republication(self):
        code = r'''param($Execute)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Execute,[ref]$null,[ref]$null)
$branch=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq"`$downstreamPlan.ContainsKey('publication')"},$true)
if(-not$branch){throw 'source publication boundary missing'}
function Invoke-ResourceBudgetedProcess {throw 'source entered native solver'}
function Write-NativeExecutionEvidence {throw 'source rewrote native execution evidence'}
function Invoke-RunToolRootContext {throw 'source republished original native fields'}
$publication=@{receipt_record=@{path='frozen_source_receipt.json';bytes=12;sha256='producer-identity'};receipt=@{status='success'}}
$downstreamPlan=@{steps=@();publication=$publication}
. ([scriptblock]::Create($branch.Extent.Text))
if(-not[object]::ReferenceEquals($published,$publication)){throw 'source publication was rebuilt'}
'DOWNSTREAM_SOURCE_PUBLIC_BRANCH=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'source.ps1'
            script.write_text(code, encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(EXECUTE)],
                cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('DOWNSTREAM_SOURCE_PUBLIC_BRANCH=PASS', result.stdout)


    def test_explicit_field_source_reserves_private_payload_and_protects_producer(self):
        code = r'''param($Execute,$Producer)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Execute,[ref]$null,[ref]$null)
$body=$ast.Find({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.Body.Extent.Text.Contains('$commitment=')},$true).Body
$statements=@();$collect=$false
foreach($statement in $body.Statements){
 if($statement.Extent.Text.StartsWith('$commitment=')){$collect=$true}
 if($collect){$statements+=$statement.Extent.Text}
 if($collect-and$statement.Extent.Text.StartsWith('if($ownsCapacity)')){break}
}
if(-not$statements.Count){throw 'capacity boundary not found'}
$admit=[scriptblock]::Create(($statements-join"`n"))
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths)
 $script:admission=@{bytes=$CommittedNewBytes;protected=@($ProtectedPaths)}
 return @{}
}
$Fly=$false;$Python='INERT';$RepoRoot='INERT';$artifacts='INERT';$OutputDirectory='INERT_NEW_RUN';$ownsCapacity=$true
$downstreamPlan=@{reserved_run_array_payload_bytes=41;frontend_resource_lower_bounds=@{cache_miss_new_disk_payload_bytes_lower_bound=73}}
foreach($reuseMode in @('none','partial','all')){
$reuse=$reuseMode-ne'none'
$floor=if($reuseMode-eq'none'){73}elseif($reuseMode-eq'partial'){37}else{0}
$downstreamPlan.frontend_resource_lower_bounds.cache_miss_new_disk_payload_bytes_lower_bound=$floor
foreach($downstreamReuse in @($false,$true)){
 $receipt=@{input_records=@{}}
 if($reuse){$receipt.input_records.frontend_fields=@{};$receipt.input_records.frontend_fields_manifest=@{source_path=Join-Path $Producer 'run_manifest.json'}}
 if($downstreamReuse){$receipt.input_records.downstream_fields_manifest=@{source_path=Join-Path (Join-Path $Producer 'downstream') 'run_manifest.json'}}
 . $admit
 if($script:admission.bytes-ne(41+$floor)){throw 'incorrect private/cold-cache reservation'}
 $expected=@($OutputDirectory);if($reuse){$expected+=$Producer}
 if($downstreamReuse){$expected+=Join-Path $Producer 'downstream'}
 if(($script:admission.protected-join'|')-ne($expected-join'|')){throw 'source producer protection differs'}
}
}
'FROZEN_FIELD_SOURCE_CAPACITY=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'capacity.ps1'
            script.write_text(code, encoding='utf-8', newline='\n')
            producer = Path(directory) / 'producer'
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(EXECUTE), str(producer)],
                cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('FROZEN_FIELD_SOURCE_CAPACITY=PASS', result.stdout)


    def test_held_off_workbench_and_fly_guard_only_required_fields(self):
        self._check_public_cases(('workbench_held_off','fly_held_off'))


    def test_local_oatof_complete_mother_uses_two_fields_and_default_replay(self):
        self._check_public_cases(('local_fly',))


    def test_public_managed_preparation_and_detached_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, empty_run, _ = fixture(root)
            (empty_run / 'inputs').rmdir()
            empty_run.rmdir()
            script = root / 'prepare.ps1'
            script.write_text(r'''
param($Repo,$Python,$Root,$Request)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$package=New-RunPackage -Python $Python -RepoRoot $Repo -ArtifactRoot (Join-Path $Root 'packages') `
  -RunId '20261023_010000__analysis__python__single-reflection-test' -Project instrument_assembly `
  -Mode single_reflection_preparation -Software @('Python 3.11')
& (Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1') `
  -Request $Request -PrepareOnly -OutputDirectory $package.run_dir -RepoRoot $Repo -Python $Python
''', encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO),
                                     sys.executable, str(root), str(request)], cwd=REPO,
                                    capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('SINGLE_REFLECTION_PREPARATION=PASS', result.stdout)
            run = next((root / 'packages/runs').iterdir())
            config = json.loads((run / 'run_config.json').read_text())
            receipt = json.loads((run / 'results/single_reflection/preparation_receipt.json').read_text())
            self.assertEqual(receipt['particle_count'], 100)
            self.assertEqual(receipt['stage'], 'geometry_preparation_only')
            self.assertNotIn('composition_plan', receipt['outputs'])
            self.assertTrue((run/'inputs/composition_plan.json').exists())
            geometry=json.loads(Path(receipt['outputs']['frontend_geometry']['path']).read_text())
            self.assertEqual(geometry['composition_plan']['scope']['kind'], 'full')
            for name, record in receipt['input_records'].items():
                self.assertEqual(config['inputs'][name], record['path'])
                expected_parent = (run/'inputs/components'/name.removeprefix('instance_design__')
                                   if name.startswith('instance_design__') else run/'inputs')
                self.assertEqual(Path(record['path']).parent, expected_parent)
            self.assertEqual((run / 'inputs/request.json').read_bytes(), request.read_bytes())
            snapshot = run / 'inputs/runtime_snapshot'
            environment = dict(os.environ, PYTHONPATH=str(snapshot), PYTHONNOUSERSITE='1')
            command = [sys.executable, '-B', '-s', '-m',
                       'integrations.workflows.single_reflection_flight.prepare', '--help']
            imported = subprocess.run(command, cwd=snapshot, env=environment,
                                      capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            preflight_help=subprocess.run([sys.executable,'-B','-s','-m',
                'integrations.workflows.single_reflection_flight.downstream_fields','--help'],
                cwd=snapshot,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(preflight_help.returncode,0,preflight_help.stderr)
            self.assertIn('--engineering-budget',preflight_help.stdout)
            (snapshot / 'projects/orthogonal_accelerator/simion/sectioned_accelerator.py').unlink()
            missing = subprocess.run(command, cwd=snapshot, env=environment,
                                     capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('sectioned_accelerator', missing.stderr)
            manifest = run / 'run_manifest.json'
            value = json.loads(manifest.read_text())
            value['status'] = 'success'
            manifest.write_text(json.dumps(value), encoding='utf-8')
            refused = subprocess.run(['pwsh', '-NoProfile', '-File', str(EXECUTE),
                '-Request', str(request), '-PrepareOnly', '-OutputDirectory', str(run),
                '-RepoRoot', str(REPO), '-Python', sys.executable], cwd=REPO,
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('cannot modify a terminal run', refused.stderr)

            failed_root = root / 'failure'
            failed_root.mkdir()
            bad_request, _, document = fixture(failed_root)
            document['source']['particle_source']['sha256'] = '0' * 64
            bad_request.write_text(json.dumps(document), encoding='utf-8')
            failed = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO),
                sys.executable, str(failed_root), str(bad_request)], cwd=REPO,
                capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertNotEqual(failed.returncode, 0)
            failed_run = next((failed_root / 'packages/runs').iterdir())
            failed_config = json.loads((failed_run / 'run_config.json').read_text())
            for name in receipt['input_records']:
                self.assertTrue(Path(failed_config['inputs'][name]).is_file(), name)
            seal_script = root / 'seal_failure.ps1'
            seal_script.write_text(r'''
param($Repo,$Python,$Run)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
Complete-FailedRun -Python $Python -RepoRoot $Repo -RunConfig (Join-Path $Run 'run_config.json') `
  -Summary (Join-Path $Run 'summary.json') -SummaryRole single_reflection_preparation_summary `
  -Reason 'Frozen source identity mismatch' -Software @('Python 3.11') -Status failed -FailureStage preparation
''', encoding='utf-8')
            sealed = subprocess.run(['pwsh', '-NoProfile', '-File', str(seal_script), str(REPO),
                sys.executable, str(failed_run)], cwd=REPO,
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(sealed.returncode, 0, sealed.stdout + sealed.stderr)
            failed_manifest = json.loads((failed_run / 'run_manifest.json').read_text())
            self.assertEqual(failed_manifest['status'], 'failed')
            self.assertTrue(set(receipt['input_records']) <= set(failed_manifest['inputs']))



    def test_execute_shards_have_unique_cases_and_fixture_has_no_tests(self):
        import ast
        import importlib
        import inspect
        from integrations.tests.test_support.single_reflection_execute_fixture import SingleReflectionExecuteFixture
        modules = (
            'test_single_reflection_execute', 'test_single_reflection_execute_flight',
            'test_single_reflection_execute_capacity', 'test_single_reflection_execute_discovery',
            'test_single_reflection_execute_preparation',
        )
        names = []
        for name in modules:
            module = importlib.import_module('integrations.tests.' + name)
            owner = module.SingleReflectionExecuteTests
            module_tree = ast.parse(inspect.getsource(module))
            methods = unittest.defaultTestLoader.getTestCaseNames(owner)
            self.assertTrue(methods, name)
            names.extend(methods)
            declared = {node.name for node in ast.walk(module_tree)
                        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}
            self.assertEqual(set(methods), declared)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(unittest.defaultTestLoader.getTestCaseNames(SingleReflectionExecuteFixture), [])
