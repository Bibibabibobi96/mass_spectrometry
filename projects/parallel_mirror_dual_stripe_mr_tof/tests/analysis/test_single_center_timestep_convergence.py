from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.single_center_timestep_convergence import (
    analyze_timestep_convergence,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _event(kind: str, time: float, *, z: float, vz: float) -> str:
    extra = " k=25.5 half_cycles=51" if kind == "drift_phase_return" else ""
    return (
        f"MRTOF_EVENT {kind} ion=1{extra} t_us={time} x_mm=0.1 y_mm=-2 z_mm={z} "
        f"vx_mm_us=0.01 vy_mm_us=-1 vz_mm_us={vz}\n"
    )


def _write_run(root: Path, name: str, step: float, shift: float = 0.0) -> Path:
    run = root / name
    (run / "results").mkdir(parents=True)
    (run / "logs").mkdir()
    identity_inputs = {
        key: {"path": f"C:/frozen/{key}", "bytes": 10, "sha256": "A" * 64}
        for key in (
            "geometry_run_manifest", "mirror_run_manifest", "stripe_run_manifest",
            "accelerator_run_manifest", "trajectory_numerics_contract", "flight_program",
            "mirror_cycle_counter", "voltage_map", "native_corridor_bank_run_manifest",
            "native_corridor_bank_publication", "native_corridor_runtime_receipt",
            "native_system_runtime_bundle", "native_global_fallback_pa",
            "read_only_accelerator_pa", "read_only_detector_pa", "frozen_source_fly2",
        )
    }
    identity_inputs["accelerator_pulse_schedule"] = None
    pulse = {"mode": "fixed_global_time", "pulse_off_time_us": 1.8}
    trial = {
        "status": "materialized", "flight_scope": "complete_three_dimensional_static_return",
        "source_particle_count": 1, "source_expected_particle_ids": [1],
        "source_selection": None, "source_position_project_mm": [0, -55, 37],
        "source_direction_project": [0, 1, 0], "source_time_of_birth_us": 0,
        "source_clock_basis": "global", "selected_axial_energy_per_charge_v": 4000,
        "source_slow_kinetic_energy_per_charge_v": 5, "particle_mass_th": 524,
        "charge_state": 1, "mirror_voltages_v": [0, 1, 2, 3, 4],
        "stripe_biases_v": [-25, 50], "prism_voltages_v": [191, -192],
        "accelerator_endpoint_voltages_v": [4900, 3800, 0],
        "accelerator_ring_voltages_v": [3, 2, 1],
        "analyzer_electrode_voltages_v": list(range(20)), "detector_box_mm": [0] * 6,
        "drift_phase_contract": {"target_period_ratio": 25.5},
        "detector_return_policy_authority": {"policy": "current"},
        "target_drift_period_ratio": 25.5, "target_half_oscillation_count": 51,
        "runtime_fast_adjust_enable": False, "accelerator_instance": 3,
        "accelerator_pulse": pulse,
        "trajectory_profile": {"profile_id": name, "maximum_step_us": step,
                               "trajectory_quality": 8, "purpose": "test"},
    }
    observation = {
        "status": "full_drift_observed",
        "static_return_diagnostic": {
            "status": "detector_hit", "event_contract_ok": True, "errors": [],
            "required_event_order": ["drift_phase_return", "return_p2_entry",
                                     "return_p2_pass", "return_positive_mirror_turn", "detector"],
        },
    }
    summary = {"status": "success"}
    config = {"parameters": {"flight_scope": trial["flight_scope"]}}
    log = (
        _event("drift_phase_return", 10 + shift, z=-280, vz=0)
        + _event("return_positive_mirror_turn", 20 + shift, z=280, vz=0)
        + f"MRTOF_EVENT detector ion=1 direction_z=-1 t_us={30 + shift} x_mm=0.1 y_mm=-2 z_mm=97\n"
        + f"MRTOF_EVENT terminal ion=1 splat=1 t_us={30 + shift} x_mm=0.1 y_mm=-2 z_mm=97 "
          "vx_mm_us=0.01 vy_mm_us=-1 vz_mm_us=-40 turns=51 central_crossings=51\n"
    )
    files = {
        run / "summary.json": summary,
        run / "run_config.json": config,
        run / "results" / "two_prism_trial_materialization.json": trial,
        run / "results" / "two_prism_trial_observation.json": observation,
    }
    for path, value in files.items():
        path.write_text(json.dumps(value), encoding="utf-8")
    log_path = run / "logs" / "native_two_prism_flight.log"
    log_path.write_text(log, encoding="utf-8")
    outputs = [{"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": _sha(path)}
               for path in (*files, log_path) if path.name != "run_config.json"]
    manifest = {
        "run_id": name, "project": "parallel_mirror_dual_stripe_mr_tof",
        "mode": "finite_3d_two_prism_voltage_trial", "status": "success",
        "inputs": identity_inputs, "outputs": outputs,
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


class SingleCenterTimestepConvergenceTest(unittest.TestCase):
    def test_reports_three_levels_and_signed_adjacent_differences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [
                _write_run(root, "fine", 0.00002, 0.001),
                _write_run(root, "coarse", 0.002, 0.0),
                _write_run(root, "middle", 0.0002, 0.0008),
            ]
            result = analyze_timestep_convergence(runs)
            self.assertEqual(result["status"], "candidate_diagnostic")
            self.assertIsNone(result["acceptance_threshold"])
            self.assertEqual(
                [item["maximum_step_us"] for item in result["levels"]],
                [0.002, 0.0002, 0.00002],
            )
            delta = result["adjacent_differences"][0]["events"]["detector"]
            self.assertAlmostEqual(delta["finer_minus_coarser"]["t_us"], 0.0008)
            self.assertEqual(
                result["levels"][0]["event_provenance"]["detector_velocity_source"],
                "terminal_matched_to_detector",
            )

    def test_rejects_a_voltage_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [_write_run(root, name, step) for name, step in (
                ("coarse", 0.002), ("middle", 0.0002), ("fine", 0.00002),
            )]
            trial_path = runs[-1] / "results" / "two_prism_trial_materialization.json"
            trial = json.loads(trial_path.read_text(encoding="utf-8"))
            trial["prism_voltages_v"][0] += 1
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            manifest_path = runs[-1] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = next(item for item in manifest["outputs"] if Path(item["path"]) == trial_path.resolve())
            record.update(bytes=trial_path.stat().st_size, sha256=_sha(trial_path))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "identity differs"):
                analyze_timestep_convergence(runs)

    def test_rejects_a_checkpoint_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [_write_run(root, name, step) for name, step in (
                ("coarse", 0.002), ("middle", 0.0002), ("fine", 0.00002),
            )]
            manifest_path = runs[-1] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "checkpoint"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "successful MR-TOF trial"):
                analyze_timestep_convergence(runs)


if __name__ == "__main__":
    unittest.main()
