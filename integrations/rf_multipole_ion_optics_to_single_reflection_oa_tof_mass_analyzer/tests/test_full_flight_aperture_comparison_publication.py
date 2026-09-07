from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_full_flight_aperture_comparison import (
    INTEGRATION_ID,
    publish_full_flight_aperture_comparison,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _record(path: Path) -> dict:
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}


def _source_run(
    root: Path, name: str, *, aperture_height_mm: float,
    altered_mother: bool = False,
) -> Path:
    run = root / "artifacts" / "projects" / INTEGRATION_ID / "runs" / name
    initial = run / "inputs" / "single_flight_initial_global_state.csv"
    initial.parent.mkdir(parents=True)
    with initial.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["particle_id"])
        writer.writeheader()
        for particle_id in range(1, 5001):
            writer.writerow({"particle_id": particle_id if not altered_mother or particle_id != 5000 else 6000})
    checkpoints = run / "results" / "single_flight_particle_checkpoints.csv"
    checkpoints.parent.mkdir(parents=True)
    with checkpoints.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["particle_id", "event", "z_mm", "vz_mm_per_us"])
        writer.writeheader()
        for particle_id in range(1, 5001):
            source_particle_id = particle_id if not altered_mother or particle_id != 5000 else 6000
            z_mm = (particle_id % 101) / 100.0 - .5
            writer.writerow({"particle_id": source_particle_id, "event": "pre_pulse_state", "z_mm": z_mm, "vz_mm_per_us": .04 * z_mm + .001 * z_mm**3})
    connection_path = run / "inputs" / "resolved_connection.json"
    _write_json(connection_path, {
        "spatial_registration": {"expected_gap_mm": 102.4},
        "connector": {"length_mm": 102.4},
    })
    evolution = run / "results" / "single_flight_accelerator_checkpoint_evolution.csv"
    with evolution.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "event", "z_vz_k_m_per_s_per_mm",
            "z_vz_linear_residual_sigma_m_per_s",
            "z_vz_cubic_coefficient_m_per_s_per_mm3",
            "z_vz_cubic_random_residual_rms_m_per_s",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "event": "pre_pulse_state", "z_vz_k_m_per_s_per_mm": "40",
            "z_vz_linear_residual_sigma_m_per_s": "1",
            "z_vz_cubic_coefficient_m_per_s_per_mm3": "1",
            "z_vz_cubic_random_residual_rms_m_per_s": "0",
        })
    outcomes = [{"particle_id": particle_id if not altered_mother or particle_id != 5000 else 6000, "category": "detector_crossing"} for particle_id in range(1, 5001)]
    summary_path = run / "summary.json"
    _write_json(summary_path, {
        "schema_version": 3,
        "role": "rf_oatof_simion_single_flight_summary",
        "status": "success",
        "analysis_scope": "full_single_flight_with_pulse_eligibility",
        "pulse_eligibility_validation_applied": True,
        "source_population": {"simulation_population_basis": "candidate_full_population", "candidate_population_count": 5000, "simulated_population_count": 5000},
        "transmission": {"detector_fraction_of_candidate_population": 1.0},
        "terminal_taxonomy": {"role": "rf_oatof_full_flight_terminal_taxonomy", "classification_is_mutually_exclusive_and_exhaustive": True, "category_counts": {"detector_crossing": 5000}, "particle_outcomes": outcomes},
        "pulse_effective_peak": {"direct_fwhm_tof_ns": 1.0, "direct_fwhm_mass_Da": .01, "mass_resolution": 10000.0, "tail_fraction_outside_3sigma": .02},
        "full_pulse_eligible_bootstrap": {"status": "computed", "resamples_requested": 100, "resolution_p2p5": 9000.0, "resolution_p97p5": 11000.0},
    })
    config_path = run / "run_config.json"
    _write_json(config_path, {"mode": "rf_to_oatof_simion_single_flight", "parameters": {
        "source_release_full_width_mm": 4.0,
        "accelerator_entrance_local_aperture_mm": {
            "width": 1.0, "height": aperture_height_mm,
        },
    }})
    _write_json(run / "run_manifest.json", {
        "role": "simulation_run_manifest", "status": "success", "run_id": name,
        "run_config": _record(config_path),
        "inputs": {"initial": _record(initial), "connection": _record(connection_path)},
        "outputs": [_record(summary_path), _record(checkpoints), _record(evolution)],
    })
    return run


