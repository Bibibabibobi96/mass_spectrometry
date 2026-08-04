from __future__ import annotations

import json
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import compile_frontend


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations" / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = (
            REPO.parent
            / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
            / "inputs/multipole_resolved_design.json"
        )
        if not source.is_file():
            raise unittest.SkipTest("local N=1000 octupole source artifact is unavailable")
        cls.upstream = json.loads(source.read_text(encoding="utf-8-sig"))
        cls.oatof = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        cls.connection = json.loads(
            (
                REPO.parent
                / "artifacts/projects/rf_octupole_ion_optics/runs"
                / "20260804_125500__sim__simion__oct-aperture100x090-interface__n459"
                / "inputs/resolved_connection.json"
            ).read_text(encoding="utf-8-sig")
        )

    def test_compiles_disjoint_shield_and_accelerator_voltage_ids(self) -> None:
        gem, contract = compile_frontend(self.upstream, self.oatof, self.connection)
        self.assertEqual(contract["electrodes"]["multipole_shield_id"], 9)
        self.assertEqual(contract["electrodes"]["accelerator_grid2_id"], 17)
        self.assertEqual(contract["electrodes"]["accelerator_ground_id"], 18)
        self.assertIn("9=multipole shield", gem)
        self.assertIn("18=accelerator ground", gem)
        self.assertNotIn("Numerical absorber", gem)
        self.assertNotIn(",1,-90) { cylinder", gem)
        self.assertIn(",1,90) { cylinder", gem)
        self.assertEqual(gem.count("e(9)"), 2)
        self.assertEqual(gem.count("e(18)"), 3)

    def test_preserves_direct_mating_aperture_and_global_origin(self) -> None:
        _, contract = compile_frontend(self.upstream, self.oatof, self.connection)
        self.assertEqual(contract["aperture"], {"shape": "rectangular", "width_mm": 1.0, "height_mm": 0.9})
        self.assertAlmostEqual(contract["source_exit_center_mm"]["x"], -67.8)
        self.assertEqual(
            contract["junction_enclosure"],
            {
                "rod_end_to_accelerator_shield_mm": 1.0,
                "insulated_shield_seam_length_mm": 0.5,
                "surrounded_radially": True,
            },
        )
        self.assertLessEqual(contract["dimensions"]["nx"] * contract["dimensions"]["ny"] * contract["dimensions"]["nz"], 30_000_000)

    def test_rejects_nonzero_gap(self) -> None:
        connection = json.loads(json.dumps(self.connection))
        connection["connector"]["length_mm"] = 1.0
        with self.assertRaisesRegex(ValueError, "zero gap"):
            compile_frontend(self.upstream, self.oatof, connection)


if __name__ == "__main__":
    unittest.main()
