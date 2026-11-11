"""Native owner transport uses real short processes, never a solver fixture."""
from pathlib import Path
import hashlib
import sysconfig
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO/"integrations/runtime/frontend_flight_support.ps1"
CONSUMER_ROOT = REPO


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell unavailable")
class NativePathConsumerTests(unittest.TestCase):
    def test_workbench_receipt_evidence_survives_execution_alias_cleanup(self):
        code = r"""param($Repo,$Root,$Mode)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1'),[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Write-InstrumentWorkbenchReceipt'},$true)
Invoke-Expression $node.Extent.Text
$run=Join-Path $Root 'persistent';New-Item -ItemType Directory -Path (Join-Path $run 'results/single_reflection') -Force|Out-Null
$alias=$null;$execution=$run
if($Mode-eq'alias'){
 $alias=New-RunExecutionAlias -TargetDirectory $run -ExecutionRoot (Join-Path $Root 'execution') -ExpectedExecutionRelativePaths @('results/single_reflection/workbench_execution_records.json','results/single_reflection/flight_execution_records.json')
 $execution=$alias.execution_alias
}
try{
 $RunPackage=[pscustomobject]@{run_dir=$execution;artifact_run_dir=$run}
 $workbenchReceiptPath=Join-Path $execution 'results/single_reflection/workbench_preparation.json'
 $workbenchEvidencePath=Join-Path $execution 'results/single_reflection/workbench_execution_records.json'
 $flightEvidencePath=Join-Path $execution 'results/single_reflection/flight_execution_records.json'
 [IO.File]::WriteAllText($workbenchEvidencePath,'{"kind":"native"}')
 [IO.File]::WriteAllText($flightEvidencePath,'{"kind":"flight"}')
 $workbench=@{phase='full_instrument'};$workbenchOkay=$true;$Fly=$true
 $workbenchExecution=@(@{operation='verify';exit_code=0;native_priority_occupancy_validation=@{checked_points=1;observation_only_points=0}})
 $flightExecution=@(@{phase='full_instrument';exit_code=0});$nativePhases=@('full_instrument');$phaseCollection=@('batch1')
 $defaultReplayRequested=$false;$continuationSource=$false
 if($Mode-eq'external_workbench'){$workbenchEvidencePath=Join-Path ($run+'-sibling') 'evidence.json'}
 if($Mode-eq'external_flight'){$flightEvidencePath=Join-Path ($run+'-sibling') 'evidence.json'}
 if($Mode-eq'traversal_workbench'){$workbenchEvidencePath=Join-Path $execution '../outside.json'}
 if($Mode-eq'traversal_flight'){$flightEvidencePath=Join-Path $execution '../outside.json'}
 $caught=$null
 try{Write-InstrumentWorkbenchReceipt -PhaseOkay $true}catch{$caught=$_}
 if($Mode-notin@('alias','direct')){
  if($null-eq$caught-or$caught.Exception.Message-notmatch'execution evidence is outside its owning run'){throw 'Foreign evidence reference was accepted'}
  if(Test-Path -LiteralPath $workbenchReceiptPath){throw 'Foreign receipt was published'}
 }else{
  if($caught){throw $caught}
  if($null-ne$alias){
   Remove-RunExecutionAlias -ExecutionAlias $alias.execution_alias -TargetDirectory $run
   if(Test-Path -LiteralPath $execution){throw 'Execution alias was not removed'}
  }
  $receipt=Get-Content -LiteralPath (Join-Path $run 'results/single_reflection/workbench_preparation.json') -Raw -Encoding UTF8|ConvertFrom-Json
  foreach($pair in @(@($receipt.native_validation,'native'),@($receipt.flight_validation,'flight'))){
   $path=[string]$pair[0].execution_records_path
   if(-not(Test-WorkflowPathWithin $path $run)){throw 'Receipt retained an ephemeral or external path'}
   $actual=Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json
   if($actual.kind-cne$pair[1]){throw 'Receipt no longer locates its actual evidence'}
  }
 }
 'PERSISTENT_RECEIPT_EVIDENCE=PASS'
}finally{
 if($null-ne$alias){Remove-RunExecutionAlias -ExecutionAlias $alias.execution_alias -TargetDirectory $run}
}
"""
        for mode in ("alias", "direct", "external_workbench", "external_flight",
                     "traversal_workbench", "traversal_flight"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                script = root / "receipt.ps1"
                script.write_text(code, encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO),
                                         str(root), mode], cwd=root, capture_output=True,
                                        text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PERSISTENT_RECEIPT_EVIDENCE=PASS", result.stdout)

    def test_field_and_replay_retain_actual_process_facts_before_checks(self):
        code = r"""param($Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/runtime/local_frontend_field_support.ps1'),[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-LocalFieldNative'},$true)
Invoke-Expression $node.Extent.Text
New-Item -ItemType Directory -Path (Join-Path $Root inputs),(Join-Path $Root logs) -Force|Out-Null
$Package=[pscustomobject]@{python=$Python;artifact_run_dir=$Root;run_dir=$Root;execution_alias=$null;execution_path_capacity=$null;native_path_preparation=@{calls=0;elapsed_seconds=0.0;transport_bytes=0L}}
$run=$Root;$log=Join-Path $Root logs;$logs=$log;$StageElapsed=$null;$Limits=@{};$SimionExe='INERT_NOT_A_SOLVER'
$fieldNativeContext=@{run_dir=$Root;environment=@{}}
$NativeResourceReleaseId='actual-test-grant'
$script:nativeCalls=0
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$Environment,$RedirectStandardOutput,$RedirectStandardError)
 $script:nativeCalls++
 if($mode-eq'unknown'){
  try{throw 'ORIGINAL_NATIVE_OBSERVATION_FAILURE'}catch{
   $_.Exception.Data['observed_process_exit_confirmed']=$false
   $_.Exception.Data['observed_process_returncode']=$null
   $_.Exception.Data['observed_process_id']=701
   $_.Exception.Data['observed_process_started_at_utc_ticks']=801L
   throw
  }
 }
 return @{completed=$true;exit_code=$(if($mode-eq'nonzero'){7}else{0});root_process_id=701;root_process_started_at_utc_ticks=801L;resource_budget_exceeded=$false}
}
function Get-HostResourceBudget {param($Role,$Stage);return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes);return $Lease}
function Invoke-FrontendRuntimePython {
 param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-eq'default_replay_prepare'){return @{working_directory=$Root;control_records=@();argument_list=@('--nogui','fly',(Join-Path $Root saved.iob));environment=@{};usage_path=(Join-Path $Root usage.json);stdout=(Join-Path $Root replay.log);stderr=(Join-Path $Root replay.err)}}
 if($Name-eq'default_replay_compare'){
  if($NativeOperations.Count-ne1){throw 'Native completion was not recorded before analysis'}
  throw 'ORIGINAL_COMPARISON_FAILURE'
 }
 throw 'Unexpected runtime call'
}
foreach($boundary in @('field','replay')){foreach($mode in @('nonzero','unknown','analysis_failure')){
 $NativeOperations=[Collections.Generic.List[object]]::new();$caught=$null;$before=$nativeCalls
 try{
  if($boundary-eq'field'){
   Invoke-LocalFieldNative -Arguments @('--nogui') -Directory $Root -Name field_test
   if($NativeOperations.Count-ne1){throw 'Field completion was not recorded before analysis'}
   throw 'ORIGINAL_COMPARISON_FAILURE'
  }else{
   $lease=@{};$materialized=@{default_replay_policy=@{scope='fresh_process';comparison_policy='deterministic_trajectory_parity'};gui_case=@{iob_path=(Join-Path $Root saved.iob)};batches=@()}
   $null=Invoke-FrontendDefaultReplay -Package $Package -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $Root -RepoRoot $Repo -Python $Python -SimionExe $SimionExe -Limits @{} -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId
  }
 }catch{$caught=$_}
 if($null-eq$caught-or$nativeCalls-ne($before+1)-or$NativeOperations.Count-ne1){throw 'Failure lost actual native facts or restarted the operation'}
 $fact=$NativeOperations[0]
 if($fact.resource_release_id-ne$NativeResourceReleaseId-or$fact.observation.process_id-ne701){throw 'Process or grant identity changed'}
 if($mode-eq'unknown'){
  if($fact.observation.exit_confirmed-or$null-ne$fact.observation.returncode-or$caught.Exception.Message-ne'ORIGINAL_NATIVE_OBSERVATION_FAILURE'){throw 'Unknown writer was made complete or its cause masked'}
 }elseif(-not$fact.observation.exit_confirmed-or$fact.observation.returncode-ne$(if($mode-eq'nonzero'){7}else{0})){throw 'Actual stopped process fact changed'}
 if($mode-eq'analysis_failure'-and$caught.Exception.Message-ne'ORIGINAL_COMPARISON_FAILURE'){throw 'Analysis cause was masked'}
}}
"""
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary)/"facts.ps1"
            script.write_text(code, encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO), sys.executable, temporary],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self._check_canonical_member_native_facts(Path(temporary))

    def _check_canonical_member_native_facts(self, root):
        from msplatform.backends.simion import field_worker
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.processes import ProcessExecutionError
        worker_path = Path(field_worker.__file__).resolve()
        expected_source = REPO / 'src/msplatform/backends/simion/field_worker.py'
        installed_source = Path(sysconfig.get_path('purelib')) / 'msplatform/backends/simion/field_worker.py'
        self.assertIn(worker_path, (expected_source.resolve(), installed_source.resolve()))
        self.assertEqual(hashlib.sha256(worker_path.read_bytes()).digest(),
                         hashlib.sha256(expected_source.read_bytes()).digest(),
                         'Loaded canonical field worker differs from the selected checkout source')
        context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')), tools={},
            host_state_path=root/'host.json', policy_path=root/'policy.json')
        for mode in ('nonzero', 'unknown', 'analysis_failure'):
            with self.subTest(boundary='member', mode=mode):
                logs = root / mode
                logs.mkdir()
                (logs/'member.stdout.log').write_text('', encoding='utf-8')
                observation = dict(root_process_id=701, root_process_started_at_utc_ticks=801,
                                   exit_code=None if mode == 'unknown' else 7 if mode == 'nonzero' else 0)
                receipt = dict(observation=observation,
                               host_release=dict(inherited=True, token='actual-test-grant'))
                failure = ProcessExecutionError('ORIGINAL_NATIVE_OBSERVATION_FAILURE'
                    if mode == 'unknown' else 'native nonzero', receipt)
                observations = []
                with patch.object(field_worker, 'run_observed_process',
                        side_effect=failure if mode != 'analysis_failure' else None,
                        return_value=receipt) as native, patch.object(
                        field_worker, 'inherited_host_token', return_value='actual-test-grant'):
                    caught = None
                    try:
                        field_worker._native_operation(context,
                            dict(operation_id='member', stage='prepare', arguments=['--nogui'],
                                 success_marker='', outputs=[]), executable=Path(sys.executable),
                            run_directory=root, directory=root, logs=logs, limits={},
                            observations=observations)
                        self.assertEqual(len(observations), 1)
                        raise RuntimeError('ORIGINAL_COMPARISON_FAILURE')
                    except RuntimeError as error:
                        caught = error
                self.assertEqual(native.call_count, 1)
                self.assertEqual(len(observations), 1)
                self.assertIs(observations[0]['receipt'], receipt)
                self.assertEqual(receipt['host_release']['token'], 'actual-test-grant')
                self.assertEqual(observation['root_process_id'], 701)
                self.assertEqual(observation['root_process_started_at_utc_ticks'], 801)
                if mode == 'unknown':
                    self.assertIsNone(observation['exit_code'])
                    self.assertIs(caught, failure)
                    self.assertFalse(caught.observed_process_exit_confirmed)
                    self.assertIsNone(caught.observed_process_returncode)
                    self.assertEqual(str(caught), 'ORIGINAL_NATIVE_OBSERVATION_FAILURE')
                elif mode == 'nonzero':
                    self.assertEqual(observation['exit_code'], 7)
                    self.assertIs(caught, failure)
                    self.assertTrue(caught.observed_process_exit_confirmed)
                    self.assertEqual(caught.observed_process_returncode, 7)
                else:
                    self.assertEqual(observation['exit_code'], 0)
                    self.assertEqual(str(caught), 'ORIGINAL_COMPARISON_FAILURE')

    def test_phase_completion_captures_scientific_callback_before_owner_parameter_scope(self):
        code = r"""param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Add-FrontendNativeOperation','Invoke-FrontendFlightPhase')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
function Invoke-FrontendRuntimePython {param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-like'*.dispatch-plan'){@{estimation=@{kind='inert_fixed'}}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $RunDirectory 'results/extraction.dispatch_plan.json')}
 if($Name-like'*.materialize-initial'){return $script:initial}
}
function Complete-ResourceUsage {param($RunDir,$UsagePath)}
function Invoke-SimionBatchPhase {
 param($DispatchPlanPath,$RunDir,$UsagePath,$FirstSpecification,$Replan,$PrepareRemaining,$AfterDrain,$OnProcessCompleted)
 # Deliberately use the actual owner's parameter name, which dynamically shadows the caller.
 $record=@{name='batch_1';root_process_id=701;root_process_started_at_utc_ticks=801L;completed=$true;exit_code=0}
 & $OnProcessCompleted $record
 return @{prepared=@{materialized=$script:initial};resource_budget_exceeded=$false;processes=@($record)}
}
foreach($mode in @('success','science_failure','no_science','no_operations')){
 $run=Join-Path $Root $mode;New-Item -ItemType Directory -Path (Join-Path $run results) -Force|Out-Null
 $script:initial=[pscustomobject]@{batches=@();gui_case=$null;coverage='complete_population';pending_particle_ids=@()}
 $script:scienceCalls=0;$ops=[Collections.Generic.List[object]]::new()
 $expectedOps=if($mode-eq'no_operations'){0}else{1}
 $science={param($record)
  $script:scienceCalls++
  if($ops.Count-ne$expectedOps){throw 'scientific callback preceded native fact'}
  if($mode-eq'science_failure'){throw 'original scientific checkpoint failure'}
 }
 if($mode-eq'no_science'){$science=$null}
 $arguments=@{NativeOperations=$ops;NativeResourceReleaseId='actual-lease';Package=[pscustomobject]@{};RunDirectory=$run;ProjectRunsRoot=$Root;RepoRoot=$Root;Python='unused';RuntimeModule='fixture';SimionExe='unused';Limits=@{};Phase='extraction';Prepared=@{dispatch_request_path='inert'};OnProcessCompleted=$science}
 if($mode-eq'no_operations'){$arguments.NativeOperations=$null}
 $caught=$null
 try{$null=Invoke-FrontendFlightPhase @arguments}catch{$caught=$_}
 if($mode-eq'science_failure'){
  if($null-eq$caught-or$caught.Exception.Message-ne'original scientific checkpoint failure'){throw 'scientific failure was replaced'}
 }elseif($caught){throw $caught}
 if($ops.Count-ne$expectedOps-or$script:scienceCalls-ne$(if($mode-eq'no_science'){0}else{1})){throw 'completion recursively called or dropped'}
 if($ops.Count-and($ops[0].resource_release_id-ne'actual-lease'-or$ops[0].observation.process_id-ne701)){throw 'actual native identity or lease was dropped'}
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary)/"check.ps1"
            script.write_text(code, encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(FRONTEND), temporary],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_prepared_joint_explicit_source_uses_its_original_root_lease(self):
        import json
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        from common.contracts.capacity_protection import load_capacity_protection_leases
        from common.contracts.test_cross_root_protection import CrossRootProtectionTests

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, _ = CrossRootProtectionTests().source(base/"source")
            target = base/"target"
            target.mkdir()
            initialize_capacity_ledger(target, objects=[])
            before = (source/"run_manifest.json").read_bytes()
            request = base/"request.json"
            request.write_text(json.dumps(dict(source=str(source), target=str(target))), encoding="utf-8")
            script = base/"check.ps1"
            script.write_text(r"""param($Repo,$Entry,$Python,$Request)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
