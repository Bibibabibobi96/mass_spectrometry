"""Real resolved inputs exercise the provider and actual native GEM templates.

Plain Lua expands the GEM preprocessor expressions; no PA or solver is created.
Explicit native-region vectors preserve the former renderer's boundary problem.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    PROJECT_ROOT, resolve_contract, resolve_physical_geometry,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import lua_value, render_resolved_lua

LUA = Path("C:/Program Files/SIMION-2020/lua.exe")


def nondefault_resolved():
    resolved = resolve_contract()
    resolved["geometry_mm"].update(flight_tube_r=400., flight_tube_wall=12.,
        shield_outer_z_min=-60., L_flight=700., L_reflectron=70., L_stage1=30., L_stage2=40.,
        bore_r=260., ring_outer_r=310., ring_thickness=2., shield_axial_gap=50., shield_endcap_thickness=10.)
    resolved["rings"].update(stage1_count=2, stage2_count=3)
    resolved["electrodes_V"].update(midgrid=1500., backplate=2500.)
    return resolved


def expand_gem(source: str) -> str:
    """Translate actual GEM preprocessing lines to a plain-Lua print program."""
    program = []
    for line in source.splitlines():
        if line.startswith("#"):
            program.append(line[1:].lstrip())
        else:
            parts, previous = [], 0
            for match in re.finditer(r"\$\(([^)]+)\)", line):
                parts += [json.dumps(line[previous:match.start()]), "tostring(" + match[1] + ")"]
                previous = match.end()
            parts.append(json.dumps(line[previous:] + "\n"))
            program.append("io.write(" + " .. ".join(parts) + ")")
    return "\n".join(program)


class PhysicalGeometryTests(unittest.TestCase):
    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_three_builders_reject_incomplete_inputs_before_native_operations(self):
        builders = (
            "reflectron/build_reflectron_variant.lua",
            "workbench/build_flight_tube_variant.lua",
            "workbench/build_detector_variant.lua",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "invalid.pa#"
            for relative in builders:
                with self.subTest(builder=relative):
                    result = subprocess.run(
                        [str(LUA), str(PROJECT_ROOT / "simion" / relative),
                         str(Path(directory) / "source.gem"), str(output)],
                        cwd=directory, capture_output=True, text=True, encoding="utf-8",
                        timeout=20, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing frozen resolved Lua", result.stderr)
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_real_complete_objects_keep_enclosure_fragments_and_detector_models_distinct(self):
        resolved = resolve_contract()
        before = copy.deepcopy(resolved)
        physical = resolve_physical_geometry(resolved)
        objects = {item["role"]: item for item in physical["electrodes"]}
        self.assertEqual(objects["accelerator_side_shield"]["component_electrode_id"], 1)
        shield = objects["flight_tube_shield"]["component_electrode_id"]
        tube, mirror = physical["simion"]["flight_tube"], physical["simion"]["reflectron"]
        self.assertEqual(tube["electrodes"][0]["component_electrode_id"], shield)
        self.assertEqual(mirror["electrodes"][-1]["component_electrode_id"], shield)
        self.assertNotEqual(mirror["electrodes"][0]["component_electrode_id"], shield)
        self.assertEqual(mirror["electrodes"][0]["local_electrode_id"], 1)
        self.assertEqual(tube["electrodes"][0]["local_electrode_id"], 1)
        detector = objects["detector"]["geometry"]
        self.assertEqual(detector, dict(primitive="cylinder", radius_mm=40.,
            base_center_mm=[48.8, 0, -1.], height_mm=1., axis=[0, 0, 1]))
        self.assertEqual(physical["simion"]["detector_marker"]["absorber_thickness_mm"], .1)
        self.assertFalse(any("marker" in item["role"] for item in objects.values()))
        resolved["particle_source"]["center_z_mm"] += 1
        self.assertEqual(resolve_physical_geometry(resolved), physical)
        self.assertNotIn("physical_geometry", before)
        resolved["particle_source"]["center_z_mm"] -= 1
        self.assertEqual(resolved, before)

    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_real_nondefault_templates_render_explicit_native_boundary_vectors(self):
        resolved = nondefault_resolved()
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "resolved.lua"
            snapshot.write_text(render_resolved_lua(resolved), encoding="utf-8")
            actual = {}
            for role, relative in (("flight_tube", "workbench/oatof_flight_tube_ground.gem"),
                                    ("reflectron", "reflectron/oatof_reflectron_ideal_10_5.gem")):
                source = (PROJECT_ROOT / "simion" / relative).read_text()
                mesh = resolved["simion_geometry_build"][role]
                prefix = ("local contract=dofile(" + json.dumps(str(snapshot)) + ")\n"
                    "_G.var={component=contract.physical_geometry.simion." + role + ",mmgu_axial="
                    + str(mesh["cell_axial_mm"]) + ",mmgu_radial=" + str(mesh["cell_radial_mm"]) + "}\n")
                script = Path(directory) / (role + ".lua")
                script.write_text(prefix + expand_gem(source), encoding="utf-8")
                result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True,
                    encoding="utf-8", cwd=directory, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                native, electrode = [], None
                for line in result.stdout.splitlines():
                    match = re.search(r"e\((\d+)\)", line)
                    if match:
                        electrode = int(match[1])
                    match = re.search(r"box\(([^)]+)\)", line)
                    if match:
                        native.append((electrode, *map(float, match[1].split(","))))
                actual[role] = native
            self.assertEqual(actual["flight_tube"], [(1, 0., 0., 10., 412.), (1, 10., 400., 760., 412.)])
            self.assertEqual(actual["reflectron"], [
                (1, 0., 0., 0., 400.), (2, 9., 260., 11., 310.), (3, 19., 260., 21., 310.),
                (4, 30., 0., 30., 310.), (5, 39., 260., 41., 310.), (6, 49., 260., 51., 310.),
                (7, 59., 260., 61., 310.), (8, 70., 0., 72., 310.),
                (9, 0., 400., 122., 412.), (9, 122., 0., 132., 412.)])

    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_actual_reflectron_fast_adjust_consumes_frozen_projection(self):
        for resolved in (resolve_contract(), nondefault_resolved()):
            for long_output in (False, True):
                with self.subTest(rings=resolved["rings"], long_output=long_output), tempfile.TemporaryDirectory() as directory:
                    self.check_fast_adjust(resolved, Path(directory), long_output=long_output)

    def check_fast_adjust(self, resolved, directory, *, long_output=False):
        with self.subTest(directory=directory):
            snapshot = Path(directory) / "resolved.lua"
            snapshot.write_text(render_resolved_lua(resolved), encoding="utf-8")
            builder = PROJECT_ROOT / "simion/reflectron/build_reflectron_variant.lua"
            script = Path(directory) / "drive.lua"
            output = directory.joinpath(*(["long directory with spaces"] * 12), "reflectron.pa#") if long_output else directory / "reflectron.pa#"
            argv = [str(PROJECT_ROOT / "simion/reflectron/oatof_reflectron_ideal_10_5.gem"),
                    str(output), str(snapshot), "adjust-only"]
            controller = str(output).removesuffix("#") + "0"
            script.write_text("arg={" + ",".join(map(json.dumps, argv)) + "}\n"
                "expected=" + json.dumps(controller) + "\n" + r'''
local calls={}
local pa={}
function pa:fast_adjust(values)
 calls[#calls+1]='fast_adjust'
 for id,value in pairs(values) do print(string.format('VOLTAGE=%d,%.17g',id,value)) end
end
function pa:save(path) assert(path==expected);calls[#calls+1]='save';print('API_SAVE='..path) end
function pa:close() calls[#calls+1]='close' end
simion={command=function() error('Fast Adjust must not use a command string') end,
 pas={close=function() calls[#calls+1]='pas_close' end,
      open=function(_,path) assert(path==expected);calls[#calls+1]='open';return pa end}}
''' + "dofile(" + json.dumps(str(builder)) + ")\n"
                "assert(table.concat(calls,',')=='pas_close,open,fast_adjust,save,close')\n",
                encoding="utf-8")
            result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True,
                encoding="utf-8", cwd=directory, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = {int(key): float(value) for line in result.stdout.splitlines() if line.startswith("VOLTAGE=")
                      for key, value in [line.removeprefix("VOLTAGE=").split(",")]}
            self.assertIn("API_SAVE=" + controller, result.stdout)
            if long_output:
                self.assertGreater(len(controller), 260)
                self.assertIn(" ", controller)
            expected = {item["local_electrode_id"]: item["voltage_v"]
                        for item in resolve_physical_geometry(resolved)["simion"]["reflectron"]["electrodes"]}
            self.assertEqual(actual, expected)
            if resolved["rings"]["stage1_count"] == 10:
                # Actual pre-extraction Formal PS double, not an integer divider fixture.
                self.assertEqual(actual[8], 1036.5091545454545)
            self.assertNotIn("refine ", result.stdout)
            self.assertNotIn("gem2pa ", result.stdout)
            self.assertIn("BUILD: PASS", result.stdout)

    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_current_frozen_native_gem_regions_and_grids_remain_identical(self):
        frozen = (PROJECT_ROOT.parents[2] / "artifacts/projects/instrument_assembly/runs/"
            "20261025_110745__sim__simion__single-reflection-flight/inputs")
        if not frozen.is_dir():
            self.skipTest("explicit historical source snapshot is unavailable")
        plan = json.loads((frozen / "downstream_field_source_command_plan.json").read_text())
        source = frozen / "components/oatof/resolved_design.json"
        payload = source.read_bytes()
        record = plan["oatof_resolved_record"]
        self.assertEqual((len(payload), hashlib.sha256(payload).hexdigest().upper()), (record["bytes"], record["sha256"]))
        resolved = json.loads(payload)
        physical = resolve_physical_geometry(resolved)
        parameters = {
            "flight_tube": "mmgu_axial mmgu_radial max_gib inner_radius wall near_cap_thickness near_outer_z reflectron_interface_z",
            "detector": "mmgu_xy mmgu_z radius absorber_thickness front_margin_z back_margin_z margin_xy max_mib",
            "reflectron": "mmgu_axial mmgu_radial max_gib inner_radius wall backplate_front backplate_thickness far_clearance far_cap_thickness stage1_length stage2_length bore_radius ring_outer_radius stage1_ring_count stage2_ring_count midgrid_voltage backplate_voltage",
        }
        resources = {"flight_tube": "tube_gem", "detector": "detector_gem", "reflectron": "reflectron_gem"}
        with tempfile.TemporaryDirectory() as directory:
            for step in plan["steps"][:3]:
                role = step["name"]
                key = resources[role]
                record = plan["resource_records"][key]
                relative = record["path"].replace("\\", "/").split("/simion/", 1)[1]
                old_path = frozen / "runtime_snapshot/projects/single_reflection_oa_tof_mass_analyzer/simion" / relative
                old_payload = old_path.read_bytes()
                self.assertEqual((len(old_payload), hashlib.sha256(old_payload).hexdigest().upper()),
                                 (record["bytes"], record["sha256"]))
                old_vars = dict(zip(parameters[role].split(), map(float, step["argv"][6:6+len(parameters[role].split())]), strict=True))
                new_vars = (old_vars if role == "detector" else dict(component=physical["simion"][role],
                    mmgu_axial=old_vars["mmgu_axial"], mmgu_radial=old_vars["mmgu_radial"]))
                outputs = []
                for label, template, variables in (("old", old_payload.decode(), old_vars),
                    ("new", (PROJECT_ROOT / "simion" / relative).read_text(), new_vars)):
                    script = Path(directory) / (label + ".lua")
                    script.write_text("_G.var=" + lua_value(variables) + "\n" + expand_gem(template), encoding="utf-8")
                    result = subprocess.run([str(LUA), str(script)], capture_output=True, text=True,
                        encoding="utf-8", cwd=directory, timeout=30, check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    grid = re.search(r"pa_define\((.*?)\)", result.stdout, re.S)[1]
                    signatures, eid = [], None
                    for line in result.stdout.splitlines():
                        match = re.search(r"e\((\d+)\)", line)
                        if match:
                            eid = int(match[1])
                        for primitive, arguments in re.findall(r"(box|cylinder|locate)\(([^)]+)\)", line):
                            signatures.append((eid, primitive, tuple(float(x) if x.strip() else None for x in arguments.split(","))))
                    outputs.append((re.sub(r"\s+", "", grid), signatures))
                self.assertEqual(outputs[0], outputs[1], role)

    def test_invalid_physical_dimensions_fail_before_transport(self):
        for field, value in (("ring_thickness", 0), ("detector_thickness", -1), ("L_stage1", float("nan"))):
            with self.subTest(field=field):
                resolved = resolve_contract()
                resolved["geometry_mm"][field] = value
                with self.assertRaises(ValueError):
                    render_resolved_lua(resolved)
