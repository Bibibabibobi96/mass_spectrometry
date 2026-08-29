from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_ideal_acceptance_aperture_campaign import analyze_campaign


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class IdealAcceptanceApertureCampaignTest(unittest.TestCase):
    def _campaign(self, root: Path) -> Path:
        rows = []
        for realization in ("square", "cylindrical"):
            for height in ("090", "150", "200", "250"):
                run_id = f"run-{realization}-{height}"
                connection = "rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm" if height == "090" else f"rf_octupole_oatof_shield_terminal_aperture_100x{height}_direct_mating_gap_0mm"
                rows.append({"run_id": run_id, "experiment_id": f"experiment-{realization}-{height}", "overrides": {"single_flight_layout_profile_id": f"three_zone_ideal_acceptance_300mm_{realization}_v1", "connection_profile_id": connection}})
        value = {"campaign_id": "ideal_acceptance_300mm_aperture_height_pre_pulse_n5000", "experiments": {"shared": {"single_flight_three_zone_candidate": {"sha256": "A" * 64}}, "rows": rows}}
        path = root / "campaign.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _arm(self, root: Path, row: dict, *, tamper: bool = False) -> None:
        run = root / row["run_id"]
        results = run / "results"
        results.mkdir(parents=True)
        states = results / "pre_pulse_time_series_states.csv"
        with states.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["particle_id", "event", "sample_index", "z_mm", "vz_mm_per_us", "survival_status"])
            writer.writeheader()
            for particle_id, z in enumerate((-2.5, -1.0, 1.0, 2.5), start=1):
                writer.writerow({"particle_id": particle_id, "event": "pre_pulse_time_series_state", "sample_index": 1, "z_mm": z, "vz_mm_per_us": 1.0 + 2.0 * z, "survival_status": "alive"})
        layout = row["overrides"]["single_flight_layout_profile_id"]
        connection = row["overrides"]["connection_profile_id"]
        receipt = {"role": "rf_oatof_pre_pulse_time_series_screening_receipt", "status": "success", "pulse_disabled": True, "particle_count": 5000, "state_row_count": 4, "identities": {"campaign_id": "ideal_acceptance_300mm_aperture_height_pre_pulse_n5000", "experiment_id": "wrong" if tamper else row["experiment_id"], "connection_profile_id": connection, "layout_profile_id": layout, "candidate_sha256": "A" * 64}, "outputs": {"states": {"sha256": _sha(states)}}, "terminal_census": {"window_complete": {"count": 4}, "splat": {"count": 4996}}, "sample_census": [{"alive_count": 4, "missing_count": 4996}]}
        receipt_path = results / "pre_pulse_time_series_screening_receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        summary = {"role": "rf_oatof_simion_single_flight_summary", "status": "success", "pulse_disabled": True}
        (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        manifest = {"outputs": [{"path": str(states), "sha256": _sha(states)}, {"path": str(receipt_path), "sha256": _sha(receipt_path)}]}
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_compares_all_arms_with_complete_mother_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = self._campaign(root)
            campaign = json.loads(campaign_path.read_text())
            runs = root / "runs"
            for row in campaign["experiments"]["rows"]:
                self._arm(runs, row)
            result = analyze_campaign(campaign_path=campaign_path, runs_root=runs)
        self.assertEqual(len(result["arms"]), 8)
        self.assertEqual(result["arms"][0]["mother_cohort"]["loss_count"], 4996)
        self.assertTrue(result["arms"][0]["axial_z_width"]["exceeds_4mm_full_range"])
        self.assertAlmostEqual(result["arms"][0]["z_vz_affine"]["slope_per_us"], 2.0)
        affine = result["arms"][0]["z_vz_affine"]
        self.assertAlmostEqual(affine["k_per_us"], 2.0)
        self.assertEqual(affine["random_residual_model_degree"], 3)
        self.assertAlmostEqual(affine["random_residual_rms_mm_per_us"], 0.0, places=12)
        self.assertEqual(
            affine["polynomial_diagnostics"]["cubic"]["coefficient_units_descending_power"],
            ["mm_per_us_per_mm3", "mm_per_us_per_mm2", "mm_per_us_per_mm", "mm_per_us"],
        )

    def test_rejects_experiment_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = self._campaign(root)
            campaign = json.loads(campaign_path.read_text())
            runs = root / "runs"
            for index, row in enumerate(campaign["experiments"]["rows"]):
                self._arm(runs, row, tamper=index == 3)
            with self.assertRaisesRegex(ValueError, "campaign or experiment identity"):
                analyze_campaign(campaign_path=campaign_path, runs_root=runs)

    def test_rejects_missing_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = self._campaign(root)
            with self.assertRaisesRegex(ValueError, "missing run manifest"):
                analyze_campaign(campaign_path=campaign_path, runs_root=root / "runs")

    def test_rejects_failed_arm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = self._campaign(root)
            campaign = json.loads(campaign_path.read_text())
            runs = root / "runs"
            for row in campaign["experiments"]["rows"]:
                self._arm(runs, row)
            target = runs / campaign["experiments"]["rows"][0]["run_id"]
            receipt_path = target / "results" / "pre_pulse_time_series_screening_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["status"] = "failed"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            manifest_path = target / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["outputs"][1]["sha256"] = _sha(receipt_path)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a successful pre-pulse screen"):
                analyze_campaign(campaign_path=campaign_path, runs_root=runs)
