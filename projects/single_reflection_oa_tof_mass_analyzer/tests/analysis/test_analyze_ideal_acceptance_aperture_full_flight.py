from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_ideal_acceptance_aperture_full_flight import analyze_campaign


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class IdealAcceptanceApertureFullFlightTest(unittest.TestCase):
    def _campaign(self, root: Path) -> Path:
        rows = []
        for realization in ("square", "cylindrical"):
            for height in ("090", "150", "200", "250"):
                connection = "rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm" if height == "090" else f"rf_octupole_oatof_shield_terminal_aperture_100x{height}_direct_mating_gap_0mm"
                rows.append({"run_id": f"run-{realization}-{height}", "experiment_id": f"experiment-{realization}-{height}", "overrides": {"single_flight_layout_profile_id": f"three_zone_ideal_acceptance_300mm_{realization}_v1", "connection_profile_id": connection}})
        path = root / "campaign.json"
        path.write_text(json.dumps({"campaign_id": "ideal_acceptance_300mm_aperture_height_full_flight_n5000", "experiments": {"shared": {"single_flight_three_zone_candidate": {"sha256": "A" * 64}}, "rows": rows}}), encoding="utf-8")
        return path

    def _arm(self, root: Path, row: dict, *, bad_candidate: bool = False, bad_layout: bool = False) -> None:
        parent = root / row["run_id"]
        run = root / (row["run_id"] + "__single-flight")
        results, inputs = run / "results", run / "inputs"
        results.mkdir(parents=True); inputs.mkdir()
        candidate = inputs / "three_zone_t5_candidate_resolved.json"
        candidate.write_text("other-candidate" if bad_candidate else "candidate", encoding="utf-8")
        layout = row["overrides"]["single_flight_layout_profile_id"]
        geometry = {"single_flight_layout_derivation": {"layout_profile_id": "wrong_layout" if bad_layout else layout}, "geometry_derivation": {"accelerator": {"realization_id": "square_3d" if "square" in layout else "cylindrical_3d"}}}
        (inputs / "oatof_resolved_geometry.json").write_text(json.dumps(geometry), encoding="utf-8")
        with (inputs / "single_flight_initial_global_state.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("particle_id",)); writer.writeheader()
            writer.writerows({"particle_id": particle_id} for particle_id in range(1, 5001))
        checkpoints = results / "single_flight_particle_checkpoints.csv"
        with checkpoints.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("particle_id", "event", "z_mm", "vz_mm_per_us", "pulse_eligibility")); writer.writeheader()
            for particle_id, z in enumerate((-2.5, -1.0, 1.0, 2.5), start=1):
                writer.writerow({"particle_id": particle_id, "event": "pre_pulse_state", "z_mm": z, "vz_mm_per_us": 1 + 2 * z, "pulse_eligibility": "eligible"})
        summary_path = run / "summary.json"
        census = {"launched": 5000, "accelerator_grid1_forward": 4000, "accelerator_intermediate2_forward": 3500, "local_accelerator_exit": 3200, "detector_crossing": 3000}
        outcomes = [
            {"particle_id": particle_id, "category": "detector_crossing", "terminal_event": "detector_crossing", "instance_id": 4}
            if particle_id <= 3000 else
            {"particle_id": particle_id, "category": "non_detector_splat_instance_3", "terminal_event": "non_detector_splat", "instance_id": 3}
            for particle_id in range(1, 5001)
        ]
        summary = {"role": "rf_oatof_simion_single_flight_summary", "status": "success", "resolution_time_basis": "detector_time_minus_pulse_effective_time", "census": census, "terminal_taxonomy": {"role": "rf_oatof_full_flight_terminal_taxonomy", "classification_is_mutually_exclusive_and_exhaustive": True, "mother_cohort_count": 5000, "terminal_outcome_count": 5000, "category_counts": {"detector_crossing": 3000, "non_detector_splat_instance_3": 2000}, "particle_outcomes": outcomes}, "pulse_effective_peak": {"mean_tof_us": 70.0, "direct_fwhm_tof_ns": 2.0, "mass_resolution": 17500.0, "direct_fwhm_mass_Da": 0.0057, "significant_kde_modes": 1, "tail_fraction_outside_3sigma": 0.01, "tof_skewness": 0.0, "tof_excess_kurtosis": 0.0}, "full_pulse_eligible_bootstrap": {"status": "computed", "resamples_requested": 1000, "resamples_valid": 1000}}
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        child_manifest = run / "run_manifest.json"
        child_manifest.write_text(json.dumps({"role": "simulation_run_manifest", "run_id": run.name, "status": "success", "outputs": [{"path": str(summary_path), "sha256": _sha(summary_path)}, {"path": str(checkpoints), "sha256": _sha(checkpoints)}]}), encoding="utf-8")
        parent.mkdir()
        parent_summary = parent / "summary.json"
        parent_summary.write_text(json.dumps({"role": "integration_family_source_closure_summary", "status": "success", "campaign_id": "ideal_acceptance_300mm_aperture_height_full_flight_n5000", "experiment_id": row["experiment_id"], "connection_profile_id": row["overrides"]["connection_profile_id"]}), encoding="utf-8")
        parent_manifest = {"role": "simulation_run_manifest", "status": "success", "outputs": [{"path": str(parent_summary), "sha256": _sha(parent_summary)}], "inputs": {"single_flight_transport_manifest": {"path": str(child_manifest), "sha256": _sha(child_manifest)}}}
        (parent / "run_manifest.json").write_text(json.dumps(parent_manifest), encoding="utf-8")

    def _prepare(self, root: Path, *, bad_candidate: bool = False) -> tuple[Path, Path]:
        campaign_path = self._campaign(root)
        campaign = json.loads(campaign_path.read_text(encoding="utf-8")); runs = root / "runs"
        for index, row in enumerate(campaign["experiments"]["rows"]):
            self._arm(runs, row, bad_candidate=bad_candidate and index == 0)
        candidate_path = runs / (campaign["experiments"]["rows"][0]["run_id"] + "__single-flight") / "inputs" / "three_zone_t5_candidate_resolved.json"
        campaign["experiments"]["shared"]["single_flight_three_zone_candidate"]["sha256"] = _sha(candidate_path)
        campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
        return campaign_path, runs

    def test_reports_whole_cohort_and_all_hit_peak_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign, runs = self._prepare(Path(directory))
            result = analyze_campaign(campaign_path=campaign, runs_root=runs)
        arm = result["arms"][0]
        self.assertEqual(len(result["arms"]), 8)
        self.assertEqual(arm["mother_cohort"]["checkpoint_interval_loss_counts"]["before_grid1"], 1000)
        taxonomy = arm["mother_cohort"]["terminal_taxonomy"]
        self.assertTrue(taxonomy["classification_is_mutually_exclusive_and_exhaustive"])
        self.assertEqual(taxonomy["category_counts"]["non_detector_splat_instance_3"], 2000)
        self.assertTrue(arm["axial_z_width"]["exceeds_4mm_full_range"])
        self.assertAlmostEqual(arm["z_vz_affine"]["slope_per_us"], 2.0)
        self.assertAlmostEqual(arm["z_vz_affine"]["k_per_us"], 2.0)
        self.assertEqual(arm["z_vz_affine"]["random_residual_model_degree"], 3)
        self.assertAlmostEqual(arm["z_vz_affine"]["random_residual_rms_mm_per_us"], 0.0, places=12)
        self.assertEqual(arm["detector_peak"]["status"], "COMPUTED")

    def test_rejects_candidate_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign, runs = self._prepare(Path(directory), bad_candidate=True)
            with self.assertRaisesRegex(ValueError, "Candidate identity"):
                analyze_campaign(campaign_path=campaign, runs_root=runs)

    def test_rejects_layout_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_path = self._campaign(root)
            campaign = json.loads(campaign_path.read_text(encoding="utf-8")); runs = root / "runs"
            for index, row in enumerate(campaign["experiments"]["rows"]):
                self._arm(runs, row, bad_layout=index == 0)
            candidate_path = runs / (campaign["experiments"]["rows"][0]["run_id"] + "__single-flight") / "inputs" / "three_zone_t5_candidate_resolved.json"
            campaign["experiments"]["shared"]["single_flight_three_zone_candidate"]["sha256"] = _sha(candidate_path)
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "layout profile"):
                analyze_campaign(campaign_path=campaign_path, runs_root=runs)

    def test_rejects_missing_or_inconsistent_terminal_taxonomy(self) -> None:
        for defect, message in (
            ("missing", "lacks terminal taxonomy"),
            ("nonexclusive", "not exhaustive and exclusive"),
            ("detector_count", "taxonomy counts differ"),
            ("instance", "non-detector terminal taxonomy instance differs"),
        ):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                campaign, runs = self._prepare(Path(directory))
                first = json.loads(campaign.read_text(encoding="utf-8"))["experiments"]["rows"][0]
                summary_path = runs / (first["run_id"] + "__single-flight") / "summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                if defect == "missing":
                    summary.pop("terminal_taxonomy")
                elif defect == "nonexclusive":
                    summary["terminal_taxonomy"]["classification_is_mutually_exclusive_and_exhaustive"] = False
                elif defect == "detector_count":
                    summary["terminal_taxonomy"]["category_counts"]["detector_crossing"] = 2999
                else:
                    summary["terminal_taxonomy"]["particle_outcomes"][3000]["instance_id"] = 2
                summary_path.write_text(json.dumps(summary), encoding="utf-8")
                child_manifest_path = summary_path.parent / "run_manifest.json"
                child_manifest = json.loads(child_manifest_path.read_text(encoding="utf-8"))
                child_manifest["outputs"][0]["sha256"] = _sha(summary_path)
                child_manifest_path.write_text(json.dumps(child_manifest), encoding="utf-8")
                parent_manifest_path = runs / first["run_id"] / "run_manifest.json"
                parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
                parent_manifest["inputs"]["single_flight_transport_manifest"]["sha256"] = _sha(child_manifest_path)
                parent_manifest_path.write_text(json.dumps(parent_manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    analyze_campaign(campaign_path=campaign, runs_root=runs)


if __name__ == "__main__":
    unittest.main()
