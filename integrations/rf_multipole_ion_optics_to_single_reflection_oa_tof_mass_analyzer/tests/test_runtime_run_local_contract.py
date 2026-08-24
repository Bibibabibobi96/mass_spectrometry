"""Static regression tests for mandatory run-local integration inputs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from common.contracts.file_identity import repository_text_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.three_zone_runtime_identity import (
    validate_runtime_identity,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_execution_profile import (
    resolve_execution_profile,
)


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BINDING = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
WORKFLOW_ENTRY = (
    INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
)
SINGLE_FLIGHT_RUNNER = INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
PRE_PULSE_TIME_SERIES_MATERIALIZER = (
    INTEGRATION_ROOT / "runtime" / "materialize_pre_pulse_time_series.py"
)
FAMILY_RUNTIME_IMPLEMENTATION = (
    INTEGRATION_ROOT / "config" / "family_runtime_implementation.json"
)
FAMILY_ADAPTER = (
    INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
)
RUNNERS = (
    INTEGRATION_ROOT / "runtime" / "run_transfer.ps1",
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pre_pulse_interface_transport.ps1",
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pulse_capture.ps1",
    INTEGRATION_ROOT / "stages" / "cross_solver" / "run_analyzer_transport.ps1",
)


class RuntimeRunLocalContractTests(unittest.TestCase):
    def test_adapter_accepts_one_manifest_bound_pre_pulse_restart_authority(self) -> None:
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        gate = adapter.index("$restartAuthorityCount = @(")
        frozen_source_gate = adapter.index(
            "Pre-pulse restart lacks a frozen source state.", gate
        )
        self.assertLess(gate, frozen_source_gate)
        self.assertIn("'post_pulse_restart_reuse_authority'", adapter[gate - 300:gate])
        self.assertIn("if ($restartAuthorityCount -ne 1)", adapter[gate:frozen_source_gate])
        self.assertIn(
            "($usesGeneratedPrePulseSubset -or "
            "$usesManifestBoundPostPulseRestart)",
            adapter,
        )
        self.assertIn(
            "pre_pulse_restart_validation_sha256", adapter
        )

    def test_pre_pulse_time_series_is_pre_solver_fail_closed_and_gap_bound(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$PrePulseTimeSeriesContract = ''", runner)
        self.assertIn("[string]$PrePulseTimeSeriesContractSha256 = ''", runner)
        self.assertIn(
            "$PaCachePolicy -notin @('require_existing','build_and_publish_if_missing')",
            runner,
        )
        identity_gate = runner.index(
            "Pre-pulse time-series source/layout/field/PA identity differs."
        )
        solver_launch = runner.index("Invoke-ResourceBudgetedProcesses")
        self.assertLess(identity_gate, solver_launch)
        completion = runner.index("if ($isPrePulseTimeSeriesScreening) {", solver_launch)
        downstream = runner.index("analysis.analyze_single_flight")
        self.assertLess(completion, downstream)
        self.assertIn("'--adjustable','handoff_pulse_mode=2'", runner)
        self.assertIn("'--adjustable','handoff_pulse_mode=1'", runner)
        self.assertNotIn("'--adjustable','handoff_pulse_mode=0'", runner)
        self.assertIn("pre_pulse_time_series_states.csv", runner)
        self.assertIn("pre_pulse_time_series_screening_receipt.json", runner)
        self.assertIn(
            "runtime.materialize_pre_pulse_time_series", runner
        )
        for argument in (
            "--run-config",
            "--pre-pulse-time-series-contract-sha256",
            "--stdout-log",
            "--states-output",
            "--receipt-output",
            "--summary-output",
        ):
            self.assertIn(argument, runner)
        self.assertNotIn("$tracePattern", runner)
        self.assertNotIn("$rows +=", runner)
        self.assertNotIn("Export-Csv", runner)
        self.assertEqual(
            runner.count("-not $isPrePulseTimeSeriesScreening -and"), 2
        )
        self.assertIn("$null -ne $cacheKeys.flight_tube", runner)
        self.assertIn("$null -ne $cacheKeys.reflectron", runner)
        self.assertNotIn("rod_end_to_accelerator_shield_mm=1.0", runner)
        self.assertIn(
            "rod_end_to_accelerator_shield_mm=[double]$frontendGeometry."
            "junction_enclosure.rod_end_to_accelerator_shield_mm",
            runner,
        )

    def test_execution_batch_count_and_parallel_memory_gate_are_governed(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateScript({ $_ -ge 1 })][int]$ExecutionBatchCount = 1", runner
        )
        self.assertNotIn("ValidateRange(1,10000)", runner)
        self.assertIn("execution_batch_count=$ExecutionBatchCount", runner)
        self.assertIn(
            "execution_batches_parallel=[bool]($ExecutionBatchCount -gt 1 "
            "-and $maxParallelBatches -gt 1)",
            runner,
        )
        self.assertNotIn("$settings.batching_policy.default_batch_count", runner)
        self.assertNotIn("$batchCount -ne 5", runner)
        self.assertNotIn("N=1000 single flight requires five batches", runner)
        self.assertIn("common.simion.particle_batching", runner)
        self.assertIn("simion_execution_batch_plan.json", runner)
        self.assertIn("simion_single_wave_batch_plan_sha256", runner)
        self.assertNotIn("$quotient = [Math]::Floor($launched / $batchCount)", runner)
        self.assertNotIn("$remainder = $launched % $batchCount", runner)
        self.assertIn("Invoke-ResourceBudgetedProcesses", runner)
        self.assertIn("$resourceUsageFiles = @($resourceUsage)", runner)
        self.assertIn("$processSpecifications += [pscustomobject]@", runner)
        self.assertNotIn("$waveStart += $maxParallelBatches", runner)
        self.assertNotIn("$waveBatchCount -gt 1", runner)
        self.assertNotIn("$jobs += Start-Job", runner)
        batch_launch_block = runner[
            runner.index("$processSpecifications += [pscustomobject]@"):runner.index(
                "if ($isPrePulseTimeSeriesScreening) {", runner.index(
                    "$processSpecifications += [pscustomobject]@"
                )
            )
        ]
        self.assertNotIn("Invoke-ResourceBudgetedProcess `", batch_launch_block)
        self.assertNotIn("[int64](10GB)", runner)
        self.assertNotIn("[int64](4GB)", runner)
        batch_bound = runner.index(
            "Single-flight execution batch count exceeds launched particle count."
        )
        solver_launch = runner.index("Invoke-ResourceBudgetedProcesses")
        self.assertLess(batch_bound, solver_launch)

    def test_solver_stage_runners_use_short_lived_execution_aliases(self) -> None:
        for runner_path in RUNNERS[1:]:
            runner = runner_path.read_text(encoding="utf-8")
            self.assertIn("-UseShortExecutionPath", runner, runner_path)
            self.assertIn(
                "Remove-RunPackageExecutionAlias -Package $package",
                runner,
                runner_path,
            )
        single_flight = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        for relative_path in (
            "inputs/simion_five_instance_container/mag_quad_2dp.iob",
            "inputs/single_flight_mother_sample__batch999.fly2",
            "results/single_flight_accelerator_checkpoint_evolution_metadata.json",
            "simion/overlay_iob_stage/mag_quad_2dp.iob",
        ):
            self.assertIn(relative_path, single_flight)
        for runner_path, consumer_id in (
            (RUNNERS[1], "pre_pulse_interface_transport"),
            (RUNNERS[2], "pulse_capture"),
            (RUNNERS[3], "analyzer_transport"),
        ):
            runner = runner_path.read_text(encoding="utf-8")
            self.assertIn(
                "Get-RfOatofExecutionCapacityPaths -Runtime $runtime",
                runner,
                runner_path,
            )
            self.assertIn(f"-ConsumerId '{consumer_id}'", runner, runner_path)
            self.assertIn(
                "-ExpectedExecutionRelativePaths $executionCapacityPaths",
                runner,
                runner_path,
            )

    def test_pre_pulse_time_series_materializer_is_runtime_bound(self) -> None:
        registry = json.loads(
            FAMILY_RUNTIME_IMPLEMENTATION.read_text(encoding="utf-8")
        )
        record = registry["implementation"][
            "single_flight_pre_pulse_time_series_materializer"
        ]
        self.assertEqual(
            record["path"],
            "integrations/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runtime/materialize_pre_pulse_time_series.py",
        )
        self.assertEqual(
            record["sha256"],
            repository_text_sha256(PRE_PULSE_TIME_SERIES_MATERIALIZER),
        )

    def test_observed_projection_identity_is_promoted_before_solver(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        script = f"""
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  '{FAMILY_ADAPTER}', [ref]$null, [ref]$errors
)
if ($errors) {{ throw $errors[0] }}
$fn = $ast.Find({{
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Resolve-RfObservedPrePulseSourceIdentity'
}}, $true)
if ($null -eq $fn) {{ throw 'observed projection identity resolver is missing' }}
. ([scriptblock]::Create($fn.Extent.Text))
$projection = [pscustomobject]@{{
  arm_id='full_observed_6d'
  authority_manifest=[pscustomobject]@{{path='authority.json';sha256=('A' * 64)}}
}}
$experiment = [pscustomobject]@{{observed_pre_pulse_projection=$projection}}
$budgetIdentity = [pscustomobject]@{{
  run_id='source-run';observed_pre_pulse_projection=$projection
}}
$resolved = Resolve-RfObservedPrePulseSourceIdentity `
  -Experiment $experiment -BudgetSourceIdentity $budgetIdentity
if ($resolved.run_id -ne 'source-run' -or
    $resolved.observed_pre_pulse_projection.arm_id -ne 'full_observed_6d') {{
  throw 'complete budget source identity was not returned'
}}
$mismatch = [pscustomobject]@{{
  run_id='source-run'
  observed_pre_pulse_projection=[pscustomobject]@{{
    arm_id='observed_z_vz_energy_transverse_collapsed'
    authority_manifest=$projection.authority_manifest
  }}
}}
try {{
  Resolve-RfObservedPrePulseSourceIdentity `
    -Experiment $experiment -BudgetSourceIdentity $mismatch
  throw 'projection mismatch was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'differs from the campaign row') {{ throw }}
}}
try {{
  Resolve-RfObservedPrePulseSourceIdentity `
    -Experiment ([pscustomobject]@{{experiment_id='ordinary'}}) `
    -BudgetSourceIdentity $budgetIdentity
  throw 'ordinary row accepted an observed projection'
}} catch {{
  if ($_.Exception.Message -notmatch 'Non-observed campaign row prohibits') {{ throw }}
}}
'OBSERVED_PROJECTION_IDENTITY=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1], text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=False, timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("OBSERVED_PROJECTION_IDENTITY=PASS", completed.stdout)
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        promotion = adapter.index(
            "$runtime.source_identity = Resolve-RfObservedPrePulseSourceIdentity"
        )
        self.assertLess(
            promotion,
            adapter.index("& $runtime.implementation.single_flight_runner"),
        )
        self.assertIn(
            "-BudgetSourceIdentity $budget.source_identity", adapter
        )
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "upstream_source_identity=$resolvedBudgetDocument.source_identity",
            runner,
        )
        self.assertNotIn(
            "upstream_source_identity=$runtime.source_identity", runner
        )

    def test_three_zone_runner_arguments_are_all_or_none_and_layout_scoped(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        script = f"""
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  '{SINGLE_FLIGHT_RUNNER}', [ref]$null, [ref]$errors
)
if ($errors) {{ throw $errors[0] }}
$fn = $ast.Find({{
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Assert-RfThreeZoneArgumentSet'
}}, $true)
if ($null -eq $fn) {{ throw 'three-zone argument assertion is missing' }}
. ([scriptblock]::Create($fn.Extent.Text))
$valid = @{{
  Candidate='candidate.json'; CandidateSha256=('A' * 64)
}}
if (-not (Assert-RfThreeZoneArgumentSet @valid)) {{ throw 'valid set rejected' }}
if (Assert-RfThreeZoneArgumentSet) {{
  throw 'absence of a Candidate was misclassified'
}}
try {{
  Assert-RfThreeZoneArgumentSet -Candidate 'candidate.json'
  throw 'missing Candidate was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'Candidate arguments are incomplete') {{ throw }}
}}
'THREE_ZONE_ARGUMENT_SET=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False, timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("THREE_ZONE_ARGUMENT_SET=PASS", completed.stdout)

    def test_three_zone_candidate_is_frozen_and_cross_checked_without_public_cli(self) -> None:
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        public_entry = WORKFLOW_ENTRY.read_text(encoding="utf-8")
        for name in (
            "single_flight_three_zone_candidate_path",
            "single_flight_three_zone_candidate_sha256",
            "ThreeZoneCandidate",
        ):
            self.assertIn(name, adapter)
        for name in (
            "ThreeZoneTopologyId",
            "ThreeZoneGeometryId",
            "ThreeZoneFrontendElectrodeTopologyId",
            "ThreeZoneFieldId",
        ):
            self.assertNotIn(name, adapter)
        self.assertIn("$workspaceArtifactRoot", adapter)
        self.assertIn("runtime.three_zone_runtime_identity", runner)
        self.assertIn("three_zone_t5_candidate_resolved.json", runner)
        self.assertIn(
            "$runConfiguration.inputs.three_zone_t5_candidate", runner
        )
        self.assertIn("--frontend-electrode-topology", runner)
        self.assertNotIn("three_zone_t5_primary_v1", adapter)
        self.assertNotIn("three_zone_t5_primary_shaping_rings_1p4_v1", adapter)
        self.assertNotIn("ThreeZoneCandidate", public_entry)

    def test_three_zone_runtime_identity_rejects_mapping_tamper(self) -> None:
        planes = {"repeller": -25.0, "intermediate1": -20.0, "intermediate2": -10.0, "exit": -5.0}
        potentials = {"repeller": 2000.0, "intermediate1": 1500.0, "intermediate2": 500.0, "exit": 0.0}
        topology = {
            "topology_id": "registered_three_zone_topology_v2",
            "planes_global_z_mm": planes,
            "potentials_v": potentials,
        }
        candidate = {
            "schema_version": 1,
            "role": "oatof_three_zone_simion_candidate_resolved",
            "qualification": "CANDIDATE_ONLY",
            "compiler_mode": "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
            "identities": {
                "topology_id": "registered_three_zone_topology_v2",
                "geometry_id": "registered_three_zone_geometry_v2",
            },
            "accelerator_topology": copy.deepcopy(topology),
        }
        geometry = {
            "accelerator_topology": copy.deepcopy(topology),
            "single_flight_layout_derivation": {
                "layout_profile_id": "registered_future_three_zone_layout",
                "architecture_generation_id": "registered_three_zone_generation_v2",
                "design_compilation": {"candidate": {"sha256": "A" * 64}},
            },
        }
        region = {
            "layout_geometry": {"sha256": "B" * 64},
            "semantic": {
                "canonical_profile_id": "accelerator_real_three_zone_pa_real_reflectron",
                "accelerator_topology": copy.deepcopy(topology),
            },
        }
        field = {
            "profile_id": "accelerator_real_three_zone_pa_real_reflectron",
            "topology_id": "registered_three_zone_topology_v2",
            "geometry_id": "registered_three_zone_geometry_v2",
            "frontend_electrode_topology_id": "registered_three_zone_frontend_v2",
            "field_id": "registered_three_zone_real_field_v2",
        }
        arguments = {
            "candidate": candidate,
            "candidate_sha256": "A" * 64,
            "geometry": geometry,
            "geometry_sha256": "B" * 64,
            "frontend_contract": {
                "accelerator_topology_id": "registered_three_zone_topology_v2"
            },
            "frontend_electrode_topology": {
                "topology_id": "registered_three_zone_frontend_v2"
            },
            "region_field": region,
            "configuration": {"accelerator_field_profiles": [field]},
            "layout_profile_id": "registered_future_three_zone_layout",
            "architecture_generation_id": "registered_three_zone_generation_v2",
        }
        self.assertEqual(
            validate_runtime_identity(**arguments),
            "registered_three_zone_real_field_v2",
        )
        missing_field_identity = copy.deepcopy(arguments)
        missing_field_identity["configuration"]["accelerator_field_profiles"][0][
            "field_id"
        ] = None
        with self.assertRaisesRegex(ValueError, "Candidate/runtime identity differs"):
            validate_runtime_identity(**missing_field_identity)
        region["semantic"]["accelerator_topology"]["potentials_v"]["exit"] = 1.0
        with self.assertRaisesRegex(
            ValueError, "plane or potential mapping differs"
        ):
            validate_runtime_identity(**arguments)


    def test_generated_pre_pulse_subset_does_not_require_external_campaign_state(self) -> None:
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("$usesGeneratedPrePulseSubset", adapter)
        self.assertIn("$declaredPrePulseSourceState", adapter)
        self.assertIn("@(Import-Csv -LiteralPath $prePulseSourceStatePath).Count", adapter)
        self.assertIn(
            "$frozenArguments.source_release_mode -eq 'continuous_frontend'",
            adapter,
        )
        self.assertIn(
            "Restart source modes prohibit an unused mother-source override.",
            runner,
        )
        self.assertIn("[string]$MotherParticleSourceRunRoot = ''", runner)
        self.assertIn(
            "Explicit mother-source run root requires one non-materialized "
            "mother-source override.",
            runner,
        )
        self.assertIn("[IO.Path]::GetFullPath($MotherParticleSourceRunRoot)", runner)
        self.assertNotIn("$experiment.pre_pulse_source_state.particle_count", adapter)
        self.assertNotIn(
            "$experiment.pre_pulse_source_state.position_rowwise_abs_tolerance_mm",
            adapter,
        )

    def test_pa_cache_policy_run_config_is_written_before_budget_and_cache_gates(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        initial_write = runner.index(
            "Write-RfPreCacheRunConfiguration `\n"
            "  -LifecycleStage 'pa_cache_policy_pending_budget_validation'"
        )
        budget_parse = runner.index("Initialize-RfIntegrationStageBudget")
        first_cache_gate = runner.index("Resolve-RfReusableCacheDirectory")
        first_builder = runner.index("$gem2pa = Invoke-ResourceBudgetedProcess")
        self.assertLess(initial_write, budget_parse)
        self.assertLess(budget_parse, first_cache_gate)
        self.assertLess(first_cache_gate, first_builder)
        for family in (
            "simion_single_flight_frontend_pa_cache",
            "simion_accelerator_overlay_pa_cache",
            "simion_oatof_flight_tube_pa_cache",
            "simion_oatof_reflectron_pa_cache",
        ):
            self.assertIn(f"role='{family}'", runner)
        self.assertIn("disposition='pending_cache_decision'", runner)
        self.assertIn("single_flight_pa_cache_policy=$PaCachePolicy", runner)
        self.assertIn(
            "single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance",
            runner,
        )

    def test_resolved_budget_authority_switches_to_run_local_frozen_copy(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        initialize = runner.index(
            "$budget = Initialize-RfIntegrationStageBudget "
            "-ResolvedBudget $ResolvedEngineeringBudget"
        )
        after_initialize = runner[initialize:]
        self.assertIn(
            "$resolvedBudgetDocument = Read-RfFrozenResolvedBudgetDocument `\n"
            "    -StageBudgetReceipt $budget",
            after_initialize,
        )
        self.assertNotIn(
            "Get-Content -LiteralPath $ResolvedEngineeringBudget",
            after_initialize,
        )
        self.assertEqual(after_initialize.count("$ResolvedEngineeringBudget"), 1)
        self.assertIn(
            "single_flight_pa_cache_policy -ne\n      $PaCachePolicy",
            after_initialize,
        )
        frozen_policy_rebind = after_initialize.index(
            "$PaCachePolicy = [string]"
            "$resolvedBudgetDocument.single_flight_pa_cache_policy"
        )
        frozen_provenance_rebind = after_initialize.index(
            "$PaCachePolicyProvenance = [string](\n"
            "    $resolvedBudgetDocument."
            "single_flight_pa_cache_policy_provenance"
        )
        first_cache_gate = after_initialize.index("Resolve-RfReusableCacheDirectory")
        frozen_receipt_policy = after_initialize.index(
            "$preCacheRunConfiguration.parameters."
            "single_flight_pa_cache_policy =\n"
            "    [string]$resolvedBudgetDocument.single_flight_pa_cache_policy"
        )
        frozen_receipt_provenance = after_initialize.index(
            "$preCacheRunConfiguration.parameters."
            "single_flight_pa_cache_policy_provenance =\n"
            "    [string]$resolvedBudgetDocument."
            "single_flight_pa_cache_policy_provenance"
        )
        frozen_post_budget_write = after_initialize.index(
            "Write-RfPreCacheRunConfiguration `\n"
            "    -LifecycleStage "
            "'pa_cache_policy_frozen_post_budget_validation'"
        )
        configuration_source = after_initialize.index(
            "$configurationSource = Join-Path $integrationRoot"
        )
        frozen_pre_cache_write = after_initialize.index(
            "Write-RfPreCacheRunConfiguration "
            "-LifecycleStage 'pa_cache_policy_frozen_pre_cache'"
        )
        self.assertLess(frozen_policy_rebind, first_cache_gate)
        self.assertLess(frozen_provenance_rebind, first_cache_gate)
        self.assertLess(frozen_receipt_policy, frozen_post_budget_write)
        self.assertLess(frozen_receipt_provenance, frozen_post_budget_write)
        self.assertLess(frozen_post_budget_write, configuration_source)
        self.assertLess(frozen_post_budget_write, frozen_pre_cache_write)
        self.assertLess(frozen_pre_cache_write, first_cache_gate)
        frozen_write_extent = after_initialize[
            frozen_receipt_provenance:frozen_post_budget_write
        ]
        self.assertNotIn("$configurationSource", frozen_write_extent)
        self.assertIn(
            "$preCacheRunConfiguration.parameters."
            "single_flight_pa_cache_policy_provenance =\n"
            "    [string]$resolvedBudgetDocument."
            "single_flight_pa_cache_policy_provenance\n"
            "  Write-RfPreCacheRunConfiguration `\n"
            "    -LifecycleStage "
            "'pa_cache_policy_frozen_post_budget_validation'\n"
            "  $configurationSource = Join-Path $integrationRoot",
            after_initialize,
        )

    def test_require_existing_cache_misses_precede_every_simion_verifier(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        reflectron_gate = runner.index(
            'Required PA cache MISS or damage: role=$($reflectronCachePlan.role)'
        )
        overlay_verify = runner.index(
            "$overlayVerify = Invoke-ResourceBudgetedProcess"
        )
        topology_verify = runner.index("frontend_aperture_topology_resource_usage.json")
        self.assertLess(reflectron_gate, overlay_verify)
        self.assertLess(reflectron_gate, topology_verify)
        self.assertIn("-InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing')", runner)
        self.assertIn("single_flight_pa_cache_policy=$PaCachePolicy", runner)
        self.assertIn("pa_cache_dispositions=$paCacheDispositions", runner)

    def test_external_runtime_implementation_paths_are_exact_role_bound(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        script = f"""
. '{RUNTIME_BINDING}'
$root = 'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/'
$cases = @(
  @('simion_rf_drive_kernel','common/multipole/simion_rf_drive.lua',$true),
  @('oatof_analyzer_component','projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_analyzer_component.lua',$true),
  @('single_flight_runner',$root + 'runtime/run_single_flight.ps1',$true),
  @('simion_rf_drive_kernel','common/multipole/not_the_kernel.lua',$false),
  @('unknown_external_role','common/multipole/simion_rf_drive.lua',$false),
  @('oatof_analyzer_component','projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/formal/oatof_ideal_grounded.lua',$false)
)
foreach ($case in $cases) {{
  $actual = Test-RfOatofImplementationPath -Name $case[0] -Path $case[1] `
    -IntegrationRelativeRoot $root
  if ($actual -ne $case[2]) {{
    throw "implementation path case differs: $($case[0]) $($case[1])"
  }}
}}
'RUNTIME_IMPLEMENTATION_PATH_CASES=PASS COUNT=6'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            capture_output=True,
            check=False, timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "RUNTIME_IMPLEMENTATION_PATH_CASES=PASS COUNT=6", completed.stdout
        )

    def test_all_runtime_boundaries_require_four_run_local_identities(self) -> None:
        parameters = (
            "ResolvedSourceContract",
            "ResolvedSourceContractSha256",
            "UpstreamResolvedDesign",
            "UpstreamResolvedDesignSha256",
        )
        for path in (RUNTIME_BINDING, *RUNNERS):
            text = path.read_text(encoding="utf-8")
            for parameter in parameters:
                self.assertRegex(
                    text,
                    rf"\[Parameter\(Mandatory\)\]\[string\]\${parameter}\b",
                    (path, parameter),
                )
            self.assertNotIn("SourceContractOverride", text, path)
            self.assertNotIn("UpstreamResolvedDesignOverride", text, path)

    def test_runtime_accepts_only_active_v3_and_fixed_parent_run_files(self) -> None:
        text = RUNTIME_BINDING.read_text(encoding="utf-8")
        self.assertIn("$binding.schema_version -ne 3", text)
        self.assertNotRegex(text, r"sourceContract\.schema_version\s+-eq\s+1")
        self.assertIn("filename = 'resolved_source_contract.json'", text)
        self.assertIn("filename = 'upstream_resolved_design.json'", text)
        self.assertIn("-Root $parentRunRoot", text)
        self.assertIn("contractPaths.resolved_source_contract", text)
        self.assertNotIn("binding.contracts.source_contract", text)
        self.assertNotIn("binding.contracts.upstream_resolved_design", text)

    def test_stage_modes_and_manifest_roles_are_particle_count_neutral(self) -> None:
        joined = "\n".join(path.read_text(encoding="utf-8") for path in RUNNERS)
        for forbidden in (
            "rf_to_oatof_pre_pulse_interface_transport_n100",
            "rf_to_oatof_pulse_capture_n100",
            "rf_to_oatof_analyzer_transport_n100",
        ):
            self.assertNotIn(forbidden, joined)
        for path in RUNNERS[1:]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("resolved_source_contract", text, path)
            self.assertIn("upstream_resolved_design", text, path)

    def test_pulse_capture_uses_run_local_design_not_repository_inventory(self) -> None:
        text = RUNNERS[2].read_text(encoding="utf-8")
        self.assertIn(
            "Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design "
            "-Destination $rf",
            text.replace("`\n    ", ""),
        )
        self.assertNotIn("'rf_resolved_design'", text)

    def test_validate_cleanup_tolerates_parallel_empty_root_removal(self) -> None:
        self.assertIn(
            "Remove-Item -LiteralPath $validationRoot -Force "
            "-ErrorAction SilentlyContinue",
            WORKFLOW_ENTRY.read_text(encoding="utf-8"),
        )

    def test_joint_single_flight_run_package_is_integration_owned(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        integration_id = (
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        )
        self.assertIn(f"$runProjectId = '{integration_id}'", text)
        self.assertIn(
            '"artifacts\\projects\\$runProjectId"', text
        )
        self.assertIn("-Project $runProjectId", text)
        self.assertIn("project=$runProjectId", text)
        self.assertIn(
            "upstream_project_id=$runtime.upstream_project_id", text
        )
        self.assertNotIn("-Project $runtime.upstream_project_id", text)
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        self.assertIn(
            "'artifacts\\projects\\' + $plan.integration_id + '\\runs'",
            adapter,
        )
        self.assertIn(
            "$singleFlightManifest.project -ne $plan.integration_id", adapter
        )
        self.assertIn(
            "$singleFlightManifest.mode -ne 'rf_to_oatof_simion_single_flight'",
            adapter,
        )

    def test_single_flight_freezes_only_successor_program_components(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        for flag in (
            "--analyzer-component",
            "--pulse-hook",
            "--frontend-hook",
            "--rf-drive-kernel",
        ):
            self.assertIn(flag, text)
        for frozen_input in (
            "analyzer_component=$analyzerComponent",
            "pulse_hook=$pulseHook",
            "frontend_hook=$frontendHook",
            "rf_drive_kernel=$rfDriveKernel",
        ):
            self.assertIn(frozen_input, text)
        for legacy in (
            "--formal",
            "--pulse-extension",
            "simion\\workbench\\formal",
            "oatof_handoff_pulse.lua",
        ):
            self.assertNotIn(legacy, text)

    def test_overlay_cache_is_staged_and_reuses_the_basis_report(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("'b-' + [guid]::NewGuid().ToString('N').Substring(0,12)", text)
        self.assertIn("legacy path-length limit", text)
        self.assertIn(
            "$overlayCacheDir = Publish-RfVerifiedCacheEntry",
            text,
        )
        self.assertIn(
            "$overlayCacheBasisReport = Join-Path $overlayCacheDir "
            "'basis_build.json'",
            text,
        )
        self.assertIn(
            "Copy-Item -LiteralPath $overlayCacheBasisReport "
            "-Destination $overlayBasisReport",
            text,
        )
        self.assertNotIn(
            "Copy-Item -LiteralPath $overlayCacheManifest "
            "-Destination $overlayBasisReport",
            text,
        )
        self.assertIn(
            "Get-ChildItem -LiteralPath $cacheDir -Filter 'frontend.pa*' -File",
            text,
        )
        self.assertIn("$frontendWorkingPa0,$overlayBuildPaSharp", text)
        self.assertIn("frontend_pa_cache_key=$frontendCacheKey", text)

    def test_simion_consumes_physical_pa_copies_and_rechecks_frontend_cache(
        self,
    ) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("New-Item -ItemType HardLink", text)
        self.assertIn("function Copy-RfPaCacheFamilyToRuntime", text)
        self.assertIn(
            "Copy-Item -LiteralPath $source.FullName -Destination $target -Force",
            text,
        )
        self.assertIn("$frontendWorkingPa0,$overlayRuntimePa0", text)
        self.assertIn(
            "-FilePath $SimionExe -WorkingDirectory $runtimeDir",
            text,
        )
        self.assertNotIn(
            "-FilePath $SimionExe -WorkingDirectory $overlayCacheDir",
            text,
        )
        self.assertIn("Set-RfMaterializedCacheFileWritable -Path $target", text)
        self.assertIn("-PaPath $frontendWorkingPa0", text)
        self.assertIn(
            "OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0",
            text,
        )
        guard = text.index(
            "Frontend PA cache changed during construction-time SIMION access."
        )
        manifest_copy = text.index(
            "$frontendCacheManifestInput = Copy-RfCacheManifestInput"
        )
        fly_override = text.index(
            "OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0"
        )
        self.assertLess(guard, manifest_copy)
        self.assertLess(manifest_copy, fly_override)

    def test_all_four_pa_cache_roles_use_one_verified_contract(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        artifacts = (INTEGRATION_ROOT / "runtime" / "run_artifacts.ps1").read_text(
            encoding="utf-8"
        )
        for role in (
            "simion_single_flight_frontend_pa_cache",
            "simion_accelerator_overlay_pa_cache",
            "simion_oatof_flight_tube_pa_cache",
            "simion_oatof_reflectron_pa_cache",
        ):
            self.assertIn(role, runner)
        self.assertIn("Get-RfSimionSolverCacheIdentity", runner)
        self.assertIn("Get-RfContentIdentitySha256", runner)
        self.assertIn("executable_sha256", artifacts)
        self.assertIn("product_version", artifacts)
        self.assertIn("Test-RfReusableCacheEntry", artifacts)
        self.assertIn("Publish-RfVerifiedCacheEntry", artifacts)
        self.assertNotIn("requires manual quarantine", runner)
        for input_name in (
            "frontend_pa_cache_manifest",
            "accelerator_overlay_pa_cache_manifest",
            "flight_tube_pa_cache_manifest",
            "reflectron_pa_cache_manifest",
        ):
            self.assertIn(input_name, runner)

    def test_dz0025_profile_keeps_coarse_grid_isotropic_and_refines_only_z(self) -> None:
        import json

        settings = json.loads(
            (INTEGRATION_ROOT / "config" / "simion_single_flight.json").read_text(
                encoding="utf-8"
            )
        )
        profile = next(
            item for item in settings["frontend_grid_profiles"]
            if item["profile_id"] == "frontend_isotropic_020_accelerator_overlay_z0025"
        )
        self.assertEqual(profile["cell_mm_xyz"], {"x": 0.2, "y": 0.2, "z": 0.2})
        self.assertEqual(
            profile["accelerator_overlay"]["cell_mm_xyz"],
            {"x": 0.2, "y": 0.2, "z": 0.025},
        )
        self.assertEqual(
            profile["accelerator_overlay"]["boundary_mode"],
            "coarse_electrode_basis_dirichlet_v1",
        )
        resolved = resolve_execution_profile(
            settings,
            frontend_grid_profile_id=profile["profile_id"],
        )
        self.assertEqual(
            resolved["frontend_cell_mm_xyz"], {"x": 0.2, "y": 0.2, "z": 0.2}
        )
        self.assertEqual(
            resolved["accelerator_overlay_cell_mm_xyz"],
            {"x": 0.2, "y": 0.2, "z": 0.025},
        )
        self.assertEqual(
            resolved["accelerator_overlay_boundary_mode"],
            "coarse_electrode_basis_dirichlet_v1",
        )

    def test_execution_profile_resolver_uses_default_and_explicit_numerics(self) -> None:
        settings = json.loads(
            (INTEGRATION_ROOT / "config" / "simion_single_flight.json").read_text(
                encoding="utf-8"
            )
        )
        defaults = resolve_execution_profile(settings)
        self.assertEqual(defaults["frontend_grid_profile_id"], "frontend_isotropic_020")
        self.assertEqual(defaults["oatof_numerical_profile_id"], "oatof_formal_mesh")
        self.assertEqual(defaults["trajectory_quality"], 8)
        self.assertEqual(defaults["rf_steps_per_period"], 40)
        self.assertEqual(defaults["maximum_time_of_flight_us"], 90.0)
        explicit = resolve_execution_profile(
            settings,
            frontend_grid_profile_id="frontend_isotropic_015",
            oatof_numerical_profile_id="oatof_reflectron_z010_r100",
            trajectory_quality_profile_id="tqual_108",
            time_integration_profile_id="dt160",
            maximum_time_of_flight_us=120.0,
            spatial_window_profile_id="accelerator_xy_open_bore",
        )
        self.assertEqual(explicit["frontend_cell_mm_xyz"], {"x": 0.15, "y": 0.15, "z": 0.15})
        self.assertEqual(explicit["reflectron_cell_mm"], {"axial": 0.1, "radial": 1.0})
        self.assertEqual(explicit["trajectory_quality"], 108)
        self.assertEqual(explicit["rf_steps_per_period"], 160)
        self.assertEqual(explicit["maximum_time_of_flight_us"], 120.0)
        self.assertEqual(explicit["spatial_window_profile_id"], "accelerator_xy_open_bore")

    def test_execution_profile_resolver_rejects_invalid_selection_and_overlay(self) -> None:
        settings = json.loads(
            (INTEGRATION_ROOT / "config" / "simion_single_flight.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(ValueError, "Single-flight numerical configuration"):
            resolve_execution_profile(settings, time_integration_profile_id="not-a-profile")
        invalid = copy.deepcopy(settings)
        profile = next(
            item for item in invalid["frontend_grid_profiles"]
            if item["profile_id"] == "frontend_isotropic_020_accelerator_overlay_z005"
        )
        profile["accelerator_overlay"]["cell_mm_xyz"]["x"] = 0.1
        with self.assertRaisesRegex(ValueError, "Single-flight numerical configuration"):
            resolve_execution_profile(
                invalid, frontend_grid_profile_id=profile["profile_id"]
            )

    def test_full_flight_uses_configured_source_region_diagnostic_default(self) -> None:
        settings = json.loads(
            (INTEGRATION_ROOT / "config" / "simion_single_flight.json").read_text(
                encoding="utf-8"
            )
        )
        profile_id = settings["default_source_region_diagnostic_profile_id"]
        self.assertEqual(profile_id, "layout_resolved_axial_provisional_xy2_v1")
        profiles = settings["source_region_diagnostic_profiles"]
        profile = next(item for item in profiles if item["profile_id"] == profile_id)
        self.assertEqual(profile["claim_status"], "PROVISIONAL_DIAGNOSTIC_ONLY")
        self.assertEqual(profile["axes"]["x"]["full_width_mm"], 2.0)
        self.assertEqual(profile["axes"]["y"]["full_width_mm"], 2.0)
        self.assertEqual(
            profile["axes"]["z"]["full_width_binding"],
            "particle_source.size_z_mm",
        )
        self.assertNotIn(
            profile_id,
            {item["profile_id"] for item in settings["spatial_window_profiles"]},
        )
        self.assertEqual(
            resolve_execution_profile(
                settings, include_source_region_diagnostic=True
            )["source_region_diagnostic_profile_id"],
            profile_id,
        )
        self.assertIsNone(
            resolve_execution_profile(settings)["source_region_diagnostic_profile_id"]
        )
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("--include-source-region-diagnostic", runner)
        self.assertNotIn("default_source_region_diagnostic_profile_id", runner)
        self.assertNotIn("source_region_diagnostic_profiles", runner)
        self.assertIn("--source-region-diagnostic-profile-id", runner)
        self.assertIn("-not $isPrePulseTimeSeriesScreening", runner)
        self.assertNotIn("$SamplingMode", runner)
        self.assertNotIn("layout_resolved_axial_provisional_xy2_v1", runner)

    def test_full_flight_freezes_default_accelerator_phase_space_diagnostic(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("single_flight_accelerator_pre_pulse_phase_space.png", runner)
        self.assertIn("--phase-space-output", runner)
        self.assertIn("--phase-space-metadata", runner)
        self.assertIn("--phase-space-data", runner)
        self.assertIn("single_flight_accelerator_checkpoint_evolution.png", runner)
        self.assertIn("--evolution-output", runner)
        self.assertIn("--evolution-metadata", runner)
        self.assertIn("--evolution-data", runner)
        self.assertIn("accelerator_pre_pulse_phase_space", runner)
        self.assertIn("accelerator_checkpoint_evolution", runner)
        self.assertIn("$phaseSpace,$phaseSpaceMetadata,$phaseSpaceData", runner)

        catalog = json.loads(
            (INTEGRATION_ROOT / "config" / "analysis_capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        capability = next(
            item
            for item in catalog["capabilities"]
            if item["capability_id"]
            == "rf_oatof_accelerator_phase_space_evolution_v2"
        )
        self.assertEqual(capability["required_event_plane"], "pre_pulse_state")
        self.assertEqual(capability["claim_class"], "DIAGNOSTIC_ONLY")

    def test_resolution_qualification_requires_full_bootstrap(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        configuration = json.loads(
            (INTEGRATION_ROOT / "config" / "simion_single_flight.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("[int]$BootstrapResamples = 0", text)
        self.assertIn("[switch]$ResolutionQualification", text)
        self.assertEqual(
            configuration["resolution_qualification_policy"]
            ["required_bootstrap_resample_count"],
            5000,
        )
        self.assertEqual(
            resolve_execution_profile(configuration)[
                "required_qualification_bootstrap_resamples"
            ],
            5000,
        )
        self.assertIn(
            "$BootstrapResamples -ne $requiredQualificationBootstrapResamples",
            text,
        )
        self.assertIn(
            "runtime.single_flight_execution_profile",
            text,
        )
        self.assertIn(
            "resolution_qualification_required_bootstrap_resample_count",
            text,
        )
        self.assertIn(
            "$populationContract.analysis_randomness.bootstrap_resample_count", text
        )
        self.assertNotIn("'--bootstrap-resamples'", text)
        self.assertIn("'--require-resolution-qualification'", text)
        self.assertIn("'--require-three-zone-checkpoint-census'", text)
        self.assertNotIn("Assert-RfThreeZoneCheckpointCensus", text)

    def test_population_contract_is_the_only_release_and_mode_authority(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        self.assertNotIn("[string]$SourceReleaseMode", runner)
        self.assertNotIn("$runnerArguments.SourceReleaseMode", adapter)
        self.assertIn(
            "$sourceReleaseMode = [string]$populationContract.source_release_mode",
            runner,
        )
        self.assertNotIn("source_release_mode=$sourceReleaseMode", runner)
        self.assertNotIn("source_release_mode=$SourceReleaseMode", runner)
        self.assertIn("single_flight_execution", runner)
        self.assertIn("$populationBasis = [string]", runner)
        self.assertNotIn("$SamplingMode", runner)
        self.assertNotIn("steady_candidate_pool", runner)

    def test_r03_baseline_population_is_strictmode_safe_without_paired_cohort(self) -> None:
        population = (
            INTEGRATION_ROOT.parents[2]
            / "artifacts/projects/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runs/20260815_160000__sim__cross__pulse-direct-real-rr__n100__r03/"
            "resolved_population_contract.json"
        )
        if not population.is_file():
            self.skipTest("local R03 baseline population evidence is unavailable")
        self.assertTrue(population.is_file())
        self.assertEqual(
            hashlib.sha256(population.read_bytes()).hexdigest().upper(),
            "1D8D54EEEA5BB9B98A6BF631825AF0FE383523259444A3F6C95A9CE92794FC36",
        )
        completed = subprocess.run(
            [
                "pwsh", "-NoProfile", "-Command",
                "Set-StrictMode -Version Latest; "
                "$p=Get-Content -LiteralPath $args[0] -Raw | ConvertFrom-Json; "
                "$paired=$p.PSObject.Properties['paired_cohort_authority']; "
                "$mode=$p.PSObject.Properties['cohort_authority_mode']; "
                "if($null -ne $paired){throw 'unexpected paired cohort'}; "
                "if([string]$mode.Value -ne 'establish_observed_authority'){"
                "throw 'mode differs'}; "
                "if($null -ne $p.denominators.PSObject.Properties["
                "'eligible_population_count']){throw 'eligible denominator present'}; "
                "Write-Output 'R03_BASELINE_STRICTMODE=PASS'",
                str(population),
            ],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False, timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("R03_BASELINE_STRICTMODE=PASS", completed.stdout)
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "$populationContract.PSObject.Properties['paired_cohort_authority']",
            runner,
        )
        self.assertIn("$EligiblePopulationCount = if ($hasPairedCohort)", runner)

if __name__ == "__main__":
    unittest.main()
