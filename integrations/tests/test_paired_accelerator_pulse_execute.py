"""Managed pulse owner regression; vendor boundaries use explicit inert files."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common.contracts.capacity_ledger import initialize_capacity_ledger
from integrations.tests import test_paired_accelerator_pulse_preparation as preparation_tests

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / 'integrations/workflows/paired_accelerator_pulse/execute.ps1'


class PairedPulseOwnerTests(unittest.TestCase):
    def capacity_isolated_owner(self, root):
        """Startup capacity admission is inert; lease and lifecycle operations remain real."""
        source=OWNER.read_text(encoding='utf-8')
        boundary=". (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')"
        self.assertEqual(source.count(boundary),1)
        owner=root/'inert_capacity_owner.ps1'
        owner.write_text(source.replace(boundary,boundary+"\nfunction Invoke-ArtifactCapacityGate { [pscustomobject]@{satisfied_after_apply=$true} }"),
            encoding='utf-8',newline='\n')
        return owner

    def invoke(self, arguments: list[str], *, timeout: int = 180):
        return subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', *arguments], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False)

    def test_native_authorization_fails_before_run_or_vendor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / 'request.json'
            request.write_text('{}')
            result = self.invoke(['-File', str(OWNER), '-Request', str(request), '-ArtifactRoot', str(root / 'artifacts')])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('requires SolverAuthorized', result.stderr)
            self.assertFalse((root / 'artifacts').exists())

    def test_public_dry_run_freezes_selected_source_without_native_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, _, _, _ = preparation_tests.PairedPulsePreparationTests().fixture(root)
            artifacts = root / 'artifacts'
            artifacts.mkdir()
            initialize_capacity_ledger(artifacts, objects=[])
            run_id = '20261026_060001__test__python__paired-pulse-owner'
            result = self.invoke(['-File', str(self.capacity_isolated_owner(root)), '-Request', str(request), '-DryRun',
                '-ArtifactRoot', str(artifacts), '-Python', sys.executable, '-RunId', run_id,'-RepoRoot',str(ROOT)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = artifacts / 'projects/instrument_assembly/runs' / run_id
            summary = json.loads((run / 'summary.json').read_text())
            self.assertEqual(summary['particle_count'], 100)
            self.assertFalse(summary['native_executed'])
            self.assertEqual(json.loads((run / 'run_manifest.json').read_text())['status'], 'success')
            plan = json.loads((run / 'inputs/pulse/paired_accelerator_pulse_plan.json').read_text())
            self.assertEqual(plan['selected_particle_ids'], list(range(100, 0, -1)))
            self.assertTrue(Path(plan['source_csv']['path']).is_file())
            self.assertFalse(any(run.rglob('*.mph')))
            self.assertFalse(any(run.rglob('*.pa')))
            # Metadata-only TEST_ONLY member: this is not a native field.
            publication = json.loads(Path(plan['input_records']['simion_field_publication']['path']).read_text())
            generation = Path(publication['generation_directory'])
            generation.mkdir()
            (generation / 'cache_manifest.json').write_text(json.dumps(dict(files=[
                dict(name='paired_static_on.pa', bytes=1, sha256='A' * 64)])))
            frozen = run / 'inputs/runtime_snapshot'
            worker = root / 'test_only_worker_planning'
            (worker / 'inputs').mkdir(parents=True)
            (worker / 'results').mkdir()
            environment = dict(os.environ)
            environment.pop('PYTHONPATH', None)
            extractor = root / 'inline_python_imports.ps1'
            extractor.write_text(r'''param($Owner)
$tokens=$null;$errors=$null
$ownerAst=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$strings=@($ownerAst.FindAll({param($node)
 $node-is[Management.Automation.Language.StringConstantExpressionAst]-or
 $node-is[Management.Automation.Language.ExpandableStringExpressionAst]
},$true)|ForEach-Object Value)
ConvertTo-Json -InputObject $strings -Compress -Depth 4
''', encoding='utf-8', newline='\n')
            extracted = self.invoke(['-File', str(extractor), str(OWNER)])
            self.assertEqual(extracted.returncode, 0, extracted.stdout + extracted.stderr)
            imports = set()
            for code in json.loads(extracted.stdout):
                try:
                    tree = ast.parse(code)
                except SyntaxError:
                    continue
                imports.update(ast.unparse(node) for node in ast.walk(tree)
                    if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom) and node.level == 0)
            self.assertIn('from common.simion.pa_family_cache import validate_pa_family_cache_generation', imports)
            imported = subprocess.run([sys.executable, '-B', '-s', '-c', '\n'.join(sorted(imports)) + '\n' +
                'import sys\nfrom pathlib import Path\n'
                'for name,module in list(sys.modules.items()):\n'
                ' if name.startswith(("common.","integrations.","projects.")) and getattr(module,"__file__",None):\n'
                '  assert Path(module.__file__).resolve().is_relative_to(Path.cwd().resolve()), name\n'
                'print("FROZEN_OWNER_INLINE_IMPORTS=PASS")\n'], cwd=frozen, env=environment,
                capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            self.assertIn('FROZEN_OWNER_INLINE_IMPORTS=PASS', imported.stdout)
            arguments = ['--run', str(worker), '--phase', 'pulse', '--plan', str(run / 'inputs/pulse/paired_accelerator_pulse_plan.json'),
                '--code-root', str(frozen), '--field-pa', str(generation / 'paired_static_on.pa'),
                '--seed-iob', str(frozen / 'common/simion/assets/iob_instance_seeds/1_instance_seed.iob')]
            scheduled = subprocess.run([sys.executable, '-B', '-s', '-m',
                'integrations.workflows.paired_accelerator_pulse.runtime', 'prepare-dispatch', *arguments],
                cwd=frozen, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(scheduled.returncode, 0, scheduled.stdout + scheduled.stderr)
            request_path = json.loads(scheduled.stdout)['dispatch_request_path']
            dispatch = worker / 'results/test_only_dispatch.json'
            scheduler = subprocess.run([sys.executable, '-B', '-s', '-m', 'common.simion.resource_scheduler',
                '--request', request_path, '--output', str(dispatch), '--available-memory-bytes', str(8 * 1024**3),
                '--total-physical-memory-bytes', str(16 * 1024**3), '--logical-processors', '4'],
                cwd=frozen, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(scheduler.returncode, 0, scheduler.stdout + scheduler.stderr)
            materialized = subprocess.run([sys.executable, '-B', '-s', '-m',
                'integrations.workflows.paired_accelerator_pulse.runtime', 'materialize-batches', *arguments,
                '--batch-plan', str(dispatch)], cwd=frozen, env=environment, capture_output=True,
                text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(materialized.returncode, 0, materialized.stdout + materialized.stderr)
            prepared = json.loads(materialized.stdout)
            self.assertEqual(prepared['coverage'], 'initial_formal_batch_only')
            self.assertEqual(prepared['batches'][0]['expected_particle_ids'][0], 100)
            self.assertFalse(Path(prepared['batches'][0]['iob_path']).exists())
            analysis_import = subprocess.run([sys.executable, '-B', '-s', '-c',
                'from integrations.analysis.compare_paired_accelerator_pulse import compare_paired_accelerator_pulse;from integrations.workflows.paired_accelerator_pulse.runtime import load_completed_pulse_stages,materialize_simion_continuation;print("FROZEN_ANALYSIS_AND_RECOVERY_IMPORT=PASS")'],
                cwd=frozen, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(analysis_import.returncode, 0, analysis_import.stdout + analysis_import.stderr)

    def test_actual_terminal_and_failure_blocks_preserve_raw_cpt_evidence(self):
        script = r'''param($Owner,$RepoRoot,$Python,$ArtifactRoot,$RunId,$Outcome)
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
function Invoke-ArtifactCapacityGate { [pscustomobject]@{satisfied_after_apply=$true} }
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$body=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally},$false))[0]
$start=@($body.Body.Statements|Where-Object{$_.Extent.Text-eq"`$stage='terminal_publication'"})[0]
$success=[scriptblock]::Create((@($body.Body.Statements|Where-Object{$_.Extent.StartOffset-ge$start.Extent.StartOffset}).Extent.Text-join"`n"))
$handler=[scriptblock]::Create(($body.CatchClauses[0].Body.Statements.Extent.Text-join"`n"))
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
$register=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Register-PulseInputs'},$true)
. ([scriptblock]::Create($register.Extent.Text))
$project='instrument_assembly';$software=@('TEST_ONLY inert vendor boundary');$reason='TEST_ONLY pulse lifecycle; no native model or particle simulation.'
$package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot (Join-Path $ArtifactRoot 'projects/instrument_assembly') `
 -Project $project -Mode paired_accelerator_pulse -RunId $RunId -Software $software -RetentionContractEnabled `
 -RetentionClass solver_review -RetentionReason $reason -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $ArtifactRoot `
 -AdditionalDirectories @('comsol','simion') -UseShortExecutionPath
$capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $ArtifactRoot `
 -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -Owner ('test-pulse:'+$RunId)
$terminalized=$false;$lease=$null;$guard=$null;$failure=$null;$DryRun=$false;$reusedParticleSolution=$false;$reusedBaseline=$false;$reusedReplay=$false;$reusedParticleExports=$false;$nativeExecuted=$false;$paGuards=@()
$plan=@{particle_count=2};$stage='inert_particle_export';$failureText=''
$payload=Join-Path $package.artifact_run_dir 'comsol/paired_accelerator_pulse.mph'
[IO.File]::WriteAllBytes($payload,[Text.Encoding]::UTF8.GetBytes('TEST_ONLY_INERT_CPT_MODEL_IDENTITY'))
Write-RunJson -Path (Join-Path $package.artifact_run_dir 'comsol/paired_pulse_solution.json') -Value @{
 schema_version=1;role='TEST_ONLY_inert_vendor_fact';status='solved_saved';model_path=$payload}
try{
 try{
  if($Outcome-eq'failed'){throw 'TEST_ONLY_PARTICLE_EXPORT_FAILURE'}
  . $success
 }catch{. $handler}
}catch{$failureText=$_.Exception.Message}
finally{. $finalizer}
$manifest=Get-Content (Join-Path $package.artifact_run_dir 'run_manifest.json') -Raw|ConvertFrom-Json
if($manifest.status-ne$Outcome){throw "Wrong scientific terminal: $failureText"}
if($Outcome-eq'failed'-and$failureText-ne'TEST_ONLY_PARTICLE_EXPORT_FAILURE'){throw "Scientific failure hidden: $failureText"}
if($Outcome-eq'success'-and$failureText){throw $failureText}
if(@($manifest.outputs|Where-Object{[IO.Path]::GetFileName($_.path)-eq'paired_accelerator_pulse.mph'}).Count-ne1){throw 'Raw CPT model omitted from terminal manifest'}
if(-not(Test-Path -LiteralPath $payload)){throw 'Raw CPT evidence was removed'}
if((Get-Content (Join-Path $package.artifact_run_dir 'retention_actions.json') -Raw|ConvertFrom-Json).status-ne'complete'){throw 'Terminal retention incomplete'}
'TEST_ONLY_OWNER_LIFECYCLE=PASS'
'''
        for outcome in ('success', 'failed'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                artifacts = root / 'artifacts'
                artifacts.mkdir()
                initialize_capacity_ledger(artifacts, objects=[])
                wrapper = root / 'owner_boundary.ps1'
                wrapper.write_text(script, encoding='utf-8', newline='\n')
                run_id = f'20261026_060002__test__python__pulse-{outcome}'
                result = self.invoke(['-File', str(wrapper), str(OWNER), str(ROOT), sys.executable,
                    str(artifacts), run_id, outcome])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('TEST_ONLY_OWNER_LIFECYCLE=PASS', result.stdout)

    def test_predecessor_reuses_completed_stages_and_only_runs_missing_fly(self):
        script = r'''param($Owner,$PublicRepo,$Python,$Root,$Completed)
$ErrorActionPreference='Stop'
. (Join-Path $PublicRepo 'common/contracts/run_artifact_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$ownerBody=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally},$false))[0]
$native=@($ownerBody.Body.Statements|Where-Object{$_.Extent.Text.StartsWith('if(-not$DryRun){')})[0]
$execute=[scriptblock]::Create(($native.Clauses[0].Item2.Statements.Extent.Text-join"`n"))
$RepoRoot=Join-Path $Root repo
$run=Join-Path $Root run
foreach($name in @('inputs','logs','results','comsol','simion')){$null=New-Item -ItemType Directory -Path (Join-Path $run $name) -Force}
$comsolStub=Join-Path $RepoRoot 'common/comsol/run_comsol_r2025b.ps1'
$null=New-Item -ItemType Directory -Path (Split-Path -Parent $comsolStub) -Force
[IO.File]::WriteAllText($comsolStub,('param($TaskScript,$ReportPath,$ResourceBudgets,$RunId,$Limits,$RunDir,$UsagePath);if($null-eq$Limits-or$UsagePath-ne(Join-Path $RunDir ''logs/comsol.resource_usage.json'')-or$ReportPath-ne(Join-Path $RunDir ''logs/comsol_bootstrap.txt'')){{throw ''Owner omitted canonical budget observation''}};[IO.File]::WriteAllText(''{0}'',''TEST_ONLY_NATIVE_MODEL_BOUNDARY'');$global:LASTEXITCODE=0' -f (Join-Path $Root 'native_model_called').Replace("'","''")))
$generation=Join-Path $Root 'generation';$null=New-Item -ItemType Directory $generation
$publication=Join-Path $run 'inputs/publication.json'
Write-RunJson -Path $publication -Value @{generation_directory=$generation;cache_key='TEST_ONLY_CACHE_IDENTITY'}
$null=New-Item -ItemType Directory -Path (Join-Path $Root 'original_producer')
$nativeModelPath=Join-Path $Root 'original_producer/saved-cpt.mph';[IO.File]::WriteAllText($nativeModelPath,'TEST_ONLY INERT MODEL; NEVER OPENED AS NATIVE')
$staticModelPath=Join-Path $Root 'static-field.mph';[IO.File]::WriteAllText($staticModelPath,'TEST_ONLY_STATIC_MODEL')
$priorResults=Join-Path $Root 'prior_simion.json';[IO.File]::WriteAllText($priorResults,'{"TEST_ONLY":true}')
$null=New-Item -ItemType Directory -Path (Join-Path $Root 'predecessor')
$PredecessorManifest=Join-Path $Root 'predecessor/run_manifest.json';[IO.File]::WriteAllText($PredecessorManifest,'{"TEST_ONLY":true}')
$configPath=Join-Path $run 'run_config.json';Write-RunJson -Path $configPath -Value @{inputs=@{}}
$package=@{artifact_run_dir=$run;input_dir=(Join-Path $run inputs);result_dir=(Join-Path $run results);log_dir=(Join-Path $Root 'removed_execution_alias/logs');run_config=$configPath}
$plan=@{model=@{path=$staticModelPath};input_records=@{simion_field_publication=@{path=$publication}}}
$planPath=Join-Path $run 'inputs/plan.json'
$frozen=@{execution_root=$PublicRepo};$capacity=@{lease_id='TEST_ONLY';owner='TEST_ONLY'};$lease=@{token='TEST_ONLY'}
$RunId='TEST_ONLY_OWNER_BRANCH';$SimionExe=Join-Path $Root 'never-executed.exe';[IO.File]::WriteAllText($SimionExe,'TEST_ONLY')
$ExecutionBudgetPath=Join-Path $Root 'budget.json'
Write-RunJson -Path $ExecutionBudgetPath -Value @{committed_new_bytes=10000;limits=@{wall_clock_seconds=100;transient_run_directory_bytes=10000;process_tree_working_set_bytes=10000;minimum_system_available_memory_bytes=10000;compact_final_retained_bytes=10000};host_budgets=@{simion_flight=@{};comsol=@{}}}
$script:simionCalls=0;$script:replayCalls=0;$script:modelVerifications=0;$script:collected=0
. (Join-Path $PublicRepo 'integrations/runtime/frontend_flight_support.ps1')
$oldIob=Join-Path $Root 'original.iob';[IO.File]::WriteAllText($oldIob,'TEST_ONLY_ORIGINAL_IOB_IDENTITY')
$sourceReceipt=Join-Path $Root 'original_case.json';[IO.File]::WriteAllText($sourceReceipt,'TEST_ONLY_READONLY_SOURCE_RECEIPT')
$case=[pscustomobject]@{index=1;case_id='borrowed';count=2;expected_particle_ids=@(100,99);source_row_range=@(1,2);simion_particle_id_offset=0;merge_offset=0;working_directory=$Root;environment=@{};stdout='TEST_ONLY_original.stdout';stderr='TEST_ONLY_original.stderr';fly_arguments=@('--nogui','--noprompt','fly',$oldIob);receipt_path=$sourceReceipt;control_records=@(@{path=$oldIob});iob_reopen_record=@{path=$priorResults}}
$oldWorkbench=Join-Path $Root 'prior_workbench.json';Write-RunJson -Path $oldWorkbench -Value @{batches=@($case)} -Depth 100
$oldDispatch=Join-Path $Root 'prior_dispatch.json';Write-RunJson -Path $oldDispatch -Value @{TEST_ONLY=$true}
function Invoke-PulsePython {
 param($Code,$Arguments)
 if($Code.Contains('load_completed_pulse_stages')){
  $baseline=$null;$replay=$null;$particle=$null;$exports=$null
  if($Completed-ne'cpt_only'){$baseline=@{collection=@{path=$priorResults};samples=@{path=$priorResults};logs=@();workbench=@{path=$oldWorkbench};dispatch=@{path=$oldDispatch};field=@{path=(Join-Path $generation 'paired_static_on.pa');cache_key='TEST_ONLY_CACHE_IDENTITY';generation_directory=$generation}}}
  if($Completed-in@('simion_done','all_done','analysis_only')){$replay=@{comparison=@{path=$priorResults};samples=@{path=$priorResults};logs=@()}}
  if($Completed-in@('cpt_only','all_done','analysis_only')){$particle=@{path=$nativeModelPath}}
  if($Completed-eq'analysis_only'){$exports=@{particles=@{path=$priorResults};initial=@{path=$priorResults};native_facts=@{path=$priorResults};plan=@{path=$configPath}}}
  return @{particle_model=$particle;particle_exports=$exports;simion_baseline=$baseline;simion_replay=$replay}
 }
 if($Code.Contains('materialize_simion_continuation')){return $null}
 if($Code.Contains('compare_paired_accelerator_pulse')){return @{TEST_ONLY=$true}}
 if($Code.Contains('validate_pa_family_cache_generation')){return @{files=@(@{name='paired_static_on.pa';bytes=10;sha256='TEST_ONLY'})}}
 if($Code.Contains('collect_simion_batches')){$script:collected++;return @{TEST_ONLY=$true}}
 if($Code.Contains('materialize_comsol_task')){return @{matlab='TEST_ONLY_NOT_EXECUTED.m'}}
 if($Code.Contains('verify_record')){$script:modelVerifications++;if(($Arguments[0]|ConvertFrom-Json).path-ne$(if($Completed-in@('cpt_only','all_done')){$nativeModelPath}else{$staticModelPath})){throw 'Wrong actual model selected'};return @{}}
 throw "Unexpected owner scientific call: $Code"
}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes,$ProtectedPaths,$ProtectedCacheKeys)
 if($reusedParticleSolution-and$ProtectedPaths-notcontains$nativeModelPath){throw 'Actual ancestor CPT model is not protected'}
 return @{session=$Session}
}
function Protect-ImmutablePaSource {param($Source,$ExpectedBytes,$ExpectedSha256)return @{path=$Source}}
function Enter-HostResourceStage {param($Role,$Stage,$Budget,$RunId)return @{token='TEST_ONLY'}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return $Lease}
function Exit-HostResourceStage {param($Lease)}
function Get-HostResourceBudget {param($Role,$Stage)return @{}}
function Register-PulseInputs {}
function Invoke-FrontendFlightPhase {param($RunDirectory,$ProjectRunsRoot,$RepoRoot,$Python,$RuntimeModule,$SimionExe,$Limits,$Phase,$RuntimeInputArguments,$WorkbenchReceiptPath,$IobVerification)$script:simionCalls++;return @{batches=@($case);native_process_records=@(@{TEST_ONLY=$true})}}
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications)
 if($ProcessSpecifications.Count-ne1-or$ProcessSpecifications[0].argument_list[-1]-ne$oldIob){throw 'Replay did not use the original saved IOB defaults'}
 $expectedStdout=Join-Path $run 'logs/borrowed.replay.stdout.log'
 $expectedStderr=Join-Path $run 'logs/borrowed.replay.stderr.log'
 if($case.default_replay_stdout-ne$expectedStdout-or$case.default_replay_stderr-ne$expectedStderr){throw 'Replay records retained a temporary execution alias'}
 if($ProcessSpecifications[0].stdout-ne$expectedStdout-or$ProcessSpecifications[0].stderr-ne$expectedStderr){throw 'Replay execution logs differ from canonical records'}
 $script:replayCalls++;return @{resource_budget_exceeded=$false;processes=@()}
}
function Complete-ResourceUsage {param($RunDir,$UsagePath)}
function Confirm-PulseIobVerification {}
$reusedParticleSolution=$false;$reusedBaseline=$false;$reusedReplay=$false;$reusedParticleExports=$false;$nativeExecuted=$false;$paGuards=@();$guard=$null
. $execute
if($script:modelVerifications-ne$(if($Completed-eq'analysis_only'){0}else{1})-or$reusedParticleSolution-ne($Completed-in@('cpt_only','all_done','analysis_only'))){throw 'Wrong saved/new CPT model consumption'}
$expectedBaseline=if($Completed-eq'cpt_only'){1}else{0}
$expectedReplay=if($Completed-in@('simion_done','all_done','analysis_only')){0}else{1}
if($script:simionCalls-ne$expectedBaseline-or$script:replayCalls-ne$expectedReplay){throw 'A complete Fly was repeated or missing Fly skipped'}
if($script:collected-ne($expectedBaseline+$expectedReplay)){throw 'A completed native phase was collected again'}
if((Test-Path -LiteralPath (Join-Path $Root 'native_model_called'))-eq($Completed-eq'analysis_only')){throw 'Analysis-only entered native model loader, or missing CPT did not execute'}
if($Completed-eq'analysis_only'-and$nativeExecuted){throw 'Analysis-only falsely reported native execution'}
if([IO.File]::ReadAllText($sourceReceipt)-ne'TEST_ONLY_READONLY_SOURCE_RECEIPT'-or[IO.File]::ReadAllText($oldIob)-ne'TEST_ONLY_ORIGINAL_IOB_IDENTITY'){throw 'Read-only predecessor controls changed'}
'TEST_ONLY_RECOVERY_BRANCH=PASS'
'''
        for completed in ('baseline_only', 'simion_done', 'cpt_only', 'all_done', 'analysis_only'):
            with self.subTest(completed=completed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                wrapper = root / 'source_branch.ps1'
                wrapper.write_text(script, encoding='utf-8', newline='\n')
                result = self.invoke(['-File', str(wrapper), str(OWNER), str(ROOT), sys.executable, str(root), completed])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('TEST_ONLY_RECOVERY_BRANCH=PASS', result.stdout)

    def test_iob_callback_reopens_before_fly_and_keeps_original_control_identities(self):
        script = r'''param($Owner,$RepoRoot,$Python,$Root)
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/frontend_flight_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$callback=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Confirm-PulseIobVerification'},$true)
. ([scriptblock]::Create($callback.Extent.Text))
$null=New-Item -ItemType Directory -Path (Join-Path $Root logs)
$paths=@('paired_pulse.lua','paired_pulse.fly2','build_iob.lua','build_spec.lua','paired_pulse.iob')|ForEach-Object{
 $path=Join-Path $Root $_;[IO.File]::WriteAllText($path,'TEST_ONLY_INERT_CONTROL_IDENTITY');$path}
$raw=&$Python -B -c 'import json,sys;from pathlib import Path;from common.contracts.write_run_manifest import file_record;print(json.dumps([file_record(Path(p)) for p in sys.argv[1:]]))' @($paths[0..3])
if($LASTEXITCODE-ne0){throw 'Test controls could not be recorded'}
$case=[pscustomobject]@{case_id='batch_0001';working_directory=$Root;reopen_arguments=@('TEST_ONLY_REOPEN');iob_path=$paths[4];receipt_path=(Join-Path $Root receipt.json);control_records=@($raw|ConvertFrom-Json)}
$buildLog=Join-Path $Root 'logs/pulse.batch_0001.assembly.stdout.log'
[IO.File]::WriteAllText($buildLog,'PAIRED_ACCELERATOR_PULSE_IOB_BUILD=PASS TEST_ONLY')
$script:reopenCalls=0
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 if($ArgumentList[0]-ne'TEST_ONLY_REOPEN'){throw 'Unexpected native boundary'}
 $script:reopenCalls++
 [IO.File]::WriteAllText($RedirectStandardOutput,'PAIRED_ACCELERATOR_PULSE_IOB_VERIFY=PASS TEST_ONLY')
 return @{resource_budget_exceeded=$false;exit_code=0}
}
$arguments=@{Case=$case;Phase='pulse';RunDirectory=$Root;SimionExe='TEST_ONLY_NEVER_EXECUTED';Limits=@{};Python=$Python;RepoRoot=$RepoRoot}
Confirm-PulseIobVerification @arguments -Operation after_build -BuildResult @{exit_code=0}
if($script:reopenCalls-ne1-or$case.control_records.Count-ne5){throw 'Independent reopen or original control closure missing'}
Confirm-PulseIobVerification @arguments -Operation after_first_fly -BuildResult $null
if($script:reopenCalls-ne1){throw 'After-fly controls unnecessarily launched a second native reopen'}
[IO.File]::AppendAllText($paths[0],'TEST_ONLY_TAMPER')
$rejected=$false
try{Confirm-PulseIobVerification @arguments -Operation after_first_fly -BuildResult $null}catch{$rejected=$true}
if(-not$rejected){throw 'Post-fly source mutation was silently rebound'}
'TEST_ONLY_IOB_CALLBACK=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / 'iob_callback.ps1'
            wrapper.write_text(script, encoding='utf-8', newline='\n')
            result = self.invoke(['-File', str(wrapper), str(OWNER), str(ROOT), sys.executable, str(root)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('TEST_ONLY_IOB_CALLBACK=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
