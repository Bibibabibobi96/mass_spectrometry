from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_octupole_aperture_comparison import (
    _hit_particle_ids,
    _stats,
)


class OctupoleApertureComparisonTests(unittest.TestCase):
    def test_stats_reports_sample_sigma(self) -> None:
        result = _stats([1.0, 2.0, 3.0])
        self.assertEqual(result["mean"], 2.0)
        self.assertEqual(result["sample_sigma"], 1.0)

    def test_hit_particle_ids_preserves_solver_row_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "inputs").mkdir()
            (run / "results").mkdir()
            with (run / "inputs" / "row_map.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("solver_row_index", "particle_id"))
                writer.writeheader()
                writer.writerows((
                    {"solver_row_index": 1, "particle_id": 17},
                    {"solver_row_index": 2, "particle_id": 42},
                ))
            with (run / "results" / "simion_downstream_particles.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=("Ion", "Hit"))
                writer.writeheader()
                writer.writerows((
                    {"Ion": "1", "Hit": "False"},
                    {"Ion": "2", "Hit": "True"},
                ))
            self.assertEqual(_hit_particle_ids(run), {42})


if __name__ == "__main__":
    unittest.main()
