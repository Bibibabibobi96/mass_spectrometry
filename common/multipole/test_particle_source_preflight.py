from __future__ import annotations

import copy
import csv
import hashlib
import json
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

    def test_explicit_operating_point_allows_5ev_without_relaxing_default(self) -> None:
        def five_ev(rows: list[dict[str, object]]) -> None:
            for row in rows:
                row["vz_m_s"] = self.speed * math.sqrt(5.0 / 2.0)

        family = {
            "schema_version": 1,
            "operating_points": {
                "five_ev": {
                    "mass_amu": 100.0,
                    "charge_state": 1,
                    "kinetic_energy_eV": {"distribution": "fixed", "value": 5.0},
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, mutate=five_ev)
            family_path = Path(directory) / "family.json"
            family_path.write_text(json.dumps(family), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "resolved design|resolved closed interval"):
                validate_source(source, self.resolved)
            result = validate_source(
                source,
                self.resolved,
                source_family_path=family_path,
                operating_point_id="five_ev",
            )
        self.assertEqual(
            result["operating_point_binding"]["operating_point_id"], "five_ev"
        )

    def test_operating_point_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            family_path = Path(directory) / "family.json"
            family_path.write_text(
                json.dumps({"schema_version": 1, "operating_points": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires both"):
                validate_source(
                    source,
                    self.resolved,
                    source_family_path=family_path,
                )
            with self.assertRaisesRegex(ValueError, "binding is invalid"):
                validate_source(
                    source,
                    self.resolved,
                    source_family_path=family_path,
                    operating_point_id="missing",
                )

    def test_operating_point_rejects_invalid_energy_domains(self) -> None:
        invalid_models = {
            "fixed_nan": {"distribution": "fixed", "value": math.nan},
            "fixed_positive_inf": {"distribution": "fixed", "value": math.inf},
            "fixed_negative_inf": {"distribution": "fixed", "value": -math.inf},
            "fixed_negative": {"distribution": "fixed", "value": -1.0},
            "uniform_nan_min": {
                "distribution": "uniform",
                "min": math.nan,
                "max": 2.2,
            },
            "uniform_positive_inf_max": {
                "distribution": "uniform",
                "min": 1.8,
                "max": math.inf,
            },
            "uniform_negative_inf_min": {
                "distribution": "uniform",
                "min": -math.inf,
                "max": 2.2,
            },
            "uniform_negative": {
                "distribution": "uniform",
                "min": -0.1,
                "max": 2.2,
            },
            "uniform_reversed": {
                "distribution": "uniform",
                "min": 2.2,
                "max": 1.8,
            },
        }
        for label, energy_model in invalid_models.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                source = self.write_source(directory)
                family = {
                    "schema_version": 1,
                    "operating_points": {
                        "invalid": {
                            "mass_amu": 100.0,
                            "charge_state": 1,
                            "kinetic_energy_eV": energy_model,
                        }
                    },
                }
                family_path = Path(directory) / "family.json"
                family_path.write_text(json.dumps(family), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "must be finite|bounds must be finite"
                ):
                    validate_source(
                        source,
                        self.resolved,
                        source_family_path=family_path,
                        operating_point_id="invalid",
                    )

    def test_operating_point_parsing_and_sha_share_one_frozen_read(self) -> None:
        family = {
            "schema_version": 1,
            "operating_points": {
                "two_ev": {
                    "mass_amu": 100.0,
                    "charge_state": 1,
                    "kinetic_energy_eV": {"distribution": "fixed", "value": 2.0},
                }
            },
        }
        first_bytes = json.dumps(family).encode("utf-8")
        drifted_bytes = json.dumps(
            {
                **family,
                "operating_points": {
                    "two_ev": {
                        **family["operating_points"]["two_ev"],
                        "kinetic_energy_eV": {
                            "distribution": "fixed",
                            "value": 5.0,
                        },
                    }
                },
            }
        ).encode("utf-8")

        class DriftingSourceFamily:
            def __init__(self) -> None:
                self.read_count = 0

            def read_bytes(self) -> bytes:
                self.read_count += 1
                return first_bytes if self.read_count == 1 else drifted_bytes

        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            drifting_family = DriftingSourceFamily()
            result = validate_source(
                source,
                self.resolved,
                source_family_path=drifting_family,  # type: ignore[arg-type]
                operating_point_id="two_ev",
                expected_source_family_sha256=hashlib.sha256(
                    first_bytes
                ).hexdigest(),
            )
        self.assertEqual(drifting_family.read_count, 1)
        self.assertEqual(
            result["operating_point_binding"]["source_family_sha256"],
            hashlib.sha256(first_bytes).hexdigest().upper(),
        )


if __name__ == "__main__":
    unittest.main()
