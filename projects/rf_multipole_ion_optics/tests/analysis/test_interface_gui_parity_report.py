"""Project report behavior and thin real normal-CLI wiring; no solver launch."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
CLI = PROJECT / "workflows/interface_readiness/run_comsol.ps1"


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell7 required")
class InterfaceGuiParityReportTests(unittest.TestCase):
    def test_real_report_reader_and_normal_consumer_keep_unknown_echo_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "gui_report.txt"
            value = dict(role="rf_interface_gui_parity", status="PASS", scientific_result="NOT_EVALUATED",
                         source_binding_verified=True, observed_state_parity_verified=True,
                         native_birth_echo_unavailable_saved_observation=True, particle_ids=[41, 9], particles=2,
                         terminal_outcomes=[dict(particle_id=41, status="unknown"), dict(particle_id=9, status="transmitted")],
                         common_stored_time_count=4, compared_finite_state_count=5, maximum_position_error_mm=0,
                         maximum_velocity_error_m_s=0, transport_tolerance_mm_and_m_s=1e-12)
            report.write_text("GUI_PARITY_JSON=" + json.dumps(value) + "\nSTATUS=PASS\n", encoding="utf-8")
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
if($e.Count){throw 'actual CLI parse failed'}
$f=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Read-InterfaceGuiParityReport'},$true)
. ([scriptblock]::Create($f.Extent.Text))
$actual=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41)
if(-not$actual.source_binding_verified-or-not$actual.native_birth_echo_unavailable_saved_observation-or$actual.scientific_result-cne'NOT_EVALUATED'){throw 'native echo unknown was erased or promoted'}
# Actual GUI invocation through report consumption, with only the native call
# replaced at its existing boundary. The substituted call launches no process.
function Invoke-InterfaceComsolTask {param($Task,$Report,$Stage,$State);if($Stage-cne'gui'-or$Report-cne REPORT){throw 'GUI report binding differs'};$script:called=$true}
$source=[IO.File]::ReadAllText(ENTRY)
$call=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Invoke-InterfaceComsolTask'-and$n.Extent.Text.Contains('-Stage gui')},$true)
$consume=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$guiParity'},$true)
$frozenCodeRoot='frozen';$guiVerifyReport=REPORT;$ownerState=@{};$solverSummary=@{source_ids=@(9,41)}
. ([scriptblock]::Create($source.Substring($call.Extent.StartOffset,$consume.Extent.EndOffset-$call.Extent.StartOffset)))
$summary=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$publicSummary.gui_verification'},$true)
$publicSummary=@{};. ([scriptblock]::Create($summary.Extent.Text))
if(-not$script:called-or$publicSummary.gui_verification.scientific_result-cne'NOT_EVALUATED'-or-not$publicSummary.gui_verification.native_birth_echo_unavailable_saved_observation){throw 'normal CLI did not consume the actual GUI parity report'}
$original=Get-Content REPORT -Raw
foreach($kind in @('binding','science','echo','ids','tolerance','null_error','duplicates')){
 $bad=$original.Substring('GUI_PARITY_JSON='.Length).Split([char]10)[0]|ConvertFrom-Json -AsHashtable
 switch($kind){
  'binding'{$bad.source_binding_verified=$false;$expected='*unconfirmed*'}
  'science'{$bad.scientific_result='PASS';$expected='*unconfirmed*'}
  'echo'{$bad.native_birth_echo_unavailable_saved_observation='true';$expected='*unconfirmed*'}
  'ids'{$bad.particle_ids=@(41,88);$expected='*complete original mother*'}
  'tolerance'{$bad.transport_tolerance_mm_and_m_s=1e-8;$expected='*changed the original transport tolerance*'}
  'null_error'{$bad.maximum_position_error_mm=$null;$expected='*observed-state error is invalid*'}
  'duplicates'{$expected='*exactly one completed observed-parity*'}
 }
 $line='GUI_PARITY_JSON='+($bad|ConvertTo-Json -Compress -Depth 32)
 if($kind-eq'duplicates'){$line+=[Environment]::NewLine+$line}
 $line|Set-Content REPORT
 $caught=$false;try{$null=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41)}catch{if($_.Exception.Message-notlike$expected){throw};$caught=$true}
 if(-not$caught){throw ('invalid report accepted: '+$kind)}
}
""".replace('ENTRY', literal(CLI)).replace('REPORT', literal(report))
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                                    cwd=PROJECT.parents[1])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
