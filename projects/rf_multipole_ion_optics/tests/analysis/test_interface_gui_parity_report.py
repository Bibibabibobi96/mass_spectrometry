"""Actual GUI report/normal/analyze consumer wiring; vendor and owner boundaries explicit."""
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


def observation_fixture(root, *, accepted=True):
    value = dict(role="rf_interface_gui_parity", status="PASS" if accepted else "FAIL",
                 scientific_result="NOT_EVALUATED", numerical_equivalence_status="NOT_EVALUATED",
                 gui_operation_completed=True, original_acceptance_verified=accepted,
                 source_binding_verified=True, observed_state_parity_verified=False,
                 native_birth_echo_unavailable_saved_observation=True, particle_ids=[41, 9], particles=2,
                 original_acceptance=dict(particles=2, expected_particles=2, hits=1 if accepted else 0,
                                          expected_hits=1),
                 terminal_outcomes=[dict(status="unknown"), dict(status="transmitted")],
                 common_stored_time_count=4, compared_finite_state_count=5,
                 maximum_position_error_mm=3e-4, maximum_velocity_error_m_s=0.03,
                 rms_position_component_error_mm=1e-4, rms_velocity_component_error_m_s=0.01,
                 active_mask_difference_count=1, terminal_observation_difference_count=1,
                 project_outcome_difference_count=1,
                 snapshot_files=["gui_observations_saved.mat", "gui_observations_computed.mat"])
    root.mkdir(parents=True, exist_ok=True)
    for name in value['snapshot_files']:
        # The PS reader verifies declared roles/presence; real MAT roundtrip is
        # tested in RfInterfaceGuiParityTest, not forged by this file sentinel.
        (root / name).write_bytes(b"TEST_ONLY opaque presence sentinel")
    (root / "gui_verification.json").write_text(json.dumps(value), encoding="utf-8")
    return value


def run_command(command):
    return subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                          cwd=PROJECT.parents[1])


READER = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
if($e.Count){throw 'actual CLI parse failed'}
$f=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Read-InterfaceGuiParityReport'},$true)
. ([scriptblock]::Create($f.Extent.Text))
"""


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell7 required")
class InterfaceGuiParityReportTests(unittest.TestCase):
    def test_real_report_reader_and_normal_consumer_separate_diagnostics_from_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observation_fixture(root / 'results')
            report = root / 'logs' / 'report.txt'
            report.parent.mkdir()
            report.write_text('TEST_ONLY damaged textual report; JSON/observations remain', encoding='utf-8')
            command = READER + r"""
