from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.full_flight_batch_continuation import (
    FROZEN_INPUT_ROLES,
    build_continuation_plan,
)


def _release(local_id: int, particle_id: int) -> str:
    return (
        f"TRACE: source_release ion={local_id} particle_id={particle_id} "
        "instrument_time_us=0 source_instance=4"
    )


def _terminal(local_id: int) -> str:
    return (
        f"TRACE: handoff_terminal_raw ion={local_id} instance=4 "
        "instrument_time_us=1 x_mm=0 y_mm=0 z_mm=0 "
        "vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0"
    )


def _fixture(root: Path) -> tuple[Path, Path]:
    predecessor = root / "predecessor"
    current = root / "current"
    for run in (predecessor, current):
        (run / "inputs").mkdir(parents=True)
        (run / "logs").mkdir()

    program = {
        "source_release_mode": "continuous_frontend",
        "terminate_after_pulse": False,
        "clock_basis": "canonical_instrument_time_us",
        "upstream_bridge_contract_sha256": "A" * 64,
        "accelerator_main_contract_sha256": "B" * 64,
    }
    parent_inputs: dict[str, str] = {}
    current_inputs: dict[str, str] = {}
    for role in FROZEN_INPUT_ROLES:
        name = f"{role}.json"
        if role == "particle_row_map":
            name = "particle_row_map.csv"
            content = "simulation_particle_id,source_particle_id\n1,1\n2,2\n3,3\n4,4\n"
        elif role == "program_metadata":
            content = json.dumps(program)
        else:
            content = role + "\n"
        for run, registry in ((predecessor, parent_inputs), (current, current_inputs)):
            path = run / "inputs" / name
            path.write_text(content, encoding="utf-8")
            registry[role] = str(path.resolve())
    plan = {
        "role": "simion_single_wave_particle_batch_plan",
        "batches": [
            {"index": 1, "particle_id_min": 1, "particle_id_max": 2, "count": 2},
            {"index": 2, "particle_id_min": 3, "particle_id_max": 4, "count": 2},
        ],
    }
    plan_path = predecessor / "inputs" / "simion_execution_batch_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    parent_inputs["simion_execution_batch_plan"] = str(plan_path.resolve())
    parameters = {
        "particle_count": 4,
        "launched_particle_count": 4,
        "clock_basis": "canonical_instrument_time_us",
        "pulse_time_us": 10.0,
        "pulse_width_us": 2.0,
        "pa_cache_dispositions": {
            role: {"role": f"cache_{role}", "key": str(index) * 64}
            for index, role in enumerate((
                "frontend", "full_coarse_bridge", "fine_upstream",
                "accelerator_main", "accelerator_entrance_local",
                "flight_tube", "reflectron",
            ), start=1)
        },
    }
    parent_config = predecessor / "run_config.json"
    parent_config.write_text(json.dumps({
        "parameters": parameters, "inputs": parent_inputs,
    }), encoding="utf-8")
    current_config = current / "run_config.json"
    current_config.write_text(json.dumps({
        "parameters": parameters, "inputs": current_inputs,
    }), encoding="utf-8")
    complete = predecessor / "logs" / "simion__batch01.stdout.log"
    complete.write_text("\n".join((
        "solver header", _release(1, 1), "TRACE: pre_pulse_state ion=1 fixture=1",
        _terminal(1), _release(2, 2), _terminal(2),
        "status,Fly completed. 2 splats, 1 seconds",
    )) + "\n", encoding="utf-8")
    partial = predecessor / "logs" / "simion__batch02.stdout.log"
    partial.write_text(_release(1, 3) + "\n", encoding="utf-8")
    manifest_inputs = {
        role: {"path": path, "exists": True, "sha256": file_sha256(Path(path))}
        for role, path in parent_inputs.items()
    }
    (predecessor / "run_manifest.json").write_text(json.dumps({
        "role": "simulation_run_manifest", "run_id": "predecessor",
        "status": "interrupted",
        "run_config": {"sha256": file_sha256(parent_config)},
        "inputs": manifest_inputs,
        "outputs": [
            {"path": str(complete), "sha256": file_sha256(complete)},
            {"path": str(partial), "sha256": file_sha256(partial)},
        ],
    }), encoding="utf-8")
    return predecessor, current_config


