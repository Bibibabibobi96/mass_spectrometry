"""Focused software checks for canonical detector projection; native occupancy remains open."""
import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from common.contracts.test_simion_geometry_compiler import compiler_inputs
from msplatform.backends.simion.compiler import compile_geometry

LUA = (os.environ["SIMION_LUA_EXE"] if "SIMION_LUA_EXE" in os.environ else
       shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")


class DetectorPhysicalProjectionTests(unittest.TestCase):
    def test_detector_body_and_marker_have_distinct_authorities(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, _ = compiler_inputs(Path(directory))
            before = copy.deepcopy((assembly, numerics))
            result = compile_geometry(assembly, numerics=numerics)
            detector = next(s for s in result.downstream_specs if s['role'] == 'detector')
            body = assembly['components_resolved']['oatof']['geometry_mm']
            marker = numerics['detector_marker']
            self.assertEqual(detector['template_variables']['radius'], body['detector_radius'])
            self.assertEqual(detector['template_variables']['absorber_thickness'], body['detector_thickness'])
            self.assertEqual(marker['absorber_thickness_mm'], 0.1)
            self.assertEqual(marker['capture_depth_mm'], 0.02)
            self.assertEqual((assembly, numerics), before)
            row = next(x for x in result.frontend_geometry['downstream_pa_instances'] if x['role'] == 'detector')
            self.assertEqual(row['physical_detector']['height_mm'], body['detector_thickness'])
            self.assertEqual(row['numerical_marker'], marker)
            self.assertEqual(row['z_mm'], marker['active_plane_z_mm'] - row['physical_back_cells'] * marker['cell_z_mm'])
            self.assertEqual(row['nz'], row['physical_back_cells'] + row['physical_front_cells'] + 1)
            self.assertGreaterEqual((row['nz'] - 1) * marker['cell_z_mm'], marker['front_margin_z_mm'] + body['detector_thickness'] + marker['back_margin_z_mm'])


if __name__ == '__main__':
    unittest.main()

class DetectorBuilderBudgetTests(unittest.TestCase):
    def test_real_builder_budget_and_phase_aligned_body(self):
        import subprocess
        from msplatform.backends.simion.source import lua_value
        from msplatform.backends.simion.resources import native_resource_path
        lua = LUA
        marker = dict(cell_xy_mm=.5, cell_z_mm=.01, active_radius_mm=40.,
                      absorber_thickness_mm=.1, front_margin_z_mm=.2, back_margin_z_mm=.05)
        body = dict(radius_mm=40., height_mm=1.003, back_cells=106, front_cells=20)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.gem'
            source.write_text('inert source\n', encoding='utf-8')
            builder = native_resource_path('build_detector_variant.lua')
            for limit, passes in ((64, False), (128, True)):
                with self.subTest(limit=limit):
                    projection = root / ('projection%d.lua' % limit)
                    projection.write_text('return ' + lua_value(dict(
                        physical_geometry=dict(simion=dict(detector_marker=marker, detector_body=body)),
                        simion_geometry_build=dict(detector=dict(margin_xy_mm=1., max_mib=limit)))) + '\n', encoding='utf-8')
                    harness = root / ('harness%d.lua' % limit)
                    import json
                    argv = [str(source), str(root / ('raw%d.pa#' % limit)), str(projection), 'geometry-only']
                    harness.write_text('arg={' + ','.join(json.dumps(s) for s in argv) + '}\n' +
                        'simion={command=function(_) assert(var.absorber_thickness==1.003); assert(var.back_cells==106); assert(var.front_cells==20); print("MOCK_GEM2PA=CALLED") end}\n' +
                        'dofile(' + json.dumps(str(builder)) + ')\n', encoding='utf-8')
                    result = subprocess.run([lua, str(harness)], cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
                    if passes:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn('MOCK_GEM2PA=CALLED', result.stdout)
                        self.assertIn('BUILD_GEOMETRY=PASS ROLE=detector', result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('exceeds limit', result.stderr)
                        self.assertNotIn('MOCK_GEM2PA=CALLED', result.stdout)

class DetectorOffGridTests(unittest.TestCase):
    def test_nonintegral_thickness_keeps_active_plane_and_complete_body(self):
        from msplatform.backends.simion.downstream import compile_downstream_specs
        with tempfile.TemporaryDirectory() as directory:
            assembly, _, _ = compiler_inputs(Path(directory))
            resolved = assembly['components_resolved']['oatof']
            resolved['geometry_mm']['detector_thickness'] = 1.003
            spec = next(s for s in compile_downstream_specs(resolved) if s['role'] == 'detector')
            marker = resolved['simion_detector_marker']
            row = spec['native_instance']
            self.assertEqual(spec['template_variables']['absorber_thickness'], 1.003)
            self.assertEqual(row['physical_back_cells'], 106)
            self.assertEqual(row['physical_front_cells'], 20)
            self.assertAlmostEqual(row['z_mm'] + row['physical_back_cells'] * marker['cell_z_mm'], marker['active_plane_z_mm'])
            self.assertLessEqual(row['z_mm'], marker['active_plane_z_mm'] - 1.003 - marker['back_margin_z_mm'])
            self.assertEqual(marker['absorber_thickness_mm'], .1)
            self.assertEqual(marker['capture_depth_mm'], .02)

class DetectorNondefaultFaceTests(unittest.TestCase):
    def test_nonzero_physical_face_and_radius_are_preserved(self):
        from msplatform.backends.simion.downstream import compile_downstream_specs
        with tempfile.TemporaryDirectory() as directory:
            assembly, _, _ = compiler_inputs(Path(directory))
            resolved = assembly["components_resolved"]["oatof"]
            resolved["geometry_mm"].update(detector_z=12.5, detector_radius=27.5)
            resolved["simion_detector_marker"].update(active_plane_z_mm=12.5, active_radius_mm=27.5)
            spec = next(row for row in compile_downstream_specs(resolved) if row["role"] == "detector")
            body, instance = spec["physical_detector"], spec["native_instance"]
            self.assertEqual(body["base_center_mm"][2] + body["height_mm"], 12.5)
            self.assertEqual(body["radius_mm"], 27.5)
            self.assertAlmostEqual(instance["z_mm"] + instance["physical_back_cells"] * .01, 12.5)
            resolved["simion_detector_marker"]["active_plane_z_mm"] = 0.
            with self.assertRaisesRegex(ValueError, "differs from the physical detector active face"):
                compile_downstream_specs(resolved)


class DetectorNativePlanTests(unittest.TestCase):
    def test_real_geometry_plan_transports_body_and_marker_without_refine(self):
        from common.contracts.test_simion_native_plans import SEED, NATIVE_PATH
        from msplatform.backends.simion.native_plans import plan_geometry_build
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, numerics, _ = compiler_inputs(root / 'author')
            compiled = compile_geometry(assembly, numerics=numerics)
            plan = plan_geometry_build(compiled, run_directory=root / 'plan', seed_record=SEED,
                                       native_path_resource=NATIVE_PATH)
            projection = plan.materializations[str(root / 'plan/inputs/downstream_projection.lua')]
            self.assertIn('detector_body', projection)
            self.assertIn('detector_marker', projection)
            self.assertIn('back_cells', projection)
            detector = next(op for op in plan.operations if op['operation_id'] == 'geometry_detector')
            self.assertEqual(detector['arguments'][-1], 'geometry-only')
            self.assertFalse(any('refine' in arg.lower() or 'fly' in arg.lower()
                                 for op in plan.operations for arg in op['arguments']))
            self.assertFalse((root / 'plan').exists())

class DetectorCoarseBuilderTests(unittest.TestCase):
    def test_builder_accepts_coarse_grid_without_resizing_body_or_marker(self):
        import subprocess
        from msplatform.backends.simion.source import lua_value
        from msplatform.backends.simion.resources import native_resource_path
        marker = dict(cell_xy_mm=.5, cell_z_mm=.025, active_radius_mm=40.,
                      absorber_thickness_mm=.1, front_margin_z_mm=.25,
                      back_margin_z_mm=.125, capture_depth_mm=.02)
        body = dict(radius_mm=40., height_mm=1., back_cells=45, front_cells=10)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gem = root / "source.gem"
            gem.write_text("inert source\n", encoding="utf-8")
            projection = root / "projection.lua"
            projection.write_text("return " + lua_value(dict(
                physical_geometry=dict(simion=dict(detector_marker=marker, detector_body=body)),
                simion_geometry_build=dict(detector=dict(margin_xy_mm=1., max_mib=128.)))) + "\n", encoding="utf-8")
            builder = native_resource_path("build_detector_variant.lua")
            import json
            argv = [str(gem), str(root / "raw.pa#"), str(projection), "geometry-only"]
            script = root / "run.lua"
            script.write_text("arg={" + ",".join(json.dumps(s) for s in argv) + "}\n" +
                "simion={command=function(_) assert(var.absorber_thickness==1); assert(var.back_cells==45); assert(var.front_cells==10); print('COARSE_PHYSICAL=PASS') end}\n" +
                "dofile(" + json.dumps(str(builder)) + ")\n", encoding="utf-8")
            result = subprocess.run([LUA, str(script)], cwd=root, capture_output=True,
                                    text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("COARSE_PHYSICAL=PASS", result.stdout)
            self.assertIn("BUILD_GEOMETRY=PASS ROLE=detector", result.stdout)
            self.assertFalse((root / "raw.pa#").exists())


class DetectorResourceTests(unittest.TestCase):
    def test_frozen_resource_missing_and_same_length_tamper_refuse(self):
        from msplatform.backends.simion.resources import gem_template_path
        from msplatform.io.manifest_records import file_record, verify_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(FileNotFoundError, 'frozen SIMION GEM resource is missing'):
                gem_template_path('detector', source_root=root)
            frozen = root / 'src/msplatform/backends/simion/resources/oatof_detector_ground.gem'
            frozen.parent.mkdir(parents=True)
            frozen.write_bytes(gem_template_path('detector').read_bytes())
            record = file_record(frozen)
            self.assertEqual(gem_template_path('detector', source_root=root), frozen)
            verify_record('detector GEM', record)
            content = frozen.read_bytes()
            frozen.write_bytes(bytes([content[0] ^ 1]) + content[1:])
            with self.assertRaisesRegex(AssertionError, 'SHA-256 changed'):
                verify_record('detector GEM', record)
            frozen.unlink()
            with self.assertRaisesRegex(AssertionError, 'is missing'):
                verify_record('detector GEM', record)
