"""Small, solver-free production provider contract regressions."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import native_static_field_provider as p
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import derive_candidate_authority
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import build_static_c0_gem
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import _record, load_binding
from common.contracts.verify_run_manifest import verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import PaHeader


class NativeStaticProviderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.contract_path = self.root / "numerical_contract.json"
        self.contract = {"simion": {"numerical_profiles": {"native_static_field": {
            "target_layout": {"parent": {"pitch_mm": [1, 1, 1]}, "windows": [{"pitch_mm": [1, 1, 1]}]},
            "refine": {"convergence_v": 1e-5}}, "grid_generation": {"spacing_quantum_mm": .01}}}}
        p.write_json(self.contract_path, self.contract)
        self.authority = {"analyzer_electrode_voltages_v": [0.0] * 20,
                          "component_voltages_v": [{"component_namespace": "accelerator", "component_electrode_id": 1, "voltage_v": 4000.0},
                                                   {"component_namespace": "detector", "component_electrode_id": 25, "voltage_v": 0.0}]}
        self.geometry = {"frozen": "geometry"}
        self.source = {"mode": "native_static_pa", "authority": self.authority,
                       "geometry": self.geometry, "instances": [], "refinement_windows": []}
        for label in ("parent", "window"):
            directory = self.root / label
            directory.mkdir()
            numerical = directory / "plan.json"
            p.write_json(numerical, {"box_mm": [0, -2, -2, 2, 2, 2], "pitch_mm": [1, 1, 1],
                                    "dimensions": [3, 5, 5], "mirror_axes": ["x"], "surface": "fractional",
                                    "resource_budget": {"estimated_memory_bytes": 123},
                                    "resource_limits": {"automatic_retry_count": 0},
                                    "committed_new_bytes": 6 * 1024**3})
            surface = directory / "static.pa-surf"
            surface.write_bytes(b"fractional")
            level = {"manifest": str(directory / "run_manifest.json"),
                     "native_solver_numerics": {"refine_stopping": "contract_convergence", "convergence_v": 1e-5},
                     "sources": {"numerical_plan": str(numerical), "surface": str(surface),
                                 "scalar_pa": str(directory / "static.pa"),
                                 "geometry_authority": str(directory / "geometry.json"),
                                 "voltage_authority": str(directory / "voltage.json")}}
            if label == "parent":
                self.source.update(level)
            else:
                level.update(name="covered", active_box_mm=[[-1, 1], [-1, 1], [-1, 1]])
                self.source["refinement_windows"].append(level)
        self.source["instances"] = [
            {"role": role, "manifest": str(self.root / (role + ".json")),
             "pa_path": str(self.root / (role + ".pa")), "origin_mm": [0, 0, 0]}
            for role in ("global_fallback", "native_corridor", "accelerator", "detector")]
        wp = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        value = p.read(wp)
        value.update(parent_manifest=self.source["manifest"], parent_pa=self.source["sources"]["scalar_pa"])
        p.write_json(wp, value)
        self.request = {"schema_version": 1, "role": p.ROLE, "run_id": "test_run",
                        "numerical_contract_path": str(self.contract_path),
                        "source_binding_path": str(self.root / "binding.json"),
                        "source_field_manifest": self.source["manifest"],
                        "candidate_voltages_v": {"p1": 1, "p2": -2, "s1": -27, "s2": 55}}
        for name, replacement in (("load_binding", lambda _: self.source),
                                  ("_record", lambda *_: {}),
                                  ("verify_record", lambda *_a, **_k: None),
                                  ("derive_candidate_authority", lambda *_: (self.authority, {})),
                                  ("build_static_c0_gem", lambda *_a, **_k: ("pa_define{}\n", {}))):
            mock = patch.object(p, name, side_effect=replacement)
            mock.start()
            self.addCleanup(mock.stop)

    def new_geometry(self):
        """Small frozen assembly; no PA, Refine, vendor call or fixture mutation."""
        for key in ("coordinate_system", "accelerator", "detector"):
            self.contract[key] = {"identity": key}
        p.write_json(self.contract_path, self.contract)
        self.geometry.update(frame_id="same_frame", detector={"id": 25, "box": [0, -1, -1, 1, 1, 1]},
                             mirror_electrodes=[{"box": [-1, -1, -1, 1, 1, 1]}],
                             mirror_ground_shields=[], mirror_e_closures=[])
        self.authority["assembly"] = {"detector": self.geometry["detector"]}
        collision = Path(self.source["instances"][1]["pa_path"])
        header = PaHeader(-2, 1, 100000, 3, 5, 5, 1, 1, 1, 1)
        collision.write_bytes(header.pack() + b"\0" * (header.node_count * 8))
        shapes = patch.object(p, "_analyzer_geometry_lines", return_value=["e(1) { box(0,-1,-1,1,1,1) }"])
        shapes.start()
        self.addCleanup(shapes.stop)
        updated = copy.deepcopy(self.geometry)
        updated["mirror_electrodes"][0].update(polygon_yz_mm=[[-1, -1], [1, -.9], [1, 1], [-1, .9]])
        updated["mirror_convergence_transform"] = {"angle_deg": .1}
        path = self.root / "geometry_contract.json"
        p.write_json(path, self.contract)
        self.request["geometry_contract_path"] = str(path)
        contract_mock = patch.object(p, "load_contract", side_effect=p.read)
        resolve_mock = patch.object(p, "resolve_geometry", return_value=updated)
        contract_mock.start()
        resolver = resolve_mock.start()
        self.addCleanup(contract_mock.stop)
        self.addCleanup(resolve_mock.stop)
        return updated, resolver

    def mirror_reuse_request(self):
        central = self.source["refinement_windows"][0]
        mirrors = []
        for index in (0, 1):
            mirror = copy.deepcopy(central)
            directory = self.root / f"mirror_{index}"
            directory.mkdir()
            plan_path = directory / "plan.json"
            numerical = p.read(Path(central["sources"]["numerical_plan"]))
            numerical.update(parent_manifest=central["manifest"], parent_pa=central["sources"]["scalar_pa"])
            p.write_json(plan_path, numerical)
            mirror.update(manifest=str(directory / "run_manifest.json"), name=f"mirror_{index}")
            mirror["sources"]["numerical_plan"] = str(plan_path)
            mirror["sources"]["scalar_pa"] = str(directory / "static.pa")
            mirrors.append(mirror)
        self.source["refinement_windows"] = [*mirrors, central]
        for level in [self.source, *self.source["refinement_windows"]]:
            numerical = p.read(Path(level["sources"]["numerical_plan"]))
            level["grid"] = dict(origin_mm=numerical["box_mm"][:3], pitch_mm=numerical["pitch_mm"],
                                 dimensions=numerical["dimensions"], symmetry="x")
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"] = [
            {"pitch_mm": [1, 1, .5]}, {"pitch_mm": [1, 1, .5]}, {"pitch_mm": [1, 1, 1]}]
        p.write_json(self.contract_path, self.contract)
        self.request["reuse_source_levels"] = ["parent", "window_2"]
        return self.request

    def test_mirror_refinement_reuses_sealed_parent_and_central_without_pa_copy(self):
        request = self.mirror_reuse_request()
        plan = p.compile_request(request)
        self.assertEqual(plan["levels"]["parent"]["committed_new_bytes"], 0)
        self.assertEqual(plan["levels"]["window_2"]["committed_new_bytes"], 0)
        self.assertEqual(plan["levels"]["window_0"]["pitch_mm"], [1, 1, .5])
        run = self.root / "mirror_run"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        self.assertFalse((run / "simion/parent").exists())
        self.assertFalse((run / "simion/window_2").exists())
        original_central = self.source["refinement_windows"][2]
        mirror_plan = p.read(run / "inputs/window_0_plan.json")
        self.assertEqual(mirror_plan["parent_pa"], original_central["sources"]["scalar_pa"])
        binding = p.binding_spec(plan, run)
        self.assertEqual(binding["parent"]["pa_path"], self.source["sources"]["scalar_pa"])
        self.assertEqual(binding["refinement_windows"][2]["pa_path"], original_central["sources"]["scalar_pa"])
        self.assertEqual(binding["refinement_windows"][0]["parent_manifest"], original_central["manifest"])
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])

    def test_mirror_reuse_rejects_voltage_stopping_fixed_grid_or_new_geometry(self):
        request = self.mirror_reuse_request()
        with patch.object(p, "derive_candidate_authority", return_value=({**self.authority, "changed": True}, {})):
            with self.assertRaisesRegex(ValueError, "complete voltage"):
                p.compile_request(request)
        for label, change in (("parent", [1, 1, .5]), ("window_2", [1, 1, .5])):
            contract = copy.deepcopy(self.contract)
            layout = contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
            (layout["parent"] if label == "parent" else layout["windows"][2])["pitch_mm"] = change
            p.write_json(self.contract_path, contract)
            with self.assertRaisesRegex(ValueError, "reused level target"):
                p.compile_request(request)
        p.write_json(self.contract_path, self.contract)
        self.source["native_solver_numerics"]["convergence_v"] = 1e-6
        with self.assertRaisesRegex(ValueError, "stopping contract"):
            p.compile_request(request)
        self.source["native_solver_numerics"]["convergence_v"] = 1e-5
        with self.assertRaisesRegex(ValueError, "same-geometry"):
            p.compile_request({**request, "geometry_contract_path": str(self.contract_path)})

    def mirror_extension_request(self):
        request = self.mirror_reuse_request()
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        for index in (0, 1):
            mirror = self.source["refinement_windows"][index]
            path = Path(mirror["sources"]["numerical_plan"])
            plan = p.read(path)
            plan["box_mm"][4] = 1
            plan["dimensions"][1] = 4
            p.write_json(path, plan)
            mirror["grid"]["dimensions"][1] = 4
            mirror["active_box_mm"][1][1] = 0
            layout["windows"][index] = {"pitch_mm": [1, 1, 1], "box_mm": [0, -2, -2, 2, 2, 2]}
        p.write_json(self.contract_path, self.contract)
        return request

    def test_mirror_y_extension_preserves_guard_reused_layers_and_collision(self):
        request = self.mirror_extension_request()
        original = copy.deepcopy(self.source)
        plan = p.compile_request(request)
        for index in (0, 1):
            level = plan["levels"][f"window_{index}"]
            self.assertEqual(level["box_mm"], [0, -2, -2, 2, 2, 2])
            self.assertEqual(level["dimensions"], [3, 5, 5])
            self.assertEqual(level["active_box_mm"], [[-1, 1], [-1, 1], [-1, 1]])
            self.assertNotIn("reuse_source", level)
        for label in ("parent", "window_2"):
            self.assertEqual(plan["levels"][label]["committed_new_bytes"], 0)
        self.assertEqual(self.source, original)
        binding = p.binding_spec(plan, self.root / "extended")
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])

    def test_mirror_y_extension_rejects_other_axes_shrink_unaligned_and_outside_donor(self):
        request = self.mirror_extension_request()
        for axis, value in ((0, -1), (1, -3), (2, -3), (3, 3), (5, 3), (4, 0), (4, 1.5), (4, 3)):
            with self.subTest(axis=axis, value=value):
                contract = copy.deepcopy(self.contract)
                contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["box_mm"][axis] = value
                p.write_json(self.contract_path, contract)
                with self.assertRaises(ValueError):
                    p.compile_request(request)

    def test_mirror_box_unchanged_is_compatible_and_prepare_rejects_tampered_box(self):
        request = self.mirror_extension_request()
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        for target in layout["windows"][:2]:
            target["box_mm"][4] = 1
        p.write_json(self.contract_path, self.contract)
        plan = p.compile_request(request)
        self.assertEqual(plan["levels"]["window_0"]["active_box_mm"][1][1], 0)
        run = self.root / "tampered"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        plan["levels"]["window_0"]["box_mm"][4] = 2
        plan["levels"]["window_0"]["dimensions"][1] = 5
        with self.assertRaisesRegex(ValueError, "target layout"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_mirror_box_override_rejects_reused_roles_and_response_routes(self):
        request = self.mirror_extension_request()
        for role in ("parent", "window_2"):
            contract = copy.deepcopy(self.contract)
            layout = contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
            (layout["parent"] if role == "parent" else layout["windows"][2])["box_mm"] = [0, -2, -2, 2, 2, 2]
            p.write_json(self.contract_path, contract)
            with self.assertRaisesRegex(ValueError, "only extend"):
                p.compile_request(request)
        p.write_json(self.contract_path, self.contract)
        for changes in ({"response_axis": "s1"}, {"response_basis_paths": {}},
                        {"reuse_source_levels": ["parent", "window_2", "window_2"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                p.compile_request({**request, **changes})

    def test_pure_s1_extension_reuses_only_matching_pure_parent_and_central(self):
        request = self.mirror_extension_request()
        request.pop("candidate_voltages_v")
        request["response_axis"] = "s1"
        original_authority = copy.deepcopy(self.authority)
        self.source["authority"] = p._pure_axis_authority(original_authority, "s1")
        meta = dict(axis="s1", normalization_v=10000., physical_electrode_ids=[11, 12],
                    excitation_semantics="pure axis response; all other analyzer/component potentials zero",
                    combination_semantics="base PA plus (target axis minus base axis)/normalization_v times this PA")
        self.source.update(response_basis=meta, source_authority=original_authority,
                           source_binding_path=str(self.root / "ordinary.json"))
        p.write_json(Path(request["source_binding_path"]), dict(
            role="mrtof_native_static_field_response_basis", source_binding_path=self.source["source_binding_path"]))
        with patch.object(p, "load_native_response_basis", return_value=self.source):
            plan = p.compile_request(request)
            self.assertEqual(plan["source_authority"], original_authority)
            self.assertEqual(plan["candidate_authority"], self.source["authority"])
            self.assertEqual(plan["inputs"]["source_binding"], self.source["source_binding_path"])
            self.assertEqual(plan["inputs"]["source_response_basis"], request["source_binding_path"])
            for label in ("parent", "window_2"):
                self.assertEqual(plan["levels"][label]["committed_new_bytes"], 0)
            self.assertEqual(plan["levels"]["window_0"]["box_mm"][4], 2)
            for mutation in ("axis", "normalization", "background"):
                bad = copy.deepcopy(self.source)
                if mutation == "axis":
                    bad["response_basis"]["axis"] = "p1"
                elif mutation == "normalization":
                    bad["response_basis"]["normalization_v"] = 1
                else:
                    bad["authority"]["component_voltages_v"][0]["voltage_v"] = 1
                with self.subTest(mutation=mutation), patch.object(p, "load_native_response_basis", return_value=bad), self.assertRaises(ValueError):
                    p.compile_request(request)

    def test_new_geometry_direct_build_freezes_contract_and_same_collision_parent(self):
        updated, resolver = self.new_geometry()
        old = copy.deepcopy(self.source)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["resolved_geometry"], updated)
        self.assertEqual(plan["operation"], "refine")
        self.assertEqual(plan["inputs"]["geometry_contract"], self.request["geometry_contract_path"])
        resolver.assert_called_once_with(self.contract, accelerator_assembly=self.authority["assembly"])
        self.assertEqual(self.source, old)
        run = self.root / "new_geometry_run"
        (run / "inputs").mkdir(parents=True)
        for name in ("numerical_contract", "geometry_contract"):
            p.write_json(run / "inputs" / (name + ".json"), self.contract)
        p.prepare_run(plan, run)
        self.assertEqual(p.read(run / "inputs/resolved_geometry.json"), updated)
        binding = p.binding_spec(plan, run)
        self.assertEqual(binding["instances"][0]["pa_path"], binding["parent"]["pa_path"])
        self.assertEqual(binding["instances"][2:], old["instances"][2:])
        self.assertEqual(binding["instances"][1]["pa_path"], str((run / "simion/collision/collision.pa").resolve()))
        self.assertEqual(plan["collision_build"]["pa_bytes"], 656)
        self.assertIn("no Refine or Fast Adjust", (run / "simion/collision/collision.gem").read_text())
        self.assertEqual(p.read(run / "inputs/collision_plan.json")["resolved_geometry"], str((run / "inputs/resolved_geometry.json").resolve()))
        for label in ("parent", "window"):
            numerical = p.read(run / "inputs" / (label + "_plan.json"))
            self.assertEqual(numerical["resolved_geometry"], str((run / "inputs/resolved_geometry.json").resolve()))
        self.assertEqual(p.read(run / "inputs/window_plan.json")["parent_pa"], binding["parent"]["pa_path"])
        self.assertFalse(list(run.rglob("*.pa")))

    def test_new_geometry_rejects_old_response_and_consumer_routes_before_loading(self):
        for key in ("response_axis", "response_basis_paths", "consumer_view_source_path"):
            with self.subTest(key=key), patch.object(p, "load_binding") as load:
                request = dict(self.request, geometry_contract_path="explicit.json", **{key: "old"})
                with self.assertRaisesRegex(ValueError, "direct build"):
                    p.compile_request(request)
                load.assert_not_called()

    def test_new_geometry_rejects_component_frame_and_parent_bounds_changes(self):
        updated, resolver = self.new_geometry()
        path = Path(self.request["geometry_contract_path"])
        for key in ("coordinate_system", "accelerator", "detector"):
            changed = copy.deepcopy(self.contract)
            changed[key] = {"identity": "different"}
            p.write_json(path, changed)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "new assembly"):
                p.compile_request(self.request)
        p.write_json(path, self.contract)
        for key in ("frame_id", "prism_electrodes", "detector"):
            changed = copy.deepcopy(updated)
            changed[key] = "different"
            resolver.return_value = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "only mirror solids"):
                p.compile_request(self.request)
        changed = copy.deepcopy(updated)
        changed["mirror_electrodes"][0]["box"][5] = 3
        resolver.return_value = changed
        with self.assertRaisesRegex(ValueError, "outside the grounded parent"):
            p.compile_request(self.request)

    def test_prepare_rejects_new_geometry_changed_after_compile(self):
        updated, resolver = self.new_geometry()
        plan = p.compile_request(self.request)
        run = self.root / "new_geometry_run"
        (run / "inputs").mkdir(parents=True)
        for name in ("numerical_contract", "geometry_contract"):
            p.write_json(run / "inputs" / (name + ".json"), self.contract)
        changed = copy.deepcopy(updated)
        changed["mirror_convergence_transform"]["angle_deg"] = .2
        resolver.return_value = changed
        with self.assertRaisesRegex(ValueError, "frozen geometry contract"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_new_geometry_allows_only_mirror_derived_reference_bound(self):
        updated, resolver = self.new_geometry()
        reference = dict(reference_plane_project_z_mm=33, open_project_z_interval_mm=[26, 40],
                         derivation=dict(lower_boundary={"value_mm": 26},
                                         upper_boundary_candidates_mm={"mirror": 102}, selected_upper_boundary_mm=40))
        self.geometry["two_prism_low_field_reference_section"] = copy.deepcopy(reference)
        updated["two_prism_low_field_reference_section"] = copy.deepcopy(reference)
        updated["two_prism_low_field_reference_section"]["derivation"].update(
            upper_boundary_candidates_mm={"mirror": 101.9}, mirror_inner_face={"dz_dy": -.001})
        self.assertEqual(p.compile_request(self.request)["resolved_geometry"]["two_prism_low_field_reference_section"]
                         ["reference_plane_project_z_mm"], 33)
        changed = copy.deepcopy(updated)
        changed["two_prism_low_field_reference_section"]["reference_plane_project_z_mm"] = 34
        resolver.return_value = changed
        with self.assertRaisesRegex(ValueError, "observation plane"):
            p.compile_request(self.request)

    def test_composition_source_recovers_sealed_full_solve_without_old_pa(self):
        self.three_windows()
        for index, level in enumerate(self.source["refinement_windows"][:2]):
            path = Path(level["sources"]["numerical_plan"])
            consumer = p.read(path)
            ancestor = path.with_name("sealed_original_consumer.json")
            p.write_json(ancestor, consumer)
            composed = copy.deepcopy(consumer)
            composed.pop("crop")
            composed.pop("full_solve_plan_path")
            composed.update(source_solve_plan_path=str(ancestor), source_solve_manifest=level["manifest"])
            p.write_json(path, composed)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["levels"]["window_0"]["box_mm"][3], 2)
        self.assertEqual(plan["levels"]["window_0"]["consumer_grid"]["box_mm"][3], 1.5)
        self.assertIn("window_0_solve_ancestor_1", plan["inputs"])
        ancestor = Path(plan["inputs"]["window_0_solve_ancestor_1"])
        changed = p.read(ancestor)
        changed["pitch_mm"][0] = .25
        p.write_json(ancestor, changed)
        with self.assertRaisesRegex(ValueError, "consumer grid differs"):
            p.compile_request(self.request)

    def test_compiles_new_u_both_levels_and_capacity_from_nodes(self):
        plan = p.compile_request(self.request)
        self.assertEqual(plan["run_id"], "test_run")
        self.assertEqual(plan["candidate_authority"], self.authority)
        self.assertEqual(plan["levels"]["parent"]["boundary_mode"], "grounded_enclosure")
        self.assertEqual(plan["levels"]["window"]["boundary_mode"], "x_mirror_five_faces")
        self.assertEqual(plan["levels"]["parent"]["capacity_basis"]["pa_node_bytes"], 656)
        self.assertLess(plan["committed_new_bytes"], 40 * 1024**2)
        self.assertEqual(plan["automatic_retry_count"], 0)
        self.assertFalse(plan["qualification_passed"])
        self.assertEqual(plan["refine_options"], {"convergence": 1e-5})
        self.assertEqual(plan["inputs"]["numerical_contract"], str(self.contract_path.resolve()))
        self.assertEqual(Path(plan["inputs"]["grid_validator"]).name, "native_corridor_plan.py")
        for level in plan["levels"].values():
            self.assertEqual(level["convergence_v"], 1e-5)
            self.assertEqual(level["refine_stopping"], "contract_convergence")

    def test_requires_explicit_finite_positive_numerical_contract(self):
        missing = dict(self.request)
        del missing["numerical_contract_path"]
        with self.assertRaisesRegex(ValueError, "numerical_contract_path"):
            p.compile_request(missing)
        for value in (None, True, 0, -1, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.contract["simion"]["numerical_profiles"]["native_static_field"]["refine"]["convergence_v"] = value
                self.contract_path.write_text(json.dumps(self.contract))
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    p.compile_request(self.request)
        p.write_json(self.contract_path, {"simion": {}})
        with self.assertRaisesRegex(ValueError, "Refine profile"):
            p.compile_request(self.request)

    def test_new_generation_rejects_legacy_pitch_without_rounding_or_mutating_source(self):
        path = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        value = p.read(path)
        value.update(pitch_mm=[.125, 1, 1], dimensions=[17, 5, 5])
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["pitch_mm"] = [.125, 1, 1]
        p.write_json(self.contract_path, self.contract)
        p.write_json(path, value)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "spacing_quantum_mm"):
            p.compile_request(self.request)
        self.assertEqual(path.read_bytes(), before)

    def test_new_generation_preserves_valid_anisotropic_pitch(self):
        path = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        value = p.read(path)
        value.update(pitch_mm=[.05, .1, .2], dimensions=[41, 41, 21])
        self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["pitch_mm"] = [.05, .1, .2]
        p.write_json(self.contract_path, self.contract)
        p.write_json(path, value)
        plan = p.compile_request(self.request)
        self.assertEqual(plan["levels"]["window"]["pitch_mm"], [.05, .1, .2])
        self.assertEqual(plan["levels"]["window"]["box_mm"], value["box_mm"])
        self.assertEqual(plan["grid_generation"], {"spacing_quantum_mm": .01})

    def test_numerical_repository_contract_is_frozen_input_not_an_artifact_lease(self):
        plan = p.compile_request(self.request)
        self.assertEqual(plan["inputs"]["numerical_contract"], str(self.contract_path.resolve()))
        self.assertNotIn(str(self.contract_path.resolve()), plan["protected_paths"])
        self.assertIn(self.request["source_binding_path"], plan["protected_paths"])
        for level in (self.source, *self.source["refinement_windows"]):
            self.assertIn(str(Path(level["manifest"]).parent), plan["protected_paths"])
            for path in level["sources"].values():
                self.assertIn(path, plan["protected_paths"])
        for instance in self.source["instances"][1:]:
            self.assertIn(instance["manifest"], plan["protected_paths"])
            self.assertIn(instance["pa_path"], plan["protected_paths"])

    def test_reject_invalid_run_id_and_four_coordinate_contract(self):
        for change in ({"run_id": "../old"}, {"candidate_voltages_v": {"s1": 2}},
                       {"candidate_voltages_v": dict(self.request["candidate_voltages_v"], p1=float("nan"))},
                       {"candidate_voltages_v": dict(self.request["candidate_voltages_v"], p1=True)},
                       {"unrecognized": 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.compile_request(dict(self.request, **change))

    def test_real_candidate_authority_maps_only_four_ps_groups(self):
        self.authority["analyzer_electrode_voltages_v"] = list(range(20))
        with patch.object(p, "derive_candidate_authority", side_effect=derive_candidate_authority):
            plan = p.compile_request(self.request)
        actual = plan["candidate_authority"]["analyzer_electrode_voltages_v"]
        for index, expected in ((10, -27), (11, -27), (12, 55), (13, 55), (15, 1), (16, -2)):
            self.assertEqual(actual[index], expected)
        for index in set(range(20)) - {10, 11, 12, 13, 15, 16}:
            self.assertEqual(actual[index], index)
        self.assertEqual(self.authority["analyzer_electrode_voltages_v"], list(range(20)))

    def test_reject_non_native_or_multiple_windows_or_wrong_manifest(self):
        self.source["mode"] = "comsol_static_scalar_v"
        with self.assertRaises(ValueError):
            p.compile_request(self.request)
        self.source["mode"] = "native_static_pa"
        self.source["refinement_windows"].append(copy.deepcopy(self.source["refinement_windows"][0]))
        with self.assertRaises(ValueError):
            p.compile_request(self.request)
        self.source["refinement_windows"].pop()
        with self.assertRaises(ValueError):
            p.compile_request(dict(self.request, source_field_manifest=str(self.root / "wrong.json")))

    def test_reject_source_retry_contract(self):
        path = Path(self.source["sources"]["numerical_plan"])
        value = p.read(path)
        value["resource_limits"]["automatic_retry_count"] = 1
        p.write_json(path, value)
        with self.assertRaises(ValueError):
            p.compile_request(self.request)

    def test_prepare_and_binding_keep_same_u_surface_and_collision_roles(self):
        plan = p.compile_request(self.request)
        run = self.root / "test_run"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        self.assertEqual(p.read(run / "inputs/frozen_input.json"), self.authority)
        self.assertEqual(p.read(run / "inputs/resolved_geometry.json"), self.geometry)
        window_plan = p.read(run / "inputs/window_plan.json")
        for label in ("parent", "window"):
            actual = p.read(run / "inputs" / (label + "_plan.json"))
            self.assertEqual(actual["numerical_contract_path"], str((run / "inputs/numerical_contract.json").resolve()))
            self.assertEqual(actual["convergence_v"], 1e-5)
        binding = p.binding_spec(plan, run)
        self.assertEqual(window_plan["parent_manifest"], binding["parent"]["manifest"])
        self.assertEqual(window_plan["parent_pa"], binding["parent"]["pa_path"])
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])
        self.assertEqual(binding["instances"][0]["pa_path"], binding["parent"]["pa_path"])
        self.assertEqual(binding["parent"]["surface_path"], binding["parent"]["pa_path"] + "-surf")
        self.assertEqual(binding["refinement_windows"][0]["active_box_mm"], plan["levels"]["window"]["active_box_mm"])
        self.assertFalse(list(run.rglob("*.pa")))
        json.dumps(binding, allow_nan=False)

    def test_prepare_rejects_contract_changed_after_compile_before_gem_emission(self):
        plan = p.compile_request(self.request)
        run = self.root / "test_run"
        (run / "inputs").mkdir(parents=True)
        changed = copy.deepcopy(self.contract)
        changed["simion"]["numerical_profiles"]["native_static_field"]["refine"]["convergence_v"] = 1e-7
        p.write_json(run / "inputs/numerical_contract.json", changed)
        with self.assertRaisesRegex(ValueError, "frozen numerical contract"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def three_windows(self):
        """Build real-shaped child-before-E priority with sealed full/crop plans."""
        e = self.source["refinement_windows"][0]
        windows = []
        for index in range(2):
            child = copy.deepcopy(e)
            directory = self.root / f"mirror_{index}"
            directory.mkdir()
            child["manifest"] = str(directory / "run_manifest.json")
            child["name"] = f"mirror_{index}"
            child["sources"]["scalar_pa"] = str(directory / "static.pa")
            child["sources"]["numerical_plan"] = str(directory / "consumer_plan.json")
            full = p.read(Path(e["sources"]["numerical_plan"]))
            full.update(parent_manifest=e["manifest"], parent_pa=e["sources"]["scalar_pa"],
                        crop={"consumer_box_mm": [0, -2, -2, 1.5, 2, 2],
                              "consumer_dimensions": [4, 5, 5]},
                        pitch_mm=[.5, 1, 1], dimensions=[5, 5, 5])
            p.write_json(directory / "full_plan.json", full)
            consumer = copy.deepcopy(full)
            consumer.update(box_mm=full["crop"]["consumer_box_mm"],
                            dimensions=full["crop"]["consumer_dimensions"],
                            full_solve_plan_path=str(directory / "full_plan.json"))
            p.write_json(directory / "consumer_plan.json", consumer)
            windows.append(child)
        self.source["refinement_windows"] = [*windows, e]
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        layout["windows"] = [{"pitch_mm": [.5, 1, 1], "stored_xmax_mm": 1.5},
                             {"pitch_mm": [.5, 1, 1], "stored_xmax_mm": 1.5},
                             {"pitch_mm": [1, 1, 1]}]
        p.write_json(self.contract_path, self.contract)

    def test_three_level_dependencies_priority_fullsolve_and_capacity(self):
        self.three_windows()
        plan = p.compile_request(self.request)
        self.assertEqual(plan["window_labels"], ["window_0", "window_1", "window_2"])
        self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
        self.assertEqual(plan["levels"]["window_0"]["parent_label"], "window_2")
        self.assertEqual(plan["levels"]["window_2"]["parent_label"], "parent")
        mirror = plan["levels"]["window_0"]
        self.assertEqual(mirror["box_mm"][3], 2)
        self.assertEqual(mirror["dimensions"], [5, 5, 5])
        self.assertEqual(mirror["consumer_grid"]["dimensions"], [4, 5, 5])
        self.assertEqual(mirror["crop"]["width_grid"], [3, 4, 4])
        self.assertEqual(mirror["crop"]["expected_consumer_pa_bytes"], 856)
        self.assertLess(plan["committed_new_bytes"], sum(v["committed_new_bytes"] for v in plan["levels"].values()))
        run = self.root / "prepared"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        p.prepare_run(plan, run)
        binding = p.binding_spec(plan, run)
        self.assertEqual([w["name"] for w in binding["refinement_windows"]], ["mirror_0", "mirror_1", "covered"])
        for label in plan["execution_order"]:
            actual = p.read(run / "inputs" / (label + "_plan.json"))
            self.assertEqual(actual["convergence_v"], 1e-5)
            self.assertEqual(p.read(Path(actual["frozen_input"])), self.authority)
        consumer = p.read(run / "inputs/window_0_consumer_plan.json")
        self.assertEqual(consumer["parent_pa"], str((run / "simion/window_2/c0_local.pa").resolve()))
        self.assertEqual(consumer["full_solve_plan_path"], str((run / "inputs/window_0_plan.json").resolve()))
        self.assertEqual(binding["refinement_windows"][0]["grid"]["dimensions"], [4, 5, 5])
        self.assertEqual(binding["instances"][1:], self.source["instances"][1:])
        self.assertFalse(list(run.rglob("*.pa")))

    def test_three_windows_reject_missing_or_consumer_in_place_of_full_plan(self):
        self.three_windows()
        path = Path(self.source["refinement_windows"][0]["sources"]["numerical_plan"])
        original = p.read(path)
        for replacement in (None, str(path)):
            with self.subTest(path=replacement):
                changed = dict(original, full_solve_plan_path=replacement)
                p.write_json(path, changed)
                with self.assertRaisesRegex(ValueError, "full.solve"):
                    p.compile_request(self.request)
        p.write_json(path, original)
        with patch.object(p, "verify_record", side_effect=ValueError("sealed full plan changed")):
            with self.assertRaisesRegex(ValueError, "sealed full plan"):
                p.compile_request(self.request)

    def test_three_windows_reject_unknown_parent_cycle_and_invalid_target(self):
        self.three_windows()
        path = Path(self.source["refinement_windows"][2]["sources"]["numerical_plan"])
        original = p.read(path)
        for parent_pa in (str(self.root / "unrelated.pa"), self.source["refinement_windows"][2]["sources"]["scalar_pa"]):
            p.write_json(path, dict(original, parent_pa=parent_pa))
            with self.assertRaisesRegex(ValueError, "declared distinct"):
                p.compile_request(self.request)
        p.write_json(path, original)
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        for target in ({}, {"pitch_mm": [.125, 1, 1]}, {"pitch_mm": [.5, 1, 1], "stored_xmax_mm": 1}):
            layout["windows"][0] = target
            p.write_json(self.contract_path, self.contract)
            with self.assertRaises(ValueError):
                p.compile_request(self.request)

    def test_prepare_rejects_changed_target_layout_before_gem(self):
        plan = p.compile_request(self.request)
        changed = copy.deepcopy(self.contract)
        changed["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"][0]["pitch_mm"] = [.5, 1, 1]
        run = self.root / "changed_target"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", changed)
        with self.assertRaisesRegex(ValueError, "target layout"):
            p.prepare_run(plan, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_actual_a162200_compiles_frozen_prepare_and_binding_without_pa_io(self):
        repo = Path(__file__).resolve().parents[4]
        artifact = repo.parent / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs"
        binding_path = artifact / "20261012_162200__analysis__simion__mrtof-integer-grid-a-binding/results/field_binding.json"
        if not binding_path.is_file():
            self.skipTest("external successful A binding unavailable")
        if not Path(p.read(binding_path)["parent"]["pa_path"]).is_file():
            self.skipTest("external A parent payload retired; small evidence remains")
        contract_path = repo / "projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json"
        with (patch.object(p, "load_binding", side_effect=load_binding),
              patch.object(p, "_record", side_effect=_record),
              patch.object(p, "verify_record", side_effect=verify_record),
              patch.object(p, "derive_candidate_authority", side_effect=derive_candidate_authority),
              patch.object(p, "build_static_c0_gem", side_effect=build_static_c0_gem)):
            source = load_binding(binding_path)
            values = source["authority"]["analyzer_electrode_voltages_v"]
            request = dict(self.request, source_binding_path=str(binding_path),
                           source_field_manifest=source["manifest"], numerical_contract_path=str(contract_path),
                           candidate_voltages_v=dict(s1=values[10], s2=values[12], p1=values[15], p2=values[16]))
            plan = p.compile_request(request)
            self.assertEqual(plan["candidate_authority"], source["authority"])
            self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
            self.assertEqual(plan["levels"]["window_2"]["dimensions"], [91, 1961, 6501])
            self.assertEqual(plan["levels"]["window_0"]["dimensions"], [51, 2076, 5851])
            run = self.root / "actual_a_pure_prepare"
            (run / "inputs").mkdir(parents=True)
            p.write_json(run / "inputs/numerical_contract.json", p.read(contract_path))
            p.prepare_run(plan, run)
            binding = p.binding_spec(plan, run)
            self.assertEqual([w["name"] for w in binding["refinement_windows"]],
                             [w["name"] for w in source["refinement_windows"]])
            self.assertEqual(binding["instances"][1:], plan["collision_instances"][1:])
            for index, label in enumerate(plan["window_labels"]):
                actual = p.read(Path(binding["refinement_windows"][index]["numerical_plan_path"]))
                parent_label = plan["levels"][label]["parent_label"]
                basename = "c0_static.pa" if parent_label == "parent" else "c0_local.pa"
                self.assertEqual(actual["parent_pa"], str((run / "simion" / parent_label / basename).resolve()))
                self.assertEqual(actual["convergence_v"], 1e-5)
                if index < 2:
                    full = p.read(Path(actual["full_solve_plan_path"]))
                    self.assertEqual(full["box_mm"][3], 2)
                    self.assertEqual(actual["box_mm"][3], 1.28)
                    self.assertEqual(actual["dimensions"], [33, 2076, 5851])
                    self.assertEqual(actual["crop"]["expected_consumer_pa_bytes"], 3206722520)
            self.assertFalse(list(run.rglob("*.pa")))

    def test_new_mirror_offset_uses_normal_refine_without_dropping_declared_bank(self):
        request = dict(self.request, response_basis_paths={'s1': 's1-basis.json', 's2': 's2-basis.json'})
        def basis(path, source):
            result = copy.deepcopy(source)
            result['descriptor_path'] = str(path)
            result['response_basis'] = {'axis': path.name.split('-')[0]}
            return result
        with patch.object(p, '_compile_composition', return_value=None), \
                patch.object(p, 'load_native_response_basis', side_effect=basis):
            plan = p.compile_request(request)
        self.assertEqual(plan['operation'], 'refine')
        self.assertIsNone(plan['response_basis'])
        self.assertEqual(plan['inputs']['response_s1'], 's1-basis.json')
        self.assertEqual(plan['inputs']['response_s2'], 's2-basis.json')
        self.assertIn('s1-basis.json', plan['protected_paths'])
        self.assertEqual(request['response_basis_paths'], {'s1': 's1-basis.json', 's2': 's2-basis.json'})

    def test_all_four_pure_axes_clear_fixed_background_and_preserve_source(self):
        self.three_windows()
        self.authority["analyzer_electrode_voltages_v"] = [float(i) for i in range(20)]
        before = copy.deepcopy(self.source)
        for axis, ids in p.PS_GROUPS.items():
            with self.subTest(axis=axis):
                request = {k: v for k, v in self.request.items() if k != "candidate_voltages_v"}
                request["response_axis"] = axis
                plan = p.compile_request(request)
                self.assertEqual(plan["source_authority"], self.authority)
                actual = plan["candidate_authority"]
                self.assertEqual(actual["analyzer_electrode_voltages_v"],
                                 [10000.0 if i+1 in ids else 0.0 for i in range(20)])
                self.assertTrue(all(item["voltage_v"] == 0 for item in actual["component_voltages_v"]))
                self.assertEqual(plan["resolved_geometry"], self.geometry)
                self.assertFalse(plan["fly_authorized"])
                self.assertEqual(plan["response_basis"]["normalization_v"], 10000)
                self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
                self.assertTrue(all(x["response_basis"] == plan["response_basis"] for x in plan["levels"].values()))
                run = self.root / ("basis_"+axis)
                (run / "inputs").mkdir(parents=True)
                p.write_json(run / "inputs/numerical_contract.json", self.contract)
                p.prepare_run(plan, run)
                self.assertEqual(p.read(run / "inputs/source_authority.json"), self.authority)
                self.assertEqual(p.read(run / "inputs/frozen_input.json"), actual)
                descriptor = p.binding_spec(plan, run)
                self.assertEqual(descriptor["role"], "mrtof_native_static_field_response_basis")
                descriptor_path = run / "response_basis.json"
                p.write_json(descriptor_path, descriptor)
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    load_binding(descriptor_path)
                self.assertFalse(list(run.rglob("*.pa")))
        self.assertEqual(self.source, before)

    def te1_reference(self, direction=None):
        path = self.root / "te1_reference.json"
        direction = direction if direction is not None else [.26534181722826355,
            -1.3064907730209914, .8123479538407015, .7579824137295434]
        base = [0., -5920.610006092399, -2612.9815460419827, 4190.462801307053, 6029.159819776669]
        p.write_json(path, dict(schema_version=1, role="mrtof_terminal_time_mirror_voltage_variation",
            status="screening_candidate_materialized", mode="TE1", coordinate=1.,
            qualification="diagnostic_only__complete_3d_detector_response_pending",
            base_mirror_voltages_v=base, voltage_delta_v=direction,
            target_mirror_voltages_v=[0., *[v+d for v, d in zip(base[1:], direction, strict=True)]]))
        return path

    def test_te1_pure_direction_clears_background_and_covers_both_mirrors(self):
        self.three_windows()
        reference = self.te1_reference()
        request = {k:v for k,v in self.request.items() if k != "candidate_voltages_v"}
        request.update(response_axis="te1", te1_reference_path=str(reference))
        before = copy.deepcopy(self.source)
        plan = p.compile_request(request)
        basis = plan["response_basis"]
        excitation = p._te1_excitation(basis)
        self.assertEqual(max(abs(v) for v in excitation), 10000.)
        self.assertEqual(plan["candidate_authority"]["analyzer_electrode_voltages_v"], excitation*2+[0.]*10)
        self.assertTrue(all(v["voltage_v"] == 0 for v in plan["candidate_authority"]["component_voltages_v"]))
        self.assertEqual(basis["physical_electrode_ids"], [2,3,4,5,7,8,9,10])
        self.assertEqual(plan["execution_order"], ["parent", "window_2", "window_0", "window_1"])
        self.assertEqual(plan["inputs"]["te1_reference"], str(reference.resolve()))
        self.assertTrue(all(v["response_basis"] == basis for v in plan["levels"].values()))
        self.assertFalse(plan["fly_authorized"])
        run = self.root/"pure_te1"
        (run/"inputs").mkdir(parents=True)
        p.write_json(run/"inputs/numerical_contract.json", self.contract)
        (run/"inputs/te1_reference.json").write_bytes(reference.read_bytes())
        p.prepare_run(plan, run)
        descriptor = p.binding_spec(plan, run)
        self.assertEqual(descriptor["direction_reference_path"], str((run/"inputs/te1_reference.json").resolve()))
        self.assertEqual(self.source, before)
        self.assertFalse(list(run.rglob("*.pa")))

    def test_te1_coefficients_use_actual_nonzero_mirror_anchor_not_absolute_coordinate(self):
        reference = self.te1_reference()
        basis = p._te1_basis_metadata(reference)
        data = p.read(reference)
        direction = data["voltage_delta_v"]
        c0 = -22.894154431673797
        base = copy.deepcopy(self.authority)
        baseline = [0., *[v+c0*d for v,d in zip(data["base_mirror_voltages_v"][1:], direction, strict=True)]]
        base["analyzer_electrode_voltages_v"][:10] = baseline*2
        target_ps = {axis:0. for axis in p.PS_GROUPS}
        for delta in (0., -.988552922784, .988552922784):
            target = [0., *[v+delta*d for v,d in zip(baseline[1:], direction, strict=True)]]
            plan = p.compile_response_coefficients(base, target_ps, ["te1"],
                mirror_voltages_v=target, te1_basis=basis)
            self.assertAlmostEqual(plan["coefficients"]["te1"], delta*max(abs(d) for d in direction)/10000., places=15)
            self.assertEqual(plan["target_authority"]["analyzer_electrode_voltages_v"][:10], target*2)
        bad = target.copy(); bad[4] += .01
        with self.assertRaisesRegex(ValueError, "incompatible"):
            p.compile_response_coefficients(base, target_ps, ["te1"], mirror_voltages_v=bad, te1_basis=basis)
        for change in ({"normalization_v":0}, {"normalization_v":1},
                       {"direction_v_per_coordinate":[0.,0.,0.,0.]},
                       {"direction_v_per_coordinate":[1.,2.,3.,float("nan")]}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "normalization"):
                p._te1_excitation(dict(basis, **change))
        with self.assertRaises(ValueError):
            p._te1_basis_metadata(self.te1_reference([0.,0.,0.,0.]))

    def test_te1_reference_is_required_only_for_pure_te1_and_frozen_before_prepare(self):
        request = {k:v for k,v in self.request.items() if k != "candidate_voltages_v"}
        for change in ({"response_axis":"te1"}, {"response_axis":"s1", "te1_reference_path":"unused"},
                       {"response_axis":"te1", "te1_reference_path":"unused", "candidate_voltages_v":self.request["candidate_voltages_v"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.compile_request(dict(request, **change))

    def test_te1_e_closure_ids_consume_the_same_paired_e_drive(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import _mirror_ground_shield_lines
        basis = p._te1_basis_metadata(self.te1_reference())
        authority = p._response_authority(self.authority, basis)
        geometry = dict(mirror_inner_shield_slot=[-2,0,-1,2,1,1], mirror_ground_shields=[],
                        mirror_e_closures=[dict(id=5,box=[-1,0,2,1,1,3]), dict(id=10,box=[-1,0,-3,1,1,-2])])
        lines = _mirror_ground_shield_lines(geometry)
        self.assertIn("  e(5) {", lines)
        self.assertIn("  e(10) {", lines)
        self.assertEqual(authority["analyzer_electrode_voltages_v"][4], authority["analyzer_electrode_voltages_v"][9])
        self.assertNotEqual(authority["analyzer_electrode_voltages_v"][4], 0.)

    def test_response_axis_rejects_workpoint_updates_and_changed_baseline_layout(self):
        request = {k: v for k, v in self.request.items() if k != "candidate_voltages_v"}
        for extra in ({"response_axis": None}, {"response_axis": "mirror"},
                      {"response_axis": "s1", "candidate_voltages_v": self.request["candidate_voltages_v"]},
                      {"response_axis": "s1", "mirror_voltage_variation_path": "unused"}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "response_axis"):
                p.compile_request(dict(request, **extra))
        layout = self.contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]
        layout["windows"][0]["pitch_mm"] = [.5, 1, 1]
        p.write_json(self.contract_path, self.contract)
        with self.assertRaisesRegex(ValueError, "actual baseline"):
            p.compile_request(dict(request, response_axis="s1"))
        layout["windows"][0]["pitch_mm"] = [1, 1, 1]
        p.write_json(self.contract_path, self.contract)
        self.source["refinement_windows"][0]["native_solver_numerics"]["convergence_v"] = 1e-7
        with self.assertRaisesRegex(ValueError, "stopping contract"):
            p.compile_request(dict(request, response_axis="s1"))

    def test_prepare_rejects_contaminated_basis_or_fly_authorization(self):
        request = {k: v for k, v in self.request.items() if k != "candidate_voltages_v"}
        plan = p.compile_request(dict(request, response_axis="s1"))
        run = self.root / "bad_basis"
        (run / "inputs").mkdir(parents=True)
        p.write_json(run / "inputs/numerical_contract.json", self.contract)
        for change in ("background", "normalization", "fly"):
            bad = copy.deepcopy(plan)
            if change == "background":
                bad["candidate_authority"]["component_voltages_v"][0]["voltage_v"] = 1
            elif change == "normalization":
                bad["response_basis"]["normalization_v"] = 1
            else:
                bad["fly_authorized"] = True
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "pure response"):
                p.prepare_run(bad, run)
        self.assertFalse(list(run.rglob("*.gem")))

    def test_pure_response_coefficients_use_delta_over_normalization(self):
        base = copy.deepcopy(self.authority)
        for axis, ids in p.PS_GROUPS.items():
            for physical_id in ids:
                base["analyzer_electrode_voltages_v"][physical_id-1] = {"s1": -27., "s2": 55., "p1": 190., "p2": -190.}[axis]
        target = {"s1": -26., "s2": 53., "p1": 190., "p2": -190.}
        plan = p.compile_response_coefficients(base, target, ["s1", "s2"])
        self.assertEqual(plan["coefficients"], {"s1": .0001, "s2": -.0002})
        self.assertEqual(plan["target_authority"]["component_voltages_v"], base["component_voltages_v"])
        self.assertEqual(plan["target_authority"]["analyzer_electrode_voltages_v"][:10], base["analyzer_electrode_voltages_v"][:10])
        with self.assertRaisesRegex(ValueError, "without a pure response"):
            p.compile_response_coefficients(base, dict(target, p1=191), ["s1", "s2"])

    def test_actual_zero_voltage_bodies_and_all_unit_axis_geometry_are_retained(self):
        repo = Path(__file__).resolve().parents[4]
        binding_path = repo.parent / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261012_162200__analysis__simion__mrtof-integer-grid-a-binding/results/field_binding.json"
        if not binding_path.is_file():
            self.skipTest("external A geometry unavailable")
        if not Path(p.read(binding_path)["parent"]["pa_path"]).is_file():
            self.skipTest("external A parent payload retired; small evidence remains")
        source = load_binding(binding_path)
        original = p.read(Path(source["sources"]["numerical_plan"]))
        grid = {k: original[k] for k in ("box_mm", "pitch_mm", "dimensions", "mirror_axes", "surface")}
        base, _ = build_static_c0_gem(source["geometry"], source["authority"], grid, boundary_mode="grounded_enclosure")
        import re
        mask = lambda text: re.sub(r"\be\([^)]*\)", "e(PHYSICAL)", text)
        for axis, ids in p.PS_GROUPS.items():
            authority = p._pure_axis_authority(source["authority"], axis)
            gem, _ = build_static_c0_gem(source["geometry"], authority, grid, boundary_mode="grounded_enclosure")
            self.assertEqual(mask(gem), mask(base))
            self.assertEqual(gem.count("e(10000)"), len(ids))
            self.assertGreater(gem.count("e(0)"), 0)

    def test_composition_requires_explicit_nonempty_axis_map_and_no_basis_excitation(self):
        for paths in ({}, {"mirror": "x"}, {"s1": ""}, {"s1": None}):
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "response_basis_paths"):
                p.compile_request(dict(self.request, response_basis_paths=paths))
        request = {k:v for k,v in self.request.items() if k != "candidate_voltages_v"}
        with self.assertRaisesRegex(ValueError, "response_axis"):
            p.compile_request(dict(request, response_axis="s1", response_basis_paths={"s1": "x"}))


if __name__ == "__main__":
    unittest.main()
