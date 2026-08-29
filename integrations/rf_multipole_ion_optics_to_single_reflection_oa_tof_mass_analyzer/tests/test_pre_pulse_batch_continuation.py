from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pre_pulse_batch_continuation import (
    build_continuation_plan,
)


def _terminal(particle_id: int) -> str:
    return (
        "TRACE: pre_pulse_screening_terminal "
        f"ion={particle_id} particle_id={particle_id} instrument_time_us=3 "
        "x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 "
        "terminal_reason=splat"
    )


def _predecessor(root: Path, batches: list[list[int]], logs: list[list[str]]) -> tuple[Path, str]:
    run = root / "predecessor"
    (run / "inputs").mkdir(parents=True)
    (run / "logs").mkdir()
    count = sum(len(batch) for batch in batches)
    contract = run / "inputs" / "pre_pulse_time_series_screening_contract.json"
    contract.write_text("{}\n", encoding="utf-8")
    mother = run / "inputs" / "mother_particle_source.csv"
    state = run / "inputs" / "single_flight_initial_global_state.csv"
    row_map = run / "inputs" / "single_flight_particle_row_map.csv"
    mother.write_text("particle_id,source\n1,fixture\n", encoding="utf-8")
    state.write_text("particle_id,state\n1,fixture\n", encoding="utf-8")
    row_map.write_text("source_particle_id\n" + "\n".join(str(index) for index in range(1, count + 1)) + "\n", encoding="utf-8")
    plan = {
        "role": "simion_single_wave_particle_batch_plan",
        "batches": [
            {
                "index": index, "particle_id_min": ids[0], "particle_id_max": ids[-1],
                "count": len(ids), "simion_particle_id_offset": ids[0] - 1,
            }
            for index, ids in enumerate(batches, start=1)
        ],
    }
    (run / "inputs" / "simion_execution_batch_plan.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )
    (run / "run_config.json").write_text(json.dumps({"parameters": {
        "execution_mode": "real_pa_rf_pre_pulse_time_series", "particle_count": count,
        "launched_particle_count": count,
    }, "inputs": {
        "pre_pulse_time_series_contract": str(contract.resolve()),
        "simion_execution_batch_plan": str((run / "inputs" / "simion_execution_batch_plan.json").resolve()),
        "mother_particle_source": str(mother.resolve()),
        "initial_global_state": str(state.resolve()), "particle_row_map": str(row_map.resolve()),
    }}), encoding="utf-8")
    for index, lines in enumerate(logs, start=1):
        (run / "logs" / f"simion__batch{index:02d}.stdout.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    manifest_outputs = []
    for path in (run / "logs").glob("*.stdout.log"):
        manifest_outputs.append({"path": str(path), "sha256": file_sha256(path)})
    manifest_inputs = {key: {"path": str(path.resolve()), "exists": True, "sha256": file_sha256(path)} for key, path in {
        "pre_pulse_time_series_contract": contract,
        "simion_execution_batch_plan": run / "inputs" / "simion_execution_batch_plan.json",
        "mother_particle_source": mother, "initial_global_state": state, "particle_row_map": row_map,
    }.items()}
    (run / "run_manifest.json").write_text(json.dumps({
        "role": "simulation_run_manifest", "status": "interrupted",
        "run_config": {"sha256": file_sha256(run / "run_config.json")},
        "inputs": manifest_inputs, "outputs": manifest_outputs,
    }), encoding="utf-8")
    return run, file_sha256(contract)


class PrePulseBatchContinuationTests(unittest.TestCase):
    @staticmethod
    def _build(predecessor: Path, contract_sha: str, output: Path, ids: list[int]) -> dict:
        inputs = predecessor / "inputs"
        return build_continuation_plan(
            predecessor_run_dir=predecessor, particle_ids=ids,
            expected_contract_sha256=contract_sha,
            mother_particle_source=inputs / "mother_particle_source.csv",
            initial_global_state=inputs / "single_flight_initial_global_state.csv",
            particle_row_map=inputs / "single_flight_particle_row_map.csv",
            output_dir=output,
        )

    def test_recovery_wiring_is_pre_pulse_only_and_keeps_imported_traces(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runner = (root / "runtime" / "run_single_flight.ps1").read_text(encoding="utf-8")
        adapter = (
            root / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[string]$ResumePrePulseFromRun = ''", runner)
        self.assertIn("pre_pulse_batch_continuation", runner)
        self.assertIn("$stdoutFiles += $importedCompletedTraceFiles", runner)
        self.assertIn("if ($prePulseTimeSeriesScreening)", adapter)
        self.assertIn("$runnerArguments.ResumePrePulseFromRun", adapter)

    def test_preserves_each_independent_completed_or_terminal_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, contract_sha = _predecessor(root, [[1, 2], [3, 4], [5, 6]], [
                [_terminal(1), _terminal(2), "status,Fly completed. 2 splats, 1 seconds"],
                [_terminal(3)],
                [_terminal(5), _terminal(6), "status,Fly completed. 2 splats, 1 seconds"],
            ])
            result = self._build(predecessor, contract_sha, root / "continuation", list(range(1, 7)))
        self.assertEqual(result["completed_particle_count"], 5)
        self.assertEqual(result["replay_particle_count"], 1)
        self.assertEqual(
            [item["replay_particle_count"] for item in result["batches"]], [0, 1, 0]
        )

    def test_rejects_noncontiguous_terminal_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, contract_sha = _predecessor(root, [[1, 2]], [[_terminal(2)]])
            with self.assertRaisesRegex(ContractError, "contiguous prefix"):
                self._build(predecessor, contract_sha, root / "continuation", [1, 2])

    def test_second_recovery_reuses_prior_imported_trace_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ancestor, contract_sha = _predecessor(root / "ancestor", [[1, 2], [3, 4]], [
                [_terminal(1), _terminal(2), "status,Fly completed. 2 splats, 1 seconds"], [],
            ])
            predecessor, _ = _predecessor(root / "predecessor", [[1, 2], [3, 4]], [
                [], [_terminal(3), _terminal(4), "status,Fly completed. 2 splats, 1 seconds"],
            ])
            continuation_root = predecessor / "inputs" / "pre_pulse_batch_continuation"
            self._build(ancestor, contract_sha, continuation_root, [1, 2, 3, 4])
            config_path = predecessor / "run_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["inputs"]["simion_execution_batch_plan"] = str(
                (continuation_root / "simion_execution_batch_plan.json").resolve()
            )
            config["inputs"]["simion_batch_continuation_plan"] = str(
                (continuation_root / "simion_batch_continuation_plan.json").resolve()
            )
            config_path.write_text(json.dumps(config), encoding="utf-8")
            manifest_path = predecessor / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["run_config"]["sha256"] = file_sha256(config_path)
            for role, relative in {
                "simion_execution_batch_plan": "simion_execution_batch_plan.json",
                "simion_batch_continuation_plan": "simion_batch_continuation_plan.json",
            }.items():
                path = continuation_root / relative
                manifest["inputs"][role] = {
                    "path": str(path.resolve()), "exists": True, "sha256": file_sha256(path),
                }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self._build(predecessor, contract_sha, root / "continuation", [1, 2, 3, 4])
        self.assertEqual(result["completed_particle_count"], 4)
        self.assertEqual(result["replay_particle_count"], 0)

    def test_rejects_completed_sentinel_without_full_terminal_census(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor, contract_sha = _predecessor(root, [[1, 2]], [[
                _terminal(1), "status,Fly completed. 2 splats, 1 seconds",
            ]])
            with self.assertRaisesRegex(ContractError, "completion sentinel"):
                self._build(predecessor, contract_sha, root / "continuation", [1, 2])


if __name__ == "__main__":
    unittest.main()
