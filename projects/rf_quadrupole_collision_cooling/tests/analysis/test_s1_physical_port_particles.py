from __future__ import annotations

import unittest
import pandas as pd


from projects.rf_quadrupole_collision_cooling.analysis import analyze_s1_physical_port_particles as module


class S1PhysicalPortParticleTests(unittest.TestCase):
    def test_function_gate_counts_geometric_and_dynamic_losses(self) -> None:
        rows = []
        for particle_id in range(1, 101):
            if particle_id <= 12:
                event, status, pulse = "geometric_reject", "lost", False
            elif particle_id <= 50:
                event, status, pulse = "local_joint_exit", "transmitted", True
            else:
                event, status, pulse = "terminal", "lost", True
            rows.append({
                "particle_id": particle_id, "event": event, "status": status,
                "pulse_time_reached": pulse,
            })
        result = module.analyze(pd.DataFrame(rows))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["geometric_port_accepted"], 88)
        self.assertEqual(result["local_joint_exit"], 38)
        self.assertFalse(result["physical_link_claim_allowed"])

    def test_incomplete_census_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 100"):
            module.analyze(pd.DataFrame([{
                "particle_id": 1, "event": "local_joint_exit", "pulse_time_reached": True,
            }]))

    def test_matlab_numeric_boolean_column_is_accepted(self) -> None:
        rows = []
        for particle_id in range(1, 101):
            rows.append({
                "particle_id": particle_id,
                "event": "local_joint_exit" if particle_id <= 28 else "terminal",
                "status": "transmitted" if particle_id <= 28 else "lost",
                "pulse_time_reached": 1,
            })
        result = module.analyze(pd.DataFrame(rows))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["particles_reaching_pulse_time"], 100)


if __name__ == "__main__":
    unittest.main()
