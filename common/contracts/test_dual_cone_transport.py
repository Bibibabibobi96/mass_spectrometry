"""Installed dual-cone preparation and official SDS initialization; never Fly."""

import subprocess
import hashlib, json, tempfile, unittest
from pathlib import Path
from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import prepare, GAS_INTERFACE


class MismatchTests(unittest.TestCase):
    def test_original_prepare_rejects_other_producer_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            interface = json.loads(GAS_INTERFACE.read_text())
            runtime = root / "field.lua"
            runtime.write_text(
                "return {pressure_pa=function() return 400 end,temperature_k=function() return 300 end,velocity_m_s=function() return 0,0,0 end}\n"
            )
            source_csv = root / "different.csv"
            source_csv.write_text("EXPLICIT_INERT_NOT_CFD\n")
            metadata = root / "different.json"
            metadata.write_text("{}")
            changed_geometry = root / "other_geometry.json"
            changed_geometry.write_text('{"explicit":"different producer geometry"}')
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            manifest = dict(
                schema_version=1,
                role="dual_cone_gas_field_export",
                project_id="dual_cone_tandem_quadrupole_ion_interface",
                source=dict(
                    kind="validated_comsol_axisymmetric_rz",
                    field_csv=dict(path=str(source_csv), sha256=sha(source_csv)),
                    metadata=dict(path=str(metadata), sha256=sha(metadata)),
                    source_contract_sha256=dict(
                        gas_flow_science="1" * 64,
                        comsol_solver_numerics="2" * 64,
                        resolved_geometry=sha(changed_geometry),
                    ),
                ),
                coordinate_frame=interface["runtime_artifact_contract"]["coordinate_frame"],
                domain=interface["runtime_artifact_contract"]["domain"],
                interpolation_policy=interface["runtime_artifact_contract"]["interpolation_policy"],
                runtime_lua=dict(path=str(runtime), sha256=sha(runtime)),
            )
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            sds = root / "sds"
            sds.mkdir()
            for name in ("collision_sds.lua", "mbmr.dat", "textfilelib.lua", "arraylib.lua", "m_defs.dat"):
                (sds / name).write_text("INERT")
            with self.assertRaisesRegex(ValueError, "geometry"):
                prepare(
                    root / "prepared", mode="gas_assisted_transport", gas_field_manifest=path, collision_sds_dir=sds
                )


SDS_HARNESS = r"""local vendor = assert(arg[1])
local function load_official(path, ...)
 local f=assert(io.open(path,'rb'));local text=f:read('*a');f:close()
 -- Ordinary Lua does not implement SIMION's declaration keyword. Only the
 -- declaration keyword is removed; actual official initialization executes.
 text=text:gsub('adjustable%s+', '')
 return assert(loadstring(text,'@'..path))(...)
end
rawset(_G,'checkglobals',function() end)
segment={}
rand=math.random
local ver={}
setmetatable(ver,{__call=function() return ver end,__lt=function() return false end,__le=function() return true end})
simion={VERSION=ver,workbench_program=function() end,import=function(path,opt) return load_official(path,opt) end}

local config={mode='gas_assisted_transport',rf_drive_kernel='RF',gas_field_lua='FIELD',collision_sds_lua=vendor..'/collision_sds.lua',
trajectory_csv=assert(arg[3])..'/trajectory.csv',final_state_csv=arg[3]..'/final.csv',random_seed=7,
collision_gas_mass_amu=28.0134,collision_gas_diameter_nm=.364,diffusion_enabled=0,
stage_1={dc_amplitude_v=0},stage_2={dc_amplitude_v=0},rf_steps_per_period=80}
local old_loadfile=loadfile
loadfile=function(path)
 if path=='CONFIG' then return function() return config end
 elseif path=='RF' then return function() return {new=function() return {apply_at=function()end,timestep_cap_us=1} end} end
 elseif path=='FIELD' then return function() return {pressure_pa=function()return 400 end,temperature_k=function()return 300 end,velocity_m_s=function()return 0,0,0 end} end
 else return old_loadfile(path) end
end
os.getenv=function(name) assert(name=='DUAL_CONE_SIMION_RUN_CONFIG_LUA');return 'CONFIG' end
seed=function()end
ion_run=1
sim_ions_count=0
simion.wb={instances={}}
load_official(assert(arg[2]))
segment.initialize_run()
segment.terminate_run()
assert(SDS_collision_gas_mass_amu==28.0134,'declared N2 gas mass unused; actual='..tostring(SDS_collision_gas_mass_amu))
assert(SDS_collision_gas_diameter_nm==.364,'declared N2 diameter unused')
assert(SDS_diffusion==0,'declared diffusion off unused')
print('OFFICIAL_SDS_INIT_BINDINGS=PASS')
"""


