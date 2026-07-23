from __future__ import annotations

import math
import unittest

from common.contracts.particle_physics import kinetic_energy_ev
from projects.rf_quadrupole_collision_cooling.analysis import audit_s1_state_chain as module


class S1StateChainAuditTests(unittest.TestCase):
    def test_instance3_direction_round_trip(self) -> None:
        velocity = [3091.05090412163, 41.5362499862517, 62010.1364580715]
        mass = 100.0
        energy = kinetic_energy_ev(mass, *velocity)
        local_x, local_y, local_z = velocity[0], -velocity[2], velocity[1]
        azimuth = math.degrees(math.atan2(local_y, local_x))
        elevation = math.degrees(math.atan2(local_z, math.hypot(local_x, local_y)))
        decoded = module.decode_simion_instance3_velocity(mass, energy, azimuth, elevation)
        for expected, actual in zip(velocity, decoded):
            self.assertAlmostEqual(expected, actual, places=9)


if __name__ == "__main__":
    unittest.main()
