"""Native owner transport uses real short processes, never a solver fixture."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO/"integrations/runtime/frontend_flight_support.ps1"
CONSUMER_ROOT = REPO


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell unavailable")
class NativePathConsumerTests(unittest.TestCase):
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


    def test_local_and_cooled_topology_project_environment_paths_before_actual_writer(self):
        code=r"""param($Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
$source=Join-Path $Repo 'integrations/workflows/local_frontend/execute.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$topology.InvokeVerifier'},$true)
Invoke-Expression ('$callback='+$node.Right.Extent.Text)
$callbacks=@($callback)
$source=Join-Path $Repo 'integrations/workflows/cooled_frontend/execute.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$parameters.InvokeVerifier'},$true)
Invoke-Expression ('$callback='+$node.Right.Extent.Text);$callbacks+=@($callback)
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
 if($calls-ne2-or$nativeOperations.Count-ne2-or$result.exit_code-ne0){throw 'topology writer/fact wiring failed'}
 if($env:SIMION_APERTURE_PA_PATH-ne(Join-Path $run 'inputs/field.pa')){throw 'persistent caller environment rewritten'}
 function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool);throw 'PREPARATION_FAILED_BEFORE_WRITER'}
 try{&$callback $verifier;throw 'missing preparation failure'}catch{if($_.Exception.Message-ne'PREPARATION_FAILED_BEFORE_WRITER'){throw}}
 if($calls-ne2-or$nativeOperations.Count-ne2){throw 'preparation failure created native operation'}
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
