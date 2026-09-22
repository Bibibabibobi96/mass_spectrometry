from __future__ import annotations

import json
import re
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RUNNER = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runtime"
    / "run_single_flight.ps1"
)
ADAPTER = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "workflows"
    / "family_source_closure"
    / "adapter.ps1"
)


class DomainSplitRunnerContractTests(unittest.TestCase):
    """Keep the long-gap PA family on its governed, non-superposed path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8")
        cls.adapter_source = ADAPTER.read_text(encoding="utf-8")

    def test_host_phases_cover_hidden_refiners_and_keep_observed_waves_together(self) -> None:
        stages = list(re.finditer(r"\$hostExecutionLease = Update-HostResourceStage .*?-Stage (\w+)", self.source))
        def active_stage(offset: int) -> str:
            return next((m[1] for m in reversed(stages) if m.start() < offset), "prepare")
        for variable in ("basisInitialization", "paPlusInitialization", "localPaPlusInitialization",
                         "overlayBuild", "flightTubeBuild", "reflectronBuild", "singleRefine",
                         "fineRefineWave", "localRefineWave", "overlayRefineWave", "refineWave"):
            with self.subTest(variable=variable):
                self.assertEqual(active_stage(self.source.index(f"${variable} = Invoke-")), "pa_refine")
        begin = self.source.index("$formalObservation = Start-ObservedFormalProcess")
        end = self.source.index("$waveResult = Invoke-ResourceBudgetedProcesses", begin)
        self.assertFalse(any(begin < m.start() < end for m in stages))
        for prefix in ("fine", "local", "overlay"):
            self.assertIn(f"${prefix}RefineWave = Invoke-RfObservedRefineWave", self.source)
        self.assertEqual(active_stage(self.source.index("$formalObservation = Start-ObservedFormalProcess")), "flight")
        self.assertIn("if ($processSpecifications.Count -gt 0) {\n    $hostExecutionLease = Update-HostResourceStage", self.source)
        self.assertIn("Enter-HostExecutionLease -Role SIMION -Stage prepare", self.source)
        self.assertEqual(active_stage(self.source.index("$axisFieldResult = Invoke-ResourceBudgetedProcess")), "prepare")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_refine_wave_observation_handoff(self) -> None:
        start = self.source.index("function Invoke-RfObservedRefineWave {")
        end = self.source.index("function Resolve-RfNativeOperatingPaCompanion", start)
        function = self.source[start:end]
        for observed, completed, callback, peak in (
            (False, False, False, 100),
            (True, False, True, 100),
            (True, True, False, 100),
            (True, True, True, 0),
        ):
            with self.subTest(observed=observed, completed=completed, callback=callback, peak=peak):
                script = function + "\n" + r'''
$ErrorActionPreference = 'Stop'
$script:kind = 'INITIAL_KIND'
$script:arguments = @()
function Get-Content { param($LiteralPath, [switch]$Raw, $Encoding)
    return (@{estimation=@{kind=$script:kind}} | ConvertTo-Json)
}
function Start-ObservedFormalProcess { param($DispatchPlanPath, $ProcessSpecification)
    if ($ProcessSpecification.id -ne 1) { throw 'wrong observation item' }
    return @{observed_peak_process_tree_working_set_bytes=PEAK;
        available_memory_bytes=1000; total_physical_memory_bytes=2000;
        observed_process_cpu_percent=50; observed_background_cpu_percent=5;
        completed_naturally=COMPLETED; process_record=@{id=1}}
}
function Invoke-SingleFlightPython { param($Arguments, $Failure)
    $script:arguments = $Arguments
    $script:kind = 'observed_formal_batch'
    Write-Output 'RESOURCE_SCHEDULER=PASS'
    Write-Output 'RESOURCE_DISPATCH=OBSERVED'
}
function Out-Host { process {} }
function Invoke-ResourceBudgetedProcesses {
    param($DispatchPlanPath, $RunDir, $UsagePath, $ProcessSpecifications,
        $ExistingProcessRecords, $OnProcessCompleted)
    return @{ids=@($ProcessSpecifications | ForEach-Object {$_.id});
        records=@($ExistingProcessRecords | ForEach-Object {$_.id});
        callback=($null -ne $OnProcessCompleted); arguments=$script:arguments}
}
$options = @{}
CALLBACK
try {
    Invoke-RfObservedRefineWave -DispatchRequest request -DispatchPlan plan -RunDir run `
      -UsagePath usage -Specifications @(@{id=1},@{id=2}) @options | ConvertTo-Json -Depth 8
} catch { @{error=$_.Exception.Message} | ConvertTo-Json }
'''
                script = (script.replace("INITIAL_KIND", "formal_first_batch_observation" if observed else "cached")
                          .replace("PEAK", str(peak))
                          .replace("COMPLETED", "$true" if completed else "$false")
                          .replace("CALLBACK", "$options.OnProcessCompleted = {}" if callback else ""))
                result = subprocess.run(
                    [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                    capture_output=True, text=True, timeout=30, cwd=REPO,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                if not peak:
                    self.assertIn("usable resource observation", payload["error"])
                    continue
                self.assertEqual(payload["ids"], [2] if observed else [1, 2])
                self.assertEqual(payload["records"], [1] if observed else [])
                self.assertEqual(payload["callback"], callback)
                self.assertEqual("--first-batch-completed" in payload["arguments"], observed and completed)
                self.assertEqual("--observed-formal-peak-bytes" in payload["arguments"], observed)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_extracted_host_boundaries_use_one_private_token_and_reject_light_parent_upgrade(self) -> None:
        commands = re.findall(
            r"(?m)^ *\$hostExecutionLease = Update-HostResourceStage[^\n]+\n *-Budget[^\n]+", self.source)
        sequence = []
        for stage in ("pa_refine", "prepare", "flight", "postprocess"):
            sequence.append(next(command for command in commands if f"-Stage {stage} `" in command))
        def quote(path: Path) -> str:
            return "'" + str(path).replace("'", "''") + "'"
        with tempfile.TemporaryDirectory(prefix="integration_host_phases_") as directory:
            script = (
                f"$env:SIMULATION_PYTHON_EXE={quote(Path(sys.executable))};"
                "$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='';"
                f"$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH={quote(Path(directory)/'host.sqlite3')};"
                f". {quote(REPO/'common/host_execution_lease.ps1')};"
                "function Get-HostResourceSnapshot {return @{complete=$true;observed_at_ticks=[DateTime]::UtcNow.Ticks;"
                "logical_processors=8;cpu_percent=0;total_memory_bytes=32GB;available_memory_bytes=24GB;io_pressure=$false;"
                "processes=@(@{pid=$PID;parent_pid=0;started='0000000000000000001';memory_bytes=64MB})}};"
                "$hostExecutionLease=Enter-HostExecutionLease -Role SIMION -Stage prepare;"
                "$token=$hostExecutionLease.token;try {\n"
                + "\n".join(sequence)
                + "\nif($hostExecutionLease.token-ne$token){throw 'token changed'};"
                "Assert-HostResourceHeavyStage -Lease $hostExecutionLease"
                "}catch{if($_.Exception.Message-notmatch 'heavy stage'){throw}}"
                "finally{Exit-HostExecutionLease -Lease $hostExecutionLease};"
                "$parent=Enter-HostExecutionLease -Role SIMION -Stage prepare;"
                "try{$hostExecutionLease=Enter-HostExecutionLease -Role SIMION -Stage prepare;"
                "$rejected=$false;try{\n" + sequence[0]
                + "\n}catch{if($_.Exception.Message-notmatch 'heavy stage'){throw};$rejected=$true};"
                "if(-not$rejected){throw 'light parent upgraded'};Exit-HostExecutionLease -Lease $hostExecutionLease"
                "}finally{Exit-HostExecutionLease -Lease $parent};"
                "if(@((Get-HostResourceStatus -StatePath $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH).records).Count){throw 'leaked'}"
            )
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _run_refine_receipt_functions(self, body: str) -> object:
        start = self.source.index("function Write-RfAtomicJsonFile {")
        end = self.source.index("function Get-RfSingleFlightParticleLines", start)
        script = self.source[start:end] + "\n" + body
        completed = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=REPO,
        )
        return json.loads(completed.stdout)

    def test_runner_derives_radii_from_frozen_geometry_without_scalar_duplicates(self) -> None:
        self.assertIn("architecture generation identity differs", self.source)
        for parameter in (
            "ExpectedBoreRadiusMm",
            "ExpectedRingOuterRadiusMm",
            "ExpectedShieldInnerRadiusMm",
        ):
            self.assertNotIn(parameter, self.source)
            self.assertNotIn(parameter, self.adapter_source)

    def test_long_gap_derives_its_endpoint_extent_from_the_connection_contract(self) -> None:
        self.assertIn("function Resolve-RfPositiveGapDomainSplit", self.source)
        self.assertIn("upstream_fine_extent_mm", self.source)
        self.assertIn("accelerator_fine_extent_mm", self.source)
        self.assertNotIn("$upstreamExtentMm = 10.0", self.source)
        self.assertNotIn("$minimumSplitGapMm = 50.0", self.source)
        self.assertIn("coarse_sleeve_length_mm=($gapMm - $terminalThicknessMm - $upstreamExtentMm - $acceleratorExtentMm)", self.source)
        self.assertIn("if ($gapMm -le ($terminalThicknessMm + $upstreamExtentMm + $acceleratorExtentMm))", self.source)
        self.assertIn("fine_domain_overlap_prohibited=$true", self.source)
        self.assertIn("upstream_fine_extent_mm=$upstreamExtentMm", self.source)

    def test_zero_and_short_positive_gaps_remain_on_integrated_path(self) -> None:
        self.assertIn("mode='integrated_frontend'; reason='direct_mating_gap_zero'", self.source)
        self.assertIn(
            "mode='integrated_frontend'; reason='connection_domain_split_not_declared'",
            self.source,
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required for runner behavior")
    def test_runner_reserves_both_connector_end_extents(self) -> None:
        start = self.source.index("function Resolve-RfPositiveGapDomainSplit {")
        end = self.source.index("$hasThreeZoneCandidate =", start)
        function = self.source[start:end]
        cases = [
            {"connector": {"length_mm": gap, "upstream_fine_extent_mm": 10.0,
                           "accelerator_fine_extent_mm": 10.0}}
            for gap in (0.0, 10.0, 24.0, 24.1, 102.4)
        ]
        script = function + "\n$cases = '" + json.dumps(cases) + "' | ConvertFrom-Json\n"
        script += "$upstream = [pscustomobject]@{downstream_terminal=[pscustomobject]@{electrode_thickness_mm=4.0}}\n"
        script += "@($cases | ForEach-Object { Resolve-RfPositiveGapDomainSplit -ResolvedConnection $_ -ResolvedUpstream $upstream }) | ConvertTo-Json -Depth 8"
        completed = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, check=True, timeout=30, cwd=REPO,
        )
        resolved = json.loads(completed.stdout)
        self.assertEqual([row["mode"] for row in resolved[:3]], ["integrated_frontend"] * 3)
        self.assertEqual(resolved[3]["mode"], "domain_split")
        self.assertAlmostEqual(resolved[3]["coarse_sleeve_length_mm"], 0.1)
        self.assertEqual(resolved[4]["mode"], "domain_split")
        self.assertAlmostEqual(resolved[4]["coarse_sleeve_length_mm"], 78.4)

    def test_long_gap_builds_governed_split_pa_and_iob_path(self) -> None:
        self.assertIn("mode='domain_split'; reason='connector_fits_disjoint_fine_domains'", self.source)
        self.assertIn("field_superposition_prohibited=$true", self.source)
        self.assertIn("domain_split_runtime_contract.json", self.source)
        self.assertIn("--upstream-bridge-contract", self.source)
        self.assertIn("--accelerator-main-contract", self.source)
        self.assertIn("build_single_flight_full_iob.lua", self.source)
        self.assertIn("coarse_electrode_basis_dirichlet_v1", self.source)

    def test_detector_blind_pre_pulse_uses_only_the_reachable_iob_roles(self) -> None:
        self.assertIn("$prePulseEntranceZoneCollision = [bool](", self.source)
        self.assertIn("$sourceReleaseMode -eq 'continuous_frontend'", self.source)
        self.assertIn("$prePulseTerminalHandoffCollision", self.source)
        self.assertIn("$prePulseReachableIob = $prePulseEntranceZoneCollision", self.source)
        self.assertIn("if (-not $prePulseReachableIob) {", self.source)
        self.assertIn("build_single_flight_pre_pulse_iob.lua", self.source)
        self.assertIn("common\\simion\\assets\\iob_instance_seeds", self.source)
        self.assertIn("4_instance_seed.iob", self.source)
        self.assertIn("$prePulseFourInstanceSeed", self.source)
        self.assertNotIn("examples\\sims", self.source)
        self.assertIn("Versioned four-instance pre-pulse IOB seed", self.source)
        self.assertIn("Compact pre-pulse IOB build failed.", self.source)
        self.assertIn(
            "'fine_upstream,accelerator_main,accelerator_entrance_local'",
            self.source,
        )
        self.assertIn("accelerator_main_pa_cache_manifest.json", self.source)
        self.assertIn("accelerator_entrance_local_pa_cache_manifest.json", self.source)
        self.assertIn("pre_pulse_iob_omitted_roles", self.source)
        self.assertIn(
            "$paCacheDispositions.accelerator_entrance_local.disposition = 'pending_cache_decision'",
            self.source,
        )
        self.assertIn(
            "$paCacheDispositions.flight_tube.disposition = 'not_applicable'",
            self.source,
        )
        self.assertIn(
            "$paCacheDispositions.reflectron.disposition = 'not_applicable'",
            self.source,
        )

    def test_pre_pulse_iob_preserves_full_flight_overlap_priority(self) -> None:
        start = self.source.index("$prePulseIobArguments = @(")
        end = self.source.index("$built = Invoke-ResourceBudgetedProcess", start)
        arguments = self.source[start:end]
        ordered_tokens = [
            "$(if($standaloneFieldBearingRuntime){$frontendWorkingPa0}else{Join-Path $runtimeDir 'coarse_frontend.pa0'})",
            "$domainMain[0].pa0",
            "$domainUpstream[0].pa0",
            "$entranceLocalBuild[0].pa0",
            "$frontendBoundaryGeometry.instance_origin_mm.x",
            "$frontendBoundaryGeometry.instance_origin_mm.y",
            "$frontendBoundaryGeometry.instance_origin_mm.z",
            "$domainMain[0].geometry.instance_origin_mm.x",
            "$domainMain[0].geometry.instance_origin_mm.y",
            "$domainMain[0].geometry.instance_origin_mm.z",
            "$domainUpstream[0].geometry.instance_origin_mm.x",
            "$domainUpstream[0].geometry.instance_origin_mm.y",
            "$domainUpstream[0].geometry.instance_origin_mm.z",
            "$entranceLocalBuild[0].geometry.instance_origin_mm.x",
            "$entranceLocalBuild[0].geometry.instance_origin_mm.y",
            "$entranceLocalBuild[0].geometry.instance_origin_mm.z",
        ]
        for left, right in zip(ordered_tokens, ordered_tokens[1:]):
            self.assertLess(arguments.index(left), arguments.index(right))

    def test_full_flight_iob_arguments_match_the_seven_slot_builder_contract(self) -> None:
        start = self.source.index("$fullFlightIobArguments = @(")
        end = self.source.index("$built = Invoke-ResourceBudgetedProcess", start)
        arguments = self.source[start:end]
        # The full builder API receives reusable families as coarse/upstream/main,
        # then maps them to priority slots 2/4/3 respectively.  Keep its four
        # dynamic origins paired to the same API role order.
        ordered_tokens = [
            "$coarseFrontendRuntimePa0",
            "$domainUpstream[0].pa0",
            "$acceleratorMainRuntimePa0",
            "(Join-Path $runtimeDir 'flight_tube_ground.pa0')",
            "(Join-Path $runtimeDir 'reflectron.pa0')",
            "$entranceLocalBuild[0].pa0",
            "(Join-Path $runtimeDir 'detector_ground.pa0')",
            "$frontendGeometry.instance_origin_mm.x",
            "$frontendGeometry.instance_origin_mm.y",
            "$frontendGeometry.instance_origin_mm.z",
            "$domainUpstream[0].geometry.instance_origin_mm.x",
            "$domainUpstream[0].geometry.instance_origin_mm.y",
            "$domainUpstream[0].geometry.instance_origin_mm.z",
            "$domainMain[0].geometry.instance_origin_mm.x",
            "$domainMain[0].geometry.instance_origin_mm.y",
            "$domainMain[0].geometry.instance_origin_mm.z",
            "$entranceLocalBuild[0].geometry.instance_origin_mm.x",
            "$entranceLocalBuild[0].geometry.instance_origin_mm.y",
            "$entranceLocalBuild[0].geometry.instance_origin_mm.z",
        ]
        for left, right in zip(ordered_tokens, ordered_tokens[1:]):
            self.assertLess(arguments.index(left), arguments.index(right))

    def test_detector_blind_pre_pulse_reuses_full_flight_coarse_and_upstream_families(self) -> None:
        self.assertNotIn("pre_pulse_coarse_bridge", self.source)
        self.assertNotIn("pre_pulse_upstream_bridge", self.source)
        self.assertNotIn("--pre-pulse-compact-basis-contract", self.source)
        self.assertIn("$frontendCacheGem = $frontendGem", self.source)
        self.assertIn("gem=$upstreamBridgeGem", self.source)
        self.assertIn("contract=$upstreamBridgeContract", self.source)
        self.assertIn(
            "the already-refined accelerator-main family", self.source
        )

    def test_pre_pulse_native_grid_honors_the_frozen_sampling_stride(self) -> None:
        self.assertIn("$sampleStrideRfSteps = if ($null -eq $rfGrid.sample_stride_rf_steps)", self.source)
        self.assertIn("$index * $sampleStrideRfSteps", self.source)

    def test_zero_field_geometry_is_limited_to_terminal_handoff_collision(self) -> None:
        self.assertIn("if ($domainSplitEnabled -and $prePulseTerminalHandoffCollision)", self.source)
        self.assertIn("Build-RawPrePulseCollisionPa", self.source)
        self.assertNotIn("$entranceZoneGeometry", self.source)

    def test_domain_split_prohibits_monolithic_accelerator_override(self) -> None:
        self.assertIn("if ($domainSplitEnabled)", self.source)
        self.assertIn("OATOF_ACCELERATOR_PA_OVERRIDE", self.source)

    def test_domain_split_axis_field_export_does_not_pass_monolithic_override(self) -> None:
        self.assertIn("$axisFieldEnvironment = @{", self.source)
        self.assertIn("if (-not $domainSplitEnabled) {", self.source)
        self.assertIn(
            "$axisFieldEnvironment.OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0",
            self.source,
        )
        self.assertIn("-Environment $axisFieldEnvironment", self.source)

    def test_main_pa_only_axis_field_gate_uses_a_real_five_slot_container(self) -> None:
        self.assertIn("$domainSplitMainPaOnlyAxisField", self.source)
        self.assertIn("build_single_flight_domain_split_main_only_iob.lua", self.source)
        self.assertIn("mag_quad_2dp.iob", self.source)
        self.assertIn("domain_split_iob_instance_count", self.source)
        self.assertIn("domain_split_iob_omitted_roles", self.source)
        self.assertIn("--domain-split-main-pa-only-axis-field", self.source)
        self.assertIn("-not $domainSplitMainPaOnlyAxisField -and $domainProgramOverlay.Count", self.source)

    def test_local_axis_field_skips_upstream_but_keeps_the_coarse_dirichlet_source(self) -> None:
        self.assertIn("if (-not $postPulseHandoffMinimal -and -not $domainSplitLocalAxisField)", self.source)
        self.assertIn(
            "'full_coarse_bridge','accelerator_main','accelerator_entrance_local'",
            self.source,
        )
        self.assertIn("$paCacheDispositions.fine_upstream", self.source)
        local_axis = self.source[
            self.source.index("} elseif ($domainSplitLocalAxisField) {"):
            self.source.index("} elseif ($postPulseHandoffMinimal) {", self.source.index("} elseif ($domainSplitLocalAxisField) {"))
        ]
        self.assertIn("$domainMain.Count -ne 1 -or $entranceLocalBuild.Count -ne 1", local_axis)
        self.assertNotIn("upstream_bridge", local_axis)
        self.assertIn("$domainSplitLocalAxisField -or $postPulseHandoffMinimal) { 5 }", self.source)
        omitted = self.source[
            self.source.index("$runConfiguration.parameters.domain_split_iob_omitted_roles"):
            self.source.index("$runConfiguration.parameters.post_pulse_handoff_minimal_iob", self.source.index("$runConfiguration.parameters.domain_split_iob_omitted_roles"))
        ]
        self.assertIn("@('coarse_frontend','upstream_bridge')", omitted)

    def test_coarse_frontend_refines_fast_adjust_template_once_for_fine_boundaries(self) -> None:
        self.assertIn("refine_mode='pa_plus_official_default_single_refine_v2'", self.source)
        self.assertIn("initialize_fast_adjust_pa_basis.lua", self.source)
        self.assertIn("Coarse frontend PA+ file rendering failed.", self.source)
        self.assertIn("-Prefix 'frontend'", self.source)
        self.assertIn("SIMION refines every member of a fast-adjust .pa# family", self.source)
        self.assertNotIn("frontend_refine_pa{0}_resource_usage.json", self.source)

    def test_frontend_staging_is_recoverable_under_the_parent_capacity_session(self) -> None:
        self.assertIn("-RecoveryCacheKey $frontendCacheKey", self.source)
        self.assertIn("simion_single_flight_frontend_pa_refinement", self.source)
        self.assertIn("$frontendCapacityScope = Update-ArtifactWorkflowCapacitySession", self.source)
        self.assertIn("-ProtectedPaths @($frontendBuildDir)", self.source)
        self.assertIn("-ProtectedCacheKeys @($frontendCacheKey)", self.source)
        self.assertNotIn("$frontendProjectedFamilyBytes", self.source)

    def test_pa_refinement_uses_simion_official_default_convergence(self) -> None:
        self.assertIn("refinement_convergence='simion_official_default'", self.source)
        self.assertNotIn("'5e-7'", self.source)
        self.assertNotIn("'initialize_fast_adjust_pa_basis.lua','frontend.pa#','1e6'", self.source)
        self.assertNotIn("$cacheBasisInitializer,$cachePaSharp,'1e6'", self.source)

    def test_new_pa_plus_generation_requires_the_eight_mode_field_loading_identity(self) -> None:
        self.assertIn(
            "three_zone_linear_ring_octupole_symmetry_pa_plus_v2", self.source
        )
        self.assertIn("octupole_common_differential_pa_plus_v2", self.source)
        self.assertIn("$localSolutionIds.Count -ne 8", self.source)

    def test_fine_pa_basis_refinement_uses_the_shared_independent_work_scheduler(self) -> None:
        self.assertIn("$fineRefineDispatchRequest", self.source)
        self.assertIn("$fineRefineDispatchPlan", self.source)
        self.assertIn("$fineRefineResourceUsage", self.source)
        self.assertIn("independent_work_items=$true", self.source)
        self.assertIn("Start-ObservedFormalProcess", self.source)
        self.assertIn("Invoke-ResourceBudgetedProcesses", self.source)
        self.assertIn("$fineRefineWave", self.source)

    def test_completed_fine_refinement_is_receipted_for_cache_publication_recovery(self) -> None:
        self.assertIn("$fineRefinementReceipt", self.source)
        self.assertIn("simion_single_flight_fine_pa_refinement", self.source)
        self.assertIn("basis_build_sha256", self.source)
        self.assertIn("if (-not $fineRefinementComplete)", self.source)

    def test_local_pa_basis_refinement_uses_the_shared_independent_work_scheduler(self) -> None:
        self.assertIn("$localRefineDispatchRequest", self.source)
        self.assertIn("$localRefineDispatchPlan", self.source)
        self.assertIn("$localRefineResourceUsage", self.source)
        self.assertIn("$localRefineWave", self.source)
        self.assertIn("Accelerator entrance-local refinement dispatch plan is invalid.", self.source)

    def test_interrupted_local_pa_staging_is_identity_bound_and_recoverable(self) -> None:
        self.assertIn(
            "-RecoveryCacheKey $localKey -RecoveryRole $localRole", self.source
        )
        self.assertIn("$localBasisComplete", self.source)
        self.assertIn("$localRefinementReceipt", self.source)
        self.assertIn(
            "simion_single_flight_accelerator_entrance_local_pa_refinement",
            self.source,
        )
        self.assertIn("$recoverableLocalStaging", self.source)
        local_catch = self.source[
            self.source.index("$recoverableLocalStaging"):
            self.source.index("throw", self.source.index("$recoverableLocalStaging"))
        ]
        self.assertIn("(Join-Path $localBuildDir 'basis_build.json')", local_catch)
        self.assertIn("-not $recoverableLocalStaging", local_catch)

    def test_local_pa_plus_family_materializes_its_controller_before_basis_transfer(self) -> None:
        self.assertIn("pa_plus_initializer_sha256=(Get-FileHash -LiteralPath $paPlusInitializerSource", self.source)
        self.assertIn("$localPa0 = Join-Path $localBuildDir 'accelerator_entrance_local.pa0'", self.source)
        self.assertIn("$localPaPlusInitialization = Invoke-ResourceBudgetedProcess", self.source)
        self.assertIn("Accelerator entrance-local PA+ controller initialization failed.", self.source)

    def test_local_basis_uses_only_a_short_verified_main_standalone_projection(self) -> None:
        self.assertNotIn("New-RfSimionShortPathJunction", self.source)
        self.assertNotIn("-ItemType Junction", self.source)
        local_basis_block = self.source[
            self.source.index("$basis = Invoke-ResourceBudgetedProcess", self.source.index("$localPaPlusInitialization")):
            self.source.index("$localRefinementReceipt", self.source.index("$localPaPlusInitialization"))
        ]
        self.assertIn("$localBoundaryProjection.mode_map", local_basis_block)
        self.assertNotIn("common.simion.cache_generation", local_basis_block)
        self.assertNotIn("accelerator_main.pa0", local_basis_block)
        self.assertNotIn(".paN", local_basis_block)

    def test_post_pulse_materializes_only_the_main_and_local_accelerator_families(self) -> None:
        self.assertIn(
            "if (-not $postPulseHandoffMinimal -and -not $domainSplitLocalAxisField)",
            self.source,
        )
        self.assertIn("$domainSplitRuntimeBuilds = if ($postPulseHandoffMinimal)", self.source)
        self.assertIn("@('accelerator_main','accelerator_entrance_local')", self.source)
        self.assertIn("foreach ($domainSplitFineBuild in $domainSplitRuntimeBuilds)", self.source)
        self.assertNotIn(
            "Post-pulse handoff requires an existing shared accelerator-main PA cache",
            self.source,
        )

    def test_domain_split_uses_declared_coarse_bridge_grid_only_for_frontend(self) -> None:
        self.assertIn("$executionProfile.coarse_bridge_cell_mm_xyz", self.source)
        self.assertIn("Positive-gap domain split requires a coarse-bridge grid declaration.", self.source)
        self.assertIn("Domain-split coarse frontend PA grid differs from the declared coarse-bridge grid.", self.source)
        self.assertIn("$additionalFrontendGem", self.source)
        self.assertIn("$additionalFrontendContract", self.source)
        self.assertIn("'--partition-cell-mm-x',([string]$frontendCellMmX)", self.source)
        self.assertNotIn("'--partition-cell-mm-x','0.25'", self.source)

    def test_empty_cache_miss_is_not_used_as_a_filesystem_path(self) -> None:
        self.assertIn("if (-not [string]::IsNullOrWhiteSpace($cacheDir))", self.source)
        self.assertIn(
            "if (-not [string]::IsNullOrWhiteSpace($cacheDir) -and @($requiredFrontendBasisFiles",
            self.source,
        )

    def test_intermediate_overlay_uses_full_envelope_coarse_frontend_basis(self) -> None:
        self.assertIn("$basisSourcePa0 = $frontendWorkingPa0", self.source)
        self.assertIn("$basisSourceKey = $frontendCacheKey", self.source)
        self.assertIn("$basisSourceOrigin = $frontendGeometry.instance_origin_mm", self.source)
        self.assertIn("full accelerator cross-section", self.source)
        self.assertNotIn("$basisSourceWorkingDirectory = Join-Path $overlayBuildDir 'basis_source'", self.source)
        self.assertNotIn("-Filter 'accelerator_main.pa*' -File", self.source)

    def test_domain_pa_cache_copy_helper_is_defined_before_its_first_use(self) -> None:
        definition = self.source.index("function Copy-RfPaCacheFamilyToRuntime")
        first_domain_copy = self.source.index("foreach ($domainSplitFineBuild in $domainSplitFineBuilds)")
        self.assertLess(definition, first_domain_copy)

    def test_flight_binding_reuses_each_already_frozen_fine_manifest(self) -> None:
        start = self.source.index("$domainSplitFineCacheManifestInputs = @()")
        end = self.source.index("$twoLocalOverlayCacheManifestInputs = @()", start)
        binding = self.source[start:end]
        self.assertIn("path=$domainSplitFineBuild.cache_manifest_input", binding)
        self.assertNotIn("path=(Copy-RfCacheManifestInput", binding)

    def test_native_operating_field_bank_uses_program_contract_identity(self) -> None:
        self.assertIn(
            "role='rf_oatof_simion_standalone_dynamic_field_bank'", self.source
        )
        self.assertNotIn("role='rf_oatof_standalone_dynamic_field_bank'", self.source)

    def test_parent_workflow_owns_one_capacity_session_without_startup_maintenance(self) -> None:
        budget = self.source.index("$stageBudgetDocument = Get-Content")
        enter = self.source.index("Enter-ArtifactWorkflowCapacitySession", budget)
        self.assertLess(budget, enter)
        self.assertIn(
            "-CommittedNewBytes ([int64]$stageBudgetDocument.limits.transient_run_directory_bytes)",
            self.source[enter:enter + 900],
        )
        self.assertNotIn("reconcile_interrupted_compact_runs", self.source)
        self.assertNotIn("Test-RepositoryDiskCapacity", self.source)
        self.assertNotIn("Invoke-ArtifactCapacityGate", self.source)

    def test_capacity_session_has_no_legacy_measurement_or_raw_budget_path(self) -> None:
        self.assertNotIn("$artifactCapacityState", self.source)
        self.assertNotIn("KnownMeasuredBytes", self.source)
        self.assertNotIn("MaximumNewArtifactBytes", self.source)
        self.assertNotIn("TargetGiB", self.source)
        self.assertNotIn("MinimumFreeGiB", self.source)
        self.assertIn("Complete-RfArtifactCapacityCommitment", self.source)
        self.assertIn("Exit-ArtifactWorkflowCapacitySession", self.source)

    def test_domain_split_aperture_check_uses_the_authoritative_local_or_main_pa(self) -> None:
        self.assertIn("Domain-split aperture topology check requires exactly one authoritative aperture PA.", self.source)
        self.assertIn("{'accelerator_entrance_local'} else {'accelerator_main'}", self.source)
        self.assertIn("Refine-materialized `.pa0` controller", self.source)
        self.assertIn("$geometryPa0 = Join-Path $runtimeDir ($prefix + '.pa0')", self.source)
        self.assertIn("PA+ cache family is missing its Refine-materialized controller", self.source)
        self.assertIn("-NotePropertyName topology_pa", self.source)
        self.assertIn("$apertureTopologyPa = [string]$domainApertureProvider[0].topology_pa", self.source)
        self.assertIn("$apertureTopologyGeometry.accelerator_port_aperture.discretization", self.source)
        self.assertIn(
            "$apertureWidthMm = [double]$apertureTopologyDiscretization.mechanical_width_mm",
            self.source,
        )
        self.assertIn(
            "$apertureHeightMm = [double]$apertureTopologyDiscretization.mechanical_height_mm",
            self.source,
        )
        self.assertIn("-PaPath $apertureTopologyPa", self.source)

    def test_pre_pulse_iob_reuses_the_materialized_main_pa0(self) -> None:
        self.assertIn("the already-refined accelerator-main PA", self.source)
        self.assertIn("$domainMain[0].pa0", self.source)
        self.assertIn(
            "$_.name -in @('upstream_bridge','accelerator_main','accelerator_entrance_local')",
            self.source,
        )
        self.assertIn("if ($acceleratorEntranceLocalEnabled) {'accelerator_entrance_local'}", self.source)
        self.assertNotIn(
            "$programArguments += @('--pre-pulse-entrance-zone-collision-contract'",
            self.source,
        )

    def test_early_failure_receipt_cannot_mask_the_original_launch_error(self) -> None:
        self.assertIn("$stdoutFiles = @()", self.source)
        self.assertIn("$stderrFiles = @()", self.source)
        self.assertIn("$materializerStdout = $null", self.source)
        self.assertIn("$materializerStderr = $null", self.source)
        topology_block = self.source[
            self.source.index("$topologyPa = if ("):
            self.source.index("$domainSplitFineBuild | Add-Member", self.source.index("$topologyPa = if ("))
        ]
        self.assertIn("$domainSplitFineBuild.pa0", topology_block)

    def test_shared_main_local_aperture_profile_is_connected_end_to_end(self) -> None:
        self.assertIn("--coarse-bridge-reference-aperture-width-mm", self.source)
        self.assertIn("--accelerator-main-reference-aperture-width-mm", self.source)
        self.assertIn("--accelerator-entrance-local-gem", self.source)
        self.assertIn("accelerator_main_electrode_basis_dirichlet_v1", self.source)
        self.assertIn("replacement_semantics='highest_priority_complete_local_replacement_v1'", self.source)
        self.assertIn("build_single_flight_full_iob.lua", self.source)
        self.assertIn("common\\simion\\assets\\iob_instance_seeds", self.source)
        self.assertIn("5_instance_seed.iob", self.source)
        self.assertIn("7_instance_seed.iob", self.source)
        self.assertIn("$domainSplitLocalAxisField", self.source)
        self.assertIn("local-axis-field IOB builder", self.source)
        self.assertIn("--domain-split-local-axis-field", self.source)
        self.assertIn("--accelerator-entrance-local-contract", self.source)
        self.assertIn("--accelerator-entrance-local-aperture-width-mm", self.source)
        self.assertIn("$AcceleratorEntranceLocalApertureHeightMm", self.source)
        self.assertIn("$runConfiguration.parameters.accelerator_intermediate2_provider", self.source)
        self.assertIn("if ($domainSplitEnabled) { 'accelerator_main' }", self.source)
        self.assertIn("$postPulseHandoffMinimal", self.source)
        self.assertIn("build_single_flight_post_pulse_iob.lua", self.source)
        self.assertIn("validate_post_pulse_handoff_envelope.py", self.source)
        self.assertIn("Post-pulse handoff states are not covered by the reduced IOB.", self.source)
        self.assertIn("@('coarse_frontend','upstream_bridge')", self.source)
        self.assertIn(
            "requires the entrance-local replacement PA for every field-bearing flight",
            self.source,
        )
        self.assertIn(
            "requires an explicit local replacement aperture", self.source
        )

    def test_pre_pulse_scans_do_not_multiply_the_shared_coarse_bridge_cache(self) -> None:
        start = self.source.index("$coarseBridgeReferenceAperture =")
        end = self.source.index("$frontendCompileArguments += @(\n      '--upstream-bridge-gem'", start)
        aperture_block = self.source[start:end]
        self.assertIn(
            "$coarseBridgeReferenceAperture = $executionProfile.accelerator_main_reference_aperture_mm",
            aperture_block,
        )
        self.assertIn(
            "--coarse-bridge-reference-aperture-width-mm',([string]$coarseBridgeReferenceAperture.width)",
            aperture_block,
        )
        self.assertIn(
            "--accelerator-main-reference-aperture-width-mm',([string]$acceleratorMainCompileAperture.width)",
            self.source,
        )

    def test_domain_split_iob_aliases_coarse_frontend_from_its_materialized_family(self) -> None:
        self.assertIn("[string]$SourceDirectory=$runtimeDir", self.source)
        self.assertIn("-SourceDirectory $frontendWorkingDir", self.source)

    def test_standalone_runtime_materializes_prepublication_operating_cache(self) -> None:
        copy_assignment = self.source.index("$frontendWorkingDir = Join-Path")
        copy_guard = self.source.rindex(
            "if (-not $standaloneFieldBearingRuntime)", 0, copy_assignment
        )
        frontend_copy = self.source[
            copy_guard : self.source.index("# A positive long gap")
        ]
        self.assertIn("if (-not $standaloneFieldBearingRuntime)", frontend_copy)
        dynamic = self.source[
            self.source.index("if ($standaloneFieldBearingRuntime) {") : self.source.index(
                "$reflectronBuilderFrozen = $null"
            )
        ]
        self.assertIn("--action','materialize'", dynamic)
        self.assertIn("$roleRow.build.operating_companion", dynamic)
        self.assertIn("native_operating_pa_cache_manifest.json", dynamic)
        self.assertIn("$standaloneDynamicExecutionDir", dynamic)
        self.assertIn("'rf_oatof_operating_pa_'", dynamic)
        self.assertIn("'--destination-directory',$standaloneDynamicExecutionDir", dynamic)
        self.assertNotIn("New-ShortPaCopy", dynamic)
        self.assertNotIn("compose_standalone_pa.lua", dynamic)
        self.assertIn("Remove-PrivatePaFamilyDirectory", self.source)
        self.assertIn(
            "-ExpectedNamePrefix 'rf_oatof_operating_pa_'", self.source
        )
        self.assertNotIn("$fieldPlan.rf_copies", dynamic)
        self.assertIn("standalone_dynamic_operating_pa_receipt.json", dynamic)
        for name in (
            "standalone_dynamic_field_materialization_plan",
            "standalone_dynamic_field_bank",
            "standalone_dynamic_operating_pa_receipt",
            "standalone_${inputStem}_operating_cache_manifest",
            "standalone_${inputStem}_operating_identity",
        ):
            self.assertIn(name, self.source)

    def test_domain_split_program_does_not_require_the_unrelated_entrance_overlay(self) -> None:
        self.assertIn("} elseif ($overlayEnabled -and -not $domainSplitEnabled) {", self.source)

    def test_terminal_handoff_program_uses_raw_connector_contract(self) -> None:
        self.assertIn("$programUpstreamContract = if ($prePulseTerminalHandoffCollision)", self.source)
        self.assertIn("$prePulseConnectorCollisionContract", self.source)
        self.assertIn("'--upstream-bridge-contract',$programUpstreamContract", self.source)

    def test_all_fine_domains_use_the_shared_pa_plus_builder_and_namespace(self) -> None:
        self.assertIn("build_accelerator_pa_plus_basis.lua", self.source)
        self.assertIn("$fineBasisBuilderSource = $acceleratorMainBasisBuilderSource", self.source)
        self.assertIn("$fineSolutionIds = @($sharedPaPlusSolutionIds)", self.source)
        self.assertIn("$finePaPlusModeSpec = @($fineSolutionIds | ForEach-Object", self.source)
        self.assertIn("'{0}:{0}=1' -f [int]$_", self.source)
        self.assertIn(
            "$fineGeometry.PSObject.Properties['pa_plus_solution_model']",
            self.source,
        )
        self.assertNotIn(
            "$fineModel = $fineGeometry.pa_plus_solution_model", self.source
        )
        self.assertIn("'36,37,38,39,40,41,42,43'", self.source)
        self.assertIn("Test-RfPaPlusModeFamily", self.source)
        self.assertIn("$finePa0 = Join-Path $fineBuildDir", self.source)
        self.assertIn("PA+ controller initialization failed", self.source)
        self.assertIn("basis_builder_sha256=(Get-FileHash -LiteralPath $fineBasisBuilderSource", self.source)
        self.assertIn("pa_plus_initializer_sha256", self.source)
        self.assertIn("$fineBoundaryProjection.mode_map,$fineBuildSharp", self.source)

    def test_accelerator_pa_plus_builder_materializes_only_independent_modes(self) -> None:
        builder = RUNNER.with_name("build_accelerator_pa_plus_basis.lua").read_text(encoding="utf-8")
        self.assertIn("local mode_spec=assert(arg[9]", builder)
        self.assertIn("local source_arrays={}", builder)
        self.assertIn("for _,mode in ipairs(modes) do", builder)
        self.assertIn("if not exists(fine_path) then copy_file(fine_pa_sharp,fine_path) end", builder)
        self.assertNotIn("initializer:refine", builder)
        self.assertNotIn("convergence=", builder)
        self.assertIn("disjoint PA+ boundary traversal", builder)

    def test_pa_plus_boundary_builder_uses_only_disjoint_writes_and_source_projection(self) -> None:
        builder = RUNNER.with_name("build_accelerator_pa_plus_basis.lua").read_text(encoding="utf-8")
        self.assertIn("mode_spec", builder)
        self.assertIn("source:potential_vc", builder)
        self.assertIn("disjoint PA+ boundary traversal", builder)
        self.assertNotIn("fine:potential", builder)

    def test_accelerator_overlay_builder_covers_six_faces_without_duplicate_key_tracking(self) -> None:
        builder = RUNNER.with_name("build_accelerator_overlay_basis.lua").read_text(encoding="utf-8")
        self.assertNotIn("local seen={}", builder)
        self.assertNotIn("ix..':'..iy..':'..iz", builder)
        self.assertIn("for ix=1,fine.nx-2 do", builder)
        self.assertIn("for iy=1,fine.ny-2 do", builder)
        self.assertIn('"disjoint_six_faces_v1"', builder)
        self.assertIn("duplicate_boundary_writes", builder)
        self.assertNotIn("boundary_readback", builder)
        self.assertNotIn("potential(ix,iy,iz)", builder)

    def test_parent_boundary_sources_are_manifest_verified_standalone_maps(self) -> None:
        self.assertIn("function Select-RfStandalonePaResponses", self.source)
        self.assertIn("--action','select'", self.source)
        self.assertIn("--manifest',$Manifest", self.source)
        self.assertIn("--mode-map',$ModeMapPath", self.source)
        self.assertIn(
            "standalone_selection_path=$frontendStandaloneSelectionPath",
            self.source,
        )
        self.assertIn("standalone_mode_map=$frontendStandaloneModeMap", self.source)
        self.assertIn("standalone_selection_path=$fineStandaloneSelectionPath", self.source)
        self.assertIn("standalone_mode_map=$fineStandaloneModeMap", self.source)
        self.assertIn("standalone_selection_path=$localStandaloneSelectionPath", self.source)
        self.assertIn("standalone_mode_map=$localStandaloneModeMap", self.source)

    def test_boundary_builder_uses_verified_short_copies_and_always_cleans_them(self) -> None:
        helper = self.source[
            self.source.index("function New-RfStandaloneBoundarySourceProjection"):
            self.source.index("function Get-RfProcessDiagnosticTail")
        ]
        self.assertIn("New-ShortPaCopy", helper)
        self.assertIn("[Parameter(Mandatory)][string]$ExpectedPrefix", helper)
        self.assertIn("[Parameter(Mandatory)][int[]]$ExpectedResponseIds", helper)
        self.assertIn("[string]$selection.prefix -ne $ExpectedPrefix", helper)
        self.assertIn("($actualResponseIds -join ',') -ne ($ExpectedResponseIds -join ',')", helper)
        self.assertIn("-ExpectedBytes ([int64]$record.bytes)", helper)
        self.assertIn("-ExpectedSha256 ([string]$record.sha256)", helper)
        self.assertIn("simion_pa_links_", helper)
        self.assertIn("Remove-ShortPaCopyDirectory", helper)
        self.assertIn("[Text.UTF8Encoding]::new($false)", helper)
        fine_basis = self.source[
            self.source.index("$fineBoundaryProjection ="):
            self.source.index("$fineRefinementReceipt")
        ]
        self.assertIn("finally {", fine_basis)
        self.assertIn(
            "Remove-RfStandaloneBoundarySourceProjection -Projection $fineBoundaryProjection",
            fine_basis,
        )
        local_basis = self.source[
            self.source.index("$localBoundaryProjection ="):
            self.source.index("$localRefinementReceipt")
        ]
        self.assertIn("finally {", local_basis)
        self.assertIn(
            "Remove-RfStandaloneBoundarySourceProjection -Projection $localBoundaryProjection",
            local_basis,
        )

    def test_interrupted_refine_keeps_only_complete_basis_staging(self) -> None:
        self.assertNotIn("basis_build.json.basis_*.complete", self.source)
        self.assertIn("basis_build.json", self.source)
        self.assertIn("(Join-Path $fineBuildDir 'basis_build.json')", self.source)
        self.assertIn("(Join-Path $localBuildDir 'basis_build.json')", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required for runner behavior")
    def test_mode_receipt_rejects_zero_bytes_wrong_identity_and_changed_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = str(Path(directory).resolve()).replace("'", "''")
            result = self._run_refine_receipt_functions(
                f"""
