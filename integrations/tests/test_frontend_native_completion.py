"""Public completion transport; inert process records, no solver launch."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
class FrontendNativeCompletionTests(unittest.TestCase):
    def test_known_failure_unknown_and_callback_preserve_each_actual_fact(self):
        code = r'''param($Repo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
$facts=[Collections.Generic.List[object]]::new()
$birth=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks
$unknown=@{observed_process_exit_confirmed=$false;observed_process_returncode=$null;observed_process_id=$PID;observed_process_started_at_utc_ticks=$birth}
Add-FrontendNativeOperation -NativeOperations $facts -NativeResourceReleaseId OWNER -OperationId unknown -ExceptionData $unknown
$known=@{exit_code=0;root_process_id=$PID;root_process_started_at_utc_ticks=$birth;completed=$true}
Add-FrontendNativeOperation -NativeOperations $facts -NativeResourceReleaseId OWNER -OperationId same -ProcessRecord $known
if($facts.Count-ne1-or$facts[0].observation.exit_confirmed){throw 'Known completion replaced another unknown writer fact'}
$failed=@{exit_code=7;root_process_id=$PID;root_process_started_at_utc_ticks=($birth+1);completed=$true;name='failed'}
Add-FrontendNativeOperation -NativeOperations $facts -NativeResourceReleaseId OWNER -OperationId failed -ProcessRecord $failed
if($facts.Count-ne2-or$facts[1].observation.returncode-ne7-or-not$facts[1].observation.exit_confirmed){throw 'Failed natural exit fact lost'}
$NativeOperations=$facts;$NativeResourceReleaseId='OWNER';$Phase='baseline'
$OnProcessCompleted={param($record);throw 'SCIENTIFIC_CALLBACK_FAILURE'}
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1'),[ref]$null,[ref]$null)
$function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-FrontendFlightPhase'},$true)
foreach($statement in $function.Body.EndBlock.Statements){
 if($statement.Extent.Text-match '^\$completion(?:Writer|Operations|ReleaseId|Phase)?='-or$statement.Extent.Text-match '^\$scientificCompletion='){. ([scriptblock]::Create($statement.Extent.Text))}
}
$known.root_process_started_at_utc_ticks=$birth+2;$known.name='success'
$caught=$null;try{& $completion $known}catch{$caught=$_}
if($null-eq$caught-or$caught.Exception.Message-ne'SCIENTIFIC_CALLBACK_FAILURE'-or$facts.Count-ne3-or$facts[2].observation.returncode-ne0){throw 'Completion must precede scientific callback failure'}
if($facts[0].observation.exit_confirmed){throw 'Later success erased unknown completion'}
'PUBLIC_FRONTEND_COMPLETION=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "completion.ps1"
            script.write_text(code, encoding="utf-8")
            actual = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script), str(ROOT)],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
            self.assertIn("PUBLIC_FRONTEND_COMPLETION=PASS", actual.stdout)