class OfficialSdsInitializationTests(unittest.TestCase):
    def test_actual_official_module_receives_declared_parameters_before_initialization(self):
        from msplatform.backends.simion.resources import native_resource_path

        lua = Path("C:/Program Files/SIMION-2020/lua.exe")
        vendor = lua.parent / "examples/collision_sds"
        if not lua.is_file() or not (vendor / "collision_sds.lua").is_file():
            self.skipTest("Installed official SDS and plain Lua interpreter unavailable; no commercial process used")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for mode in ("declared", "bad_mass", "bad_diameter", "bad_diffusion"):
                with self.subTest(mode=mode):
                    code = SDS_HARNESS
                    if mode == "bad_mass":
                        code = code.replace("collision_gas_mass_amu=28.0134", "collision_gas_mass_amu=-1")
                    if mode == "bad_diameter":
                        code = code.replace("collision_gas_diameter_nm=.364", "collision_gas_diameter_nm=0")
                    if mode == "bad_diffusion":
                        code = code.replace("diffusion_enabled=0", "diffusion_enabled=2")
                    script = root / (mode + ".lua")
                    script.write_text(code, encoding="utf-8")
                    result = subprocess.run(
                        [
                            str(lua),
                            str(script),
                            str(vendor),
                            str(native_resource_path("dual_cone_gas_assisted_transport.lua")),
                            str(root),
                        ],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=30,
                        check=False,
                    )
                    if mode == "declared":
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("OFFICIAL_SDS_INIT_BINDINGS=PASS", result.stdout)
                        self.assertIn("SDS collision gas mass (u)=\t28.0134", result.stdout)
                        self.assertIn("diffusion disabled", result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            {
                                "bad_mass": "collision_gas_mass_amu",
                                "bad_diameter": "collision_gas_diameter_nm",
                                "bad_diffusion": "diffusion_enabled",
                            }[mode],
                            result.stdout + result.stderr,
                        )
                        self.assertNotIn("SDS Defining", result.stdout)


class PublishedGasPreparationTests(unittest.TestCase):
    def test_explicit_published_product_freezes_original_contracts_and_rejects_geometry_change(self):
        from msplatform.backends.simion.dual_cone_transport import prepare_transport, SDS_FILES
        from msplatform.io.manifest_records import file_record
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import _write_fixture
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import PROJECT

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path, metadata_path = _write_fixture(root)
            config = PROJECT / "config"
            paths = dict(
                science=config / "gas_flow_science.json",
                numerics=config / "comsol_solver_numerics.json",
                geometry=config / "resolved_geometry.json",
                field_csv=csv_path,
                field_metadata=metadata_path,
            )
            records = {name: file_record(path, "required_evidence") for name, path in paths.items()}
            producer = dict(
                schema_version=2,
                role="simulation_run_manifest",
                project=PROJECT.name,
                run_id="explicit-inert-gas-fixture",
                mode="axisymmetric_gas_flow_screening",
                status="success",
                inputs={name: records[name] for name in ("science", "numerics", "geometry")},
                outputs=[records["field_csv"], records["field_metadata"]],
                products=dict(
                    gas_field=dict(
                        schema_version=1,
                        kind="gas_field",
                        status="complete",
                        metadata=dict(claim_scope="INERT_PREPARATION_FIXTURE_NOT_NATIVE"),
                        data=records,
                    )
                ),
            )
            manifest = root / "producer.json"
            manifest.write_text(json.dumps(producer), encoding="utf-8")
            reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")
            interface = json.loads((config / "gas_field_interface.json").read_text())
            interface["runtime_artifact_contract"]["domain"] = dict(
                minimum_z_mm=0.0, maximum_z_mm=9.0, minimum_radius_mm=0.0, maximum_radius_mm=9.0
            )
            interface_path = root / "explicit-test-interface.json"
            interface_path.write_text(json.dumps(interface), encoding="utf-8")
            sds = root / "sds"
            sds.mkdir()
            for name in SDS_FILES:
                (sds / name).write_text("EXPLICIT_INERT_PREPARATION_ONLY", encoding="utf-8")
            kwargs = dict(
                mode="gas_assisted_transport",
                resolved_path=paths["geometry"],
                numerics_path=config / "simion_solver_numerics.json",
                science_path=config / "ion_transport_science.json",
                interface_path=interface_path,
                gas_science_path=paths["science"],
                source_spec_path=config / "cylindrical_ion_source.json",
                gas_field_reference=reference,
                collision_sds_dir=sds,
            )
            receipt = prepare_transport(root / "positive", **kwargs)
            self.assertFalse(receipt["qualified_evidence"])
            self.assertEqual(receipt["inputs"]["gas_producer_manifest"]["sha256"], reference["manifest"]["sha256"])
            for name in ("science", "numerics", "geometry"):
                self.assertEqual(receipt["inputs"]["gas_producer_" + name]["sha256"], records[name]["sha256"])
            self.assertEqual(list((root / "positive").rglob("*.pa*")), [])
            self.assertEqual(receipt["inputs"]["cylindrical_ion_source_receipt"]["identity"]["particle_count"], 100)
            altered = root / "changed-geometry.json"
            altered.write_bytes(paths["geometry"].read_bytes() + b" ")
            kwargs["resolved_path"] = altered
            with self.assertRaisesRegex(ValueError, "producer geometry"):
                prepare_transport(root / "negative", **kwargs)
            self.assertFalse((root / "negative").exists())


