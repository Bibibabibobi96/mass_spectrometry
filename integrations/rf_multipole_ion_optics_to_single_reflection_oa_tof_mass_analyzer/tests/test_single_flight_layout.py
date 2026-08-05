from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightLayoutTests(unittest.TestCase):
    def test_10ev_profile_derives_linked_layout_from_one_energy_parameter(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        profile = select_profile(registry, "symmetric_10ev_injection_diagnostic")
        resolved, derived_port, values = compile_geometry_and_port(geometry, port, profile)
        expected_axis = -48.8 * math.sqrt(2.0)
        self.assertAlmostEqual(values["accelerator_axis_x_mm"], expected_axis)
        self.assertAlmostEqual(values["detector_x_mm"], -expected_axis)
        self.assertAlmostEqual(values["entry_port_x_mm"], expected_axis - 19.0)
        self.assertEqual(resolved["particle_source"]["center_x_mm"], expected_axis)
        self.assertEqual(derived_port["mating_surface"]["center_mm"][0], expected_axis - 19.0)


if __name__ == "__main__":
    unittest.main()
