from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic import (
    analyze_source_z_energy_timing,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture(
    root: Path,
    *,
    omit_event: tuple[str, int] | None = None,
    selected_parent_interval: tuple[int, int] | None = None,
) -> Path:
    source, run = root / "source", root / "run"
    source.mkdir()
    (run / "logs").mkdir(parents=True)
    (run / "results").mkdir()
    (run / "simion").mkdir()
    state = source / "bunch_source_states.csv"
    fields = [
        "particle_id", "tob_us", "mass_th", "charge_e", "kinetic_energy_ev",
        "x_mm", "y_mm", "z_mm", "direction_x", "direction_y", "direction_z",
    ]
    with state.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        source_count = 100 if selected_parent_interval is not None else 4
        for ion in range(1, source_count + 1):
            writer.writerow({
                "particle_id": ion, "tob_us": 0, "mass_th": 524, "charge_e": 1,
                "kinetic_energy_ev": 5, "x_mm": 0, "y_mm": -55, "z_mm": ion - 1,
                "direction_x": 0, "direction_y": 1, "direction_z": 0,
            })
    fly2 = source / "bunch_source.fly2"
    fly2.write_text(
        "\n".join("standard_beam {" for _ in range(source_count)), encoding="utf-8"
    )
    receipt_source = source / "bunch_source_receipt.json"
    receipt = {
        "schema_version": 1, "role": "mrtof_deterministic_ideal_bunch_source",
        "status": "materialized", "sampling_method": "center_first_halton_position_energy_angle_v1",
        "clock_basis": "ion_time_of_flight_us_from_common_tob_zero_release",
        "species": {"mass_th": 524.0, "charge_e": 1}, "common_time_of_birth_us": 0.0,
        "source_profile_id": "test_source", "frame_id": "test_frame",
        "prefix_rule": "ordered_first_n_states_of_one_mother_cohort",
        "particle_count": source_count, "mother_particle_count": source_count,
        "expected_particle_ids": list(range(1, source_count + 1)),
        "expected_particle_ids_sha256": hashlib.sha256(
            json.dumps(list(range(1, source_count + 1)), separators=(",", ":")).encode()
        ).hexdigest(),
        "particle_states_sha256": "a" * 64,
        "state_table": _record(state), "fly2": _record(fly2),
    }
    _write_json(receipt_source, receipt)
    source_config = source / "run_config.json"
    source_definition = source / "source_definition.json"
    _write_json(source_config, {"schema_version": 1, "role": "test_source_config"})
    _write_json(source_definition, {"role": "test_source_definition"})
    source_manifest = source / "run_manifest.json"
    _write_json(source_manifest, {
        "project": "parallel_mirror_dual_stripe_mr_tof",
        "mode": "deterministic_bunch_source_materialization", "status": "success",
        "run_config": _record(source_config),
        "inputs": {"source_definition": _record(source_definition)},
        "outputs": [_record(state), _record(fly2), _record(receipt_source)],
    })
    receipt_copy = run / "simion" / "bunch_source_receipt.json"
    receipt_copy.write_bytes(receipt_source.read_bytes())

    batch_records = []
    log_paths = []
    for batch_index, offset in enumerate((0, 2), start=1):
        log = run / "logs" / f"native_two_prism_flight__batch{batch_index:02d}.log"
        lines: list[str] = []
        for local_id in (1, 2):
            ion = local_id + offset

            def add(kind: str, line: str) -> None:
                if omit_event != (kind, ion):
                    lines.append(line)

            add(
                "accelerator_safe_exit",
                f"MRTOF_EVENT accelerator_safe_exit ion={local_id} t_us={1 + ion / 1000} "
                f"from_instance=2 to_instance=1 x_mm=0 y_mm=-53 z_mm=-6 "
                f"vx_mm_us=0 vy_mm_us=1.3 vz_mm_us={-40 - ion / 10}",
            )
            add(
                "central_plane_directional",
                f"MRTOF_EVENT central_plane_directional ion={local_id} n=51 direction_z=-1 "
                f"t_us={9.5 + 2 * (ion - 1) / 100} x_mm=0 y_mm=-20 "
                "vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40",
            )
            add(
                "target_k_phase_sample",
                f"MRTOF_EVENT target_k_phase_sample ion={local_id} k=25.5 half_cycles=51 "
                f"t_us={10 + (ion - 1) / 100} x_mm=0 y_mm=0 z_mm=-282 "
                "vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
            )
            if ion == 4:
                lines.append(
                    f"MRTOF_EVENT terminal ion={local_id} splat=-1 t_us=10.5 x_mm=0 y_mm=-8 z_mm=-97 "
                    "vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40 turns=51 central_crossings=51"
                )
                continue
            add(
                "return_p2_entry",
                f"MRTOF_EVENT return_p2_entry ion={local_id} t_us={11 + 2 * (ion - 1) / 100} "
                "x_mm=0 y_mm=-8 z_mm=-26 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=40",
            )
            add(
                "return_p2_pass",
                f"MRTOF_EVENT return_p2_pass ion={local_id} t_us={12 + (ion - 1) / 100} "
                f"x_mm=0 y_mm={-11 + 0.2 * (ion - 1)} z_mm=26 vx_mm_us=0 "
                f"vy_mm_us=-3 vz_mm_us={40 + 0.1 * (ion - 1)}",
            )
            add(
                "return_positive_mirror_turn",
                f"MRTOF_EVENT return_positive_mirror_turn ion={local_id} "
                f"t_us={13 + 3 * (ion - 1) / 100} x_mm=0 y_mm=-32 "
                f"z_mm={280 + 0.5 * (ion - 1)} vx_mm_us=0 vy_mm_us=-3 vz_mm_us=0",
            )
            add(
                "terminal_bridge_exit",
                f"MRTOF_EVENT patch_interface ion={local_id} "
                "name=handoff_positive_bridge_to_mirror__z_plane region=local_handoff "
                f"face=z_plane n=54 direction=-1 t_us={13.8 + 4 * (ion - 1) / 100} "
                "x_mm=0 y_mm=-47 z_mm=105 vx_mm_us=0 vy_mm_us=-3 "
                f"vz_mm_us={-40 - 0.1 * (ion - 1)}",
            )
            add(
                "terminal_detector_plane",
                f"MRTOF_EVENT detector_plane ion={local_id} direction_z=-1 "
                f"t_us={14 + 5 * (ion - 1) / 100} x_mm=0 y_mm=-48 z_mm=97 "
                "vx_mm_us=0 vy_mm_us=-3 "
                f"vz_mm_us={-40 - 0.1 * (ion - 1)}",
            )
            add(
                "detector",
                f"MRTOF_EVENT detector ion={local_id} direction_z=-1 "
                f"t_us={14 + 5 * (ion - 1) / 100} x_mm=0 y_mm=-48 z_mm=97",
            )
            lines.append(
                f"MRTOF_EVENT terminal ion={local_id} splat=1 "
                f"t_us={14 + 5 * (ion - 1) / 100} x_mm=0 y_mm=-48 z_mm=97 "
                "vx_mm_us=0 vy_mm_us=-3 vz_mm_us=-40 turns=51 central_crossings=51"
            )
        lines.append("status,Fly completed. 2 splats")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log_paths.append(log)
        batch_records.append({"path": str(log), "sha256": _sha(log), "offset": offset, "count": 2})
    batch_receipt = run / "results" / "batch_log_merge_receipt.json"
    _write_json(batch_receipt, {
        "schema_version": 1, "role": "mrtof_rebased_batch_log_merge", "status": "success",
        "particle_count": 4, "global_particle_ids": [1, 4], "all_batch_losses_retained": True,
        "batches": batch_records,
        "merged_log": {"path": str(run / "logs" / "native_two_prism_flight.log"), "sha256": "not-retained"},
    })
    observation = run / "results" / "two_prism_trial_observation.json"
    _write_json(observation, {"cohort_analysis": {
        "event_integrity_passed": True, "expected_particle_count": 4,
        "observed_particle_ids": [1, 2, 3, 4],
        "electrode_collision_count": 1, "detector_hit_count": 3,
    }})
    run_config = run / "run_config.json"
    parameters: dict[str, object] = {}
    if selected_parent_interval is not None:
        selected = resolve_bunch_source_interval(
            receipt_path=receipt_copy,
            particle_id_min=selected_parent_interval[0],
            particle_id_max=selected_parent_interval[1],
        )
        parameters = {
            "source_selection": selected["source_cohort"]["selection"],
            "source_cohort": selected["source_cohort"],
        }
    _write_json(
        run_config,
        {"schema_version": 1, "role": "test_flight_config", "parameters": parameters},
    )
    manifest = run / "run_manifest.json"
    _write_json(manifest, {
        "project": "parallel_mirror_dual_stripe_mr_tof",
        "mode": "finite_3d_two_prism_voltage_trial", "status": "success",
        "run_config": _record(run_config),
        "inputs": {
            "bunch_source_receipt": _record(receipt_copy),
            "bunch_source_run_manifest": _record(source_manifest),
            "batch_log_merge_receipt": _record(batch_receipt),
        },
        "outputs": [_record(path) for path in log_paths] + [_record(observation)],
    })
    return run


class SourceZEnergyTimingDiagnosticTests(unittest.TestCase):
    def test_contiguous_parent_interval_is_rebased_to_local_particle_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(
                _fixture(Path(directory), selected_parent_interval=(2, 5))
            )
        self.assertEqual(result["cohort"]["particle_count"], 4)
        self.assertAlmostEqual(
            result["stages"]["detector"]["absolute_time"]
            ["initial_z_association"]["slope"],
            0.05,
        )

    def test_batch_run_retains_losses_and_reports_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_source_z_energy_timing(_fixture(Path(directory)))
        self.assertEqual(result["cohort"]["particle_count"], 4)
        self.assertEqual(result["cohort"]["detector_hit_count"], 3)
        self.assertEqual(result["cohort"]["electrode_collision_count"], 1)
        self.assertTrue(result["cohort"]["all_terminal_particles_retained"])
        self.assertEqual(result["safe_exit"]["time"]["sample_count"], 4)
        self.assertEqual(result["stages"]["detector"]["absolute_time"]["sample_count"], 3)
        self.assertAlmostEqual(
            result["stages"]["detector"]["absolute_time"]["initial_z_association"]["slope"],
            0.05,
        )
        self.assertAlmostEqual(
            result["derived_transfer"]["fraction_of_detector_dt_dz_accumulated_after_target_k"],
            0.8,
        )
        self.assertAlmostEqual(
            result["state_dispersion"]["return_p2_pass_y"]["initial_z_association"]["slope"],
            0.2,
        )
        self.assertAlmostEqual(
            result["state_dispersion"]["return_positive_mirror_turn_depth"]
            ["initial_z_association"]["slope"],
            0.5,
        )
        self.assertGreater(
            result["safe_exit"]["axial_kinetic_energy"]["initial_z_association"]["pearson_r"],
            0.999,
        )
        self.assertEqual(result["event_coverage"]["target_k_phase_sample"], 4)
        terminal = result["terminal_plane_diagnostic"]
        self.assertEqual(terminal["positive_mirror_bridge_exit"]["z_mm"], 105.0)
        self.assertEqual(terminal["detector_plane"]["z_mm"], 97.0)
        self.assertAlmostEqual(
            terminal["positive_mirror_bridge_exit"]["absolute_time"]
            ["initial_z_association"]["slope"],
            0.04,
        )
        self.assertLess(
            terminal["local_ballistic_model_from_bridge_exit"]
            ["actual_detector_plane_projection"]["prediction_minus_observation"]
            ["maximum_absolute_us"],
            0.03,
        )
        central = result["central_plane_focus_history"]
        self.assertEqual(central["status"], "observed")
        self.assertEqual(central["last_complete_crossing"]["crossing_index"], 51)
        self.assertEqual(central["last_complete_crossing"]["direction_z"], -1)
        self.assertAlmostEqual(
            central["last_complete_crossing"]["absolute_time"]
            ["initial_z_association"]["slope"],
            0.02,
        )

    def test_missing_downstream_event_for_detector_hit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), omit_event=("detector", 3))
            with self.assertRaisesRegex(CandidateContractError, "ion 3.*detector"):
                analyze_source_z_energy_timing(run)

    def test_missing_safe_exit_for_loss_also_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), omit_event=("accelerator_safe_exit", 4))
            with self.assertRaisesRegex(CandidateContractError, "ion 4.*accelerator_safe_exit"):
                analyze_source_z_energy_timing(run)

    def test_missing_terminal_bridge_exit_for_detector_hit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = _fixture(Path(directory), omit_event=("terminal_bridge_exit", 2))
            with self.assertRaisesRegex(CandidateContractError, "ion 2.*terminal patch_interface"):
                analyze_source_z_energy_timing(run)


if __name__ == "__main__":
    unittest.main()
