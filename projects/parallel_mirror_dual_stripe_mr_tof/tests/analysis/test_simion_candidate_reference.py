from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, build_simion_gem, derive_two_zone_focus, load_contract, write_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry import (
    ELECTRODE_IDS,
    build_full_candidate_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
    summarize_events,
)


PROJECT = Path(__file__).resolve().parents[2]


class SimionCandidateReferenceTest(unittest.TestCase):
    def test_candidate_places_two_zone_focus_at_central_plane(self) -> None:
        focus = derive_two_zone_focus(load_contract(PROJECT / "config" / "simion_candidate_two_zone.json"))
        self.assertGreater(focus.focus_after_exit_mm, 0.0)
        self.assertAlmostEqual(39.6 + focus.focus_after_exit_mm + focus.accelerator_translation_z_mm, 0.0)

    def test_gem_has_five_mirrored_electrodes_and_two_stripe_voltage_pairs(self) -> None:
        gem = build_simion_gem(load_contract(PROJECT / "config" / "simion_candidate_two_zone.json"))
        for electrode_id in range(1, 15):
            self.assertIn(f"e({electrode_id})", gem)
        self.assertIn("surface=none", gem)

    def test_writer_emits_a_lf_gem_source(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "nested" / "candidate.gem"
            write_gem(PROJECT / "config" / "simion_candidate_two_zone.json", output)
            self.assertTrue(output.is_file())
            self.assertNotIn("\r\n", output.read_text(encoding="utf-8"))

    def test_rejects_wrong_coordinate_frame(self) -> None:
        contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")
        contract["coordinate_system"]["frame_id"] = "wrong"
        with self.assertRaises(CandidateContractError):
            derive_two_zone_focus(contract)

    def test_full_candidate_has_all_stable_electrodes_and_native_grids(self) -> None:
        gem = build_full_candidate_gem(PROJECT / "config" / "simion_candidate_two_zone.json")
        self.assertIn("surface=none", gem)
        for group in ELECTRODE_IDS.values():
            identifiers = (group,) if isinstance(group, int) else group
            for identifier in identifiers:
                self.assertIn(f"e({identifier})", gem)
        self.assertIn("e(23) { box3D", gem)
        self.assertIn("e(24) { box3D", gem)
        self.assertIn("box3D(-30,-310,-33.6,30,-250,-33.6)", gem)
        self.assertIn("box3D(-30,-310,0,30,-250,0)", gem)
        self.assertIn("focus_phase_z = 0.12918680341102168", gem)
        self.assertIn("polyline(-55,-230,-30,-230,-42,-180)", gem)

    def test_event_analysis_retains_losses_and_refuses_small_sample_fwhm(self) -> None:
        events = parse_events(
            "MRTOF_EVENT central_plane ion=1 n=1 t_us=1 x_mm=0 y_mm=0\n"
            "MRTOF_EVENT terminal ion=1 t_us=5 x_mm=0 y_mm=285 z_mm=0 turns=50 central_crossings=2\n"
            "MRTOF_EVENT terminal ion=2 t_us=5.1 x_mm=0 y_mm=3 z_mm=0 turns=48 central_crossings=1\n"
        )
        summary = summarize_events(events)
        self.assertEqual(summary["particle_terminal_count"], 2)
        self.assertEqual(summary["detector_hit_count"], 1)
        self.assertEqual(summary["target_k_count"], 1)
        self.assertTrue(summary["all_losses_retained"])
        self.assertIsNone(summary["detector_tof_fwhm_us"])


if __name__ == "__main__":
    unittest.main()