$actual=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41) -ObservationRoot OBS -ExpectedHits 1
if(-not$actual.source_binding_verified-or-not$actual.native_birth_echo_unavailable_saved_observation-or$actual.observed_state_parity_verified-or$actual.numerical_equivalence_status-cne'NOT_EVALUATED'){throw 'diagnostics promoted or unavailable echo erased'}
# Only the existing native invocation is replaced; actual normal call -> reader
# -> public-summary assignment executes from the original CLI AST.
function Invoke-InterfaceComsolTask {param($Task,$Report,$Stage,$State);if($Stage-cne'gui'-or$Report-cne REPORT){throw 'GUI report binding differs'};$script:called=$true}
$source=[IO.File]::ReadAllText(ENTRY)
$call=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Invoke-InterfaceComsolTask'-and$n.Extent.Text.Contains('-Stage gui')},$true)
$consume=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$guiParity'},$true)
$frozenCodeRoot='frozen';$guiVerifyReport=REPORT;$ownerState=@{};$solverSummary=@{source_ids=@(9,41);hits=1};$package=@{artifact_run_dir=PARENT}
. ([scriptblock]::Create($source.Substring($call.Extent.StartOffset,$consume.Extent.EndOffset-$call.Extent.StartOffset)))
$summary=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$publicSummary.gui_verification'},$true)
$publicSummary=@{};. ([scriptblock]::Create($summary.Extent.Text))
if(-not$script:called-or$publicSummary.gui_verification.observed_state_parity_verified-or-not$publicSummary.gui_verification.original_acceptance_verified){throw 'normal CLI did not preserve distinct GUI acceptance/diagnostics'}
$original=Get-Content (Join-Path OBS 'gui_verification.json') -Raw
$unpaired=$original|ConvertFrom-Json -AsHashtable;$unpaired.common_stored_time_count=0;$unpaired.compared_finite_state_count=0
foreach($key in @('maximum_position_error_mm','maximum_velocity_error_m_s','rms_position_component_error_mm','rms_velocity_component_error_m_s')){$unpaired[$key]=@()}
$unpaired|ConvertTo-Json -Depth 32|Set-Content (Join-Path OBS 'gui_verification.json')
$empty=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41) -ObservationRoot OBS -ExpectedHits 1
if($empty.observed_state_parity_verified-or$empty.compared_finite_state_count-ne0){throw 'empty shared observation was promoted to equivalence'}
$original|Set-Content (Join-Path OBS 'gui_verification.json')
foreach($kind in @('binding','science','echo','ids','parity','numerical','null_error','acceptance')){
 $bad=$original|ConvertFrom-Json -AsHashtable
 switch($kind){
  'binding'{$bad.source_binding_verified=$false;$expected='*unconfirmed*'}
  'science'{$bad.scientific_result='PASS';$expected='*unconfirmed*'}
  'echo'{$bad.native_birth_echo_unavailable_saved_observation='true';$expected='*unconfirmed*'}
  'ids'{$bad.particle_ids=@(41,88);$expected='*complete original mother*'}
  'parity'{$bad.observed_state_parity_verified=$true;$expected='*unconfirmed*'}
  'numerical'{$bad.numerical_equivalence_status='PASS';$expected='*unconfirmed*'}
  'null_error'{$bad.maximum_position_error_mm=$null;$expected='*diagnostic is invalid*'}
  'acceptance'{$bad.original_acceptance.hits=0;$expected='*acceptance is contradictory*'}
 }
 $bad|ConvertTo-Json -Depth 32|Set-Content (Join-Path OBS 'gui_verification.json')
 $caught=$false;try{$null=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41) -ObservationRoot OBS -ExpectedHits 1}catch{if($_.Exception.Message-notlike$expected){throw};$caught=$true}
 if(-not$caught){throw ('invalid report accepted: '+$kind)}
}
$original|Set-Content (Join-Path OBS 'gui_verification.json')
Move-Item -LiteralPath (Join-Path OBS 'gui_verification.json') -Destination (Join-Path OBS 'gui_verification.saved')
$caught=$false;try{$null=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41) -ObservationRoot OBS}catch{if($_.Exception.Message-notlike'*retained MAT*without COMSOL*'){throw};$caught=$true}
if(-not$caught){throw 'retained observations did not identify zero-Compute analysis recovery'}
Move-Item -LiteralPath (Join-Path OBS 'gui_verification.saved') -Destination (Join-Path OBS 'gui_verification.json')
Remove-Item -LiteralPath (Join-Path OBS 'gui_observations_computed.mat')
$caught=$false;try{$null=Read-InterfaceGuiParityReport -Path REPORT -ExpectedParticleIds @(9,41) -ObservationRoot OBS}catch{if($_.Exception.Message-notlike'*original observations are missing*'){throw};$caught=$true}
if(-not$caught){throw 'missing actual observation accepted'}
"""
            command = command.replace('ENTRY', literal(CLI)).replace('REPORT', literal(report))
            command = command.replace('OBS', literal(root / 'results')).replace('PARENT', literal(root))
            result = run_command(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_analyze_consumer_preserves_failed_acceptance_without_compute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observation_fixture(root / 'results', accepted=False)
            (root / 'logs').mkdir()
            (root / 'results/solver_summary.json').write_text(json.dumps(dict(hits=1)), encoding='utf-8')
            receipt = dict(role='comsol_launcher_completion', run_id='fixture',
                           operations=[dict(operation_id='TEST_ONLY_stopped_native_fixture', observation=dict(
                               exit_confirmed=True, returncode=2))],
                           host_release=dict(inherited=False, token='TEST_ONLY_fixture'))
            (root / 'logs/gui_completion.json').write_text(json.dumps(receipt), encoding='utf-8')
            command = READER + r"""
# Public source admission/owner validation is covered by its existing matrix.
# These two explicit boundary doubles only assert this consumer forwards the
# same actual receipt and does not try another native/Compute invocation.
function Add-RunArtifactResourceRelease {param($ResourceReleases,$ReleaseId,$Receipt);if($ReleaseId-cne'saved-gui'-or$Receipt.run_id-cne'fixture'){throw 'GUI release binding differs'};$script:releaseCalled=$true}
function Assert-WorkflowWriterCompletion {param($Value,[switch]$PowerShellOwner);if(-not$PowerShellOwner-or$Value.operations.Count-ne1-or$Value.operations[0].observation.returncode-ne2){throw 'GUI failed native completion was erased'};$script:writerCalled=$true}
function Invoke-InterfaceComsolTask {throw 'AnalyzeOnly must not invoke native'}
$source=[IO.File]::ReadAllText(ENTRY)
$start=$source.IndexOf("        `$guiEvidence=Join-Path")
$end=$source.IndexOf('        Complete-InterfaceOwner -Status success -Summary $result',$start)
if($start-lt0-or$end-lt$start){throw 'actual AnalyzeOnly GUI re-read block is missing'}
$parentRoot=PARENT;$raw=@{source_ids=@(9,41)};$config=@{run_id='fixture'};$result=@{gui_verified=$false;new_solve_calls=0}
. ([scriptblock]::Create($source.Substring($start,$end-$start)))
if(-not$script:releaseCalled-or-not$script:writerCalled-or$result.gui_verified-or$result.gui_verification.status-cne'FAIL'-or$result.gui_verification.numerical_equivalence_status-cne'NOT_EVALUATED'-or$result.new_solve_calls-ne0){throw 'AnalyzeOnly changed old failed acceptance or invoked Compute'}
$caught=$false;try{$null=Read-InterfaceGuiParityReport -Path 'unused' -ExpectedParticleIds @(9,41) -ObservationRoot (Join-Path $parentRoot 'results') -ExpectedHits 1}catch{if($_.Exception.Message-notlike'*original count/hit acceptance failed*'){throw};$caught=$true}
if(-not$caught){throw 'normal acceptance failure was hidden'}
"""
            command = command.replace('ENTRY', literal(CLI)).replace('PARENT', literal(root))
            result = run_command(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
