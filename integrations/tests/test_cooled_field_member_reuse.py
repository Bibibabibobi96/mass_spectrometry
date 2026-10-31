"""Small public-cache transactions; inert bytes never claim native solutions."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_cooled_frontend import cooled_request_fixture, REPO
from integrations.workflows.cooled_frontend.prepare import prepare_cooled_frontend
from integrations.workflows.cooled_frontend import runtime
from integrations.runtime.build_single_flight_program import _standalone_dynamic_field_lua


class CooledFieldMemberReuseTests(unittest.TestCase):
    def test_actual_lua_pulse_multiplies_the_projected_source_field(self):
        lua = Path("C:/Program Files/SIMION-2020/lua.exe")
        if not lua.is_file():
            self.skipTest("plain Lua unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for scale in (2., 0., -1.):
                spec = dict(role="accelerator", instance_index=1, carrier_pa_basename="carrier.pa",
                    rf_differential_pa_paths=[], pulse_delta_pa_basename="pulse.pa",
                    pulse_delta_pa_path="pulse.pa", pulse_delta_scale=scale)
                program = _standalone_dynamic_field_lua([spec]) + r'''
local pa={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,symmetry='planar',potential_type='electric',path='carrier.pa'}
function pa:field_vc() return 1,2,3 end
local instance={pa=pa,filename='carrier.pa',wb_to_pa_coords=function() return 0,0,0 end}
simion={wb={instances={instance}},pas={open=function() return pa end}}
single_flight_pulse={is_active_at=function() return true end}
ion_instance=1;ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0
ion_dvoltsx_gu=10;ion_dvoltsy_gu=20;ion_dvoltsz_gu=30
single_flight_initialize_standalone_dynamic_fields()
single_flight_apply_standalone_dynamic_field(instance,0)
''' + f"assert(ion_dvoltsx_gu==10-({scale}) and ion_dvoltsy_gu==20-2*({scale}) and ion_dvoltsz_gu==30-3*({scale}))\n"
                path = root / "pulse.lua"
                path.write_text(program, encoding="utf-8", newline="\n")
                result = subprocess.run([str(lua), str(path)], cwd=root, capture_output=True,
                    text=True, encoding="utf-8", timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def prepared(self, root):
        author, _ = cooled_request_fixture(root)
        run = root / "artifacts/projects/instrument_assembly/runs/20261022_120000__test__python__members"
        prepare_cooled_frontend(author, run, REPO, root, run_id=run.name)
        (run / "inputs/native_discovery.json").write_text(json.dumps(dict(
            bytes=1, sha256="A" * 64, file_version="INERT_TEST")), encoding="utf-8")
        return run

    def test_seven_real_transactions_bind_distinct_generations_without_aggregate_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                run = self.prepared(root)
                bundle = runtime.field_cache_plan(run, cache_root=root / "cache")
                completed = {}
                for member in bundle["domains"][0]["members"]:
                    kind = member["member_id"]
                    first = runtime.advance_field_cache(run, member)
                    self.assertEqual(len(first["missing_files"]), 1)
                    payload = Path(first["build_directory"]) / member["filenames"][0]
                    payload.write_bytes(b"INERT_NOT_A_NATIVE_SOLUTION" * 3)
                    sealed = runtime.advance_field_cache(run, member)
                    self.assertEqual(sealed["action_required"], "verify")
                    report = run / "inputs" / (kind + "_inert_verification.txt")
                    report.write_text("INERT_PUBLIC_TRANSACTION_ONLY", encoding="utf-8")
                    status = runtime.advance_field_cache(run, member, report)
                    status["refine_performed"] = False
                    completed[kind] = status
                result = runtime.finalize_field_stage(run, bundle, completed)
                rows = result["working_points"]
                self.assertEqual(tuple(row["kind"] for row in rows), runtime.KINDS)
                self.assertEqual(len({row["generation_directory"] for row in rows}), 7)
                self.assertEqual(result["receipt"]["aggregate_pa_copy_bytes"], 0)
                self.assertEqual(result["receipt"]["actual_refine_count"], 0)
                with patch.object(runtime, "file_sha256", wraps=runtime.file_sha256) as identities:
                    resolved = runtime.fields(run)
                for row in rows:
                    actual = resolved["records"][row["kind"]]
                    self.assertEqual({key: actual[key] for key in row}, row)
                self.assertFalse(any(Path(call.args[0]).suffix == ".pa"
                                     for call in identities.call_args_list))
                for member in bundle["domains"][0]["members"]:
                    hit = runtime.advance_field_cache(run, member)
                    self.assertEqual(hit["action_required"], "complete")
                    self.assertEqual(hit["generation_directory"],
                                     completed[member["member_id"]]["generation_directory"])
            finally:
                for path in root.rglob("*"):
                    if path.is_file():
                        path.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_voltage_change_affects_only_pulse_and_requires_exact_operator_and_vector(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = self.prepared(root)
            before = runtime.field_member_plans(run, cache_root=root / "cache", freeze=False)
            plan_path = run / "inputs/cooled_field_plan.json"
            plan = json.loads(plan_path.read_text())
            pulse = next(row for row in plan["working_points"] if row["kind"] == "pulse_delta")
            pulse["electrode_voltages_v"] = {key: value * 2 for key, value in pulse["electrode_voltages_v"].items()}
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            after = runtime.field_member_plans(run, cache_root=root / "cache", freeze=False)
            for old, new in zip(before["domains"][0]["members"], after["domains"][0]["members"]):
                if old["member_id"] == "pulse_delta":
                    self.assertNotEqual(old["cache_key"], new["cache_key"])
                    self.assertEqual(runtime.pulse_reuse_scale(new["identity"], old["identity"]), 2.)
                    changed = copy.deepcopy(new["identity"])
                    changed["boundary_policy"] = "zero_neumann"
                    self.assertIsNone(runtime.pulse_reuse_scale(changed, old["identity"]))
                    changed = copy.deepcopy(new["identity"])
                    changed["working_points"][0]["electrode_voltages_v"]["1"] += 1
                    self.assertIsNone(runtime.pulse_reuse_scale(changed, old["identity"]))
                else:
                    self.assertEqual(old["cache_key"], new["cache_key"])

    def test_legacy_projection_requires_all_frozen_operator_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = self.prepared(root)
            members = runtime.field_member_plans(run, freeze=False)["domains"][0]["members"]
            first = members[0]["identity"]
            legacy = copy.deepcopy(first)
            legacy["geometry"].pop("bounds_mm")
            legacy["working_points"] = [dict(member["identity"]["working_points"][0],
                output_basename=member["filenames"][0]) for member in members]
            legacy["rf_reference_voltage_v"] = 1.
            legacy["builder_identity"] = dict(operating_point=first["builder_identity"]["operating_builder"],
                standalone_export=first["builder_identity"]["exporter"])
            original = copy.deepcopy(legacy)
            for member, point in zip(members, legacy["working_points"]):
                self.assertEqual(runtime._legacy_member_identity(legacy, point), member["identity"])
            self.assertEqual(legacy, original)
            for key in ("grid_phase", "simion_identity", "builder_identity", "boundary_policy"):
                missing = copy.deepcopy(legacy)
                missing.pop(key)
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    runtime._legacy_member_identity(missing, legacy["working_points"][0])


if __name__ == "__main__":
    unittest.main()
