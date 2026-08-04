from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import materialize


REPO = Path(__file__).resolve().parents[3]


class SingleFlightSourceTests(unittest.TestCase):
    def test_maps_all_n1000_particles_without_handoff_filtering(self) -> None:
        run = (
            REPO.parent
            / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
        )
        if not run.is_dir():
            self.skipTest("local N=1000 octupole source artifact is unavailable")
        connection = json.loads(
            (
                REPO.parent
                / "artifacts/projects/rf_octupole_ion_optics/runs"
                / "20260804_125500__sim__simion__oct-aperture100x090-interface__n459"
                / "inputs/resolved_connection.json"
            ).read_text(encoding="utf-8-sig")
        )
        ion, states = materialize(run / "inputs/particle_source.csv", connection)
        self.assertEqual(len(ion), 1000)
        self.assertEqual(len(states), 1000)
        first = states[0]
        self.assertAlmostEqual(float(first["position_x_mm"]), -149.9)
        self.assertAlmostEqual(float(first["position_y_mm"]), -0.08166000357342909)
        self.assertAlmostEqual(float(first["position_z_mm"]), -18.32170905524317)
        self.assertAlmostEqual(float(first["velocity_x_m_s"]), 1959.568200662977)
        self.assertAlmostEqual(float(first["velocity_y_m_s"]), -105.35913222607861)
        self.assertAlmostEqual(float(first["velocity_z_m_s"]), -91.67991313892833)
        self.assertEqual(len(ion[0]), 11)

    def test_rejects_noncontiguous_particle_ids(self) -> None:
        connection = {
            "spatial_registration": {
                "rotation_upstream_to_downstream": [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "translation_mm": [0.0, 0.0, 0.0],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(["particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state"])
                writer.writerow([2, 0, 0, 0, 0, 0, 0, 1, 100, 1])
            with self.assertRaisesRegex(ValueError, "contiguous"):
                materialize(path, connection)


if __name__ == "__main__":
    unittest.main()
