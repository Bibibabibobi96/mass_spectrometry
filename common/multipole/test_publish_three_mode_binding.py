from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from common.multipole.publish_three_mode_binding import publish_binding, publish_handoff


REPO_ROOT = Path(__file__).parents[2]
SOURCE_COLUMNS = [
    "particle_id",
    "birth_time_s",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "mass_amu",
    "charge_state",
]


class ThreeModeBindingPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.csv"
        self.state = self.root / "state.csv"
        self.output = self.root / "handoff.csv"
        self._write_csv(
            self.source,
            SOURCE_COLUMNS,
            [
                {
                    "particle_id": particle_id,
                    "birth_time_s": 0,
                    "x_mm": 0,
                    "y_mm": 0,
                    "z_mm": -1.5,
                    "vx_m_s": 0,
                    "vy_m_s": 0,
                    "vz_m_s": 1000,
                    "mass_amu": 100,
                    "charge_state": 1,
                }
                for particle_id in (1, 2)
            ],
        )
        self._write_csv(
            self.state,
            PARTICLE_STATE_COLUMNS,
            [
                self._state_row(1, "source", "alive", 0.0),
                self._state_row(1, "handoff", "transmitted", 1.0),
                self._state_row(2, "source", "alive", 0.0),
                self._state_row(2, "handoff", "transmitted", 1.2),
            ],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _state_row(
        particle_id: int,
        event: str,
        status: str,
        elapsed_time_us: float,
    ) -> dict:
        return {
            "particle_id": particle_id,
            "event": event,
            "status": status,
            "terminal_reason": "none",
            "time_us": 2.0 + elapsed_time_us,
            "elapsed_time_us": elapsed_time_us,
            "rf_phase_rad": 0.5,
            "axial_z_mm": 80.6 if event == "handoff" else -1.5,
            "transverse_x_mm": particle_id / 10,
            "transverse_y_mm": -particle_id / 10,
            "velocity_axial_m_s": 1000,
            "velocity_x_m_s": 10,
            "velocity_y_m_s": -20,
            "kinetic_energy_eV": 1,
            "radial_position_mm": 0.2,
            "divergence_angle_deg": 1,
            "max_rod_radius_mm": 0.2,
        }

    def test_publishes_solver_neutral_handoff_for_one_project(self) -> None:
        publish_handoff(
            self.state,
            self.source,
            self.output,
            project_id="rf_hexapole_ion_optics",
        )
        report = validate_component_particle_state_csv(self.output)
        self.assertEqual(report["particles"], 2)
        with self.output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0]), csv_columns())
        self.assertEqual(rows[0]["source_component_id"], "rf_hexapole_ion_optics")
        self.assertEqual(rows[0]["state_event"], "canonical_handoff")
        self.assertEqual(float(rows[0]["position_z_mm"]), 80.6)

    def test_preserves_losses_by_publishing_only_handoff_survivors(self) -> None:
        self._write_csv(
            self.state,
            PARTICLE_STATE_COLUMNS,
            [self._state_row(1, "handoff", "transmitted", 1.0)],
        )
        publish_handoff(
            self.state,
            self.source,
            self.output,
            project_id="rf_octupole_ion_optics",
        )
        self.assertEqual(
            validate_component_particle_state_csv(self.output)["particles"],
            1,
        )

    def test_rejects_unknown_handoff_particle_identity(self) -> None:
        self._write_csv(
            self.state,
            PARTICLE_STATE_COLUMNS,
            [self._state_row(3, "handoff", "transmitted", 1.0)],
        )
        with self.assertRaisesRegex(ValueError, "unknown source particle"):
            publish_handoff(
                self.state,
                self.source,
                self.output,
                project_id="rf_octupole_ion_optics",
            )

    def test_projects_do_not_define_private_three_mode_publishers(self) -> None:
        duplicates = list(
            (REPO_ROOT / "projects").glob("rf_*pole_ion_optics/**/publish_three_mode_binding.py")
        )
        self.assertEqual(duplicates, [])

    def test_binding_rejects_missing_preregistered_bootstrap(self) -> None:
        preregistration = self.root / "preregistration.json"
        preregistration.write_text(
            json.dumps({"project_id": "rf_octupole_ion_optics"}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "must freeze bootstrap"):
            publish_binding(
                REPO_ROOT,
                preregistration,
                [],
                self.root / "binding",
            )


if __name__ == "__main__":
    unittest.main()
