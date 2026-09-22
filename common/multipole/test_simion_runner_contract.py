import csv
import ctypes
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.multipole.particle_source_preflight import COLUMNS
from common.multipole.simion_particle_source import render_canonical_source
from common.simion.resource_profile import publish_resource_profile


RUNNER = Path(__file__).resolve().parent / "run_simion_finite_3d_transport.ps1"
REPO_ROOT = Path(__file__).parents[2]


def _short_windows_path(path: Path) -> Path:
    """Return an existing path's 8.3 spelling when Windows exposes one."""
    if sys.platform != "win32":
        return path
    get_short_path = ctypes.windll.kernel32.GetShortPathNameW
    required = get_short_path(str(path), None, 0)
    if required == 0:
        return path
    buffer = ctypes.create_unicode_buffer(required)
    if get_short_path(str(path), buffer, required) == 0:
        return path
    return Path(buffer.value)


class SimionRunnerContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_control_receipt_cannot_replace_primary_observation(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    $resourceUsage=if($name-eq$primaryName)"):
                       source.index("    if($batchRuns.Count-gt 1){\n      if($script:retainedFormalBatchOutputs.ContainsKey($name))")]
        support = (RUNNER.parent / "resource_budget_support.ps1").read_text(encoding="utf-8-sig")
        observation = support[support.index("  if($ExistingProcessRecords.Count-gt 0){\n    $first="):
                              support.index("  Write-ResourceUsage -Usage $usage -Path $UsagePath", support.index("    $usage.first_formal_observation="))]
        terminal = source[source.index("  $caseResourceUsage=[ordered]@{}"):
                          source.index("  if($null-ne$dispatchPlan-and$resourceIdentityWasUnknown){", source.index("  $caseResourceUsage=[ordered]@{}"))]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support_path = str(RUNNER.parent / "resource_budget_support.ps1").replace("'", "''")
            script = f". '{support_path}'\n" + """
$ErrorActionPreference='Stop'
$resultDir=$PWD.Path;$runDir=$resultDir;$primaryName='primary'
$script:calls=@()
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
 $usage=@{role='multipole_resource_usage';status='running';peak_run_directory_bytes=0;peak_process_tree_working_set_bytes=999999}
""" + observation + """
 $usage|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $UsagePath
 $script:calls+=@{launched=@($ProcessSpecifications|ForEach-Object{$_.scheduler_batch.index});retained=@($ExistingProcessRecords).Count}
 return @{resource_budget_exceeded=$false;processes=@(@{exit_code=0})}
}
$simion='unused';$solverDir='.';$logDir='.';$dispatchPlan='unused';$rfDriveKernelLua='unused'
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(1,2|ForEach-Object{@{batch=@{index=$_;particle_id_min=$_;particle_id_max=$_};lua_config='unused';fly2='unused'}})
# Explicit fixture observation differs from the aggregate peak above.
$script:existingFormalProcessRecords=@(@{name='primary-first';peak_working_set_bytes=12345;
 peak_managed_memory_bytes=12345;completed_during_observation=$true;
 observed_process_cpu_percent=12;observed_background_cpu_percent=3})
function Run-Case($name) {
""" + block + """
}
Run-Case primary
$before=[IO.File]::ReadAllText((Join-Path $resultDir 'resource_usage.json'))
Run-Case control
if([IO.File]::ReadAllText((Join-Path $resultDir 'resource_usage.json')) -ne $before){throw 'Control overwrote primary'}
$resourceUsage=Join-Path $resultDir 'resource_usage.json'
$resolvedResourceBudget=$null;$control=@{};$controlName='control'
$null=Complete-ResourceUsage -RunDir $runDir -UsagePath $resourceUsage
""" + terminal + """
ConvertTo-Json -InputObject $script:calls -Depth 6
"""
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-Command", script],
                cwd=root, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [
                {"launched": [2], "retained": 1}, {"launched": [1, 2], "retained": 0},
            ])
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan", "resource_identity": {"solver": "SIMION"},
                "waves": [{"kind": "observed_formal_batch", "batches": [{"count": 1}]}],
            }), encoding="utf-8")
            profile = publish_resource_profile(
                run_id="fixture", resource_usage_path=root / "resource_usage.json", dispatch_plan_path=plan,
            )
            self.assertEqual(profile["per_batch_peak_working_set_bytes"], 12345)
            for name, filename in (("primary", "resource_usage.json"), ("control", "resource_usage__control.json")):
                receipt = json.loads((root / filename).read_text(encoding="utf-8-sig"))
                self.assertEqual(receipt["case_name"], name)
                self.assertEqual(receipt["status"], "completed")
                self.assertEqual(receipt["measurement_scope"], "single_transport_case_not_all_run_cases")
            with self.assertRaisesRegex(ValueError, "explicit first formal observation"):
                publish_resource_profile(
                    run_id="fixture", resource_usage_path=root / "resource_usage__control.json", dispatch_plan_path=plan,
                )
        self.assertIn("$outputs+=@($caseResourceUsage.Values|Where-Object{$_-ne$resourceUsage})", source)
        self.assertIn("single_transport_case_not_all_run_cases", source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is required")
    def test_transport_snapshots_include_host_runtime_dependency_closure(self) -> None:
        expected = {
            "common/host_execution_lease.ps1", "common/host_resource_scheduler.py",
            "common/host_resource_policy.json", "common/require_powershell7.ps1",
        }
        for runner_name in ("run_finite_3d_transport.ps1", RUNNER.name):
            source = (RUNNER.parent / runner_name).read_text(encoding="utf-8-sig")
            capacity = source[source.index("$hostRuntimeSourcePaths="):source.index("$package=New-RunPackage")]
            freeze = source[source.index("  $codeRoot=Join-Path $inputDir 'code'"):source.index("  $manifestRepoRoot=$codeRoot")]
            with self.subTest(runner=runner_name), tempfile.TemporaryDirectory() as directory:
                root = _short_windows_path(Path(directory))
                def quoted(path: Path) -> str:
                    return "'" + str(path).replace("'", "''") + "'"
                script = (
                    f"$ErrorActionPreference='Stop'\n$repoRoot={quoted(REPO_ROOT)}\n"
                    f"$inputDir={quoted(root)}\n"
                    f". {quoted(REPO_ROOT / 'common/contracts/run_artifact_support.ps1')}\n"
                    + capacity + "\n" + freeze
                    + f"\n$executionCapacityPaths | ConvertTo-Json | Set-Content {quoted(root / 'capacity.json')}\n"
                    + ". (Join-Path $codeRoot 'common/host_execution_lease.ps1')\n"
                    + "$null = Get-HostResourceBudget -Role GATE -Stage snapshot-probe\n"
                )
                completed = subprocess.run(
                    [shutil.which("pwsh"), "-NoProfile", "-Command", script],
                    cwd=root, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=45, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                records = json.loads((root / "code_inventory.json").read_text(encoding="utf-8-sig"))["files"]
                by_path = {record["path"]: record for record in records}
                capacities = json.loads((root / "capacity.json").read_text(encoding="utf-8-sig"))
                for relative in expected:
                    payload = root / "code" / relative
                    self.assertIn("inputs/code/" + relative, capacities)
                    self.assertEqual(payload.read_bytes(), (REPO_ROOT / relative).read_bytes())
                    self.assertEqual(hashlib.sha256(payload.read_bytes()).hexdigest().upper(), by_path[relative]["sha256"])
                imports = "from common.host_resource_scheduler import load_policy; assert load_policy()"
                if "simion" in runner_name:
                    imports += "; from common.simion import resource_scheduler; assert resource_scheduler.CPU_ADMISSION_PERCENT > 0"
                probe = subprocess.run(
                    [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(root / 'code')!r}); " + imports],
                    cwd=root, capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_frozen_comsol_runner_receives_resolved_python_environment(self) -> None:
        source = (RUNNER.parent / "run_finite_3d_transport.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$environmentNames=@('SIMULATION_PYTHON_EXE'", source)
        self.assertIn("$env:SIMULATION_PYTHON_EXE=$python", source)
        self.assertLess(source.index("$env:SIMULATION_PYTHON_EXE=$python"), source.index("$solverProcess=Invoke-ResourceBudgetedProcess"))
        self.assertIn("Restore-RunEnvironment -Names $environmentNames -Snapshot $oldEnvironment", source)

    def test_runner_freezes_resolved_campaign_selection_before_solver_launch(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$ResolvedRuntimeProfilePath=''", source)
        self.assertIn(
            "Campaign transport requires the resolved runtime-profile snapshot.",
            source,
        )
        self.assertIn("resolved_runtime_profile.json", source)
        self.assertIn("campaign_sha256=[string]$campaignSelection.sha256", source)
        self.assertLess(
            source.index("Campaign authority changed before it was frozen."),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_source_model_comparison_can_require_an_existing_pa_basis(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$paBasisRequireExisting", source)
        self.assertIn("SIMION_PA_BASIS_CACHE_REQUIRED", source)
        self.assertLess(
            source.index("SIMION_PA_BASIS_CACHE_REQUIRED"),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_runner_freezes_terminal_authority_and_consumes_resolved_snapshot(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "downstream_terminal_profiles.json",
            "common.multipole.downstream_terminal",
            "Downstream-terminal registry changed before it was frozen.",
            "Frozen resolved design differs from the resolved runtime snapshot.",
            "Resolved runtime-profile design identity is invalid.",
            "$design.axial_dc",
            "$design.downstream_terminal.surface_plane_z_mm",
            "handoff_aperture={shape=",
            "radius_mm=$([double]$terminalAperture.radius_mm)",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("Resolved runtime-profile design identity is invalid."),
            source.index("common.multipole.simion_geometry"),
        )

    def test_default_run_ids_delimit_the_design_profile_variable(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (RUNNER.parent / name).read_text(encoding="utf-8-sig")
            self.assertIn("$($DesignProfileId.Replace('_','-'))__resolved-l3", source)
            self.assertNotIn("$DesignProfileId__resolved-l3", source)

    def test_shared_host_lease_reports_one_manifest_bound_terminal_outcome(self) -> None:
        for runner_name, role, successful_manifests in (
            ("run_simion_finite_3d_transport.ps1", "SIMION", 1),
            ("run_finite_3d_transport.ps1", "COMSOL", 3),
        ):
            source = (RUNNER.parent / runner_name).read_text(encoding="utf-8-sig")
            self.assertIn(
                ". (Join-Path $repoRoot 'common\\host_execution_lease.ps1')",
                source,
            )
            self.assertIn(
                (f"$hostExecutionLease=Enter-HostResourceStage -Role {role} -Stage prepare -RunId $RunId"
                 if role == "SIMION" else
                 f"$hostExecutionLease=Enter-HostExecutionLease -Role {role} -Stage prepare -RunId $RunId"),
                source,
            )
            self.assertIn("$hostExecutionOutcome='failed'", source)
            self.assertEqual(
                source.count("$hostExecutionOutcome='success'"), successful_manifests,
            )
            self.assertIn(
                "$hostExecutionOutcome=if($resourceBudgetExceeded){'interrupted'}else{'failed'}",
                source,
            )
            self.assertIn(
                "Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId",
                source,
            )
            # COMSOL also returns its own light preparation grant before the
            # child launcher; that boundary carries no terminal outcome.
            self.assertEqual(source.count("Exit-HostExecutionLease"), 2 if role == "COMSOL" else 1)
            if role == "COMSOL":
                self.assertIn("Exit-HostExecutionLease -Lease $hostExecutionLease\n", source)
            self.assertEqual(source.count("Write-VerifiedRunManifest"), successful_manifests)
            self.assertLess(
                source.rindex("Write-VerifiedRunManifest"),
                source.rindex("$hostExecutionOutcome='success'"),
            )
            self.assertLess(
                source.rindex("$hostExecutionOutcome='success'"),
                source.rindex("Exit-HostExecutionLease"),
            )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_dispatch_request_does_not_replace_design_manifest_input(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("      $dispatchRequestDocument=[ordered]@"):
                       source.index("      $dispatchRequestDocument|ConvertTo-Json")]
        script = (
            "$ErrorActionPreference='Stop'; $request='design.json'; "
            "$automaticDispatch=@{field_kind='rf'}; $sourceMeta=@{particle_count=17}; "
            "$TrajectoryQuality=0; $RuntimeProfileId='fixture'; $RfStepsPerPeriod=32; "
            + block + "\n@{design_request=$request; dispatch=$dispatchRequestDocument}|ConvertTo-Json -Depth 5"
        )
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["design_request"], "design.json")
        self.assertEqual(payload["dispatch"]["particle_count"], 17)
        self.assertIn("design_request=$request", source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_control_launches_all_batches_after_retaining_primary_first_worker(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    if($null-eq$dispatchPlan-and$batchRuns.Count-eq 1-and$script:existingFormalProcessRecords.Count-eq 0)"):
                       source.index("    if($batchRuns.Count-gt 1){\n      if($script:retainedFormalBatchOutputs.ContainsKey($name))")]
        script = """
$ErrorActionPreference='Stop'
$script:calls=@()
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
 $script:calls+=@{launched=@($ProcessSpecifications|ForEach-Object{$_.scheduler_batch.index}); retained=@($ExistingProcessRecords).Count}
 return @{resource_budget_exceeded=$false;processes=@(@{exit_code=0})}
}
$simion='unused';$solverDir='.';$logDir='.';$resourceUsage='unused';$runDir='.';$dispatchPlan='unused';$rfDriveKernelLua='unused'
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(1,2|ForEach-Object{@{batch=@{index=$_;particle_id_min=$_;particle_id_max=$_};lua_config='unused';fly2='unused'}})
$script:existingFormalProcessRecords=@(@{name='primary-first'})
""" + "\nforeach($name in @('primary','control')){\n" + block + "\n}\nConvertTo-Json -InputObject $script:calls -Depth 6"
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            {"launched": [2], "retained": 1}, {"launched": [1, 2], "retained": 0},
        ])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_single_dispatch_waits_in_shared_executor_before_start(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    if($null-eq$dispatchPlan-and$batchRuns.Count-eq 1"):
                       source.index("    if($batchRuns.Count-gt 1){\n      if($script:retainedFormalBatchOutputs.ContainsKey($name))")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan",
                "estimation": {"kind": "exact_resource_profile",
                               "per_process_memory_budget_bytes": 64 * 1024**2,
                               "memory_safety_factor": 1.1},
                "limits": {"maximum_concurrency": 1, "launch_stagger_seconds": 5,
                           "memory_critical_seconds": 15, "memory_recovery_stable_seconds": 45,
                           "maximum_memory_recovery_attempts": 2,
                           "maximum_memory_danger_termination_attempts": 2,
                           "memory_admission_reserve_bytes": 1024**3,
                           "memory_critical_reserve_bytes": 512 * 1024**2,
                           "cpu_admission_percent": 95},
            }), encoding="utf-8")
            def quoted(path: Path) -> str:
                return "'" + str(path).replace("'", "''") + "'"
            script = (
                f". {quoted(REPO_ROOT / 'common/multipole/resource_budget_support.ps1')}\n"
                f"$runDir={quoted(root)};$logDir=$runDir;$solverDir=$runDir;"
                f"$resourceUsage={quoted(root / 'usage.json')};$dispatchPlan={quoted(dispatch)};"
                + """
function Assert-HostResourceHeavyStage {}
function Invoke-SimionStep {throw 'single-dispatch-bypassed-wave'}
function Get-SystemCpuPercent {return [double]0}
$script:memorySamples=0
function Get-RepositoryAvailableMemoryBytes {
 $script:memorySamples++
 if($script:memorySamples-le2){return [int64](1GB)}
 return [int64](4GB)
}
$script:startWorker=${function:Start-RepositoryScheduledProcess}
function Start-RepositoryScheduledProcess {
 param($Specification)
 if($script:memorySamples-lt3){throw 'worker-started-before-memory-recovery'}
 $Specification.argument_list=@('-NoProfile','-Command','Start-Sleep -Milliseconds 200')
 & $script:startWorker -Specification $Specification
}
$simion=(Get-Process -Id $PID).Path;$name='primary';$rfDriveKernelLua='unused'
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(@{batch=@{index=1;particle_id_min=1;particle_id_max=1};lua_config='unused';fly2='unused'})
$script:existingFormalProcessRecords=@()
""" + block + """
$receipt=Get-Content -Raw $resourceUsage|ConvertFrom-Json
$pauses=@($receipt.scheduler_receipt.launch_pause_events|Where-Object {$_.reason-eq'available_memory_below_dynamic_admission'})
if($pauses.Count-lt1-or$wave.processes.Count-ne1-or$wave.processes[0].exit_code-ne0){throw 'missing-wait-or-completion'}
"""
            )
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                    cwd=REPO_ROOT, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_refine_returns_same_facade_grant_to_light_after_terminal_step(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("    $hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage pa_refine")
        end = source.index("    if($paBasisReuseAuthorized){", start)
        block = source[start:end]
        facade = REPO_ROOT / "common/host_execution_lease.ps1"
        for scenario in ("success", "failure", "inherited_light"):
            with self.subTest(scenario=scenario):
                script = f". '{facade}'\n$scenario='{scenario}'\n" + r'''
$script:events=@();$script:heavy=$false;$script:terminal=$false
$hostExecutionLease=@{token='same-token';role='SIMION';stage='prepare';state_path='unused';
    inherited=($scenario-eq'inherited_light');status='acquired';reason=''}
function Invoke-HostResourceTransaction {
 param($StatePath,$Request)
 if($Request.token-ne'same-token'){throw 'token-changed'}
 if($Request.operation-eq'inherit'){
   if($Request.ContainsKey('budget')-and$Request.budget.heavy_stage-and-not$script:heavy){throw 'inherited-light-cannot-upgrade'}
   if($Request.ContainsKey('require_heavy_stage')-and-not$script:heavy){throw 'solver-without-heavy'}
   return @{}
 }
 if($Request.operation-ne'transition'){throw 'unexpected-operation'}
 if($Request.stage-eq'prepare'-and-not$script:terminal){throw 'released-before-terminal'}
 $script:heavy=[bool]$Request.budget.heavy_stage
 $script:events+="transition:$($Request.stage):$($script:heavy)"
 return @{status='acquired';reason=''}
}
function Invoke-SimionStep($name,$arguments){
 Assert-HostResourceHeavyStage -Lease $hostExecutionLease
 $script:events+="solver:$name"
 $script:terminal=$true
 if($scenario-eq'failure'){throw 'refine-fixture-failure'}
}
$caught=''
try {
''' + block + r'''
} catch {$caught=$_.Exception.Message}
if($scenario-eq'inherited_light'){
 if($caught-ne'inherited-light-cannot-upgrade'-or$script:events.Count-ne0){throw 'inherited-upgrade-bypassed'}
}else{
 if(($script:events-join',')-ne'transition:pa_refine:True,solver:refine,transition:prepare:False'){throw 'wrong-boundaries'}
 if($script:heavy-or$hostExecutionLease.stage-ne'prepare'){throw 'heavy-permission-not-returned'}
 if($scenario-eq'failure'-and$caught-ne'refine-fixture-failure'){throw 'failure-swallowed'}
 if($scenario-eq'success'-and$caught){throw $caught}
}
'''
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                        cwd=REPO_ROOT, capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 0, repr(result.stdout) + repr(result.stderr))

    def test_simion_refine_and_flight_are_the_explicit_heavy_stages(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertEqual(source.count("Enter-HostResourceStage -Role SIMION"), 1)
        self.assertEqual(source.count("Update-HostResourceStage -Lease $hostExecutionLease"), 4)
        self.assertLess(source.index("-Stage prepare -RunId"), source.index("  $codeRoot=Join-Path"))
        self.assertLess(source.index("-Stage flight `"), source.index("$primary=Invoke-TransportCase"))
        self.assertLess(source.rindex("$control=Invoke-TransportCase"), source.index("-Stage postprocess `"))
        policy = json.loads((REPO_ROOT / "common/host_resource_policy.json").read_text(encoding="utf-8"))
        for stage in ("pa_refine", "flight"):
            self.assertTrue(policy["profiles"][policy["stages"]["SIMION/" + stage]]["heavy_stage"])
        self.assertNotIn("SIMION/prepare", policy["stages"])
        self.assertFalse(policy["profiles"][policy["stages"]["SIMION/postprocess"]]["heavy_stage"])

    def test_segmented_voltage_binding_uses_resolved_dynamic_electrodes(self) -> None:
        lua = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("adj_elect[electrode_id] = voltage", lua)
        self.assertIn("electrode_id <= 1000", lua)
        self.assertIn("$design.segmentation.segmented_rod_array", runner)
        self.assertIn("zero_axial_drop_rf_on", runner)
        self.assertNotIn("--segmented-rods", runner)

    def test_segmented_rf_program_collapses_shared_pa_electrodes(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$electrodesById=[ordered]@{}", runner)
        self.assertIn("$electrodesById.Contains($electrodeId)", runner)
        self.assertIn("$electrodesById[[object]$electrodeId]", runner)
        self.assertIn(
            "Segmented RF electrode $electrodeId has inconsistent group or common-mode voltage.",
            runner,
        )
        self.assertIn("$electrodesById.Values|Sort-Object electrode_id", runner)

    def test_pa_basis_delegates_to_the_common_content_addressed_cache(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        for token in (
            "common.simion.pa_family_cache",
            "--action',$Operation",
            "-Operation ensure -IdentityPath $paBasisIdentityPath",
            "-Operation publish -IdentityPath $paBasisIdentityPath",
            "-Operation materialize -IdentityPath $paBasisIdentityPath",
            "'probe','ensure','publish','materialize'",
            "Assert-MultipolePaBasisNames",
            "SIMION GEM must declare exactly one PA surface mode.",
            "if($paSurface-eq'fractional'){$paBasisNames=@('quad_monolithic.pa-surf')+$paBasisNames}",
        ):
            self.assertIn(token, runner)
        self.assertNotIn("function Get-VerifiedPaBasisFiles", runner)
        self.assertNotIn("function Get-TextSha256", runner)
        self.assertNotIn("Remove-Item -LiteralPath $paBasisCacheDir", runner)
        self.assertNotIn("-ItemType HardLink", runner)
        self.assertLess(
            runner.index("Invoke-CommonPaFamilyCache -Operation materialize"),
            runner.index("Invoke-SimionStep 'build_runtime_iob'"),
        )

    def test_volume_source_skips_planar_phase_reserialization(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$hasVolumeSnapshotReceipt=", runner)
        self.assertEqual(
            runner.count("-not$hasVolumeSnapshotReceipt-and$resolvedRuntimeDocument"),
            2,
        )
        self.assertIn("Re-serializing it through the planar phase matcher", runner)

    def test_build_and_fly_are_serialized_without_nested_reentry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        watchdog = (RUNNER.parent / "resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Invoke-ResourceBudgetedProcess", source)
        self.assertIn("Start-Process @startArguments", watchdog)
        self.assertIn("$record.process.WaitForExit", watchdog)
        self.assertIn("Start-Sleep -Milliseconds 500", source)
        self.assertIn("'--nogui','--noprompt','fly'", source)
        self.assertNotIn("simion_run_fly.lua", source)

    def test_default_dispatch_retains_first_formal_batch_before_parallel_replan(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        discover = "common.simion.resource_profile discover"
        schedule = "common.simion.resource_scheduler"
        publish = "common.simion.resource_profile publish"
        self.assertIn(discover, source)
        self.assertIn("--profiles $resourceProfiles", source)
        self.assertIn(publish, source)
        self.assertLess(source.index(discover), source.index(schedule))
        self.assertLess(source.index("Complete-ResourceUsage"), source.index(publish))
        self.assertIn("formal_first_batch_observation", source)
        self.assertIn("$automaticDispatch=[pscustomobject]@{kind='automatic';field_kind='rf';independent_particles=$true}", source)
        self.assertIn("Start-ObservedFormalProcess", source)
        self.assertIn("--observed-formal-peak-bytes", source)
        self.assertIn("--first-batch-completed", source)
        self.assertIn("$retainedFormalBatchOutputs", source)
        self.assertIn("retained first formal", source)
        self.assertIn("shared $($merge.property) CSV is incomplete", source)
        self.assertNotIn("RESOURCE_CALIBRATION_ONLY", source)
        self.assertIn("& $python @batchArguments | Out-Null", source)
        self.assertNotIn("maximum_process_tree_working_set_bytes=[int64]", source)
        self.assertNotIn("$request[$name]=[int]$automaticDispatch.$name", source)

    def test_scheduler_rejects_reused_process_ids(self) -> None:
        support = (RUNNER.parent / "resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("TrackedProcessStartedAtUtcTicks", support)
        self.assertIn("tracked_process_started_at_utc_ticks", support)
        self.assertIn("$staleProcessIds", support)

    def test_governed_profile_is_the_only_physical_entry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in ("ProjectId", "DesignProfileId", "ParticleSourcePath"):
            self.assertIn(token, source)
        for legacy in (
            "ProjectRoot",
            "ResolvedDesignPath",
            "ParticleMassAmu",
            "Adapter",
            "FieldScreenRunId",
            "AxialAccelerationContractPath",
            "EntranceConnectorLengthMm",
            "ExitConnectorLengthMm",
            "EndplateAcceleration",
        ):
            self.assertNotIn(legacy, source)
        self.assertIn("common.multipole.design_profile", source)
        self.assertIn("common.multipole.compile_design_request", source)
        self.assertIn("common.multipole.particle_source_preflight", source)

    def test_typed_mode_is_forwarded_to_both_solver_compilers(self) -> None:
        for runner_name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (RUNNER.parent / runner_name).read_text(encoding="utf-8")
            self.assertIn("$profile.profile.mode_id", source)
            self.assertIn("$profile.paths.operating_mode_registry", source)
            self.assertIn("--operating-mode-registry", source)
            self.assertIn("--mode-id", source)
            self.assertIn("operating_mode_registry=$modeRegistry", source)
            self.assertIn("operating_mode_id=$modeId", source)

    def test_tool_paths_are_numerical_runtime_parameters(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        template_support = (
            RUNNER.parent / "simion_layout_template_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[string]$SimionExe", source)
        self.assertNotIn("TemplateIob", source)
        self.assertIn(
            "common\\multipole\\simion_layout_template_support.ps1", source
        )
        self.assertIn("Resolve-MultipoleSimionLayoutTemplate", source)
        self.assertIn("common.multipole.simion_layout_template", template_support)
        self.assertIn("build_simion_runtime_iob.lua", source)
        self.assertIn("simion_layout_template_registry", source)
        self.assertIn("simion_layout_template_con", source)
        self.assertNotIn("C:\\Program Files\\SIMION-2020", source)

    def test_manifest_lifecycle_preserves_partial_outputs(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        support = (
            REPO_ROOT / "common/contracts/run_artifact_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertIn("Get-ChildItem -LiteralPath $directory -Recurse -File", support)
        self.assertIn("Write-VerifiedRunManifest", support)
        for output in (
            'simion_summary__$primaryName.json',
            'simion_summary__$controlName.json',
            'particle_states__$primaryName.csv',
            'particle_states__$controlName.csv',
            'trajectory_samples__$primaryName.csv',
            'trajectory_samples__$controlName.csv',
        ):
            self.assertIn(output, source)

    def test_census_and_handoff_are_exact_resolved_projections(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$interfaces.exit.handoff_plane_z_mm", source)
        self.assertIn("$interfaces.exit.census_plane_z_mm", source)
        self.assertIn("handoff_plane_mm=$handoffPlaneMm", source)
        self.assertIn("census_plane_mm=$censusPlaneMm", source)
        self.assertIn("numerical_census_marker_is_handoff=false", source)
        self.assertIn(
            "$surfaceToleranceMm=[Math]::Max(1e-6*$resolvedCellMmZ,1e-9)",
            source,
        )
        self.assertIn(
            "$censusPlaneMm-2*$resolvedCellMmZ-$surfaceToleranceMm",
            source,
        )
        program = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        self.assertIn("census_plane_mm = assert(run_config.census_plane_mm)", program)
        self.assertIn(
            "project_state_to_plane(handoff_state[particle], census_plane_mm)",
            program,
        )

    def test_gem_z_spacing_maps_to_the_flight_axis_controls(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("DefaultParameterSetName='IsotropicCell'", source)
        for axis in ("X", "Y", "Z"):
            self.assertIn(
                f"ParameterSetName='AnisotropicCell')]\n"
                f"  [ValidateScript({{[double]::IsFinite($_) -and $_ -gt 0}})][double]$CellMm{axis}",
                source,
            )
            self.assertIn(f"--cell-mm-{axis.lower()} $resolvedCellMm{axis}", source)
        self.assertIn("trajectory_plane_step_mm=$resolvedCellMmZ", source)
        self.assertIn('axial_axis="x"', source)
        self.assertIn("maps GEM +z to flight +x", source)

    def test_runner_accepts_small_positive_and_large_exploration_numerics(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        parameter_block = source[: source.index(")\n\nSet-StrictMode")] + ")\n'BOUND'\n"
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "parameter_probe.ps1"
            probe.write_text(parameter_block, encoding="utf-8")
            result = subprocess.run(
                [
                    "pwsh", "-NoProfile", "-NonInteractive", "-File", str(probe),
                    "-ProjectId", "probe", "-RuntimeProfileId", "probe",
                    "-DesignProfileId", "probe", "-ParticleSourcePath", "probe",
                    "-EngineeringBudgetPath", "probe", "-CellMm", "0.000001",
                    "-MaximumTimeUs", "0.000001", "-TrajectoryQuality", "10001",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOUND", result.stdout)

    def test_solver_numerics_artifact_excludes_dispatch_control(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("simion_execution_batch_plan.json", source)
        self.assertNotIn("solverNumericsDocument.execution_batching", source)

    def test_final_run_id_is_always_forwarded_to_budget_authorization(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("$runIdWasExplicit", source)
        self.assertIn("$budgetArguments+=@('--run-id',$RunId)", source)
        self.assertIn("authorized_run_id", source)
        self.assertLess(
            source.index("authorized_run_id"),
            source.index("New-RunPackage"),
        )

    def test_pa_grid_budget_is_audited_before_simion_starts(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "Get-SimionPaGridAudit",
            "maximum_pa_grid_points",
            "simion_grid_audit.json",
            "multipole_simion_pa_grid_audit",
            "SIMION PA grid point budget exceeded",
        ):
            self.assertIn(token, source)
        audit = source.index(
            "$gridAuditDocument=Get-SimionPaGridAudit -GemPath $gem"
        )
        persisted = source.index(
            "Set-Content -LiteralPath $gridAudit -Encoding UTF8",
            audit,
        )
        rejected = source.index("if($gridAuditDocument.status-eq'FAIL')", persisted)
        simion_start = source.index("Invoke-SimionStep 'gem2pa'")
        self.assertLess(audit, persisted)
        self.assertLess(persisted, rejected)
        self.assertLess(rejected, simion_start)
        self.assertIn("simion_grid_audit=$gridAudit", source)

    def test_pa_grid_budget_accepts_below_cap_and_rejects_over_cap(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("function Get-SimionPaGridAudit")
        end = source.index("\nfunction Invoke-CommonPaFamilyCache", start)
        audit_function = source[start:end]
        with tempfile.TemporaryDirectory() as directory:
            gem = Path(directory) / "anisotropic.gem"
            gem.write_text(
                "pa_define(101, 41, 51, planar, non-mirrored)\n",
                encoding="ascii",
            )

            def audit(maximum: int | None) -> dict:
                maximum_argument = "$null" if maximum is None else str(maximum)
                command = (
                    f"{audit_function}\n"
                    f"Get-SimionPaGridAudit -GemPath '{gem}' "
                    f"-MaximumPaGridPoints {maximum_argument} | "
                    "ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    [
                        "pwsh",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            grid_points = 101 * 41 * 51
            below_cap = audit(grid_points + 1)
            self.assertEqual(below_cap["status"], "PASS")
            self.assertEqual(below_cap["grid_points"], grid_points)
            self.assertEqual(
                below_cap["maximum_pa_grid_points"],
                grid_points + 1,
            )
            over_cap = audit(grid_points - 1)
            self.assertEqual(over_cap["status"], "FAIL")
            self.assertEqual(over_cap["grid_points"], grid_points)
            unconfigured = audit(None)
            self.assertEqual(unconfigured["status"], "NOT_CONFIGURED")
            self.assertIsNone(unconfigured["maximum_pa_grid_points"])

    def test_rejected_handoff_writes_a_unique_terminal_event(self) -> None:
        program = (REPO_ROOT / "common" / "multipole" / "simion_transport.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "write_particle_state(ion_number, 'terminal', 'lost', "
            "'acceptance_aperture', handoff)",
            program,
        )
        self.assertIn("inside_handoff_aperture(handoff)", program)
        self.assertIn("handoff_aperture.radius_mm", program)
        self.assertIn("terminal_written[ion_number] = true", program)
        self.assertIn("if terminal_written[particle] then return end", program)
        self.assertIn(
            "if previous_state[particle] then "
            "finalize_particle(particle, previous_state[particle]) end",
            program,
        )

    def test_raw_and_paired_transmission_cannot_diverge(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        metrics = (RUNNER.parent / "analyze_simion_transport_metrics.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("common.multipole.analyze_simion_transport_metrics", source)
        self.assertIn("def _handoff_transmission", metrics)
        self.assertIn('row["event"] == "handoff"', metrics)
        self.assertNotIn("Import-Csv", source)

    def test_waveform_and_all_drive_scalars_come_from_resolved_design(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        lua = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        for field in (
            "waveform",
            "rf_amplitude_V_zero_to_peak_per_group",
            "dc_amplitude_V_per_group",
            "common_mode_offset_V",
            "frequency_Hz",
            "phase_rad",
        ):
            self.assertIn(field, source)
        self.assertIn("transport_waveform == 'sine'", lua)
        self.assertIn("transport_waveform == 'cosine'", lua)
        kernel = (RUNNER.parent / "simion_rf_drive.lua").read_text(encoding="utf-8")
        self.assertIn("RF drive waveform must be sine or cosine", kernel)
        self.assertIn("config.waveform == 'sine' and math.sin or math.cos", kernel)

    def test_mechanically_segmented_rods_always_receive_full_length_rf(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        comsol = (RUNNER.parent / "solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "$segmentedRodGeometry=($null-ne$design.segmentation.segmented_rod_array)",
            source,
        )
        self.assertIn("if($segmentedRodGeometry){", source)
        self.assertIn(
            "$segmented=($axialTopology-eq'segmented_rod_axial_acceleration')",
            source,
        )
        self.assertIn(
            "segmentedRodGeometry = isfield(design.segmentation,'segmented_rod_array');",
            comsol,
        )
        self.assertIn("if segmentedRodGeometry", comsol)
        self.assertIn(
            "segmentedAccelerationEnabled = strcmp("
            "axialTopology,'segmented_rod_axial_acceleration');",
            comsol,
        )

    def test_metrics_are_unqualified_without_explicit_evidence(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$qualification='UNQUALIFIED'", source)
        self.assertIn("evaluate_transport_evidence", source)
        self.assertIn("analyze_simion_axial_acceleration", source)
        self.assertIn("common.multipole.analyze_simion_transport_metrics", source)
        self.assertNotIn("function ConvertTo-TransportMetricCase", source)
        self.assertNotIn("MinimumRfTransmission", source)
        self.assertNotIn("MinimumImprovementOverZeroRf", source)

    def test_validator_output_is_not_returned_as_case_data(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("--output $stateReport|Out-Null", source)
        self.assertIn("return Get-Content -LiteralPath $caseSummary", source)

    def test_reference_comsol_run_is_verified_before_simion(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "common.contracts.verify_run_manifest",
            "--require-status success",
            "--require-local-run-config",
            "--require-run-id $ReferenceComsolRunId",
            "--require-project $ProjectId",
            "--require-mode resolved_design_transport",
            "--require-design-profile-id $DesignProfileId",
            "--require-parent-resolved-design-sha256 $resolvedHash",
            "--require-particle-source-sha256",
            "reference_comsol_run_manifest.json",
            "reference_comsol_run_manifest_sha256",
            "reference_comsol_source_run_id",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("common.contracts.verify_run_manifest"),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_project_wrappers_are_thin_profile_consumers(self) -> None:
        projects = (
            "rf_quadrupole_ion_optics",
            "rf_hexapole_ion_optics",
            "rf_octupole_ion_optics",
        )
        for project in projects:
            project_root = REPO_ROOT / "projects" / project
            wrapper_path = (
                project_root
                / "workflows"
                / "no_collision_transport"
                / "run_simion.ps1"
                if project == "rf_quadrupole_ion_optics"
                else project_root / "analysis" / "run_simion_finite_3d_transport.ps1"
            )
            wrapper = wrapper_path.read_text(encoding="utf-8-sig")
            self.assertIn("RuntimeProfileId", wrapper)
            if project == "rf_quadrupole_ion_optics":
                self.assertNotIn("DesignProfileId", wrapper)
                self.assertNotIn("ParticleSourcePath", wrapper)
                self.assertIn("project_transport_launcher_support.ps1", wrapper)
            else:
                self.assertNotIn("DesignProfileId", wrapper)
                self.assertNotIn("ParticleSourcePath", wrapper)
                self.assertIn("project_transport_launcher_support.ps1", wrapper)
            self.assertNotIn("FieldScreenRunId", wrapper)
            self.assertNotIn("AxialAccelerationContractPath", wrapper)

    def test_5ev_projection_requires_and_consumes_explicit_operating_point(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$sourceProjectionArguments", runner)
        self.assertIn("--expected-source-family-sha256", runner)
        self.assertGreaterEqual(runner.count("--source-family"), 2)
        self.assertGreaterEqual(runner.count("--operating-point"), 2)
        project = REPO_ROOT / "projects" / "rf_quadrupole_ion_optics"
        resolved_path = project / "config" / "resolved_design_official.json"
        family_path = project / "config" / "interface_readiness_particle_source.json"
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        speed = math.sqrt(
            2.0 * 5.0 * ELEMENTARY_CHARGE_C / (100.0 * AMU_KG)
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=COLUMNS, lineterminator="\n"
                )
                writer.writeheader()
                for particle_id in range(1, 101):
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "birth_time_s": "0",
                            "x_mm": "0",
                            "y_mm": "0",
                            "z_mm": resolved["interfaces_mm"]["entrance"][
                                "release_plane_z_mm"
                            ],
                            "vx_m_s": "0",
                            "vy_m_s": "0",
                            "vz_m_s": format(speed, ".17g"),
                            "mass_amu": "100",
                            "charge_state": "1",
                        }
                    )
            with self.assertRaisesRegex(
                ValueError, "resolved closed interval"
            ):
                render_canonical_source(source, resolved_path)
            fly, states, count = render_canonical_source(
                source,
                resolved_path,
                source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(
                    family_path.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(count, 100)
            self.assertIn("ke=5", fly)
            self.assertIn("ke=5", states)
            with self.assertRaisesRegex(ValueError, "requires both"):
                render_canonical_source(
                    source,
                    resolved_path,
                    source_family_path=family_path,
                )
            with self.assertRaisesRegex(ValueError, "differs from the frozen"):
                render_canonical_source(
                    source,
                    resolved_path,
                    source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256="0" * 64,
                )

            class DriftingSourceFamily:
                def __init__(self) -> None:
                    self.read_count = 0

                def read_bytes(self) -> bytes:
                    self.read_count += 1
                    return (
                        family_path.read_bytes()
                        if self.read_count == 1
                        else b'{"schema_version":1,"operating_points":{}}'
                    )

            drifting_family = DriftingSourceFamily()
            _, _, drift_count = render_canonical_source(
                source,
                resolved_path,
                source_family_path=drifting_family,  # type: ignore[arg-type]
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(
                    family_path.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(drift_count, 100)
            self.assertEqual(drifting_family.read_count, 1)

            fly, states, count = render_canonical_source(
                source, resolved_path, source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                particle_id_min=21, particle_id_max=40,
            )
            self.assertEqual(count, 20)
            self.assertIn("[21]", states)
            self.assertIn("[40]", states)
            self.assertNotIn("[20]", states)
            self.assertEqual(fly.count("standard_beam"), 20)
            _, local_states, _ = render_canonical_source(
                source, resolved_path, source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                particle_id_min=21, particle_id_max=40, simion_particle_id_offset=20,
            )
            self.assertIn("[1]", local_states)
            self.assertIn("[20]", local_states)
            self.assertNotIn("[21]", local_states)
            with self.assertRaisesRegex(ValueError, "offset exceeds"):
                render_canonical_source(
                    source, resolved_path, source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                    particle_id_min=21, particle_id_max=40, simion_particle_id_offset=21,
                )
            with self.assertRaisesRegex(ValueError, "batch interval"):
                render_canonical_source(
                    source, resolved_path, source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                    particle_id_min=1,
                )

    def test_primary_only_case_set_skips_control_and_records_null_control(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('primary_and_zero_axial_control','primary_and_rf_off_energy_control','primary_only')]",
            runner,
        )
        self.assertIn("if($CaseSet-eq'primary_and_zero_axial_control')", runner)
        self.assertIn("elseif($CaseSet-eq'primary_and_rf_off_energy_control')", runner)
        self.assertIn("$control=Invoke-TransportCase $controlName 0 1", runner)
        self.assertIn("--metric-kind rf_off_energy_control", runner)
        self.assertIn("case_set=$CaseSet", runner)

    def test_parallel_batching_is_single_wave_and_revalidates_the_merged_state(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        support = (RUNNER.parent / "resource_budget_support.ps1").read_text(encoding="utf-8")
        self.assertIn("common.simion.particle_batching", runner)
        self.assertIn("SIMION shared single-wave batch plan differs from the canonical source.", runner)
        self.assertIn("--particle-id-min", runner)
        self.assertIn("Invoke-ResourceBudgetedProcesses", runner)
        self.assertIn("SIMION shared single-wave batch plan", runner)
        self.assertIn("SIMION $name particle-state contract failed.", runner)
        self.assertIn("--merge-rebase-csv", runner)
        self.assertIn("--merge-summaries", runner)
        self.assertIn(
            "'--observed-formal-peak-bytes',([string]$formalObservation.observed_peak_process_tree_working_set_bytes)",
            runner,
        )
        self.assertIn(
            "--from-dispatch-plan $dispatchPlan",
            runner,
        )
        self.assertNotIn("Add-Content -LiteralPath $caseState", runner)
        self.assertIn("Get-ProcessTreeWorkingSetBytes", support)
        self.assertIn("execution_wave", support)
        self.assertIn("$control=$null;$controlName=$null", runner)
        self.assertIn(
            "Primary-only SIMION runs cannot consume a paired-case evidence contract.",
            runner,
        )
        self.assertIn("--metric-kind primary", runner)
        self.assertIn("$controlTransmission=$null", runner)
        self.assertIn('"simion_summary__$primaryName.json"', runner)
        self.assertIn("Primary SIMION case did not produce a transmission.", runner)
        self.assertIn("if($CaseSet-ne'primary_only')", runner)
        self.assertIn(
            "Paired SIMION case set did not produce a control transmission.", runner
        )


if __name__ == "__main__":
    unittest.main()
