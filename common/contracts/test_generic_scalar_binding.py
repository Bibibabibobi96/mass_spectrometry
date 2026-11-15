"""Generic linear sample admission with registered toy components and inert products."""

import copy
import tempfile
import unittest
from pathlib import Path
from common.contracts import test_static_world_model as toy_fixture
from common.contracts import test_sfi_scalar_binding as fixtures
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.simion.generic_scalar_binding import (
    compile_linear_terms,
    admit_linear_samples,
)
from common.contracts.test_support import generic_other_provider
from msplatform import assembly, components


class GenericScalarTests(unittest.TestCase):
    def setUp(self):
        parent = toy_fixture.StaticWorldModelTests(methodName="runTest")
        parent.setUp()
        generic_other_provider.ensure_registered()
        recipe = copy.deepcopy(parent.assembly.composition_plan["recipe"])
        recipe["instances"][1]["project_id"] = "toy_other"
        first = components.resolve_component(
            {"provider_id": "toy_registered", "design": {"width_mm": 2}}
        )
        second = components.resolve_component(
            {"provider_id": "toy_other", "design": {"width_mm": 3}}
        )
        self.assembly = assembly.assemble(recipe, {"first": first, "second": second})
        self.snapshot = dict(
            composition_plan=self.assembly.composition_plan,
            components_resolved=self.assembly.components_resolved,
            components_source=self.assembly.components_source,
        )
        self.projection = project_assembly_geometry(
            self.snapshot, outer_box_mm={"min": [-100] * 3, "max": [100] * 3}
        )
        self.operator = dict(
            relative_permittivity=1.0,
            exterior={"kind": "potential", "voltage_v": 0.0},
            mesh={"global_automatic_level": 9, "electrode_hmax_mm": 5.0},
            study={"kind": "stationary"},
        )
        self.drive = dict(
            clock=dict(
                clock_epoch_id="instrument_clock_epoch_v1",
                authority_sha256="6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0",
                phase_reference_instrument_time_us=0.0,
            ),
            pulse=dict(mode="timed", time_us=0.2, width_us=0.5),
            groups={
                "first": {
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
                "second": {
                    "body": dict(kind="pulse", off_voltage_v=-2.0, on_voltage_v=5.0)
                },
            },
        )
        from msplatform.backends.simion.operations import compile_geometry
        from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS

        numerics = dict(
            representation="neutral_world_collision",
            domain=dict(
                frame_id="world", minimum_mm=[-5, -5, -5], maximum_mm=[20, 5, 5]
            ),
            pitch_mm=1,
            boundary="native_zero_neumann",
            metal_witnesses=[
                dict(instance_id="first", electrode_group_id="body", gu=[5, 5, 5]),
                dict(instance_id="second", electrode_group_id="body", gu=[15, 5, 5]),
            ],
            void_witnesses=[[0, 0, 0]],
        )
        compiled = compile_geometry(self.assembly, numerics=numerics)
        self.model = compile_prepared_model(
            compiled,
            self.assembly.components_resolved,
            drive=self.drive,
            physics=RF_PHYSICS,
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = fixtures.SfiScalarAdmissionTests(methodName="runTest")
        self.fixture.root = Path(self.temp.name)
        self.fixture.projection = self.projection
        self.fixture.snapshot = self.snapshot
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        from importlib.resources import files
        import json, shutil

        root = self.fixture.root / "model"
        root.mkdir()
        clock = root / "clock"
        clock.mkdir()
        for name in ("instrument_clock_authority_v1.json", "instrument_epoch_v1.json"):
            shutil.copyfile(files("msplatform.examples").joinpath(name), clock / name)
        paths = {
            "compiled_model": root / "model.json",
            "clock_authority": clock / "instrument_clock_authority_v1.json",
            "instrument_epoch": clock / "instrument_epoch_v1.json",
            "raw_geometry": root / "raw.pa#",
            "fractional_surface": root / "raw.pa-surf",
            "surface_witnesses": root / "witness.csv",
        }
        paths["compiled_model"].write_text(
            json.dumps(self.model.document), encoding="utf8"
        )
        for key in ("raw_geometry", "fractional_surface", "surface_witnesses"):
            paths[key].write_bytes(b"inert")
        records = {key: file_record(path) for key, path in paths.items()}
        metadata = dict(
            backend="simion",
            drive_configured=True,
            geometry_materialized=True,
            field_status="not_solved",
            source_status="not_requested",
            native_assets={
                "world": {
                    "raw_geometry": "raw_geometry",
                    "fractional_surface": "fractional_surface",
                    "surface_witnesses": "surface_witnesses",
                }
            },
        )
        manifest = dict(
            schema_version=2,
            role="simulation_run_manifest",
            run_id="model",
            project="instrument_assembly",
            mode="prepared_model",
            status="success",
            inputs={},
            outputs=list(records.values()),
            products={
                "model": dict(
                    schema_version=1,
                    kind="prepared_model",
                    status="complete",
                    metadata=metadata,
                    data=records,
                )
            },
        )
        publish_terminal_state(root, {"status": "success"}, manifest)
        self.model_reference = {
            "manifest": file_record(root / "run_manifest.json"),
            "product_id": "model",
        }
        self.geometry = self.fixture.make_geometry()
        self.samples = {}
        for name, vector, coeff in [
            (
                "one",
                {("first", "body"): 1.0, ("second", "body"): 0.0},
                [
                    dict(instance_id="first", electrode_group_id="body", weight=1.0),
                    dict(instance_id="second", electrode_group_id="body", weight=0.0),
                ],
            ),
            (
                "two",
                {("first", "body"): 0.0, ("second", "body"): 1.0},
                [
                    dict(instance_id="first", electrode_group_id="body", weight=0.0),
                    dict(instance_id="second", electrode_group_id="body", weight=1.0),
                ],
            ),
        ]:
            self.fixture.vectors = {name: vector}
            ref = self.fixture.make_sample(name)
            from msplatform.results.artifacts import open_artifact

            request = __import__("json").loads(
                open_artifact(ref, expected_kind="scalar_field_samples")
                .data_path("request")
                .read_text(encoding="utf8")
            )
            self.samples[name] = dict(reference=ref, request=request, weights=coeff)

    def test_published_products_span_and_refuse_missing(self):
        before = copy.deepcopy(self.samples)
        result = admit_linear_samples(
            assembly=self.assembly,
            geometry_artifact=self.geometry,
            operator=self.operator,
            model_reference=self.model_reference,
            samples=self.samples,
        )
        self.assertEqual(result["terms"]["terms"], ["carrier", "pulse", "rf_0"])
        self.assertEqual(set(result["bases"]), {"one", "two"})
        self.assertEqual(before, self.samples)
        bad = copy.deepcopy(self.samples)
        bad["two"]["weights"][1]["weight"] = 0.8
        with self.assertRaisesRegex(ValueError, "span"):
            admit_linear_samples(
                assembly=self.assembly,
                geometry_artifact=self.geometry,
                operator=self.operator,
                model_reference=self.model_reference,
                samples=bad,
            )
        missing = dict(self.samples)
        missing.pop("one")
        with self.assertRaisesRegex(ValueError, "span"):
            admit_linear_samples(
                assembly=self.assembly,
                geometry_artifact=self.geometry,
                operator=self.operator,
                model_reference=self.model_reference,
                samples=missing,
            )

    def test_rename_and_reorder_keyed_vectors(self):
        rename = {"first": "z", "second": "a"}
        recipe = copy.deepcopy(self.assembly.composition_plan["recipe"])
        for instance in recipe["instances"]:
            instance["instance_id"] = rename[instance["instance_id"]]
        recipe["instances"].reverse()
        renamed = assembly.assemble(
            recipe,
            {rename[name]: part for name, part in self.assembly.components.items()},
        )
        snapshot = dict(
            composition_plan=renamed.composition_plan,
            components_resolved=renamed.components_resolved,
            components_source=renamed.components_source,
        )
        p = project_assembly_geometry(
            snapshot, outer_box_mm={"min": [-100] * 3, "max": [100] * 3}
        )
        drive = copy.deepcopy(self.drive)
        drive["groups"] = {
            rename[k]: v for k, v in reversed(list(drive["groups"].items()))
        }
        samples = copy.deepcopy(self.samples)
        for row in samples.values():
            for voltage in row["request"]["group_voltages"]:
                voltage["instance_id"] = rename[voltage["instance_id"]]
            for weight in row["weights"]:
                weight["instance_id"] = rename[weight["instance_id"]]
            row["weights"].reverse()
            row["request"]["group_voltages"].reverse()
            row["request"] = validate_request(p, row["request"])
        result = compile_linear_terms(
            p,
            drive,
            {
                n: {"request": v["request"], "weights": v["weights"]}
                for n, v in samples.items()
            },
        )
        self.assertEqual(result["terms"], ["carrier", "pulse", "rf_0"])

    def test_clock_operator_sample_and_nonfinite_refuse(self):
        bad = copy.deepcopy(self.model_reference)
        bad["manifest"]["sha256"] = "0" * 64
        with self.assertRaises((ValueError, AssertionError)):
            admit_linear_samples(
                assembly=self.assembly,
                geometry_artifact=self.geometry,
                operator=self.operator,
                model_reference=bad,
                samples=self.samples,
            )
        operator = copy.deepcopy(self.operator)
        operator["mesh"]["electrode_hmax_mm"] = 6.0
        with self.assertRaisesRegex(ValueError, "operator"):
            admit_linear_samples(
                assembly=self.assembly,
                geometry_artifact=self.geometry,
                operator=operator,
                model_reference=self.model_reference,
                samples=self.samples,
            )
        samples = copy.deepcopy(self.samples)
        samples["one"]["reference"] = samples["two"]["reference"]
        with self.assertRaisesRegex(ValueError, "workpoint"):
            admit_linear_samples(
                assembly=self.assembly,
                geometry_artifact=self.geometry,
                operator=self.operator,
                model_reference=self.model_reference,
                samples=samples,
            )
        samples = copy.deepcopy(self.samples)
        samples["one"]["weights"][0]["weight"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite basis weights"):
            admit_linear_samples(
                assembly=self.assembly,
                geometry_artifact=self.geometry,
                operator=self.operator,
                model_reference=self.model_reference,
                samples=samples,
            )

    def test_actual_lua_model_and_scalar_adapter(self):
        import os, shutil, subprocess
        from msplatform.backends.simion.model import render_model_configuration
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value

        admitted = admit_linear_samples(
            assembly=self.assembly,
            geometry_artifact=self.geometry,
            operator=self.operator,
            model_reference=self.model_reference,
            samples=self.samples,
        )
        bases = []
        for name, item in admitted["bases"].items():
            grid = item["grid"]
            r = item["records"]
            bases.append(
                dict(
                    binding=dict(
                        mode="comsol_static_scalar_v",
                        scalar_pa=r["field_v"]["path"],
                        valid_pa=r["field_valid"]["path"],
                        origin_mm=grid["origin_mm"],
                        pitch_mm=grid["pitch_mm"],
                        dimensions=grid["dimensions"],
                        ideal_sheet_projection=item["ideal_sheet_projection"],
                    ),
                    weights=admitted["weights"][name],
                )
            )
        binding = dict(
            model_identity_sha256=admitted["model_identity_sha256"],
            bases=bases,
        )
        lua = os.environ.get("SIMION_LUA_EXE") or shutil.which("lua") or shutil.which("lua5.1")
        if not lua:
            raise FileNotFoundError("required standalone Lua executable unavailable")
        resources = native_resource_path("model_drive.lua").parent
        composer = (
            Path(__file__).resolve().parents[2]
            / "src/msplatform/backends/simion/resources/generic_scalar_field.lua"
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = root / "model.lua"
            config.write_text(render_model_configuration(self.model), encoding="utf8")
            script = r"""
local dir=arg[1]; local config=dofile(arg[2]);local bindings=BINDINGS
local model=dofile(dir..'/model_drive.lua');local rf=dofile(dir..'/rf_drive.lua');local pulse=dofile(dir..'/single_flight_pulse_hook.lua');local waves=dofile(dir..'/voltage_waveforms.lua')
local bad=nil
simion={early_access=function()end,pas={},experimental={}}
function simion.pas:open(path)
 local mask=path:find('field_valid',1,true)~=nil
 local pa={path=path,symmetry='3dplanar',nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
 function pa:potential() if mask then return bad~=path and 1 or 0 end return 0 end
 return pa
end
function simion.experimental.field_array(args)
 local value=args.V.path==bindings.bases[1].binding.scalar_pa and 1 or 2
 return {efield=function()return value,0,0 end}
end
local adapter=dofile(dir..'/scalar_field_adapter.lua');local composer=dofile(arg[3]);local consumer=model.new(config,rf,pulse,waves);local sample=composer.new(adapter,consumer,bindings)
local inst={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1}};function inst:wb_to_pa_orient(x,y,z)return x,y,z end
for _,row in ipairs({{0,2},{.25,-15},{.75,5}}) do local x=sample(inst,1,1,1,row[1]);print('actual',row[1],x,'expected',row[2]);assert(math.abs(x-row[2])<1e-10) end
bad=bindings.bases[1].binding.valid_pa;local zero=(2*math.pi+math.asin(-2/3))/(2*math.pi);assert(math.abs(2+3*math.sin(2*math.pi*zero))<1e-14);local ok=pcall(sample,inst,1,1,1,zero);assert(not ok,'zero-coefficient invalid support must refuse')
bad=nil
local original=consumer.evaluate_at
consumer.evaluate_at=function(t) local rows=original(t);rows[2]=rows[1];return rows end
local duplicate,reason=pcall(sample,inst,1,1,1,0);assert(not duplicate and reason:find('duplicate evaluated group',1,true))
consumer.evaluate_at=function(t) local rows=original(t);rows[2]=nil;return rows end
a=pcall(sample,inst,1,1,1,0);assert(not a,'missing evaluated group must refuse')
print('GENERIC_SCALAR=PASS')
""".replace("BINDINGS", lua_value(binding))
            path = root / "test.lua"
            path.write_text(script, encoding="utf8")
            result = subprocess.run(
                [
                    lua,
                    str(path),
                    str(resources),
                    str(config),
                    str(composer),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf8",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("GENERIC_SCALAR=PASS", result.stdout)
