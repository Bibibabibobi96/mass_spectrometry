"""Exercise public native path preparation without a solver or PA payload."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
class NativeExecutionPathsTests(unittest.TestCase):
    def test_host_release_restores_missing_and_explicit_empty_environment(self):
        source = r'''
param($Repo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/host_execution_lease.ps1')
$name='MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'
foreach($prior in @($null,'')){
 [Environment]::SetEnvironmentVariable($name,'temporary-owned-state','Process')
 $lease=[pscustomobject]@{inherited=$true;environment_set=$true;previous_environment=@{($name)=$prior}}
 Exit-HostResourceStage -Lease $lease
 $actual=[Environment]::GetEnvironmentVariable($name,'Process')
 if($null-eq$prior){if($null-ne$actual){throw 'Originally absent host state leaked as an empty value'}}
 elseif($actual-cne''){throw 'Explicit empty host state was not preserved'}
}
'''
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-Command', '& { ' + source + ' }', str(ROOT)],
            cwd=ROOT, text=True, encoding='utf-8', capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_host_snapshot_observes_payload_volume_and_explicit_target(self):
        script = r'''
param($Repo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/host_execution_lease.ps1')
function Get-CimInstance {
 param($ClassName,$ErrorAction)
 switch($ClassName){
  Win32_OperatingSystem {return [pscustomobject]@{TotalVisibleMemorySize=1000000;FreePhysicalMemory=500000}}
  Win32_Processor {return [pscustomobject]@{LoadPercentage=0}}
  Win32_Process {return @()}
  Win32_PerfFormattedData_PerfDisk_PhysicalDisk {return @(
   [pscustomobject]@{Name='0 C:';CurrentDiskQueueLength=3},
   [pscustomobject]@{Name='1 D:';CurrentDiskQueueLength=0})}
  default {throw ('Unexpected telemetry class: '+$ClassName)}
 }
}
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT='D:\payload'
Remove-Item Env:\MASS_SPECTROMETRY_RUN_DIRECTORY -ErrorAction SilentlyContinue
if((Get-HostResourceSnapshot).io_pressure){throw 'Source disk pressure blocked the configured payload volume'}
$env:MASS_SPECTROMETRY_RUN_DIRECTORY='C:\frozen-run'
if(-not(Get-HostResourceSnapshot).io_pressure){throw 'Frozen run volume was ignored'}
if((Get-HostResourceSnapshot -TargetPath 'D:\explicit').io_pressure){throw 'Explicit payload target did not win'}
$caught=$false
try{Get-HostResourceSnapshot -TargetPath 'relative'|Out-Null}catch{
 if($_.Exception.Message-ne'Host I/O observation target must be absolute.'){throw};$caught=$true
}
if(-not$caught){throw 'Relative observation target was accepted'}
'''
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-Command', '& { ' + script + ' }', str(ROOT)],
            cwd=ROOT, text=True, encoding='utf-8', capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_plan_selects_alias_and_scoped_environment_restores_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deep = root / ("deep-" + "a"*90) / ("nested-" + "b"*90)
            source = deep / "inputs/native/control.lua"
            source.parent.mkdir(parents=True)
            source.write_text("frozen native input", encoding="utf-8")
            script = root / "check.ps1"
            script.write_text(r'''param($Repo,$Root,$Deep,$InputFile,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
function Package($Path){[pscustomobject]@{artifact_run_dir=$Path;run_dir=$Path;execution_alias=$null;execution_path_capacity=$null;python=$Python}}
$short=Package $Root
$shortContext=Get-RunNativeExecutionContext -Package $short -Paths @((Join-Path $Root 'result.json')) -Tool 'fixture'
if($null-ne$shortContext.execution_alias){throw 'Short native plan created an alias'}
$analysis=Package $Deep
$analysisContext=Get-RunNativeExecutionContext -Package $analysis -Paths @() -Tool 'analysis'
if($null-ne$analysisContext.execution_alias){throw 'No-native scope created an alias'}
$package=Package $Deep
$package|Add-Member -NotePropertyName path_context -NotePropertyValue ([pscustomobject]@{
 artifact_root=(Join-Path $Root 'payload');execution_root=(Join-Path $Root 'exec');host_resource_state_path=(Join-Path $Root 'scheduler.sqlite3')
})
$executionRoot=Join-Path $Root 'exec'
$context=Get-RunNativeExecutionContext -Package $package -Paths @($InputFile,(Join-Path $Deep 'results/derived.pa#')) -ExecutionRoot $executionRoot -Tool 'fixture'
try{
 if($null-eq$context.execution_alias-or$package.artifact_run_dir-cne$Deep){throw 'Persistent/execution roots were not separated'}
 if([IO.File]::ReadAllText($context.projected_paths[0])-cne'frozen native input'){throw 'Native projection changed the file'}
 if($context.projected_paths[1].Length-gt259){throw 'Derived native suffix remains too long'}
 $again=Get-RunNativeExecutionContext -Package $package -Paths $context.projected_paths -ExecutionRoot $executionRoot -Tool 'fixture'
 if($again.execution_alias-cne$context.execution_alias){throw 'Repeated native preparation created another alias'}
 $beforeLocation=(Get-Location).Path
 $before=[Environment]::GetEnvironmentVariable('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
 $caught=$false
 try{Invoke-RunToolRootContext -RepoRoot $Repo -Environment $context.environment -Operation {
   if($env:MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY-cne$context.run_dir-or$env:PYTHONDONTWRITEBYTECODE-ne'1'){throw 'Native environment was not scoped'}
   if($env:MASS_SPECTROMETRY_ARTIFACT_ROOT-cne$package.path_context.artifact_root-or$env:MASS_SPECTROMETRY_EXECUTION_ROOT-cne$package.path_context.execution_root-or$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH-cne$package.path_context.host_resource_state_path){throw 'Frozen deployment roots did not reach the native consumer'}
   throw 'ORIGINAL_FAILURE'
 }}catch{if($_.Exception.Message-ne'ORIGINAL_FAILURE'){throw};$caught=$true}
 if(-not$caught){throw 'Original failure was lost'}
 if((Get-Location).Path-cne$beforeLocation){throw 'Working directory leaked'}
 if([Environment]::GetEnvironmentVariable('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')-cne$before){throw ('Environment leaked: before='+($null-eq$before)+' after='+[Environment]::GetEnvironmentVariable('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY'))}
}finally{Remove-RunPackageExecutionAlias -Package $package}
if(-not(Test-Path -LiteralPath $InputFile)-or(Test-Path -LiteralPath $context.run_dir)){throw 'Alias cleanup changed persistent inputs'}
if($null-ne$package.execution_alias-or$package.run_dir-cne$Deep-or$null-ne$package.execution_path_capacity){throw 'Package retained a deleted execution representation'}
$reopened=Get-RunNativeExecutionContext -Package $package -Paths @($InputFile) -Tool 'fixture cold reopen'
try{
 if($reopened.run_dir-ceq$context.run_dir-or-not(Test-Path -LiteralPath $reopened.projected_paths[0])){throw 'Cold reopen returned an expired alias'}
 # Also cover a restored package whose recorded alias was cleaned elsewhere.
 $expired=$package.execution_alias
 Remove-RunExecutionAlias -ExecutionAlias $expired -TargetDirectory $Deep
 $restored=Get-RunNativeExecutionContext -Package $package -Paths @($InputFile) -Tool 'fixture restored package'
 if($restored.run_dir-ceq$expired-or[IO.File]::ReadAllText($restored.projected_paths[0])-cne'frozen native input'){throw 'Restored package did not recreate its execution representation'}
}finally{Remove-RunPackageExecutionAlias -Package $package}
$external=Join-Path (Join-Path (Split-Path -Parent $Root) ('external-'+('x'*180))) (('y'*80)+'.lua')
$caught=$false;try{Get-RunNativeExecutionContext -Package $short -Paths @($external) -Tool 'fixture'|Out-Null}catch{if($_.Exception.Message-notmatch'external_input_requires_its_existing_owner_transport'){throw};$caught=$true}
if(-not$caught){throw 'Untransported long external input passed native preparation'}
''', encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ROOT), str(root), str(deep), str(source), sys.executable],
                                    cwd=root, text=True, encoding="utf-8", capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
