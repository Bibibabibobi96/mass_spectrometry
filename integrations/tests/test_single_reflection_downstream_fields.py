"""Pure command/evidence contracts; fixture PA bytes are never scientific fields."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from integrations.tests.test_single_reflection_preparation import fixture
from integrations.workflows.single_reflection_flight.prepare import prepare
from integrations.workflows.single_reflection_flight.downstream_fields import _live_run, plan_downstream_fields, preflight_frontend_resources, publish_downstream_fields

ROOT = Path(__file__).resolve().parents[2]
LUA = Path("C:/Program Files/SIMION-2020/lua.exe")


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


class DownstreamFieldsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        request, self.run, _ = fixture(self.root)
        self.preparation = prepare(request, self.run)
        (self.run / "run_config.json").write_text(json.dumps(dict(project="instrument_assembly")))
        self.planned = plan_downstream_fields(self.preparation, self.run, snapshot_root=ROOT)
        self.plan_path = Path(self.planned["plan_record"]["path"])
        self.plan = json.loads(self.plan_path.read_text())

    def unplanned_provider(self, name, edits):
        run = self.root / name
        (run / "inputs").mkdir(parents=True)
        (run / "run_config.json").write_text(json.dumps(dict(project="instrument_assembly")))
        resolved = json.loads(Path(self.plan["oatof_resolved_record"]["path"]).read_text())
        for path, value in edits:
            target = resolved
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        provider = run / "inputs/oatof.json"
        provider.write_text(json.dumps(resolved), encoding="utf-8")
        geometry = run/'inputs/frontend_geometry.json'
        geometry.write_bytes(Path(self.preparation['outputs']['frontend_geometry']['path']).read_bytes())
        from integrations.runtime.single_flight_frontend import native_frontend_instances
        instance_id = native_frontend_instances(json.loads(geometry.read_text())['composition_plan'])[1]
        return run, dict(role="single_reflection_geometry_preparation",
            input_records={'instance_design__'+instance_id: file_record(provider)},
            outputs=dict(frontend_geometry=file_record(geometry)))

    def test_declared_source_reuses_native_publication_without_staging(self):
        producer = self.root / "sealed_producer"
        producer.mkdir()
        assets, outputs = [], []
        for role in ("flight_tube", "reflectron", "detector"):
            names = [role + ".pa"] if role == "reflectron" else [role + suffix for suffix in (".pa#", ".pa0", ".pa1", ".pa-surf")]
            family = []
            for name in names:
                path = producer / name
                path.write_bytes(b"INERT_SOURCE_PA_NOT_NATIVE_EVIDENCE")
                row = {**file_record(path), "read_only": True}
                family.append(row)
                outputs.append(file_record(path))
            assets.append(dict(role=role,
                representation="standalone_voltageized_static_pa" if role == "reflectron" else "run_private_native_static_family",
                carrier_record=family[0] if role == "reflectron" else family[1],
                family_records=[] if role == "reflectron" else family))
        manifest_path = producer / "run_manifest.json"
        manifest_path.write_text(json.dumps(dict(role="simulation_run_manifest", status="success", outputs=outputs)))
        command_path = self.run / "inputs/downstream_field_source_command_plan.json"
        command_path.write_text(self.plan_path.read_text())
        receipt_path = self.run / "inputs/downstream_field_source_receipt.json"
        receipt_path.write_text(json.dumps(dict(schema_version=1,
            role="single_reflection_downstream_field_preparation", status="success",
            native_family_origin="generated_in_producer_run", run_directory=str(producer),
            oatof_resolved_record=self.plan["oatof_resolved_record"], assets=assets,
            command_plan_record=file_record(command_path))))
        frozen_manifest = self.run / "inputs/downstream_field_source_manifest.json"
        frozen_manifest.write_text(manifest_path.read_text())
        preparation = json.loads(json.dumps(self.preparation))
        # The existing preparation is immutable in production; this fixture only
        # models the explicit records added by the preparation boundary.
        preparation["input_records"].update(dict(
            downstream_fields={**file_record(receipt_path), "source_path": str(producer / "field_receipt.json")},
            downstream_fields_manifest={**file_record(frozen_manifest), "source_path": str(manifest_path)},
            downstream_fields_command_plan={**file_record(command_path), "source_path": str(producer / "command_plan.json")}))
        result = plan_downstream_fields(preparation, self.run, snapshot_root=ROOT)
        self.assertEqual(result["steps"], [])
        self.assertEqual(result["array_estimates"], [])
        self.assertEqual(result["reserved_run_array_payload_bytes"], 0)
        self.assertEqual(result["publication"], dict(receipt_record=preparation["input_records"]["downstream_fields"]))
        original_receipt = receipt_path.read_bytes()
        original_command = command_path.read_bytes()
        missing = producer / 'detector.pa-surf'
        original_payload = missing.read_bytes()
        for mutation, reason in (("provider", "provider"), ("native_builder", "native resources"),
                                 ("payload", "published PA path/size/identity")):
            with self.subTest(mutation=mutation):
                receipt = json.loads(original_receipt)
                command = json.loads(original_command)
                if mutation == "provider":
                    receipt["oatof_resolved_record"]["sha256"] = "F" * 64
                elif mutation == "native_builder":
                    command["resource_records"]["audit"]["sha256"] = "F" * 64
                else:
                    missing.unlink()
                command_path.write_text(json.dumps(command))
                receipt["command_plan_record"] = file_record(command_path)
                receipt_path.write_text(json.dumps(receipt))
                preparation["input_records"]["downstream_fields"] = file_record(receipt_path)
                preparation["input_records"]["downstream_fields_command_plan"] = file_record(command_path)
                with self.assertRaisesRegex(ValueError, reason):
                    plan_downstream_fields(preparation, self.run, snapshot_root=ROOT)
                if not missing.exists():
                    missing.write_bytes(original_payload)

    @unittest.skipUnless(os.name == "nt", "Windows execution junction semantics")
    def test_execution_junction_is_not_resolved_back_to_the_artifact_path(self):
        target = self.root / "long_artifact_run"
        target.mkdir()
        (target / "run_config.json").write_text(json.dumps(dict(project="instrument_assembly")))
        alias = self.root / "short_run"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                                 cwd=self.root, timeout=30, capture_output=True, text=True, check=False)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertEqual(_live_run(alias), alias.absolute())

    @unittest.skipUnless(os.name == "nt", "Windows execution junction semantics")
    def test_plan_keeps_execution_junction_for_native_arguments_but_accepts_canonical_records(self):
        fixture_root = self.root / "junction_fixture"
        fixture_root.mkdir()
        request, target, _ = fixture(fixture_root)
        preparation = prepare(request, target)
        (target / "run_config.json").write_text(json.dumps(dict(project="instrument_assembly")))
        alias = self.root / "short_plan_run"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                                 cwd=self.root, timeout=30, capture_output=True, text=True, check=False)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        plan = plan_downstream_fields(preparation, alias, snapshot_root=ROOT)
        document = json.loads(Path(plan["plan_record"]["path"]).read_text())
        self.assertEqual(document["run_directory"], str(alias.absolute()))
        reflectron = next(step for step in document["steps"] if step["name"] == "reflectron")
        self.assertTrue(reflectron["argv"][5].startswith(str(alias.absolute())))
        records = []
        for step in document["steps"]:
            row = dict(index=step["index"], argv=step["argv"], exit_code=0)
            for kind, text in (("stdout", step["success_marker"]), ("stderr", ""),
                               ("usage", json.dumps(dict(role="multipole_resource_usage", status="running",
                                                          failure_class=None, limit_name=None)))):
                path = target / f"logs/{step['index']}_{kind}.txt"
                path.parent.mkdir(exist_ok=True)
                path.write_text(text, encoding="utf-8")
                row[kind + "_record"] = file_record(path)
            records.append(row)
        for asset in document["assets"]:
            for name in asset["family_paths"] or [asset["carrier_path"]]:
                Path(name).write_bytes(b"UNIT TEST ONLY - NOT A PA")
        Path(document["audit_output"]).write_text(json.dumps(dict(
            role="single_reflection_downstream_native_audit", status="success",
            checked_assets=[dict(role=a["role"], grid=a["grid"]) for a in document["assets"]])))
        publication = publish_downstream_fields(Path(plan["plan_record"]["path"]), records)
        self.assertEqual(publication["receipt"]["run_directory"], str(alias.absolute()))

    def test_provider_array_limits_reject_before_staging_or_native(self):
        for estimate in self.plan["array_estimates"]:
            role = estimate["role"]
            key, unit = ("max_mib", 1024**2) if role == "detector" else ("max_gib", 1024**3)
            exact = estimate["provider_array_set_bytes"] / unit
            for accepted, limit in ((False, math.nextafter(exact, 0)), (True, exact)):
                with self.subTest(role=role, accepted=accepted):
                    run, preparation = self.unplanned_provider(f"{role}_{accepted}", [
                        (("simion_geometry_build", role, key), limit)])
                    with patch("subprocess.run") as native:
                        if accepted:
                            planned = plan_downstream_fields(preparation, run, snapshot_root=ROOT)
                            self.assertEqual(planned["array_estimates"], self.plan["array_estimates"])
                        else:
                            with self.assertRaisesRegex(ValueError, f"{role} provider array estimate.*{key}"):
                                plan_downstream_fields(preparation, run, snapshot_root=ROOT)
                            self.assertFalse((run / "simion/downstream_fields").exists())
                        native.assert_not_called()

    def test_run_payload_reservation_includes_frontend_and_future_downstream_before_staging(self):
        design_path = self.run / 'inputs/frontend_field_design.json'
        design = json.loads(design_path.read_text())
        floor = preflight_frontend_resources(design, dict(transient_run_directory_bytes=10**15,
            process_tree_working_set_bytes=10**15))
        downstream = math.ceil(sum(row['provider_array_set_bytes'] for row in self.plan['array_estimates'])
            + next(row['single_array_bytes'] for row in self.plan['array_estimates'] if row['role']=='reflectron'))
        reserved = downstream
        self.assertEqual(self.plan['reserved_run_array_payload_bytes'], downstream)
        for accepted, budget in ((False, reserved), (True, max(reserved, floor['mandatory_new_disk_payload_bytes_lower_bound'])+1)):
            run, preparation = self.unplanned_provider(f'reserve_{accepted}', [])
            (run/'inputs/frontend_field_design.json').write_bytes(design_path.read_bytes())
            limits = dict(transient_run_directory_bytes=budget, process_tree_working_set_bytes=10**15)
            with self.subTest(accepted=accepted), patch('subprocess.run') as native:
                if accepted:
                    planned = plan_downstream_fields(preparation,run,snapshot_root=ROOT,field_limits=limits)
                    self.assertEqual(planned['reserved_run_array_payload_bytes'],reserved)
                else:
                    with self.assertRaisesRegex(ValueError,'positive headroom'):
                        plan_downstream_fields(preparation,run,snapshot_root=ROOT,field_limits=limits)
                    self.assertFalse((run/'simion/downstream_fields').exists())
                native.assert_not_called()

    def test_declared_frontend_source_skips_private_field_preflight_and_reservation(self):
        design_path = self.run / 'inputs/frontend_field_design.json'
        design = json.loads(design_path.read_text())
        downstream = math.ceil(sum(row['provider_array_set_bytes'] for row in self.plan['array_estimates'])
            + next(row['single_array_bytes'] for row in self.plan['array_estimates'] if row['role'] == 'reflectron'))
        run, preparation = self.unplanned_provider('declared_frontend', [])
        (run / 'inputs/frontend_field_design.json').write_bytes(design_path.read_bytes())
        preparation['input_records']['frontend_fields'] = dict(path='frozen-producer-receipt')
        request_path = run/'inputs/request.json'
        request_path.write_text(json.dumps(dict(providers=dict(frontend_fields=dict(path='explicit-source')))))
        preparation['input_records']['request'] = file_record(request_path)
        limits = dict(transient_run_directory_bytes=downstream + 1, process_tree_working_set_bytes=1)
        with patch('subprocess.run') as native:
            planned = plan_downstream_fields(preparation, run, snapshot_root=ROOT, field_limits=limits)
        native.assert_not_called()
        self.assertEqual(planned['frontend_resource_lower_bounds']['mandatory_new_disk_payload_bytes_lower_bound'], 0)
        self.assertEqual(planned['frontend_resource_lower_bounds']['cache_miss_new_disk_payload_bytes_lower_bound'], 0)
        self.assertEqual(planned['frontend_resource_lower_bounds']['flight_process_array_bytes_lower_bound'],
                         10*len(design['working_points'])*sum(row['nodes'] for row in planned['frontend_resource_lower_bounds']['domain_arrays']))
        self.assertEqual(planned['reserved_run_array_payload_bytes'], downstream)

    def test_invalid_provider_numerics_fail_without_staging(self):
        cases = [
            (("simion_geometry_build", "flight_tube", "cell_axial_mm"), 0, "cell_axial_mm"),
            (("simion_geometry_build", "reflectron", "max_gib"), -1, "max_gib"),
            (("simion_geometry_build", "detector", "max_mib"), float("inf"), "max_mib"),
            (("geometry_mm", "flight_tube_wall"), -1, "flight_tube_wall"),
            (("geometry_mm", "L_flight"), -1e6, "near cap"),
            (("geometry_mm", "L_reflectron"), 1, "length"),
            (("geometry_mm", "ring_outer_r"), 0.01, "radii"),
            (("rings", "stage1_count"), 1.5, "positive integer"),
            (("electrodes_V", "midgrid"), float("nan"), "midgrid"),
            (("simion_geometry_build", "reflectron", "cell_axial_mm"), 0.37, "zero-width sheet"),
            (("simion_detector_marker", "absorber_thickness_mm"), 1e-6, "cell-span minimum"),
            (("simion_detector_marker", "front_margin_z_mm"), 1e-6, "cell-span minimum"),
            (("simion_detector_marker", "back_margin_z_mm"), 1e-6, "cell-span minimum"),
            (("simion_geometry_build", "detector", "margin_xy_mm"), 1e-6, "one xy cell"),
        ]
        for index, (path, value, message) in enumerate(cases):
            with self.subTest(path=path):
                run, preparation = self.unplanned_provider(f"invalid_{index}", [(path, value)])
                with patch("subprocess.run") as native, self.assertRaisesRegex(ValueError, message):
                    plan_downstream_fields(preparation, run, snapshot_root=ROOT)
                native.assert_not_called()
                self.assertFalse((run / "simion/downstream_fields").exists())

    def test_detector_half_cell_grid_and_budget_use_the_same_provider_dimensions(self):
        edits = [(("simion_geometry_build", "detector", "margin_xy_mm"), 1)]
        edits.extend((("simion_detector_marker", key), value) for key, value in dict(
            active_radius_mm=4.125, cell_xy_mm=.5, cell_z_mm=.25,
            absorber_thickness_mm=1.25, front_margin_z_mm=2.5, back_margin_z_mm=1.375).items())
        nodes = 22**3  # Native floor(span/cell + .5) + 1 for each 20.5-cell span.
        exact_mib = nodes * 8 * 3.25 / 1024**2
        for accepted, limit in ((False, math.nextafter(exact_mib, 0)), (True, exact_mib)):
            with self.subTest(accepted=accepted):
                run, preparation = self.unplanned_provider(f"detector_half_{accepted}",
                    edits + [(("simion_geometry_build", "detector", "max_mib"), limit)])
                with patch("subprocess.run") as native:
                    if accepted:
                        planned = plan_downstream_fields(preparation, run, snapshot_root=ROOT)
                        plan = json.loads(Path(planned["plan_record"]["path"]).read_text())
                        detector = next(a for a in plan["assets"] if a["role"] == "detector")
                        self.assertEqual(detector["grid"], dict(nx=22, ny=22, nz=22,
                            dx_mm=.5, dy_mm=.5, dz_mm=.25))
                        estimate = next(a for a in plan["array_estimates"] if a["role"] == "detector")
                        self.assertEqual(estimate["nodes"], nodes)
                        self.assertEqual(estimate["provider_array_set_bytes"], exact_mib * 1024**2)
                    else:
                        with self.assertRaisesRegex(ValueError, "detector provider array estimate.*max_mib"):
                            plan_downstream_fields(preparation, run, snapshot_root=ROOT)
                        self.assertFalse((run / "simion/downstream_fields").exists())
                    native.assert_not_called()

    def fixture_evidence(self):
        """Model the trusted runner projection without executing a solver."""
        records = []
        for step in self.plan["steps"]:
            row = dict(index=step["index"], argv=step["argv"], exit_code=0)
            for kind, text in (("stdout",step["success_marker"]), ("stderr",""), ("usage",json.dumps(dict(role="multipole_resource_usage",status="running",failure_class=None,limit_name=None)))):
                path = self.run / f"logs/{step['index']}_{kind}.txt"
                path.parent.mkdir(exist_ok=True)
                path.write_text(text, encoding="utf-8")
                row[kind+"_record"] = file_record(path)
            records.append(row)
        for asset in self.plan["assets"]:
            for name in asset["family_paths"] or [asset["carrier_path"]]:
                Path(name).write_bytes(b"UNIT TEST ONLY - NOT A PA")
        Path(self.plan["audit_output"]).write_text(json.dumps(dict(
            role="single_reflection_downstream_native_audit", status="success",
            checked_assets=[dict(role=a["role"], grid=a["grid"]) for a in self.plan["assets"]])))
        return records

    def test_plan_uses_actual_provider_arguments_and_no_solver_execution(self):
        self.assertEqual([s["name"] for s in self.plan["steps"]],
            ["flight_tube","detector","reflectron","reflectron_export","native_audit"])
        self.assertEqual(self.plan["steps"][2]["argv"][-1], "refine-all")
        self.assertTrue(self.plan["steps"][3]["argv"][-2].endswith("reflectron.pa0"))
        self.assertTrue(self.plan["steps"][3]["argv"][-1].endswith("reflectron.pa"))
        for asset in self.plan["assets"]:
            if asset["role"] == "reflectron":
                self.assertFalse(asset["family_paths"])
            else:
                self.assertEqual(len(asset["family_paths"]), 4)
                self.assertTrue(asset["family_paths"][-1].endswith(".pa-surf"))
            self.assertFalse(Path(asset["carrier_path"]).exists())
        with self.assertRaises(ValueError):
            publish_downstream_fields(self.plan_path, [])
        self.assertFalse((self.plan_path.parent / "downstream_field_preparation.json").exists())

    def test_publication_rejects_failed_missing_or_wrong_native_evidence(self):
        records = self.fixture_evidence()
        for change in ("exit", "argv", "missing", "audit", "budget"):
            with self.subTest(change=change):
                edited = copy.deepcopy(records)
                if change == "exit": edited[0]["exit_code"] = 1
                elif change == "argv": edited[0]["argv"][-1] = "999"
                elif change == "missing": edited.pop()
                elif change == "budget":
                    p = Path(edited[0]["usage_record"]["path"])
                    p.write_text(json.dumps(dict(role="multipole_resource_usage",status="resource_budget_exceeded")))
                    edited[0]["usage_record"] = file_record(p)
                else:
                    p = Path(self.plan["audit_output"])
                    p.write_text(json.dumps(dict(role="single_reflection_downstream_native_audit",status="success",checked_assets=[])))
                with self.assertRaises(ValueError): publish_downstream_fields(self.plan_path, edited)
        self.assertFalse((self.plan_path.parent / "downstream_field_preparation.json").exists())

    def test_fixture_publication_binds_complete_members_once_and_refuses_overwrite(self):
        records = self.fixture_evidence()
        result = publish_downstream_fields(self.plan_path, records)
        receipt = result["receipt"]
        self.assertEqual(receipt["native_family_origin"], "generated_in_producer_run")
        self.assertEqual(receipt["native_execution_records"], records)
        self.assertEqual([len(a["family_records"]) for a in receipt["assets"]], [4,0,4])
        self.assertEqual(receipt["oatof_resolved_record"], self.plan["oatof_resolved_record"])
        with self.assertRaises(ValueError): publish_downstream_fields(self.plan_path, records)

    def test_missing_family_member_cannot_publish_success(self):
        records = self.fixture_evidence()
        Path(self.plan["assets"][0]["family_paths"][-1]).unlink()
        with self.assertRaisesRegex(ValueError, "missing or empty"):
            publish_downstream_fields(self.plan_path, records)
        self.assertFalse((self.plan_path.parent / "downstream_field_preparation.json").exists())

    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_plain_lua_audit_reads_real_properties_and_rejects_bad_grid(self):
        script = self.root / "audit_test.lua"
        script.write_text("""
local target=assert(arg[1]);local spec=assert(arg[2]);local wrong=arg[3]=='wrong'
local original=dofile
local data=original(spec)
data.assets={data.assets[2]}
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
""",encoding="utf-8",newline="\n")
        target = ROOT / "integrations/workflows/single_reflection_flight/audit_downstream_fields.lua"
        spec = Path(self.plan["audit_spec_record"]["path"])
        bad=subprocess.run([str(LUA),str(script),str(target),str(spec),"wrong"],capture_output=True,text=True,cwd=self.root,timeout=10)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("nx differs",bad.stderr)
        good=subprocess.run([str(LUA),str(script),str(target),str(spec)],capture_output=True,text=True,cwd=self.root,timeout=10)
        self.assertEqual(good.returncode,0,good.stdout+good.stderr)
        self.assertIn("DOWNSTREAM_NATIVE_AUDIT=PASS",good.stdout)


if __name__ == "__main__":
    unittest.main()
