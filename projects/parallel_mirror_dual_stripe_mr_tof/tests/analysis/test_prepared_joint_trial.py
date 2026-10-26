"""Measured joint batch identity/clock tests; no commercial solver."""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import merge_measured_event_logs
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import (
    compare_trajectory_representation, compile_memory_consumer_crops, materialize_batch,
    validate_candidate_binding, analyze_centroid_probe, prepare_trial,
)
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_measured_component_source as source_fixtures


class PreparedJointBatchTests(unittest.TestCase):
    def test_prepare_trial_allows_observation_budget_and_selected_step_without_changing_97_states(self):
        import copy
        from common.contracts.write_run_manifest import file_record
        from common.contracts.component_particle_state import write_component_particle_state_csv
        fixture = source_fixtures.MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Synthetic 100-mother/97-handoff fixture, not a solver result. Reuse the
        # real handoff/materialization adapters so every source companion agrees.
        upstream = fixture.fixture
        selected_ids = [particle for particle in range(1,101) if particle not in {24,64,80}]
        upstream.rows = [upstream._row(particle) for particle in selected_ids]
        write_component_particle_state_csv(upstream.source, upstream.rows)
        with upstream.census.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["particle_id","transfer_status","terminal_reason","instrument_time_us","particle_birth_time_us","particle_age_us"])
            for particle in range(1,101):
                time = upstream._row(particle)["instrument_time_us"]
                writer.writerow([particle,"transferred" if particle in selected_ids else "not_transferred",
                                 "downstream_domain_exit" if particle in selected_ids else "solver_stop",time,0,time])
        upstream.receipt.update(counts=dict(source=100,transferred=97,not_transferred=3),
                                transferred_particle_ids=selected_ids,lost_particle_ids=[24,64,80])
        upstream.receipt["outputs"] = dict(component_states=upstream._identity(upstream.source),
                                           mother_census=upstream._identity(upstream.census))
        upstream._write(upstream.receipt_path,upstream.receipt)
        upstream.output = fixture.root / "synthetic_handoff97"
        upstream._prepare()
        fixture.handoff = upstream.output / "handoff_receipt.json"
        fixture._materialize()
        root, prepared = fixture.root, fixture.root / "prepared"
        source = prepared / "results/joint_workbench/measured_source"
        source.parent.mkdir(parents=True)
        (prepared / "inputs").mkdir()
        for name, original_input in (("composition_plan", upstream.recipe_path), ("accelerator_request", upstream.request)):
            shutil.copyfile(original_input, prepared / "inputs" / (name + ".json"))
        assembly_plan = json.loads((prepared / "inputs/composition_plan.json").read_text())
        poses = {item["instance_id"]: item["transform"] for item in assembly_plan["recipe"]["instances"]}
        ip_id = assembly_plan["recipe"]["connections"][0]["upstream"]["instance_id"]
        (prepared / "run_manifest.json").write_text("{}")
        shutil.copytree(fixture.output, source)
        reference = root / "reference"
        (reference / "results").mkdir(parents=True)
        (reference / "run_config.json").write_text("{}")
        manifest = reference / "run_manifest.json"
        manifest.write_text(json.dumps(dict(run_config=file_record(reference / "run_config.json"))))
        (reference / "results/two_prism_trial_materialization.json").write_text(json.dumps(
            dict(field_binding=dict(refinement_windows=[]))))
        recording = dict(schema_version=1, mode="fixed_interval", interval_us=.1,
                         retention_class="solver_review", reason="unit observation", output_budget_bytes=1000000)
        original = dict(simion=dict(trajectory_recording=recording, maximum_step_us=.01,
                                    default_trajectory_profile_id="center_screening",
                                    trajectory_profiles=dict(center_screening=dict(trajectory_quality=3,maximum_step_us=.004,
                                                                                  purpose="synthetic prepared integration")),
                                    full_path_timeout_axial_path_multiplier=2,
                                    numerical_profiles=dict(native_static_field=dict(refine=dict(convergence_v=1e-6), target_layout=dict(windows=[])))),
                        source=dict(energy_eV=5), target=dict(y_mm=360),
                        downstream_fixed_grid_workpoint_profile=dict(automatic_iteration=dict(
                            maximum_iterations=5, advance_multiplier=1.0, damping_factor=.5)))
        from common.analysis.peak_metrics import AnalysisSettings
        timing_authority = root / "native_timing.json"
        timing_authority.write_text(json.dumps(dict(schema_version=1, role="native_electrode_timing", pulse_start_us=7500)))
        source_receipt = json.loads((source / "source_receipt.json").read_text())
        original["peak_analysis"] = dict(method_id="common_gaussian_kde_time_v1",
            resolution_definition="mean_tof_us/(2*direct_fwhm_tof_us)",
            time_basis="instrument_arrival_minus_common_extraction_pulse_us", settings=vars(AnalysisSettings()),
            common_time_reference=dict(clock_epoch_id=source_receipt["clock_epoch_id"],
                                       field="pulse_start_us", timing=file_record(timing_authority)))
        original_path = root / "reference_contract.json"
        original_path.write_text(json.dumps(original))
        prepared_materialization = prepared / "results/joint_workbench/reference_materialization.json"
        shutil.copyfile(reference / "results/two_prism_trial_materialization.json", prepared_materialization)
        parent = dict(selected_provider="dual_pressure_rectilinear_ion_processor",
                      status="workbench_ready_no_joint_flight",
                      joint_workbench_binding=dict(field_assembly_verified=True, measured_source_matches_workpoint=True,
                                                   reference_materialization=file_record(prepared_materialization),
                                                   numerics=dict(trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100),
                                                   field_run=str(root / "fields"), source_run=str(root / "source")),
                      inputs=dict(reference_trajectory=file_record(original_path), reference_manifest=file_record(manifest),
                                  composition_plan=file_record(prepared / "inputs/composition_plan.json"),
                                  accelerator_request=file_record(prepared / "inputs/accelerator_request.json")))
        (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))
        (source.parent / "static_field_binding.json").write_text("{}")
        runtime = source.parent / "runtime"
        runtime.mkdir()
        (runtime / "joint.operating_point.lua").write_text("return {static_field={refinement_windows={}},trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100}")
        (runtime / "mr_reference.operating_point.lua").write_text(
            "return {trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100}")
        binding = dict(accelerator_provider="dual_pressure_rectilinear_ion_processor", refinement_windows=[],
                       manifest=str(root/"fields/run_manifest.json"),
                       geometry=dict(frame_id=assembly_plan["assembly_frame_id"]), grid=dict(origin_mm=[0,0,0],pitch_mm=[.1, .1, .1],dimensions=[2,2,2]),
                       authority=dict(analyzer_electrode_voltages_v=[0.0]*20,
                                      assembly=dict(ion_processor_registration=poses[ip_id])),
                       sources=dict(scalar_pa="synthetic_pa_not_opened.pa"),
                       instances=[dict(role=role,pa_path=role+".pa",origin_mm=[0,0,0],manifest=str(root/"fields/run_manifest.json"))
                                  for role in ("global_fallback","native_corridor","ion_processor_collision","detector")],
                       records=dict(scalar_pa=dict(sha256="A"*64)))
        binding["instances"][0]["pa_path"] = binding["sources"]["scalar_pa"]
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial"
        frozen_original = original_path.read_bytes()
        for name in ("unchanged", "observation", "budget", "budget_and_observation", "selected_step", "budget_and_selected_step",
                     "energy", "step", "advance", "smaller_budget", "quality", "mixed_physics", "mixed_timeout", "selector",
                     "peak_valid", "peak_wrong_epoch", "peak_late_pulse", "legacy_peak"):
            with self.subTest(name=name):
                contract = copy.deepcopy(original)
                if name not in ("unchanged", "observation", "selected_step") and not name.startswith("peak_"):
                    contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 30
                if name in ("observation", "budget_and_observation"):
                    contract["simion"]["trajectory_recording"]["interval_us"] = .2
                if name == "energy":
                    contract["source"]["energy_eV"] += 1
                elif name == "step":
                    contract["simion"]["maximum_step_us"] *= 2
                elif name == "advance":
                    contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["advance_multiplier"] = .5
                elif name == "smaller_budget":
                    contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 4
                elif name == "quality":
                    contract["simion"]["trajectory_profiles"]["center_screening"]["trajectory_quality"] = 8
                elif name == "mixed_physics":
                    contract["source"]["energy_eV"] += 1
                elif name == "mixed_timeout":
                    contract["simion"]["full_path_timeout_axial_path_multiplier"] += 1
                elif name == "selector":
                    contract["simion"]["trajectory_profiles"]["other"] = copy.deepcopy(contract["simion"]["trajectory_profiles"]["center_screening"])
                    contract["simion"]["default_trajectory_profile_id"] = "other"
                if name in ("selected_step", "budget_and_selected_step", "mixed_physics", "mixed_timeout"):
                    contract["simion"]["trajectory_profiles"]["center_screening"]["maximum_step_us"] = .002
                if name.startswith("peak_"):
                    timing = root / (name + "_timing.json")
                    timing.write_text(json.dumps(dict(schema_version=1, role="native_electrode_timing",
                                                      pulse_start_us=7600 if name == "peak_late_pulse" else 7500)))
                    source_receipt = json.loads((source / "source_receipt.json").read_text())
                    contract["peak_analysis"].update(time_basis="instrument_arrival_minus_common_extraction_pulse_us",
                        common_time_reference=dict(clock_epoch_id="wrong" if name == "peak_wrong_epoch" else source_receipt["clock_epoch_id"],
                                                   field="pulse_start_us", timing=file_record(timing)))
                if name == "legacy_peak":
                    contract["peak_analysis"]["time_basis"] = "instrument_arrival_us_from_common_zero_birth"
                    contract["peak_analysis"].pop("common_time_reference")
                    original_path.write_text(json.dumps(contract))
                    parent["inputs"]["reference_trajectory"] = file_record(original_path)
                    (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))
                path, output = root / f"{name}.json", root / name
                path.write_text(json.dumps(contract))
                with patch(module + ".verified_preparation_reference", side_effect=lambda run, relative, **kwargs: run / relative), \
                     patch(module + ".load_binding", return_value=binding) as load:
                    if name in ("peak_wrong_epoch", "peak_late_pulse", "legacy_peak"):
                        with self.assertRaisesRegex(ValueError, "clock authority|pulse time|Unsupported measured detector peak"):
                            prepare_trial(prepared, path, output)
                        load.assert_not_called()
                        if name == "legacy_peak":
                            original_path.write_bytes(frozen_original)
                            parent["inputs"]["reference_trajectory"] = file_record(original_path)
                            (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))
                        continue
                    if name in ("energy", "step", "advance", "smaller_budget", "quality", "mixed_physics", "mixed_timeout", "selector"):
                        with self.assertRaises(ValueError):
                            prepare_trial(prepared, path, output)
                        self.assertFalse(output.exists())
                        continue
                    result = prepare_trial(prepared, path, output)
                published = json.loads((output / "results/prepared_joint_trial.json").read_text())
                self.assertEqual(result, published)
                self.assertEqual(result["assembly_scope"], assembly_plan["scope"])
                self.assertEqual(Path(result["parent_composition_plan"]["path"]).read_bytes(),
                                 (prepared / "inputs/composition_plan.json").read_bytes())
                self.assertFalse((output / "inputs/composition_plan.json").exists())
                provenance = result["controller_contract_provenance"]
                self.assertEqual(provenance["prepared_reference_trajectory_contract"], file_record(original_path))
                consumed = file_record(output / "inputs/trajectory_contract.json")
                self.assertEqual(provenance["consumed_execution_contract"], consumed)
                self.assertEqual(result["trajectory_contract"], consumed)
                if name == "peak_valid":
                    self.assertEqual(provenance["analysis_change"]["current"], contract["peak_analysis"])
                else:
                    self.assertIsNone(provenance["analysis_change"])
                self.assertEqual((output / "inputs/trajectory_contract.json").read_bytes(), path.read_bytes())
                self.assertEqual(result["expected_particle_ids"], selected_ids)
                self.assertEqual(result["mother_particle_count"], 100)
                self.assertEqual(result["launched_particle_count"], 97)
                for filename in ("component_particle_state.csv","source.fly2","source_states.lua","source_projection.lua","source_census.csv"):
                    self.assertEqual((Path(result["measured_source_directory"])/filename).read_bytes(),(source/filename).read_bytes())
                changed_step = name in ("selected_step", "budget_and_selected_step")
                maximum_step = .002 if changed_step else .004
                self.assertEqual(result["numerics"],dict(trajectory_quality=3,maximum_step_us=maximum_step,full_path_timeout_us=100))
                self.assertEqual(result["dispatch_request"]["trajectory_quality"],3)
                self.assertEqual(result["dispatch_request"]["particle_count"],97)
                self.assertEqual(result["dispatch_request"]["trajectory_quality_profile_id"],"center_screening")
                self.assertEqual(result["dispatch_request"]["case_input_sha256"],result["operating_point"]["sha256"])
                self.assertIn("t.maximum_step_us="+str(maximum_step),Path(result["operating_point"]["path"]).read_text())
                self.assertEqual(provenance["selected_trajectory_profile"]["profile_id"],"center_screening")
                if changed_step:
                    self.assertEqual(provenance["numerical_change"],dict(change_kind="selected_trajectory_maximum_step_only",profile_id="center_screening",
                                                                         maximum_step_us=dict(previous=.004,current=.002)))
                else:
                    self.assertIsNone(provenance["numerical_change"])
                if name in ("budget", "budget_and_observation", "budget_and_selected_step"):
                    self.assertEqual(provenance["execution_budget_change"]["maximum_iterations"], dict(previous=5, current=30))
                    self.assertEqual(provenance["execution_budget_change"]["change_kind"], "execution_budget_only")
                    self.assertNotEqual(consumed["sha256"], file_record(original_path)["sha256"])
                else:
                    self.assertIsNone(provenance["execution_budget_change"])
                if name == "selected_step":
                    batch_directory = output / "batch_all_97"
                    batch = materialize_batch(output/"results/prepared_joint_trial.json",1,97,batch_directory)
                    self.assertEqual(batch["original_particle_ids"],selected_ids)
                    lua = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
                    if Path(lua).is_file():
                        script = output/"check_sidecar.lua"
                        script.write_text("local t=assert(loadfile(arg[1]))();assert(t.maximum_step_us==.002 and t.trajectory_quality==3 and t.full_path_timeout_us==100);"
                            "assert(t.static_field.scalar_pa=='synthetic_pa_not_opened.pa');"
                            "assert(t.static_field.collision_pa_path=='native_corridor.pa');"
                            "assert(#t.static_field.collision_geometry_pa_paths==2);"
                            "assert(t.static_field.collision_geometry_pa_paths[1]=='ion_processor_collision.pa');"
                            "assert(t.static_field.collision_geometry_pa_paths[2]=='detector.pa');"
                            "print('CONTRACT_STEP_PROPAGATED')")
                        for sidecar in (Path(result["operating_point"]["path"]),batch_directory/"joint.operating_point.lua"):
                            actual = subprocess.run([lua,str(script),str(sidecar)],capture_output=True,text=True,
                                                    cwd=root,encoding="utf-8",timeout=30,check=False)
                            self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
                            self.assertIn("CONTRACT_STEP_PROPAGATED",actual.stdout)
        self.assertEqual(original_path.read_bytes(), frozen_original)
        from common.integration.resolve_assembly import compile_assembly_layout
        plan_path = prepared / "inputs/composition_plan.json"
        request_path = prepared / "inputs/accelerator_request.json"
        plan_bytes, request_bytes = plan_path.read_bytes(), request_path.read_bytes()
        original_parent = copy.deepcopy(parent)

        def publish_assembly(plan, request):
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            request_path.write_text(json.dumps(request), encoding="utf-8")
            parent["inputs"].update(composition_plan=file_record(plan_path), accelerator_request=file_record(request_path))
            (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))

        # A different parent expression does not move the already MR-local
        # measured source, fields, collision layout, or absolute instrument clock.
        from common.contracts.rigid_transform import RigidTransform
        for index, rotation in enumerate(([[1,0,0],[0,1,0],[0,0,1]], [[0,-1,0],[1,0,0],[0,0,1]])):
            recipe = copy.deepcopy(assembly_plan["recipe"])
            movement = RigidTransform.from_contract(dict(schema_version=1, role="rigid_transform",
                from_frame_id=recipe["assembly_frame_id"], to_frame_id="instrument.assembly",
                rotation=rotation, translation_mm=[32,-16,8]))
            recipe["assembly_frame_id"] = movement.to_frame_id
            for item in recipe["instances"]:
                item["transform"] = RigidTransform.from_contract(item["transform"]).then(movement).to_contract()
            moved = compile_assembly_layout(recipe, assembly_plan["components"])
            publish_assembly(moved, json.loads(request_bytes))
            with patch(module+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
                 patch(module+".load_binding",return_value=binding):
                inherited = prepare_trial(prepared,original_path,root/f"parent_motion_{index}")
            self.assertEqual(inherited["expected_particle_ids"], selected_ids)
            self.assertEqual(inherited["solver_epoch_instrument_time_us"], result["solver_epoch_instrument_time_us"])
            self.assertEqual(inherited["field_binding"], result["field_binding"])
            for filename in ("component_particle_state.csv", "source.fly2", "source_states.lua", "source_projection.lua",
                             "source_census.csv", "clock_authority.json", "instrument_epoch.json"):
                self.assertEqual((Path(inherited["measured_source_directory"])/filename).read_bytes(), (source/filename).read_bytes())
        publish_assembly(assembly_plan, json.loads(request_bytes))

        for count in (3, 4):
            with self.subTest(parent_instance_count=count):
                recipe, components = copy.deepcopy(assembly_plan["recipe"]), copy.deepcopy(assembly_plan["components"])
                for index in range(count - 2):
                    extra = copy.deepcopy(next(item for item in recipe["instances"] if item["instance_id"] == ip_id))
                    extra["instance_id"] = f"spare_{index}"
                    extra["transform"]["translation_mm"][1] -= 1000 * (index + 1)
                    recipe["instances"].append(extra)
                    components[extra["instance_id"]] = copy.deepcopy(components[ip_id])
                recipe["instances"].reverse()
                grown = compile_assembly_layout(recipe, components)
                grown["input_files"] = {key: dict(path="unavailable_" + key + ".json", sha256="A" * 64)
                                        for key in ("recipe", "components")}
                request = json.loads(request_bytes)
                request["composition_plan"]["path"] = "author_source_no_longer_exists.json"
                request["local_scope"] = dict(instance_ids=assembly_plan["scope"]["instance_ids"],
                    research_scope="existing prepared IP to MR flight",
                    boundary_assumptions="unselected components do not participate in these frozen fields")
                publish_assembly(grown, request)
                with patch(module+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
                     patch(module+".load_binding",return_value=binding):
                    inherited = prepare_trial(prepared,original_path,root/f"grown_{count}")
                    self.assertEqual(inherited["assembly_scope"]["kind"], "local")
                    self.assertEqual(set(inherited["assembly_scope"]["instance_ids"]), set(assembly_plan["scope"]["instance_ids"]))
                    self.assertEqual(inherited["expected_particle_ids"], selected_ids)
                    self.assertEqual(inherited["mother_particle_count"],100)
                    self.assertEqual(inherited["guard_paths"],result["guard_paths"])
                    self.assertEqual(inherited["field_binding"],result["field_binding"])
                    for filename in ("component_particle_state.csv","source.fly2","source_states.lua","source_projection.lua",
                                     "source_census.csv","clock_authority.json","instrument_epoch.json"):
                        self.assertEqual((Path(inherited["measured_source_directory"])/filename).read_bytes(),(source/filename).read_bytes())
                    del request["local_scope"]
                    publish_assembly(grown, request)
                    with self.assertRaisesRegex(ValueError,"selected scope requires"):
                        prepare_trial(prepared,original_path,root/f"unsupported_full_{count}")

        for defect in ("missing_parent", "old_request", "old_plan", "wrong_path", "wrong_ip_pose", "wrong_mr_pose", "wrong_field_frame", "wrong_source_instance"):
            with self.subTest(assembly_defect=defect):
                parent = copy.deepcopy(original_parent)
                plan, request = json.loads(plan_bytes), json.loads(request_bytes)
                selected_binding = copy.deepcopy(binding)
                if defect == "old_request":
                    request["schema_version"] = 1
                elif defect == "old_plan":
                    plan["schema_version"] = 2
                elif defect == "wrong_ip_pose":
                    selected_binding["authority"]["assembly"]["ion_processor_registration"]["translation_mm"][0] += 1
                elif defect == "wrong_mr_pose":
                    for item in plan["recipe"]["instances"]:
                        item["transform"]["translation_mm"][0] += 1
                    selected_binding["authority"]["assembly"]["ion_processor_registration"]["translation_mm"][0] += 1
                    plan = compile_assembly_layout(plan["recipe"],plan["components"])
                elif defect == "wrong_field_frame":
                    selected_binding["geometry"]["frame_id"] = "unrelated_field_frame"
                elif defect == "wrong_source_instance":
                    new_id = "different_ip"
                    for item in plan["recipe"]["instances"]:
                        if item["instance_id"] == ip_id:
                            item["instance_id"] = new_id
                    plan["recipe"]["connections"][0]["upstream"]["instance_id"] = new_id
                    plan["components"][new_id] = plan["components"].pop(ip_id)
                    plan = compile_assembly_layout(plan["recipe"],plan["components"])
                publish_assembly(plan, request)
                if defect == "missing_parent":
                    del parent["inputs"]["composition_plan"]
                elif defect == "wrong_path":
                    parent["inputs"]["composition_plan"]["path"] = str(upstream.recipe_path)
                (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))
                with patch(module+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
                     patch(module+".load_binding",return_value=selected_binding), self.assertRaises(ValueError):
                    prepare_trial(prepared,original_path,root/("reject_"+defect))
        plan_path.write_bytes(plan_bytes)
        request_path.write_bytes(request_bytes)
        parent = original_parent
        (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))
        overlay = copy.deepcopy(binding)
        overlay["source_descriptor_path"] = str(root/"overlay_source.json")
        overlay["collision_overlay"] = dict(schema_version=1,role="mrtof_analyzer_collision_overlay",
            patch_plan_path=str(root/"patch_plan.json"),box_mm=[0,-4,-100,2,0,-92],pitch_mm=[.05,.05,.05],
            dimensions=[41,81,161],symmetry="x",priority_probes=[])
        overlay["instances"].append(dict(role="analyzer_collision_patch",pa_path="fine_patch.pa",origin_mm=[0,-4,-100],
                                         manifest=str(root/"patch_owner/run_manifest.json")))
        overlay_path = root/"overlay.json"
        overlay_path.write_text('{}')
        def overlay_loader(path):
            return overlay if Path(path)==overlay_path else binding
        with patch(module+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
             patch(module+".load_binding",side_effect=overlay_loader), \
             patch(module+".native_response_operator",return_value={}):
            patched = prepare_trial(prepared,original_path,root/"five_role_prepared",field_binding_path=overlay_path)
        self.assertIn("five_instances",patched["dispatch_request"]["workload_topology_id"])
        self.assertIn("fine_patch.pa",patched["guard_paths"])
        self.assertIn(str(root/"patch_owner"),patched["protected_paths"])
        self.assertIn("analyzer_collision_patch",(Path(patched["frozen_runtime_directory"])/"joint.priority.lua").read_text())
        self.assertIn("collision_overlay",Path(patched["operating_point"]["path"]).read_text())
        self.assertEqual(patched["expected_particle_ids"],selected_ids)
        for filename in ("component_particle_state.csv","source.fly2","source_states.lua","source_projection.lua","source_census.csv"):
            self.assertEqual((Path(patched["measured_source_directory"])/filename).read_bytes(),(source/filename).read_bytes())
        with patch(module+".load_binding",return_value=overlay):
            materialize_batch(root/"five_role_prepared/results/prepared_joint_trial.json",1,97,root/"five_role_batch")
        self.assertIn("5_instance_seed.iob",(root/"five_role_batch/joint.workbench_build.lua").read_text())
        self.assertIn("fine_patch.pa",(root/"five_role_batch/joint.workbench_build.lua").read_text())
        # Pure finalization -> ordinary preparation: generated effective reference
        # must carry the selected contract rather than inherit the old .004 Lua.
        from integrations.workflows.accelerator_interface.prepare import bind_joint_workbench
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import validate_execution_contract
        final = root / "finalized"
        (final / "results").mkdir(parents=True)
        (final / "run_manifest.json").write_text("{}")
        design, actual, fields = [root/name for name in ("design_final", "actual_final", "fields_final")]
        for folder in (design/"inputs", design/"results/joint_flight", actual/"inputs", fields/"results"):
            folder.mkdir(parents=True)
        (design / "run_manifest.json").write_text("{}")
        configs = {name: dict(identity=name) for name in ("baseline","native_operating_point","numerics","source","coordinate_transform")}
        configs["source"]["species"] = dict(mass_amu=524, charge_state=1)
        configs["baseline"]["electric"] = dict(lift_v=4480)
        paths = {}
        for name, value in configs.items():
            path = design/"inputs"/(name+".json")
            path.write_text(json.dumps(value))
            paths[name] = str(path)
        for name in ("composition_plan", "accelerator_request"):
            shutil.copyfile(prepared/"inputs"/(name+".json"), design/"inputs"/(name+".json"))
        matching_path = design/"inputs/matching_assembly_request.json"
        projection = dict(values_v15=list(range(15)), basis="post_extraction_pulse_held_rf_zero",
            evaluated_native_operating_point=configs["native_operating_point"], evaluated_baseline_lift_v=4480)
        matching_path.write_text(json.dumps(dict(field_assembly_reference=dict(provider_voltage_projection=projection))))
        geometry = design/"inputs/geometry.json"
        geometry.write_text(json.dumps(binding["geometry"]))
        (actual/"inputs/resolved_model.json").write_text(json.dumps(configs))
        design_materialization = design/"inputs/reference_materialization.json"
        shutil.copyfile(prepared_materialization, design_materialization)
        (design/"results/joint_flight/joint_preparation_receipt.json").write_text(json.dumps(dict(
            reference_materialization=file_record(design_materialization),
            numerics=dict(trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100),
            assembly=dict(source_config_paths=paths, assembly_geometry_path=str(geometry),
                          composition_plan=assembly_plan, assembly_coordinate_transform=poses[ip_id],
                          input_identities=[file_record(matching_path)]))))
        (design/"inputs/reference_operating_point.lua").write_text(
            "return {trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100}")
        # Deliberately noncanonical whitespace/key order: exact descriptor bytes
        # are the owner-bound transport authority, not reserialized JSON.
        descriptor = fields/"results/field_binding.json"
        descriptor.write_bytes(b'{  "z": 1, "a":2}\r\n')
        bound_field = copy.deepcopy(binding)
        bound_field.update(geometry=copy.deepcopy(binding["geometry"]), grid=dict(origin_mm=[0,0,0],pitch_mm=[.1,.1,.1],dimensions=[2,2,2]),
            instances=[dict(role=role,pa_path=role+".pa",origin_mm=[0,0,0],manifest=str(root/(role+"_owner")/"run_manifest.json")) for role in
                       ("global_fallback","native_corridor","ion_processor_collision","detector")])
        bound_field["authority"]["component_voltages_v"] = [dict(component_namespace="ion_processor", component_electrode_id=i+1, voltage_v=i) for i in range(15)] + [dict(component_namespace="detector", component_electrode_id=25, voltage_v=0)]
        bound_field["authority"]["assembly"].update(post_extraction_state="pulse_held_rf_zero", native_operating_point=configs["native_operating_point"])
        bound_field["source_descriptor_path"] = overlay["source_descriptor_path"]
        bound_field["collision_overlay"] = copy.deepcopy(overlay["collision_overlay"])
        bound_field["instances"].append(copy.deepcopy(overlay["instances"][4]))
        component = root/"final_component.json"
        component.write_text(json.dumps(dict(source_run=str(actual))))
        handoff = root/"final_handoff.json"
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection
        handoff.write_text(json.dumps(dict(connection=resolve_ip_mr_connection(assembly_plan), inputs=dict(component_receipt=file_record(component)))))
        selected = copy.deepcopy(original)
        selected["simion"]["trajectory_profiles"]["center_screening"]["maximum_step_us"] = .002
        selected_path = final/"selected_contract.json"
        selected_path.write_text(json.dumps(selected))
        def source_projection(_handoff, output):
            shutil.copytree(source, output)
            return dict(counts=dict(source=100,transferred=97,not_transferred=3))
        compiler = "integrations.workflows.accelerator_interface.prepare"
        with patch(compiler+".verified_reference",side_effect=lambda run,relative,**kwargs:run/relative), patch(compiler+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
             patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding",return_value=bound_field), \
             patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source.materialize_measured_source",side_effect=source_projection), \
             patch(compiler+".prepare_interface_field_audit",return_value={}):
            finalized = bind_joint_workbench(design_run=design,field_run=fields,source_run=actual,
                handoff_receipt=handoff,energy_comparison=dict(role="mrtof_measured_exit_energy_comparison",
                    centroid_match_accepted=None,inputs=dict(component_receipt=file_record(component))),
                output_directory=final/"results/joint_workbench",
                execution_contract=validate_execution_contract(original,selected))
        # The finalizer checks the same provider-local physical registration,
        # even when the frozen design parent is expressed elsewhere.
        compiler_module = __import__(compiler, fromlist=["_joint_binding_inputs"])
        design_plan_path = design / "inputs/composition_plan.json"
        design_receipt_path = design / "results/joint_flight/joint_preparation_receipt.json"
        old_design_plan, old_design_receipt = design_plan_path.read_bytes(), design_receipt_path.read_bytes()
        for rotation in ([[1,0,0],[0,1,0],[0,0,1]], [[0,-1,0],[1,0,0],[0,0,1]]):
            recipe = copy.deepcopy(assembly_plan["recipe"])
            movement = RigidTransform.from_contract(dict(schema_version=1, role="rigid_transform",
                from_frame_id=recipe["assembly_frame_id"], to_frame_id="instrument.assembly",
                rotation=rotation, translation_mm=[32,-16,8]))
            recipe["assembly_frame_id"] = movement.to_frame_id
            for item in recipe["instances"]:
                item["transform"] = RigidTransform.from_contract(item["transform"]).then(movement).to_contract()
            moved = compile_assembly_layout(recipe, assembly_plan["components"])
            design_plan_path.write_text(json.dumps(moved))
            design_receipt = json.loads(old_design_receipt)
            design_receipt["assembly"]["composition_plan"] = moved
            design_receipt_path.write_text(json.dumps(design_receipt))
            with patch(compiler+".verified_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
                 patch(compiler+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
                 patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding",return_value=bound_field):
                verified = compiler_module._joint_binding_inputs(design_run=design,field_run=fields,source_run=actual)
            self.assertEqual(verified["binding"], bound_field)
        design_plan_path.write_bytes(old_design_plan)
        design_receipt_path.write_bytes(old_design_receipt)
        self.assertEqual((final/"results/joint_workbench/static_field_binding.json").read_bytes(),descriptor.read_bytes())
        final_parent = copy.deepcopy(parent)
        (final / "inputs").mkdir(exist_ok=True)
        for name in ("composition_plan", "accelerator_request"):
            destination = final / "inputs" / (name + ".json")
            shutil.copyfile(prepared / "inputs" / (name + ".json"), destination)
            final_parent["inputs"][name] = file_record(destination)
        final_parent["inputs"]["reference_trajectory"] = file_record(selected_path)
        final_parent["joint_workbench_binding"].update(finalized)
        # Public IOB builder normally commits this no-Fly readiness state; this
        # fixture exercises Python preparation only and claims no IOB execution.
        (final/"results/accelerator_interface_preparation.json").write_text(json.dumps(final_parent))
        with patch(module+".verified_preparation_reference",side_effect=lambda run,relative,**kwargs:run/relative), \
             patch(module+".load_binding",return_value=bound_field):
            replay = prepare_trial(final,selected_path,root/"finalized_replay")
        self.assertIn("five_instances",replay["dispatch_request"]["workload_topology_id"])
        self.assertFalse(replay["candidate_iob_rebuild"])
        for item in [bound_field,*bound_field["refinement_windows"],*bound_field["instances"]]:
            self.assertIn(str(Path(item["manifest"]).parent),replay["protected_paths"])
        self.assertEqual(replay["numerics"],dict(trajectory_quality=3,maximum_step_us=.002,full_path_timeout_us=100))
        self.assertIsNone(replay["controller_contract_provenance"]["numerical_change"])
        self.assertEqual(replay["expected_particle_ids"],selected_ids)
        for filename in ("component_particle_state.csv","source.fly2","source_states.lua","source_projection.lua","source_census.csv"):
            self.assertEqual((Path(replay["measured_source_directory"])/filename).read_bytes(),(source/filename).read_bytes())
        lua = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
        if Path(lua).is_file():
            check = root/"check_finalized_step.lua"
            check.write_text("local t=dofile(arg[1]);assert(t.maximum_step_us==.002 and t.trajectory_quality==3 and t.full_path_timeout_us==100)")
            for sidecar in (final/"results/joint_workbench/runtime/joint.operating_point.lua",Path(replay["operating_point"]["path"])):
                actual_lua = subprocess.run([lua,str(check),str(sidecar)],cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(actual_lua.returncode,0,actual_lua.stdout+actual_lua.stderr)
        # Numerical authority is the frozen JSON, not incidental Lua text or
        # availability of the original reference run.
        shutil.rmtree(reference)
        (runtime/"joint.operating_point.lua").unlink()
        (runtime/"joint.priority.lua").write_text("obsolete priority must not be read")
        def inherited_reference(owner, relative, **kwargs):
            if Path(relative).parent.name == "runtime":
                self.assertNotIn(Path(relative).name, {"joint.operating_point.lua", "joint.lua",
                    "joint.source_runtime.lua", "joint.scalar_field_adapter.lua", "joint.priority.lua"})
            return owner/relative
        (runtime/"mr_reference.operating_point.lua").write_text("return {trajectory_quality=99,maximum_step_us=99,full_path_timeout_us=99}")
        with patch(module+".verified_preparation_reference",side_effect=inherited_reference), \
             patch(module+".load_binding",return_value=binding):
            detached = prepare_trial(prepared,original_path,root/"detached_reference")
            self.assertEqual(detached["numerics"],dict(trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100))
            if Path(lua).is_file():
                # Independently assert all three frozen JSON values.
                check.write_text("local t=dofile(arg[1]);assert(t.maximum_step_us==.004 and t.trajectory_quality==3 and t.full_path_timeout_us==100)")
                actual_lua = subprocess.run([lua,str(check),detached["operating_point"]["path"]],cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(actual_lua.returncode,0,actual_lua.stdout+actual_lua.stderr)
            parent["joint_workbench_binding"]["numerics"]["maximum_step_us"] = .01
            (prepared / "results/accelerator_interface_preparation.json").write_text(json.dumps(parent))
            with self.assertRaisesRegex(ValueError,"JSON numerics differ"):
                prepare_trial(prepared,original_path,root/"inconsistent_json_numerics")

    def test_staged_adapter_reuses_json_phase_space_and_rejects_changed_evidence(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
            materialize_prepared_staged_adapter,
        )
        module="projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); authority=root/"authority.json";authority.write_text('{}')
            state=dict(position_mm=(.1,-2.,33.),velocity_mm_per_us=(.01,1.4,40.))
            trial=dict(observation=dict(center_particle_prism_handoff_validation=dict(
                p2_low_field_reference_state=state)),materialization=dict(prism_voltages_v=[340.,-186.]))
            with patch(module+".load_prepared_centroid_trial",return_value=trial):
                first=materialize_prepared_staged_adapter(authority,authority,authority,root/"views")
                second=materialize_prepared_staged_adapter(authority,authority,authority,root/"views")
                self.assertEqual(first,second)
                path=Path(first["outputs"]["observation"]["path"])
                frozen=path.read_bytes()
                trial["observation"]["center_particle_prism_handoff_validation"][
                    "p2_low_field_reference_state"]["position_mm"]=(.1,-2.1,33.)
                with self.assertRaisesRegex(ValueError,"change existing stage evidence"):
                    materialize_prepared_staged_adapter(authority,authority,authority,root/"views")
                self.assertEqual(path.read_bytes(),frozen)

    def test_candidate_binding_keeps_ip_operator_and_reuses_new_parent(self):
        import copy
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import candidate_authority
        authority = dict(analyzer_electrode_voltages_v=[0.0]*20,
                         component_voltages_v=[dict(namespace="ion_processor", id=i, value_v=i) for i in range(1,16)],
                         assembly=dict(native_operating_point=dict(lift_v=4480.04379)))
        baseline = dict(accelerator_provider="dual_pressure_rectilinear_ion_processor", geometry=dict(IP="same"),
            authority=authority, sources=dict(scalar_pa="old_parent.pa"), grid=dict(origin_mm=[0,0,0]),
            instances=[dict(role=r,pa_path="old_parent.pa" if i==0 else r+".pa",origin_mm=[0,0,0])
                       for i,r in enumerate(["global_fallback","native_corridor","ion_processor_collision","detector"])])
        candidate = copy.deepcopy(baseline)
        candidate["authority"] = candidate_authority(authority, dict(s1=1,s2=2,p1=3,p2=4))
        candidate["sources"]["scalar_pa"]="new_parent.pa"
        candidate["instances"][0]["pa_path"]="new_parent.pa"
        module="projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial"
        overlay = copy.deepcopy(candidate)
        overlay["instances"].append(dict(role="analyzer_collision_patch",pa_path="patch.pa",origin_mm=[0,-4,-100]))
        with self.assertRaisesRegex(ValueError,"topology"):
            validate_candidate_binding(overlay,baseline)
        overlay.update(source_descriptor_path="sealed_source.json",collision_overlay=dict(
            schema_version=1,role="mrtof_analyzer_collision_overlay",patch_plan_path="sealed_plan.json"))
        with patch(module+".load_binding",return_value=candidate) as source_loader, \
             patch(module+".native_response_operator",return_value={}):
            self.assertEqual(validate_candidate_binding(overlay,baseline),dict(s1=1,s2=2,p1=3,p2=4))
            source_loader.assert_called_once_with(Path("sealed_source.json"))
            with self.assertRaisesRegex(ValueError,"silently remove"):
                validate_candidate_binding(candidate,overlay)
        with patch(module+".native_response_operator", return_value={}) as operator:
            self.assertEqual(validate_candidate_binding(candidate,baseline),dict(s1=1,s2=2,p1=3,p2=4))
            self.assertEqual(operator.call_count,2)
            candidate["instances"][0]["pa_path"]="old_parent.pa"
            with self.assertRaisesRegex(ValueError,"reuse"):
                validate_candidate_binding(candidate,baseline)
            candidate["instances"][0]["pa_path"]="new_parent.pa"
            candidate["authority"]["component_voltages_v"][0]["value_v"] += 1
            with self.assertRaisesRegex(ValueError,"IP15"):
                validate_candidate_binding(candidate,baseline)
        candidate=copy.deepcopy(baseline)
        with patch(module+".native_response_operator", side_effect=[dict(grid="different"),dict(grid="baseline")]):
            with self.assertRaisesRegex(ValueError,"numerical"):
                validate_candidate_binding(candidate,baseline)

    def test_probe_analysis_preserves_constructed_source_and_observed_collision(self):
        from common.contracts.write_run_manifest import file_record
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import materialize_centroid_probe
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_measured_component_analysis import _terminal
        fixture=source_fixtures.MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        fixture.setUp();self.addCleanup(fixture.doCleanups);receipt=fixture._materialize()
        from common.contracts.component_particle_state import write_component_particle_state_csv
        canonical=fixture.output/"component_particle_state.csv"
        with canonical.open() as handle:
            mother=list(csv.DictReader(handle))
        for row in mother:
            row["position_z_mm"]=0.0
        write_component_particle_state_csv(canonical,mother)
        receipt["outputs"]["component_particle_state"]=file_record(canonical)
        (fixture.output/"source_receipt.json").write_text(json.dumps(receipt))
        root=fixture.root;probe=root/"probe"
        materialize_centroid_probe(fixture.output,probe)
        reference=root/"reference.json"
        reference.write_text(json.dumps(dict(target_positive_mirror_turn_y_mm=0,target_low_field_tangent_ratio_vy_over_vz=.035)))
        binding=root/"binding.json";binding.write_text('{}')
        preparation=root/"prepared.json"
        preparation.write_text(json.dumps(dict(source_mode="centroid_probe",expected_particle_ids=[1],
            launched_particle_count=1,mother_particle_count=1,
            measured_source_directory=str(probe),source_receipt=file_record(probe/"source_receipt.json"),
            reference_materialization=file_record(reference),field_binding=file_record(binding),
            trajectory_contract=file_record(reference),operating_point=file_record(reference),
            stripe_biases_v=[0,0],prism_voltages_v=[10,20])))
        log=root/"flight.log";log.write_text(_terminal(1,-1,7600.0)+"\nstatus,Fly completed. 1 splats\n")
        module="projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial"
        normalized=dict(authority=dict(analyzer_electrode_voltages_v=[0.0]*20,
            component_voltages_v=[dict(component_namespace="ion_processor",component_electrode_id=i,voltage_v=i) for i in range(1,16)]))
        normalized["authority"]["analyzer_electrode_voltages_v"][15:17]=[10,20]
        with patch(module+".load_binding",return_value=normalized),patch(module+".native_response_operator",return_value={}),\
             patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial._static_field_receipt",return_value=dict(mode="native_static_pa",path=str(binding))):
            result=analyze_centroid_probe(preparation,log,root/"analysis")
        self.assertEqual(result["frozen_problem"]["source_center_projection"]["role"],"measured_exit_centroid")
        self.assertEqual(result["observation"]["terminal"]["splat"],-1)
        self.assertEqual(result["observation"]["center_particle_prism_handoff_validation"]["status"],"incomplete")
        self.assertFalse(result["physical_potential_evaluated"])
        field=result["field_authority_projection"]
        self.assertEqual(field["binding_record"],file_record(binding))
        self.assertEqual(field["analyzer_electrode_voltages_v"],normalized["authority"]["analyzer_electrode_voltages_v"])
        self.assertEqual(len(field["ion_processor_component_voltages_v15"]),15)
        self.assertEqual(field["normalized_binding"],normalized)
        self.assertTrue((root/"analysis/probe_event_states.csv").is_file())
        # Once published, controller reanalysis consumes frozen metadata only:
        # an absent (retired) PA must not be reopened to recover S/full evidence.
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
            load_prepared_centroid_trial, materialize_prepared_staged_adapter, reanchor_prepared_target,
        )
        manifest=root/"run_manifest.json"
        projection=root/"analysis/controller_projection.json"
        manifest.write_text(json.dumps(dict(status="success",mode="prepared_joint",
            project="instrument_assembly",outputs=[file_record(projection)])))
        target=dict(target_positive_mirror_turn_y_mm=0,target_low_field_tangent_ratio_vy_over_vz=.035,
            target_slow_turn_y_mm=360,target_k=24.5,prism_handoff_target=None,
            inputs=dict(mother_source_receipt=file_record(fixture.output/"source_receipt.json"),
                        trajectory_contract=file_record(reference)))
        target["prism_handoff_target"]={"axial_energy_per_charge_v":4372}
        adapter="projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
        with patch(adapter+".load_measured_centroid_closure_target",return_value=target),\
             patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding",side_effect=AssertionError("retired PA opened")):
            from common.contracts.component_particle_state import load_component_particle_state_csv
            with patch("common.contracts.component_particle_state.load_component_particle_state_csv",
                       wraps=load_component_particle_state_csv) as canonical_reader:
                trial=load_prepared_centroid_trial(manifest,reference,reference)
                canonical_reader.assert_called_once_with(probe/"component_particle_state.csv")
            self.assertEqual(trial["observation"]["status"],"measured_centroid_observation_incomplete")
            self.assertEqual(trial["observation"]["termination_diagnostic"]["status"],"ambiguous")
            self.assertIn("center_particle_stripe_stage_validation",trial["observation"])
            self.assertFalse(trial["observation"]["static_return_diagnostic"]["event_contract_ok"])
            state=dict(columns={"2":"old-column"},flight_count=8,attempts=["old"],prism_model_manifest="old-model")
            reset=reanchor_prepared_target(state,anchor_manifest=manifest,target_path=reference,contract_path=reference)
            self.assertEqual(reset["columns"],{})
            self.assertEqual(reset["flight_count"],8)
            self.assertEqual(reset["stage"],"prism_preclosure")
            self.assertNotIn("prism_model_manifest",reset)
            views=materialize_prepared_staged_adapter(manifest,reference,reference,root/"views")
            self.assertFalse(views["field_payload_opened"])
            self.assertFalse(views["full_population_qualified"])
            with self.assertRaisesRegex(ValueError,"pending"):
                reanchor_prepared_target(dict(pending_trial={"real":"flight"}),anchor_manifest=manifest,target_path=reference,contract_path=reference)

    def test_explicit_slow_turn_reanchor_preserves_spent_budget_and_rejects_other_changes(self):
        import copy
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import reanchor_prepared_target
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/"old.json";new=root/"new.json"
            original=dict(target_slow_turn_y_mm=360,energy=4359.32,source="same")
            old.write_text(json.dumps(original))
            target=dict(original,target_slow_turn_y_mm=340)
            new.write_text(json.dumps(target))
            trial=dict(frozen_problem=dict(source_center_projection="same",static_field_problem="same",
                                           selected_axial_energy_per_charge_v=4359.32))
            state=dict(stage="stripe_preclosure",candidate_count=16,flight_count=51,columns={"0":"old"},
                       attempts=[1],history=["keep"],prism_model_manifest="old",prediction_assessment={})
            saved=copy.deepcopy(state)
            module="projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration"
            with patch(module+".load_prepared_centroid_trial",return_value=trial):
                reset=reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                self.assertEqual((reset["candidate_count"],reset["flight_count"]),(16,51))
                self.assertEqual(reset["history"],["keep"])
                self.assertEqual(reset["columns"],{})
                self.assertEqual(reset["attempts"],[])
                self.assertEqual(state,saved)
                new.write_text(json.dumps(dict(target,target_slow_turn_y_mm=351)))
                alternate=reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                self.assertEqual(alternate["flight_count"],51)
                with self.assertRaisesRegex(ValueError,"overwrite existing debit"):
                    reanchor_prepared_target(reset,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                for changed in (dict(target,energy=4360),dict(target,source="different"),dict(target,target_slow_turn_y_mm=360)):
                    new.write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):
                        reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                new.write_text(json.dumps(target))
            other=copy.deepcopy(trial);other["frozen_problem"]["source_center_projection"]="changed"
            with patch(module+".load_prepared_centroid_trial",side_effect=[trial,other]):
                with self.assertRaisesRegex(ValueError,"source or operator"):
                    reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)

    def test_candidate_batch_does_not_copy_old_iob_and_binds_all_actual_roles(self):
        from common.contracts.write_run_manifest import file_record
        fixture=source_fixtures.MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        fixture.setUp();self.addCleanup(fixture.doCleanups);fixture._materialize()
        root=fixture.root;runtime=root/"runtime";runtime.mkdir()
        (runtime/"joint.iob").write_bytes(b"must not be loaded or copied")
        (runtime/"joint.lua").write_text("-- program")
        (runtime/"joint.operating_point.lua").write_text("return {accelerator_provider='dual_pressure_rectilinear_ion_processor',"
            "field_assembly_verified=true,measured_source_matches_workpoint=true,"
            "static_field={assembly_scope='full_c0_ion_processor_replacement'}}")
        binding=root/"binding.json";binding.write_text('{}')
        roles = ["global_fallback","native_corridor","ion_processor_collision","detector"]
        actual=dict(instances=[dict(role=roles[i],pa_path=p,origin_mm=[i,0,0]) for i,p in enumerate(
            ["new_parent.pa","original_corridor.pa","original_fine_occupancy.pa","original_detector.pa"])])
        preparation=root/"prepared.json"
        preparation.write_text(json.dumps(dict(candidate_iob_rebuild=True,field_binding=file_record(binding),
            measured_source_directory=str(fixture.output),frozen_runtime_directory=str(runtime),
            trajectory_recording=dict(mode="fixed_interval",interval_us=.1))))
        module="projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial"
        with patch(module+".load_binding",return_value=actual):
            materialize_batch(preparation,1,2,root/"batch")
        self.assertFalse((root/"batch/joint.iob").exists())
        build=(root/"batch/joint.workbench_build.lua").read_text()
        self.assertIn("new_parent.pa",build)
        self.assertNotIn("old_parent.pa",build)
        self.assertIn("original_fine_occupancy.pa",build)
        self.assertIn("4_instance_seed.iob",build)
        batch_dir = root / "batch"
        provider = "dual_pressure_rectilinear_ion_processor"
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import _lua
        priority = dict(role="mrtof_native_corridor_iob_priority_contract", accelerator_provider=provider,
                        instances=[dict(role=role, priority_number=index) for index, role in enumerate(
                            ("global_fallback", "native_corridor", "ion_processor_collision", "detector"), 1)])
        (batch_dir / "joint.priority.lua").write_text("return " + _lua(priority))
        source = batch_dir / "measured_source/source.fly2"
        before = source.read_bytes()
        expected = file_record(source)
        lua = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
        if not Path(lua).is_file():
            self.skipTest("Plain Lua unavailable; no solver fallback")
        script = root / "builder_save_overwrites.lua"
        script.write_text(r'''
local directory,builder=arg[1],arg[2]
local request=assert(loadfile(directory..'/joint.workbench_build.lua'))()
assert(request.fly2:gsub('\\','/')==directory..'/measured_source/source.fly2','independent source required')
local instances={}
for i=1,4 do
 instances[i]={scale=1,pa={nx=11,ny=11,nz=11,dx_mm=1,dy_mm=1,dz_mm=1}}
 instances[i].pa.load=function(self,path) self.path=path end
 instances[i]._debug_update_size=function() end
end
local probes=0
simion={wb={instances=instances,
 load=function(self,path) self.filename=path end,
 save=function(self,path)
  local handle=assert(io.open(path:gsub('%.iob$','.fly2'),'wb'))
  handle:write('particles { standard_beam { mass=0.00054858,charge=-1,tob=0, } }')
  handle:close()
 end,
 find_at=function() probes=probes+1;return 0,probes+1 end}}
arg={'--measured-source',directory..'/joint.workbench_build.lua'}
dofile(builder)
assert(probes==3)
print('ACTUAL_BUILDER_SAVE_SOURCE_RESTORATION=PASS')
''', encoding="utf-8")
        builder = Path(__file__).resolve().parents[2] / "simion/build_native_corridor_iob.lua"
        result = subprocess.run([lua, str(script), batch_dir.as_posix(), str(builder)], cwd=root,
                                timeout=30, capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ACTUAL_BUILDER_SAVE_SOURCE_RESTORATION=PASS", result.stdout)
        self.assertEqual(source.read_bytes(), before)
        restored = file_record(batch_dir / "joint.fly2")
        self.assertEqual((restored["sha256"], restored["bytes"]), (expected["sha256"], expected["bytes"]))
        self.assertEqual((batch_dir / "joint.fly2").read_bytes(), before)
        self.assertEqual(before.count(b"standard_beam {"), 2)

    def test_representation_comparison_preserves_every_prefix_event_and_sample(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest = root / "reference.log", root / "reference_manifest.json"
            text = ("MRTOF_TRAJECTORY ion=7 phase=birth t_us=7500.57 x_mm=0.1\n"
                    "MRTOF_EVENT terminal ion=7 t_us=7501.57\n")
            baseline.write_text(text)
            manifest.write_text('{}')
            preparation = root / "preparation.json"
            preparation.write_text(json.dumps(dict(trajectory_equivalence_reference=dict(
                reference_log=file_record(baseline),reference_manifest=file_record(manifest),
                original_particle_ids=[7]))))
            current = root / "current.log"
            current.write_text(text+"MRTOF_EVENT terminal ion=9 t_us=7502\n")
            receipt = root / "equivalence.json"
            result = compare_trajectory_representation(preparation,current,receipt)
            self.assertEqual(result["status"],"pass")
            self.assertEqual(result["compared_line_count"],2)
            self.assertFalse(result["physical_matching_qualified"])
            current.write_text(text.replace("x_mm=0.1","x_mm=0.10000000000000002"))
            with self.assertRaisesRegex(ValueError,"differs"):
                compare_trajectory_representation(preparation,current,receipt)
            failure=json.loads(receipt.read_text())
            self.assertEqual(failure["status"],"fail")
            self.assertEqual(failure["first_mismatches"][0]["selected_line"],1)

    def test_memory_crop_uses_frozen_mirror_policy_without_changing_source(self):
        names = ["positive_integer_grid_a", "negative_integer_grid_a", "covered_local"]
        targets = [dict(pitch_mm=[.04,.2,.04],stored_xmax_mm=1.28),
                   dict(pitch_mm=[.04,.2,.04],stored_xmax_mm=1.28),dict(pitch_mm=[.25,.25,.1])]
        contract = dict(simion=dict(numerical_profiles=dict(native_static_field=dict(target_layout=dict(windows=targets)))))
        reference = dict(field_binding=dict(refinement_windows=[dict(name=name) for name in names]))
        windows = [dict(name=name,grid=dict(origin_mm=[0,-65,z],pitch_mm=[.04,.2,.04],
                       dimensions=[51,2126,11701]),active_box_mm=[[-1,1],[-64.75,359.75],[90.25,323.75]])
                   for name,z in zip(names[:2],[90,-324])]
        binding = dict(refinement_windows=[dict(name="ion_processor_local"),*windows])
        before = json.dumps(binding)
        result = compile_memory_consumer_crops(contract,reference,binding)
        self.assertEqual(json.dumps(binding),before)
        self.assertEqual(set(result),set(names[:2]))
        for descriptor in result.values():
            self.assertEqual(descriptor["source_dimensions"],[51,2126,11701])
            self.assertEqual(descriptor["consumer_dimensions"],[33,2126,11701])
            self.assertEqual(descriptor["width_grid"],[32,2125,11700])
        targets[0]["stored_xmax_mm"]=1.0
        with self.assertRaisesRegex(ValueError,"halo"):
            compile_memory_consumer_crops(contract,reference,binding)

    def test_local_batch_fly2_and_actual_lua_launcher_keep_original_id_and_epoch(self):
        fixture = source_fixtures.MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        full = fixture._materialize()
        root = fixture.root
        runtime = root / "runtime"
        runtime.mkdir()
        (runtime / "joint.iob").write_bytes(b"mock saved IOB; no vendor load")
        (runtime / "joint.lua").write_text("-- plain mock program")
        (runtime / "joint.operating_point.lua").write_text("return {static_field=nil}")
        preparation = root / "prepared.json"
        preparation.write_text(json.dumps(dict(measured_source_directory=str(fixture.output),
            frozen_runtime_directory=str(runtime), trajectory_recording=dict(mode="fixed_interval",interval_us=.1))))
        batch_dir = root / "batch"
        batch = materialize_batch(preparation, 2, 2, batch_dir)
        self.assertEqual(batch["original_particle_ids"], [7])
        self.assertEqual((batch_dir / "joint.fly2").read_text().count("standard_beam {"), 1)
        with (batch_dir / "measured_source/ordinal_source_map.csv").open(newline="") as handle:
            mapping = next(csv.DictReader(handle))
        self.assertEqual(int(mapping["simion_ordinal"]), 1)
        lua = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
        if not Path(lua).exists():
            self.skipTest("Plain Lua interpreter is unavailable")
        launcher = Path(__file__).resolve().parents[2] / "simion/run_iob_flight.lua"
        script = root / "mock_launcher.lua"
        script.write_text("""
local directory,launcher,epoch,t=arg[1],arg[2],tonumber(arg[3]),tonumber(arg[4])
local module=assert(loadfile(directory..'/measured_source/source_runtime.lua'))()
local source=module.load(directory..'/measured_source')
local initialized=source.initialize(1);assert(initialized.t==t)
assert(source.source_id(1)==7)
assert(source.instrument_time_us(t)==epoch+t)
local point=assert(loadfile(directory..'/joint.operating_point.lua'))()
assert(point.trajectory_recording_mode=='fixed_interval' and point.trajectory_recording_interval_us==.1)
local calls=0
simion={command=function(command)
 calls=calls+1
 assert(command:find('--particles="'..directory..'/joint.fly2"',1,true))
 assert(not command:find('11..20',1,true))
end}
arg={directory..'/joint.iob',directory..'/joint.fly2'}
assert(loadfile(launcher))()
assert(calls==1)
print('LOCAL_BATCH_LAUNCH_MAPPING_PASS')
""", encoding="utf-8")
        result = subprocess.run([lua,str(script),batch_dir.as_posix(),launcher.as_posix(),
                                 str(full["solver_epoch_instrument_time_us"]),mapping["solver_birth_time_us"]],
                                cwd=Path(__file__).resolve().parents[4],timeout=30,
                                capture_output=True,text=True,encoding="utf-8",errors="replace",check=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("LOCAL_BATCH_LAUNCH_MAPPING_PASS",result.stdout)

    def test_public_manifest_and_stopped_payload_seal_above_light_budget(self):
        from common.contracts.artifact_retention import apply_retention
        from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
        from common.contracts.file_identity import file_sha256
        from common.contracts.run_capacity_lifecycle import finalize_ready, register_writing, seal_checkpoint
        from common.contracts.write_run_manifest import build_run_manifest
        for status in ("success", "failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                initialize_capacity_ledger(root, objects=[])
                run = root / "projects/p/runs/20261016_200001__sim__simion__payload-fixture"
                run.mkdir(parents=True)
                config = run / "run_config.json"
                config.write_text(json.dumps(dict(schema_version=2,run_id=run.name,project="p",inputs={},
                    artifact_retention=dict(policy_version=1,**{"class":"solver_review"},reason="fixture trajectories"),
                    capacity_ledger_lifecycle=dict(schema_version=1,enabled=True,artifact_root=str(root),
                                                  light_evidence_budget_bytes=26214400))))
                summary = run / "summary.json"
                summary.write_text(json.dumps(dict(status=status)))
                register_writing(root,config)
                payload = run / "trajectory_samples.csv"
                with payload.open("wb") as handle:
                    handle.truncate(26214401)
                retained = apply_retention(config)
                manifest = run / "run_manifest.json"
                manifest.write_text(json.dumps(build_run_manifest(config,status,
                    output_paths=[summary,payload,retained])))
                verify = subprocess.run([sys.executable,"-m","common.contracts.verify_run_manifest",str(manifest),
                                         "--require-status",status],capture_output=True,text=True,
                                        cwd=Path(__file__).resolve().parents[4],timeout=60,
                                        encoding="utf-8",errors="replace",check=False)
                self.assertEqual(verify.returncode,0,verify.stdout+verify.stderr)
                identity = file_sha256(manifest)
                with self.assertRaisesRegex(ValueError,"cannot become light_evidence"):
                    finalize_ready(root,config)
                with self.assertRaises(ValueError):
                    seal_checkpoint(root,config,owner="wrong",writing_stopped=True,retain_payload=True,
                                    retention_reason="fixture trajectories")
                self.assertEqual(file_sha256(manifest),identity)
                receipt = seal_checkpoint(root,config,owner="p",writing_stopped=True,retain_payload=True,
                                          retention_reason="fixture trajectories")
                self.assertEqual(receipt["status"],"ready")
                entry = load_capacity_ledger(root)["objects"][0]
                self.assertEqual(entry["class"],"rebuildable_payload")
                self.assertEqual(entry["status"],"ready")
                self.assertGreater(entry["bytes"],26214400)
                self.assertEqual(file_sha256(manifest),identity)
                self.assertEqual(json.loads(manifest.read_text())["status"],status)

    def test_merge_preserves_noncontiguous_original_ids_and_absolute_clock(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preparation = root / "preparation.json"
            preparation.write_text(json.dumps(dict(expected_particle_ids=[1,7],mother_particle_count=3,
                                                   solver_epoch_instrument_time_us=7500.5)))
            batches = []
            for ordinal, identifier in enumerate([1,7], 1):
                batch_dir = root / f"batch{ordinal}"
                batch_dir.mkdir()
                log, receipt = batch_dir / "flight.log", batch_dir / "batch_receipt.json"
                fly = batch_dir / "joint.fly2"
                fly.write_text("particles { standard_beam { tob = 0.01, } }")
                log.write_text(f"MRTOF_TRAJECTORY ion={identifier} phase=birth t_us=7500.51\n"
                               f"MRTOF_EVENT terminal ion={identifier} t_us=7501.5 splat=-1\n"
                               "status,Fly completed. 1 splats\n")
                receipt.write_text(json.dumps(dict(schema_version=1, role="mrtof_measured_source_batch",
                                                   outputs=dict(source=file_record(fly)), count=1,original_particle_ids=[identifier],
                                                   solver_epoch_instrument_time_us=7500.5)))
                batches.append((log,receipt))
            result = merge_measured_event_logs(batches=batches, preparation_path=preparation,
                                               output_path=root/"merged.log", receipt_path=root/"merged.json")
            self.assertEqual(result["original_particle_ids"], [1,7])
            self.assertEqual(result["mother_particle_count"], 3)
            self.assertFalse(result["id_rebasing_applied"])
            self.assertEqual(result["preparation"], file_record(preparation))
            self.assertEqual(len(result["batches"]), 2)
            self.assertTrue(all("fly2" in row for row in result["batches"]))
            self.assertIn("ion=7 t_us=7501.5", (root/"merged.log").read_text())
            for changed in ("wrong_id", "missing_terminal", "wrong_epoch", "duplicate_batch"):
                with self.subTest(changed=changed):
                    log, receipt = batches[-1]
                    original_log, original_receipt = log.read_text(), receipt.read_text()
                    selected = batches
                    if changed == "wrong_id":
                        log.write_text(original_log.replace("ion=7", "ion=2"))
                    elif changed == "missing_terminal":
                        log.write_text(original_log.replace("MRTOF_EVENT terminal", "IGNORED terminal"))
                    elif changed == "wrong_epoch":
                        value=json.loads(original_receipt); value["solver_epoch_instrument_time_us"]=7500.6
                        receipt.write_text(json.dumps(value))
                    else:
                        selected = [batches[0],batches[0]]
                    with self.assertRaises(ValueError):
                        merge_measured_event_logs(batches=selected,preparation_path=preparation,
                                                  output_path=root/"bad.log",receipt_path=root/"bad.json")
                    log.write_text(original_log); receipt.write_text(original_receipt)
            fly = batches[-1][1].parent / "joint.fly2"
            original = fly.read_bytes()
            for content in (b"tampered", None):
                if content is None:
                    fly.unlink()
                else:
                    fly.write_bytes(content)
                with self.assertRaisesRegex(AssertionError, "actual launched batch FLY2"):
                    merge_measured_event_logs(batches=batches, preparation_path=preparation,
                                             output_path=root/"bad.log", receipt_path=root/"bad.json")
                fly.write_bytes(original)
