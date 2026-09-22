from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.r27_source_return_correlation import (
    _linear_detrend,
    _return_lip_event,
    analyze_r27_source_return_correlation,
    main,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture(root: Path, *, collision_count: int = 12) -> Path:
    source = root / "source"
    run = root / "run"
    source.mkdir()
    (run / "logs").mkdir(parents=True)
    (run / "results").mkdir()
    (run / "simion").mkdir()
    state = source / "bunch_source_states.csv"
    fields = ["particle_id", "tob_us", "mass_th", "charge_e", "kinetic_energy_ev",
              "x_mm", "y_mm", "z_mm", "direction_x", "direction_y", "direction_z"]
    with state.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for ion in range(1, 101):
            writer.writerow({
                "particle_id": ion, "tob_us": 0, "mass_th": 524, "charge_e": 1,
                "kinetic_energy_ev": 4.95 + ion / 1000, "x_mm": ion / 100,
                "y_mm": -55 + ion / 1000, "z_mm": 36 + ion / 200,
                "direction_x": (ion - 50) / 10000, "direction_y": 1 - ion / 100000,
                "direction_z": (ion - 50) / 20000,
            })
    fly2 = source / "bunch_source.fly2"
    fly2.write_text("\n".join("standard_beam {" for _ in range(100)), encoding="utf-8")
    receipt_source = source / "bunch_source_receipt.json"
    receipt = {
        "schema_version": 1, "role": "mrtof_deterministic_ideal_bunch_source",
        "status": "materialized", "sampling_method": "center_first_halton_position_energy_angle_v1",
        "clock_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
        "species": {"mass_th": 524.0, "charge_e": 1}, "common_time_of_birth_us": 0.0,
        "particle_count": 100, "mother_particle_count": 1000,
        "expected_particle_ids": list(range(1, 101)),
        "expected_particle_ids_sha256": hashlib.sha256(
            json.dumps(list(range(1, 101)), separators=(",", ":")).encode()
        ).hexdigest(),
        "state_table": _record(state), "fly2": _record(fly2),
    }
    _write_json(receipt_source, receipt)
    source_config = source / "run_config.json"
    _write_json(source_config, {"schema_version": 1, "role": "test_source_config"})
    source_definition = source / "source_definition.json"
    _write_json(source_definition, {"role": "unused_by_analysis_but_manifest_bound"})
    source_manifest = source / "run_manifest.json"
    _write_json(source_manifest, {
        "project": "parallel_mirror_dual_stripe_mr_tof",
        "mode": "deterministic_bunch_source_materialization", "status": "success",
        "run_config": _record(source_config),
        "inputs": {"bunch_source_definition": _record(source_definition)},
        "outputs": [_record(state), _record(fly2), _record(receipt_source)],
    })
    receipt_copy = run / "simion" / "bunch_source_receipt.json"
    receipt_copy.write_bytes(receipt_source.read_bytes())
    log = run / "logs" / "native_two_prism_flight.log"
    lines: list[str] = []
    collisions = set(range(101 - collision_count, 101))
    for ion in range(1, 101):
        target_y = (ion - 50) / 10
        lip_y = target_y - 6.5
        lines.append(
            f"MRTOF_EVENT target_k_phase_sample ion={ion} k=25.5 half_cycles=51 t_us=10 "
            f"x_mm=0 y_mm={target_y} z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0"
        )
        if ion in collisions:
            lines.append(
                f"MRTOF_EVENT terminal ion={ion} splat=-1 t_us=11 x_mm=0 y_mm={lip_y} "
                "z_mm=-97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40 turns=51 central_crossings=51"
            )
        else:
            lines.append(
                f"MRTOF_EVENT patch_interface ion={ion} name=mirror_turn_negative__z_max "
                f"region=mirror_turn_negative face=z_max n=54 direction=1 t_us=11 x_mm=0 y_mm={lip_y} "
                "z_mm=-97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40"
            )
            lines.append(
                f"MRTOF_EVENT return_p2_entry ion={ion} t_us={11.1 + ion / 100000} "
                "x_mm=0 y_mm=-8 z_mm=-26 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40"
            )
            lines.append(
                f"MRTOF_EVENT return_p2_pass ion={ion} t_us={11.2 + ion / 200000} "
                "x_mm=0 y_mm=-11 z_mm=26 vx_mm_us=0 vy_mm_us=-3 vz_mm_us=40"
            )
            lines.append(
                f"MRTOF_EVENT return_positive_mirror_turn ion={ion} t_us={11.6 + ion / 50000} "
                "x_mm=0 y_mm=-32 z_mm=282 vx_mm_us=0 vy_mm_us=-3 vz_mm_us=0"
            )
            lines.append(
                f"MRTOF_EVENT detector ion={ion} direction_z=-1 t_us={12 + ion / 10000} "
                "x_mm=0 y_mm=-48 z_mm=97"
            )
            lines.append(
                f"MRTOF_EVENT terminal ion={ion} splat=1 t_us={12 + ion / 10000} x_mm=0 y_mm=-48 z_mm=97 "
                "vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40 turns=51 central_crossings=51"
            )
    lines.append("status,Fly completed. 100 splats")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    observation = run / "results" / "two_prism_trial_observation.json"
    _write_json(observation, {"cohort_analysis": {
        "event_integrity_passed": True, "expected_particle_count": 100,
        "observed_particle_ids": list(range(1, 101)),
        "electrode_collision_count": collision_count,
        "detector_hit_count": 100 - collision_count,
    }})
    run_config = run / "run_config.json"
    _write_json(run_config, {"schema_version": 1, "role": "test_flight_config"})
    unused_input = run / "simion" / "unused_but_manifest_bound.json"
    _write_json(unused_input, {"role": "provenance_only"})
    manifest = run / "run_manifest.json"
    _write_json(manifest, {
        "project": "parallel_mirror_dual_stripe_mr_tof",
        "mode": "finite_3d_two_prism_voltage_trial", "status": "success",
        "run_config": _record(run_config),
        "inputs": {
            "bunch_source_receipt": _record(receipt_copy),
            "bunch_source_run_manifest": _record(source_manifest),
            "unused_provenance": _record(unused_input),
        },
        "outputs": [_record(log), _record(observation)],
    })
    return run


class R27SourceReturnCorrelationTests(unittest.TestCase):
    def test_invariant_source_coordinate_retains_raw_width_without_fake_slope(self) -> None:
        source_value = 36.858373606822035
        result = _linear_detrend(
            [source_value, source_value, source_value], [1.0, 1.1, 1.2],
            mass_resolution_reference_us=1.1,
        )
        self.assertEqual(result["status"], "invariant_source_coordinate__detrend_not_defined")
        self.assertEqual(result["source_value"], source_value)
        self.assertIsNone(result["slope_us_per_mm"])
        self.assertIsNone(result["linearly_detrended_fwhm_us"])

    def test_return_lip_interpolates_current_five_region_interfaces(self) -> None:
        events = [
            {
                "kind": "patch_interface", "ion": 1, "t_us": 10.0,
                "name": "handoff_negative_bridge_to_mirror__z_plane",
                "z_mm": -105.0, "x_mm": 0.0, "y_mm": -5.0,
                "vx_mm_us": 0.0, "vy_mm_us": -1.0, "vz_mm_us": 40.0,
            },
            {
                "kind": "patch_interface", "ion": 1, "t_us": 11.0,
                "name": "handoff_negative_central_to_bridge__z_plane",
                "z_mm": -72.0, "x_mm": 0.0, "y_mm": -8.3,
                "vx_mm_us": 0.0, "vy_mm_us": -1.0, "vz_mm_us": 40.0,
            },
        ]
        result = _return_lip_event(events, 1, 9.0)
        self.assertEqual(result["kind"], "interpolated_patch_interface")
        self.assertEqual(result["z_mm"], -97.0)
        self.assertAlmostEqual(result["y_mm"], -5.8)

    def test_complete_cohort_and_associations_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_r27_source_return_correlation(_fixture(Path(directory)))
        self.assertEqual(result["cohort"]["particle_count"], 100)
        self.assertEqual(len(result["particles"]), 100)
        self.assertEqual(result["cohort"]["electrode_collision_count"], 12)
        self.assertIsNone(result["acceptance_threshold"])
        self.assertEqual(result["associations"]["tob_us"]["status"],
                         "invariant__association_not_defined")
        self.assertGreater(result["associations"]["x_mm"]["target_k_y"]["pearson_r"], 0.99)
        self.assertIn("balanced_accuracy",
                      result["associations"]["x_mm"]["terminal_collision"]["leave_one_out_threshold"])
        self.assertEqual(result["timing_diagnostic"]["stages"]["detector"]["sample_count"], 88)
        self.assertGreater(
            result["timing_diagnostic"]["stages"]["detector"]["source_z_pearson_r"],
            0.99,
        )

    def test_timing_diagnostic_survives_invariant_or_small_loss_class(self) -> None:
        for collision_count, expected_status in (
            (0, "invariant_terminal_class__association_not_defined"),
            (7, "minority_class_below_10__threshold_not_reported"),
        ):
            with self.subTest(collision_count=collision_count), tempfile.TemporaryDirectory() as directory:
                result = analyze_r27_source_return_correlation(
                    _fixture(Path(directory), collision_count=collision_count)
                )
            terminal = result["associations"]["x_mm"]["terminal_collision"]
            self.assertEqual(terminal["status"], expected_status)
            self.assertIsNone(terminal["leave_one_out_threshold"])
            self.assertEqual(
                result["timing_diagnostic"]["stages"]["detector"]["sample_count"],
                100 - collision_count,
            )
        self.assertIn(
            "linearly_detrended_fwhm_us",
            result["timing_diagnostic"]["detector_tof_vs_source_z"],
        )

    def test_rejects_incomplete_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory))
            observation = run / "results" / "two_prism_trial_observation.json"
            value = json.loads(observation.read_text(encoding="utf-8"))
            value["cohort_analysis"]["observed_particle_ids"].pop()
            _write_json(observation, value)
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
            manifest["outputs"][1] = _record(observation)
            _write_json(run / "run_manifest.json", manifest)
            with self.assertRaisesRegex(CandidateContractError, "complete N=100"):
                analyze_r27_source_return_correlation(run)

    def test_rejects_changed_raw_log_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory))
            with (run / "logs" / "native_two_prism_flight.log").open("a", encoding="utf-8") as stream:
                stream.write("changed\n")
            with self.assertRaisesRegex(CandidateContractError, "record verification failed"):
                analyze_r27_source_return_correlation(run)

    def test_rejects_changed_unconsumed_input_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory))
            path = run / "simion" / "unused_but_manifest_bound.json"
            path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "input unused_provenance"):
                analyze_r27_source_return_correlation(run)

    def test_cli_creates_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = _fixture(root)
            output = root / "new" / "nested" / "diagnostic.json"
            with mock.patch("sys.argv", ["r27-correlation", "--run-dir", str(run),
                                          "--output", str(output)]):
                self.assertEqual(main(), 0)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
