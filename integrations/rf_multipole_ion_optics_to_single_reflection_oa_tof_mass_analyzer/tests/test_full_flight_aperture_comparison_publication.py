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


def _source_run(root: Path, name: str, *, altered_mother: bool = False) -> Path:
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
    }})
    _write_json(run / "run_manifest.json", {
        "role": "simulation_run_manifest", "status": "success", "run_id": name,
        "run_config": _record(config_path),
        "inputs": {"initial": _record(initial)},
        "outputs": [_record(summary_path), _record(checkpoints), _record(evolution)],
    })
    return run


class FullFlightApertureComparisonPublicationTest(unittest.TestCase):
    def test_publishes_eight_full_mother_cohort_arms_without_common_hit_selection(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = {f"arm_{index}": _source_run(root, f"source-{index}") for index in range(8)}
            run_id = "20260829_120001__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            try:
                manifest = publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
                result = json.loads((output / "results" / "full_flight_aperture_comparison.json").read_text(encoding="utf-8"))
                published = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertEqual(result["controlled_variables"]["comparison_denominator"], "full_mother_cohort")
                self.assertFalse(result["controlled_variables"]["common_hit_selection_used"])
                self.assertEqual(len(result["cases"]), 8)
                self.assertEqual(result["cases"]["arm_0"]["mother_cohort_count"], 5000)
                self.assertAlmostEqual(result["cases"]["arm_0"]["z_vz"]["linear"]["k_per_us"], .04, places=3)
                self.assertEqual(result["cases"]["arm_0"]["z_vz"]["published_checkpoint_evolution_reference"]["z_vz_cubic_coefficient_m_per_s_per_mm3"], "1")
                self.assertEqual(published["status"], "success")
            finally:
                if output.exists():
                    shutil.rmtree(output)

    def test_rejects_mother_cohort_identity_drift_before_creating_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = {f"arm_{index}": _source_run(root, f"source-{index}", altered_mother=index == 7) for index in range(8)}
            run_id = "20260829_120002__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            with self.assertRaisesRegex(ContractError, "same frozen mother cohort"):
                publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
            self.assertFalse(output.exists())

    def test_rejects_incomplete_bootstrap_interval_before_creating_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            root = Path(temporary)
            cases = {f"arm_{index}": _source_run(root, f"source-{index}") for index in range(8)}
            summary_path = cases["arm_7"] / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            del summary["full_pulse_eligible_bootstrap"]["resolution_p97p5"]
            _write_json(summary_path, summary)
            manifest_path = cases["arm_7"] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"][0] = _record(summary_path)
            _write_json(manifest_path, manifest)
            run_id = "20260829_120003__analysis__python__full-flight-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            with self.assertRaisesRegex(ContractError, "bootstrap resolution interval is incomplete"):
                publish_full_flight_aperture_comparison(repo_root=REPO_ROOT, run_id=run_id, cases=cases)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
