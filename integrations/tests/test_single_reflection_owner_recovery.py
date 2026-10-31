"""Thin single-reflection binding to the public owner and original resume CLI."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import test_run_artifact_workflow as owner_fixture

ROOT = Path(__file__).resolve().parents[2]
EXECUTE_SOURCE = ROOT/'integrations/workflows/single_reflection_flight/run.ps1'
PWSH = shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell 7 required')
class SingleReflectionOwnerRecoveryTests(unittest.TestCase):
    def test_failed_source_pin_rollback_keeps_session_for_bootstrap_cleanup(self):
        code=r"""param($Source,$Run)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$body=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$null-ne$_.Finally})[-1]
$handler=[scriptblock]::Create(($body.CatchClauses[0].Body.Statements.Extent.Text-join"`n"))
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
[IO.Directory]::CreateDirectory((Join-Path $Run logs))|Out-Null
$package=@{log_dir=(Join-Path $Run logs)};$capacity=$null;$ownerContext=$null
$nativeOperations=[Collections.Generic.List[object]]::new()
$Python='unused';$RepoRoot='unused';$pathEnvironmentNames=@();$savedPathEnvironment=@{}
$script:released=0;$script:aliases=0;$script:restored=0
function Write-RunJson {param($Path,$Value,$Depth) if($script:failSave){throw 'SESSION_EVIDENCE_WRITE_FAILURE'};$Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session) if($Session.lease_id-ne'RETAINED_SOURCE_LEASE'){throw 'lost source session'};$script:released++}
function Remove-RunPackageExecutionAlias {param($Package) $script:aliases++}
function Restore-RunEnvironment {param($Names,$Snapshot) $script:restored++}
$script:failSave=$false
try{throw 'ORIGINAL_SOURCE_PIN_FAILURE'}catch{
 $_.Exception.Data['capacity_session']=@{lease_id='RETAINED_SOURCE_LEASE'}
 . $handler
}
. $finalizer
if($failure.Exception.Message-ne'ORIGINAL_SOURCE_PIN_FAILURE'-or$released-ne1-or$aliases-ne1-or$restored-ne1){throw 'bootstrap lost primary failure or cleanup'}
$saved=Get-Content (Join-Path $Run logs/capacity_session.json) -Raw|ConvertFrom-Json
if($saved.lease_id-ne'RETAINED_SOURCE_LEASE'){throw 'source session evidence missing'}
$capacity=$null;$script:failSave=$true
try{throw 'ORIGINAL_SOURCE_PIN_FAILURE'}catch{
 $_.Exception.Data['capacity_session']=@{lease_id='RETAINED_SOURCE_LEASE'}
 . $handler
}
. $finalizer
if($failure.Exception.Message-ne'ORIGINAL_SOURCE_PIN_FAILURE'-or$released-ne2-or-not$failure.Exception.Data.Contains('capacity_session_persistence_error')){throw 'evidence write failure hid primary or prevented cleanup'}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'bootstrap.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE),str(root/'run')],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_reopen_records_actual_process_before_native_or_scientific_failure(self):
        code=r"""param($Source,$Repo,$Run,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Confirm-InstrumentIobVerification'},$true)
Invoke-Expression $node.Extent.Text
New-Item -ItemType Directory -Path (Join-Path $Run logs) -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $Run 'logs/full_instrument.batch1.assembly.stdout.log'),'SINGLE_REFLECTION_IOB=PASS')
$RunPackage=[pscustomobject]@{artifact_run_dir=$Run;run_dir=$Run;execution_alias=$null;execution_path_capacity=$null;python=$Python};$lease=@{token='TEST_ONLY_ACTUAL_PARENT'}
function Write-RunJson {param($Path,$Value,$Depth)}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 if(($ArgumentList-join'|')-ne'INERT_REOPEN_ONLY'){throw 'Reopen physical controls were replaced'}
 if($mode-eq'unknown'){
  try{throw 'ORIGINAL_OBSERVATION_FAILURE'}catch{
   $_.Exception.Data['observed_process_exit_confirmed']=$false
   $_.Exception.Data['observed_process_returncode']=$null
   $_.Exception.Data['observed_process_id']=701
   $_.Exception.Data['observed_process_started_at_utc_ticks']=801L
   throw
  }
 }
 [IO.File]::WriteAllText($RedirectStandardOutput,'NOT_A_VALID_REOPEN_MARKER')
 return @{completed=$true;exit_code=$(if($mode-eq'nonzero'){7}else{0});root_process_id=701;root_process_started_at_utc_ticks=801L;resource_budget_exceeded=$false}
}
foreach($mode in @('marker','nonzero','unknown')){
 $NativeOperations=[Collections.Generic.List[object]]::new();$caught=$null
 $case=[pscustomobject]@{case_id='batch1';iob_builder_arguments=@('INERT_BUILD');iob_verify_arguments=@('INERT_REOPEN_ONLY');working_directory=$Run;iob_path=(Join-Path $Run saved.iob);receipt_path=(Join-Path $Run case.json)}
 try{Confirm-InstrumentIobVerification -Operation after_build -Case $case -BuildResult @{exit_code=0} -Phase full_instrument -RunDirectory $Run -SimionExe 'INERT_NOT_A_SOLVER' -Limits @{} -Python $Python -RepoRoot $Repo}catch{$caught=$_}
 if($null-eq$caught-or$NativeOperations.Count-ne1){throw "Reopen failure dropped its actual writer fact: $caught"}
 $fact=$NativeOperations[0]
 if($fact.resource_release_id-ne$lease.token-or$fact.observation.process_id-ne701-or$fact.observation.process_started_at_utc_ticks-ne801L){throw 'Reopen changed process or resource identity'}
 if($mode-eq'unknown'){
  if($fact.observation.exit_confirmed-or$null-ne$fact.observation.returncode-or$caught.Exception.Message-ne'ORIGINAL_OBSERVATION_FAILURE'){throw 'Unknown writer or primary error was changed'}
 }elseif(-not$fact.observation.exit_confirmed-or$fact.observation.returncode-ne$(if($mode-eq'nonzero'){7}else{0})){throw 'Known process completion changed after scientific failure'}
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'reopen.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE.with_name('execute.ps1')),str(ROOT),str(root/'run'),sys.executable],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unconfirmed_host_release_keeps_primary_and_protection(self):
        code=r"""param($Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$nodes=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.Body.Extent.Text.Contains('$released=Exit-HostResourceStage')},$true))
