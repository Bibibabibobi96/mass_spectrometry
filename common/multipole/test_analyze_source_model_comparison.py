from __future__ import annotations

import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path

from common.multipole.analyze_source_model_comparison import (
    _require_equal_identity,
    _source_distribution,
    analyze_source_models,
    main,
    markdown_report,
)


def arm(authority: str, *, source_ids: list[int] | None = None) -> dict:
    return {
        "identity": {
            "project_id": "rf_octupole_ion_optics", "solver": "SIMION",
            "design_profile_id": "no_acceleration_full_length", "physical_resolved_design_sha256": "D" * 64,
            "numerics": {"cell_mm_xyz": {"x": 0.15, "y": 0.15, "z": 0.2}},
            "terminal_fingerprint_sha256": "T" * 64, "source_particle_ids": source_ids or [1, 2],
            "source_particle_count": len(source_ids or [1, 2]), "particle_source_authority_sha256": authority,
        },
        "summary": {
            "transmission": 0.5, "centroid_x_mm": 0.0, "centroid_y_mm": 0.0,
            "centered_spatial_rms_spread_mm": 0.3, "mean_direction_tilt_deg": 1.0,
            "centered_angular_rms_spread_deg": 2.0, "mean_energy_eV": 2.0,
            "centered_rms_energy_spread_eV": 0.1, "mean_elapsed_time_us": 40.0,
            "centered_rms_elapsed_time_spread_us": 0.2, "p95_radius_mm": 1.0,
            "p99_radius_mm": 1.1, "p95_divergence_deg": 4.0, "p99_divergence_deg": 4.5,
        },
        "loss_census": {"available": True, "lost_particle_count": 1, "classified_particle_count": 1,
                         "unclassified_particle_count": 0, "by_terminal_reason": {"rod": 1}},
        "resource_metrics": {"wall_clock_seconds": 10.0, "peak_process_tree_working_set_bytes": 100.0,
                             "peak_run_directory_bytes": 200.0, "final_retained_bytes": 20.0},
        "source_distribution": {
            "particle_count": 2, "birth_time_min_s": 0.0, "birth_time_max_s": 0.0,
            "z_min_mm": -1.0, "z_max_mm": 1.0, "z_mean_mm": 0.0,
            "z_rms_spread_mm": 0.5, "vz_mean_m_s": 2000.0, "vz_rms_spread_m_s": 10.0,
            "z_vz_pearson_correlation": 0.0, "z_vz_linear_slope_m_s_per_mm": 0.0,
        },
        "label": "unused", "manifest_path": "fixture",
    }


class SourceModelComparisonTests(unittest.TestCase):
    def test_source_distribution_reports_empirical_axial_phase_space(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text(
                "particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state\n"
                "1,0,0,0,-1,0,0,100,100,1\n"
                "2,0,0,0,1,0,0,300,100,1\n",
                encoding="utf-8",
            )
            distribution = _source_distribution({"inputs": {"particle_source": {"path": "source.csv"}}}, root)
        self.assertEqual(distribution["particle_count"], 2)
        self.assertEqual(distribution["birth_time_min_s"], distribution["birth_time_max_s"])
        self.assertAlmostEqual(distribution["z_vz_pearson_correlation"], 1.0)
        self.assertAlmostEqual(distribution["z_vz_linear_slope_m_s_per_mm"], 100.0)

    def test_identity_allows_only_different_source_authorities(self) -> None:
        _require_equal_identity(arm("A" * 64), arm("B" * 64))
        with self.assertRaisesRegex(ValueError, "source authorities"):
            _require_equal_identity(arm("A" * 64), arm("A" * 64))

    def test_identity_rejects_changed_particle_cohort(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_particle_ids"):
            _require_equal_identity(arm("A" * 64), arm("B" * 64, source_ids=[1, 3]))

    def test_identity_rejects_changed_solver_numerics(self) -> None:
        candidate = arm("B" * 64)
        candidate["identity"]["numerics"]["cell_mm_xyz"]["x"] = 0.2
        with self.assertRaisesRegex(ValueError, "numerics"):
            _require_equal_identity(arm("A" * 64), candidate)

    def test_analysis_reports_deltas_resource_and_markdown(self) -> None:
        baseline, candidate = arm("A" * 64), arm("B" * 64)
        candidate["summary"] = {**candidate["summary"], "transmission": 0.75, "mean_elapsed_time_us": 42.0}
        candidate["resource_metrics"] = {**candidate["resource_metrics"], "wall_clock_seconds": 12.5}
        with patch("common.multipole.analyze_source_model_comparison._arm", side_effect=[baseline, candidate]):
            document = analyze_source_models(__import__("pathlib").Path("baseline"), __import__("pathlib").Path("candidate"))
        self.assertAlmostEqual(document["candidate_minus_baseline"]["transport_exit_metrics"]["transmission"], 0.25)
        self.assertAlmostEqual(document["candidate_minus_baseline"]["resource_metrics"]["wall_clock_seconds"], 2.5)
        self.assertIn("墙钟时间", markdown_report(document))
        self.assertIn("z–vz Pearson r", markdown_report(document))

    def test_generic_series_cli_uses_declared_baseline_and_standard_outputs(self) -> None:
        baseline, candidate = arm("A" * 64), arm("B" * 64)
        baseline["label"], candidate["label"] = "planar", "volume"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, markdown = root / "metrics.json", root / "report.md"
            arguments = [
                "analyze_source_model_comparison", "--series", "planar", "planar.json",
                "--series", "volume", "volume.json", "--baseline-label", "planar",
                "--output", str(output), "--markdown", str(markdown),
            ]
            with patch("common.multipole.analyze_source_model_comparison._arm", side_effect=[baseline, candidate]), patch("sys.argv", arguments):
                self.assertEqual(main(), 0)
            self.assertTrue(output.is_file())
            self.assertIn("planar", markdown.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
