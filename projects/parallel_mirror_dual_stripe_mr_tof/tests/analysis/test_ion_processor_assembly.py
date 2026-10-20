"""Solver-free tests of real electrode preparation and scientific authority."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ion_processor_assembly as assembly

ROOT = Path(__file__).resolve().parents[4]
IP_CONFIG = ROOT / "projects/dual_pressure_rectilinear_ion_processor/config"


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {
            k: json.loads((IP_CONFIG / (k + ".json")).read_text(encoding="utf-8-sig"))
            for k in (
                "baseline",
                "numerics",
                "source",
                "acceptance",
                "diagnostics",
                "field_diagnostics",
                "native_operating_point",
                "coordinate_transform",
            )
        }
        self.source["baseline"]["electric"]["lift_v"] = self.source["native_operating_point"]["lift_v"]
        self.trajectory = {
            "simion": {"detector_pa_span_mm": [64, 64, 8], "component_mesh_mm_per_gu": {"detector": [1, 1, 1]}},
            "coordinate_system": {"frame_id": "mr"},
            "prisms": {"ground_shields": [{"extension_to_accelerator_exit": {"clearance_mm": 1}}]},
        }

        def shield(id, station, y0, y1, z0, z1):
            polygon = [[y0, z0], [y1, z0], [y1, z1], [y0, z1]]
            return {
                "id": id,
                "station": station,
                "x": [-12, 12],
                "outer_polygon_yz_mm": polygon,
                "body_sections": [{"x": [-12, 12], "polygon_yz_mm": copy.deepcopy(polygon)}],
                "prism_clearance_polygon_yz_mm": [[-70, -90], [-40, -65], [-70, -40]],
                "rectangular_slots_mm": [[-2, -28, -40, 2, -4, 40]] if id == 20 else [[-2, -75, -100, 2, -35, -1.5]],
            }

        self.geometry = {
            "frame_id": "mr",
            "accelerator_component_layout": {"old_oa": True},
            "prism_ground_shields": [
                shield(18, "accelerator_exit", -77, -33, -100, -1.5),
                shield(20, "central_ground_left", -32, -3, -97, 97),
            ],
            "detector": {"id": 25, "box": [-1, 5, 101, 1, 7, 102]},
            "mirror_electrodes": [{"id": 2, "keep": "exact"}],
        }
        self.plan = {"box_mm": [0, -242, -425, 162.5, 558, 425], "pitch_mm": [0.5, 1, 1], "convergence_v": 1e-5}
        authority = {
            "boundary_contract": {"box_mm": self.plan["box_mm"]},
            "analyzer_electrode_voltages_v": [0] * 20,
            "component_voltages_v": [{"component_namespace": "detector", "voltage_v": 0}],
        }
        refs = {}
        for name, value in (
            ("geometry_authority", self.geometry),
            ("voltage_authority", authority),
            ("numerical_plan", self.plan),
        ):
            path = self.write(name + ".json", value)
            refs[name] = file_record(path)
        native_point = copy.deepcopy(self.source["native_operating_point"])
        native_point["lift_v"] = 4480.043790844389
        self.source["native_timing"] = {"pulse_start_us": 7500.135135135}
        refs.update(
            refinement_windows=[],
            analyzer_electrode_voltages_v=[0] * 20,
            provider_voltage_projection={
                "source_native_drive": file_record(
                    ROOT / "projects/dual_pressure_rectilinear_ion_processor/simion/native_drive.lua"
                ),
                "basis": "post_extraction_pulse_held_rf_zero",
                "evaluation_time_us": 7501,
                "evaluated_native_operating_point": native_point,
                "evaluated_baseline_lift_v": 4480.043790844389,
                "values_v15": [
                    0,
                    0,
                    5,
                    5,
                    3580.043790844389,
                    5380.043790844389,
                    3580.043790844389,
                    5380.043790844389,
                    25,
                    4485.043790844389,
                    4479.043790844389,
                    0,
                    4530.043790844389,
                    3580.043790844389,
                    5,
                ],
            },
        )
        self.request = {
            "policies": {"energy_adjustment": "provider_voltage_and_geometry"},
            "target": {"axial_energy_per_charge_v": 4372.010347796, "frame_id": "mr"},
            "current_measured_baseline": {"directional_energy": {"z": {"mean": 3891.9665569516114}}},
            "requirements": {"energy_definition": "exit_axial_kinetic_energy_per_charge"},
            "rigid_transform": {
                "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "from_frame_id": self.source["coordinate_transform"]["to_frame_id"],
                "to_frame_id": "mr",
                "translation_mm": [0, -225, 0],
            },
            "field_assembly_reference": refs,
        }

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def prepare(self):
        paths = [
            self.write(name + ".json", value)
            for name, value in (("source", self.source), ("trajectory", self.trajectory), ("request", self.request))
        ]
        with patch.object(assembly, "_analyzer_geometry_lines", return_value=["e(2) { box3d(1,2,3,4,5,6) }"]):
            return assembly.prepare_ion_processor_assembly(*paths, self.root / "output")

    def test_seed_target_geometry_and_oa_removed(self):
        report = self.prepare()
        self.assertAlmostEqual(report["energy_seed"]["new_lift_v"], 4480.043790844389)
        self.assertEqual(report["geometry_changes"]["lp_length_after_mm"], 61.5)
        self.assertEqual(report["geometry_changes"]["ip_exit_lens_max_y_mm"], -33)
        self.assertTrue(report["geometry_checks"]["before_shield_csg_interior_witnesses"])
        self.assertEqual(report["geometry_checks"]["after_shield_csg_interior_witnesses"], [])
        geometry = json.loads(Path(report["assembly_geometry_path"]).read_text())
        self.assertNotIn("accelerator_component_layout", geometry)
        self.assertEqual(geometry["mirror_electrodes"], self.geometry["mirror_electrodes"])
        self.assertFalse(report["field_qualified"])
        self.assertFalse(report["historical_exit_state_matches_new_seed"])
        baseline = json.loads(Path(report["source_config_paths"]["baseline"]).read_text())
        point = json.loads(Path(report["source_config_paths"]["native_operating_point"]).read_text())
        self.assertEqual(baseline["electric"]["lift_v"], point["lift_v"])
        self.assertEqual(baseline["gas"], self.source["baseline"]["gas"])
        self.assertEqual(json.loads(Path(report["source_config_paths"]["source"]).read_text()), self.source["source"])
        text = Path(report["parent_gem_path"]).read_text()
        self.assertIn("cylinder3d(", text)
        self.assertIn("namespace=ion_processor id=12", text)
        self.assertIn("notin_inside", text)

    def test_preserve_measured_workpoint_keeps_voltage_and_reports_original_target(self):
        lift = 4480.043790844389
        self.source["native_operating_point"]["lift_v"] = lift
        self.source["baseline"]["electric"]["lift_v"] = lift
        self.source["baseline"]["geometry"]["lp_length_mm"] = 61.5
        self.request["policies"]["energy_adjustment"] = "preserve_measured_workpoint"
        self.request["current_measured_baseline"]["directional_energy"]["z"]["mean"] = 4359.0
        report = self.prepare()
        seed = report["energy_seed"]
        self.assertEqual(seed["new_lift_v"], lift)
        self.assertEqual(seed["target_ez_per_q_v"], 4372.010347796)
        self.assertAlmostEqual(seed["measured_minus_target_ez_per_q_v"], 4359.0 - 4372.010347796)
        self.assertEqual(report["geometry_changes"]["lp_length_after_mm"], 61.5)
        for name, field in (("baseline", "electric"), ("native_operating_point", None)):
            prepared = json.loads(Path(report["source_config_paths"][name]).read_text())
            self.assertEqual((prepared[field] if field else prepared)["lift_v"], lift)

    def test_lift_seed_rejects_unknown_energy_adjustment_policy(self):
        self.request["policies"]["energy_adjustment"] = "unknown"
        with self.assertRaisesRegex(ValueError, "energy adjustment policy"):
            assembly.derive_lift_seed(self.source, self.request)

    def test_historical_source_authors_current_native_seed_without_retired_analytic_fields(self):
        expected = copy.deepcopy(self.source["baseline"])
        expected["geometry"]["lp_length_mm"] = 61.5
        expected["electric"]["lift_v"] = 4480.043790844389
        for section, names in {
            "geometry": ("interface_halfwidth_mm", "guide_blend_halfwidth_mm"),
            "electric": ("hp_axial_curvature_v_per_mm2", "lp_axial_curvature_v_per_mm2",
                         "lp_capture_offset_v", "hp_transfer_offset_v", "extraction_gradient_v_per_mm",
                         "hp_transfer_gradient_v_per_mm", "lp_transfer_axial_curvature_v_per_mm2"),
        }.items():
            self.source["baseline"][section].update(dict.fromkeys(names, 123.0))
        original = copy.deepcopy(self.source)
        report = self.prepare()
        config = {name: json.loads(Path(path).read_text())
                  for name, path in report["source_config_paths"].items()}
        self.assertEqual(config["baseline"], expected)
        self.assertEqual(config["native_operating_point"]["hp_transfer_offset_v"],
                         original["native_operating_point"]["hp_transfer_offset_v"])
        self.assertEqual(json.loads((self.root / "source.json").read_text()), original)
        from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import (
            derive_native_timing, validate_configs,
        )
        config["source_profile"] = "functional"
        config["native_timing"] = derive_native_timing(config["baseline"])
        validate_configs(config)

    def test_box_and_circular_hole_pose(self):
        r = [[0, 0, -1], [1, 0, 0], [0, -1, 0]]
        t = [0, -225, 9.8]
        hole = {
            "shape": "cylinder_x",
            "x_min_mm": 29.4,
            "x_max_mm": 30.1,
            "center_y_mm": 0,
            "center_z_mm": 0,
            "radius_mm": 1,
        }
        actual = assembly.transform_shape(hole, r, t)
        self.assertEqual(actual["endpoints_mm"], [[0, -195.6, 9.8], [0, -194.9, 9.8]])
        self.assertEqual(actual["radius_mm"], 1)
        box = assembly.transform_shape({"shape": "box", "min_mm": [166, 1.9, -0.4], "max_mm": [174, 3.6, 0.4]}, r, t)
        self.assertEqual(box["min_mm"][:2], [-0.4, -59])
        self.assertAlmostEqual(box["min_mm"][2], 6.2)

    def test_invalid_target_rejected_before_creation(self):
        self.request["target"]["axial_energy_per_charge_v"] = -1
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / "output").exists())

    def test_tampered_reference_rejected(self):
        Path(self.request["field_assembly_reference"]["geometry_authority"]["path"]).write_text("{}")
        with self.assertRaises(AssertionError):
            self.prepare()

    def test_lift_binding_mismatch_rejected(self):
        self.source["baseline"]["electric"]["lift_v"] += 1
        with self.assertRaises(ValueError):
            self.prepare()

    def test_no_overwrite(self):
        self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_invalid_rotation_rejected(self):
        with self.assertRaises(ValueError):
            assembly.transform_shape(
                {"shape": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
                [[0.7, 0, 0.7], [0, 1, 0], [-0.7, 0, 0.7]],
                [0, 0, 0],
            )

    def materializable_request(self):
        ref = Path(self.request["field_assembly_reference"]["numerical_plan"]["path"])
        data = json.loads(ref.read_text())
        data.update(
            resource_budget={"cpu_cores": 8, "memory_bytes": 8589934592, "io_slots": 1},
            resource_limits={"automatic_retry_count": 0},
        )
        ref.write_text(json.dumps(data), encoding="utf-8")
        self.request["field_assembly_reference"]["numerical_plan"] = file_record(ref)
        self.trajectory["simion"]["numerical_profiles"] = {
            "native_static_field": {"refine": {"convergence_v": 1e-5}},
            "grid_generation": {"spacing_quantum_mm": 0.01},
        }
        self.prepare()
        (self.root / "results").mkdir()
        (self.root / "results/accelerator_interface_preparation.json").write_text(json.dumps({"inputs": {}}))
        manifest = {
            "status": "success",
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "inputs": {},
            "outputs": [file_record(p) for p in self.root.rglob("*") if p.is_file()],
        }
        manifest_path = self.write("run_manifest.json", manifest)
        return {
            "schema_version": 1,
            "role": "mrtof_native_static_field_provider_request",
            "run_id": "fresh",
            "replacement_assembly_path": str(self.root / "output/assembly_preparation.json"),
            "replacement_assembly_manifest": str(manifest_path),
            "numerical_contract_path": str(self.root / "trajectory.json"),
            "ion_processor_local_grid": {
                "box_mm": [0, -227, -0.5, 4, -31.5, 14],
                "pitch_mm": [0.05, 0.1, 0.05],
                "active_box_mm": [[-3.5, 3.5], [-226.5, -32], [-0.25, 13.75]],
            },
            "surface_allowance_bytes_per_level": 1024,
        }

    def test_materializable_new_fields_and_fine_collision(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import native_static_field_provider as provider
        import shutil

        request = self.materializable_request()
        with patch.object(assembly, "_analyzer_geometry_lines", return_value=["e(2) { box3d(1,2,3,4,5,6) }"]):
            plan = provider.compile_request(request)
        self.assertEqual(plan["window_labels"], ["ion_processor_local"])
        self.assertNotIn("reuse_source", plan["levels"]["parent"])
        fine = plan["levels"]["ion_processor_local"]
        self.assertEqual(fine["pitch_mm"], [0.05, 0.1, 0.05])
        self.assertEqual(plan["ip_collision_build"]["origin_mm"], [0, -227, -0.5])
        self.assertEqual(plan["ip_collision_build"]["gem"].count("namespace=ion_processor"), 15)
        self.assertFalse(plan["fly_authorized"])
        self.assertEqual(plan["detector_build"]["pa_bytes"], 65 * 65 * 9 * 8 + 32)
        self.assertEqual(plan["ip_collision_build"]["pa_bytes"], 81 * 1956 * 291 * 8 + 56)
        self.assertGreater(
            plan["committed_new_bytes"],
            sum(level["capacity_basis"]["pa_node_bytes"] for level in plan["levels"].values()),
        )
        run = self.root / "new_run"
        (run / "inputs").mkdir(parents=True)
        for key, value in plan["inputs"].items():
            shutil.copyfile(value, run / "inputs" / (key + Path(value).suffix))
        provider.prepare_run(plan, run)
        self.assertTrue((run / "simion/ip_collision/ip_collision.gem").is_file())
        self.assertTrue((run / "simion/detector/detector.gem").is_file())
        binding = provider.binding_spec(plan, run)
        self.assertEqual(
            [i["role"] for i in binding["instances"]],
            ["global_fallback", "native_corridor", "ion_processor_collision", "detector"],
        )
        self.assertEqual(binding["instances"][2]["origin_mm"], [0, -227, -0.5])
        self.assertEqual(binding["accelerator_provider"], "dual_pressure_rectilinear_ion_processor")

    def test_ordinary_pa_header_forecast_distinguishes_unit_pitch(self):
        self.assertEqual(assembly.ordinary_pa_file_bytes([65, 65, 9], [1, 1, 1]), 304232)
        self.assertEqual(assembly.ordinary_pa_file_bytes([65, 65, 9], [1, 1, 0.5]), 304256)

    def test_materializable_rejects_missing_thin_auxiliary_resolution(self):
        request = self.materializable_request()
        request["ion_processor_local_grid"]["pitch_mm"][0] = 0.2
        with self.assertRaisesRegex(ValueError, "under-resolves"):
            assembly.compile_materializable_fields(request)

    def test_materializable_rejects_reuse_and_unsealed_receipt(self):
        request = self.materializable_request()
        request["reuse_source_levels"] = ["parent"]
        with self.assertRaises(ValueError):
            assembly.compile_materializable_fields(request)


if __name__ == "__main__":
    unittest.main()