if($nodes.Count-ne1){throw 'Expected one actual host release boundary'}
$boundary=[scriptblock]::Create($nodes[0].Extent.Text)
function Exit-HostResourceStage {param($Lease,[switch]$PassThru);if($mode-eq'error'){throw 'ACTUAL_RELEASE_FAILURE'};return $null}
foreach($mode in @('null','error')){
 $lease=@{token='TEST_ONLY_ACQUIRED';inherited=$false};$NativeOperations=$null;$ResourceReleases=$null;$writerUnknown=$false
 try{throw 'PRIMARY_SCIENCE_FAILURE'}catch{$failure=$_}
 . $boundary
 if(-not$writerUnknown-or$null-eq$lease-or$failure.Exception.Message-ne'PRIMARY_SCIENCE_FAILURE'-or-not$failure.Exception.Data.Contains('host_release_error')){throw 'Unknown host release lost primary or protection'}
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'host_release.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE.with_name('execute.ps1'))],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_original_cli_resumes_without_request_or_solver(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);facade=root/'repo'
            for source in (ROOT/'common').rglob('*'):
                if source.is_file() and source.suffix in {'.py','.ps1','.json'} and 'assets' not in source.parts:
                    target=facade/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
            policy_path=facade/'common/contracts/artifact_capacity_policy.json'
            policy=json.loads(policy_path.read_text(encoding='utf-8'));policy.update(target_gib=64/1024,minimum_free_gib=0)
            policy_path.write_text(json.dumps(policy),encoding='utf-8')
            (facade/'config').mkdir();shutil.copyfile(ROOT/'config/project_registry.json',facade/'config/project_registry.json')
            cli=facade/'integrations/workflows/single_reflection_flight/run.ps1';cli.parent.mkdir(parents=True)
            shutil.copyfile(EXECUTE_SOURCE,cli)
            helper=owner_fixture.RunArtifactWorkflowTests()
            case=root/'case';case.mkdir()
            with patch.object(owner_fixture,'REPO',facade),patch.object(owner_fixture,'OWNER',facade/'common/contracts/run_artifact_workflow.ps1'):
                first,run,_,failed=helper.invoke_fixture(case,{},retention='solver_review',failure_stage='seal',project='instrument_assembly')
            self.assertNotEqual(failed.returncode,0,failed.stdout+failed.stderr)
            self.assertFalse(first['capacity_finalized'])
            result_path=case/'result.json'
            command=[PWSH,'-NoProfile','-File',str(cli),'-ResumeFinalization','-ResultPath',str(result_path),'-RepoRoot',str(facade)]
            resumed=subprocess.run(command,cwd=root,env={**os.environ,'SIMULATION_PYTHON_EXE':sys.executable},capture_output=True,text=True,encoding='utf-8',timeout=45)
            self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
            self.assertEqual((case/'callback_count.txt').read_text(),'1')
            manifest=(run/'run_manifest.json').read_bytes()
            again=subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=45)
            self.assertEqual(again.returncode,0,again.stdout+again.stderr)
            self.assertEqual((run/'run_manifest.json').read_bytes(),manifest)
            self.assertEqual((case/'callback_count.txt').read_text(),'1')

    def test_resume_rejects_execution_stage_switches_before_reading_paths(self):
        code=r"""param($Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($stage in @('FieldDesignOnly','WorkbenchOnly','Fly')){
 $arguments=@{ResumeFinalization=$true;ResultPath='MISSING_RESULT';RepoRoot='MISSING_REPO'}
 $arguments[$stage]=$true
 $caught=$null
 try{& $Source @arguments}catch{$caught=$_}
 if($null-eq$caught-or$caught.FullyQualifiedErrorId.Split(',')[0]-ne'AmbiguousParameterSet'){
  throw ('Resume accepted execution selection or read a path before binding: '+$stage)
 }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'resume_binding.ps1'
            script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE)],
                                  cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_mode_conflict_is_rejected_before_source_or_root_resolution(self):
        result=subprocess.run([PWSH,'-NoProfile','-File',str(EXECUTE_SOURCE),'-Request','not-a-file',
            '-ExecutionBudgetPath','not-a-budget','-FieldDesignOnly','-WorkbenchOnly','-RepoRoot','not-a-repository'],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Select at most one',result.stderr)

    def test_unknown_writer_preserves_public_owner_and_primary_exception(self):
        code=r"""param($Source,$Repo,$Run)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$body=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$null-ne$_.Finally})[-1]
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
foreach($name in @('inputs','results','logs')){[IO.Directory]::CreateDirectory((Join-Path $Run $name))|Out-Null}
$package=@{artifact_run_dir=$Run;input_dir=(Join-Path $Run inputs);run_config=(Join-Path $Run run_config.json)}
$stage='fly';$stageName='native_prepare';$scientificSummary=$null;$ResultPath='TEST_ONLY_RESULT'
$writerUnknown=$false;$ownerContext=@{completion_written=$false};$capacity=@{};$lease=@{token='TEST_ONLY_PARENT'}
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$nativeOperations.Add(@{operation_id='actual_unknown';observation=@{exit_confirmed=$false}})
$phaseTimings=[ordered]@{};$runClock=[Diagnostics.Stopwatch]::StartNew();$pathEnvironmentNames=@();$savedPathEnvironment=@{}
$failure=$null;try{throw 'PRIMARY_NATIVE_FAILURE'}catch{$failure=$_}
$script:completed=$false;$script:restored=$false
function Exit-ArtifactWorkflowCapacitySession {throw 'unknown capacity released'}
function Remove-RunPackageExecutionAlias {throw 'unknown alias removed'}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure)
 if($Status-ne'failed'-or$WritersStopped-or$OriginalFailure.Exception.Message-ne'PRIMARY_NATIVE_FAILURE'-or$Summary.execution_status-ne'writer_completion_unknown'){throw 'adapter changed unknown/primary facts'}
 $script:completed=$true;throw 'PUBLIC_WRITER_UNKNOWN'
}
function Restore-RunEnvironment {param($Names,$Snapshot);if(-not$script:completed){throw 'environment restored before finalization'};$script:restored=$true}
. $finalizer
if(-not$completed-or-not$restored-or$null-eq$lease-or$failure.Exception.Message-ne'PRIMARY_NATIVE_FAILURE'-or-not$failure.Exception.Data.Contains('finalization_error')){throw 'primary/cleanup/protection facts lost'}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'adapter.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE),str(ROOT),str(root/'run')],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
