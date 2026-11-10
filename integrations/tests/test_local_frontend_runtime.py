"""Pure source/batch materialization; dummy fields are never native evidence."""
from __future__ import annotations

from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import sysconfig
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from msplatform.execution.retention import file_record
from msplatform.backends.simion.particle_batching import batch_plan_from_dispatch, plan_single_wave_batches
from msplatform.execution.simion_dispatch import plan_simion_dispatch, plan_adaptive_followup
from msplatform.backends.simion.tracking_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE, STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
)
from integrations.tests.test_local_frontend_workflow import fixture, REPO
from msplatform.workflows.local_frontend.prepare import prepare_local_frontend
from msplatform.workflows.local_frontend.runtime import (
    _phase, prepare_dispatch_request, materialize_batches,
)


class LocalFrontendRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.addCleanup(self._make_writable)
        path, _ = fixture(self.workspace)
        self.run = self.workspace/"owned_run"
        prepare_local_frontend(path, self.run, self.workspace, run_id="20261022_120000__test__python__local-runtime")
        self.times = [0., 20., 40., 60., 100.]
        self.fields = self.run/"simion/local_frontend_fields"
        self.fields.mkdir(parents=True)
        kinds = {"carrier_off": "coarse_frontend.carrier_off.pa", "rf_differential_unit": "coarse_frontend.rf_differential.pa",
                 "pulse_delta": "coarse_frontend.pulse_delta.pa"}
        working_points = []
        for kind, name in kinds.items():
            target = self.fields/name
            target.write_bytes(b"PURE_TEST_DUMMY__NOT_A_NATIVE_PA")
            target.chmod(stat.S_IREAD)
            working_points.append(dict(**file_record(target), kind=kind, read_only=True,
                                       validation="pure_fixture__no_native_field_claim"))
        bank = dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
                    runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
                    dynamic_roles=[dict(role="coarse_frontend", instance_index=1, carrier_pa_basename=kinds["carrier_off"],
                                        rf_differential_pa_basenames=[kinds["rf_differential_unit"]], rf_reference_voltage_v=1.0,
                                        pulse_delta_pa_basename=kinds["pulse_delta"])])
        bank_path = self.fields/"standalone_field_bank.json"
        bank_path.write_text(json.dumps(bank), encoding="utf-8")
        self.field_stage = dict(schema_version=1, role="rf_oatof_local_frontend_field_stage", status="success",
                                working_points=working_points, field_bank_path=str(bank_path), field_bank_record=file_record(bank_path))
        self._write_stage()

    def _make_writable(self):
        for path in self.workspace.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)

    def _write_stage(self):
        (self.run/"inputs/local_frontend_field_stage_receipt.json").write_text(json.dumps(self.field_stage), encoding="utf-8")

    def test_all_original_rows_births_and_ids_are_partitioned_once_with_full_gui(self):
        original = (self.run/"inputs/release_global.csv").read_bytes()
        before_fields = {p.name: p.read_bytes() for p in self.fields.glob("*.pa")}
        result = materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 3), 40., self.times)
        self.assertEqual(result["scheduled_particle_ids"], list(range(1, 101)))
        self.assertEqual(result["pending_particle_ids"], [])
        self.assertEqual(result["gui_case"]["expected_particle_ids"], list(range(1, 101)))
        self.assertFalse(result["gui_fly_performed"])
        self.assertEqual(result["saved_default_replay_verification"], "not_requested")
        self.assertFalse(result["default_replay_policy"]["requested"])
        self.assertEqual(result["default_replay_policy"]["scope"], "not_requested")
        with (self.run/"inputs/release_global.csv").open(newline="") as handle:
            expected = list(csv.DictReader(handle))
        actual = []
        for case in result["batches"]:
            with Path(case["source_record"]["path"]).open(newline="") as handle:
                actual.extend(csv.DictReader(handle))
            self.assertEqual(case["merge_offset"], 0)
            self.assertEqual(case["simion_particle_id_offset"], 0)
            self.assertEqual(case["environment"]["OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET"], "0")
            self.assertEqual(case["frame_id"], result["frame_id"])
            self.assertNotIn("--trajectory-quality", case["fly_arguments"])
            self.assertEqual(case["fly_arguments"][case["fly_arguments"].index("--programs")+1], "1")
            self.assertEqual(Path(case["program_path"]).stem, Path(case["iob_path"]).stem)
            self.assertTrue(Path(case["carrier_reference"]).is_absolute())
            self.assertEqual(Path(case["iob_builder_arguments"][4]), Path(case["working_directory"])/"build_iob_spec.lua")
            self.assertEqual(case["iob_builder_arguments"][5], "build")
            self.assertEqual(case["iob_reopen_arguments"][5], "verify")
            program = Path(case["program_path"]).read_text(encoding="utf-8")
            self.assertIn("sim_trajectory_quality=8", program)
            self.assertNotRegex(program, r"(?m)^\s*sim_trajectory_image_control\s*=")
            self.assertIn("LOCAL_DISPLAY_CONTROL:", program)
            self.assertIn("function segment.load()", program)
            self.assertIn("single_flight_source_particle_id={"+",".join(map(str, case["expected_particle_ids"]))+"}", program)
            self.assertEqual(Path(case["particle_input"]).read_text().count("standard_beam"), case["count"])
        self.assertEqual(actual, expected)
        self.assertEqual((self.run/"inputs/release_global.csv").read_bytes(), original)
        self.assertEqual({p.name: p.read_bytes() for p in self.fields.glob("*.pa")}, before_fields)
        self.assertEqual(len(list((self.run/"simion").rglob("*.pa"))), 3)
        seed_roots = set()
        for case in [*result["batches"], result["gui_case"]]:
            seed = Path(case["seed_record"]["path"])
            seed_roots.add(seed.parent)
            self.assertEqual(seed.read_bytes(),
                (REPO/"src/msplatform/backends/simion/resources/1_instance_seed.iob").read_bytes())
            self.assertEqual(seed.stat().st_size, 20856)
            self.assertEqual({p.name for p in seed.parent.iterdir()}, {"1_instance_seed.iob"})
            self.assertEqual(case["generated_paths"][1], str(seed.parent/"iob_seed_placeholder_01.pa0"))
            self.assertEqual(len(case["iob_pa_guard_records"]), 3)
            self.assertNotIn("seed_placeholder_record", case)
        self.assertEqual(len(seed_roots), len(result["batches"])+1)

    def test_case_boundaries_reject_changed_controls_bank_and_closed_iob(self):
        from msplatform.workflows.local_frontend.runtime import verify_case

        result = materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 1), 40., self.times)
        case = result["gui_case"]
        metadata = Path(case["working_directory"])/"case_metadata.json"
        self.assertEqual(verify_case(self.run, metadata, stage="prebuild")["fields"], 3)
        targets = [Path(case["source_record"]["path"]), Path(case["program_record"]["path"]),
                   Path(self.field_stage["field_bank_path"])]
        for target in targets:
            with self.subTest(target=target.name):
                original = target.read_bytes()
                target.write_bytes(original+b"changed")
                try:
                    with self.assertRaises(AssertionError):
                        verify_case(self.run, metadata, stage="prebuild")
                finally:
                    target.write_bytes(original)
        # This controlled file tests the closed-creation contract only; no vendor built it.
        iob = Path(case["iob_path"])
        iob.write_bytes(b"PURE_TEST_ONLY_NOT_NATIVE_IOB")
        verify_case(self.run, metadata, stage="postbuild")
        self.assertEqual(verify_case(self.run, metadata, stage="postreopen")["status"], "validated")
        iob.write_bytes(b"CHANGED_AFTER_CLOSED_CREATION")
        with self.assertRaises(AssertionError):
            verify_case(self.run, metadata, stage="preflight")

    def test_closed_iob_records_keep_classified_policy_without_a_size_cap(self):
        from types import SimpleNamespace
        from msplatform.io import manifest_records
        from msplatform.execution import retention
        from msplatform.workflows.local_frontend import runtime

        result = materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 1), 40., self.times)
        case = result["gui_case"]
        metadata = Path(case["working_directory"]) / "case_metadata.json"
        iob = Path(case["iob_path"])
        iob.write_bytes(b"PURE_TEST_ONLY_NOT_NATIVE_IOB")
        # The original classified facade does not add a role to small records.
        self.assertEqual(runtime.file_record(iob), retention.file_record(iob))
        self.assertEqual(runtime.file_record(iob), manifest_records.file_record(iob))
        self.assertNotIn("retention_role", runtime.file_record(iob))
        actual_stat = Path.stat
        actual_hash = manifest_records.file_sha256
        size = 8 * 1024 * 1024
        readers = []

        def metadata_at_reader_boundary(path, *args, **kwargs):
            value = actual_stat(path, *args, **kwargs)
            if path == iob:
                return SimpleNamespace(st_size=size, st_mode=value.st_mode, st_mtime_ns=value.st_mtime_ns)
            return value

        def buffered(path):
            if path == iob:
                readers.append(path)
                return "A" * 64
            return actual_hash(path)

        # Only stat/hash are synthetic; execute the real generated case checks.
        # No large payload or native IOB is created. IOBs are policy-classified
        # lightweight_optional and retain the buffered reader, unlike native PAs.
        with patch.object(Path, "stat", metadata_at_reader_boundary), \
             patch.object(manifest_records, "file_sha256", buffered), \
             patch.object(manifest_records, "file_sha256_unbuffered", side_effect=AssertionError("IOB is not a native PA")):
            self.assertEqual(runtime.verify_case(self.run, metadata, stage="postbuild")["fields"], 3)
            self.assertEqual(runtime.verify_case(self.run, metadata, stage="postreopen")["status"], "validated")
            recorded = json.loads(metadata.with_name("iob_identity.json").read_text())
            self.assertEqual(recorded, retention.file_record(iob))
            self.assertEqual(recorded["bytes"], size)
        self.assertEqual(len(readers), 3)
        self.assertEqual(iob.read_bytes(), b"PURE_TEST_ONLY_NOT_NATIVE_IOB")

    def test_public_formal_observation_and_followup_keep_bootstrap_and_all_pending(self):
        request = dict(solver="SIMION", field_kind="rf", particle_count=100, independent_particles=True, rf_steps_per_period=64)
        dispatch = plan_simion_dispatch(request, [], available_memory_bytes=8*1024**3, total_physical_memory_bytes=16*1024**3, logical_processors=16)
        prefix = materialize_batches(self.run, "discovery", batch_plan_from_dispatch(dispatch), 201., self.times)
        self.assertEqual(prefix["scheduled_particle_ids"], list(range(1, 11)))
        self.assertEqual(prefix["pending_particle_ids"], list(range(11, 101)))
        first = prefix["batches"][0]
        self.assertEqual(first["fly_arguments"][first["fly_arguments"].index("--default-num-particles")+1], "100")
        self.assertEqual(first["count"], 10)
        self.assertEqual(Path(first["particle_input"]).read_text().count("standard_beam"), 10)
        before = Path(first["program_path"]).read_bytes()
        followup = plan_adaptive_followup(dispatch, 1024**2, observed_cpu_percent=6.25,
                                         available_memory_bytes=8*1024**3, total_physical_memory_bytes=16*1024**3,
                                         first_batch_completed=True)
        final = materialize_batches(self.run, "discovery", followup, 201., self.times)
        self.assertEqual(final["scheduled_particle_ids"], list(range(1, 101)))
        self.assertEqual(final["pending_particle_ids"], [])
        self.assertEqual(sum(case["count"] for case in final["batches"][1:]), 90)
        for case in final["batches"]:
            self.assertEqual(case["fly_arguments"][case["fly_arguments"].index("--default-num-particles")+1], "100")
            self.assertEqual(Path(case["particle_input"]).read_text().count("standard_beam"), case["count"])
        self.assertEqual(final["batches"][0]["program_path"], first["program_path"])
        self.assertEqual(Path(first["program_path"]).read_bytes(), before)
        self.assertNotEqual(final["receipt_path"], prefix["receipt_path"])

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows junction fixture requires PowerShell 7")
    def test_frozen_module_loaded_through_junction_prepares_real_dispatch(self):
        snapshot = self.workspace / "runtime_snapshot"
        shutil.copytree(REPO/"src/msplatform", snapshot/"src/msplatform")
        alias = self.workspace / "execution_alias"
        script = self.workspace / "junction.ps1"
        script.write_text("param($Alias,$Target)\nNew-Item -ItemType Junction -Path $Alias -Target $Target -ErrorAction Stop|Out-Null\n",
                          encoding="utf-8")
        result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(alias), str(snapshot)],
                                capture_output=True, text=True, encoding="utf-8", cwd=snapshot, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(alias.rmdir)
        self.assertEqual(alias.resolve(), snapshot.resolve())
        code = """import sys,json,importlib.abc
from pathlib import Path
root,run=map(Path,sys.argv[1:3]);sys.path[:0]=[str(root/'src'),*json.loads(sys.argv[3])]
class NoRoot(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','projects','integrations'}:raise AssertionError('root fallback: '+fullname)
sys.meta_path.insert(0,NoRoot())
from msplatform.workflows.local_frontend import runtime as module
assert Path(module.__file__).is_relative_to(root)
assert Path(module.__file__)!=Path(module.__file__).resolve()
module._phase(run,'extraction',40.,[0.,20.,40.,60.,100.])
context=module._context(run);prepared=module.prepare_dispatch_request(run,'extraction',context=context)
assert prepared['particle_count']==100
assert prepared['request']['frontend_cell_mm_xyz']==json.loads((run/'inputs/numerics.json').read_text())['cell_mm_xyz']
materializer=context['code_records']['materializer']
assert Path(materializer['path'])==(root/'src/msplatform/workflows/local_frontend/runtime.py').resolve()
for key,name in module._PROGRAM_SOURCES.items():
 source=root/'src/msplatform/backends/simion/resources'/name
 assert context['sources'][key]==source.read_text(encoding='utf-8-sig')
 assert context['code_records'][key]==module.file_record(source)
for name,loaded in tuple(sys.modules.items()):
 if name.startswith('msplatform') and getattr(loaded,'__file__',None):
  assert Path(loaded.__file__).resolve().is_relative_to((root/'src').resolve()),loaded.__file__
assert not (run/'inputs/local_program_sources').exists()
print('COLD_CANONICAL_LOCAL_RUNTIME=PASS')
"""
        roots = list(dict.fromkeys(sysconfig.get_path(key) for key in ("purelib", "platlib")))
        result = subprocess.run([sys.executable,"-I","-S","-c",code,str(alias),str(self.run),json.dumps(roots)],
                                cwd=self.workspace,capture_output=True,text=True,encoding="utf-8",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("COLD_CANONICAL_LOCAL_RUNTIME=PASS",result.stdout)

    def test_dispatch_binds_phase_source_code_fields_and_uses_public_scheduler(self):
        _phase(self.run, "extraction", 40., self.times)
        with patch("msplatform.workflows.local_frontend.runtime.file_sha256", wraps=file_sha256) as hashed:
            result = prepare_dispatch_request(self.run, "extraction")
        self.assertTrue(all(Path(call.args[0]).suffix != ".pa" for call in hashed.call_args_list))
        request = result["request"]
        plan = plan_simion_dispatch(request, [], available_memory_bytes=8*1024**3, total_physical_memory_bytes=16*1024**3, logical_processors=16)
        self.assertEqual(plan["particle_count"], 100)
        self.assertEqual(plan["resource_identity"]["case_input_sha256"], request["case_input_sha256"])
        self.assertTrue(request["independent_particles"])
        with self.assertRaisesRegex(ValueError, "frozen"):
            materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 2), 41., self.times)

    def test_missing_overlapping_or_invalid_population_never_materializes_cases(self):
        valid = plan_single_wave_batches(100, 2)
        bad = deepcopy(valid)
        bad["batches"][1]["particle_id_min"] = 50
        for plan in (bad, {**valid, "particle_count": 99}, {**valid, "batches": valid["batches"][:1], "batch_count": 1}):
            with self.assertRaises(ValueError):
                materialize_batches(self.run, "discovery", plan, 201., self.times)
        self.assertFalse((self.run/"simion/discovery").exists())

    def test_field_bank_binds_current_ordered_per_volt_response(self):
        from msplatform.workflows.local_frontend.runtime import _fields
        path = Path(self.field_stage["field_bank_path"])
        original = json.loads(path.read_text())
        self.assertEqual(_fields(self.run)["bank"], original)
        for change in ({"rf_differential_pa_basenames": ["wrong.pa"]},
                       {"rf_differential_pa_basenames": []},
                       {"rf_differential_pa_basenames": ["a.pa", "b.pa"]},
                       {"rf_reference_voltage_v": 10000.0},
                       {"rf_differential_pa_basename": "old.pa"}):
            bank = deepcopy(original)
            bank["dynamic_roles"][0].update(change)
            path.write_text(json.dumps(bank), encoding="utf-8")
            self.field_stage["field_bank_record"] = file_record(path)
            self._write_stage()
            with self.subTest(change=change), self.assertRaises(ValueError):
                _fields(self.run)

    def test_changed_clock_fields_and_mutable_pa_fail_closed(self):
        path = self.run/"inputs/source_identity.json"
        clock = json.loads(path.read_text())
        changed = deepcopy(clock)
        changed["native_clock_projection"]["native_fly2_tob_us"] = 5
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "clock"):
            materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 1), 40., self.times)
        path.write_text(json.dumps(clock), encoding="utf-8")
        Path(self.field_stage["working_points"][0]["path"]).chmod(stat.S_IREAD | stat.S_IWRITE)
        with self.assertRaisesRegex(ValueError, "read-only"):
            materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 1), 40., self.times)

    def test_phase_requires_explicit_times_and_terminal_owner_is_not_reused(self):
        for times in ([], [1, 0], [1, 1], [float("nan")]):
            with self.assertRaises(ValueError):
                materialize_batches(self.run, "discovery", plan_single_wave_batches(100, 1), 201., times)
        (self.run/"run_manifest.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sealed"):
            materialize_batches(self.run, "discovery", plan_single_wave_batches(100, 1), 201., self.times)

    def test_discovery_rejects_pulse_during_the_particle_age_horizon(self):
        with self.assertRaisesRegex(ValueError, "OFF discovery"):
            materialize_batches(self.run, "discovery", plan_single_wave_batches(100, 1), 100., self.times)
        self.assertFalse((self.run/"simion/discovery").exists())

    @unittest.skipUnless(Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe").is_file(), "plain Lua interpreter unavailable")
    def test_tracking_wrapper_projects_bootstrap_and_keeps_rf_dualcone_aliases(self):
        from msplatform.backends.simion.source import lua_value

        canonical = self.workspace/"canonical"
        execution = self.workspace/"execution"
        helper = REPO/"src/msplatform/execution/resources/native_run_path.lua"
        wrapper = REPO/"src/msplatform/backends/simion/resources/build_tracking_iob.lua"
        harness = self.workspace/"projection.lua"
        harness.write_text(r"""local wrapper,specfile,helper,expected=arg[1],arg[2],arg[3],arg[4]
expected=expected:gsub('\\','/')
local original=loadfile;local checked=false
loadfile=function(path)
 if path:gsub('\\','/'):match('/iob_core%.lua$') then return function() return function(spec,mode,project)
  assert(spec.seed_iob:gsub('\\','/')==expected..'/seed/one.iob')
  assert(spec.output_iob:gsub('\\','/')==expected..'/output.iob')
  assert(spec.bootstrap_paths[1]:gsub('\\','/')==expected..'/seed/iob_seed_placeholder_01.pa0')
  assert(spec.instances[1].path:gsub('\\','/')==expected..'/fields/carrier.pa0')
  assert(project(spec.seed_iob)==spec.seed_iob,'execution alias was projected twice')
  checked=true
 end end end
 return original(path)
end
arg={specfile,'build',helper};dofile(wrapper);assert(checked,'actual wrapper did not call canonical core')
""", encoding="utf-8")
        for role in ("independent_rf_tracking_iob", "dual_cone_tracking_iob"):
            for already_projected in (False, True):
                with self.subTest(role=role, already_projected=already_projected):
                    base = execution if already_projected else canonical
                    spec = dict(schema_version=1, role=role, seed_iob=(base/"seed/one.iob").as_posix(),
                        output_iob=(base/"output.iob").as_posix(),
                        bootstrap_paths=[(base/"seed/iob_seed_placeholder_01.pa0").as_posix()],
                        instances=[dict(path=(base/"fields/carrier.pa0").as_posix())], response_fields=[])
                    request = self.workspace/"projection_spec.lua"
                    request.write_text("return "+lua_value(spec)+"\n", encoding="utf-8")
                    env = dict(os.environ, MASS_SPECTROMETRY_RUN_DIRECTORY=str(canonical),
                               MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=str(execution))
                    result = subprocess.run([shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe",
                        str(harness),str(wrapper),str(request),str(helper),execution.as_posix()],
                        env=env,cwd=self.workspace,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe").is_file(), "plain Lua interpreter unavailable")
    def test_plain_lua_iob_builder_keeps_exact_companions_and_shared_absolute_carrier(self):
        result = materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 1), 40., self.times)
        case = result["gui_case"]
        paths = [Path(case[key]) for key in ("program_path", "particle_input")]
        before = [path.read_bytes() for path in paths]
        builder = Path(case["working_directory"])/"build_tracking_iob.lua"
        harness = self.workspace/"builder_harness.lua"
        harness.write_text(r"""local builder,specpath,pathhelper,wrong=arg[1],arg[2],arg[3],arg[4]
local spec=dofile(specpath)
local row=spec.instances[1];local grid=row.grid;local saved
local function pa(path)
 local value={path=path,nx=grid.nx,ny=grid.ny,nz=grid.nz,dx_mm=grid.dx_mm,dy_mm=grid.dy_mm,dz_mm=grid.dz_mm}
 function value:size(x,y,z) self.nx,self.ny,self.nz=x,y,z end
 function value:save(output) self.path=output;local f=assert(io.open(output,'wb'));f:write('PURE_NEUTRAL_BOOTSTRAP');f:close() end
 function value:load() self.path=self.filename;for key,v in pairs(grid) do self[key]=v end end
 function value:close() end
 return value
end
local function instance(array)
 local item={pa=array,ox=0,oy=0,oz=0}
 function item:_debug_update_size() end
 function item:pa_to_wb_orient(x,y,z) return x,y,z end
 function item:pa_to_wb_coords(x,y,z) return self.x+x*self.pa.dx_mm,self.y+y*self.pa.dy_mm,self.z+z*self.pa.dz_mm end
 return item
end
simion={pas={},wb={instances={}}}
function simion.pas:open(path) return pa(path) end
function simion.pas:close() end
function simion.command(command)
 if command=='"'..spec.seed_iob..'"' then
  local array=pa(spec.bootstrap_paths[1]);array.nx,array.ny,array.nz=3,3,3
  simion.wb.instances={instance(array)}
 elseif command=='"'..spec.output_iob..'"' then
  simion.wb.instances={saved}
  if wrong=='wrong_carrier' then saved.pa.path=spec.output_iob..'.not_the_carrier.pa' end
 else error('unexpected actual workbench command '..command) end
end
function simion.wb:load_particles(path) assert(path==spec.output_iob:gsub('%.iob$','.fly2')) end
function simion.wb:save(path)
 assert(path==spec.output_iob);saved=self.instances[1]
 for _,ext in ipairs({'.lua','.fly2'}) do local f=assert(io.open(path:gsub('%.iob$',ext),'wb'));f:write('seed association');f:close() end
 local f=assert(io.open(path,'wb'));f:write('PURE_STUB_NOT_NATIVE_IOB');f:close()
end
arg={specpath,'build',pathhelper};dofile(builder)
assert(io.open(spec.bootstrap_paths[1],'rb')==nil,'owned bootstrap must be removed')
arg={specpath,'verify',pathhelper};dofile(builder)
""", encoding="utf-8")
        command = [shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe", str(harness), str(builder),
                   case["iob_builder_arguments"][4],case["iob_builder_arguments"][6]]
        completed = subprocess.run(command, cwd=self.workspace, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        self.assertEqual([path.read_bytes() for path in paths], before)
        self.assertIn("LOCAL_FRONTEND_IOB=PASS INSTANCES=1", completed.stdout)
        self.assertIn("LOCAL_FRONTEND_IOB_REOPEN=PASS INSTANCES=1", completed.stdout)
        rejected = subprocess.run([*command,"wrong_carrier"],cwd=self.workspace,capture_output=True,text=True,timeout=30)
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn("saved PA path differs",rejected.stdout+rejected.stderr)


if __name__ == "__main__":
    unittest.main()
