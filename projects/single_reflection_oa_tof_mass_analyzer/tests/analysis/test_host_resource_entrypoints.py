"""Execute real entrypoint cleanup around mocked leases, without any solver."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]
LEASE_STUB = """
function Enter-HostExecutionLease {
  param($Role, $RunId, $Stage)
  Write-Host "TEST_LEASE_ENTER=$Role"
  Write-Host "TEST_LEASE_STAGE=$Stage"
  $inherited = $env:OA_TEST_PARENT_HEAVY -eq '1'
  Write-Host "TEST_LEASE_INHERITED=$inherited"
  return [pscustomobject]@{role=$Role;inherited=$inherited}
}
function Exit-HostExecutionLease {
  param($Lease)
  Write-Host "TEST_LEASE_EXIT=$($Lease.role)"
  # Exercise Windows reader-thread decoding with a non-UTF8 error-stream byte.
  [Console]::OpenStandardError().WriteByte(0xA1)
}
"""


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "PowerShell 7 required")
class HostResourceEntrypointTests(unittest.TestCase):
    def run_failure(self, relative: str, arguments: list[str], *, nested: bool = False) -> str:
        with tempfile.TemporaryDirectory(prefix="oa_resource_entry_test_") as directory:
            root = Path(directory)
            target = root / "projects/oa" / relative
            target.parent.mkdir(parents=True)
            target.write_bytes((PROJECT / relative).read_bytes())
            support = root / "common"
            (support / "contracts").mkdir(parents=True)
            (support / "host_execution_lease.ps1").write_text(LEASE_STUB, encoding="utf-8")
            (support / "contracts/run_artifact_support.ps1").write_text("", encoding="utf-8")
            # Both real scripts fail at their first Python operation because
            # this fixture has no runtime. No scientific assets are copied.
            environment = dict(os.environ, OA_TEST_PARENT_HEAVY="1" if nested else "0")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(target), *arguments],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False, env=environment, cwd=root,
            )
            self.assertIsInstance(result.stdout, str)
            self.assertIsInstance(result.stderr, str)
            self.assertIn("\ufffd", result.stderr)
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            return output

    def test_gate_selects_role_before_work_and_releases_on_failure(self) -> None:
        for level, candidate, role in (
            ("Static", "SIMION", "GATE"),
            ("Candidate", "SIMION", "SIMION"),
            ("Candidate", "COMSOL", "COMSOL"),
            ("Candidate", "CAD", "GATE"),
            ("Formal", "SIMION", "COMSOL"),
        ):
            with self.subTest(level=level, candidate=candidate):
                output = self.run_failure("verify_project.ps1", ["-Level", level, "-CandidateTarget", candidate])
                self.assertEqual(output.count(f"TEST_LEASE_ENTER={role}"), 1, output)
                self.assertEqual(output.count(f"TEST_LEASE_EXIT={role}"), 1, output)
                self.assertIn("Python 3.11 runtime missing", output)
                stage = "prepare"
                self.assertIn(f"TEST_LEASE_STAGE={stage}", output)

    def test_standalone_geometry_smoke_prepares_light_and_releases_on_failure(self) -> None:
        output = self.run_failure("simion/workbench/run_parameterized_geometry_smoke.ps1", ["-RunId", "fixture"])
        self.assertIn("python.exe", output)
        self.assertIn("TEST_LEASE_STAGE=prepare", output)
        self.assertEqual(output.count("TEST_LEASE_ENTER=SIMION"), 1, output)
        self.assertEqual(output.count("TEST_LEASE_EXIT=SIMION"), 1, output)

    def test_direct_flight_entrypoints_select_permission_and_release(self) -> None:
        transport_arguments = [value for name in (
            "SimionExe", "IobPath", "IonPath", "LogPath", "ErrorPath", "DiagnosticsPath",
            "ParticleCsv", "SummaryPath", "AnalyzerScript", "ResolvedContractPath",
        ) for value in ("-" + name, "absent-fixture-input")]
        cases = (
            ("workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1", [], "SIMION"),
            ("workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1", ["-ReanalyzeOnly"], "GATE"),
            ("simion/workbench/run_n100_transport.ps1", transport_arguments, "SIMION"),
            ("workflows/formal_reference/run_formal_validation.ps1", [], "SIMION"),
            ("simion/workbench/run_ideal_field_diagnostic.ps1", ["-AnalyzeOnly"], "SIMION"),
            ("tests/simion/run_field_idealization_sweep.ps1", [], "SIMION"),
            ("tests/simion/run_field_idealization_sweep.ps1", ["-ValidateConfigOnly"], "GATE"),
        )
        for relative, arguments, role in cases:
            for nested in (False, True):
                with self.subTest(entry=relative, arguments=arguments, nested=nested):
                    output = self.run_failure(relative, arguments, nested=nested)
                    self.assertEqual(output.count(f"TEST_LEASE_ENTER={role}"), 1, output)
                    self.assertEqual(output.count(f"TEST_LEASE_EXIT={role}"), 1, output)
                    self.assertIn(f"TEST_LEASE_INHERITED={nested}", output)
                    if relative.endswith("run_n100_transport.ps1"):
                        self.assertIn("Required SIMION transport input is missing", output)

    def test_refining_lua_builders_switch_stage_and_propagate_failure(self) -> None:
        script = r"""
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:OA_TEST_BUILDER,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Builder parse failed'}
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $env:OA_TEST_FUNCTION},$true)
. ([scriptblock]::Create($function.Extent.Text))
function Get-HostResourceBudget { param($Role,$Stage) return @{} }
function Update-HostResourceStage {
  param($Lease,$Stage,$Budget,$RetainedMemoryBytes)
  if($Lease.token -ne 'same-token'){throw 'Token changed'}
  $Lease.stage=$Stage
  $script:events.Add($Stage)
  return $Lease
}
function Invoke-NativeFixture {
  if($hostExecutionLease.stage -ne 'pa_refine'){throw 'Native refine lacked heavy stage'}
  $script:events.Add('native')
  $global:LASTEXITCODE=if($script:fail){7}else{0}
}
$SimionExe='Invoke-NativeFixture';$outputFull=$env:TEMP
$stageWallSeconds=@{}
foreach($fail in @($false,$true)) {
  $script:fail=$fail;$script:events=[Collections.Generic.List[string]]::new()
  $hostExecutionLease=[pscustomobject]@{token='same-token';stage='prepare'}
  $caught=$false
  try {
    if($env:OA_TEST_FUNCTION -eq 'Invoke-Builder') { Invoke-Builder 'fixture.lua' @() 'fixture' }
    else { Invoke-SimionLua 'fixture.lua' @() -Refines }
  } catch { if($_.Exception.Message -notlike 'SIMION *failed*'){throw};$caught=$true }
  if($caught -ne $fail){throw 'Native failure was swallowed'}
  $expected=if($fail){'pa_refine,native'}else{'pa_refine,native,prepare'}
  if(($script:events -join ',') -ne $expected){throw "Wrong stage order: $script:events"}
}
'BUILDER_STAGES=PASS'
"""
        for name, function in (("run_parameterized_geometry_smoke.ps1", "Invoke-Builder"),
                               ("build_formal_delivery.ps1", "Invoke-SimionLua")):
            with self.subTest(builder=name), tempfile.TemporaryDirectory() as directory:
                environment = dict(os.environ, OA_TEST_BUILDER=str(PROJECT / "simion/workbench" / name),
                                   OA_TEST_FUNCTION=function, TEMP=directory)
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                        cwd=PROJECT, env=environment, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("BUILDER_STAGES=PASS", result.stdout)

    def test_mixed_solver_handoff_never_releases_an_inherited_grant(self) -> None:
        script = r"""
