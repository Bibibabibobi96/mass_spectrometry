import copy
import tempfile
import unittest
from pathlib import Path

from msplatform.backends.simion.downstream import compile_downstream_specs, split_downstream_targets
from msplatform.backends.simion.frontend import split_frontend_instances
from msplatform.components.single_reflection_tof.legacy_projection import project_legacy_downstream
from tests.contracts.test_simion_geometry_compiler import compiler_inputs


class SplitTofSimionTests(unittest.TestCase):
    def test_split_selector_keeps_independent_instances_and_rejects_legacy(self):
        plan = {"schema_version": 6, "scope": {"instance_ids": ["rf", "oa", "tof"]},
                "components": {"rf": {"project_id": "rf_multipole_ion_optics"},
                               "oa": {"project_id": "orthogonal_accelerator"},
                               "tof": {"project_id": "single_reflection_tof"}}}
        self.assertEqual(split_frontend_instances(plan), (("rf",), "oa", "tof"))
        plan["components"]["tof"]["project_id"] = "single_reflection_oa_tof_mass_analyzer"
        with self.assertRaisesRegex(ValueError, "unsupported split native component"):
            split_frontend_instances(plan)

    def test_real_downstream_template_projection_preserves_geometry_and_voltages(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, _, _ = compiler_inputs(Path(directory))
            original = assembly["components_resolved"]["oatof"]
            split = project_legacy_downstream(original)
            split.update(simion_geometry_build=copy.deepcopy(original["simion_geometry_build"]),
                         simion_detector_marker=copy.deepcopy(original["simion_detector_marker"]))
            targets = split_downstream_targets(split)
            self.assertEqual({item["domain"] for item in targets["common_ground"]},
                             {"flight_tube", "reflectron", "detector"})
            self.assertIn("reflectron_midgrid", targets)
            before = copy.deepcopy(split)
            old = compile_downstream_specs(original)
            new = compile_downstream_specs(split, split=True)
            self.assertEqual(split, before)
            for previous, current in zip(old, new, strict=True):
                self.assertEqual(previous["role"], current["role"])
                self.assertEqual(previous["native_instance"], current["native_instance"])
                self.assertEqual(previous["template_text"], current["template_text"])
                left, right = copy.deepcopy(previous["template_variables"]), copy.deepcopy(current["template_variables"])
                for variables in (left, right):
                    component = variables.get("component")
                    if component:
                        for electrode in component["electrodes"]:
                            electrode.pop("component_electrode_id")
                self.assertEqual(left, right)

    def test_split_two_component_geometry_uses_real_provider_snapshots(self):
        from msplatform import assembly as api, components, examples
        from msplatform.backends.simion.compiler import compile_geometry
        from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
            resolve_accelerator_geometry, apply_side_opening, resolve_oa_provider)
        with tempfile.TemporaryDirectory() as directory:
            original, numerics, _ = compiler_inputs(Path(directory))
            old = components.resolve_component(examples.load_example("rf_oatof_functional_v1").component_requests["oatof"]).resolved_design
            projection = apply_side_opening(resolve_accelerator_geometry(old, variant_id="three_zone_square"),
                                            side_opening=old["mechanical_side_opening"])
            source = resolve_oa_provider(old, projection=projection, geometry_profile_id=None)["source"]
            oa = components.resolve_component({"provider_id": "orthogonal_accelerator", "design": {"instrument_geometry": source}})
            tof = components.resolve_component({"provider_id": "single_reflection_tof", "design": project_legacy_downstream(old)})
            def pose(frame):
                return {"schema_version": 1, "role": "rigid_transform", "from_frame_id": frame,
                        "to_frame_id": "oatof_global", "rotation": [[1,0,0],[0,1,0],[0,0,1]], "translation_mm": [0,0,0]}
            recipe = {"schema_version": 2, "role": "assembly_recipe", "integration_id": "instrument_assembly",
                      "recipe_id": "oa_downstream", "assembly_frame_id": "oatof_global",
                      "position_tolerance_mm": 1e-8, "angular_tolerance_rad": 1e-10,
                      "instances": [{"instance_id": name, "project_id": component.assembly_interface["project_id"],
                                     "transform": pose(component.assembly_interface["local_frame_id"])}
                                    for name, component in (("oa", oa), ("tof", tof))],
                      "connections": [], "containments": [{"relation_id": "oa_inside_tof", "container_instance_id": "tof",
                          "contained_instance_id": "oa", "domain_id": "flight_tube_cavity", "coupling_mode": "monolithic_joint_solve"}]}
            instrument = api.assemble(recipe, {"oa": oa, "tof": tof})
            inputs = {"composition_plan": instrument.composition_plan,
                      "components_resolved": {"oa": oa.resolved_design, "tof": tof.resolved_design}}
            # Original frozen coordinates differ at the upper face by one ULP.
            original_numerics = examples.load_example("rf_oatof_functional_v1")._document["numerics"]["geometry"]
            # The existing detector grid forecasts 85.057 MiB; admit the same
            # geometry under an explicit 128 MiB engineering budget.
            original_numerics['geometry_build']['detector']['max_mib'] = 128.
            numerics['geometry_build']['detector']['max_mib'] = 128.
            original_result = compile_geometry(inputs, numerics=original_numerics)
            self.assertEqual(original_result.frontend_geometry["numerical_domains"]["parent"]["dimensions"],
                             {"nx": 118, "ny": 76, "nz": 3201})
            clipped_numerics = copy.deepcopy(original_numerics)
            clipped_numerics["frontend_domains"]["parent"]["pa_bounds_mm"]["z_max"] -= .1
            with self.assertRaisesRegex(ValueError, "omits OA material"):
                compile_geometry(inputs, numerics=clipped_numerics)
            numerics["frontend_domains"] = {"parent": {"cell_mm_xyz": {"x": 1., "y": 1., "z": .1},
                "pa_bounds_mm": {"x_min": -100., "x_max": 70., "y_min": -80., "y_max": 80., "z_min": -40.02918680341103, "z_max": 290.070813196589}}}
            result = compile_geometry(inputs, numerics=numerics)
            self.assertEqual(result.frontend_geometry["role"], "simion_split_oa_tof_geometry")
            self.assertEqual(result.frontend_geometry["oa_instance_id"], "oa")
            self.assertEqual(result.frontend_geometry["tof_instance_id"], "tof")
            self.assertEqual([x["native_instance"]["priority_number"] for x in result.downstream_specs], [1,2,4])
            from msplatform.backends.simion.model import PHYSICS, compile_prepared_model
            from msplatform.components.single_reflection_tof.geometry import resolve_downstream_geometry
            oa_groups = {group: ({"kind": "static", "voltage_v": 0.} if group == "grounded_shield" else
                                  {"kind": "pulse", "off_voltage_v": 0., "on_voltage_v": 0. if group == "exit_grid" else 1.})
                         for group in result.frontend_geometry["electrode_bindings"]["oa"]}
            physical = resolve_downstream_geometry(tof.resolved_design["geometry_mm"], tof.resolved_design["coordinate_convention"],
                                                   tof.resolved_design["rings"], tof.resolved_design["electrodes_v"])
            tof_groups = {("common_ground" if row["grounded"] else row["role"]):
                          {"kind": "static", "voltage_v": row["operating_voltage_v"]} for row in physical["electrodes"]}
            drive = {"groups": {"oa": oa_groups, "tof": tof_groups}, "pulse": {"mode": "timed", "time_us": 1., "width_us": 2.},
                     "clock": {"clock_epoch_id": "fixture", "authority_sha256": "0" * 64, "phase_reference_instrument_time_us": 0.}}
            model = compile_prepared_model(result, inputs["components_resolved"], drive=drive, physics=PHYSICS)
            self.assertEqual(model.document["field_status"], "not_solved")
            self.assertTrue(any(row["instance_id"] == "oa" and row["electrode_group_id"] == "grounded_shield"
                                for row in model.document["native_drive_rows"]))
            self.assertTrue(any(row["instance_id"] == "tof" and row["electrode_group_id"] == "common_ground"
                                for row in model.document["native_drive_rows"]))
            study = examples.load_example("rf_oatof_functional_v1")
            rf = components.resolve_component(study.component_requests["multipole"])
            original_recipe = copy.deepcopy(study._document["recipe"])
            original_recipe["schema_version"] = 2
            original_recipe["instances"][1] = recipe["instances"][0]
            original_recipe["instances"].append(recipe["instances"][1])
            original_recipe["connections"][0]["downstream"]["instance_id"] = "oa"
            original_recipe["containments"] = recipe["containments"]
            triple = api.assemble(original_recipe, {"multipole": rf, "oa": oa, "tof": tof})
            triple_inputs = {"composition_plan": triple.composition_plan, "components_resolved":
                             {"multipole": rf.resolved_design, "oa": oa.resolved_design, "tof": tof.resolved_design}}
            numerics["frontend_domains"]["parent"]["pa_bounds_mm"]["x_min"] = -200.
            triple_result = compile_geometry(triple_inputs, numerics=numerics)
            self.assertEqual(set(triple_result.frontend_geometry["electrode_bindings"]), {"oa", "multipole"})
            self.assertEqual(len(triple_result.frontend_gems), 1)
            from msplatform.backends.simion.native_plans import plan_geometry_build
            from tests.contracts.test_simion_native_plans import SEED, NATIVE_PATH
            geometry_plan = plan_geometry_build(triple_result, run_directory=Path(directory) / "native",
                                                seed_record=SEED, native_path_resource=NATIVE_PATH)
            self.assertEqual([row["operation_id"] for row in geometry_plan.operations],
                             ["geometry_flight_tube", "geometry_reflectron", "geometry_detector", "geometry_parent", "build_geometry", "verify_geometry"])
            from msplatform.backends.simion.electrode_contract import scientific_multipole_drive
            drive["groups"]["multipole"] = scientific_multipole_drive(rf.resolved_design,
                triple_result.frontend_geometry["electrode_bindings"]["multipole"])
            triple_model = compile_prepared_model(triple_result, triple_inputs["components_resolved"], drive=drive, physics=PHYSICS)
            self.assertTrue(triple_model.document["electrical_projection"]["rf_groups"]["multipole"])
            from msplatform.backends.simion.model import model_geometry
            roundtrip = triple_model.document
            rebuilt = compile_prepared_model(model_geometry(triple_model), roundtrip["components_resolved"],
                                              drive=roundtrip["drive"], physics=roundtrip["physics"])
            self.assertEqual(rebuilt.document, roundtrip)
            self.assertEqual(rebuilt.document["model_identity_sha256"], roundtrip["model_identity_sha256"])
            import json, sys
            from dataclasses import asdict
            from types import SimpleNamespace
            from unittest.mock import patch
            from msplatform.backends import simion
            from msplatform.contracts.machine_contracts import ContractError
            from msplatform.io.manifest_records import file_record
            self.assertEqual(simion.compile_geometry(triple, numerics=numerics), triple_result)
            root = Path(directory)
            compiled_path = root / "split-compiled.json"
            compiled_path.write_text(json.dumps(asdict(triple_result)), encoding="utf-8")
            manifest = root / "split-inert-manifest.json"
            manifest.write_text("inert", encoding="utf-8")
            source = SimpleNamespace(reference={"manifest": file_record(manifest, "required_evidence"), "product_id": "geometry"},
                                     data_path=lambda _: compiled_path)
            context = SimpleNamespace(tools={"simion": Path(sys.executable)}, execution_root=root / "execution", workspace=root)
            stage = {"limits": {"transient_run_directory_bytes": 1}, "artifact_retention": {}}
            with patch("msplatform.execution.stage_policy.read_stage_policy", return_value=(stage, {})), \
                 patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {}}) as build_owner, \
                 patch("msplatform.results.artifacts.open_artifact", return_value="INERT_GEOMETRY"):
                with self.assertRaisesRegex(ContractError, "requires an ArtifactStore"):
                    simion.build_geometry(triple_result, context=context)
                build_owner.assert_not_called()
                store = object()
                self.assertEqual(simion.build_geometry(triple_result, context=context, artifact_store=store), "INERT_GEOMETRY")
            self.assertIs(build_owner.call_args.kwargs["artifact_store"], store)
            self.assertEqual(build_owner.call_args.kwargs["action"].keywords["seed_record"]["bytes"], SEED["bytes"])
            authored_drive = {"groups": drive["groups"], "pulse": drive["pulse"],
                              "clock": {"phase_reference_instrument_time_us": 0.},
                              "clock_authority": {"example_resource": "instrument_clock_authority_v1.json"}}
            from contextlib import ExitStack, nullcontext
            from msplatform.execution.owner import managed_native_store
            from msplatform.storage import ArtifactStore
            store = ArtifactStore(root / "store")
            with ExitStack() as lifetime, managed_native_store(store, task_key="split-model-fixture", lifetime=lifetime, account=lambda _: None), \
                 patch("msplatform.execution.native_source_guard.guard_native_source", side_effect=lambda *args, **kwargs: nullcontext()), \
                 patch("msplatform.backends.simion.operations.artifact_reader.open_artifact", return_value=source), \
                 patch("msplatform.execution.stage_policy.read_stage_policy", return_value=(stage, file_record(manifest, "required_evidence"))), \
                 patch("msplatform.execution.owner.run_managed_stage", side_effect=RuntimeError("INERT_OWNER")) as managed:
                with self.assertRaisesRegex(RuntimeError, "INERT_OWNER"):
                    simion.prepare_model(source.reference, drive=authored_drive, physics=PHYSICS, context=context)
            request = managed.call_args.kwargs
            self.assertEqual(request["expected_operation_ids"], ("materialize_geometry", "build_model", "verify_model"))
            self.assertEqual(request["payload"]["model"]["drive"]["groups"], authored_drive["groups"])
            self.assertEqual(request["action"].keywords["seed_record"]["bytes"], SEED["bytes"])
            from msplatform.assembly.handoff import HandoffClock, HandoffMother, HandoffResult
            from msplatform.backends.simion.model import project_resolved_drive
            from msplatform.contracts.clock import ClockIdentity
            from msplatform.contracts.machine_contracts import ContractError
            clock = ClockIdentity("fixture", "0" * 64)
            empty_handoff = HandoffResult((), (), (), HandoffMother({}, ()), HandoffClock(clock, clock), "time_snapshot")
            old_geometry = compile_geometry(original, numerics={k: v for k, v in compiler_inputs(root / "legacy")[1].items()})
            old_clock = {"clock_epoch_id": "fixture", "authority_sha256": "0" * 64, "phase_reference_instrument_time_us": 0.}
            old_drive = project_resolved_drive(old_geometry, original["components_resolved"], clock=old_clock,
                                               pulse={"mode": "timed", "time_us": 1., "width_us": 2.})
            old_model = compile_prepared_model(old_geometry, original["components_resolved"], drive=old_drive, physics=PHYSICS)
            for label, actual_model in (("split", triple_model), ("legacy", old_model)):
                model_path = root / (label + "-model.json")
                model_path.write_text(json.dumps(actual_model.document), encoding="utf-8")
                field_source = SimpleNamespace(kind="field_bundle", metadata={"backend": "simion", "field_status": "available",
                    "source_status": "not_requested", "model_identity_sha256": actual_model.document["model_identity_sha256"],
                    "clock": actual_model.document["drive"]["clock"]}, data_path=lambda _key: model_path)
                for particle, scope in ((empty_handoff, "continuous_assembly"), ({}, "state_relaunch"), ({}, "segmented_upstream")):
                    with self.subTest(model=label, scope=scope), \
                         patch("msplatform.backends.simion.operations.artifact_reader.open_artifact", return_value=field_source), \
                         patch("msplatform.execution.owner.run_managed_stage") as tracking_owner, \
                         self.assertRaisesRegex(ContractError, "historical read-only" if label == "legacy" else "continuous_assembly"):
                        simion.track({}, particle, propagation={"scope": scope}, observations={}, numerics={}, context=context)
                    tracking_owner.assert_not_called()


            from msplatform.backends.simion.fields import prepare_split_field_design
            design = prepare_split_field_design(triple_inputs["components_resolved"], triple_result.frontend_geometry,
                physics=PHYSICS, frontend_domains={"parent": {"refine_convergence_v":
                    {"carrier_off": .1, "rf_reference": .1, "pulse_delta": .1}}},
                electrical_projection=triple_model.document["electrical_projection"], pulse=drive["pulse"], rf_reference_voltage_v=100.)
            self.assertEqual([row["kind"] for row in design["working_points"]], ["carrier_off", "rf_reference", "pulse_delta"])
            from msplatform.backends.simion.field_validation import require_supported_split_interfaces, native_priority_occupancy_probes, interface_field_probes
            require_supported_split_interfaces(triple_result.frontend_geometry, design)
            self.assertTrue(native_priority_occupancy_probes(triple_result.frontend_geometry, design))
            self.assertEqual(len(interface_field_probes(triple_result.frontend_geometry, tof.resolved_design)), 2)
            from msplatform.backends.simion.field_execution import plan_fields_execution
            field_plan = plan_fields_execution(triple_model, numerics={"frontend_domains": {"parent": {
                "refine_convergence_v": {"carrier_off": .1, "rf_reference": .1, "pulse_delta": .1}}},
                "rf_reference_voltage_v": 100., "downstream_convergence_v": {"flight_tube": .1, "reflectron": .1, "detector": .1}})
            self.assertEqual([row["member_id"] for row in field_plan["field_plan"]["ordered_members"]],
                             ["carrier_off", "rf_reference", "pulse_delta"])
            self.assertIn("downstream_fields", field_plan["expected_operation_ids"])
            field_numerics = {"frontend_domains": {"parent": {"refine_convergence_v":
                {"carrier_off": .1, "rf_reference": .1, "pulse_delta": .1}}}, "rf_reference_voltage_v": 100.,
                "downstream_convergence_v": {"flight_tube": .1, "reflectron": .1, "detector": .1}}
            with ExitStack() as field_lifetime, managed_native_store(store, task_key="split-fields-fixture", lifetime=field_lifetime, account=lambda _: None), \
                 patch("msplatform.execution.native_source_guard.guard_native_source", side_effect=lambda *args, **kwargs: nullcontext()), \
                 patch("msplatform.backends.simion.field_closure.load_field_model", return_value=SimpleNamespace(model=triple_model, artifact=source)), \
                 patch("msplatform.execution.stage_policy.read_stage_policy", return_value=(stage, file_record(manifest, "required_evidence"))), \
                 patch("msplatform.execution.owner.run_managed_stage", side_effect=RuntimeError("INERT_FIELDS_OWNER")) as fields_owner:
                with self.assertRaisesRegex(RuntimeError, "INERT_FIELDS_OWNER"):
                    simion.solve_fields(source.reference, numerics=field_numerics, context=context)
            self.assertIn("downstream_fields", fields_owner.call_args.kwargs["expected_operation_ids"])

            from msplatform.backends.simion.native_plans import plan_model_preparation, plan_downstream_solve, plan_field_workbench
            def record(name):
                return {"path": str(Path(directory) / name), "bytes": 1, "sha256": "0" * 64}
            assets = {role: {"raw_record": record(role + ".pa#"), "surface_records":
                      [record(role + ".pa-surf")] if role in {"flight_tube", "detector"} else []}
                      for role in ("flight_tube", "reflectron", "detector", "parent")}
            model_plan = plan_model_preparation(triple_model, geometry_assets=assets, run_directory=Path(directory) / "model",
                                                seed_record=SEED, native_path_resource=NATIVE_PATH)
            self.assertTrue(model_plan.operations)
            down_plan = plan_downstream_solve(triple_model, raw_geometry_assets={k: v for k, v in assets.items() if k != "parent"},
                working_directory=Path(directory) / "down", convergence_v={"flight_tube": .1, "reflectron": .1, "detector": .1},
                exporter_resource=NATIVE_PATH, verifier_resource=NATIVE_PATH)
            self.assertTrue(any(row["operation_id"] == "audit_downstream" for row in down_plan.operations))
            carrier = {k: record(k + ".pa0") for k in ("flight_tube", "reflectron", "detector", "accelerator")}
            grid = dict(design["domains"][0]["dimensions"], **{f"d{a}_mm": design["domains"][0]["cell_mm_xyz"][a] for a in "xyz"})
            responses = [{"domain": "parent", "kind": kind, "path": str(Path(directory) / (kind + ".pa")), "grid": grid}
                         for kind in ("rf_reference", "pulse_delta")]
            field_workbench = plan_field_workbench(triple_result, field_design=design,
                components_resolved=triple_inputs["components_resolved"], carriers=carrier, response_fields=responses,
                run_directory=Path(directory) / "workbench", seed_record=SEED, native_path_resource=NATIVE_PATH)
            self.assertEqual(len(field_workbench.operations), 2)
            self.assertEqual(len(design["domains"][0]["physical_samples"]),
                             len(triple_result.frontend_geometry["raw_physical_samples"]["parent"]) - 1)
            self.assertTrue(any(row["label"].startswith("multipole:")
                                for row in triple_result.frontend_geometry["raw_physical_samples"]["parent"]))
            bad = copy.deepcopy(drive)
            bad["groups"]["oa"]["repeller"]["off_voltage_v"] = 1.
            with self.assertRaisesRegex(ValueError, "all-zero OFF"):
                compile_prepared_model(triple_result, triple_inputs["components_resolved"], drive=bad, physics=PHYSICS)
            bad = copy.deepcopy(drive)
            bad["groups"]["tof"]["common_ground"]["voltage_v"] = 1.
            with self.assertRaisesRegex(ValueError, "common ground"):
                compile_prepared_model(triple_result, triple_inputs["components_resolved"], drive=bad, physics=PHYSICS)


    def test_split_detector_marker_must_match_physical_face(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, _, _ = compiler_inputs(Path(directory))
            original = assembly["components_resolved"]["oatof"]
            split = project_legacy_downstream(original)
            split.update(simion_geometry_build=copy.deepcopy(original["simion_geometry_build"]),
                         simion_detector_marker=copy.deepcopy(original["simion_detector_marker"]))
            split["simion_detector_marker"]["active_plane_z_mm"] += 1
            with self.assertRaisesRegex(ValueError, "differs from the physical detector active face"):
                compile_downstream_specs(split, split=True)
