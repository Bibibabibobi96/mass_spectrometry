from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from common.multipole.campaign_analysis import (
    _source_binding,
    compare_modes,
    compare_pair,
    compare_to_baseline,
    series_markdown_report,
)


def arm(project: str, run_id: str, *, offset: float = 0.0) -> dict:
    return {
        "project_id": project,
        "run_id": run_id,
        "particle_source_sha256": "A" * 64,
        "centroid_x_mm": offset,
        "centroid_y_mm": 0.0,
        "transmission": 1.0,
        "centered_spatial_rms_spread_mm": 0.4 + offset,
        "mean_direction_tilt_deg": 0.1 + offset,
        "centered_angular_rms_spread_deg": 3.0 + offset,
        "mean_energy_eV": 2.0 + offset,
        "centered_rms_energy_spread_eV": 0.1 + offset,
        "mean_elapsed_time_us": 40.0 + offset,
        "centered_rms_elapsed_time_spread_us": 0.2 + offset,
        "p95_radius_mm": 0.8 + offset,
        "p99_radius_mm": 0.9 + offset,
        "p95_divergence_deg": 5.0 + offset,
        "p99_divergence_deg": 6.0 + offset,
    }


class CampaignAnalysisTests(unittest.TestCase):
    def test_source_binding_fails_closed_on_state_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            state = run_dir / "canonical_particle_state.csv"
            state.write_text("particle_id,event,status\n1,source,alive\n", encoding="utf-8")
            state_sha = hashlib.sha256(state.read_bytes()).hexdigest().upper()
            figure_path = run_dir / "exit_state_diagnostics.json"
            figure = {
                "role": "multipole_exit_state_figure_manifest",
                "series": [
                    {
                        "run_id": "run-1",
                        "canonical_state": {"path": str(state), "sha256": state_sha},
                    }
                ],
            }
            figure_path.write_text(json.dumps(figure), encoding="utf-8")
            config_path = run_dir / "run_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "provenance": {
                            "runtime_selection_kind": "campaign_experiment",
                            "campaign_id": "campaign-1",
                            "campaign_sha256": "A" * 64,
                            "experiment_id": "experiment-1",
                        },
                        "parameters": {"experiment_id": "experiment-1"},
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = run_dir / "run_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "role": "simulation_run_manifest",
                        "run_config": {"path": str(config_path)},
                        "outputs": [
                            {"path": str(figure_path)},
                            {"path": str(state)},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            row = {
                "experiment_id": "experiment-1",
                "project_id": "project-1",
                "authorized_run_id": "run-1",
            }
            capability = {
                "input_roles": {
                    "source_run_manifest": "simulation_run_manifest",
                    "source_figure_manifest": "multipole_exit_state_figure_manifest",
                }
            }
            status_row = {"status": "SUCCESS", "manifest": str(manifest_path)}
            ready = _source_binding(
                status_row,
                row,
                capability,
                campaign_id="campaign-1",
                campaign_sha256="A" * 64,
            )
            self.assertEqual(ready[0], "READY")
            figure["series"][0]["canonical_state"]["sha256"] = "B" * 64
            figure_path.write_text(json.dumps(figure), encoding="utf-8")
            failed = _source_binding(
                status_row,
                row,
                capability,
                campaign_id="campaign-1",
                campaign_sha256="A" * 64,
            )
            self.assertEqual(failed[:2], ("FAILED", "source state SHA-256 differs"))

    def test_pair_reports_segmented_minus_no_acceleration(self) -> None:
        result = compare_pair(arm("p", "left"), arm("p", "right", offset=0.25))
        self.assertAlmostEqual(result["centroid_shift_mm"], 0.25)
        self.assertAlmostEqual(
            result["segmented_minus_no_acceleration"]["mean_energy_eV"], 0.25
        )

    def test_pair_rejects_different_project_or_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "project or particle source"):
            compare_pair(arm("left", "a"), arm("right", "b"))
        changed = arm("left", "b")
        changed["particle_source_sha256"] = "B" * 64
        with self.assertRaisesRegex(ValueError, "project or particle source"):
            compare_pair(arm("left", "a"), changed)

    def test_named_pair_freezes_right_minus_left_direction(self) -> None:
        result = compare_modes(
            arm("p", "segmented"),
            arm("p", "endface", offset=-0.2),
            left_mode="segmented_acceleration",
            right_mode="exit_aperture_plate_acceleration",
        )
        self.assertEqual(result["left_mode"], "segmented_acceleration")
        self.assertEqual(result["right_mode"], "exit_aperture_plate_acceleration")
        self.assertAlmostEqual(
            result["right_minus_left"]["centered_angular_rms_spread_deg"],
            -0.2,
        )

    def test_variable_series_comparison_and_markdown(self) -> None:
        baseline = arm("p", "baseline")
        candidate = arm("p", "candidate", offset=-0.1)
        comparison = compare_to_baseline(baseline, candidate)
        self.assertAlmostEqual(comparison["centroid_shift_mm"], 0.1)
        self.assertAlmostEqual(
            comparison["candidate_minus_baseline"][
                "centered_angular_rms_spread_deg"
            ],
            -0.1,
        )
        document = {
            "baseline_label": "P0",
            "series": [{"label": "P0", **baseline}],
            "comparisons": {},
            "claim_limit": "descriptive only",
        }
        report = series_markdown_report(document)
        self.assertIn("P0", report)
        self.assertIn("descriptive only", report)


if __name__ == "__main__":
    unittest.main()