$ErrorActionPreference='Stop'
$t=$null;$e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:OA_TEST_ENTRY,[ref]$t,[ref]$e)
$drop=$ast.Find({param($n) $n -is [Management.Automation.Language.IfStatementAst] -and
  $n.Extent.Text.StartsWith('if ($null -ne $hostExecutionLease -and -not $hostExecutionLease.inherited)')},$true)
$restore=$ast.Find({param($n) $n -is [Management.Automation.Language.IfStatementAst] -and
  $n.Extent.Text.StartsWith('if ($null -eq $hostExecutionLease)') -and
  $n.Extent.Text.Contains('Enter-HostExecutionLease')},$true)
if($null -eq $drop -or $null -eq $restore){throw 'Missing child lifecycle handoff'}
function Exit-HostExecutionLease { param($Lease) if($Lease.inherited){throw 'Released parent'}; $script:released++ }
function Enter-HostExecutionLease { param($Role,$Stage) $script:acquired++; return [pscustomobject]@{inherited=$false} }
$hostRole='SIMION'
foreach($nested in @($false,$true)) {
  foreach($fail in @($false,$true)) {
    $script:released=0;$script:acquired=0;$caught=$false
    $hostExecutionLease=[pscustomobject]@{inherited=$nested}
    try {
      . ([scriptblock]::Create($drop.Extent.Text))
      if($nested -ne ($null -ne $hostExecutionLease)){throw 'Wrong ownership at child call'}
      if($fail){throw 'fixture-child-failed'}
      . ([scriptblock]::Create($restore.Extent.Text))
    } catch { if($_.Exception.Message -ne 'fixture-child-failed'){throw};$caught=$true }
    $expectedRelease=if($nested){0}else{1}
    $expectedAcquire=if($nested -or $fail){0}else{1}
    if($script:released -ne $expectedRelease -or $script:acquired -ne $expectedAcquire -or $caught -ne $fail){throw 'Incorrect child failure/ownership handling'}
  }
}
'HANDOFF=PASS'
"""
        for relative in ("verify_project.ps1", "workflows/formal_reference/run_formal_validation.ps1",
                         "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1"):
            with self.subTest(entry=relative):
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                        cwd=PROJECT, env=dict(os.environ, OA_TEST_ENTRY=str(PROJECT / relative)),
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("HANDOFF=PASS", result.stdout)

    def test_direct_flights_have_stage_boundaries_and_builder_marks_real_refine(self) -> None:
        for relative in ("simion/workbench/run_n100_transport.ps1",
                         "simion/workbench/run_parameterized_geometry_smoke.ps1",
                         "simion/workbench/run_ideal_field_diagnostic.ps1",
                         "tests/simion/run_field_idealization_sweep.ps1",
                         "workflows/formal_reference/run_formal_validation.ps1",
                         "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1"):
            with self.subTest(entry=relative):
                source = (PROJECT / relative).read_text(encoding="utf-8")
                flight = source.index("= Start-Process -FilePath $SimionExe")
                self.assertLess(source.index("Update-HostResourceStage -Lease $hostExecutionLease -Stage flight"), flight)
                self.assertGreater(source.index("Update-HostResourceStage -Lease $hostExecutionLease -Stage postprocess"), flight)
                self.assertNotIn("Enter-HostExecutionLease -Role $hostRole -Stage pa_prepare", source)
        builder = (PROJECT / "simion/workbench/build_formal_delivery.ps1").read_text(encoding="utf-8")
        for name in ("build_two_zone_pa.lua", "build_reflectron_variant.lua",
                     "build_flight_tube_variant.lua", "build_detector_variant.lua"):
            line = next(line for line in builder.splitlines() if "Invoke-SimionLua" in line and name in line)
            self.assertIn("-Refines", line)
        iob_line = next(line for line in builder.splitlines() if "Invoke-SimionLua" in line and "build_formal_iob.lua" in line)
        self.assertNotIn("-Refines", iob_line)

    def test_frozen_scheduler_closure_uses_bound_python_and_shared_inheritance(self) -> None:
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
            freeze_candidate_source_closure, verify_candidate_source_closure,
        )
        with tempfile.TemporaryDirectory(prefix="oa_frozen_resource_test_") as directory:
            root = Path(directory)
            code = root / "code"
            closure = freeze_candidate_source_closure(code, root / "artifacts", Path(sys.executable))
            verify_candidate_source_closure(closure)
            self.assertTrue((code / "common/host_resource_scheduler.py").is_file())
            self.assertTrue((code / "common/host_resource_policy.json").is_file())
            script = """
