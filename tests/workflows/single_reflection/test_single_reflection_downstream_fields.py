"""Current downstream resource planning and response-audit contracts."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.simion.downstream_fields import preflight_frontend_resources

ROOT = Path(__file__).resolve().parents[3]
LUA = Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")


class FrontendResourcePreflightTests(unittest.TestCase):
    def design(self):
        return dict(schema_version=3, role="frontend_native_field_design", surface="none",
            domains=[dict(domain_id="parent", boundary_policy="native_zero_neumann",
                          dimensions=dict(nx=3, ny=4, nz=5))],
            working_points=[dict(kind=kind) for kind in ("carrier_off", "rf_reference", "pulse_delta")])

    def test_actual_direct_sequence_counts_common_fields_and_two_open_arrays(self):
        with patch("subprocess.run") as native:
            result = preflight_frontend_resources(self.design(),
                dict(transient_run_directory_bytes=1441, process_tree_working_set_bytes=1201))
        native.assert_not_called()
        self.assertEqual(result["domain_arrays"], [dict(domain_id="parent", nodes=60,
                                                      disk_payload_bytes=480, ram_bytes=600)])
        self.assertEqual(result["runtime_array_count"], 3)
        self.assertEqual(result["working_point_count"], 3)
        self.assertEqual(result["mandatory_new_disk_payload_bytes_lower_bound"], 3*480)
        self.assertEqual(result["cache_miss_new_disk_payload_bytes_lower_bound"], 5*480)
        self.assertEqual(result["construction_process_array_bytes_lower_bound"], 2*600)
        self.assertEqual(result["flight_process_array_bytes_lower_bound"], 3*600)

    def test_below_and_exact_floor_reject_but_positive_headroom_is_only_lower_bound_admission(self):
        for field, floor in (("transient_run_directory_bytes", 1440), ("process_tree_working_set_bytes", 1200)):
            for value in (floor-1, floor, floor+1):
                limits = dict(transient_run_directory_bytes=1441, process_tree_working_set_bytes=1201)
                limits[field] = value
                with self.subTest(field=field, value=value), patch("subprocess.run") as native:
                    if value <= floor:
                        with self.assertRaisesRegex(ValueError, "requires positive headroom.*excluded"):
                            preflight_frontend_resources(self.design(), limits)
                    else:
                        result = preflight_frontend_resources(self.design(), limits)
                        self.assertIn("process_overhead_excluded", result["scope"])
                    native.assert_not_called()

    def test_all_partial_and_no_member_reuse_keep_full_flight_memory(self):
        limits = dict(transient_run_directory_bytes=10000, process_tree_working_set_bytes=10000)
        for reused, missing in (([], 3), (['carrier_off', 'rf_reference'], 1),
                                (['carrier_off', 'rf_reference', 'pulse_delta'], 0)):
            with self.subTest(reused=reused):
                result = preflight_frontend_resources(self.design(), limits, reused_member_ids=reused)
                self.assertEqual(result['missing_working_member_count'], missing)
                self.assertEqual(result['mandatory_new_disk_payload_bytes_lower_bound'], missing*480)
                self.assertEqual(result['cache_miss_new_disk_payload_bytes_lower_bound'],
                                 (missing+2)*480 if missing else 0)
                self.assertEqual(result['flight_process_array_bytes_lower_bound'], 1800)
        for invalid in (['absent'], ['carrier_off', 'carrier_off']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                preflight_frontend_resources(self.design(), limits, reused_member_ids=invalid)
        multi = self.design()
        multi['working_points'][1:2] = [dict(kind='rf_reference', working_point_id='rf_reference_01'),
                                       dict(kind='rf_reference', working_point_id='rf_reference_02')]
        result = preflight_frontend_resources(multi, limits,
            reused_member_ids=['carrier_off', 'rf_reference_01', 'rf_reference_02'])
        self.assertEqual(result['missing_working_member_count'], 1)
        self.assertEqual(result['flight_process_array_bytes_lower_bound'], 2400)

    def test_unknown_design_is_not_given_a_guessed_resource_policy(self):
        for key, value in (("schema_version", 2), ("working_points", None),
                           ("working_points", []),
                           ("working_points", [dict(kind="carrier_off"), dict(kind="unknown")])):
            design = self.design()
            design[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "ordered OFF"):
                preflight_frontend_resources(design, {})

    def test_two_field_accelerator_has_no_rf_payload_or_budget_reservation(self):
        design = self.design()
        design['working_points'] = [dict(kind=kind) for kind in ('carrier_off', 'pulse_delta')]
        result = preflight_frontend_resources(design,
            dict(transient_run_directory_bytes=961, process_tree_working_set_bytes=1201))
        self.assertEqual(result['working_point_count'], 2)
        self.assertEqual(result['runtime_array_count'], 2)
        self.assertEqual(result['mandatory_new_disk_payload_bytes_lower_bound'], 960)
        self.assertEqual(result['cache_miss_new_disk_payload_bytes_lower_bound'], 1920)
        self.assertEqual(result['flight_process_array_bytes_lower_bound'], 1200)
        self.assertEqual(result['construction_process_array_bytes_lower_bound'], 1200)
        with self.assertRaisesRegex(ValueError, 'requires positive headroom'):
            preflight_frontend_resources(design,
                dict(transient_run_directory_bytes=960, process_tree_working_set_bytes=1201))

    def test_two_domains_budget_common_payload_and_construction_scratch(self):
        for parent, patch_nodes in ((60, 24), (24, 60)):
            design = self.design()
            design['domains'][0]['dimensions'] = dict(nx=2, ny=3, nz=parent // 6)
            design['domains'].append(dict(domain_id='entrance_refinement', parent_domain_id='parent',
                boundary_policy='parent_dirichlet', dimensions=dict(nx=2, ny=3, nz=patch_nodes // 6)))
            total = parent + patch_nodes
            result = preflight_frontend_resources(design, dict(transient_run_directory_bytes=24*total+1,
                process_tree_working_set_bytes=max(20*parent, 10*total, 20*patch_nodes)+1))
            self.assertEqual(result['runtime_array_count'], 6)
            self.assertEqual(result['mandatory_new_disk_payload_bytes_lower_bound'], 24*total)
            self.assertEqual(result['cache_miss_new_disk_payload_bytes_lower_bound'],
                             max(40*parent, 24*parent+40*patch_nodes))
            self.assertEqual(result['construction_process_array_bytes_lower_bound'], 1200)
            self.assertEqual(result['flight_process_array_bytes_lower_bound'], 30*total)
            with self.assertRaisesRegex(ValueError, 'requires positive headroom'):
                preflight_frontend_resources(design, dict(transient_run_directory_bytes=24*parent+1,
                    process_tree_working_set_bytes=1000000))

    def test_sequential_domain_peak_retains_prior_payload_and_never_overlaps_raw_scratch(self):
        limits = dict(transient_run_directory_bytes=100000, process_tree_working_set_bytes=100000)
        for fine_nx in (2, 5, 10):
            design = self.design()
            design['domains'].append(dict(domain_id='entrance_refinement', parent_domain_id='parent',
                boundary_policy='parent_dirichlet', dimensions=dict(nx=fine_nx, ny=4, nz=5)))
            parent, fine = 60, fine_nx*20
            for reused, missing in (([],3), (['carrier_off','rf_reference'],1),
                                    (['carrier_off','rf_reference','pulse_delta'],0)):
                with self.subTest(fine_nodes=fine, missing=missing):
                    result = preflight_frontend_resources(design, limits, reused_member_ids=reused)
                    peak = max(8*(missing+2)*parent,
                               8*(missing*parent+(missing+2)*fine),
                               8*missing*(parent+fine)) if missing else 0
                    self.assertEqual(result['cache_miss_new_disk_payload_bytes_lower_bound'], peak)
                    self.assertGreaterEqual(peak, result['mandatory_new_disk_payload_bytes_lower_bound'])
                    self.assertEqual(result['flight_process_array_bytes_lower_bound'], 30*(parent+fine))
                    if missing:
                        self.assertLess(peak, 8*(missing+2)*(parent+fine))
        # Cumulative final payload exceeds either isolated-domain payload for
        # comparable sizes; a max of independent domain budgets undercounts it.
        result = preflight_frontend_resources(design, limits)
        self.assertGreater(result['cache_miss_new_disk_payload_bytes_lower_bound'],
                           max(40*parent, 40*fine))

    def test_missing_reordered_unknown_or_wrong_parent_domains_are_rejected(self):
        parent = self.design()['domains'][0]
        fine = dict(domain_id='entrance_refinement', parent_domain_id='other',
                    boundary_policy='parent_dirichlet', dimensions=dict(nx=2, ny=3, nz=4))
        for domains in ([], [fine], [fine, parent], [parent, fine],
                        [{**parent, 'boundary_policy':'zero_dirichlet'}],
                        [parent, {**fine, 'domain_id':'unimplemented'}]):
            design = self.design()
            design['domains'] = domains
            with self.subTest(domains=domains), self.assertRaisesRegex(ValueError, 'ordered parent'):
                preflight_frontend_resources(design, {})

    def test_actual_held_off_member_counts_drive_resource_floor_without_pulse(self):
        for rf_count in (0,2,3):
            with self.subTest(rf_count=rf_count):
                design=self.design()
                design['working_points']=[dict(kind='carrier_off')]+[
                    dict(kind='rf_reference',working_point_id=f'rf_reference_{i:02d}') for i in range(1,rf_count+1)]
                result=preflight_frontend_resources(design,dict(transient_run_directory_bytes=100000,process_tree_working_set_bytes=100000))
                self.assertEqual(result['working_point_count'],rf_count+1)
                self.assertEqual(result['flight_process_array_bytes_lower_bound'],600*(rf_count+1))
                self.assertEqual(result['construction_process_array_bytes_lower_bound'],1200)

class DownstreamResponseAuditTests(unittest.TestCase):
    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_plain_lua_audit_reads_current_response_paths_and_rejects_bad_grid(self):
        from tests.contracts.test_simion_fields_execution import field_case
        from msplatform.backends.simion.native_plans import _plan_downstream_solve_with_assets

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, assets, numerics, resources, _ = field_case(root/'author')
            plan, bindings = _plan_downstream_solve_with_assets(model, raw_geometry_assets=assets,
                working_directory=root/'work', convergence_v=numerics['downstream_convergence_v'],
                exporter_resource=resources['export_standalone_pa.lua'],
                verifier_resource=resources['audit_downstream_fields.lua'])
            reflectron = next(row for row in bindings if row['role'] == 'reflectron')
            self.assertTrue(reflectron['response_paths'])
            for name, text in plan.materializations.items():
                target = Path(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8', newline='\n')
            script = root/'audit_test.lua'
            script.write_text("""local target=assert(arg[1]);local spec=assert(arg[2]);local wrong=arg[3]=='wrong'
local original=dofile
local data=original(spec)
data.assets={data.assets[3]}
data.output=data.output..'.mock'
dofile=function(path) if path==spec then return data else return original(path) end end
simion={pas={close=function() end}}
function simion.pas:open()
 local a=data.assets[1];local p={refinable=false,symmetry=a.symmetry,potential_type='electric'}
 for k,v in pairs(a.grid) do p[k]=v end
 if wrong then p.nx=p.nx+1 end
 function p:potential(x) for _,s in ipairs(a.endpoint_samples) do if s.x==x then return s.voltage end end;error('unexpected sample') end
 function p:close() end
 return p
end
arg={spec};original(target)
""", encoding='utf-8', newline='\n')
            target = resources['audit_downstream_fields.lua']
            spec = root/'work/audit.lua'
            bad = subprocess.run([str(LUA), str(script), str(target), str(spec), 'wrong'],
                capture_output=True, text=True, cwd=root, timeout=10)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('nx differs', bad.stderr)
            good = subprocess.run([str(LUA), str(script), str(target), str(spec)],
                capture_output=True, text=True, cwd=root, timeout=10)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertIn('DOWNSTREAM_NATIVE_AUDIT=PASS', good.stdout)

if __name__ == "__main__":
    unittest.main()
