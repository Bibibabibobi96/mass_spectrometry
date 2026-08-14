from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.affine_axial_ideal_report import (
    compute_analytic_report,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    PhysicsContractError,
    accelerator_state,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.verify_axial_ideal_closure import (
    segment_times_s,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixtures" / "affine_axial_ideal_report"
CAMPAIGN = (
    ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "config"
    / "diagnostics"
    / "canonical_affine_axial_all_ideal_report_campaign.json"
)


class AffineAxialIdealReportTests(unittest.TestCase):
    def test_committed_fixture_matches_existing_zero_vz_closure(self) -> None:
        report = compute_analytic_report(
            FIXTURE / "campaign.json", "fixture", workspace_root=FIXTURE
        )
        center = report["particle_tof_records"][1]
        self.assertAlmostEqual(
            center["pulse_effective_detector_tof_us"], 32.301133326523136, places=12
        )
        release_z = -68.45815512803617 - (-69.95653076887548)
        state = accelerator_state(
            2154.81955744942,
            1844.8447689590694,
            3.0,
            16.8,
            release_position_mm=release_z,
            require_downstream_focus=False,
        )
        state = replace(state, first_order_focus_drift_mm=50.156530768875484)
        reflectron = SimpleNamespace(
            stage1_voltage_drop_v=1600.8967499896587,
            stage1_field_v_per_mm=13.340806249913822,
            stage2_field_v_per_mm=9.218275772964926,
            upstream_from_accelerator_focus_mm=600.0,
            downstream_to_detector_mm=600.0,
        )
        legacy = segment_times_s(release_z, state, reflectron, 100.0)
        self.assertAlmostEqual(
            center["pulse_effective_detector_tof_us"], legacy["total_s"] * 1.0e6, places=12
        )
        self.assertEqual(report["status"], "diagnostic")
        self.assertEqual(report["evidence_level"], "PROVISIONAL")
        self.assertEqual(report["energy_envelope"]["outside_count"], 0)
        self.assertGreater(report["summary"]["sample_sigma_tof_ns"], 0.0)
        self.assertIn("direct_fwhm_tof_ns", report["summary"])
        self.assertIn("mass_resolution", report["summary"])

    def test_release_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "fixture"
            shutil.copytree(FIXTURE, copied)
            (copied / "source_release.csv").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(PhysicsContractError, "source release CSV"):
                compute_analytic_report(
                    copied / "campaign.json", "fixture", workspace_root=copied
                )

    def test_registered_campaign_has_eight_bound_provisional_cases(self) -> None:
        campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
        self.assertEqual(
            campaign["role"], "rf_oatof_affine_axial_all_ideal_report_campaign"
        )
        self.assertEqual(len(campaign["cases"]), 8)
        self.assertEqual(
            sum("zero_vz" in case["case_id"] for case in campaign["cases"]), 4
        )
        self.assertTrue(
            all("source_release_csv" in case for case in campaign["cases"])
        )


if __name__ == "__main__":
    unittest.main()
