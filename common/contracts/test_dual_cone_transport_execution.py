"""Pure native operation plans and generic Lua witnesses; never launch SIMION."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
from msplatform.io.manifest_records import file_record

from msplatform.backends.simion.dual_cone_transport_execution import plan_transport_operations
from msplatform.backends.simion.resources import native_resource_path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "projects/dual_cone_tandem_quadrupole_ion_interface/config"
LUA = Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")


def request():
    names = dict(
        resolved="resolved_geometry",
        numerics="simion_solver_numerics",
        science="ion_transport_science",
        source_spec="cylindrical_ion_source",
    )
    return {name: json.loads((CONFIG / (filename + ".json")).read_text()) for name, filename in names.items()}


class TransportPlanTests(unittest.TestCase):
    def test_nondefault_enclosure_span_is_the_compiler_authority(self):
        from msplatform.backends.simion.dual_cone_geometry import render_gem

        values = request()
        values["resolved"]["geometry_mm"]["low_pressure_enclosure"]["radius_mm"] = 24.5
        cell = values["numerics"]["pa"]["cell_mm_xyz"]
        cell.update(x=0.25, y=0.25, z=0.25)
        offsets = values["numerics"]["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]
        offsets.update(x=26.5, y=26.5)
        values["numerics"]["pa"]["grid_points_xyz"] = dict(x=213, y=213, z=489)
        gem = render_gem(values["resolved"], values["numerics"])
        self.assertIn("pa_define($(53/mmgu+1),$(53/mmgu+1)", gem)

    def test_geometry_grid_rejects_invalid_cells_and_mismatched_offset(self):
        from msplatform.backends.simion.dual_cone_geometry import geometry_grid

        for patch in ({"x": 0}, {"x": 0.5, "y": 1}):
            values = request()
            values["numerics"]["pa"]["cell_mm_xyz"].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                geometry_grid(values["resolved"], values["numerics"])
        values = request()
        values["resolved"]["geometry_mm"]["low_pressure_enclosure"]["radius_mm"] = 24.5
        values["numerics"]["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]["x"] = 23
        with self.assertRaisesRegex(ValueError, "metal geometry"):
            geometry_grid(values["resolved"], values["numerics"])

    def test_explicit_grid_freedom_and_default_bytes(self):
        from msplatform.backends.simion.dual_cone_geometry import geometry_grid, render_gem
        from msplatform.backends.simion.dual_cone_stages import plan_geometry_stage

        values = request()
        baseline = render_gem(values["resolved"], values["numerics"])
        self.assertIn("pa_define($(51/mmgu+1),$(51/mmgu+1),$(122/mmgu+1)", baseline)
        identity = plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])["projection"]["identity_sha256"]
        values["numerics"]["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]["x"] = 26.5
        self.assertEqual(geometry_grid(values["resolved"], values["numerics"])["nx"], 103)
        self.assertNotEqual(plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])["projection"]["identity_sha256"], identity)
        values["numerics"]["pa"]["cell_mm_xyz"] = dict(x=.7, y=.7, z=.7)
        values["numerics"]["pa"]["grid_points_xyz"] = dict(x=74, y=74, z=176)
        grid = geometry_grid(values["resolved"], values["numerics"])
        self.assertAlmostEqual((grid["nx"]-1)*grid["dx_mm"], 51.1)
        before = plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])["projection"]
        values["numerics"]["trajectory"]["sample_interval_us"] = 2
        self.assertEqual(plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])["projection"], before)
        values["numerics"]["pa"]["grid_points_xyz"]["x"] = 75
        self.assertNotEqual(plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])["projection"]["identity_sha256"], before["identity_sha256"])
        for counts in (dict(x=True,y=103,z=245),dict(x=2,y=103,z=245),dict(x=103.0,y=103,z=245),dict(x=10,y=103,z=245)):
            broken = request();broken["numerics"]["pa"]["grid_points_xyz"] = counts
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                geometry_grid(broken["resolved"], broken["numerics"])
        missing = request();del missing["numerics"]["pa"]["grid_points_xyz"]
        with self.assertRaises(KeyError):
            geometry_grid(missing["resolved"], missing["numerics"])

    def test_source_and_observation_use_actual_grid_not_fixed_margin(self):
        from msplatform.backends.simion.dual_cone_transport import _render_run_config, prepare_transport

        values = request()
        values["numerics"]["pa"]["grid_points_xyz"]["z"] = 227
        with self.assertRaisesRegex(ValueError, "observation plane"):
            _render_run_config(mode="c0_gem_smoke", science=values["science"],
                numerics=values["numerics"], resolved=values["resolved"], solver=Path("a/b/c"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = request()
            values["numerics"]["workbench"]["coordinate_mapping"]["device_to_workbench_offset_mm"]["z"] = 0
            numerics = root / "numerics.json";numerics.write_text(json.dumps(values["numerics"]))
            output = root / "prepared"
            with self.assertRaisesRegex(ValueError, "C0 source"):
                prepare_transport(output,mode="c0_gem_smoke",resolved_path=CONFIG/"resolved_geometry.json",
                    numerics_path=numerics,science_path=CONFIG/"ion_transport_science.json",
                    interface_path=CONFIG/"gas_field_interface.json",gas_science_path=CONFIG/"gas_flow_science.json",
                    source_spec_path=CONFIG/"cylindrical_ion_source.json")
            self.assertFalse(output.exists())

    def test_grid_changes_invalidate_actual_spatial_basis_but_source_does_not(self):
        from msplatform.backends.simion import dual_cone_stages as stages
        from msplatform.backends.simion.model import RF_PHYSICS
        from common.contracts.test_dual_cone_stages import CLOCK, record

        values = request()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = {name: record(root,name) for name in ("raw_geometry","fractional_surface","surface_witnesses")}
            impl = {name: record(root,name) for name in ("simion","refiner","auditor")}
            def basis():
                geometry = stages.plan_geometry_stage(resolved=values["resolved"],numerics=values["numerics"])["projection"]
                model = stages.plan_model_stage(geometry,electric_field=values["science"]["electric_field"],clock=CLOCK,physics=RF_PHYSICS)["projection"]
                return stages.plan_fields_stage(model,numerics=values["numerics"],raw_records=raw,implementation_records=impl)["spatial_identity"]
            before = basis()
            values["source_spec"]["sampling"]["seed"] = 999
            values["numerics"]["trajectory"]["sample_interval_us"] = 2
            self.assertEqual(basis(),before)
            values["numerics"]["pa"]["grid_points_xyz"]["x"] += 1
            self.assertNotEqual(basis()["identity_sha256"],before["identity_sha256"])

    def test_actual_scientific_input_and_explicit_native_dependency_graph(self):
        values = request()
        original = copy.deepcopy(values)
        plan = plan_transport_operations(**values)
        self.assertEqual(values, original)
        self.assertEqual(plan["electrode_ids"], [1, 2, 3, 11, 12, 21, 22])
        self.assertEqual(plan["source_count"], 100)
        self.assertEqual(plan["operation_dependencies"]["fly"], ["verify_tracking_model"])
        self.assertNotIn("convergence_v", plan["refinement"])
        self.assertEqual(plan["saved_field_reuse"], "not_implemented")

    def test_legal_cohort_time_and_convergence_selections_are_preserved(self):
        values = request()
        values["source_spec"]["particle_count"] = 7
        values["source_spec"]["mother_particle_count"] = 7
        values["numerics"]["trajectory"]["maximum_time_us"] = 1234
        values["numerics"]["pa"].update(refine_policy="explicit_convergence", convergence_v=0.001)
        plan = plan_transport_operations(**values)
        self.assertEqual(plan["source_count"], 7)
        self.assertEqual(plan["numerics"]["trajectory"]["maximum_time_us"], 1234)
        self.assertEqual(plan["refinement"]["convergence_v"], 0.001)

    def test_invalid_selections_fail_before_outputs(self):
        base = request()
        for mutation in (
            lambda v: v["numerics"]["pa"].update(refine_policy="unknown"),
            lambda v: v["numerics"]["pa"].update(convergence_v=1),
            lambda v: v["numerics"]["pa"].update(refine_policy="explicit_convergence", convergence_v=0),
            lambda v: v["source_spec"].update(mother_particle_count=101),
            lambda v: v["science"]["electric_field"]["stage_1"]["electrode_group_ids"].update({"1": 1}),
        ):
            values = copy.deepcopy(base)
            mutation(values)
            with self.subTest(values=values), self.assertRaises(ValueError):
                plan_transport_operations(**values)

    @unittest.skipUnless(LUA.is_file(), "plain Lua unavailable; no native fallback")
    def test_original_generic_builder_and_optional_namespace_failures(self):
        script = native_resource_path("build_frontend_geometry.lua")
        for ids, actual, expected, metadata in (
            (None, [1], True, [1]),
            ([1, 2], [1, 2], True, [1, 2]),
            ([1, 2], [1], False, [1]),
            ([1], [1, 2], False, [1, 2]),
            ([1, 1], [1], False, [1]),
            ([1, 2, 3, 11, 12, 21, 22], [1, 2, 3, 11, 12, 21, 22], True, []),
            ([1, 2, 3, 11, 12, 21, 22], [1, 2, 3, 11, 12, 21, 22], True, None),
            ([1, 2], [1, 2, 99], False, []),
        ):
            with self.subTest(ids=ids, actual=actual), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                # An inert PA implements the official point/grid API. The actual
                # generic resource body runs; no proprietary application opens.
                spec = "return {schema_version=1,role='simion_frontend_raw_geometry',domain_id='test',output='raw.pa#',gem='fixture',grid={nx=10,ny=3,nz=3},physical_samples={}}"
                if ids is not None:
                    spec = (
                        spec[:-1]
                        + ",electrode_witness_ids={"
                        + ",".join(map(str, ids))
                        + "},fractional_surface='raw.pa-surf',surface_witnesses='surface.csv'}"
                    )
                    (root / "raw.pa-surf").write_text("INERT_SURFACE_NOT_NATIVE")
                (root / "spec.lua").write_text(spec)
                source = script.read_text(encoding="utf-8")
                (root / "builder.lua").write_text(source)
                harness = """local original_loadfile=loadfile
