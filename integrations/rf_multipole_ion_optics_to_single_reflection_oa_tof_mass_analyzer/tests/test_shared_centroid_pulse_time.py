from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
)


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = INTEGRATION_ROOT.parents[1]
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import derive_shared_centroid_pulse_time as module


class SharedCentroidPulseTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolved_temp = tempfile.TemporaryDirectory()
        registry_path = (
            REPO_ROOT
            / "integrations"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "config"
            / "connection_profiles.json"
        )
        registry = load_connection_profile_registry(registry_path)
        upstream = registry["profiles"][0]["upstream"]
        upstream.pop("port_binding")
        upstream["port_contract"] = (
            "projects/rf_quadrupole_ion_optics/config/interfaces/provided/"
            "rf_multipole_exit_no_acceleration_full_length.json"
        )
        resolved = resolve_connection_profile(
            registry,
            "rf_quadrupole_oatof_shield_terminal_direct_mating_gap_0mm",
            repo_root=REPO_ROOT,
        )
        cls.resolved = Path(cls.resolved_temp.name) / "resolved_connection.json"
        cls.resolved.write_text(json.dumps(resolved), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.resolved_temp.cleanup()

    def setUp(self) -> None:
        self.baseline = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "baseline.json"
        self.pre_pulse = (
            INTEGRATION_ROOT / "config" / "family_pre_pulse_interface_transport.json"
        )

    def _write(self, path: Path, rows: list[dict]) -> None:
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_velocity_and_entry_time_drive_selected_species_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "particles.csv"
            base = {
                "position_x_mm": -67.8,
                "position_y_mm": 0.0, "position_z_mm": -18.42918680341103,
                "velocity_y_m_s": 0.0, "velocity_z_m_s": 0.0,
                "charge_state": 1,
                "event": "oatof_entry", "status": "transmitted",
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch_v1",
            }
            self._write(path, [
                dict(base, particle_id=1, instrument_time_us=10.0, mass_amu=100.0,
                     velocity_x_m_s=1000.0, kinetic_energy_eV=1.0),
                dict(base, particle_id=2, instrument_time_us=12.0, mass_amu=100.0,
                     velocity_x_m_s=2000.0, kinetic_energy_eV=4.0),
            ])
            result = module.derive_schedule(
                path, self.baseline, self.pre_pulse, self.resolved
            )
            release_x = result["geometry_mm"]["release_x"]
            target_x = result["geometry_mm"]["target_centroid_x"]
            expected = (1000 * (target_x - release_x) + (1000 * 10 + 2000 * 12) / 2) / 1500
            self.assertAlmostEqual(result["derived_pulse_time_us"], expected)
            self.assertAlmostEqual(result["predicted_centroid_error_x_mm"], 0.0)

    def test_finite_wall_filter_uses_particle_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "particles.csv"
            base = {
                "instrument_time_us": 10.0, "mass_amu": 50.0, "charge_state": 2,
                "position_x_mm": -67.8,
                "position_y_mm": 0.49, "position_z_mm": -18.42918680341103,
                "velocity_x_m_s": 1000.0, "velocity_z_m_s": 0.0,
                "event": "oatof_entry", "status": "transmitted",
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch_v1",
            }
            self._write(path, [
                dict(base, particle_id=1, velocity_y_m_s=0.0),
                dict(base, particle_id=2, velocity_y_m_s=100.0),
            ])
            result = module.derive_schedule(
                path, self.baseline, self.pre_pulse, self.resolved
            )
            self.assertEqual(result["target_species"], {"mass_amu": 50.0, "charge_state": 2})
            self.assertEqual(result["population_counts"]["outer_face_geometric_acceptance"], 2)
            self.assertEqual(result["population_counts"]["predicted_finite_wall_survivors"], 1)

    def test_mixed_species_requires_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "particles.csv"
            rows = []
            for particle_id, mass, charge in ((1, 100.0, 1), (2, 50.0, 2)):
                rows.append({
                    "particle_id": particle_id, "instrument_time_us": 10.0,
                    "mass_amu": mass, "charge_state": charge,
                    "position_x_mm": -67.8,
                    "position_y_mm": 0.0, "position_z_mm": -18.42918680341103,
                    "velocity_x_m_s": 1000.0, "velocity_y_m_s": 0.0,
                    "velocity_z_m_s": 0.0,
                    "event": "oatof_entry", "status": "transmitted",
                    "frame_id": "oatof_global",
                    "clock_epoch_id": "instrument_clock_epoch_v1",
                })
            self._write(path, rows)
            with self.assertRaisesRegex(ValueError, "mixed-species"):
                module.derive_schedule(
                    path, self.baseline, self.pre_pulse, self.resolved
                )
            selected = module.derive_schedule(
                path,
                self.baseline,
                self.pre_pulse,
                self.resolved,
                target_mass_amu=50.0,
                target_charge_state=2,
            )
            self.assertEqual(selected["target_species"]["charge_state"], 2)

    def test_rejects_stale_projected_entry_coordinate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "particles.csv"
            self._write(path, [{
                "particle_id": 1, "instrument_time_us": 10.0,
                "mass_amu": 100.0, "charge_state": 1,
                "position_x_mm": -62.8, "position_y_mm": 0.0,
                "position_z_mm": -18.42918680341103,
                "velocity_x_m_s": 1000.0, "velocity_y_m_s": 0.0,
                "velocity_z_m_s": 0.0,
                "event": "oatof_entry", "status": "transmitted",
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch_v1",
            }])
            with self.assertRaisesRegex(ValueError, "physical oa-TOF entry surface"):
                module.derive_schedule(
                    path, self.baseline, self.pre_pulse, self.resolved
                )

    def test_pulse_capture_uses_only_real_pre_pulse_entry_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "particles.csv"
            base = {
                "instrument_time_us": 10.0, "mass_amu": 100.0, "charge_state": 1,
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch_v1",
                "position_x_mm": -67.8, "position_y_mm": 0.0,
                "position_z_mm": -18.42918680341103,
                "velocity_x_m_s": 1000.0, "velocity_y_m_s": 0.0,
                "velocity_z_m_s": 0.0,
            }
            self._write(path, [
                dict(base, particle_id=1, event="oatof_entry", status="transmitted"),
                dict(base, particle_id=2, event="downstream_entry_wall", status="lost"),
            ])
            result = module.derive_schedule(
                path, self.baseline, self.pre_pulse, self.resolved
            )
            self.assertEqual(result["phase"], "pulse_capture")
            self.assertEqual(
                result["role"], "rf_to_oatof_pulse_capture_centroid_pulse_schedule"
            )
            self.assertEqual(result["population_counts"]["outer_face_geometric_acceptance"], 1)


if __name__ == "__main__":
    unittest.main()
