"""Thin local frontend binding to the public owner and original resume CLI."""
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
EXECUTE_SOURCE = ROOT/'integrations/workflows/local_frontend/execute.ps1'
PWSH = shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell 7 required')
class LocalFrontendOwnerRecoveryTests(unittest.TestCase):
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
            clis=[]
            for consumer in ('local_frontend','cooled_frontend'):
                cli=facade/f'integrations/workflows/{consumer}/execute.ps1';cli.parent.mkdir(parents=True)
                shutil.copyfile(ROOT/f'integrations/workflows/{consumer}/execute.ps1',cli);clis.append(cli)
            helper=owner_fixture.RunArtifactWorkflowTests()
            case=root/'case';case.mkdir()
            with patch.object(owner_fixture,'REPO',facade),patch.object(owner_fixture,'OWNER',facade/'common/contracts/run_artifact_workflow.ps1'):
                first,run,_,failed=helper.invoke_fixture(case,{'status':'failed','log':'complete','preserve':True},retention='solver_review',failure_stage='seal',project='instrument_assembly')
            self.assertNotEqual(failed.returncode,0,failed.stdout+failed.stderr)
            self.assertFalse(first['capacity_finalized'])
            result_path=case/'result.json'
            original_manifest=None
            for cli in clis:
                command=[PWSH,'-NoProfile','-File',str(cli),'-ResumeFinalization','-ResultPath',str(result_path),'-RepoRoot',str(facade)]
                resumed=subprocess.run(command,cwd=root,env={**os.environ,'SIMULATION_PYTHON_EXE':sys.executable},capture_output=True,text=True,encoding='utf-8',timeout=45)
                self.assertNotEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
                self.assertIn('finalization completed; original terminal status is failed',resumed.stderr)
                actual_result=json.loads(result_path.read_text(encoding='utf-8'))
                self.assertEqual((actual_result['status'],actual_result['stage']),('failed','complete'))
                self.assertEqual((case/'callback_count.txt').read_text(),'1')
                manifest=(run/'run_manifest.json').read_bytes()
                if original_manifest is None:
                    original_manifest=manifest
                self.assertEqual(manifest,original_manifest)
                rejected=subprocess.run(command+['-ExecutionBudgetPath',str(root/'must-not-be-read.json')],
                    cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertNotEqual(rejected.returncode,0,rejected.stdout+rejected.stderr)
                self.assertIn('original frozen operation',rejected.stderr)
                self.assertEqual((case/'callback_count.txt').read_text(),'1')
                self.assertEqual((run/'run_manifest.json').read_bytes(),original_manifest)

    def test_registered_budget_paths_survive_execution_alias_removal(self):
        code = r"""param($Repo,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
$canonical=Join-Path $Root canonical;$alias=Join-Path $Root alias
[IO.Directory]::CreateDirectory((Join-Path $canonical inputs))|Out-Null
[IO.File]::WriteAllText((Join-Path $canonical 'inputs/budget.json'),'FROZEN_BUDGET')
New-Item -ItemType Junction -Path $alias -Target $canonical|Out-Null
$package=@{artifact_run_dir=$canonical;input_dir=(Join-Path $alias inputs);run_config=(Join-Path $canonical run_config.json)}
$ownerContext=@{run_directory=$canonical;execution_run_directory=$alias}
$budget=@{frozen_budget=(Join-Path $alias 'inputs/budget.json')};$ExecutionBudgetPath='UNUSED'
$budgetPaths=@();$stage='analysis';$scope='field';$populationFlightAttempted=$false
function Write-RunJson {param($Path,$Value,$Depth);$Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
foreach($owner in @('local_frontend','cooled_frontend')){
 '{}'|Set-Content -LiteralPath $package.run_config
 '{"inputs":{}}'|Set-Content -LiteralPath $package.run_config
 $source=Join-Path $Repo ('integrations/workflows/'+$owner+'/execute.ps1')
 $name=if($owner-eq'local_frontend'){'Register-LocalInputs'}else{'Register-CooledInputs'}
 $ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
 $function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 . ([scriptblock]::Create($function.Extent.Text));& $name
 $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json
 if($config.parameters.execution_budget-ne(Join-Path $canonical 'inputs/budget.json')){throw 'budget alias leaked'}
 $script:budgetPaths+=@($config.parameters.execution_budget)
}
Remove-Item -LiteralPath $alias -Force
foreach($path in $budgetPaths){if([IO.File]::ReadAllText($path)-ne'FROZEN_BUDGET'){throw 'persistent budget unreadable'}}
'BUDGET_CANONICAL=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'register.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(ROOT),str(root)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('BUDGET_CANONICAL=PASS',result.stdout)

    def test_unknown_writer_keeps_protection_and_primary_error(self):
        code=r"""param($Source,$Repo,$Run)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$body=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$null-ne$_.Finally})[-1]
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
foreach($name in @('inputs','results','logs')){[IO.Directory]::CreateDirectory((Join-Path $Run $name))|Out-Null}
$package=@{artifact_run_dir=$Run;input_dir=(Join-Path $Run inputs);run_config=(Join-Path $Run run_config.json)}
$script:run=$Run;$stage='native_prepare';$scientificSummary=$null;$ResultPath='TEST_ONLY_RESULT'
$writerUnknown=$false;$hostReleaseUnknown=$false;$ownerContext=@{completion_written=$false};$capacity=@{};$lease=@{token='TEST_ONLY_PARENT'}
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$nativeOperations.Add(@{operation_id='actual_unknown';observation=@{exit_confirmed=$false}})
$workingFieldGuards=[Collections.Generic.List[string]]::new();$workingFieldGuards.Add('TEST_ONLY_GUARDED_PA')
$phaseTimings=[ordered]@{};$stageClock=[Diagnostics.Stopwatch]::StartNew();$runClock=[Diagnostics.Stopwatch]::StartNew();$oldEnvironment=@{}
$failure=$null;try{throw 'PRIMARY_NATIVE_FAILURE'}catch{$failure=$_}
$script:completed=$false;$script:restored=$false
function Close-LocalHostStage {throw 'unknown parent grant released'}
function Unprotect-ImmutablePaSource {throw 'unknown PA guard released'}
function Exit-ArtifactWorkflowCapacitySession {throw 'unknown capacity released'}
function Remove-RunPackageExecutionAlias {throw 'unknown alias removed'}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure)
 if($Status-ne'failed'-or$WritersStopped-or$OriginalFailure.Exception.Message-ne'PRIMARY_NATIVE_FAILURE'-or$Summary.execution_status-ne'writer_completion_unknown'){throw 'adapter changed unknown/primary facts'}
 $script:completed=$true;throw 'PUBLIC_WRITER_UNKNOWN'
}
function Restore-RunEnvironment {param($Names,$Snapshot);if(-not$script:completed){throw 'environment restored before finalization'};$script:restored=$true}
. $finalizer
if(-not$completed-or-not$restored-or$null-eq$lease-or$workingFieldGuards.Count-ne1-or$failure.Exception.Message-ne'PRIMARY_NATIVE_FAILURE'-or-not$failure.Exception.Data.Contains('finalization_error')){throw 'primary/cleanup/protection facts lost'}
'LOCAL_UNKNOWN_ADAPTER=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'adapter.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE),str(ROOT),str(root/'run')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('LOCAL_UNKNOWN_ADAPTER=PASS',result.stdout)

    def test_flight_binding_retains_actual_fact_list_and_propagates_error(self):
        code=r"""param($Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-LocalFlightPhase'},$true)
. ([scriptblock]::Create($node.Extent.Text))
$package=@{};$script:run='TEST_RUN';$projectArtifacts='TEST_PROJECT';$script:pythonRoot='TEST_ROOT';$Python='TEST_PYTHON'
$workflowModule='integrations.workflows.local_frontend';$simion='TEST_SOLVER';$budget=@{limits=@{}};$lease=@{token='TEST_PARENT'}
$nativeOperations=[Collections.Generic.List[object]]::new();$script:fail=$false
function Invoke-FrontendFlightPhase {
 param($Package,$RunDirectory,$ProjectRunsRoot,$RepoRoot,$Python,$RuntimeModule,$SimionExe,$Limits,$Phase,$PulseTimeUs,$SharedTimesPath,$NativeOperations,$NativeResourceReleaseId)
 if(-not[object]::ReferenceEquals($NativeOperations,$script:nativeOperations)-or$NativeResourceReleaseId-ne'TEST_PARENT'-or$Phase-ne'extraction'-or$PulseTimeUs-ne12.5-or$SharedTimesPath-ne'TEST_TIMES'){throw 'native fact or physical phase binding changed'}
 if($script:fail){throw 'PUBLIC_PHASE_FAILURE'}
 return 'ACTUAL_PUBLIC_PHASE_RETURN'
}
if((Invoke-LocalFlightPhase -Phase extraction -PulseTime 12.5 -SharedTimesPath TEST_TIMES)-ne'ACTUAL_PUBLIC_PHASE_RETURN'){throw 'public return dropped'}
$script:fail=$true;$rejected=$false
try{Invoke-LocalFlightPhase -Phase extraction -PulseTime 12.5 -SharedTimesPath TEST_TIMES}catch{if($_.Exception.Message-ne'PUBLIC_PHASE_FAILURE'){throw};$rejected=$true}
if(-not$rejected){throw 'public phase error swallowed'}
'LOCAL_PHASE_BINDING=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'binding.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('LOCAL_PHASE_BINDING=PASS',result.stdout)
