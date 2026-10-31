"""Pure project selectors: deliberately artificial small geometry fixtures."""
from copy import deepcopy
import json
import unittest
from projects.rf_multipole_ion_optics.runtime.finite_extraction_context import project_finite_extraction_science as project


def fixture():
    design = {"role": "multipole_resolved_design_do_not_edit", "resolved_sha256": "FROZEN_TEST_ID",
              "particle_source": {"charge_state": 1}, "axial_drive": {"topology": "none"},
              "drive": {"waveform": "cosine", "frequency_Hz": 123.0, "phase_rad": .7},
              "geometry_mm": {"rod_z_min": 2., "rod_z_max": 8., "enclosure": {"model": "bare"},
                              "numerical_domain": {"working_region_radius_mm": 3.},
                              "observations": {"release_plane_z_mm": 1., "handoff_plane_z_mm": 9.,
                                               "census_plane_z_mm": 10., "acceptance_radius_mm": 4.},
                              "enclosure_layout": {"ports": {
                                  "mechanical_entrance": {"center_mm": [0., 0., 2.], "cross_section": {"shape": "open_rod_envelope", "inscribed_radius_mm": 5.}},
                                  "mechanical_exit": {"center_mm": [0., 0., 8.], "cross_section": {"shape": "circle", "radius_mm": 6.}}}}}}
    numerics = {"role": "multipole_comsol_solver_numerics", "trajectory": {"rf_steps_per_period": 80, "maximum_global_time_us": 8.}}
    metadata = {"role": "multipole_canonical_particle_source_metadata", "parent_resolved_design_sha256": "FROZEN_TEST_ID",
                "particle_count": 2, "mass_amu": 100., "charge_state": 1, "source_plane_z_mm": None, "source_volume_snapshot": True}
    return design, numerics, metadata


class FiniteExtractionContextTests(unittest.TestCase):
    def test_open_circle_json_and_actual_mapping_are_separate(self):
        args = fixture()
        before = deepcopy(args)
        result = project(*args)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertEqual(result["acceptance"]["entrance_interface"]["cross_section"], {"shape": "open_rod_envelope", "inscribed_radius_mm": 5.})
        self.assertEqual(result["acceptance"]["exit_interface"]["cross_section"], {"shape": "circle", "radius_mm": 6.})
        self.assertEqual(result["census_radius_mm"], 4.)
        self.assertEqual(result["drive"], args[0]["drive"])
        self.assertEqual(args, before)
        for key in ("native_order", "source_ids", "source_birth_s", "solution_on", "dataset_on", "outputs"):
            self.assertNotIn(key, result)
        result["drive"]["phase_rad"] = 99.
        self.assertEqual(args, before)

    def test_rectangle_keeps_detector_and_aperture_distinct(self):
        d, n, m = fixture()
        g = d["geometry_mm"]
        g["enclosure"] = {"model": "rectangular_reference_enclosure_v1", "outer_half_width_mm": 20.,
                          "vacuum_z_min_mm": -1., "vacuum_z_max_mm": 15., "working_region_radius_mm": 3., "physical_detector_radius_mm": 12.}
        d["interfaces_mm"] = {"entrance": {"release_plane_z_mm": 1., "aperture_plate_downstream_face_z_mm": 2., "aperture_radius_mm": 6.},
                              "exit": {"handoff_plane_z_mm": 9., "census_plane_z_mm": 10., "aperture_crossing_plane_z_mm": 8., "aperture_radius_mm": 7.}}
        result = project(d, n, m)
        self.assertEqual(result["census_radius_mm"], 12.)
        self.assertEqual(result["acceptance"]["exit_interface"]["cross_section"]["radius_mm"], 7.)
        self.assertEqual(result["geometry"]["exit_port_plane_z"], 8.)

    def test_explicit_axial_case_and_changed_frozen_values(self):
        d, n, m = fixture()
        d["axial_drive"]["topology"] = "segmented_rod_axial_acceleration"
        d["drive"]["phase_rad"] = 1.3
        d["geometry_mm"]["observations"]["census_plane_z_mm"] = 11.
        result = project(d, n, m)
        self.assertEqual((result["primary_case_id"], result["control_case_id"]), ("axial_acceleration_rf_on", "zero_axial_drop_rf_on"))
        self.assertEqual(result["drive"]["phase_rad"], 1.3)
        self.assertEqual(result["geometry"]["census_plane_z"], 11.)

    def test_invalid_authority_and_missing_geometry_fail(self):
        changes = [("source binding", lambda d, n, m: m.update(parent_resolved_design_sha256="OTHER")),
                   ("role", lambda d, n, m: n.update(role="other")),
                   ("charge", lambda d, n, m: m.update(charge_state=-1)),
                   ("count", lambda d, n, m: m.update(particle_count=True)),
                   ("domain", lambda d, n, m: d["geometry_mm"].pop("numerical_domain")),
                   ("open radius", lambda d, n, m: d["geometry_mm"]["enclosure_layout"]["ports"]["mechanical_entrance"]["cross_section"].update(inscribed_radius_mm=float("inf"))),
                   ("drive", lambda d, n, m: d["drive"].update(phase_rad=float("nan"))),
                   ("topology", lambda d, n, m: d["axial_drive"].update(topology="unsupported"))]
        for name, change in changes:
            with self.subTest(name=name):
                args = fixture()
                change(*args)
                with self.assertRaises((ValueError, KeyError)):
                    project(*args)
