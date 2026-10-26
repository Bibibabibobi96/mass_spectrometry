"""Pure source/batch materialization; dummy fields are never native evidence."""
from __future__ import annotations

from copy import deepcopy
import csv
import json
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.contracts.write_run_manifest import file_record
from common.simion.particle_batching import batch_plan_from_dispatch, plan_single_wave_batches
from common.simion.resource_scheduler import plan_simion_dispatch, plan_adaptive_followup
from integrations.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE, STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
)
from integrations.tests.test_local_frontend_workflow import fixture, REPO
from integrations.workflows.local_frontend.prepare import prepare_local_frontend
from integrations.workflows.local_frontend.runtime import (
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
        self.assertEqual(result["saved_default_replay_verification"], "pending")
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
            self.assertIn("--trajectory-quality", case["fly_arguments"])
            self.assertTrue(Path(case["carrier_reference"]).is_absolute())
            self.assertEqual(Path(case["iob_builder_arguments"][5]), Path(case["iob_path"]))
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
        seed_root = self.run/"simion/iob_seed"
        self.assertEqual({p.name for p in seed_root.iterdir()}, {"1_instance_seed.iob", "iob_seed_placeholder_01.pa0"})
        source_root = REPO/"common/simion/assets/iob_instance_seeds"
        for target in seed_root.iterdir():
            self.assertEqual(target.read_bytes(), (source_root/target.name).read_bytes())
            self.assertLess(len(str(target).encode("utf-16-le"))//2, 260)
        for case in [*result["batches"], result["gui_case"]]:
            self.assertEqual(Path(case["seed_record"]["path"]).parent, seed_root)
            self.assertEqual(Path(case["seed_placeholder_record"]["path"]).parent, seed_root)
            self.assertEqual(case["iob_builder_arguments"][4], str(seed_root/"1_instance_seed.iob"))

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
        relative = Path("integrations/workflows/local_frontend/runtime.py")
        resources = [relative, Path("integrations/runtime/build_single_flight_program.py"),
                     Path("common/simion/rf_drive.lua"),
                     Path("common/simion/voltage_waveforms.lua"),
                     Path("integrations/runtime/single_flight_pulse_hook.lua"),
                     Path("integrations/runtime/single_flight_frontend_hook.lua")]
        for name in resources:
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        seeds = snapshot / "common/simion/assets/iob_instance_seeds"
        seeds.mkdir(parents=True)
        # These bytes exercise freezing only; no vendor parses them or flies.
        (seeds / "1_instance_seed.iob").write_bytes(b"PURE_TEST_IOB_SEED")
        (seeds / "iob_seed_placeholder_01.pa0").write_bytes(b"PURE_TEST_PLACEHOLDER")
        alias = self.workspace / "execution_alias"
        script = self.workspace / "junction.ps1"
        script.write_text("param($Alias,$Target)\nNew-Item -ItemType Junction -Path $Alias -Target $Target -ErrorAction Stop|Out-Null\n",
                          encoding="utf-8")
        result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(alias), str(snapshot)],
                                capture_output=True, text=True, encoding="utf-8", cwd=snapshot, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(alias.rmdir)
        self.assertEqual(alias.resolve(), snapshot.resolve())
        imported = alias / relative
        spec = importlib.util.spec_from_file_location("frozen_local_frontend_runtime", imported)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(Path(module.__file__), imported)
        self.assertNotEqual(imported, imported.resolve())
        with self.assertRaises(ValueError):
            imported.relative_to(snapshot.resolve())
        module._phase(self.run, "extraction", 40., self.times)
        context = module._context(self.run)
        prepared = module.prepare_dispatch_request(self.run, "extraction", context=context)
        self.assertEqual(prepared["particle_count"], 100)
        self.assertTrue(Path(prepared["dispatch_request_path"]).is_file())
        materializer = context["code_records"]["materializer"]
        self.assertEqual(Path(materializer["path"]), (snapshot/relative).resolve())
        self.assertEqual(materializer, file_record(snapshot/relative))
        for key, relative_source in module._PROGRAM_SOURCES.items():
            self.assertEqual(context["sources"][key],(snapshot/relative_source).read_text(encoding="utf-8-sig"))
            self.assertEqual(context["code_records"][key],file_record(snapshot/relative_source))
        self.assertFalse((self.run/"inputs/local_program_sources").exists())
        self.assertEqual(prepared["request"]["frontend_cell_mm_xyz"],
                         json.loads((self.run / "inputs/numerics.json").read_text())["cell_mm_xyz"])

    def test_dispatch_binds_phase_source_code_fields_and_uses_public_scheduler(self):
        _phase(self.run, "extraction", 40., self.times)
        with patch("integrations.workflows.local_frontend.runtime.file_sha256", wraps=file_sha256) as hashed:
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
        from integrations.workflows.local_frontend.runtime import _fields
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

    @unittest.skipUnless(Path(shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe").is_file(), "plain Lua interpreter unavailable")
    def test_plain_lua_iob_builder_keeps_exact_companions_and_shared_absolute_carrier(self):
        result = materialize_batches(self.run, "extraction", plan_single_wave_batches(100, 1), 40., self.times)
        case = result["gui_case"]
        paths = [Path(case[key]) for key in ("program_path", "particle_input")]
        before = [path.read_bytes() for path in paths]
        builder = Path(case["working_directory"])/"build_iob.lua"
        harness = self.workspace/"builder_harness.lua"
        harness.write_text("""local builder,seed,output,field=arg[1],arg[2],arg[3],arg[4]
local item={pa={nz=2}}
function item.pa:load() assert(self.filename==field) end
function item:_debug_update_size() end
simion={wb={instances={item}}}
function simion.command(command) assert(command=='"'..seed..'"') end
function simion.wb:load_particles(path) assert(path==output:gsub('%.iob$','.fly2')) end
function simion.wb:save(path)
  assert(path==output and item.x==1 and item.y==2 and item.z==3)
  assert(item.az==0 and item.el==0 and item.rt==0 and item.scale==1)
  for _,ext in ipairs({'.lua','.fly2'}) do
    local f=assert(io.open(path:gsub('%.iob$',ext),'wb'));f:write('seed association');f:close()
  end
  local f=assert(io.open(path,'wb'));f:write('PURE_STUB_NOT_NATIVE_IOB');f:close()
end
arg={seed,output,field,'1','2','3'}
dofile(builder)
""", encoding="utf-8")
        command = [shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe", str(harness), str(builder),
                   case["seed_record"]["path"], case["iob_path"], case["carrier_reference"]]
        completed = subprocess.run(command, cwd=self.workspace, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        self.assertEqual([path.read_bytes() for path in paths], before)
        self.assertIn("INSTANCES=1", completed.stdout)


if __name__ == "__main__":
    unittest.main()
