from __future__ import annotations

import json
import statistics
import tempfile
import unittest
from pathlib import Path

from common.multipole.sources.continuous_axial_volume_source import materialize, rows


def spec() -> dict[str, object]:
    return {
        "schema_version": 1, "role": "continuous_axial_volume_ion_beam_source",
        "method": "independent_spatial_velocity_ion_source_snapshot_v1",
        "source_region_model": "ion_source_volume_cylinder_v1", "source_frame_id": "multipole_cartesian_z_axis_v1", "particle_count": 5000,
        "seed": 73, "snapshot_time_s": 0.0,
        "geometry_mm": {"center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": -1.5, "radius_mm": 0.5, "axial_length_mm": 2.2},
        "velocity_distribution": {"mean_vx_m_s": 0.0, "mean_vy_m_s": 0.0, "mean_vz_m_s": 1964.668136, "sigma_vx_m_s": 35.0,
                                  "sigma_vy_m_s": 35.0, "sigma_vz_m_s": 50.0, "minimum_vz_m_s": 1500.0},
        "ion": {"mass_amu": 100.0, "charge_state": 1},
    }


class ContinuousAxialVolumeSourceTest(unittest.TestCase):
    def test_snapshot_is_reproducible_and_has_no_prescribed_z_vz_relation(self) -> None:
        first, receipt = rows(spec())
        second, _ = rows(spec())
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5000)
        self.assertEqual(receipt["method"], "independent_spatial_velocity_ion_source_snapshot_v1")
        self.assertEqual(receipt["phase_space_assumption"], "spatial_density_and_velocity_distribution_are_independent; no_z_vz_correlation_prescribed")
        reference = float(receipt["snapshot_time_s"])
        for index, row in enumerate(first, start=1):
            self.assertEqual(int(row["particle_id"]), index)
            self.assertLessEqual(float(row["x_mm"]) ** 2 + float(row["y_mm"]) ** 2, 0.5 ** 2 + 1e-12)
            self.assertGreaterEqual(float(row["z_mm"]), -2.6)
            self.assertLessEqual(float(row["z_mm"]), -0.4)
            self.assertGreaterEqual(float(row["vz_m_s"]), 1500.0)
            self.assertEqual(float(row["birth_time_s"]), reference)
        self.assertNotIn("entry_history", receipt)

    def test_gaussian_transverse_components_have_zero_center(self) -> None:
        generated, _ = rows(spec())
        self.assertLess(abs(statistics.fmean(float(row["vx_m_s"]) for row in generated)), 2.0)
        self.assertLess(abs(statistics.fmean(float(row["vy_m_s"]) for row in generated)), 2.0)

    def test_materialization_receipt_binds_the_exact_frozen_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "source.json"
            spec_path.write_text(json.dumps(spec()), encoding="utf-8")
            receipt = materialize(spec_path, root / "source.csv", root / "receipt.json")
        self.assertEqual(receipt["particle_source"]["particle_count"], 5000)
        self.assertRegex(receipt["particle_source"]["sha256"], r"^[A-F0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
