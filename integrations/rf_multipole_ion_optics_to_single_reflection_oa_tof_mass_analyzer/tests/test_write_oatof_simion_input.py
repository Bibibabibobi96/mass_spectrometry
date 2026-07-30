from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import (
    validate_component_particle_state_csv,
    write_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    write_oatof_simion_input as writer,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.rf_handoff_adapter import (
    decode_simion_accelerator_velocity,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class OatofSimionInputWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.csv"
        self.canonical = self.root / "canonical.csv"
        self.ion = self.root / "particles.ion"
        self.row_map = self.root / "row_map.csv"
        self.metadata = self.root / "metadata.json"
        self.rows = [
            self._canonical_row(11, 1.25, (1000.0, 10.0, -20.0)),
            self._canonical_row(27, 2.5, (900.0, -30.0, 40.0)),
        ]
        write_component_particle_state_csv(self.source, self.rows)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_import_does_not_require_legacy_quadrupole_migration(self) -> None:
        script = """
import builtins
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.startswith(
        "projects.rf_quadrupole_ion_optics.analysis."
        "migrate_legacy_component_particle_state"
    ):
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import write_oatof_simion_input
print(write_oatof_simion_input.EXPECTED_FRAME_ID)
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "oatof_global")

    @staticmethod
    def _canonical_row(
        particle_id: int,
        instrument_time_us: float,
        velocity: tuple[float, float, float],
        *,
        frame_id: str = "oatof_global",
    ) -> dict[str, object]:
        mass_amu = 100.0 + particle_id
        return {
            "particle_id": particle_id,
            "parent_particle_id": "",
            "generation": 0,
            "species_id": f"ion_{mass_amu:g}amu_z1",
            "particle_weight": 1,
            "source_component_id": "rf_hexapole_ion_optics",
            "target_component_id": "single_reflection_oa_tof_mass_analyzer",
            "state_event": "canonical_handoff",
            "frame_id": frame_id,
            "clock_epoch_id": "instrument_clock_epoch_v1",
            "instrument_time_us": instrument_time_us,
            "lineage_age_us": instrument_time_us,
            "particle_age_us": instrument_time_us,
            "last_component_elapsed_time_us": instrument_time_us,
            "lineage_birth_time_us": 0,
            "particle_birth_time_us": 0,
            "mass_to_charge_Th": mass_amu,
            "mass_amu": mass_amu,
            "charge_state": 1,
            "position_x_mm": -67.8,
            "position_y_mm": particle_id / 100,
            "position_z_mm": -18.4,
            "velocity_x_m_s": velocity[0],
            "velocity_y_m_s": velocity[1],
            "velocity_z_m_s": velocity[2],
            "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity),
            "phase_reference_id": "multipole_rf_drive",
            "phase_rad": 0.5,
        }

    def test_writes_controlled_canonical_copy_and_strict_solver_inputs(self) -> None:
        metadata = writer.write_oatof_simion_input(
            self.source,
            self.canonical,
            self.ion,
            self.row_map,
            self.metadata,
        )
        self.assertEqual(self.canonical.read_bytes(), self.source.read_bytes())
        self.assertEqual(
            validate_component_particle_state_csv(self.canonical)["particles"], 2
        )

        with self.row_map.open(encoding="utf-8", newline="") as handle:
            mapping = list(csv.DictReader(handle))
        self.assertEqual(list(mapping[0]), writer.ROW_MAP_COLUMNS)
        self.assertEqual(
            [row["solver_row_index"] for row in mapping], ["1", "2"]
        )
        self.assertEqual([row["particle_id"] for row in mapping], ["11", "27"])

        ion_rows = list(csv.reader(self.ion.read_text().splitlines()))
        self.assertTrue(all(len(row) == 11 for row in ion_rows))
        decoded = decode_simion_accelerator_velocity(
            float(ion_rows[0][1]),
            float(ion_rows[0][8]),
            float(ion_rows[0][6]),
            float(ion_rows[0][7]),
        )
        expected_velocity = (1000.0, 10.0, -20.0)
        for actual, expected in zip(decoded, expected_velocity):
            self.assertTrue(
                math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8)
            )

        recorded = json.loads(self.metadata.read_text(encoding="utf-8"))
        self.assertEqual(metadata, recorded)
        self.assertEqual(recorded["role"], "oatof_simion_input_bundle")
        self.assertEqual(recorded["coordinate_frame_id"], "oatof_global")
        self.assertEqual(
            recorded["outputs"]["oatof_ion"]["sha256"],
            file_sha256(self.ion),
        )

    def test_rejects_non_oatof_global_source(self) -> None:
        write_component_particle_state_csv(
            self.source,
            [
                self._canonical_row(
                    11,
                    1.25,
                    (1000.0, 10.0, -20.0),
                    frame_id="multipole_cartesian_z_axis_v1",
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "must be oatof_global"):
            writer.write_oatof_simion_input(
                self.source,
                self.canonical,
                self.ion,
                self.row_map,
                self.metadata,
            )

    def test_rejects_overwriting_source_or_aliasing_outputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            writer.write_oatof_simion_input(
                self.source,
                self.source,
                self.ion,
                self.row_map,
                self.metadata,
            )
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            writer.write_oatof_simion_input(
                self.source,
                self.canonical,
                self.ion,
                self.ion,
                self.metadata,
            )


if __name__ == "__main__":
    unittest.main()