function loadfile(path)
 if path:match('gem2pa_geometry.lua$') then return function() return {gem2pa=function() end} end end
 return original_loadfile(path)
end
local actual={%s}
local pa={nx=10,ny=3,nz=3,potential_type='electric'}
local metadata=%s
setmetatable(pa,{__index=function(_,key)
 if key=='electrode_numbers' then
  assert(metadata~=false,'electrode_numbers is not raw namespace metadata')
  return metadata
 end
end})
function pa:point(x,y,z)
 if y==0 and z==0 and x<#actual then
  -- Put the final unexpected-ID control at the last node, past all witnesses.
  if actual[x+1]~=99 then return actual[x+1],true end
 end
 if x==9 and y==2 and z==2 and actual[#actual]==99 then return 99,true end
 return 0,false
end
function pa:surface_info() return .25,nil,nil end
function pa:close() end
simion={pas={open=function() return pa end,close=function() end}}
arg={'spec.lua'}
dofile(%s)
""" % (
                    ",".join(map(str, actual)),
                    "false" if metadata is None else "{" + ",".join(map(str, metadata)) + "}",
                    json.dumps(str(root / "builder.lua")),
                )
                (root / "harness.lua").write_text(harness)
                result = subprocess.run([str(LUA), "harness.lua"], cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)
                if ids is not None and expected:
                    self.assertIn("GEOMETRY_NAMESPACE_SCAN=PASS", result.stdout)
                    self.assertTrue((root / "surface.csv").read_text().strip())


class TrackingBoundaryTests(unittest.TestCase):
    def test_fly_requires_closed_writer_completion_and_full_census(self):
        from msplatform.backends.simion.dual_cone_transport_execution import track_transport
        from common.simion.test_analyze_terminal_plane import HEADER

        for scenario in ("valid", "unknown_writer", "missing_completion", "wrong_count", "missing_identity"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                iob = root / "owned.iob"
                iob.write_text("INERT_WORKBENCH_NOT_NATIVE")
                final = root / "final.csv"
                final.write_text(
                    HEADER
                    + "1,10,25.5,25.5,121.75,0,0,1,0\n"
                    + ("" if scenario == "missing_identity" else "2,11,25.5,25.5,121.75,0,0,1,3\n")
                )
                calls = []
                session = SimpleNamespace(
                    context=SimpleNamespace(tools={"simion": root / "simion.exe"}),
                    artifact_run_dir=root,
                    expected_operation_ids=("fly",),
                    operations=[],
                    log_dir=root,
                    canonical_path=lambda path: Path(path).resolve(),
                )

                def run(operation, **kwargs):
                    calls.append((operation, kwargs))
                    if scenario != "unknown_writer":
                        session.operations.append(
                            dict(operation_id=operation, observation=dict(exit_confirmed=True, returncode=0))
                        )
                    (root / "operation_0001.stdout.log").write_text(
                        "NO_COMPLETION\n"
                        if scenario == "missing_completion"
                        else "status,Fly completed. "
                        + ("1" if scenario == "wrong_count" else "2")
                        + " splats, 0.1 seconds\n"
                    )

                session.run_process = run
                arguments = dict(
                    workbench=iob,
                    fly2=root / "source.fly2",
                    run_config=root / "run.lua",
                    numerics=request()["numerics"],
                    source_count=2,
                    limits={"explicit_fixture": 1},
                    final_state=final,
                    immutable_input_records=[file_record(iob, "required_evidence")],
                )
                if scenario == "valid":
                    metrics, transmitted = track_transport(session, **arguments)
                    self.assertEqual(metrics["terminal_code_counts"], {"0": 1, "3": 1})
                    self.assertEqual(transmitted, [])
                else:
                    with self.assertRaises(ValueError):
                        track_transport(session, **arguments)
                self.assertEqual([name for name, _ in calls], ["fly"])
                self.assertNotIn("refine", calls[0][1]["arguments"])
                self.assertEqual(calls[0][1]["immutable_input_records"], arguments["immutable_input_records"])
                self.assertEqual(calls[0][1]["environment"], {"DUAL_CONE_SIMION_RUN_CONFIG_LUA": str(root / "run.lua")})

    def test_track_refuses_an_external_published_workbench_before_launch(self):
        from msplatform.backends.simion.dual_cone_transport_execution import track_transport

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = SimpleNamespace(artifact_run_dir=root / "run", canonical_path=lambda p: Path(p).resolve())
            with self.assertRaisesRegex(ValueError, "external/published"):
                track_transport(
                    session,
                    workbench=root / "published.iob",
                    fly2=None,
                    run_config=None,
                    numerics={},
                    source_count=1,
                    limits={},
                    final_state=None,
                    immutable_input_records=[],
                )


class ManagedTransportTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": ""})
    def test_actual_preparation_owner_graph_and_publication_with_inert_native_observations(self):
        import os
        from dataclasses import replace
        from unittest.mock import patch
        from msplatform.io.manifest_records import file_record
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        from msplatform.workflows.dual_cone_transport import run_gas_assisted_transport
        from common.contracts.test_execution_runtime import NormalOwnerTests
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import _write_fixture

        for scenario in (
            "valid",
            "native_alias_contract",
            "native_missing_bootstrap",
            "native_wrong_bootstrap",
            "sync",
            "async",
            "invalid_bool",
            "invalid_key",
            "insufficient_gas_coverage",
            "bad_gas_quality",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                if scenario.startswith("native_") and not LUA.is_file():
                    self.skipTest("plain Lua unavailable; no native fallback")
                root = Path(directory)
                helper = NormalOwnerTests()
                policy = root / "capacity.json"
                policy.write_text(json.dumps(helper._policy()))
                simion = root / "simion.exe"
                simion.write_bytes(b"INERT_NOT_EXECUTABLE")
                context = replace(helper._context(root), capacity_policy_path=policy, tools={"simion": simion})
                from msplatform.execution.capacity_ledger import initialize_capacity_ledger, record_capacity_object

                artifact_root = context.workspace / "artifacts"
                artifact_root.mkdir(parents=True)
                initialize_capacity_ledger(artifact_root, objects=[])
                source = (
                    context.workspace
                    / "artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/runs/inert-gas-source"
                )
                source.mkdir(parents=True)
                csv_path, metadata = _write_fixture(source)
                # Explicit inert gas data covers the unchanged governed transport
                # domain. This is a software fixture, not a CFD solve or tolerance.
                import csv, hashlib

                with csv_path.open(newline="") as stream:
                    reader = csv.DictReader(stream)
                    names = reader.fieldnames
                    rows = list(reader)
                interface = json.loads((CONFIG / "gas_field_interface.json").read_text())
                domain = interface["runtime_artifact_contract"]["domain"]
                radii = [
                    domain["minimum_radius_mm"] + (domain["maximum_radius_mm"] - domain["minimum_radius_mm"]) * i / 9
                    for i in range(10)
                ]
                axial = [
                    domain["minimum_z_mm"] + (domain["maximum_z_mm"] - domain["minimum_z_mm"]) * i / 9
                    for i in range(10)
                ]
                if scenario == "insufficient_gas_coverage":
                    axial = list(range(10))
                for row in rows:
                    row["r_mm"] = radii[int(row["r_index"])]
                    row["z_mm"] = axial[int(row["z_index"])]
                with csv_path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=names)
                    writer.writeheader()
                    writer.writerows(rows)
                meta = json.loads(metadata.read_text())
                meta["grid"] = {"r_values_mm": radii, "z_values_mm": axial}
                meta["field_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                if scenario == "bad_gas_quality":
                    meta["solution_summary"]["mass_balance_relative_error"] = 1.0
                metadata.write_text(json.dumps(meta))
                identity = dict(
                    project="dual_cone_tandem_quadrupole_ion_interface",
                    run_id=source.name,
                    mode="axisymmetric_gas_flow_screening",
                )
                config = source / "run_config.json"
                config.write_text(json.dumps(identity))
                inputs = {}
                for key, filename in (
                    ("gas_flow_science", "gas_flow_science.json"),
                    ("comsol_solver_numerics", "comsol_solver_numerics.json"),
                    ("resolved_geometry", "resolved_geometry.json"),
                ):
                    path = source / filename
                    path.write_bytes((CONFIG / filename).read_bytes())
                    inputs[key] = file_record(path, "required_evidence")
                manifest = source / "run_manifest.json"
                manifest.write_text(
                    json.dumps(
                        dict(
                            schema_version=2,
                            role="simulation_run_manifest",
                            status="success",
                            **identity,
                            run_config=file_record(config, "required_evidence"),
                            inputs=inputs,
                            outputs=[
                                file_record(csv_path, "required_evidence"),
                                file_record(metadata, "required_evidence"),
                            ],
                        )
                    )
                )
                record_capacity_object(
                    artifact_root,
                    path=source,
                    object_class="light_evidence",
                    bytes_count=sum(path.stat().st_size for path in source.iterdir()),
                    status="ready",
                    owner="inert-gas-fixture",
                )
                reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")
                sds = root / "sds"
                sds.mkdir()
                for name in ("collision_sds.lua", "mbmr.dat", "textfilelib.lua", "arraylib.lua", "m_defs.dat"):
                    (sds / name).write_text("INERT_SDS_NOT_NATIVE")
                stage = root / "stages.json"
                stage.write_text(
                    json.dumps(
                        dict(
                            schema_version=1,
                            role="execution_stage_policy",
                            stages=dict(
                                dual_cone_transport=dict(
                                    limits=dict(
                                        wall_clock_seconds=120,
                                        transient_run_directory_bytes=64 * 1024**2,
                                        process_tree_working_set_bytes=1024**3,
                                        minimum_system_available_memory_bytes=1,
                                        compact_final_retained_bytes=64 * 1024**2,
                                        automatic_retry_count=0,
                                    ),
                                    artifact_retention=dict(policy_version=1, **{"class": "compact"}, reason=None),
                                )
                            ),
                        )
                    )
                )
                if scenario in {"sync", "async", "invalid_bool", "invalid_key"}:
                    document = json.loads(stage.read_text())
                    runtime = {"simion_allow_asynchronous_io": scenario == "async"}
                    if scenario == "invalid_bool":
                        runtime["simion_allow_asynchronous_io"] = "false"
                    if scenario == "invalid_key":
                        runtime["unknown_runtime_key"] = False
                    document["stages"]["dual_cone_transport"]["runtime"] = runtime
                    stage.write_text(json.dumps(document))
                context = replace(context, stage_policy_path=stage)
                calls = []

                def observed(_context, **kwargs):
                    args = kwargs["arguments"]
                    observed_exit = 0
                    if scenario in {"sync", "async"}:
                        self.assertEqual(args[:3], ["--nogui", "--noprompt", "--lua"])
                        self.assertIn("d.allow_asynchronous_io=" + str(scenario == "async").lower(), args[3])
                    else:
                        self.assertNotIn("--lua", args)
                    run = kwargs["working_directory"]
                    solver = run / "transport/solver/simion"
                    result = run / "transport/results"
                    row = {"arguments": list(args), "guards": kwargs.get("immutable_input_records", ())}
                    calls.append(row)
                    if "build_frontend_geometry.lua" in " ".join(args):
                        (solver / "dual_cone_tandem.pa#").write_bytes(b"INERT_RAW_NOT_PA")
                        (solver / "dual_cone_tandem.pa-surf").write_bytes(b"INERT_SURFACE")
                        (solver / "dual_cone_surface.csv").write_text("0,0,0,0.25,nil,nil\n")
                        stdout = "BUILD_GEOMETRY=PASS ROLE=dual_cone\n"
                    elif "refine_rf_field_family.lua" in " ".join(args):
                        for eid in (0, 1, 2, 3, 11, 12, 21, 22):
                            (solver / ("dual_cone_tandem.pa" + str(eid))).write_bytes(b"INERT_RESPONSE_NOT_PA")
                        stdout = "INDEPENDENT_RF_REFINE=PASS\n"
                    elif "audit_rf_field_family.lua" in " ".join(args):
                        (run / "results/field_audit.json").write_text(
                            '{"status":"success","checked_domains":["dual_cone"]}'
                        )
                        self.assertEqual(len(row["guards"]), 11)
                        stdout = "INDEPENDENT_RF_FIELDS_READBACK=PASS\n"
                    elif "build_tracking_iob.lua" in " ".join(args):
                        self.assertEqual(
                            kwargs["environment"]["DUAL_CONE_SIMION_RUN_CONFIG_LUA"], str(solver / "run_config.lua")
                        )
                        if scenario.startswith("native_"):
                            # The ACTUAL public action has already materialized this spec.
                            # Never rewrite its seed/bootstrap/field paths in this fixture.
                            from common.contracts.test_dual_cone_iob import HARNESS

                            index = next(
                                i for i, value in enumerate(args) if str(value).endswith("build_tracking_iob.lua")
                            )
                            specification, mode, path_helper = args[index + 1 : index + 4]
                            code = HARNESS[: HARNESS.index("arg={arg[1],mode,arg[5]}")]
                            code = code.replace(
                                "local result={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,electrode_numbers=spec.instances[1].response_ids}",
                                "local g=spec.instances[1].grid;local result={nx=g.nx,ny=g.ny,nz=g.nz,dx_mm=g.dx_mm,dy_mm=g.dy_mm,dz_mm=g.dz_mm,electrode_numbers=spec.instances[1].response_ids}",
                            )
                            code = code.replace(
                                "local g=spec.instances[1].grid;",
                                "local g=spec.instances[1].grid;if path and path:match('iob_seed_placeholder_') then g={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1} end;",
                            )
                            code = code.replace(
                                "function result:load()self.path=self.filename end",
                                "function result:load()self.path=self.filename;for _,key in ipairs{'nx','ny','nz','dx_mm','dy_mm','dz_mm'} do self[key]=spec.instances[1].grid[key] end end",
                            )
                            code = code.replace(
                                "return x,y,z end", "return x*row.grid.dx_mm,y*row.grid.dy_mm,z*row.grid.dz_mm end", 1
                            )
                            code += (
                                "\narg={arg[1],mode,"
                                + json.dumps(str(path_helper))
                                + "}\nassert(loadfile("
                                + json.dumps(str(args[index]))
                                + "))()\n"
                            )
                            harness = root / "actual-public-iob.lua"
                            harness.write_text(code)
                            environment = {**os.environ, **kwargs["environment"]}
                            self.assertNotEqual(
                                environment["MASS_SPECTROMETRY_RUN_DIRECTORY"],
                                environment["MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"],
                            )
                            tested = subprocess.run(
                                [str(LUA), str(harness), str(specification), str(mode), "valid"],
                                cwd=root,
                                env=environment,
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            stdout = tested.stdout
                            observed_exit = tested.returncode
                            if observed_exit:
                                print("ACTUAL_PUBLIC_IOB_LUA_FAILURE=" + tested.stderr)
                        else:
                            if "build" in args:
                                (solver / "transport.iob").write_bytes(b"INERT_NOT_IOB")
                            else:
                                self.assertTrue((solver / "transport.iob").is_file())
                            stdout = (
                                "DUAL_CONE_TRACKING_IOB=PASS\n"
                                if "build" in args
                                else "DUAL_CONE_TRACKING_IOB_REOPEN=PASS\n"
                            )
                    else:
                        guarded = {Path(record["path"]).name: record for record in row["guards"]}
                        for name in (
                            "dual_cone_tandem.pa#",
                            "dual_cone_tandem.pa-surf",
                            "dual_cone_tandem.pa0",
                            "dual_cone_surface.csv",
                            "transport.iob",
                            "transport.lua",
                            "transport.fly2",
                            "run_config.lua",
                            "simion_rf_drive.lua",
                            "gas_field_runtime.lua",
                            "compiled_gas_field.lua",
                            "collision_sds_binding.lua",
                            "gas_source_states.lua",
                            "cylindrical_ion_source.csv",
                            "collision_sds.lua",
                            "mbmr.dat",
                            "textfilelib.lua",
                            "arraylib.lua",
                            "m_defs.dat",
                        ):
                            self.assertIn(name, guarded)
                        for eid in (1, 2, 3, 11, 12, 21, 22):
                            self.assertIn("dual_cone_tandem.pa" + str(eid), guarded)
                        audit_guards = next(
                            call["guards"]
                            for call in calls
                            if "audit_rf_field_family.lua" in " ".join(call["arguments"])
                        )
                        for record in audit_guards:
                            self.assertEqual(guarded[Path(record["path"]).name], record)
                        self.assertIn("fly", args)
                        if scenario.startswith("native_"):
                            self.assertEqual(args[-1], str(solver / "transport.iob"))
                            self.assertEqual(args[args.index("--particles") + 1], str(solver / "transport.fly2"))
                        self.assertNotIn("refine", args)
                        from common.simion.test_analyze_terminal_plane import HEADER

                        (result / "particle_final_state.csv").write_text(
                            HEADER + "".join(f"{pid},10,25.5,25.5,121.75,0,0,1,0\n" for pid in range(1, 101))
                        )
                        (result / "trajectory_samples.csv").write_text("INERT_TRAJECTORY_NOT_SCIENCE\n")
                        stdout = "status,Fly completed. 100 splats, 0.1 seconds\n"
                        self.assertIn("DUAL_CONE_SIMION_RUN_CONFIG_LUA", kwargs["environment"])
                    for name in ("stdout_path", "stderr_path", "usage_path"):
                        kwargs[name].write_text(stdout if name == "stdout_path" else "{}")
                    return dict(
                        observation=dict(
                            exit_code=observed_exit,
                            root_process_id=os.getpid(),
                            root_process_started_at_utc_ticks=12345,
                        ),
                        host_release=dict(
                            inherited=False, token="inert", error=None, result=dict(status="released", token="inert")
                        ),
                    )

                from msplatform.backends.simion.dual_cone_transport_execution import _write_spec as actual_write_spec

                def write_spec(session, name, value):
                    if name == "tracking_model" and scenario in {"native_missing_bootstrap", "native_wrong_bootstrap"}:
                        value = copy.deepcopy(value)
                        value["bootstrap_paths"] = (
                            []
                            if scenario == "native_missing_bootstrap"
                            else [
                                str(Path(value["seed_iob"]).parent / "wrong_seed_directory/iob_seed_placeholder_01.pa0")
                            ]
                        )
                    return actual_write_spec(session, name, value)

                with (
                    patch("msplatform.execution.run_session.run_observed_process", side_effect=observed),
                    patch(
                        "msplatform.backends.simion.dual_cone_transport_execution._write_spec", side_effect=write_spec
                    ),
                ):
                    if scenario in {"native_missing_bootstrap", "native_wrong_bootstrap"}:
                        with self.assertRaisesRegex(ValueError, "native operation has no successful closed writer"):
                            run_gas_assisted_transport(
                                resolved_path=CONFIG / "resolved_geometry.json",
                                numerics_path=CONFIG / "simion_solver_numerics.json",
                                science_path=CONFIG / "ion_transport_science.json",
                                interface_path=CONFIG / "gas_field_interface.json",
                                gas_science_path=CONFIG / "gas_flow_science.json",
                                source_spec_path=CONFIG / "cylindrical_ion_source.json",
                                gas_field_reference=reference,
                                collision_sds_dir=sds,
                                context=context,
                            )
                        self.assertEqual(len(calls), 4)
                        self.assertFalse(any("fly" in row["arguments"] for row in calls))
                        self.assertEqual(load_capacity_protection_leases(artifact_root)["audit"], [])
                        continue

                    if scenario == "bad_gas_quality":
                        from msplatform.results.gas_field import read_gas_field

                        self.assertEqual(read_gas_field(reference).data.row_count, 100)
                        with self.assertRaisesRegex(ValueError, "mass-balance contract"):
                            run_gas_assisted_transport(
                                resolved_path=CONFIG / "resolved_geometry.json",
                                numerics_path=CONFIG / "simion_solver_numerics.json",
                                science_path=CONFIG / "ion_transport_science.json",
                                interface_path=CONFIG / "gas_field_interface.json",
                                gas_science_path=CONFIG / "gas_flow_science.json",
                                source_spec_path=CONFIG / "cylindrical_ion_source.json",
                                gas_field_reference=reference,
                                collision_sds_dir=sds,
                                context=context,
                            )
                        self.assertEqual(calls, [])
                        self.assertEqual(list(context.workspace.glob("artifacts/projects/*/runs/20*")), [])
                        self.assertEqual(load_capacity_protection_leases(artifact_root)["audit"], [])
                        continue
                    if scenario in {"invalid_bool", "invalid_key"}:
                        with self.assertRaisesRegex(ValueError, "runtime only accepts explicit boolean"):
                            run_gas_assisted_transport(
                                resolved_path=CONFIG / "resolved_geometry.json",
                                numerics_path=CONFIG / "simion_solver_numerics.json",
                                science_path=CONFIG / "ion_transport_science.json",
                                interface_path=CONFIG / "gas_field_interface.json",
                                gas_science_path=CONFIG / "gas_flow_science.json",
                                source_spec_path=CONFIG / "cylindrical_ion_source.json",
                                gas_field_reference=reference,
                                collision_sds_dir=sds,
                                context=context,
                            )
                        self.assertEqual(calls, [])
                        self.assertEqual(list(context.workspace.glob("artifacts/projects/*/runs/20*")), [])
                        continue
                    if scenario == "insufficient_gas_coverage":
                        with self.assertRaisesRegex(ValueError, "governed axial domain") as caught:
                            run_gas_assisted_transport(
                                resolved_path=CONFIG / "resolved_geometry.json",
                                numerics_path=CONFIG / "simion_solver_numerics.json",
                                science_path=CONFIG / "ion_transport_science.json",
                                interface_path=CONFIG / "gas_field_interface.json",
                                gas_science_path=CONFIG / "gas_flow_science.json",
                                source_spec_path=CONFIG / "cylindrical_ion_source.json",
                                gas_field_reference=reference,
                                collision_sds_dir=sds,
                                context=context,
                            )
                        self.assertEqual(calls, [])
                        self.assertFalse(
                            any(
                                "Workflow finalization failed" in note
                                for note in getattr(caught.exception, "__notes__", [])
                            )
                        )
                        failed = next(context.workspace.glob("artifacts/projects/*/runs/20*/run_manifest.json"))
                        self.assertEqual(json.loads(failed.read_text())["status"], "failed")
                        self.assertEqual(load_capacity_protection_leases(artifact_root)["audit"], [])
                        continue
                    else:
                        product = run_gas_assisted_transport(
                            resolved_path=CONFIG / "resolved_geometry.json",
                            numerics_path=CONFIG / "simion_solver_numerics.json",
                            science_path=CONFIG / "ion_transport_science.json",
                            interface_path=CONFIG / "gas_field_interface.json",
                            gas_science_path=CONFIG / "gas_flow_science.json",
                            source_spec_path=CONFIG / "cylindrical_ion_source.json",
                            gas_field_reference=reference,
                            collision_sds_dir=sds,
                            context=context,
                        )
                self.assertEqual(len(calls), 6)
                self.assertEqual(product.metadata["execution_count"], 100)
                self.assertEqual(product.metadata["saved_field_reuse"], "not_implemented")
                metrics = json.loads(product.data_path("metrics").read_text())
                self.assertEqual(metrics["terminal_code_counts"], {"0": 100})
                self.assertEqual(load_capacity_protection_leases(context.workspace / "artifacts")["audit"], [])
                self.assertFalse(any(product.manifest_location.parent.rglob("*.pa0")))


class TimeStepContractTests(unittest.TestCase):
    def test_invalid_maximum_step_fails_before_preparation_outputs(self):
        from msplatform.backends.simion.dual_cone_transport import prepare_transport

        for value in (None, 0, -1, True, float("nan"), float("inf")):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                numerics = request()["numerics"]
                numerics["trajectory"]["maximum_step_us"] = value
                path = root / "numerics.json"
                path.write_text(json.dumps(numerics))
                output = root / "not_created"
                with self.assertRaisesRegex(ValueError, "maximum_step_us"):
                    prepare_transport(
                        output,
                        mode="gas_assisted_transport",
                        resolved_path=CONFIG / "resolved_geometry.json",
                        numerics_path=path,
                        science_path=CONFIG / "ion_transport_science.json",
                        interface_path=CONFIG / "gas_field_interface.json",
                        gas_science_path=CONFIG / "gas_flow_science.json",
                        source_spec_path=CONFIG / "cylindrical_ion_source.json",
                    )
                self.assertFalse(output.exists())

    @unittest.skipUnless(LUA.is_file(), "plain Lua unavailable; no native fallback")
    def test_actual_program_consumes_selected_maximum_step_with_existing_rf_cap(self):
        from msplatform.backends.simion.dual_cone_transport import _render_run_config

        for maximum in (0.0125, 0.03):
            with self.subTest(maximum=maximum), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                values = request()
                values["numerics"]["trajectory"]["maximum_step_us"] = maximum
                config = root / "run.lua"
                config.write_text(
                    _render_run_config(
                        mode="c0_gem_smoke",
                        science=values["science"],
                        numerics=values["numerics"],
                        resolved=values["resolved"],
                        solver=root,
                    )
                )
                # Stock Lua has no SIMION adjustable declaration preprocessor.
                original_program = native_resource_path("dual_cone_gas_assisted_transport.lua")
                program = root / "dual_cone_gas_assisted_transport.lua"
                program.write_text(original_program.read_text(encoding="utf-8").replace("adjustable ", ""),
                                   encoding="utf-8")
                text = """simion={workbench_program=function()end}
segment={}
local original=loadfile
function loadfile(path)
 if path:match('simion_rf_drive.lua$') then
  return function() return {new=function() return {timestep_cap_us=.02} end} end
 end
 return original(path)
end
os.getenv=function(name) assert(name=='DUAL_CONE_SIMION_RUN_CONFIG_LUA');return %s end
dofile(%s)
ion_time_step=1
segment.tstep_adjust()
assert(ion_time_step==%s,'declared maximum timestep unused: '..tostring(ion_time_step))
""" % (json.dumps(str(config)), json.dumps(str(program)), repr(min(maximum, 0.02)))
                script = root / "test.lua"
                script.write_text(text)
                result = subprocess.run([str(LUA), str(script)], cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
