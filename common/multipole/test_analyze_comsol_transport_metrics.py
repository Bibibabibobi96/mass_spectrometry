from __future__ import annotations

import unittest

from common.multipole.analyze_comsol_transport_metrics import derive


class AnalyzeComsolTransportMetricsTests(unittest.TestCase):
    def test_derives_case_metrics_from_canonical_state_and_event_rows(self) -> None:
        state = [
            {"particle_id": "1", "event": "source", "status": "alive", "radial_position_mm": "0", "kinetic_energy_eV": "2", "max_rod_radius_mm": "1"},
            {"particle_id": "1", "event": "terminal", "status": "transmitted", "radial_position_mm": "3", "kinetic_energy_eV": "5", "max_rod_radius_mm": "1"},
        ]
        events = [{"case_id": case, "particle_id": "1", "entrance_aperture_radius_mm": "1", "exit_aperture_radius_mm": "1"} for case in ("finite_3d_rf_on", "zero_rf_control")]
        resolved = {"identity": {"project_id": "fixture"}, "axial_drive": {"topology": "none"}, "drive": {}, "geometry_mm": {"rod_radius_ratio": 1, "rod_radius": 2, "rod_center_radius": 3}, "interfaces_mm": {"entrance": {"aperture_radius_mm": 1, "release_plane_z_mm": 0}, "exit": {"aperture_radius_mm": 1, "census_plane_z_mm": 1}}}
        numerics = {"mesh": {"global_auto_level": 3, "working_region_maximum_element_size_mm": 0.5}}
        result = derive(events, state, state, resolved, numerics)
        self.assertEqual(result["metrics_authority"], "python_canonical_particle_state_and_events")
        self.assertEqual(result["cases"]["finite_3d_rf_on"]["transmission_fraction"], 1.0)
        self.assertEqual(result["cases"]["finite_3d_rf_on"]["exit_rms_radius_mm"], 3.0)


if __name__ == "__main__":
    unittest.main()
