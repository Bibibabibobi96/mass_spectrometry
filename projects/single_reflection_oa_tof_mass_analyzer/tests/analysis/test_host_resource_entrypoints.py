"""Execute real entrypoint cleanup around mocked leases, without any solver."""
from __future__ import annotations

import os
import json
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
    def test_fixed_n100_forwards_actual_inputs_to_guarded_flight_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="n100-guard-route-") as directory:
            root = Path(directory)
            workbench = root / "projects/oa/simion/workbench"
            workbench.mkdir(parents=True)
            transport = workbench / "run_n100_transport.ps1"
            transport.write_bytes((PROJECT / "simion/workbench/run_n100_transport.ps1").read_bytes())
            support = root / "common/contracts/run_artifact_support.ps1"
            support.parent.mkdir(parents=True)
            support.write_text("function Write-RunJson {param($Path,$Value) $Value|ConvertTo-Json -Depth 32|Set-Content -LiteralPath $Path -Encoding utf8}\n", encoding="utf-8")
            (workbench / "run_candidate_flight.ps1").write_text(r'''
param($ExecutionRequestPath,$RuntimeReceiptPath,$CapacitySessionPath,$PythonExe,$RepositoryRoot)
$request=Get-Content -LiteralPath $ExecutionRequestPath -Raw|ConvertFrom-Json
@{request=$request;runtime=$RuntimeReceiptPath;session=$CapacitySessionPath;python=$PythonExe;repo=$RepositoryRoot}|
 ConvertTo-Json -Depth 32|Set-Content -LiteralPath $env:OA_TEST_CAPTURE -Encoding utf8
throw 'deliberate guard boundary rejection'
''', encoding="utf-8")
            inputs = {}
            for key, suffix in (("IobPath", ".iob"), ("IonPath", ".ion"),
                                ("AnalyzerScript", ".ps1"), ("ResolvedContractPath", ".json"),
                                ("RuntimeReceiptPath", ".json"), ("CapacitySessionPath", ".json")):
                path = root / (key + suffix)
                path.write_text("fixture", encoding="utf-8")
                inputs[key] = str(path)
            inputs["SimionExe"] = sys.executable
            inputs["PythonExe"] = sys.executable
            for key in ("LogPath", "ErrorPath", "DiagnosticsPath", "ParticleCsv", "SummaryPath", "CompletionPath"):
                inputs[key] = str(root / "outputs" / (key + ".json"))
            inputs.update(RunId="fixture-run", ContextSha256="a" * 64)
            captured = root / "captured.json"
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(transport),
                *[value for key, item in inputs.items() for value in ("-" + key, item)]], cwd=root,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
                env=dict(os.environ, OA_TEST_CAPTURE=str(captured)), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("deliberate guard boundary rejection", result.stderr)
            record = json.loads(captured.read_text(encoding="utf-8-sig"))
            self.assertEqual(record["runtime"], inputs["RuntimeReceiptPath"])
            self.assertEqual(record["session"], inputs["CapacitySessionPath"])
            self.assertEqual(record["python"], sys.executable)
            self.assertEqual(Path(record["repo"]), root)
            request = record["request"]
            self.assertEqual(request["context_sha256"], "a" * 64)
            self.assertEqual(request["run_id"], "fixture-run")
            self.assertEqual(request["result_receipt"], inputs["CompletionPath"])
            self.assertEqual(request["argv"], ["--default-num-particles", "100", "--nogui", "fly",
                "--trajectory-quality", "8", "--retain-trajectories", "0", "--particles", inputs["IonPath"],
                "--adjustable", "trajectory_quality=8", "--adjustable", "trajectory_log_enable=1", inputs["IobPath"]])
            self.assertFalse(Path(inputs["ParticleCsv"]).exists())

    def run_failure(self, relative: str, arguments: list[str], *, nested: bool = False) -> str:
        with tempfile.TemporaryDirectory(prefix="oa_resource_entry_test_") as directory:
            root = Path(directory)
            target = root / "projects/oa" / relative
            target.parent.mkdir(parents=True)
            target.write_bytes((PROJECT / relative).read_bytes())
            support = root / "common"
            (support / "contracts").mkdir(parents=True)
            (support / "host_execution_lease.ps1").write_text(LEASE_STUB, encoding="utf-8")
            # Resolve real roots with the explicit interpreter, then fail at
            # the next absent science dependency. No native asset is copied.
            paths = support / "paths"
            paths.mkdir()
            for name in ("workspace_paths.ps1", "workspace_paths.py"):
                shutil.copyfile(PROJECT.parents[1] / "common/paths" / name, paths / name)
            (support / "contracts/run_artifact_support.ps1").write_text(r'''
. (Join-Path $PSScriptRoot '../host_execution_lease.ps1')
$public=[Management.Automation.Language.Parser]::ParseFile($env:OA_TEST_PUBLIC_SUPPORT,[ref]$null,[ref]$null)
foreach($name in @('Save-RunEnvironment','Restore-RunEnvironment')){
 $functions=@($public.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq$name},$true))
 if($functions.Count-ne1){throw 'Public environment boundary is not unique'}
 Invoke-Expression $functions[0].Extent.Text
}
''', encoding="utf-8", newline="\n")
            environment = dict(os.environ, OA_TEST_PARENT_HEAVY="1" if nested else "0",
                SIMULATION_PYTHON_EXE=sys.executable,
                OA_TEST_PUBLIC_SUPPORT=str(PROJECT.parents[1]/"common/contracts/run_artifact_support.ps1"),
                MASS_SPECTROMETRY_ARTIFACT_ROOT=str(root/"artifacts"),
                MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/"execution"),
                MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/"host.sqlite3"))
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
        cases = (
            ("workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1", [], "SIMION"),
            ("workflows/formal_reference/run_formal_validation.ps1", [], "SIMION"),
            ("simion/workbench/run_ideal_field_diagnostic.ps1", ["-AnalyzeOnly", "-SourceRunPath", "fixture-source"], "GATE"),
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

    def test_deep_lua_transport_uses_frozen_root_and_preserves_unknown_writer(self) -> None:
        script = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:OA_TEST_REPO 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($env:OA_TEST_BUILDER,[ref]$null,[ref]$null)
$f=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-SimionLua'},$true)
. ([scriptblock]::Create($f.Extent.Text))
$cleanup=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.StartsWith('if($null-ne$script:codeExecutionAlias-and$script:allOperationsStopped)')},$true)
if($null-eq$cleanup){throw 'Actual builder cleanup missing'}
function Invoke-OwnedSimionArguments {
 param($ArgumentList,$OperationId)
 $script:observedLua=[string]$ArgumentList[3]
 if($script:observedLua.Length-ge260){throw 'Native Lua argv still exceeds MAX_PATH'}
 if((Get-Content -LiteralPath $script:observedLua -Raw)-cne'frozen Lua fixture'){throw 'Wrong source transport'}
 if($script:mode-ne'success'){
  $e=[Exception]::new('NATIVE_PRIMARY_SENTINEL')
  $e.Data['native_operation_observation']=@{observation=@{exit_confirmed=($script:mode-ne'unknown');returncode=$(if($script:mode-eq'unknown'){$null}else{7})};managed_process_completion=@{}}
  throw $e
 }
 return @{observation=@{exit_confirmed=$true;returncode=0};managed_process_completion=@{}}
}
$expectedRunRoot=Join-Path $env:TEMP 'managed-run'
[IO.Directory]::CreateDirectory($expectedRunRoot)|Out-Null
$repoRoot=Join-Path $expectedRunRoot 'inputs/code'
while($repoRoot.Length-lt285){$repoRoot=Join-Path $repoRoot 'frozen_segment'}
[IO.Directory]::CreateDirectory($repoRoot)|Out-Null
$lua=Join-Path $repoRoot 'fixture.lua';[IO.File]::WriteAllText($lua,'frozen Lua fixture')
$execution=Join-Path $env:TEMP 'frozen-execution'
Write-RunJson -Path (Join-Path $expectedRunRoot 'run_config.json') -Value @{paths=@{execution_root=$execution}}
$env:MASS_SPECTROMETRY_EXECUTION_ROOT=Join-Path $env:TEMP 'drifted-default'
$removeAlias=${function:Remove-RunExecutionAlias}
foreach($mode in @('success','failed','unknown','cleanup_failure')){
 $script:mode=$mode;$script:codeExecutionAlias=$null;$script:nativeSequence=0
 $nativeOperations=[Collections.Generic.List[object]]::new();$caught=$null
 try{Invoke-SimionLua $lua @()}catch{$caught=$_}
 if(($mode-eq'success')-ne($null-eq$caught)){throw 'Wrong native failure propagation'}
 if($null-ne$caught-and$caught.Exception.Message-cne'NATIVE_PRIMARY_SENTINEL'){throw $caught}
 $alias=$script:codeExecutionAlias.execution_alias
 if((Split-Path -Parent $alias)-ine$execution){throw 'Frozen execution root was not used'}
 $script:allOperationsStopped=$mode-ne'unknown';$buildFailure=$caught
 if($mode-eq'cleanup_failure'){function Remove-RunExecutionAlias {param($ExecutionAlias,$TargetDirectory);throw 'CLEANUP_SECONDARY_SENTINEL'}}
 . ([scriptblock]::Create($cleanup.Extent.Text))
 if($null-ne$buildFailure-and$buildFailure.Exception.Message-cne'NATIVE_PRIMARY_SENTINEL'){throw 'Cleanup masked native primary'}
 if($mode-eq'cleanup_failure'){
  if(-not(Test-Path -LiteralPath $alias)){throw 'Failed cleanup alias unexpectedly vanished'}
  Set-Item Function:Remove-RunExecutionAlias $removeAlias
  Remove-RunExecutionAlias -ExecutionAlias $alias -TargetDirectory $repoRoot
 }
 if((Test-Path -LiteralPath $alias)-ne($mode-eq'unknown')){throw 'Known/unknown alias cleanup differs'}
 if($mode-eq'unknown'){
  # No real writer was started by this inert fixture. Keep the production
  # unknown protection assertion above, then remove only this fixture junction.
  Remove-RunExecutionAlias -ExecutionAlias $alias -TargetDirectory $repoRoot
 }
}
$script:codeExecutionAlias=$null
$outside=Join-Path (Split-Path -Parent $repoRoot) 'outside.lua';[IO.File]::WriteAllText($outside,'external')
$rejected=$false
try{Invoke-SimionLua $outside @()}catch{if($_.Exception.Message-notlike'*outside its frozen*'){throw};$rejected=$true}
if(-not$rejected-or$null-ne$script:codeExecutionAlias){throw 'External code was transported'}
'DEEP_LUA_TRANSPORT=PASS'
"""
        with tempfile.TemporaryDirectory(prefix="oa-lua-path-") as directory:
            environment = dict(os.environ, TEMP=directory, OA_TEST_REPO=str(PROJECT.parents[1]),
                               OA_TEST_BUILDER=str(PROJECT / "simion/workbench/build_formal_delivery.ps1"))
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                    cwd=PROJECT, env=environment, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DEEP_LUA_TRANSPORT=PASS", result.stdout)

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
function Invoke-OwnedSimionArguments {
 param($ArgumentList,$OperationId)
 Invoke-NativeFixture
 if($script:fail){throw 'Native component operation failed: fixture'}
 return @{observation=@{exit_confirmed=$true;returncode=0};managed_process_completion=@{fixture=$true}}
}
$SimionExe='Invoke-NativeFixture';$outputFull=$env:TEMP
$script:nativeSequence=0;$nativeOperations=[Collections.Generic.List[object]]::new()
$stageWallSeconds=@{}
foreach($fail in @($false,$true)) {
  $script:fail=$fail;$script:events=[Collections.Generic.List[string]]::new()
  $hostExecutionLease=[pscustomobject]@{token='same-token';stage='prepare'}
  $caught=$false
  try {
    if($env:OA_TEST_FUNCTION -eq 'Invoke-Builder') { Invoke-Builder 'fixture.lua' @() 'fixture' }
    else { Invoke-SimionLua 'fixture.lua' @() -Refines }
  } catch { if($_.Exception.Message -notlike 'SIMION *failed*'-and$_.Exception.Message-notlike'Native component operation failed:*'){throw};$caught=$true }
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
        for relative in ("simion/workbench/run_parameterized_geometry_smoke.ps1",
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
            line = next(line for line in builder.splitlines() if "Invoke-SimionLua -Refines" in line and name in line)
            self.assertIn("-Refines", line)
        iob_line = next(line for line in builder.splitlines() if "Invoke-SimionLua" in line and "build_formal_iob.lua" in line)
        self.assertNotIn("-Refines", iob_line)
        transport = (PROJECT / "simion/workbench/run_n100_transport.ps1").read_text(encoding="utf-8")
        self.assertNotIn("Start-Process", transport)
        self.assertIn("'run_candidate_flight.ps1'", transport)
        flight = (PROJECT / "simion/workbench/run_candidate_flight.ps1").read_text(encoding="utf-8")
        self.assertLess(flight.index("Enter-HostExecutionLease -Role SIMION -Stage flight"),
                        flight.index("Invoke-RepositoryManagedPythonProcess"))
        for name in ("RuntimeReceiptPath", "CapacitySessionPath", "PythonExe", "RepositoryRoot"):
            self.assertIn("-" + name, transport)

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
            self.assertTrue((code / "common/resource_budget_support.ps1").is_file())
            script = """
