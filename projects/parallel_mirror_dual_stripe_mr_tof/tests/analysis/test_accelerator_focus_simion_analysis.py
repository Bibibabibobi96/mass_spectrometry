from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_simion_analysis import analyze
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_accelerator_focus_source import (
    materialize as materialize_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    derive_two_zone_focus,
    derive_two_zone_placement,
    load_contract,
)

PROJECT = Path(__file__).parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AcceleratorFocusSimionAnalysisTest(unittest.TestCase):
    def test_source_materializer_reuses_reviewed_geometry_but_generates_axial_family(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "focus.fly2"
            receipt_path = root / "source.json"
            receipt = materialize_source(
                CONTRACT, CONTRACT, "accelerator_focus_bunch_fly2", output, receipt_path,
            )
            text = output.read_text(encoding="utf-8")
        self.assertEqual(receipt["particle_count"], 100)
        self.assertEqual(receipt["release_interval_in_gap_1_mm"], [2.9, 3.1])
        self.assertEqual(text.count("standard_beam {"), 100)
        self.assertNotIn("circle_distribution", text)

    def test_source_materializer_rejects_geometry_drift(self) -> None:
        reviewed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        reviewed["accelerator"]["gap_1_mm"] += 0.1
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reviewed_path = root / "reviewed.json"
            reviewed_path.write_text(json.dumps(reviewed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewed PA/IOB"):
                materialize_source(
                    CONTRACT, reviewed_path, "accelerator_focus_center_fly2",
                    root / "focus.fly2", root / "source.json",
                )

    def test_complete_axial_family_matches_analytic_reference(self) -> None:
        contract = load_contract(CONTRACT)
        placement = derive_two_zone_placement(contract)
        focus = derive_two_zone_focus(contract)
        accelerator = contract["accelerator"]
        mass = contract["particle_source"]["species"]["mass_th"]
        releases = [2.9, 3.0, 3.1]
        lines = ["MRTOF_ACCELERATOR_FOCUS: status=prototype target_plane_z_mm=0"]
        for ion, release in enumerate(releases, start=1):
            z = placement.repeller_z_mm - release
            time_us = 1.0e6 * time_to_fixed_plane_s(
                accelerator["repeller_v"], accelerator["intermediate_grid_v"],
                accelerator["gap_1_mm"], accelerator["gap_2_mm"], release, 0.0,
                focus.focus_after_exit_mm, mass, exit_v=accelerator["exit_grid_v"],
            )
            lines.extend([
                f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion={ion} t_us=0 x_mm=0 y_mm={placement.focus_y_mm} z_mm={z}",
                f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion={ion} t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1",
                f"MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion={ion} code=1 reached_focus=1 t_us={time_us} x_mm=0 y_mm={placement.focus_y_mm} z_mm=0",
            ])
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = analyze(log, CONTRACT, 3)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["focus_particle_count"], 3)
        self.assertLess(result["timing"]["analytic_max_abs_time_error_ns"], 1.0e-8)
        # The exact first derivative is zero at the centre.  A finite symmetric
        # secant over +/-0.1 mm retains a small higher-order odd contribution.
        self.assertLess(abs(result["timing"]["linear_slope_ps_per_mm"]), 10.0)
        self.assertGreater(result["timing"]["quadratic_coefficient_ps_per_mm2"], 0.0)

    def test_missing_focus_is_reported_without_fabricating_timing(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        placement = derive_two_zone_placement(contract)
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 y_mm=0 z_mm={placement.repeller_z_mm - 3}\n"
            "MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=2 reached_focus=0 t_us=3 x_mm=0 y_mm=0 z_mm=1\n"
        )
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text(text, encoding="utf-8")
            result = analyze(log, CONTRACT, 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["focus_particle_count"], 0)
        self.assertIsNone(result["timing"])

    def test_one_particle_does_not_fabricate_derivatives(self) -> None:
        contract = load_contract(CONTRACT)
        placement = derive_two_zone_placement(contract)
        focus = derive_two_zone_focus(contract)
        accelerator = contract["accelerator"]
        mass = contract["particle_source"]["species"]["mass_th"]
        release = accelerator["release_position_in_gap_1_mm"]
        time_us = 1.0e6 * time_to_fixed_plane_s(
            accelerator["repeller_v"], accelerator["intermediate_grid_v"],
            accelerator["gap_1_mm"], accelerator["gap_2_mm"], release, 0.0,
            focus.focus_after_exit_mm, mass, exit_v=accelerator["exit_grid_v"],
        )
        text = (
            f"MRTOF_ACCELERATOR_FOCUS_EVENT source ion=1 t_us=0 x_mm=0 y_mm=0 z_mm={placement.repeller_z_mm-release}\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=1 t_us={time_us} x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1\n"
            f"MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=1 code=1 reached_focus=1 t_us={time_us} x_mm=0 y_mm=0 z_mm=0\n"
        )
        with TemporaryDirectory() as directory:
            log = Path(directory) / "focus.log"
            log.write_text(text, encoding="utf-8")
            result = analyze(log, CONTRACT, 1)
        self.assertIsNone(result["timing"]["linear_slope_ps_per_mm"])
        self.assertIsNone(result["timing"]["quadratic_coefficient_ps_per_mm2"])
        self.assertIsNone(result["timing"]["derived_first_order_focus_project_z_mm"])


if __name__ == "__main__":
    unittest.main()