class FullFlightBatchContinuationTests(unittest.TestCase):
    def test_imports_complete_prefix_and_preserves_all_stdout_trace_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, current = _fixture(root)
            result = build_continuation_plan(
                predecessor_run_dir=predecessor,
                current_run_config=current,
                output_dir=root / "continuation",
            )
            imported = Path(result["batches"][0]["imported_completed_trace"]["path"])
            text = imported.read_text(encoding="utf-8")
        self.assertEqual(result["completed_particle_count"], 2)
        self.assertEqual(result["replay_particle_count"], 2)
        self.assertIn("solver header", text)
        self.assertIn("TRACE: pre_pulse_state ion=1 fixture=1", text)

    def test_rejects_pa_generation_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, current = _fixture(root)
            config = json.loads(current.read_text(encoding="utf-8"))
            config["parameters"]["pa_cache_dispositions"]["accelerator_main"]["key"] = "F" * 64
            current.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "geometry, field, clock or PA"):
                build_continuation_plan(
                    predecessor_run_dir=predecessor,
                    current_run_config=current,
                    output_dir=root / "continuation",
                )

    def test_requires_one_release_and_one_terminal_per_particle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, current = _fixture(root)
            batch = predecessor / "logs" / "simion__batch01.stdout.log"
            with batch.open("a", encoding="utf-8") as handle:
                handle.write(_terminal(2) + "\n")
            manifest_path = predecessor / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for output in manifest["outputs"]:
                if Path(output["path"]) == batch:
                    output["sha256"] = file_sha256(batch)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "terminal particle identity"):
                build_continuation_plan(
                    predecessor_run_dir=predecessor,
                    current_run_config=current,
                    output_dir=root / "continuation",
                )

    def test_all_completed_batches_require_no_solver_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, current = _fixture(root)
            batch = predecessor / "logs" / "simion__batch02.stdout.log"
            batch.write_text("\n".join((
                _release(1, 3), _terminal(1), _release(2, 4), _terminal(2),
                "status,Fly completed. 2 splats, 1 seconds",
            )) + "\n", encoding="utf-8")
            manifest_path = predecessor / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for output in manifest["outputs"]:
                if Path(output["path"]) == batch:
                    output["sha256"] = file_sha256(batch)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = build_continuation_plan(
                predecessor_run_dir=predecessor,
                current_run_config=current,
                output_dir=root / "continuation",
            )
        self.assertEqual(result["completed_particle_count"], 4)
        self.assertEqual(result["replay_particle_count"], 0)

    def test_runner_and_adapter_expose_full_flight_recovery_without_changing_pre_pulse(self) -> None:
        integration = Path(__file__).resolve().parents[1]
        runner = (integration / "runtime" / "run_single_flight.ps1").read_text(encoding="utf-8")
        adapter = (integration / "workflows" / "family_source_closure" / "adapter.ps1").read_text(encoding="utf-8")
        self.assertIn("[string]$ResumeFullFlightFromRun = ''", runner)
        self.assertIn("full_flight_batch_continuation", runner)
        self.assertIn("$analysisBatchRecords", runner)
        self.assertIn("if ($processSpecifications.Count -eq 0)", runner)
        self.assertIn("only need deterministic merge/analysis", runner)
        self.assertIn("function Resolve-RfFullFlightContinuationChild", adapter)
        self.assertIn("simion_batch_continuation_plan", adapter)
        self.assertIn("$runnerArguments.ResumeFullFlightFromRun", adapter)
        self.assertIn("$runnerArguments.ResumePrePulseFromRun", adapter)

    def test_pwsh_discovers_completed_child_across_fresh_parent_timestamp(self) -> None:
        integration = Path(__file__).resolve().parents[1]
        adapter = integration / "workflows" / "family_source_closure" / "adapter.ps1"
        with tempfile.TemporaryDirectory() as directory:
            script = r"""
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_ADAPTER_PATH, [ref]$null, [ref]$errors
)
if ($errors) { throw $errors[0] }
foreach ($name in @(
    'Get-RfCompletedFullFlightBatchStdout',
    'Resolve-RfFullFlightContinuationChild'
  )) {
  $functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $name
  }, $true)
  if ($null -eq $functionAst) { throw "missing helper: $name" }
  . ([scriptblock]::Create($functionAst.Extent.Text))
}
function Write-Parent([string]$RunId) {
  $path = Join-Path $env:RF_RUNS_ROOT $RunId
  New-Item -ItemType Directory -Path $path -Force | Out-Null
  @{run_id=$RunId;status='interrupted'} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $path 'run_manifest.json')
  @{campaign_id='campaign';experiment_id='experiment';experiment_row_sha256=('A'*64)} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $path 'run_config.json')
}
$oldParent = '20260905_172230__sim__cross__same-experiment__n5000'
$freshParent = '20260905_180452__sim__cross__same-experiment__n5000'
Write-Parent $oldParent
$childId = '20260905_172230__sim__simion__rf-oatof-single-flight-gap102p4__n5000'
$child = Join-Path $env:RF_RUNS_ROOT $childId
New-Item -ItemType Directory -Path (Join-Path $child 'logs') -Force | Out-Null
@{run_id=$childId;status='interrupted'} | ConvertTo-Json |
  Set-Content -LiteralPath (Join-Path $child 'run_manifest.json')
@{inputs=@{}} | ConvertTo-Json |
  Set-Content -LiteralPath (Join-Path $child 'run_config.json')
'status,Fly completed. 556 splats' |
  Set-Content -LiteralPath (Join-Path $child 'logs\simion__batch01.stdout.log')
$resolved = Resolve-RfFullFlightContinuationChild `
  -CurrentParentRunId $freshParent -RunsRoot $env:RF_RUNS_ROOT `
  -CampaignId campaign -ExperimentId experiment -ExperimentRowSha256 ('A'*64) `
  -ConnectorGapLabel 102p4 -ParticleCount 5000
if ($resolved -ne $child) {
  throw "cross-timestamp child was not discovered: $resolved"
}
Write-Output 'CROSS_TIMESTAMP_FULL_FLIGHT_CONTINUATION=PASS'
"""
            environment = os.environ.copy()
            environment.update({
                "RF_ADAPTER_PATH": str(adapter),
                "RF_RUNS_ROOT": directory,
            })
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=60,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("CROSS_TIMESTAMP_FULL_FLIGHT_CONTINUATION=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
