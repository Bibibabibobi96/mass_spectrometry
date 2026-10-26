"""Pure contract/dispatch tests for a native collision regression fixture.

Plain Lua stubs exercise preparation and launch boundaries, never SIMION.
Native collision outcomes are deliberately not predeclared by these tests.
"""
from __future__ import annotations

import copy
import csv
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_distance_study import lua_literal


FIXTURE = Path(__file__).resolve().parents[1] / "simion/test_ip_prism_collision_fixture.lua"
LUA = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"


def fixture_context(root: Path) -> dict:
    """Explicit small-fixture author data; no production defaults or run IDs."""
    output = root / "fixture"
    fields = []
    for ordinal, (kind, pitch) in enumerate(
        [("rod", .1), ("rod", .05), ("rod", .02), ("solid_block", .1), ("vacuum", .1)], 1
    ):
        field = dict(field_id=f"field_{ordinal:02d}", directory=(output / f"field_{ordinal:02d}").as_posix(),
                     kind=kind, pitch_mm=[pitch]*3, box_mm=[0, -54, -32, 1, -52.5, -28], voltage_v=0)
        if kind == "rod":
            field.update(center_mm=[0, -53.4, -30], radius_mm=.2, length_mm=3)
        elif kind == "solid_block":
            field["block_box_mm"] = [0, -53.9, -31.5, .5, -52.9, -28.5]
        fields.append(field)
    paths = [dict(particle_id=i, label=label, position_mm=position, mass_amu=524,
                  charge_state=1, ke_ev=4350, time_us=0) for i, (label, position) in enumerate([
        ("center", [.05, -53.4, -28.2]),
        ("id3_like_grazing", [.012733738608599223, -53.57018313032381, -28.2]),
        ("outside", [.012733738608599223, -53.7, -28.2]),
    ], 1)]
    cases = [dict(case_id=f"case_{i:02d}", directory=(output / f"case_{i:02d}").as_posix(),
                  field_id=fields[(i-1)//2]["field_id"], program_mode=mode)
             for i, mode in enumerate(["off", "logging_only"]*5, 1)]
    return dict(schema_version=1, role="mrtof_native_collision_fixture", output_directory=output.as_posix(),
                private_iob=(root/"private/local.iob").as_posix(), private_pa=(root/"private/field.pa").as_posix(),
                seed_iob=(root/"seed.iob").as_posix(), production_driver=(root/"production_driver.lua").as_posix(),
                recording_path=(root/"official_tof.rec").as_posix(),
                fields=fields, cases=cases, paths=paths, trajectory_quality=8, stop_z_mm=-31.8,
                nominal_y_mm=-53.4,
                probe_points=[dict(name="actual_id3", position_mm=[.012733738608599223, -53.57018313032381, -31.426238625456513])],
                paths_for_query=[dict(name=p["label"], position_mm=[*p["position_mm"][:2], -30]) for p in paths])


@unittest.skipUnless(Path(LUA).is_file(), "Plain Lua required; never launches SIMION")
class CollisionFixtureTests(unittest.TestCase):
    def invoke(self, context: dict, stage="validate", ordinal=None, harness=""):
        root = Path(context["output_directory"]).parent
        config = root / "context.lua"
        config.write_text("return " + lua_literal(context) + "\n", encoding="utf-8")
        entry = FIXTURE
        arguments = [str(config), stage] + ([] if ordinal is None else [str(ordinal)])
        if harness:
            entry = root/"harness.lua"
            entry.write_text(harness + "\nassert(loadfile(" + lua_literal(FIXTURE.as_posix()) + "))()\n", encoding="utf-8")
        return subprocess.run([LUA, str(entry), *arguments], capture_output=True, text=True, check=False, cwd=root, timeout=30)

    def test_explicit_matrix_validates_without_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.invoke(fixture_context(Path(tmp)))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS cases=10", result.stdout)

    def test_invalid_contexts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = fixture_context(Path(tmp))
            bad = []
            c = copy.deepcopy(original); c["fields"][0]["voltage_v"] = 1; bad.append(c)
            c = copy.deepcopy(original); c["cases"][1]["directory"] = c["cases"][0]["directory"]; bad.append(c)
            c = copy.deepcopy(original); c["cases"][0]["field_id"] = "absent"; bad.append(c)
            c = copy.deepcopy(original); c["fields"][0]["directory"] = "C:/outside"; bad.append(c)
            c = copy.deepcopy(original); c["fields"][0]["pitch_mm"] = [.13]*3; bad.append(c)
            c = copy.deepcopy(original); c["paths"][0]["position_mm"][2] = -40; bad.append(c)
            c = copy.deepcopy(original); c["cases"][0]["program_mode"] = "override_collision"; bad.append(c)
            for context in bad:
                with self.subTest(context=context):
                    self.assertNotEqual(self.invoke(context).returncode, 0)

    def test_fly_ordinal_dispatches_only_one_case_no_refine(self):
        harness = r'''
simion={command=function(command)
 assert(command:match('^fly '),'unexpected vendor operation')
 print('STUB_COMMAND '..command)
end}
'''
        with tempfile.TemporaryDirectory() as tmp:
            context = fixture_context(Path(tmp))
            for ordinal, mode in [(1, 0), (2, 1), (10, 1)]:
                result = self.invoke(context, "fly", ordinal, harness)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count("STUB_COMMAND"), 1)
                self.assertIn(f"--programs={mode}", result.stdout)
                self.assertIn(f"case_{ordinal:02d}/local.iob", result.stdout)
                self.assertIn("--trajectory-quality=8", result.stdout)
                self.assertNotIn("refine", result.stdout.lower())
            self.assertNotEqual(self.invoke(context, "fly", 11, harness).returncode, 0)
            self.assertNotEqual(self.invoke(context, "fly", 1.5, harness).returncode, 0)

    def test_prepare_uses_zero_gem_and_assemble_only(self):
        harness = r'''
local c=assert(loadfile(arg[1]))()
local commands,reads=0,0
local pa={}
function pa:potential(...) reads=reads+1;return 0 end
function pa:electrode(...) return false end
function pa:save(path) local f=assert(io.open(path,'wb'));f:write('STUB PA');f:close() end
function pa:close() end
local instance={pa=pa}
function instance:wb_to_pa_coords(x,y,z) return x*10,(y+54)*10,(z+32)*10 end
function instance:pa_to_array_coords(x,y,z) return math.abs(x),y,z end
function instance:pa_to_wb_coords(x,y,z) return x*.1,y*.1-54,z*.1-32 end
simion={pas={},wb={instances={instance}}}
function simion.wb:find_at(...) return false,1 end
function simion.pas:close() end
function simion.pas:open(_) return pa end
function simion.command(command)
 assert(command:match('^gem2pa '),'prepare must not Fly/Refine')
 commands=commands+1
end
local driver=assert(io.open(c.production_driver,'wb'))
driver:write([[assert((...)=='assemble','production driver must assemble only'); print('STUB_ASSEMBLE')]])
driver:close()
'''
        with tempfile.TemporaryDirectory() as tmp:
            context = fixture_context(Path(tmp))
            for item in context["fields"] + context["cases"]:
                Path(item["directory"]).mkdir(parents=True)
            result = self.invoke(context, "prepare", harness=harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("STUB_ASSEMBLE"), 10)
            self.assertIn("refine=0 fly=0", result.stdout)
            for field in context["fields"]:
                gem = (Path(field["directory"])/"field.gem").read_text()
                self.assertIn("surface=fractional", gem)
                self.assertEqual("cylinder3d(" in gem, field["kind"] == "rod")
            for case in context["cases"]:
                program = (Path(case["directory"])/"local.lua").read_text()
                self.assertNotIn("ion_splat=", program)
                self.assertNotIn("ion_time_step=", program)
                self.assertNotIn("ion_px_mm=", program)
                self.assertNotIn("efield_adjust", program)
                self.assertEqual((Path(case["directory"])/"local.fly2").read_text().count("standard_beam"), 3)

    def test_actual_query_uses_selected_instance_conversion_and_eight_corners(self):
        harness = r'''
local c=assert(loadfile(arg[1]))()
local pa={path=c.private_pa}
function pa:electrode(x,y,z) return x==0 end
function pa:potential(...) return 0 end
local instance={pa=pa}
function instance:wb_to_pa_coords(x,y,z) return x*10,(y+105)*10,(z+120)*10 end
function instance:pa_to_array_coords(x,y,z) return math.abs(x),y,z end
function instance:pa_to_wb_coords(x,y,z) return x*.1,y*.1-105,z*.1-120 end
simion={pas={},wb={instances={instance}}}
function simion.pas:close() end
function simion.wb:load(path) assert(path==c.private_iob) end
function simion.wb:find_at(x,y,z) return false,1 end
'''
        with tempfile.TemporaryDirectory() as tmp:
            context = fixture_context(Path(tmp))
            Path(context["output_directory"]).mkdir()
            context["probe_points"].append(dict(name="mirror", position_mm=[-.012733738608599223, -53.57018313032381, -31.426238625456513]))
            result = self.invoke(context, "query", harness=harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            with (Path(context["output_directory"])/"actual_points.csv").open(newline="") as stream:
                points = list(csv.DictReader(stream))
            with (Path(context["output_directory"])/"actual_corners.csv").open(newline="") as stream:
                corners = list(csv.DictReader(stream))
            self.assertEqual(len(corners), 16)
            self.assertLess(float(points[1]["pa_x_gu"]), 0)
            self.assertGreater(float(points[1]["array_x_gu"]), 0)
            self.assertAlmostEqual(float(points[1]["world_x_mm"]), float(points[1]["roundtrip_x_mm"]), 14)
            self.assertEqual({int(r["ix"]) for r in corners}, {0, 1})
            self.assertEqual({int(r["iy"]) for r in corners}, {514, 515})
            self.assertEqual({int(r["iz"]) for r in corners}, {885, 886})
            self.assertEqual(sum(int(r["electrode"]) for r in corners), 8)
            broken = harness.replace("path=c.private_pa", "path='published/wrong.pa'")
            self.assertNotEqual(self.invoke(context, "query", harness=broken).returncode, 0)


if __name__ == "__main__":
    unittest.main()
