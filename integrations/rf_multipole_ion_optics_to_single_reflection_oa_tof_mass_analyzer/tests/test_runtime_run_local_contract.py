"""Static regression tests for mandatory run-local integration inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from common.contracts.file_identity import repository_text_sha256


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
PULSE_RESOLUTION_REGISTRAR = (
    INTEGRATION_ROOT / "analysis" / "register_pulse_resolution_result.py"
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
        solver_launch = runner.index("$jobs += Start-Job")
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
        self.assertIn("$quotient = [Math]::Floor($launched / $batchCount)", runner)
        self.assertIn("$remainder = $launched % $batchCount", runner)
        self.assertIn("$waveStart += $maxParallelBatches", runner)
        self.assertIn("$waveBatchCount -gt 1", runner)
        self.assertIn("[MultipoleMemoryStatus]::AvailableBytes()", runner)
        self.assertIn(
            "$settings.batching_policy.parallel_batch_memory_reservation_bytes",
            runner,
        )
        self.assertIn(
            "$stageBudgetDocument.limits.minimum_system_available_memory_bytes",
            runner,
        )
        self.assertNotIn("[int64](10GB)", runner)
        self.assertNotIn("[int64](4GB)", runner)
        memory_gate = runner.index("$waveBatchCount -gt 1")
        solver_launch = runner.index("$jobs += Start-Job")
        self.assertLess(memory_gate, solver_launch)
        batch_bound = runner.index(
            "Single-flight execution batch count exceeds launched particle count."
        )
        self.assertLess(batch_bound, solver_launch)

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
            errors="replace", capture_output=True, check=False,
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
  LayoutProfileId='three_zone_t5_primary_v1'; Candidate='candidate.json'
  CandidateSha256=('A' * 64); TopologyId='three_zone_accelerator_ideal_v1'
  GeometryId='three_zone_focus_origin_planes_v1'
  FrontendElectrodeTopologyId='three_zone_frontend_v1'
  FieldId='three_zone_refined_pa_field_v1'
}}
if (-not (Assert-RfThreeZoneArgumentSet @valid)) {{ throw 'valid set rejected' }}
if (Assert-RfThreeZoneArgumentSet -LayoutProfileId 'theory_source_z10_d1_3') {{
  throw 'two-zone identity was misclassified'
}}
try {{
  Assert-RfThreeZoneArgumentSet -LayoutProfileId 'three_zone_t5_primary_v1'
  throw 'missing Candidate was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'arguments and layout identity differ') {{ throw }}
}}
try {{
  $invalid = $valid.Clone()
  $invalid.LayoutProfileId = 'theory_source_z10_d1_3'
  Assert-RfThreeZoneArgumentSet @invalid
  throw 'two-zone Candidate was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'arguments and layout identity differ') {{ throw }}
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
            check=False,
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
            "ThreeZoneTopologyId",
            "ThreeZoneGeometryId",
            "ThreeZoneFrontendElectrodeTopologyId",
            "ThreeZoneFieldId",
        ):
            self.assertIn(name, adapter)
        self.assertIn("$workspaceArtifactRoot", adapter)
        self.assertIn("Assert-RfThreeZoneRuntimeIdentity", runner)
        self.assertIn("three_zone_t5_candidate_resolved.json", runner)
        self.assertIn(
            "$runConfiguration.inputs.three_zone_t5_candidate", runner
        )
        self.assertIn(
            "$FrontendElectrodeTopology.topology_id", runner
        )
        self.assertNotIn("ThreeZoneCandidate", public_entry)

    def test_three_zone_runtime_identity_rejects_mapping_tamper(self) -> None:
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
    $node.Name -eq 'Assert-RfThreeZoneRuntimeIdentity'
}}, $true)
if ($null -eq $fn) {{ throw 'three-zone runtime assertion is missing' }}
. ([scriptblock]::Create($fn.Extent.Text))
$planes = [pscustomobject]@{{
  repeller=-25.0; intermediate1=-20.0; intermediate2=-10.0; exit=-5.0
}}
$potentials = [pscustomobject]@{{
  repeller=2000.0; intermediate1=1500.0; intermediate2=500.0; exit=0.0
}}
$topology = [pscustomobject]@{{
  topology_id='three_zone_accelerator_ideal_v1'
  planes_global_z_mm=$planes; potentials_v=$potentials
}}
$candidate = [pscustomobject]@{{
  schema_version=1; role='oatof_three_zone_simion_candidate_resolved'
  qualification='CANDIDATE_ONLY'; compiler_mode='T5_FROZEN_PRIMARY_AND_BRANCH_ONLY'
  identities=[pscustomobject]@{{
    topology_id='three_zone_accelerator_ideal_v1'
    geometry_id='three_zone_focus_origin_planes_v1'
    field_id='three_zone_piecewise_uniform_ideal_field_v1'
  }}
  accelerator_topology=$topology
}}
$geometry = [pscustomobject]@{{
  accelerator_topology=$topology
  single_flight_layout_derivation=[pscustomobject]@{{
    layout_profile_id='three_zone_t5_primary_v1'
    architecture_generation_id='three_zone_t5_frozen_primary_v1'
    design_compilation=[pscustomobject]@{{
      candidate=[pscustomobject]@{{sha256=('A' * 64)}}
    }}
  }}
}}
$region = [pscustomobject]@{{
  layout_geometry=[pscustomobject]@{{sha256=('B' * 64)}}
  semantic=[pscustomobject]@{{
    canonical_profile_id='accelerator_real_three_zone_pa_real_reflectron'
    accelerator_topology=$topology
  }}
}}
$field = [pscustomobject]@{{
  profile_id='accelerator_real_three_zone_pa_real_reflectron'
  topology_id='three_zone_accelerator_ideal_v1'
  geometry_id='three_zone_focus_origin_planes_v1'
  frontend_electrode_topology_id='three_zone_frontend_v1'
  field_id='three_zone_refined_pa_field_v1'
}}
$arguments = @{{
  Candidate=$candidate; CandidateSha256=('A' * 64)
  Geometry=$geometry; GeometrySha256=('B' * 64)
  FrontendContract=[pscustomobject]@{{
    accelerator_topology_id='three_zone_accelerator_ideal_v1'
  }}
  FrontendElectrodeTopology=[pscustomobject]@{{topology_id='three_zone_frontend_v1'}}
  RegionField=$region; FieldProfile=$field
  LayoutProfileId='three_zone_t5_primary_v1'
  ArchitectureGenerationId='three_zone_t5_frozen_primary_v1'
  TopologyId='three_zone_accelerator_ideal_v1'
  GeometryId='three_zone_focus_origin_planes_v1'
  FrontendElectrodeTopologyId='three_zone_frontend_v1'
  FieldId='three_zone_refined_pa_field_v1'
}}
Assert-RfThreeZoneRuntimeIdentity @arguments
$region.semantic.accelerator_topology = [pscustomobject]@{{
  topology_id='three_zone_accelerator_ideal_v1'
  planes_global_z_mm=$planes
  potentials_v=[pscustomobject]@{{
    repeller=2000.0; intermediate1=1500.0; intermediate2=500.0; exit=1.0
  }}
}}
try {{
  Assert-RfThreeZoneRuntimeIdentity @arguments
  throw 'mapping tamper was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'plane or potential mapping differs') {{ throw }}
}}
'THREE_ZONE_RUNTIME_IDENTITY=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("THREE_ZONE_RUNTIME_IDENTITY=PASS", completed.stdout)

    def test_three_zone_intermediate2_checkpoint_is_required_only_for_three_zone(
        self,
    ) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        runner_text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        script = f"""
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  '{SINGLE_FLIGHT_RUNNER}', [ref]$null, [ref]$errors
)
if ($errors) {{ throw $errors[0] }}
$fn = $ast.Find({{
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Assert-RfThreeZoneCheckpointCensus'
}}, $true)
if ($null -eq $fn) {{ throw 'three-zone checkpoint assertion is missing' }}
. ([scriptblock]::Create($fn.Extent.Text))
$three = [pscustomobject]@{{
  accelerator_grid1_forward=7
  accelerator_intermediate2_forward=6
  local_accelerator_exit=5
  detector_crossing=4
}}
Assert-RfThreeZoneCheckpointCensus -Required $true -Census $three -LaunchedCount 7
Assert-RfThreeZoneCheckpointCensus -Required $false `
  -Census ([pscustomobject]@{{}}) -LaunchedCount 7
try {{
  Assert-RfThreeZoneCheckpointCensus -Required $true `
    -Census ([pscustomobject]@{{}}) -LaunchedCount 7
  throw 'missing intermediate2 checkpoint was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'checkpoint census differs') {{ throw }}
}}
try {{
  Assert-RfThreeZoneCheckpointCensus -Required $true `
    -Census ([pscustomobject]@{{
      accelerator_grid1_forward=5
      accelerator_intermediate2_forward=6
      local_accelerator_exit=5
      detector_crossing=4
    }}) -LaunchedCount 7
  throw 'non-monotonic checkpoint census was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'checkpoint census differs') {{ throw }}
}}
'THREE_ZONE_CHECKPOINT_CENSUS=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("THREE_ZONE_CHECKPOINT_CENSUS=PASS", completed.stdout)
        self.assertIn(
            "accelerator_intermediate2_forward_launched_upper_bound", runner_text
        )
        self.assertIn("accelerator_intermediate2_forward_count", runner_text)

    def test_three_zone_n1_authorization_rejects_missing_fail_tamper_and_identity_mismatch(
        self,
    ) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            producer = workspace / "artifacts" / "projects" / "integration" / "runs" / "producer"
            child = workspace / "artifacts" / "projects" / "integration" / "runs" / "child"
            result = producer / "results" / "three_zone_n1_solver_authorization_receipt.json"
            summary = child / "summary.json"
            checkpoints = child / "results" / "single_flight_particle_checkpoints.csv"
            for path, text in ((summary, "{}\n"), (checkpoints, "particle_id,event\n500,detector_crossing\n")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            def sha(path: Path) -> str:
                return hashlib.sha256(path.read_bytes()).hexdigest().upper()

            def binding(path: Path) -> dict[str, object]:
                return {
                    "path": path.relative_to(workspace).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha(path),
                }

            transport_manifest = child / "run_manifest.json"
            transport_manifest.write_text(json.dumps({
                "role": "simulation_run_manifest",
                "run_id": "child",
                "project": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
                "mode": "rf_to_oatof_simion_single_flight",
                "status": "success",
                "formal_eligible": False,
            }, indent=2) + "\n", encoding="utf-8")
            ids = {
                "candidate_sha256": "A" * 64,
                "layout_profile_id": "three_zone_t5_primary_v1",
                "architecture_generation_id": "three_zone_t5_frozen_primary_v1",
                "topology_id": "three_zone_accelerator_ideal_v1",
                "geometry_id": "three_zone_focus_origin_planes_v1",
                "frontend_electrode_topology_id": "three_zone_frontend_v1",
                "accelerator_field_profile_id": "accelerator_real_three_zone_pa_real_reflectron",
                "field_id": "three_zone_refined_pa_field_v1",
                "resolved_region_field_semantic_sha256": "B" * 64,
                "source_identity_sha256": "C" * 64,
            }
            events = [
                "source_release", "pre_pulse_state",
                "accelerator_grid1_forward", "accelerator_intermediate2_forward",
                "local_accelerator_exit", "reflectron_entrance_forward",
                "reflectron_turning_point", "reflectron_exit_return",
                "detector_crossing",
            ]
            receipt = {
                "schema_version": 1,
                "role": "rf_oatof_three_zone_n1_solver_authorization_receipt",
                "gate_id": "three_zone_real_pa_gate_v1",
                "decision": "PASS",
                "authorization_status": "N100_SOLVER_AUTHORIZED",
                "campaign": {"campaign_id": "campaign", "campaign_sha256": "D" * 64},
                "producer": {
                    "experiment_id": "producer", "experiment_row_sha256": "E" * 64,
                    "integration_run_id": "producer", "transport_run_id": "child",
                    "transport_manifest": binding(transport_manifest),
                },
                "authorized_successor": {
                    "experiment_id": "successor", "experiment_row_sha256": "F" * 64,
                    "particle_count": 100,
                },
                "identities": ids,
                "evidence": {
                    "summary": binding(summary), "checkpoints": binding(checkpoints),
                    "particle_id": 500,
                    "census": {"launched": 1, **{event: 1 for event in events[2:]}},
                    "required_event_sequence": events,
                },
                "failure_codes": [], "claim_limit": "functional only",
                "formal_gate_passed": False,
            }
            result.parent.mkdir(parents=True, exist_ok=True)
            result.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            parent_manifest = producer / "run_manifest.json"
            parent_manifest.write_text(json.dumps({
                "role": "simulation_run_manifest", "run_id": "producer",
                "project": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
                "mode": "multipole_family_source_closure", "status": "success",
                "formal_eligible": False,
                "outputs": [{"path": str(result.resolve()), "bytes": result.stat().st_size,
                             "sha256": sha(result)}],
            }, indent=2) + "\n", encoding="utf-8")
            script = f"""
$errors=$null
$runnerAst=[System.Management.Automation.Language.Parser]::ParseFile(
  '{SINGLE_FLIGHT_RUNNER}',[ref]$null,[ref]$errors)
if($errors){{throw $errors[0]}}
$supportAst=[System.Management.Automation.Language.Parser]::ParseFile(
  '{INTEGRATION_ROOT / 'runtime' / 'run_artifacts.ps1'}',[ref]$null,[ref]$errors)
foreach($name in @('Get-RfManifestOutputRecord')){{
  $fn=$supportAst.Find({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}},$true)
  . ([scriptblock]::Create($fn.Extent.Text))
}}
foreach($name in @('Assert-RfThreeZoneAuthorizationFileBinding','Assert-RfThreeZoneSolverAuthorization')){{
  $fn=$runnerAst.Find({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}},$true)
  . ([scriptblock]::Create($fn.Extent.Text))
}}
$args=@{{Stage='n100_solver_authorized_consumer';ParticleCount=100
  ReceiptPath='{result}';ReceiptSha256='{sha(result)}'
  ParentManifestPath='{parent_manifest}';ParentManifestSha256='{sha(parent_manifest)}'
  GateId='three_zone_real_pa_gate_v1';CampaignId='campaign';CampaignSha256=('D'*64)
  ProducerExperimentId='producer';ProducerExperimentRowSha256=('E'*64)
  SuccessorExperimentId='successor';SuccessorExperimentRowSha256=('F'*64)
  CandidateSha256=('A'*64);LayoutProfileId='three_zone_t5_primary_v1'
  ArchitectureGenerationId='three_zone_t5_frozen_primary_v1'
  TopologyId='three_zone_accelerator_ideal_v1';GeometryId='three_zone_focus_origin_planes_v1'
  FrontendElectrodeTopologyId='three_zone_frontend_v1'
  AcceleratorFieldProfileId='accelerator_real_three_zone_pa_real_reflectron'
  FieldId='three_zone_refined_pa_field_v1';RegionFieldSemanticSha256=('B'*64)
  SourceIdentitySha256=('C'*64);WorkspaceRoot='{workspace}'}}
Assert-RfThreeZoneSolverAuthorization @args
Assert-RfThreeZoneSolverAuthorization -Stage '' -ParticleCount 100 -WorkspaceRoot '{workspace}'
$ungatedWithReceipt=@{{Stage='';ParticleCount=100;ReceiptPath='{result}';WorkspaceRoot='{workspace}'}}
try{{Assert-RfThreeZoneSolverAuthorization @ungatedWithReceipt;throw 'ungated receipt accepted'}}catch{{if($_.Exception.Message -notmatch 'cannot consume'){{throw}}}}
try{{Assert-RfThreeZoneSolverAuthorization -Stage 'n100_solver_authorized_consumer' -ParticleCount 100 -WorkspaceRoot '{workspace}';throw 'missing accepted'}}catch{{if($_.Exception.Message -notmatch 'incomplete'){{throw}}}}
$bad=$args.Clone();$bad.FieldId='wrong_field'
try{{Assert-RfThreeZoneSolverAuthorization @bad;throw 'identity accepted'}}catch{{if($_.Exception.Message -notmatch 'identity or decision'){{throw}}}}
$receipt=Get-Content -LiteralPath '{result}' -Raw|ConvertFrom-Json
$receipt.decision='FAIL';$receipt.authorization_status='N100_SOLVER_NOT_AUTHORIZED'
$receipt.failure_codes=@('DETECTOR_STATUS')
$receipt|ConvertTo-Json -Depth 12|Set-Content -LiteralPath '{result}' -Encoding UTF8
$manifest=Get-Content -LiteralPath '{parent_manifest}' -Raw|ConvertFrom-Json
$manifest.outputs[0].bytes=(Get-Item -LiteralPath '{result}').Length
$manifest.outputs[0].sha256=(Get-FileHash -LiteralPath '{result}' -Algorithm SHA256).Hash
$manifest|ConvertTo-Json -Depth 8|Set-Content -LiteralPath '{parent_manifest}' -Encoding UTF8
$failed=$args.Clone();$failed.ReceiptSha256=(Get-FileHash -LiteralPath '{result}' -Algorithm SHA256).Hash
$failed.ParentManifestSha256=(Get-FileHash -LiteralPath '{parent_manifest}' -Algorithm SHA256).Hash
try{{Assert-RfThreeZoneSolverAuthorization @failed;throw 'FAIL receipt accepted'}}catch{{if($_.Exception.Message -notmatch 'identity or decision'){{throw}}}}
Set-Content -LiteralPath '{result}' -Value 'tampered' -Encoding UTF8
try{{Assert-RfThreeZoneSolverAuthorization @failed;throw 'tamper accepted'}}catch{{if($_.Exception.Message -notmatch 'missing or stale'){{throw}}}}
'N1_AUTHORIZATION_GATE=PASS'
"""
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-Command", script],
                cwd=INTEGRATION_ROOT.parents[1], text=True, encoding="utf-8",
                errors="replace", capture_output=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("N1_AUTHORIZATION_GATE=PASS", completed.stdout)

    def test_three_zone_authorization_precedes_first_simion_process(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        self.assertLess(
            runner.index("Assert-RfThreeZoneSolverAuthorization -Stage"),
            runner.index("Invoke-ResourceBudgetedProcess"),
        )
        self.assertLess(
            adapter.index("$authorizationIdentityDiffers"),
            adapter.index("& $runtime.implementation.single_flight_runner"),
        )
        self.assertNotIn("ThreeZoneAuthorizationReceipt", WORKFLOW_ENTRY.read_text(encoding="utf-8"))

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

    def test_v4_staged_solver_authorization_fails_before_child_creation(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        experiment_id = "staged_v4_early_gate_fixture"
        run_id = "20260815_235959__sim__cross__staged-v4-early-gate__n1"
        campaign = {
            "schema_version": 4,
            "status": "authorized",
            "experiments": [{
                "experiment_id": experiment_id,
                "run_id": run_id,
                "source_release_mode": "staged_grid2_restart",
                "staged_grid2_source_state": {},
            }],
        }
        diagnostics = INTEGRATION_ROOT / "config" / "diagnostics"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=diagnostics, delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(campaign, handle)
            campaign_path = Path(handle.name)
        child = (
            INTEGRATION_ROOT.parents[2] / "artifacts" / "projects" /
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer" /
            "runs" / run_id
        )
        try:
            completed = subprocess.run(
                [
                    pwsh, "-NoProfile", "-File", str(WORKFLOW_ENTRY),
                    "-Campaign", str(campaign_path),
                    "-ExperimentId", experiment_id, "-SolverAuthorized",
                ],
                cwd=INTEGRATION_ROOT.parents[1], text=True, encoding="utf-8",
                errors="replace", capture_output=True, check=False,
            )
        finally:
            campaign_path.unlink(missing_ok=True)
        self.assertNotEqual(completed.returncode, 0)
        output = completed.stdout + completed.stderr
        self.assertIn(
            "requires campaign v5 with an explicit loader authorization budget",
            output,
        )
        self.assertNotIn("CAMPAIGN_SOURCE_BINDINGS", output)
        self.assertFalse(child.exists())

    def test_runner_rejects_staged_loader_source_identity_mismatch(self) -> None:
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
    $node.Name -eq 'Assert-RfStagedLoaderSourceIdentity'
}}, $true)
if ($null -eq $fn) {{ throw 'staged loader source assertion is missing' }}
. ([scriptblock]::Create($fn.Extent.Text))
Assert-RfStagedLoaderSourceIdentity -ValidationSourceSha256 ('A' * 64) `
  -DeclaredSourceSha256 ('A' * 64) -PopulationSourceTableSha256 ('A' * 64)
try {{
  Assert-RfStagedLoaderSourceIdentity -ValidationSourceSha256 ('A' * 64) `
    -DeclaredSourceSha256 ('A' * 64) -PopulationSourceTableSha256 ('B' * 64)
  throw 'mismatch was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'source identity differs') {{ throw }}
}}
'STAGED_LOADER_SOURCE_IDENTITY_NEGATIVE=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1], text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "STAGED_LOADER_SOURCE_IDENTITY_NEGATIVE=PASS", completed.stdout
        )

    def test_pa_cache_policy_run_config_is_written_before_budget_and_cache_gates(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        initial_write = runner.index(
            "Write-RfPreCacheRunConfiguration `\n"
            "  -LifecycleStage 'pa_cache_policy_pending_budget_validation'"
        )
        budget_parse = runner.index("Initialize-RfIntegrationStageBudget")
        first_cache_gate = runner.index("Test-RfReusableCacheEntry")
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
        first_cache_gate = after_initialize.index("Test-RfReusableCacheEntry")
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
        overlay_verify = runner.index("overlay_interface_verify_resource_usage.json")
        topology_verify = runner.index("frontend_aperture_topology_resource_usage.json")
        self.assertLess(reflectron_gate, overlay_verify)
        self.assertLess(reflectron_gate, topology_verify)
        self.assertIn("-InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing')", runner)
        self.assertIn("single_flight_pa_cache_policy=$PaCachePolicy", runner)
        self.assertIn("pa_cache_dispositions=$paCacheDispositions", runner)

    def test_source_authority_scope_synthetic_matrix_is_strict(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        script = f"""
. '{RUNTIME_BINDING}'
$staged = [pscustomobject]@{{authority_scope='connection_lineage_only'}}
$nonstaged = [pscustomobject]@{{role='synthetic_nonstaged'}}
Assert-RfOatofSourceAuthorityScope -SourceContract $staged -StagedGrid2Mode $true
Assert-RfOatofSourceAuthorityScope -SourceContract $nonstaged -StagedGrid2Mode $false
$wrong = [pscustomobject]@{{authority_scope='source_population'}}
$failures = 0
foreach ($case in @(
  @($nonstaged,$true), @($wrong,$true), @($staged,$false)
)) {{
  try {{
    Assert-RfOatofSourceAuthorityScope -SourceContract $case[0] `
      -StagedGrid2Mode $case[1]
  }} catch {{ $failures++ }}
}}
if ($failures -ne 3) {{ throw "authority-scope negative cases differ: $failures" }}
'SOURCE_AUTHORITY_SCOPE_SYNTHETIC=PASS POSITIVE=2 NEGATIVE=3'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "SOURCE_AUTHORITY_SCOPE_SYNTHETIC=PASS POSITIVE=2 NEGATIVE=3",
            completed.stdout,
        )

    def test_historical_staged_source_contract_rejects_changed_stable_adapter(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        published = (
            INTEGRATION_ROOT.parents[2] / "artifacts" / "projects" /
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer" /
            "runs" /
            "20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r01" /
            "resolved_source_contract.json"
        )
        if not published.is_file():
            self.skipTest("published fail-closed staged preflight contract is unavailable")
        run_root = published.parent
        runtime_binding = (
            INTEGRATION_ROOT / "config" /
            "family_octupole_direct_mating_gap_0mm_runtime_binding.json"
        )
        script = f"""
. '{RUNTIME_BINDING}'
$sourcePath = '{published}'
$designPath = '{run_root / "upstream_resolved_design.json"}'
$runtime = Resolve-RfOatofRuntimeBinding `
  -RepoRoot '{INTEGRATION_ROOT.parents[1]}' `
  -ResolvedConnection '{run_root / "resolved_connection.json"}' `
  -RuntimeBinding '{runtime_binding}' `
  -ExpectedConnectionProfileId 'rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm' `
  -SourceBranchId simion `
  -ResolvedSourceContract $sourcePath `
  -ResolvedSourceContractSha256 (Get-FileHash $sourcePath -Algorithm SHA256).Hash `
  -UpstreamResolvedDesign $designPath `
  -UpstreamResolvedDesignSha256 (Get-FileHash $designPath -Algorithm SHA256).Hash
if ($runtime.resolved_source_contract.authority_scope -ne 'connection_lineage_only') {{
  throw 'resolved runtime authority scope differs'
}}
'PUBLISHED_STAGED_SOURCE_RUNTIME_PREFLIGHT=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "Resolved source adapter differs from its stable contract: sha256",
            completed.stdout + completed.stderr,
        )

    def test_schema_v4_staged_build_budget_constructs_cache_hit_run_identity(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        parent = (
            INTEGRATION_ROOT.parents[2] / "artifacts" / "projects" /
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer" /
            "runs" /
            "20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r03"
        )
        budget = parent / "resolved_engineering_budget.json"
        child_config = (
            parent.parent /
            "20260815_120000__sim__simion__rf-oatof-single-flight-gap0__n34__r03" /
            "run_config.json"
        )
        if not budget.is_file() or not child_config.is_file():
            self.skipTest("published schema-v4 staged BUILD failure evidence is unavailable")
        script = f"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  '{SINGLE_FLIGHT_RUNNER}', [ref]$null, [ref]$parseErrors
)
if ($parseErrors) {{ throw $parseErrors[0] }}
foreach ($functionName in @(
  'Read-RfFrozenResolvedBudgetDocument',
  'Set-RfStagedRunConfigurationIdentity'
)) {{
  $functionAst = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $functionName
  }}, $true)
  if ($null -eq $functionAst) {{ throw "staged compiler is missing: $functionName" }}
  . ([scriptblock]::Create($functionAst.Extent.Text))
}}
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$frozenBudget = Join-Path $tempRoot 'frozen_budget.json'
$externalBudget = Join-Path $tempRoot 'external_budget.json'
Copy-Item -LiteralPath '{budget}' -Destination $frozenBudget
Copy-Item -LiteralPath '{budget}' -Destination $externalBudget
$tamperedExternal = Get-Content -LiteralPath $externalBudget -Raw | ConvertFrom-Json
$tamperedExternal.single_flight_pa_cache_policy = 'require_existing'
$tamperedExternal.source_identity.authority_role = 'tampered_external_authority'
$tamperedExternal | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $externalBudget
$stageBudgetReceipt = [pscustomobject]@{{
  frozen_budget = $frozenBudget
  stage_budget = (Join-Path $tempRoot 'stage_budget.json')
}}
$budget = Read-RfFrozenResolvedBudgetDocument -StageBudgetReceipt $stageBudgetReceipt
$failedConfig = Get-Content '{child_config}' -Raw | ConvertFrom-Json
if ($budget.single_flight_pa_cache_policy -ne 'build_and_publish_if_missing' -or
    $budget.source_identity.authority_role -ne
      'staged_grid2_canonical_source_state' -or
    $failedConfig.parameters.pa_cache_dispositions.frontend.disposition -ne
      'built_and_published') {{
  throw 'run-local frozen staged BUILD evidence identity differs'
}}
$runConfig = [ordered]@{{
  upstream_source_identity = [ordered]@{{obsolete=$true}}
  parameters = [ordered]@{{
    pa_cache_dispositions = [ordered]@{{
      frontend = [ordered]@{{disposition='cache_hit'}}
    }}
  }}
}}
$lineage = [ordered]@{{run_id='lineage-only'}}
Set-RfStagedRunConfigurationIdentity -RunConfiguration $runConfig `
  -ResolvedBudgetDocument $budget -ConnectionLineageIdentity $lineage
if ($runConfig.Contains('upstream_source_identity') -or
    $runConfig.source_identity.authority_role -ne
      'staged_grid2_canonical_source_state' -or
    $runConfig.connection_lineage.authority_scope -ne
      'connection_lineage_only' -or
    $runConfig.parameters.pa_cache_dispositions.frontend.disposition -ne
      'cache_hit') {{
  throw 'staged cache-hit run configuration construction differs'
}}
Remove-Item -LiteralPath $tempRoot -Recurse -Force
'SCHEMA_V4_STAGED_BUILD_CACHE_HIT_RUN_CONFIG=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=INTEGRATION_ROOT.parents[1], text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "SCHEMA_V4_STAGED_BUILD_CACHE_HIT_RUN_CONFIG=PASS",
            completed.stdout,
        )

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
            check=False,
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

    def test_pulse_only_candidate_pilot_skips_downstream_pa_rebuilds(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertEqual(text.count("$SamplingMode -ne 'steady_candidate_pool' -and"), 2)
        self.assertIn("$programArguments += '--terminate-after-pulse'", text)

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
            "$env:OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0",
            text,
        )
        guard = text.index(
            "Frontend PA cache changed during construction-time SIMION access."
        )
        manifest_copy = text.index(
            "$frontendCacheManifestInput = Copy-RfCacheManifestInput"
        )
        fly_override = text.index(
            "$env:OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0"
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
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("'transient_disk_estimate'", runner)
        self.assertIn("$frontendCellMmX -ne $frontendCellMmY", runner)
        self.assertIn("$overlayCellMmX -ne $frontendCellMmX", runner)

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
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("default_source_region_diagnostic_profile_id", runner)
        self.assertIn("source_region_diagnostic_profiles", runner)
        self.assertIn("--source-region-diagnostic-profile-id", runner)
        self.assertIn("$isPrePulseTimeSeriesScreening -eq $false", runner)
        self.assertIn("$SamplingMode -notin @('steady_candidate_pool')", runner)
        self.assertNotIn("layout_resolved_axial_provisional_xy2_v1", runner)

    def test_full_flight_freezes_default_accelerator_phase_space_diagnostic(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("single_flight_accelerator_pre_pulse_phase_space.png", runner)
        self.assertIn("--phase-space-output", runner)
        self.assertIn("--phase-space-metadata", runner)
        self.assertIn("--phase-space-data", runner)
        self.assertIn("accelerator_pre_pulse_phase_space", runner)
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
            == "rf_oatof_accelerator_pre_pulse_phase_space_v1"
        )
        self.assertEqual(capability["required_event_plane"], "pre_pulse_state")
        self.assertEqual(capability["claim_class"], "DIAGNOSTIC_ONLY")

    def test_resolution_qualification_requires_full_bootstrap(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("[int]$BootstrapResamples = 0", text)
        self.assertIn("[switch]$ResolutionQualification", text)
        self.assertIn("$BootstrapResamples -ne 5000", text)
        self.assertIn(
            "$populationContract.analysis_randomness.bootstrap_resample_count", text
        )
        self.assertNotIn("'--bootstrap-resamples'", text)
        self.assertIn("[int]$_.resamples_valid -lt 4750", text)
        self.assertIn(
            "[double]$_.relative_95pct_interval_width -gt 0.10", text
        )

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
        for mode in (
            "staged_three_stage",
            "continuous_injection_full_population",
            "resolved_layout_pulse_ideal_linear_z_vz",
            "pre_pulse_restart",
            "pulse_eligible_conditional",
            "first_100_rows_in_frozen_file_order",
        ):
            self.assertIn(f"'{mode}'", runner)
        self.assertIn(
            'default { throw "Unsupported resolved population mode:', runner
        )

    def test_r03_baseline_population_is_strictmode_safe_without_paired_cohort(self) -> None:
        population = (
            INTEGRATION_ROOT.parents[2]
            / "artifacts/projects/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runs/20260815_160000__sim__cross__pulse-direct-real-rr__n100__r03/"
            "resolved_population_contract.json"
        )
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
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("R03_BASELINE_STRICTMODE=PASS", completed.stdout)
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "$populationContract.PSObject.Properties['paired_cohort_authority']",
            runner,
        )
        self.assertIn("$EligiblePopulationCount = if ($hasPairedCohort)", runner)

    def test_paired_n100_field_authority_is_run_local_contract(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        registrar = PULSE_RESOLUTION_REGISTRAR.read_text(encoding="utf-8")
        self.assertNotIn("OATOF_IDEAL_ACCEL_STAGE1_ENABLE", runner)
        self.assertNotIn("OATOF_IDEAL_ACCEL_STAGE2_ENABLE", runner)
        self.assertNotIn("single_flight_ideal_accel_stage1_enable", runner)
        self.assertIn("ResolvedRegionFieldContractSha256", runner)
        self.assertIn("ResolvedRegionFieldSemanticSha256", runner)
        self.assertNotIn("PulseResolutionBaselineCheckpoints", runner)
        self.assertIn("inputs/pulse_resolution_baseline_evidence.json", adapter)
        self.assertIn("$PulseResolutionRegistrationAuthoritySha256", runner)
        self.assertIn("--registration-authority-sha256", runner)
        self.assertIn('campaign.get("pulse_resolution_baseline_evidence", {})', registrar)
        self.assertIn('baseline_evidence.get("paired_checkpoint_rows", [])', registrar)
        self.assertIn("'pulse_resolution_' + $PulseResolutionExperimentId + '_result.json'", runner)
        self.assertIn("$PulseResolutionFieldProfileId -eq 'accelerator_real_pa'", runner)
        self.assertIn("execution_status=$expectedStatus", runner)
        self.assertIn("$PulseResolutionExperimentId + '_promotion_receipt.json'", runner)


if __name__ == "__main__":
    unittest.main()