$root = '{root}'
$basis = Join-Path $root 'basis_build.json'
[IO.File]::WriteAllText($basis,'basis',[Text.UTF8Encoding]::new($false))
$pa = Join-Path $root 'main.pa36'
[IO.File]::WriteAllBytes($pa,[byte[]](1,2,3,4))
$key = 'a' * 64
Write-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionId 36 `
  -BasisReport $basis -ExitCode 0 | Out-Null
$valid = Test-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionId 36 -BasisReport $basis
$wrongKey = Test-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey ('b' * 64) `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionId 36 -BasisReport $basis
$wrongRole = Test-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'local_role' -PaPrefix 'main' -SolutionId 36 -BasisReport $basis
[IO.File]::WriteAllBytes($pa,[byte[]](4,3,2,1))
$changedHash = Test-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionId 36 -BasisReport $basis
[IO.File]::WriteAllBytes($pa,[byte[]]@())
$zeroBytes = Test-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionId 36 -BasisReport $basis
[ordered]@{{valid=$valid;wrong_key=$wrongKey;wrong_role=$wrongRole;changed_hash=$changedHash;zero_bytes=$zeroBytes}} | ConvertTo-Json -Compress
"""
            )
        self.assertEqual(
            result,
            {
                "valid": True,
                "wrong_key": False,
                "wrong_role": False,
                "changed_hash": False,
                "zero_bytes": False,
            },
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required for runner behavior")
    def test_resume_state_schedules_existing_legacy_pa_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = str(Path(directory).resolve()).replace("'", "''")
            result = self._run_refine_receipt_functions(
                f"""