$ErrorActionPreference='Stop'
. ./common/host_execution_lease.ps1
. ./common/resource_budget_support.ps1
$observationSource=(Get-Command New-RepositoryProcessObservation).ScriptBlock.File
if($observationSource -ne [IO.Path]::GetFullPath('./common/resource_budget_support.ps1')){
  throw 'Process observation did not load from the frozen closure'
}
$observation=New-RepositoryProcessObservation
if($null -ne $observation.usage -or $observation.usage_path -or $observation.run_dir){
  throw 'Unbudgeted frozen observation unexpectedly requires usage output'
}
function Get-CimInstance {
  param($ClassName, $ErrorAction)
  switch($ClassName) {
    Win32_OperatingSystem { [pscustomobject]@{TotalVisibleMemorySize=32MB;FreePhysicalMemory=24MB} }
    Win32_Processor { [pscustomobject]@{LoadPercentage=0} }
    Win32_PerfFormattedData_PerfDisk_PhysicalDisk {
      $volume=[IO.Path]::GetPathRoot($PWD.Path).TrimEnd([IO.Path]::DirectorySeparatorChar)
      [pscustomobject]@{Name=('0 ' + $volume);CurrentDiskQueueLength=0}
    }
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
    ResolvedContractPath='absent';ExpectedParticleCount=99;RuntimeReceiptPath='absent';CapacitySessionPath='absent';
    CompletionPath='absent';ContextSha256='absent';RunId='absent';PythonExe='absent'}
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