foreach($name in @('Invoke-ProjectPython','Get-PreparedJointSourceReferences')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$script:preparedPackage=$null
$repoRoot=(Resolve-Path -LiteralPath $Repo).Path
$script:pythonRoot=$Repo;$python=$Python
$data=Get-Content $Request -Raw|ConvertFrom-Json -AsHashtable
function Invoke-ArtifactWorkflowCapacityAdmission {return @{satisfied=$true;fixture_admission=$true}}
$references=@(Get-PreparedJointSourceReferences -RunDirectories @($data.source))
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $data.target -RunDirectory (Join-Path $data.target 'projects/fixture/runs/new') -CommittedNewBytes 1024 -SourceReferences $references
try{
 if($session.source_protection_leases.Count-ne1){throw 'entry did not retain original source capacity owner'}
 if($session.source_protection_leases[0].artifact_root-eq$session.artifact_root){throw 'source root was relabeled target'}
 $lease=Get-Content (Join-Path $session.source_protection_leases[0].artifact_root ('common/capacity_protection_leases/'+$session.source_protection_leases[0].lease_id+'.json')) -Raw|ConvertFrom-Json
 if($lease.committed_new_bytes-ne0){throw 'borrowed data counted as new bytes'}
}finally{$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session}
""", encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO),
                str(CONSUMER_ROOT/"integrations/workflows/prepared_joint/execute.ps1"), sys.executable,
                str(request)], cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual((source/"run_manifest.json").read_bytes(), before)
            self.assertFalse(load_capacity_protection_leases(base/"source")["protected_paths"])
            self.assertFalse(load_capacity_protection_leases(target)["protected_paths"])

    def test_mr_continuation_routes_only_explicit_manifest_authorities(self):
        code = r"""param($Support,$Root,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Support,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Protect-MrtofContinuationEvidence'},$true)
Invoke-Expression $node.Extent.Text
$one=Join-Path $Root one;$two=Join-Path $Root two
New-Item -ItemType Directory -Path $one,$two|Out-Null
$files=@();$manifests=@{}
foreach($run in @($one,$two)){
 $manifest=Join-Path $run run_manifest.json;Set-Content $manifest '{}'
 $data=Join-Path $run event.csv;Set-Content $data 'inert event'
 $files+=@($manifest,$data);$manifests[$manifest]='A'*64
}
$projection=Join-Path $Root projection.json
@{run_directories=@($one,$two);files=$files;manifests=$manifests}|ConvertTo-Json -Depth 20|Set-Content $projection
$env:INERT_PROTECTION_PROJECTION=$projection
$fake=Join-Path $Root fake-python.ps1
Set-Content $fake 'Get-Content -LiteralPath $env:INERT_PROTECTION_PROJECTION -Raw;exit 0'
$script:calls=0
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths,$SourceReferences)
 if(@($ProtectedPaths).Count-ne0-or@($SourceReferences).Count-ne2){throw 'foreign paths entered the new root lease'}
 foreach($ref in $SourceReferences){
  if($ref.manifest_record.sha256-ne('A'*64)-or$ref.manifest_record.bytes-le0-or@($ref.protected_paths).Count-ne3){throw 'explicit manifest identity or payload protection dropped'}
 }
 $script:calls++;return @{session=$Session}
}
$guards=[Collections.Generic.List[IDisposable]]::new()
try{
 $null=Protect-MrtofContinuationEvidence -Parent $one -Session @{} -Python $fake -RepoRoot $Root -Guards $guards
 if($script:calls-ne1-or$guards.Count-ne4){throw 'source admission/guards not preserved'}
 $bad=Get-Content $projection -Raw|ConvertFrom-Json -AsHashtable
 $bad.files+=Join-Path $Root orphan.csv;Set-Content $bad.files[-1] 'orphan'
 $bad|ConvertTo-Json -Depth 20|Set-Content $projection
 try{$null=Protect-MrtofContinuationEvidence -Parent $one -Session @{} -Python $fake -RepoRoot $Root -Guards $guards;throw 'unowned evidence accepted'}catch{if($_.Exception.Message-ne'Continuation evidence lacks an explicit manifest authority.'){throw}}
 if($script:calls-ne1){throw 'unowned source reached admission'}
}finally{foreach($guard in $guards){$guard.Dispose()};Remove-Item Env:INERT_PROTECTION_PROJECTION}
"""
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary)/"check.ps1"
            script.write_text(code, encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script),
                str(CONSUMER_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/simion/native_corridor_runtime_support.ps1"),
                temporary, sys.executable], cwd=REPO, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


    def test_ip_and_prepared_joint_use_the_public_package_and_propagate_failure(self):
        code = r'''param($Ip,$Prepared,$Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
$run=Join-Path $Root ('canonical_'+('deep_'*40));New-Item -ItemType Directory -Path $run -Force|Out-Null
$package=[pscustomobject]@{artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;python=$Python;log_dir=(Join-Path $run 'logs');
 path_context=[pscustomobject]@{source_root=$Repo;artifact_root=(Join-Path $Root 'artifacts');execution_root=(Join-Path $Root 'x');host_resource_state_path=(Join-Path $Root 'host.sqlite3')}}
function Import-InertBoundary {param($Path,$Name)
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
 $node=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$Name},$true))
 if($node.Count-ne1){throw 'actual consumer boundary missing'}
 Set-Item -Path ('Function:script:'+$Name) -Value ([scriptblock]::Create(($node[0].Body.Extent.Text.TrimStart('{').TrimEnd('}'))))
}
try{
 Import-InertBoundary $Ip 'New-IonProcessorProcessSpecification'
 $SimionExe='NOT_STARTED';$numerics=@{trajectory_quality=8};$retainBatchTrajectories='0'
 $batch=[pscustomobject]@{index=1;count=1;particle_id_min=1;particle_id_max=1;simion_particle_id_offset=0}
 $ipSpec=New-IonProcessorProcessSpecification $batch
 if($ipSpec.working_directory-eq(Join-Path $run 'simion_batch_0001')-or$ipSpec.stdout-ne(Join-Path $package.log_dir 'flight_batch_0001.log')){throw 'IP mixed native/persistent paths'}
 if($ipSpec.environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH-ne$package.path_context.host_resource_state_path){throw 'IP host identity drifted'}
 Import-InertBoundary $Prepared 'New-PreparedJointBatch'
 $script:pythonRoot=$Repo;$batchRoot=Join-Path $run 'results/batches';$resultDir=Join-Path $run results;$logDir=$package.log_dir
 $preparationPath=Join-Path $run 'inputs/preparation.json';$simion='NOT_STARTED'
 $trial=@{launcher=(Join-Path $run 'inputs/code/launcher.lua');guard_paths=@()};$script:materializations=0
 function Invoke-ProjectPython {param($Arguments)
  $script:materializations++
  $index=[array]::IndexOf($Arguments,'--output');$output=[string]$Arguments[$index+1]
  if(-not$output.StartsWith($package.artifact_run_dir)){throw 'MR persisted alias in materializer arguments'}
  if($env:MASS_SPECTROMETRY_RUN_DIRECTORY-ne$package.artifact_run_dir-or$env:MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY-ne$package.run_dir){throw 'MR materializer missed scoped execution context'}
 }
 $jointSpec=New-PreparedJointBatch $batch
 if($script:materializations-ne1-or$jointSpec.working_directory.StartsWith($run)-or-not$jointSpec.batch_receipt.StartsWith($run)){throw 'prepared joint did not use public transport'}
 if($jointSpec.argument_list[3].StartsWith($run)){throw 'prepared joint launcher was not projected'}
 function Invoke-ProjectPython {throw 'EXPECTED_MATERIALIZATION_FAILURE'}
 $caught=$null;try{New-PreparedJointBatch $batch}catch{$caught=$_}
 if($null-eq$caught-or$caught.Exception.Message-ne'EXPECTED_MATERIALIZATION_FAILURE'){throw 'prepared materialization failure was hidden'}
 'TWO_NATIVE_CONSUMERS=PASS'
}finally{Remove-RunPackageExecutionAlias -Package $package}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/"fixture.ps1"
            path.write_text(code, encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path),
                str(CONSUMER_ROOT/"projects/dual_pressure_rectilinear_ion_processor/simion/run_functional.ps1"),
                str(CONSUMER_ROOT/"integrations/workflows/prepared_joint/execute.ps1"),
                str(REPO), sys.executable, str(root)], cwd=REPO,
                capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("TWO_NATIVE_CONSUMERS=PASS", result.stdout)


    def test_iob_process_fact_precedes_science_and_transport_keeps_canonical_case(self):
        code = r'''param($Source,$Repo,$Python,$Root,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
foreach($name in @('Add-FrontendNativeOperation','Invoke-FrontendIobBuild','New-FrontendFlightSpecification')){
 $node=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true))
 if($node.Count-ne1){throw 'public native boundary missing'}
 Invoke-Expression $node[0].Extent.Text
}
$run=Join-Path $Root ('canonical_'+('deep_'*40));$native=Join-Path $run 'simion/case'
New-Item -ItemType Directory -Path $native -Force|Out-Null
$scriptPath=Join-Path $native 'inert_builder.ps1';$iob=Join-Path $native 'case.iob'
[IO.File]::WriteAllText($scriptPath,"param(`$Output);[IO.File]::WriteAllText(`$Output,'INERT_NOT_A_WORKBENCH')")
$package=[pscustomobject]@{artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;python=$Python;
 path_context=[pscustomobject]@{source_root=$Repo;artifact_root=(Join-Path $Root 'artifacts');execution_root=(Join-Path $Root 'x');host_resource_state_path=(Join-Path $Root 'host.sqlite3')}}
$case=[pscustomobject]@{case_id='case';index=1;count=1;expected_particle_ids=@(7);simion_particle_id_offset=0;merge_offset=0;
 working_directory=$native;iob_path=$iob;program_path=(Join-Path $native 'case.lua');particle_input=(Join-Path $native 'case.fly2');
 iob_builder_arguments=@('-NoProfile','-File',$scriptPath,$iob,((Join-Path $native 'response.pa')+',0.5'));fly_arguments=@('--nogui','fly','case.iob');
 environment=@{OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET='0'};stdout=(Join-Path $run 'logs/fly.log');stderr=(Join-Path $run 'logs/fly.stderr.log')}
$before=$case|ConvertTo-Json -Depth 20 -Compress
$operations=[Collections.Generic.List[object]]::new();$script:actual=$null
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 if($WorkingDirectory.Length-gt259-or$ArgumentList[-1].Length-gt259){throw 'native execution was not shortened'}
 if($Environment.MASS_SPECTROMETRY_RUN_DIRECTORY-ne$run){throw 'canonical identity changed'}
 $start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=$FilePath;$start.WorkingDirectory=$WorkingDirectory;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
 foreach($argument in $ArgumentList){$start.ArgumentList.Add([string]$argument)}
 $process=[Diagnostics.Process]::Start($start)
 try{$id=$process.Id;$birth=$process.StartTime.ToUniversalTime().Ticks;$process.WaitForExit();$exit=$process.ExitCode}finally{$process.Dispose()}
 $script:actual=@{root_process_id=$id;root_process_started_at_utc_ticks=$birth;exit_code=$exit;resource_budget_exceeded=$false}
 if($Scenario-eq'unknown') {throw 'OBSERVER_DID_NOT_PROVIDE_EXIT_FACT'}
 return $script:actual
}
$verification={param($Operation,$Case,$BuildResult,$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot)
 if($operations.Count-ne1-or$operations[0].observation.process_id-ne$script:actual.root_process_id){throw 'science ran before process fact'}
 if($Scenario-eq'science_failure'){throw 'INERT_SCIENCE_FAILURE'}
}
$caught=$null
try{
 Invoke-FrontendIobBuild -Package $package -Case $case -Phase phase -RunDirectory $run -SimionExe (Get-Command pwsh).Source -Limits @{} -Python $Python -RepoRoot $Repo -IobVerification $verification -NativeOperations $operations -NativeResourceReleaseId 'real-owner-token'|Out-Null
}catch{$caught=$_}
if($caught){Write-Host ('OBSERVED_FIXTURE_FAILURE='+$caught.Exception.Message)}
try{
 if(($case|ConvertTo-Json -Depth 20 -Compress)-cne$before){throw 'persistent case was rewritten with alias'}
 if($Scenario-eq'unknown'){
  if($null-eq$caught-or$caught.Exception.Data['simion_wave_writer_completion_confirmed']-ne$false-or$operations.Count){throw 'missing observation became a known writer'}
 }else{
  if($operations.Count-ne1-or-not$operations[0].observation.exit_confirmed-or$operations[0].observation.returncode-ne0){throw 'actual native fact missing'}
  if($operations[0].resource_release_id-ne'real-owner-token'){throw 'owner release identity changed'}
  if(($null-ne$caught)-ne($Scenario-eq'science_failure')){throw 'scientific failure propagation changed'}
  if($caught-and$caught.Exception.Message-ne'INERT_SCIENCE_FAILURE'){throw $caught}
  $spec=New-FrontendFlightSpecification -Package $package -Case $case -SimionExe NOT_NATIVE
  if($spec.working_directory-eq$native-or$spec.stdout-ne$case.stdout){throw 'execution and persistent paths were mixed'}
 }
 'NATIVE_FACT_BEFORE_SCIENCE=PASS'
}finally{Remove-RunPackageExecutionAlias -Package $package}
'''
        for scenario in ("success", "science_failure", "unknown"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root/"fixture.ps1"
                path.write_text(code, encoding="utf-8", newline="\n")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path), str(FRONTEND),
                    str(REPO), sys.executable, str(root), scenario], cwd=REPO,
                    capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("NATIVE_FACT_BEFORE_SCIENCE=PASS", result.stdout)


    def test_local_topology_project_environment_paths_before_actual_writer(self):
        code=r"""param($Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
$source=Join-Path $Repo 'integrations/workflows/local_frontend/execute.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$topology.InvokeVerifier'},$true)
Invoke-Expression ('$callback='+$node.Right.Extent.Text)
$callbacks=@($callback)
$Limits=@{};$SimionExe='INERT';$NativeResourceReleaseId='owner'
$run=Join-Path $Root ('persistent_'+('depth_'*40));New-Item -ItemType Directory -Path (Join-Path $run logs),(Join-Path $run inputs) -Force|Out-Null
$package=[pscustomobject]@{artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;python=$Python;log_dir=(Join-Path $run logs);path_context=[pscustomobject]@{execution_root=(Join-Path $Root short);artifact_root=$Root;host_resource_state_path=(Join-Path $Root host.sqlite3)}}
$script:run=$run;$budget=@{limits=@{}};$simion='INERT';$lease=@{token='owner'};$nativeOperations=[Collections.Generic.List[object]]::new()
$env:SIMION_APERTURE_PA_PATH=Join-Path $run 'inputs/field.pa'
$env:SIMION_APERTURE_REPORT_PATH=Join-Path $run 'results/report.json'
$verifier=Join-Path $run 'inputs/verifier.lua';$script:calls=0
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$WorkingDirectory,$ArgumentList,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 $script:calls++
 foreach($path in @($WorkingDirectory,$ArgumentList[-1],$Environment.SIMION_APERTURE_PA_PATH,$Environment.SIMION_APERTURE_REPORT_PATH)){
  if($path.StartsWith($run)-or-not$path.StartsWith($package.run_dir)){throw 'topology native locator not projected'}
 }
 if($RunDir-ne$run-or$Environment.MASS_SPECTROMETRY_RUN_DIRECTORY-ne$run-or$Environment.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY-ne$package.run_dir){throw 'identity/execution roots mixed'}
 return @{completed=$true;exit_code=0;root_process_id=(701+$calls);root_process_started_at_utc_ticks=(801L+$calls);resource_budget_exceeded=$false}
}
try{
 foreach($callback in $callbacks){$result=&$callback $verifier}
 if($calls-ne1-or$nativeOperations.Count-ne1-or$result.exit_code-ne0){throw 'topology writer/fact wiring failed'}
 if($env:SIMION_APERTURE_PA_PATH-ne(Join-Path $run 'inputs/field.pa')){throw 'persistent caller environment rewritten'}
 function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool);throw 'PREPARATION_FAILED_BEFORE_WRITER'}
 try{&$callback $verifier;throw 'missing preparation failure'}catch{if($_.Exception.Message-ne'PREPARATION_FAILED_BEFORE_WRITER'){throw}}
 if($calls-ne1-or$nativeOperations.Count-ne1){throw 'preparation failure created native operation'}
 'LOCAL_TOPOLOGY_PATH_CONTEXT=PASS'
}finally{Remove-RunPackageExecutionAlias -Package $package}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            script=root/'topology.ps1'
            script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(script),str(REPO),sys.executable,str(root)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('LOCAL_TOPOLOGY_PATH_CONTEXT=PASS',result.stdout)


if __name__ == "__main__":
    unittest.main()