$ErrorActionPreference='Stop'
. ./common/host_execution_lease.ps1
function Get-CimInstance {
  param($ClassName, $ErrorAction)
  switch($ClassName) {
    Win32_OperatingSystem { [pscustomobject]@{TotalVisibleMemorySize=32MB;FreePhysicalMemory=24MB} }
    Win32_Processor { [pscustomobject]@{LoadPercentage=0} }
    Win32_PerfFormattedData_PerfDisk_PhysicalDisk { [pscustomobject]@{Name='fixture';CurrentDiskQueueLength=0} }
    Win32_Process { [pscustomobject]@{ProcessId=$PID;ParentProcessId=0;CreationDate=[datetime]'2026-01-01';WorkingSetSize=32MB;PrivatePageCount=32MB;ExecutablePath='fixture.exe'} }
  }
}
$lease=Enter-HostExecutionLease -Role SIMION -Stage flight
try {
  $child=Enter-HostExecutionLease -Role SIMION -Stage flight
  if(-not $child.inherited -or $child.token -ne $lease.token){throw 'Nested grant duplicated'}
  Exit-HostExecutionLease -Lease $child
  $transport='./projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_n100_transport.ps1'
  $arguments=@{SimionExe='absent';IobPath='absent';IonPath='absent';LogPath='absent';ErrorPath='absent';
    DiagnosticsPath='absent';ParticleCsv='absent';SummaryPath='absent';AnalyzerScript='absent';
    ResolvedContractPath='absent';ExpectedParticleCount=99}
  $expectedFailure=$false
  try { & $transport @arguments } catch { $expectedFailure=$_.Exception.Message -like '*fixed N=100*' }
  if(-not $expectedFailure){throw 'Frozen transport did not reach its input validation'}
  Assert-HostResourceHeavyStage
} finally { Exit-HostExecutionLease -Lease $lease }
if(@((Get-HostResourceStatus).records).Count){throw 'Frozen grant leaked'}
Write-Output 'FROZEN_HOST_ENTRY=PASS'
"""
            environment = dict(os.environ, MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root / "state.sqlite3"),
                               SIMULATION_PYTHON_EXE="intentionally-absent-runtime")
            environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
            # Status's default path is initialized separately from the env.
            script = script.replace(". ./common/host_execution_lease.ps1", ". ./common/host_execution_lease.ps1\n$script:HostResourceStatePath=$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH")
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                    cwd=code, env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=45, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FROZEN_HOST_ENTRY=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
