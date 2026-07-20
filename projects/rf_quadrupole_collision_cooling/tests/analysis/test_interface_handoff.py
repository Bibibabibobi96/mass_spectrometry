from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
ANALYSIS = PROJECT_ROOT / "analysis"
sys.path.insert(0, str(ANALYSIS))
SCRIPT = ANALYSIS / "build_interface_handoff.py"
SPEC = importlib.util.spec_from_file_location("build_interface_handoff", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_interface_candidate.json"


class InterfaceContractTests(unittest.TestCase):
    def test_two_boundaries_and_capture_state_remain_distinct(self) -> None:
        contract = MODULE.validate_contract(CONTRACT)["contract"]
        boundaries = contract["boundaries"]
        self.assertEqual(boundaries["source_exit_surface"]["status"], "defined_by_source_component")
        self.assertEqual(boundaries["target_entry_surface"]["status"], "unresolved")
        self.assertEqual(boundaries["pulse_capture_state"]["status"], "unresolved")
        self.assertFalse(boundaries["pulse_capture_state"]["stored_by_default"])
        self.assertFalse(contract["target_reference_distribution"]["hard_acceptance"])
        self.assertFalse(contract["package_generation_allowed"])

    def test_canonical_columns_exclude_derived_quantities(self) -> None:
        contract = MODULE.validate_contract(CONTRACT)["contract"]
        derived = set(contract["state_transfer"]["derived_not_stored"])
        self.assertFalse(derived.intersection(MODULE.EVENT_COLUMNS))
        self.assertNotIn("kinetic_energy_eV", MODULE.EVENT_COLUMNS)
        self.assertNotIn("rf_phase_rad", MODULE.EVENT_COLUMNS)
        self.assertNotIn("divergence_angle_deg", MODULE.EVENT_COLUMNS)

    def test_time_rebase_and_field_free_snapshot(self) -> None:
        event = {
            "instrument_time_us": 12.0,
            "position_x_mm": 1.0,
            "position_y_mm": 2.0,
            "position_z_mm": 3.0,
            "velocity_x_m_s": 1000.0,
            "velocity_y_m_s": -2000.0,
            "velocity_z_m_s": 500.0,
        }
        self.assertEqual(MODULE.solver_local_time_us(12.0, 10.0), 2.0)
        with self.assertRaisesRegex(ValueError, "precedes"):
            MODULE.solver_local_time_us(9.0, 10.0)
        self.assertIsNone(MODULE.field_free_snapshot(event, 11.0))
        snapshot = MODULE.field_free_snapshot(event, 14.0)
        assert snapshot is not None
        self.assertEqual(snapshot["position_x_mm"], 3.0)
        self.assertEqual(snapshot["position_y_mm"], -2.0)
        self.assertEqual(snapshot["position_z_mm"], 4.0)


class ExitEventBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "particle_state.csv"
        legacy = MODULE.legacy
        fieldnames = sorted(legacy.REQUIRED_SOURCE_COLUMNS)
        vx, vy, vz = 100.0, 200.0, 2000.0
        energy = (
            0.5 * 100.0 * legacy.ATOMIC_MASS_KG * (vx**2 + vy**2 + vz**2)
            / legacy.ELEMENTARY_CHARGE_C
        )
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for particle_id in range(100, 0, -1):
                writer.writerow({
                    "particle_id": particle_id,
                    "event": "handoff",
                    "status": "transmitted",
                    "time_us": 10.0 + particle_id * 0.1,
                    "elapsed_time_us": 5.0 + particle_id * 0.01,
                    "rf_phase_rad": 0.25,
                    "axial_z_mm": 90.2,
                    "transverse_x_mm": 0.1,
                    "transverse_y_mm": 0.2,
                    "velocity_axial_m_s": vz,
                    "velocity_x_m_s": vx,
                    "velocity_y_m_s": vy,
                    "kinetic_energy_eV": energy,
                })
        self.manifest = self.root / "run_manifest.json"
        self.manifest.write_text(json.dumps({
            "project": "rf_quadrupole_collision_cooling",
            "mode": "transport_interface_readiness",
            "status": "success",
            "inputs": {
                "baseline": {"sha256": legacy.sha256(PROJECT_ROOT / "config" / "baseline.json")},
                "mode": {"sha256": legacy.sha256(PROJECT_ROOT / "config" / "modes" / "transport_interface_readiness.json")},
                "interface_contract": {"sha256": legacy.sha256(PROJECT_ROOT / "config" / "interface_contract.json")},
            },
            "outputs": [{"path": str(self.source), "sha256": legacy.sha256(self.source)}],
        }), encoding="utf-8")
        self.events = self.root / "source_exit_events.csv"
        self.metadata = self.root / "source_exit_metadata.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_is_compact_lossless_and_sorted(self) -> None:
        metadata = MODULE.build_exit_events(
            self.source, self.manifest, CONTRACT, self.events, self.metadata
        )
        with self.events.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, MODULE.EVENT_COLUMNS)
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]["particle_id"], "1")
        self.assertEqual(rows[0]["species_id"], "ion_100amu_z1")
        self.assertAlmostEqual(float(rows[0]["instrument_time_us"]), 10.1)
        self.assertAlmostEqual(float(rows[0]["lineage_birth_time_us"]), 5.09)
        self.assertAlmostEqual(float(rows[0]["position_z_mm"]), 90.2)
        self.assertAlmostEqual(float(rows[0]["velocity_z_m_s"]), 2000.0)
        self.assertEqual(metadata["particles"], 100)
        self.assertEqual(metadata["derived_outputs_written"], [])
        self.assertLess(metadata["diagnostics"]["maximum_energy_velocity_relative_residual"], 1e-12)
        self.assertEqual(metadata["output"]["source_exit_event_sha256"], MODULE.legacy.sha256(self.events))

    def test_backward_crossing_is_rejected(self) -> None:
        with self.source.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["velocity_axial_m_s"] = "-1"
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted(MODULE.legacy.REQUIRED_SOURCE_COLUMNS), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["outputs"][0]["sha256"] = MODULE.legacy.sha256(self.source)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "forward crossing"):
            MODULE.build_exit_events(self.source, self.manifest, CONTRACT, self.events, self.metadata)


if __name__ == "__main__":
    unittest.main()