class LargeGasRuntimeFreezeTests(unittest.TestCase):
    def test_public_preparation_freezes_large_valid_runtime_with_original_receipt_shape(self):
        from msplatform.backends.simion.dual_cone_transport import prepare_transport, SDS_FILES
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import PROJECT
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.uniform_gas_runtime import (
            export_uniform_runtime,
        )
        from msplatform.io.file_identity import file_sha256

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = PROJECT / "config"
            runtime = root / "large-field.lua"
            manifest_path = root / "field.json"
            export_uniform_runtime(
                runtime,
                manifest_path,
                spec_path=config / "uniform_rear_gas_field.json",
                interface_path=config / "gas_field_interface.json",
            )
            # A valid Lua comment makes this real public input cross the existing
            # 8MiB file-identity tier without inventing a native result.
            runtime.write_bytes(b"--" + b"x" * (8 * 1024 * 1024) + b"\n" + runtime.read_bytes())
            original = runtime.read_bytes()
            manifest = json.loads(manifest_path.read_text())
            manifest["runtime_lua"]["sha256"] = file_sha256(runtime).lower()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            sds = root / "sds"
            sds.mkdir()
            for name in SDS_FILES:
                (sds / name).write_text("INERT_PREPARATION_ONLY", encoding="utf-8")
            output = root / "prepared"
            receipt = prepare_transport(
                output,
                mode="gas_assisted_transport",
                resolved_path=config / "resolved_geometry.json",
                numerics_path=config / "simion_solver_numerics.json",
                science_path=config / "ion_transport_science.json",
                interface_path=config / "gas_field_interface.json",
                gas_science_path=config / "gas_flow_science.json",
                source_spec_path=config / "cylindrical_ion_source.json",
                collision_sds_dir=sds,
                gas_field_manifest=manifest_path,
            )
            record = receipt["inputs"]["gas_field_runtime"]
            self.assertGreater(record["bytes"], 8 * 1024 * 1024)
            self.assertEqual(set(record), {"source_path", "frozen_path", "sha256", "bytes"})
            self.assertEqual(Path(record["frozen_path"]).read_bytes(), original)
            self.assertEqual(runtime.read_bytes(), original)
            self.assertEqual(file_sha256(Path(record["frozen_path"])), record["sha256"])
            self.assertEqual(file_sha256(runtime), record["sha256"])
            self.assertLess((output / "preparation_receipt.json").stat().st_size, 32 * 1024)
            self.assertFalse(receipt["qualified_evidence"])
            self.assertEqual(list(output.rglob("*.pa*")), [])
