from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from projects.rf_quadrupole_collision_cooling.analysis import audit_s3_pulse_chain as module


class S3PulseChainAuditTests(unittest.TestCase):
    def test_minimal_chain_preserves_clock_and_exit_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = pd.DataFrame([{
                "particle_id": 1, "frame_id": "oatof_global", "clock_epoch_id": "epoch",
                "instrument_time_us": 10.0, "lineage_age_us": 4.0, "particle_age_us": 4.0,
                "mass_amu": 100.0, "charge_state": 1,
            }])
            velocity = 1000.0
            energy = 0.5*100*module.ATOMIC_MASS_KG*velocity**2/module.ELEMENTARY_CHARGE_C
            terminal = pd.DataFrame([{
                "particle_id": 1, "event": "local_accelerator_exit", "frame_id": "oatof_global",
                "clock_epoch_id": "epoch", "instrument_time_us": 12.0, "lineage_age_us": 6.0,
                "particle_age_us": 6.0, "last_component_elapsed_time_us": 2.0,
                "mass_amu": 100.0, "charge_state": 1, "vx_m_s": velocity,
                "vy_m_s": 0.0, "vz_m_s": 0.0, "kinetic_energy_eV": energy,
                "first_forward_oatof_entry": True,
            }])
            capture = pd.DataFrame([{
                "particle_id": 1, "instrument_time_us": 11.0,
                "inside_oatof_ideal_reference_volume": True, "active_at_pulse": True,
            }])
            local_exit = pd.DataFrame([{
                "particle_id": 1, "frame_id": "oatof_global", "clock_epoch_id": "epoch",
                "instrument_time_us": 12.0, "lineage_age_us": 6.0, "particle_age_us": 6.0,
                "mass_amu": 100.0, "charge_state": 1, "position_x_mm": 0.0,
                "position_y_mm": 0.0, "position_z_mm": 0.0, "velocity_x_m_s": velocity,
                "velocity_y_m_s": 0.0, "velocity_z_m_s": 0.0,
                "kinetic_energy_eV": energy, "source_rf_phase_rad": 0.0,
            }])
            for name, frame in (("source", source), ("terminal", terminal),
                                ("capture", capture), ("exit", local_exit)):
                frame.to_csv(root/f"{name}.csv", index=False)
            (root/"schedule.json").write_text(json.dumps({
                "derived_pulse_time_us": 11.0, "pulse_width_us": 1.0}), encoding="utf-8")
            (root/"contract.json").write_text(json.dumps({
                "source": {"source_particles": 1},
                "runtime": {"minimum_active_at_pulse": 1, "minimum_local_accelerator_exit": 1},
            }), encoding="utf-8")
            result = module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                                  root/"exit.csv", root/"schedule.json", root/"contract.json")
            self.assertEqual(result["local_accelerator_exit"], 1)
            self.assertEqual(result["maximum_clock_residual_us"], 0.0)


if __name__ == "__main__":
    unittest.main()
