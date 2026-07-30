from __future__ import annotations

import csv
import json
import subprocess
import sys
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
        self.contract = {
            "schema_version": 1,
            "role": "multipole_handoff_publication_contract",
            "selector": {"event": "handoff", "status": "transmitted"},
            "geometry": {
                "axial_plane_mm": 80.6,
                "absolute_tolerance_mm": 1e-9,
                "require_positive_axial_velocity": True,
            },
            "population": {
                "expected_source_particle_count": 2,
                "source_particle_id_policy": "contiguous_one_based",
                "handoff_particle_id_policy": "unique_subset_of_source",
            },
            "canonical_state": {
                "state_event": "canonical_handoff",
                "frame_id": "multipole_exit_frame",
                "clock_epoch_id": "instrument_trigger",
                "source_component_id": "rf_hexapole_ion_optics",
                "target_component_id": "downstream_interface",
                "lineage_policy": (
                    "root_birth_time_plus_component_elapsed_time"
                ),
                "species_policy": "frozen_particle_source_mass_and_charge",
                "particle_weight": 1,
                "phase_reference_id": "multipole_rf_drive",
                "clock_tolerance_us": 1e-9,
            },
        }
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
            "time_us": elapsed_time_us,
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
            contract=self.contract,
        )
        report = validate_component_particle_state_csv(self.output)
        self.assertEqual(report["particles"], 2)
        with self.output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0]), csv_columns())
        self.assertEqual(rows[0]["source_component_id"], "rf_hexapole_ion_optics")
        self.assertEqual(rows[0]["target_component_id"], "downstream_interface")
        self.assertEqual(rows[0]["state_event"], "canonical_handoff")
        self.assertEqual(rows[0]["frame_id"], "multipole_exit_frame")
        self.assertEqual(rows[0]["clock_epoch_id"], "instrument_trigger")
        self.assertEqual(rows[0]["species_id"], "ion_100amu_z1")
        self.assertEqual(float(rows[0]["lineage_birth_time_us"]), 0.0)
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
            contract=self.contract,
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
                contract=self.contract,
            )

    def test_rejects_nonexact_solver_state_header(self) -> None:
        self._write_csv(
            self.state,
            PARTICLE_STATE_COLUMNS + ["unexpected"],
            [
                {
                    **self._state_row(1, "handoff", "transmitted", 1.0),
                    "unexpected": "value",
                }
            ],
        )
        with self.assertRaisesRegex(ValueError, "exact 17-column schema"):
            publish_handoff(
                self.state,
                self.source,
                self.output,
                contract=self.contract,
            )

    def test_rejects_nonexact_particle_source_header(self) -> None:
        self._write_csv(
            self.source,
            SOURCE_COLUMNS + ["unexpected"],
            [
                {
                    "particle_id": 1,
                    "unexpected": "value",
                }
            ],
        )
        with self.assertRaisesRegex(ValueError, "source columns differ"):
            publish_handoff(
                self.state,
                self.source,
                self.output,
                contract=self.contract,
            )

    def test_rejects_duplicate_wrong_status_off_plane_and_backward_rows(
        self,
    ) -> None:
        cases = {
            "duplicates": (
                [
                    self._state_row(1, "handoff", "transmitted", 1.0),
                    self._state_row(1, "handoff", "transmitted", 1.1),
                ],
                "duplicates",
            ),
            "status": (
                [self._state_row(1, "handoff", "lost", 1.0)],
                "status differs",
            ),
            "plane": (
                [
                    {
                        **self._state_row(
                            1, "handoff", "transmitted", 1.0
                        ),
                        "axial_z_mm": 80.61,
                    }
                ],
                "expected axial plane",
            ),
            "backward": (
                [
                    {
                        **self._state_row(
                            1, "handoff", "transmitted", 1.0
                        ),
                        "velocity_axial_m_s": 0,
                    }
                ],
                "positive forward crossing",
            ),
        }
        for name, (rows, message) in cases.items():
            with self.subTest(name=name):
                self._write_csv(self.state, PARTICLE_STATE_COLUMNS, rows)
                with self.assertRaisesRegex(ValueError, message):
                    publish_handoff(
                        self.state,
                        self.source,
                        self.output,
                        contract=self.contract,
                    )

    def test_rejects_source_count_and_lineage_clock_mismatch(self) -> None:
        invalid_count = json.loads(json.dumps(self.contract))
        invalid_count["population"]["expected_source_particle_count"] = 3
        with self.assertRaisesRegex(ValueError, "source count differs"):
            publish_handoff(
                self.state,
                self.source,
                self.output,
                contract=invalid_count,
            )
        row = self._state_row(1, "handoff", "transmitted", 1.0)
        row["time_us"] = 1.1
        self._write_csv(self.state, PARTICLE_STATE_COLUMNS, [row])
        with self.assertRaisesRegex(ValueError, "source lineage clock"):
            publish_handoff(
                self.state,
                self.source,
                self.output,
                contract=self.contract,
            )

    def test_module_help_exposes_one_handoff_analysis_class(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "common.multipole.publish_three_mode_binding",
                "--help",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("{formal,posthoc,handoff}", completed.stdout)
        self.assertIn("--handoff-contract", completed.stdout)

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
