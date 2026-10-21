"""Pure provider-contract tests; no PA, native solver or artifact dependency."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from common.contracts.rigid_transform import PhaseSpaceState, RigidTransform
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import export_guide_contract
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection


class GuideInterfaceTests(unittest.TestCase):
    def setUp(self):
        config = Path(__file__).parents[2] / "config"
        read = lambda name: json.loads((config / name).read_text(encoding="utf-8-sig"))
        baseline = read("baseline.json")
        self.model = {
            "baseline": baseline, "source": read("source.json"),
            "native_projection": native_projection(baseline, read("numerics.json")),
            "native_operating_point": read("native_operating_point.json"),
        }
        self.identities = {name: {"path": f"inputs/{name}", "bytes": 1, "sha256": "A"*64}
                           for name in ("resolved_model", "source_spec", "release_csv")}

    def test_exports_exact_continuous_native_rods_and_no_added_metal(self):
        before = copy.deepcopy(self.model)
        result = export_guide_contract(self.model, self.identities)
        self.assertEqual(self.model, before)
        self.assertEqual(result["role"], "ion_processor_bare_guide_interface")
        rods = result["rod_array"]["rods"]
        self.assertEqual([r["physical_electrode_id"] for r in rods], list(range(1, 9)))
        self.assertEqual([r["source_electrode_id"] for r in rods], [1, 2]*4)
        self.assertEqual({(r["z_min_mm"], r["z_max_mm"], r["radius_mm"]) for r in rods}, {(0.0, 29.0, .6)})
        self.assertTrue(all(value is False for value in result["mechanical_components"].values()))
        self.assertEqual(result["vacuum"]["pressure_pa"], 0)
        self.assertEqual(result["guide_exit_surface"]["center_mm"], [0, 0, 29])
        self.assertEqual(result["source_envelope_bounds_mm"], {
            "min_mm": [-1, -1, -1.5], "max_mm": [1, 1, 3.5],
        })
        self.assertEqual(result["source_particle_count"], self.model["source"]["particle_count"])
        self.assertNotIn("segmented_rod_array", result)

    def test_transform_is_proper_and_preserves_clock_and_velocity(self):
        result = export_guide_contract(self.model, self.identities)
        transform = RigidTransform.from_contract(result["coordinate_transform"])
        mapped = transform.transform_state(PhaseSpaceState(transform.from_frame_id, (1, 2, 3), (4, 5, 6), 7))
        self.assertEqual(mapped.position_mm, (2, 3, 1))
        self.assertEqual(mapped.velocity_m_s, (5, 6, 4))
        self.assertEqual(mapped.instrument_time_us, 7)

    def test_drive_uses_original_guide_amplitude_phase_and_offset(self):
        self.model["baseline"]["electric"]["guide_rf_peak_to_peak_v"] = 800
        self.model["baseline"]["clock"].update(rf_phase_rad=.25, epoch_us=13)
        self.model["native_operating_point"]["guide_offset_v"] = -2
        result = export_guide_contract(self.model, self.identities)
        self.assertEqual(result["drive"]["rf_amplitude_v"], 400)
        self.assertEqual(result["drive"]["phase_rad"], .25)
        self.assertEqual(result["drive"]["common_mode_v"], -2)
        self.assertEqual(result["drive"]["frequency_hz"], 3700000)
        self.assertEqual(result["clock"]["epoch_us"], 13)

    def test_malformed_or_changed_csg_is_rejected(self):
        for mutation in (
            lambda m: m["native_projection"].update(schema_version=2),
            lambda m: m["native_projection"]["electrodes"][0]["solids"][0].update(radius_mm=.7),
            lambda m: m["native_projection"]["electrodes"][1]["solids"][0].update(x_max_mm=28),
            lambda m: m["native_projection"]["electrodes"][0]["solids"][0].update(center_y_mm=2.7),
            lambda m: m["native_projection"]["electrodes"][0]["cutouts"].append({"shape": "box"}),
            lambda m: m["baseline"]["geometry"].update(guide_order=3),
        ):
            model = copy.deepcopy(self.model)
            mutation(model)
            with self.subTest(model=model["native_projection"]["schema_version"]), self.assertRaises(ValueError):
                export_guide_contract(model, self.identities)

    def test_unknown_gas_schema_frame_and_source_axis_fail_closed(self):
        for mutation in (
            lambda m: m["baseline"]["gas"].update(guide_pressure_pa=.1),
            lambda m: m["baseline"].update(schema_version=2),
            lambda m: m["native_projection"].update(frame_id="other"),
            lambda m: m["source"]["geometry"].update(axis="z"),
        ):
            model = copy.deepcopy(self.model)
            mutation(model)
            with self.assertRaises(ValueError):
                export_guide_contract(model, self.identities)

    def test_identity_validation_is_explicit_structural_and_detached(self):
        result = export_guide_contract(self.model, self.identities)
        self.identities["source_spec"]["path"] = "changed"
        self.assertNotEqual(result["inputs"], self.identities)
        self.assertIn("caller_must_verify", result["input_identity_validation"])
        for change in ({"extra": {}}, {"release_csv": {"path": "x", "bytes": 1, "sha256": "BAD"}}):
            identities = {**self.identities, **change}
            with self.assertRaises(ValueError):
                export_guide_contract(self.model, identities)


if __name__ == "__main__":
    unittest.main()