$root = '{root}'
$basis = Join-Path $root 'basis_build.json'
[IO.File]::WriteAllText($basis,'basis',[Text.UTF8Encoding]::new($false))
$key = 'c' * 64
[IO.File]::WriteAllBytes((Join-Path $root 'main.pa36'),[byte[]](1,2))
Write-RfPaRefineModeReceipt -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionId 36 `
  -BasisReport $basis -ExitCode 0 | Out-Null
[IO.File]::WriteAllBytes((Join-Path $root 'main.pa37'),[byte[]](9,8,7))
[IO.File]::WriteAllBytes((Join-Path $root 'main.pa38'),[byte[]]@())
$state = Get-RfPaRefineResumeState -BuildDirectory $root -CacheKey $key `
  -FamilyRole 'main_role' -PaPrefix 'main' -SolutionIds @(36,37,38,39) `
  -BasisReport $basis
$state | ConvertTo-Json -Compress
"""
            )
        self.assertEqual(result["completed_solution_ids"], [36])
        self.assertEqual(result["pending_solution_ids"], [37, 38, 39])

    def test_main_and_local_refine_resume_are_symmetric_and_pending_only(self) -> None:
        fine = self.source[
            self.source.index("$fineRefinementReceipt =") :
            self.source.index("$fineStandaloneReceipt =")
        ]
        local = self.source[
            self.source.index("$localRefinementReceipt =") :
            self.source.index("$localStandaloneReceipt =")
        ]
        for block, pending, prefix in (
            (fine, "$finePendingSolutionIds", "$fineDefinition.name"),
            (local, "$localPendingSolutionIds", "'accelerator_entrance_local'"),
        ):
            self.assertIn("Get-RfPaRefineResumeState", block)
            self.assertIn("Write-RfPaRefineModeReceipt", block)
            self.assertIn("-OnProcessCompleted", block)
            self.assertIn(f"work_item_count={pending}.Count", block)
            self.assertIn(f"@({pending} | ForEach-Object", block)
            self.assertIn("basis repair failed", block)
            self.assertIn("refinement mode receipts are incomplete", block)
            self.assertIn("schema_version=2", block)
            self.assertIn("mode_receipts=@(", block)
            self.assertIn(f"-PaPrefix {prefix}", block)

    def test_legacy_semantic_reuse_is_not_used_for_schema_three_fine_families(self) -> None:
        self.assertIn("function Resolve-RfSemanticallyEquivalentFineCache", self.source)
        fine_block = self.source[
            self.source.index("$fineIdentity = [ordered]@{"):
            self.source.index(
                "if ($acceleratorEntranceLocalEnabled)",
                self.source.index("$fineIdentity = [ordered]@{"),
            )
        ]
        self.assertIn("schema_version=3", fine_block)
        self.assertNotIn("Resolve-RfSemanticallyEquivalentFineCache", fine_block)
        self.assertNotIn("cache_hit_semantically_equivalent_boundary_builder", fine_block)

    def test_every_pa_plus_family_exports_and_receipts_standalone_modes(self) -> None:
        self.assertIn("function Export-RfStandalonePaResponses", self.source)
        self.assertIn("common\\simion\\export_standalone_pa.lua", self.source)
        self.assertIn("--action','write-receipt'", self.source)
        self.assertIn("standalone_response_set.json", self.source)
        self.assertIn('"{0}.response_{1}.pa"', self.source)
        self.assertIn("Export-RfStandalonePaResponses", self.source)
        self.assertGreaterEqual(self.source.count("Export-RfStandalonePaResponses `"), 3)
        self.assertIn("standalone_exporter_sha256", self.source)
        self.assertIn("standalone_receipt_policy_sha256", self.source)
        self.assertIn("new_pa_object_export_surface_none_v1", self.source)
        self.assertIn(
            "native_staging_plus_responses_plus_prepublication_operating_companion_v2",
            self.source,
        )
        self.assertIn("Resolve-RfNativeOperatingPaCompanion", self.source)
        self.assertIn("export_fast_adjusted_standalone_pa.lua", self.source)

    def test_operating_companions_are_synthesized_only_before_family_publication(self) -> None:
        for receipt, publication in (
            ("$frontendStandaloneReceipt =", "$cacheDir = Publish-RfVerifiedCacheEntry"),
            ("$fineStandaloneReceipt =", "$fineCacheDir = Publish-RfVerifiedCacheEntry"),
            ("$localStandaloneReceipt =", "$localCacheDir = Publish-RfVerifiedCacheEntry"),
        ):
            start = self.source.index(receipt)
            end = self.source.index(publication, start)
            block = self.source[start:end]
            self.assertIn("Resolve-RfNativeOperatingPaCompanion", block)
            self.assertIn("-AllowSynthesis", block)
        helper = self.source[
            self.source.index("function Resolve-RfNativeOperatingPaCompanion") :
            self.source.index("function Export-RfStandalonePaResponses")
        ]
        self.assertIn("if (-not $AllowSynthesis)", helper)
        self.assertIn("published PA families are forbidden synthesis sources", helper)
        self.assertIn("Add-RfArtifactCapacityProtectedCacheKey", helper)
        self.assertIn("[string]$export.receipt", helper)
        self.assertIn("'--action','verify-exports'", helper)
        self.assertIn("physical_geometry_boundary_flags_v1", helper)
        self.assertIn("verification_sha256", helper)
        self.assertIn("schema_version=2", helper)

    def test_disjoint_face_partition_is_the_same_complete_boundary_as_the_legacy_loops(self) -> None:
        # Small non-cubic dimensions exercise each edge/corner ownership rule.
        nx, ny, nz = 7, 5, 4
        legacy = {
            (ix, iy, iz)
            for iz in range(nz)
            for iy in range(ny)
            for ix in (0, nx - 1)
        }
        legacy |= {
            (ix, iy, iz)
            for iz in range(nz)
            for ix in range(nx)
            for iy in (0, ny - 1)
        }
        legacy |= {
            (ix, iy, iz)
            for iy in range(ny)
            for ix in range(nx)
            for iz in (0, nz - 1)
        }
        disjoint = {
            (ix, iy, iz)
            for iz in range(nz)
            for iy in range(ny)
            for ix in (0, nx - 1)
        }
        disjoint |= {
            (ix, iy, iz)
            for iz in range(nz)
            for ix in range(1, nx - 1)
            for iy in (0, ny - 1)
        }
        disjoint |= {
            (ix, iy, iz)
            for iy in range(1, ny - 1)
            for ix in range(1, nx - 1)
            for iz in (0, nz - 1)
        }
        self.assertEqual(disjoint, legacy)
        self.assertEqual(len(disjoint), 2 * ny * nz + 2 * (nx - 2) * nz + 2 * (nx - 2) * (ny - 2))


if __name__ == "__main__":
    unittest.main()