def _matrix_cases(root: Path, *, altered_mother: bool = False) -> dict[str, Path]:
    return {
        (
            f"ideal_acceptance_300mm_{shape}_accelerator_port_"
            f"h{int(height_mm * 100):03d}_full_flight_n5000"
        ): _source_run(
            root,
            f"source-{shape}-{int(height_mm * 100):03d}",
            aperture_height_mm=height_mm,
            altered_mother=altered_mother and shape == "cylindrical" and height_mm == 2.5,
        )
        for shape in ("square", "cylindrical")
        for height_mm in (1.0, 1.5, 2.0, 2.5)
    }


def _restart_case(root: Path, name: str) -> tuple[str, Path]:
    pre = root / "pre-pulse"
    (pre / "inputs").mkdir(parents=True)
    (pre / "results").mkdir()
    initial = pre / "inputs" / "single_flight_initial_global_state.csv"
    with initial.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["particle_id"])
        writer.writeheader()
        writer.writerows({"particle_id": particle_id} for particle_id in range(1, 5001))
    _write_json(pre / "run_config.json", {"parameters": {
        "execution_mode": "real_pa_rf_pre_pulse_time_series", "source_release_full_width_mm": 4.0,
        "layout_profile_id": "three_zone_ideal_acceptance_300mm_square_kinematic_envelope_v1",
        "accelerator_entrance_local_aperture_mm": {"width": 1.0, "height": 1.0},
    }})
    _write_json(pre / "inputs" / "resolved_connection.json", {
        "spatial_registration": {"expected_gap_mm": 102.4}, "connector": {"length_mm": 102.4},
    })
    _write_json(pre / "inputs" / "resolved_population_contract.json", {
        "role": "rf_oatof_resolved_population_contract", "source_release_mode": "continuous_frontend",
        "source_authority": {"particle_count": 5000, "table": {"sha256": "B" * 64}},
    })
    handoff = pre / "results" / "pre_pulse_compact_handoff.csv"
    selected_ids = [11, 22, 33]
    with handoff.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["particle_id", "instrument_time_us", "position_z_mm", "velocity_z_m_s"])
        writer.writeheader()
        for particle_id, z_mm in zip(selected_ids, (0.0, 1.0, 2.0), strict=True):
            writer.writerow({"particle_id": particle_id, "instrument_time_us": 2.0, "position_z_mm": z_mm, "velocity_z_m_s": 1000.0 + z_mm})
    terminal = pre / "results" / "pre_pulse_particle_terminal_states.csv"
    with terminal.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["particle_id", "terminal_reason"])
        writer.writeheader()
        writer.writerows({"particle_id": particle_id, "terminal_reason": "geometry_collision"} for particle_id in range(1, 5001))
    receipt = pre / "results" / "pre_pulse_compact_handoff_receipt.json"
    _write_json(receipt, {
        "role": "rf_oatof_compact_pre_pulse_trace_handoff_receipt", "status": "success",
        "selection_uses_detector_outcome": False, "detector_results_used": False, "pulse_disabled": True,
        "selection": {"sample_index": 2, "pulse_effective_time_us": 2.0, "mother_population_count": 5000,
                      "pulse_eligible_count": 3, "pulse_eligible_particle_ids": selected_ids, "postselection_prohibited": True},
        "pulse_target_state": {"bytes": handoff.stat().st_size, "sha256": _record(handoff)["sha256"],
                               "particle_count": 3, "pulse_effective_time_us": 2.0,
                               "ordered_particle_id_sha256": "C" * 64},
        "natural_terminal_census": {"complete": True, "mother_population_count": 5000,
            "terminal_particle_count": 5000, "accounted_particle_count": 5000, "unknown_terminal_count": 0,
            "by_reason": {"geometry_collision": 5000},
            "terminal_state": _record(terminal)},
    })
    _write_json(pre / "summary.json", {"status": "success", "role": "rf_oatof_simion_single_flight_summary"})
    pre_inputs = {path.name: _record(path) for path in (pre / "inputs").glob("*")}
    _write_json(pre / "run_manifest.json", {"status": "success", "run_id": pre.name,
        "run_config": _record(pre / "run_config.json"), "inputs": pre_inputs,
        "outputs": [_record(pre / "summary.json"), _record(handoff), _record(receipt), _record(terminal)]})

    run = root / "post-pulse"
    (run / "inputs").mkdir(parents=True)
    (run / "results").mkdir()
    for filename in ("mother_particle_source.csv", "single_flight_initial_global_state.csv"):
        shutil.copyfile(handoff, run / "inputs" / filename)
    row_map = run / "inputs" / "single_flight_particle_row_map.csv"
    with row_map.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["simulation_particle_id", "source_particle_id"])
        writer.writeheader()
        writer.writerows({"simulation_particle_id": index, "source_particle_id": particle_id} for index, particle_id in enumerate(selected_ids, start=1))
    _write_json(run / "inputs" / "canonical_pulse_restart_target_state_validation.json", {
        "role": "canonical_pulse_restart_target_state_validation", "status": "PASS",
        "target_pulse_state_sha256": _record(handoff)["sha256"], "ordered_particle_id_sha256": "C" * 64,
        "particle_count": 3,
    })
    _write_json(run / "inputs" / "resolved_connection.json", {
        "spatial_registration": {"expected_gap_mm": 102.4}, "connector": {"length_mm": 102.4},
    })
    _write_json(run / "inputs" / "resolved_single_flight_population.json", {})
    _write_json(run / "inputs" / "resolved_population_contract.json", {
        "source_release_mode": "pre_pulse_restart",
        "source_authority": {"particle_count": 3, "table": {"path": handoff.relative_to(WORKSPACE_ROOT).as_posix(), "sha256": _record(handoff)["sha256"]}},
        "denominators": {"population_count": 5000},
    })
    checkpoints = run / "results" / "single_flight_particle_checkpoints.csv"
    checkpoints.write_text("particle_id,event\n11,detector_crossing\n", encoding="utf-8")
    _write_json(run / "summary.json", {
        "role": "rf_oatof_simion_single_flight_summary", "status": "success",
        "analysis_scope": "full_single_flight_with_pulse_eligibility",
        "source_population": {"simulation_population_basis": "pulse_eligible_conditional_population",
            "candidate_population_count": 5000, "pulse_eligible_population_count": 3,
            "simulated_population_count": 3, "complete_pulse_eligible_population_simulated": True},
        "terminal_taxonomy": {"role": "rf_oatof_full_flight_terminal_taxonomy",
            "classification_is_mutually_exclusive_and_exhaustive": True,
            "category_counts": {"detector_crossing": 2, "non_detector_splat_instance_3": 1},
            "particle_outcomes": [{"particle_id": 11}, {"particle_id": 22}, {"particle_id": 33}]},
        "pulse_effective_peak": {"direct_fwhm_tof_ns": 1.0, "direct_fwhm_mass_Da": .01,
            "mass_resolution": 10000.0, "tail_fraction_outside_3sigma": .02},
        "full_pulse_eligible_bootstrap": {"status": "computed", "resolution_p2p5": 9000.0, "resolution_p97p5": 11000.0},
    })
    _write_json(run / "run_config.json", {"mode": "rf_to_oatof_simion_single_flight", "parameters": {
        "accelerator_entrance_local_aperture_mm": {"width": 1.0, "height": 1.0},
    }})
    records = {path.name: _record(path) for path in (run / "inputs").glob("*")}
    records["summary"] = _record(run / "summary.json")
    records["checkpoints"] = _record(checkpoints)
    _write_json(run / "run_manifest.json", {"status": "success", "run_id": run.name,
        "run_config": _record(run / "run_config.json"),
        "inputs": {key: value for key, value in records.items() if key not in {"summary", "checkpoints"}},
        "outputs": [records["summary"], records["checkpoints"]]})
    return "ideal_acceptance_300mm_square_accelerator_port_h100_pre_pulse_n5000_post_pulse", run


