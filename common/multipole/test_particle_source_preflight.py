from __future__ import annotations

import copy
import csv
import math
import tempfile
import unittest
from pathlib import Path
from collections.abc import Callable

from common.multipole.compile_design_request import compile_design_request
from common.multipole.particle_source_preflight import (
    AMU_KG,
    COLUMNS,
    E_CHARGE_C,
    validate_source,
)
from common.multipole.test_compile_design_request import design_request


class ParticleSourcePreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        request = design_request(segmentation={"strategy": "off"})
        self.resolved = compile_design_request(
            request, expected_identity=request["identity"]
        )
        self.mass = 100.0
        energy = self.resolved["particle_source"]["energy_model"]["kinetic_energy_eV"]
        self.speed = math.sqrt(2 * energy * E_CHARGE_C / (self.mass * AMU_KG))

    def write_source(
        self,
        directory: str,
        *,
        count: int = 100,
        mutate: Callable[[list[dict[str, object]]], None] | None = None,
    ) -> Path:
        path = Path(directory) / "particles.csv"
        rows = []
        source_z = self.resolved["interfaces_mm"]["entrance"]["particle_plane_z_mm"]
        for particle_id in range(1, count + 1):
            row = {
                "particle_id": particle_id,
                "birth_time_s": 0.0,
                "x_mm": 0.0,
                "y_mm": 0.0,
                "z_mm": source_z,
                "vx_m_s": 0.0,
                "vy_m_s": 0.0,
                "vz_m_s": self.speed,
                "mass_amu": self.mass,
                "charge_state": self.resolved["particle_source"]["charge_state"],
            }
            rows.append(row)
        if mutate:
            mutate(rows)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_valid_source_binds_hash_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_source(self.write_source(directory), self.resolved)
        self.assertEqual(result["particle_count"], 100)
        self.assertEqual(result["mass_amu"], self.mass)
        self.assertEqual(result["parent_resolved_design_sha256"], self.resolved["resolved_sha256"])

    def test_source_attacks_fail_closed(self) -> None:
        attacks = {
            "duplicate": lambda rows: rows[1].update(particle_id=1),
            "nan": lambda rows: rows[0].update(x_mm="nan"),
            "plane": lambda rows: rows[0].update(z_mm=float(rows[0]["z_mm"]) + 1e-6),
            "velocity": lambda rows: rows[0].update(vz_m_s=float(rows[0]["vz_m_s"]) * 1.01),
            "mass": lambda rows: rows[0].update(mass_amu=101.0),
            "clock": lambda rows: rows[0].update(birth_time_s=-1e-9),
        }
        for label, mutation in attacks.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    validate_source(
                        self.write_source(directory, mutate=mutation),
                        copy.deepcopy(self.resolved),
                    )

    def test_nonstandard_count_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            validate_source(self.write_source(directory, count=99), self.resolved)

    def test_bounded_distribution_records_actual_statistics_and_rejects_outlier(self) -> None:
        bounded = copy.deepcopy(self.resolved)
        bounded["particle_source"]["energy_model"] = {
            "kind": "bounded_distribution",
            "minimum_energy_eV": 1.8,
            "maximum_energy_eV": 2.2,
            "nominal_energy_eV": 2.0,
            "authority": "fixture.json",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            result = validate_source(source, bounded)
        statistics = result["sample_energy_statistics_eV"]
        self.assertAlmostEqual(statistics["minimum"], 2.0)
        self.assertAlmostEqual(statistics["maximum"], 2.0)
        self.assertAlmostEqual(statistics["mean"], 2.0)

        def outside(rows: list[dict[str, object]]) -> None:
            rows[0]["vz_m_s"] = self.speed * math.sqrt(2.21 / 2.0)

        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError, "outside the resolved closed interval"
        ):
            validate_source(self.write_source(directory, mutate=outside), bounded)


if __name__ == "__main__":
    unittest.main()
