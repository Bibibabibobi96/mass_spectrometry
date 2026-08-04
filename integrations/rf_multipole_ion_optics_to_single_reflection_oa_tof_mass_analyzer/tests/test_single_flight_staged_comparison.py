from __future__ import annotations

import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_to_staged import compare


REPO = Path(__file__).resolve().parents[3]
RUNS = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs"


class SingleFlightStagedComparisonTests(unittest.TestCase):
    def test_pairs_original_mother_sample_ids_and_separates_tof_origins(self) -> None:
        single = RUNS / "20260804_142000__sim__simion__rf-oatof-single-flight-gap0__n1000"
        interface = RUNS / "20260804_125500__sim__simion__oct-aperture100x090-interface__n459"
        staged = RUNS / "20260804_130500__sim__simion__oct-aperture100x090-oatof__n396"
        if not all(path.is_dir() for path in (single, interface, staged)):
            self.skipTest("local N=1000 paired source runs are unavailable")
        paired, result = compare(
            single / "results/single_flight_particle_checkpoints.csv",
            single / "inputs/single_flight_initial_global_state.csv",
            interface / "inputs/canonical_oatof_entry.csv",
            interface / "results/simion_local_accelerator_exit.csv",
            staged / "inputs/row_map.csv",
            staged / "results/simion_downstream_particles.csv",
            39.58788438081105,
        )
        self.assertEqual(len(paired), 1000)
        self.assertEqual(result["census"]["paired"]["detector_crossing"], 368)
        self.assertFalse(
            result["resolution"]["non_equivalent_elapsed_diagnostics"][
                "resolution_comparison_allowed"
            ]
        )
        self.assertAlmostEqual(
            result["resolution"]["non_equivalent_elapsed_diagnostics"][
                "staged_published_downstream_from_grid2_restart"
            ]["direct_fwhm_tof_ns"],
            2.1948713386805707,
        )


if __name__ == "__main__":
    unittest.main()
