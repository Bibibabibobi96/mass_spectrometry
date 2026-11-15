"""Two registered providers, real model drive Lua, no native solver."""

import copy
import os
import shutil
import pathlib
import subprocess
import tempfile
import unittest
from common.contracts.test_support import (
    registered_component as toy,
    generic_other_provider,
)
from msplatform import assembly, components
from msplatform.backends.simion.operations import compile_geometry
from msplatform.backends.simion.model import (
    compile_prepared_model,
    render_model_configuration,
    RF_PHYSICS,
)
from msplatform.backends.simion.resources import native_resource_path


class DynamicWorldTests(unittest.TestCase):
    def setUp(self):
        toy.ensure_registered()
        generic_other_provider.ensure_registered()

    def model(self, rename=False):
        names = ("z", "a") if rename else ("first", "second")
        a = components.resolve_component(
            {"provider_id": "toy_registered", "design": {"width_mm": 2}}
        )
        b = components.resolve_component(
            {"provider_id": "toy_other", "design": {"width_mm": 3}}
        )

        def pose(x):
            return dict(
                schema_version=1,
                role="rigid_transform",
                from_frame_id="toy_local",
                to_frame_id="world",
                rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                translation_mm=[x, 0, 0],
            )

        rows = [
            dict(instance_id=names[0], project_id="toy_registered", transform=pose(0)),
            dict(instance_id=names[1], project_id="toy_other", transform=pose(10)),
        ]
        if rename:
            rows.reverse()
        recipe = dict(
            schema_version=1,
            role="assembly_recipe",
            integration_id="toy_integration",
            recipe_id="toy_recipe",
            assembly_frame_id="world",
            position_tolerance_mm=1e-6,
            angular_tolerance_rad=1e-6,
            instances=rows,
            connections=[],
        )
        obj = assembly.assemble(recipe, {names[0]: a, names[1]: b})
        numerics = dict(
            representation="neutral_world_collision",
            domain=dict(
                frame_id="world", minimum_mm=[-5, -5, -5], maximum_mm=[20, 5, 5]
            ),
            pitch_mm=1,
            boundary="native_zero_neumann",
            metal_witnesses=[
                dict(instance_id=names[0], electrode_group_id="body", gu=[5, 5, 5]),
                dict(instance_id=names[1], electrode_group_id="body", gu=[15, 5, 5]),
            ],
            void_witnesses=[[0, 0, 0]],
        )
        geometry = compile_geometry(obj, numerics=numerics)
        drive = dict(
            clock=dict(
                clock_epoch_id="test",
                authority_sha256="0" * 64,
                phase_reference_instrument_time_us=0,
            ),
            pulse=dict(mode="timed", time_us=0.2, width_us=0.5),
            groups={
                names[0]: {
                    "body": dict(
                        kind="rf",
                        waveform="sine",
                        frequency_hz=1e6,
                        phase_rad=0.0,
                        rf_amplitude_v=3.0,
                        polarity=1,
                        common_mode_v=2.0,
                        dc_v=0.0,
                    )
                },
                names[1]: {
                    "body": dict(kind="pulse", off_voltage_v=-2.0, on_voltage_v=5.0)
                },
            },
        )
        return (
            compile_prepared_model(
                geometry, obj.components_resolved, drive=drive, physics=RF_PHYSICS
            ),
            geometry,
            obj,
            drive,
            names,
        )

    def test_drive_actual_lua_and_reordered_names(self):
        lua = os.environ.get("SIMION_LUA_EXE") or shutil.which("lua") or shutil.which("lua5.1")
        if not lua:
            raise FileNotFoundError("required standalone Lua executable unavailable")
        for rename in (False, True):
            model, _, _, _, names = self.model(rename)
            with tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                (root / "config.lua").write_text(
                    render_model_configuration(model), encoding="utf8"
                )
                resources = {
                    n: str(native_resource_path(n)).replace("\\", "/")
                    for n in (
                        "model_drive.lua",
                        "rf_drive.lua",
                        "single_flight_pulse_hook.lua",
                        "voltage_waveforms.lua",
                    )
                }
                script = (
                    "local c=dofile(arg[1]);local model=dofile("
                    + repr(resources["model_drive.lua"])
                    + ");local rf=dofile("
                    + repr(resources["rf_drive.lua"])
                    + ");local p=dofile("
                    + repr(resources["single_flight_pulse_hook.lua"])
                    + ");local w=dofile("
                    + repr(resources["voltage_waveforms.lua"])
                    + ");local x=model.new(c,rf,p,w);for _,t in ipairs({0,.25,.75}) do for _,r in ipairs(x.evaluate_at(t)) do print(t,r.instance_id,r.voltage_v) end end"
                )
                script_path = root / "evaluate.lua"
                script_path.write_text(script, encoding="utf8")
                result = subprocess.run(
                    [lua, str(script_path), str(root / "config.lua")],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = [line.split() for line in result.stdout.splitlines()]
                actual = {(float(t), name): float(v) for t, name, v in rows}
                for t, rf, pulse in [(0, 2, -2), (0.25, 5, 5), (0.75, -1, -2)]:
                    self.assertAlmostEqual(actual[(t, names[0])], rf, places=10)
                    self.assertEqual(actual[(t, names[1])], pulse)

    def test_missing_group_clock_unsupported_and_field_guard(self):
        model, geometry, obj, drive, _ = self.model()
        for mutate in ("group", "clock", "kind"):
            bad = copy.deepcopy(drive)
            if mutate == "group":
                bad["groups"].pop("first")
            elif mutate == "clock":
                bad["clock"]["phase_reference_instrument_time_us"] = 1.0
            else:
                bad["groups"]["first"]["body"]["kind"] = "unknown"
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                compile_prepared_model(
                    geometry, obj.components_resolved, drive=bad, physics=RF_PHYSICS
                )
        from msplatform.backends.simion.field_execution import plan_fields_execution

        with self.assertRaisesRegex(ValueError, "separately admitted scalar basis"):
            plan_fields_execution(model, numerics={"refine_policy": "vendor_default"})
