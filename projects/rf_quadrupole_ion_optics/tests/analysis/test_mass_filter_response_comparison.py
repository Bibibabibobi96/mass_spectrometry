from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_ion_optics.workflows.mass_filter_reference import (
    evaluate_comparison as module,
)


PROJECT_ROOT = Path(__file__).parents[2]


def write_response(
    path: Path,
    masses: list[float],
    *,
    particles: int,
    offset: float = 0.0,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "mass_Th",
                "particles",
                "transmitted",
                "transmission_fraction",
            ),
        )
        writer.writeheader()
        for index, mass in enumerate(masses):
            transmission = min(1.0, 0.2 + index * 0.02 + offset)
            writer.writerow(
                {
                    "mass_Th": mass,
                    "particles": particles,
                    "transmitted": round(particles * transmission),
                    "transmission_fraction": transmission,
                }
            )


class MassFilterResponseComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.baseline = PROJECT_ROOT / "config" / "baseline.json"
        self.mode = (
            PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"
        )
        mode = json.loads(self.mode.read_text(encoding="utf-8"))
        self.solver_masses = [
            float(value)
            for value in mode["mass_scan_spec"]["paired_source_masses_Th"]
        ]
        self.l1_masses = [94.0 + 0.5 * index for index in range(29)]
        self.comsol = self.root / "comsol.csv"
        self.simion = self.root / "simion.csv"
        self.l1 = self.root / "l1.csv"
        write_response(self.comsol, self.solver_masses, particles=1000)
        write_response(
            self.simion,
            self.solver_masses,
            particles=1000,
            offset=0.01,
        )
        write_response(self.l1, self.l1_masses, particles=100)
        self.source_metrics = {
            "COMSOL": {"status": "PASS", "particles_per_mass": 1000},
            "SIMION": {"status": "PASS", "particles_per_mass": 1000},
            "L1": {"status": "PASS", "particle_count_per_mass": 100},
        }

    def test_seven_point_solvers_compare_against_29_point_l1(self) -> None:
        rows, metrics = module.compare_responses(
            self.comsol,
            self.simion,
            self.l1,
            self.baseline,
            self.mode,
            self.source_metrics,
            1000,
            1000,
        )
        self.assertEqual(len(rows), 7)
        self.assertEqual(metrics["particles_per_mass"], 1000)
        self.assertEqual(metrics["decision_status"], "NOT_EVALUATED")
        self.assertFalse(
            metrics["acceptance"]["acceptance_tolerance_frozen"]
        )

    def test_solver_particle_count_mismatch_is_rejected(self) -> None:
        write_response(self.simion, self.solver_masses, particles=100)
        with self.assertRaisesRegex(ValueError, "particles per mass differ"):
            module.compare_responses(
                self.comsol,
                self.simion,
                self.l1,
                self.baseline,
                self.mode,
                self.source_metrics,
                1000,
                1000,
            )

    def test_missing_l1_grid_point_is_rejected(self) -> None:
        write_response(self.l1, self.l1_masses[:-1], particles=100)
        with self.assertRaisesRegex(ValueError, "L1 response grid is incomplete"):
            module.compare_responses(
                self.comsol,
                self.simion,
                self.l1,
                self.baseline,
                self.mode,
                self.source_metrics,
                1000,
                1000,
            )

    def test_reported_n_must_match_portable_source_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "differs from source N"):
            module.compare_responses(
                self.comsol,
                self.simion,
                self.l1,
                self.baseline,
                self.mode,
                self.source_metrics,
                100,
                100,
            )

    def test_source_metrics_n_must_match_verified_source_rows(self) -> None:
        self.source_metrics["COMSOL"]["particles_per_mass"] = 100
        with self.assertRaisesRegex(
            ValueError,
            "source metrics particle count differs from source N",
        ):
            module.compare_responses(
                self.comsol,
                self.simion,
                self.l1,
                self.baseline,
                self.mode,
                self.source_metrics,
                1000,
                1000,
            )

    def test_invalid_transmitted_count_is_rejected(self) -> None:
        self.comsol.write_text(
            "mass_Th,particles,transmitted,transmission_fraction\n"
            "96,1000,1001,0.5\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "invalid value"):
            module.read_response(self.comsol)

    def test_fraction_must_match_transmitted_over_particles(self) -> None:
        self.comsol.write_text(
            "mass_Th,particles,transmitted,transmission_fraction\n"
            "96,1000,500,0.6\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "fraction is inconsistent"):
            module.read_response(self.comsol)

    def test_failed_source_metrics_are_rejected_before_comparison(self) -> None:
        self.source_metrics["SIMION"]["status"] = "FAIL"
        with self.assertRaisesRegex(ValueError, "source functional metrics failed"):
            module.compare_responses(
                self.comsol,
                self.simion,
                self.l1,
                self.baseline,
                self.mode,
                self.source_metrics,
                1000,
                1000,
            )


if __name__ == "__main__":
    unittest.main()
