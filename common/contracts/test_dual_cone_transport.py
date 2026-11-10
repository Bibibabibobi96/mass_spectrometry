"""Installed dual-cone preparation and official SDS initialization; never Fly."""

import subprocess
import hashlib, json, tempfile, unittest
from pathlib import Path
from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import GAS_INTERFACE


class MismatchTests(unittest.TestCase):
    def test_original_prepare_rejects_other_producer_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import (
                _write_fixture, SCIENCE_PATH, NUMERICS_PATH, GEOMETRY_PATH,
            )
            from msplatform.contracts.gas_field import read_gas_field_data
            from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_cfd_gas_field
            from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
            from msplatform.io.manifest_records import file_record

            interface = json.loads(GAS_INTERFACE.read_text())
            interface["runtime_artifact_contract"]["domain"] = dict(minimum_z_mm=0, maximum_z_mm=9,
                minimum_radius_mm=0, maximum_radius_mm=9)
            csv_path, metadata_path = _write_fixture(root)
            changed_geometry = root / "other_geometry.json"
            changed_geometry.write_bytes(GEOMETRY_PATH.read_bytes() + b" ")
            metadata = json.loads(metadata_path.read_text())
            metadata["source_contract_sha256"]["resolved_geometry"] = hashlib.sha256(changed_geometry.read_bytes()).hexdigest()
            metadata_path.write_text(json.dumps(metadata))
            data = read_gas_field_data(csv_path, metadata_path, SCIENCE_PATH, NUMERICS_PATH, changed_geometry)
            files = dict(field_csv=csv_path, field_metadata=metadata_path, science=SCIENCE_PATH,
                         numerics=NUMERICS_PATH, geometry=changed_geometry)
            field, manifest = prepare_cfd_gas_field(data, interface=interface,
                source_records={name: file_record(path, "required_evidence") for name,path in files.items()})
            path = root / "manifest.json"
            materialize_gas_runtime(field, root/"field.lua", path, manifest_metadata=manifest)
            selected_interface = root / "interface.json"
            selected_interface.write_text(json.dumps(interface))
            sds = root / "sds"
            sds.mkdir()
            for name in ("collision_sds.lua", "mbmr.dat", "textfilelib.lua", "arraylib.lua", "m_defs.dat"):
                (sds / name).write_text("INERT")
            with self.assertRaisesRegex(ValueError, "geometry"):
                from msplatform.backends.simion.dual_cone_transport import prepare_transport
                from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import PROJECT
                config = PROJECT / "config"
                prepare_transport(root / "prepared", mode="gas_assisted_transport", gas_field_manifest=path,
                    collision_sds_dir=sds, interface_path=selected_interface,
                    resolved_path=config/"resolved_geometry.json", numerics_path=config/"simion_solver_numerics.json",
                    science_path=config/"ion_transport_science.json", gas_science_path=config/"gas_flow_science.json",
                    source_spec_path=config/"cylindrical_ion_source.json")


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
collision_sds_binding_lua=assert(arg[4]),gas_field_frame_id='explicit_fixture',gas_outside_domain_policy='coverage_loss',
trajectory_csv=assert(arg[3])..'/trajectory.csv',final_state_csv=arg[3]..'/final.csv',random_seed=7,
collision_gas_mass_amu=28.0134,collision_gas_diameter_nm=.364,diffusion_enabled=0,
stage_1={dc_amplitude_v=0},stage_2={dc_amplitude_v=0},rf_steps_per_period=80}
local old_loadfile=loadfile
loadfile=function(path)
 if path=='CONFIG' then return function() return config end
 elseif path=='RF' then return function() return {new=function() return {apply_at=function()end,timestep_cap_us=1} end} end
 elseif path=='FIELD' then return function() return {_sample_sds=function(channel)if channel=='pressure' then return 'gas',400 elseif channel=='temperature' then return 'gas',300 end;return 'gas',0,0,0 end,sample=function()return {status='gas',pressure_pa=400,temperature_k=300,bulk_velocity_m_s={0,0,0}} end} end
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
                            str(native_resource_path("collision_sds_binding.lua")),
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


    def test_current_runtime_keeps_direct_source_and_rejects_explicit_broken_producer(self):
        from msplatform.backends.simion.dual_cone_transport import validate_runtime_manifest
        from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_cfd_gas_field
        from msplatform.contracts.gas_field import read_gas_field_data
        from msplatform.io.manifest_records import file_record
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import (
            _write_fixture, SCIENCE_PATH, NUMERICS_PATH, GEOMETRY_PATH,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path, metadata_path = _write_fixture(root)
            interface = json.loads(GAS_INTERFACE.read_text())
            interface["runtime_artifact_contract"]["domain"] = dict(
                minimum_z_mm=0., maximum_z_mm=9., minimum_radius_mm=0., maximum_radius_mm=9.)
            data = read_gas_field_data(csv_path, metadata_path, SCIENCE_PATH, NUMERICS_PATH, GEOMETRY_PATH)
            records = {name: file_record(path, "required_evidence") for name, path in dict(
                field_csv=csv_path, field_metadata=metadata_path, science=SCIENCE_PATH,
                numerics=NUMERICS_PATH, geometry=GEOMETRY_PATH).items()}
            field, metadata = prepare_cfd_gas_field(data, interface=interface, source_records=records)
            runtime, manifest_path = root / "direct.lua", root / "direct.json"
            materialize_gas_runtime(field, runtime, manifest_path, manifest_metadata=metadata)
            actual, actual_path = validate_runtime_manifest(manifest_path, interface)
            self.assertIsNone(actual["source"]["producer_reference"])
            self.assertEqual(actual_path, runtime.resolve())
            self.assertEqual(actual["source"]["source_contract_records"]["geometry"], records["geometry"])
            producer_path = root / "explicit-producer.json"
            producer = dict(status="success", products=dict(gas_field=dict(kind="gas_field", status="complete",
                data=records)))
            producer_path.write_text(json.dumps(producer), encoding="utf8")
            reference = dict(manifest=file_record(producer_path, "required_evidence"), product_id="gas_field")
            for name, selected, message in (
                ("malformed", {}, "explicit original product"),
                ("missing_product", dict(reference, product_id="missing"), "differs from explicit producer"),
            ):
                with self.subTest(name=name):
                    broken = json.loads(manifest_path.read_text())
                    broken["source"]["producer_reference"] = selected
                    selected_path = root / (name + ".json")
                    selected_path.write_text(json.dumps(broken), encoding="utf8")
                    with self.assertRaisesRegex(ValueError, message):
                        validate_runtime_manifest(selected_path, interface)
            bound = json.loads(manifest_path.read_text())
            bound["source"]["producer_reference"] = reference
            bound_path = root / "bound.json"
            bound_path.write_text(json.dumps(bound), encoding="utf8")
            self.assertEqual(validate_runtime_manifest(bound_path, interface)[1], runtime.resolve())
            producer["products"]["gas_field"]["data"]["field_csv"] = records["field_metadata"]
            producer_path.write_text(json.dumps(producer), encoding="utf8")
            bound["source"]["producer_reference"]["manifest"] = file_record(producer_path, "required_evidence")
            bound_path.write_text(json.dumps(bound), encoding="utf8")
            with self.assertRaisesRegex(ValueError, "differs from explicit producer"):
                validate_runtime_manifest(bound_path, interface)


class LargeGasRuntimeFreezeTests(unittest.TestCase):
    def test_public_preparation_freezes_large_valid_runtime_with_original_receipt_shape(self):
        from msplatform.backends.simion.dual_cone_transport import prepare_transport, SDS_FILES
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import PROJECT
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import write_uniform_gas_fixture
        from msplatform.io.file_identity import file_sha256

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = PROJECT / "config"
            runtime = root / "large-field.lua"
            manifest_path = root / "field.json"
            write_uniform_gas_fixture(
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


class ExplicitUniformStudyTests(unittest.TestCase):
    def test_named_control_and_explicit_pressure_reach_actual_preparation_and_program(self):
        from msplatform.backends.simion.dual_cone_transport import prepare_transport, SDS_FILES
        from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_uniform_rear_gas_field
        from msplatform.contracts.gas import GasSpecies
        from msplatform.io.manifest_records import file_record
        from common.contracts.test_simion_prepared_model import LUA
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_simion_layer import PROJECT
        if not LUA.is_file():
            self.skipTest("standalone Lua 5.1 required for actual Program consumer; no native fallback")
        config = PROJECT / "config"
        source = json.loads((config / "uniform_rear_gas_field.json").read_text(encoding="utf8"))
        interface_path = config / "gas_field_interface.json"
        interface = json.loads(interface_path.read_text(encoding="utf8"))
        science = json.loads((config / "ion_transport_science.json").read_text(encoding="utf8"))
        composition = (GasSpecies("N2", science["gas"]["collision_gas_mass_amu"], 1.),)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "explicit-study.json"
            def construct(value):
                spec_path.write_text(json.dumps(value), encoding="utf8")
                return prepare_uniform_rear_gas_field(value, interface=interface, composition=composition,
                    spec_record=file_record(spec_path,"required_evidence"),
                    interface_record=file_record(interface_path,"required_evidence"))
            changed = json.loads(json.dumps(source))
            changed["rear_region"]["pressure_pa"] = 125.
            with self.assertRaisesRegex(ValueError, "frozen minimal prototype requires a 400 Pa"):
                construct(changed)
            for pressure in (125., 0.):
                with self.subTest(pressure_pa=pressure):
                    value = json.loads(json.dumps(source))
                    value["model_id"] = "explicit_" + str(pressure) + "_pa_rear_study"
                    value["rear_region"]["pressure_pa"] = pressure
                    field, metadata = construct(value)
                    runtime, manifest = root / (str(pressure)+".lua"), root / (str(pressure)+".json")
                    materialize_gas_runtime(field,runtime,manifest,manifest_metadata=metadata)
                    sds = root / ("sds-"+str(pressure)); sds.mkdir()
                    for name in SDS_FILES:(sds/name).write_text("INERT_TEST_ONLY",encoding="utf8")
                    output = root / ("prepared-"+str(pressure))
                    arguments=dict(mode="gas_assisted_transport",resolved_path=config/"resolved_geometry.json",
                        numerics_path=config/"simion_solver_numerics.json",science_path=config/"ion_transport_science.json",
                        interface_path=interface_path,gas_science_path=config/"gas_flow_science.json",
                        source_spec_path=config/"cylindrical_ion_source.json",gas_field_manifest=manifest,collision_sds_dir=sds)
                    receipt=prepare_transport(output,**arguments)
                    self.assertFalse(receipt["qualified_evidence"])
                    self.assertEqual(list(output.rglob("*.pa*")),[])
                    self.assertEqual(receipt["inputs"]["cylindrical_ion_source_receipt"]["identity"]["particle_count"],100)
                    if LUA.is_file():
                        harness=root/(str(pressure)+"-program.lua")
                        harness.write_text(r"""local load=loadfile;local config=assert(load(arg[1]))()
loadfile=function(path)if path==arg[1]then return function()return config end end;return load(path)end
local installs,seeds=0,0;local SDS={install=function()installs=installs+1 end}
simion={workbench_program=function()segment={}end,import=function()return SDS end}
os.getenv=function()return arg[1]end;seed=function(value)assert(value==config.random_seed);seeds=seeds+1 end
adj_elect={};ion_number=7;ion_time_of_flight=0;ion_time_step=1;ion_splat=0
ion_px_mm=config.device_x_offset_mm;ion_py_mm=config.device_y_offset_mm;ion_pz_mm=config.device_z_offset_mm+10
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0
local f=assert(io.open(arg[2],'rb'));local text=f:read('*a');f:close();assert(loadstring(text:gsub('adjustable%s+',''),'@'..arg[2]))()
segment.initialize_run();segment.initialize()
assert(SDS.pressure(ion_px_mm,ion_py_mm,ion_pz_mm)==tonumber(arg[3])*(760/101325))
assert(SDS.temperature(ion_px_mm,ion_py_mm,ion_pz_mm)==300)
local x,y,z=SDS.velocity(ion_px_mm,ion_py_mm,ion_pz_mm);assert(x==0 and y==0 and z==100)
segment.other_actions();segment.terminate();segment.terminate_run()
assert(installs==1 and seeds==1);print('EXPLICIT_UNIFORM_SDS=PASS')
""",encoding="utf8")
                        child=subprocess.run([str(LUA),str(harness),str(output/"solver/simion/run_config.lua"),
                            str(native_resource_path("dual_cone_gas_assisted_transport.lua")),str(pressure)],
                            cwd=output,capture_output=True,text=True,encoding="utf8",timeout=30)
                        self.assertEqual(child.returncode,0,child.stdout+child.stderr)
                        self.assertIn("EXPLICIT_UNIFORM_SDS=PASS",child.stdout)
                        print("EXPLICIT_UNIFORM_SOFTWARE="+json.dumps(dict(pressure_pa=pressure,lua=str(LUA),lua_sha256=hashlib.sha256(LUA.read_bytes()).hexdigest(),program_sha256=hashlib.sha256(native_resource_path("dual_cone_gas_assisted_transport.lua").read_bytes()).hexdigest())))
                    broken=json.loads(manifest.read_text(encoding="utf8"))
                    broken["source"]["spec_record"]["sha256"]="0"*64
                    manifest.write_text(json.dumps(broken),encoding="utf8")
                    with self.assertRaisesRegex(AssertionError,"SHA-256 changed"):
                        prepare_transport(root/("bad-source-"+str(pressure)),**arguments)
                    self.assertFalse((root/("bad-source-"+str(pressure))).exists())
            for pressure in (-1.,float("nan"),float("inf"),True):
                with self.subTest(invalid_pressure=pressure):
                    value=json.loads(json.dumps(source));value["model_id"]="explicit_invalid_pressure"
                    value["rear_region"]["pressure_pa"]=pressure
                    with self.assertRaises(ValueError):construct(value)
            for model_id in ("",None,True):
                with self.subTest(invalid_model_id=model_id):
                    value=json.loads(json.dumps(source));value["model_id"]=model_id
                    with self.assertRaisesRegex(ValueError,"explicit uniform gas study model_id"):
                        construct(value)
