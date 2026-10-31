"""Thin cooled frontend binding to the public owner and original resume CLI."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXECUTE_SOURCE = ROOT/'integrations/workflows/cooled_frontend/execute.ps1'
PWSH = shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell 7 required')
class CooledFrontendOwnerRecoveryTests(unittest.TestCase):
    def test_unknown_writer_keeps_protection_and_primary_error(self):
        code=r"""param($Source,$Repo,$Run)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$body=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$null-ne$_.Finally})[-1]
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
foreach($name in @('inputs','results','logs')){[IO.Directory]::CreateDirectory((Join-Path $Run $name))|Out-Null}
$package=@{artifact_run_dir=$Run;input_dir=(Join-Path $Run inputs);run_config=(Join-Path $Run run_config.json)}
$script:run=$Run;$stage='native_prepare';$summaryRole='cooled_frontend_population_summary';$scope='complete_mother_population';$populationFlightAttempted=$true;$scientificSummary=$null;$ResultPath='TEST_ONLY_RESULT'
$writerUnknown=$false;$hostReleaseUnknown=$false;$ownerContext=@{completion_written=$false};$capacity=@{};$lease=@{token='TEST_ONLY_PARENT'}
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$nativeOperations.Add(@{operation_id='actual_unknown';observation=@{exit_confirmed=$false}})
$workingFieldGuards=[Collections.Generic.List[string]]::new();$workingFieldGuards.Add('TEST_ONLY_GUARDED_PA')
$phaseTimings=[ordered]@{};$stageClock=[Diagnostics.Stopwatch]::StartNew();$runClock=[Diagnostics.Stopwatch]::StartNew();$saved=@{};$sourceReaders=[Collections.Generic.List[object]]::new();$script:readerReleased=$false
$reader=[pscustomobject]@{};$reader|Add-Member ScriptMethod Dispose {$script:readerReleased=$true};$sourceReaders.Add($reader)
$failure=$null;try{throw 'PRIMARY_NATIVE_FAILURE'}catch{$failure=$_}
$script:completed=$false;$script:restored=$false
function Close-CooledHostStage {throw 'unknown parent grant released'}
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
if($readerReleased-or-not$completed-or-not$restored-or$null-eq$lease-or$workingFieldGuards.Count-ne1-or$failure.Exception.Message-ne'PRIMARY_NATIVE_FAILURE'-or-not$failure.Exception.Data.Contains('finalization_error')){throw 'primary/cleanup/protection facts lost'}
'COOLED_UNKNOWN_ADAPTER=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'adapter.ps1';script.write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script),str(EXECUTE_SOURCE),str(ROOT),str(root/'run')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('COOLED_UNKNOWN_ADAPTER=PASS',result.stdout)