class FullFlightApertureComparisonPublicationTest(unittest.TestCase):
    def test_publishes_restart_arm_with_full_mother_partition_without_natural_loss_substitution(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            case_id, source = _restart_case(Path(temporary), "restart")
            run_id = "20260904_160001__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            try:
                publish_full_flight_aperture_comparison(
                    repo_root=REPO_ROOT, run_id=run_id, cases={case_id: source}
                )
                result = json.loads((output / "results" / "full_flight_aperture_comparison.json").read_text(encoding="utf-8"))
                arm = result["cases"][case_id]
                partition = arm["transmission_and_terminal_losses"]["full_mother_cohort_partition"]
                self.assertFalse(result["controlled_variables"]["matrix_complete"])
                self.assertEqual(arm["mother_cohort_count"], 5000)
                self.assertEqual(arm["accelerator_entry_count"], 3)
                self.assertEqual(arm["transmission_and_terminal_losses"]["detector_fraction_of_mother"], 2 / 5000)
                self.assertEqual(partition["categories"]["not_pulse_eligible_at_selected_time"], 4997)
                self.assertEqual(partition["categories"]["selected_post_pulse_detector"], 2)
                self.assertEqual(partition["categories"]["selected_post_pulse_loss"]["count"], 1)
                self.assertNotIn("geometry_collision", partition["categories"])
                self.assertEqual(
                    arm["transmission_and_terminal_losses"]["detector_blind_natural_terminal_census"]["by_reason"]["geometry_collision"],
                    5000,
                )
                self.assertIn("k_per_us", arm["z_vz_linear_fit"])
                self.assertIn("cubic", arm["z_vz_polynomial_diagnostics"])
            finally:
                if output.exists():
                    shutil.rmtree(output)

    def test_publishes_eight_full_mother_cohort_arms_without_common_hit_selection(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = _matrix_cases(root)
            run_id = "20260829_120001__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            try:
                manifest = publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
                result = json.loads((output / "results" / "full_flight_aperture_comparison.json").read_text(encoding="utf-8"))
                published = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertEqual(result["controlled_variables"]["comparison_denominator"], "full_mother_cohort")
                self.assertFalse(result["controlled_variables"]["common_hit_selection_used"])
                self.assertEqual(result["controlled_variables"]["connector_gap_mm"], 102.4)
                self.assertEqual(len(result["cases"]), 8)
                square_h100 = result["cases"][
                    "ideal_acceptance_300mm_square_accelerator_port_h100_full_flight_n5000"
                ]
                self.assertEqual(square_h100["mother_cohort_count"], 5000)
                self.assertEqual(square_h100["matrix_arm"], {"shape": "square", "aperture_height_mm": 1.0})
                self.assertEqual(square_h100["z_vz"]["position_unit"], "mm")
                self.assertEqual(square_h100["z_vz"]["velocity_unit"], "m_per_s")
                self.assertAlmostEqual(square_h100["z_vz"]["slope_m_per_s_per_mm"], 40.1529, places=3)
                self.assertAlmostEqual(square_h100["z_vz"]["cubic_fit"]["coefficients_m_per_s"]["cubic_per_mm3"], 1.0, places=3)
                self.assertEqual(square_h100["z_vz"]["published_checkpoint_evolution_reference"]["z_vz_cubic_coefficient_m_per_s_per_mm3"], "1")
                self.assertEqual(published["status"], "success")
            finally:
                if output.exists():
                    shutil.rmtree(output)

    def test_rejects_mother_cohort_identity_drift_before_creating_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = _matrix_cases(root, altered_mother=True)
            run_id = "20260829_120002__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            with self.assertRaisesRegex(ContractError, "same frozen mother cohort"):
                publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
            self.assertFalse(output.exists())

    def test_rejects_incomplete_bootstrap_interval_before_creating_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = _matrix_cases(root)
            summary_path = cases[
                "ideal_acceptance_300mm_cylindrical_accelerator_port_h250_full_flight_n5000"
            ] / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            del summary["full_pulse_eligible_bootstrap"]["resolution_p97p5"]
            _write_json(summary_path, summary)
            manifest_path = cases[
                "ideal_acceptance_300mm_cylindrical_accelerator_port_h250_full_flight_n5000"
            ] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"][0] = _record(summary_path)
            _write_json(manifest_path, manifest)
            run_id = "20260829_120003__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            with self.assertRaisesRegex(ContractError, "bootstrap resolution interval is incomplete"):
                publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
            self.assertFalse(output.exists())

    def test_rejects_arm_outside_the_required_matrix_before_creating_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = _matrix_cases(root)
            moved = cases.pop(
                "ideal_acceptance_300mm_square_accelerator_port_h100_full_flight_n5000"
            )
            cases["ideal_acceptance_300mm_square_accelerator_port_h090_full_flight_n5000"] = moved
            run_id = "20260829_120004__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            with self.assertRaisesRegex(ContractError, "outside the required full-flight aperture matrix"):
                publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
