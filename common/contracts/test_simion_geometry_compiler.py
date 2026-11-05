"""The installed SIMION compiler needs geometry, never a flight request/source."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_single_reflection_zero_gap import direct_inputs, direct_source
from msplatform.backends.simion import CompiledSimionGeometry, compile_geometry
from msplatform.backends.simion.geometry import compile_frontend_geometry
from msplatform.backends.simion.resources import gem_template_path


def compiler_inputs(root):
    sources = {"multipole":direct_source(shell=True)}
    tof, options = direct_inputs(root, sources)
    assembly = dict(composition_plan=options["composition_plan"], components_resolved={**sources, "oatof":tof})
    numerics = dict(frontend_domains=options["numerical_domains"],
        geometry_build=copy.deepcopy(tof["simion_geometry_build"]),
        detector_marker=copy.deepcopy(tof["simion_detector_marker"]))
    # The old provider's field-sample convenience input is not a geometry dependency.
    del tof["particle_source"]
    return assembly, numerics, options


class SimionGeometryCompilerTests(unittest.TestCase):
    def test_geometry_only_complete_specs_and_old_frontend_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, options = compiler_inputs(Path(directory))
            original = copy.deepcopy((assembly, numerics))
            with patch("subprocess.Popen", side_effect=AssertionError("no native process")), \
                    patch.object(Path, "write_text", side_effect=AssertionError("no output writes")), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("no run creation")):
                result = compile_geometry(assembly, numerics=numerics)
            self.assertIsInstance(result, CompiledSimionGeometry)
            self.assertEqual((assembly, numerics), original)
            self.assertEqual(set(result.frontend_gems), {"parent"})
            self.assertIn("pa_define(", result.frontend_gems["parent"])
            self.assertEqual([s["role"] for s in result.downstream_specs], ["flight_tube","reflectron","detector"])
            self.assertTrue(all(s["action"]=="gem2pa_only" for s in result.downstream_specs))
            self.assertTrue(all(s["template_context"]=="SIMION_GEM_Lua_global_var" for s in result.downstream_specs))
            for spec in result.downstream_specs:
                self.assertEqual(spec["template_text"].encode(), gem_template_path(spec["role"]).read_bytes())
                self.assertIn("pa_define(", spec["template_text"])
                self.assertNotIn("refine(", spec["template_text"])
                self.assertNotIn("fly(", spec["template_text"])
            self.assertEqual(set(result.downstream_specs[0]["template_variables"]), {"mmgu_axial","mmgu_radial","component"})
            detector = result.downstream_specs[2]["template_variables"]
            self.assertEqual(detector["radius"], assembly["components_resolved"]["oatof"]["geometry_mm"]["detector_radius"])
            # Expert transport of the same actual labels must reproduce old frontend text exactly.
            changed = copy.deepcopy(numerics)
            changed["electrode_group_native_ids"] = options["electrode_bindings"]
            result = compile_geometry(assembly, numerics=changed)
            legacy_gems, _ = compile_frontend_geometry(
                {"multipole":assembly["components_resolved"]["multipole"]}, assembly["components_resolved"]["oatof"], **options)
            self.assertEqual(result.frontend_gems, legacy_gems)
            for identity in result.provider_content_identities.values():
                self.assertEqual(set(identity), {"resolved_content_sha256", "component_interface_sha256"})
                self.assertTrue(all(len(value)==64 for value in identity.values()))

    def test_template_migration_preserves_all_original_bytes(self):
        expected = {
            "flight_tube": "55c4dd8e249ad3af532047f77b235c700eae47e15951a2828f1605dfc9841f1e",
            "reflectron": "6bc686c9a4827827dc45eef13590ea2ccdc578038a05f90d8132afbb00f7b2fb",
            "detector": "9688511443118d7e69f780c3d54e42685b520882b3cc55f4777c68cbe515b8f3",
        }
        for role, digest in expected.items():
            with self.subTest(role=role):
                self.assertEqual(hashlib.sha256(gem_template_path(role).read_bytes()).hexdigest(), digest)

    def test_expert_native_map_and_geometry_contract_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, options = compiler_inputs(Path(directory))
            for bad in ("missing", "extra", "collision", "boolean", "capacity", "old_plan", "source"):
                changed, model = copy.deepcopy(numerics), copy.deepcopy(assembly)
                changed["electrode_group_native_ids"] = copy.deepcopy(options["electrode_bindings"])
                mapping = changed["electrode_group_native_ids"]["multipole"]
                keys = list(mapping)
                if bad == "missing": mapping.pop(keys[0])
                elif bad == "extra": mapping["not_a_scientific_group"] = 999
                elif bad == "collision": mapping[keys[0]] = mapping[keys[1]]
                elif bad == "boolean": mapping[keys[0]] = True
                elif bad == "capacity": mapping[keys[0]] = 1001
                elif bad == "old_plan": model["composition_plan"]["schema_version"] = 3
                else: model["source"] = dict(particle_count=1)
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    compile_geometry(model, numerics=changed)

    def test_numerical_marker_cannot_change_the_physical_detector(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, _ = compiler_inputs(Path(directory))
            numerics["detector_marker"]["active_radius_mm"] += 1.
            with self.assertRaisesRegex(ValueError, "physical detector"):
                compile_geometry(assembly, numerics=numerics)

    def test_mechanical_plan_cannot_reauthorize_a_changed_gap_or_check(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, _ = compiler_inputs(Path(directory))
            for kind in ("gap", "checks"):
                changed = copy.deepcopy(assembly)
                plan = changed["composition_plan"]
                if kind == "gap":
                    plan["recipe"]["connections"][0]["gap_mm"] = 1.
                else:
                    plan["connection_checks"] = []
                before = copy.deepcopy(changed)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    compile_geometry(changed, numerics=numerics)
                self.assertEqual(changed, before)


if __name__ == "__main__":
    unittest.main()
