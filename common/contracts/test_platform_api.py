"""Real provider/API wiring and independent port-mating arithmetic."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform import api, assembly as assembly_api, components as component_api, examples as example_api
from msplatform import execution as execution_api
from msplatform.backends import simion as simion_api
from msplatform.contracts.machine_contracts import ContractError


def compile_example():
    case = example_api.load_example("rf_oatof_functional_v1")
    components = {name: component_api.resolve_component(request) for name, request in case.component_requests.items()}
    assembly = assembly_api.assemble(case.recipe, components)
    return case, components, assembly, simion_api.compile_geometry(assembly, numerics=case.geometry_numerics)


class PlatformApiTests(unittest.TestCase):
    def test_public_trajectory_comparison_opens_explicit_references_and_existing_products_read_only(self):
        from common.contracts.test_simion_trajectory_comparison import PublishedTrajectoryComparisonTests
        fixture = PublishedTrajectoryComparisonTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        left, right = [fixture.opened(value) for value in fixture.fixtures]
        selection, method = copy.deepcopy(fixture.selection), copy.deepcopy(fixture.method)
        with patch("subprocess.Popen", side_effect=AssertionError("tool")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")), \
             patch.object(Path, "write_text", side_effect=AssertionError("write")), \
             patch("msplatform.execution.owner.run_managed_stage", side_effect=AssertionError("owner")):
            result = api.compare_trajectories(left.reference, right.reference, selection=selection, method=method)
            opened = api.compare_trajectories(left, right, selection=selection, method=method)
        self.assertEqual(result, opened)
        self.assertEqual(result["status"], "comparison_completed")
        self.assertEqual(result["matched_particle_ids"], [7, 99, 123])
        self.assertEqual(result["coverage"]["left"]["denominator_count"], 4)
        self.assertEqual(result["producers"]["left"]["status"], "failed")
        self.assertEqual(result["scientific_qualification"], "not_granted")
        self.assertEqual(selection, fixture.selection)
        self.assertEqual(method, fixture.method)

    def test_finalization_api_delegates_original_owner_without_an_action_callback(self):
        from msplatform.backends.simion import native_completion
        from msplatform.exporters.execution import no_particle_batch_completion_api

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inputs").mkdir()
            request = root / "inputs/execution_request.json"
            result = root / "result.json"
            result.write_text(json.dumps(dict(run_directory=str(root))), encoding="utf-8")
            context = execution_api.load_environment(workspace=root,
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3"))
            sentinel = {"original_owner_fixture": True}
            with patch("msplatform.execution.owner.resume_finalization", return_value=sentinel) as resume, \
                 patch("subprocess.Popen", side_effect=AssertionError("API must not replay science")):
                for action, expected in (("solve_fields", native_completion),
                                         ("export_cad", no_particle_batch_completion_api())):
                    request.write_text(json.dumps(dict(payload=dict(action=action))), encoding="utf-8")
                    with self.subTest(action=action):
                        self.assertIs(api.resume_run(result, mode="finalization", context=context), sentinel)
                        args, keywords = resume.call_args
                        self.assertEqual(args, (context, result))
                        self.assertIs(keywords["completion_api"](), expected)
                        self.assertEqual(set(keywords), {"completion_api"})
                resume.reset_mock()
                with self.assertRaisesRegex(ContractError, "supports finalization"):
                    api.resume_run(result, mode="native_checkpoint", context=context)
                request.write_text(json.dumps(dict(payload=dict(action="unrecognized"))), encoding="utf-8")
                with self.assertRaisesRegex(ContractError, "completion policy"):
                    api.resume_run(result, mode="finalization", context=context)
                resume.assert_not_called()

    def test_open_model_dispatches_owned_view_without_export_solve_or_hidden_ack(self):
        from msplatform.applications.model_execution import execute_open_model
        from msplatform.execution.artifact_reader import OpenedArtifact
        from msplatform.execution.manifest_records import file_record

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe, template, assembly_template, manifest = (root / "sldworks.exe", root / "part.prtdot",
                root / "assembly.asmdot", root / "manifest.json")
            exe.write_bytes(b"INERT_NOT_SOLIDWORKS")
            template.write_bytes(b"INERT_NOT_TEMPLATE")
            assembly_template.write_bytes(b"INERT_NOT_TEMPLATE")
            manifest.write_text("{}", encoding="utf-8")
            source = OpenedArtifact(kind="cad_geometry", product_id="cad_geometry",
                reference=dict(manifest=file_record(manifest, "required_evidence"), product_id="cad_geometry"),
                metadata={}, records={}, paths={}, producer=dict(status="success"))
            limits = dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0)
            runtime = dict(com_class="SldWorks.Application.30", part_template=str(template),
                           assembly_template=str(assembly_template), lifecycle="document_close")
            stage = dict(limits=limits, runtime=runtime,
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="Viewer transport fixture"))
            policy = root / "policy.json"
            policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy", stages=dict(open_model=stage))), encoding="utf-8")
            context = execution_api.load_environment(workspace=root / "uncreated",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable), solidworks=exe),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=policy))
            sentinel = {"software_fixture": True}
            with patch("msplatform.execution.owner.run_managed_stage", return_value=sentinel) as owner, \
                 patch("subprocess.Popen", side_effect=AssertionError("transport test launched a tool")):
                self.assertIs(api.open_model(source, application="solidworks", context=context), sentinel)
                call = owner.call_args.kwargs
                self.assertEqual(call["expected_operation_ids"], ("materialize_view", "view_model"))
                self.assertEqual(call["operation_dependencies"], {"view_model": ["materialize_view"]})
                self.assertIs(call["action"].func, execute_open_model)
                self.assertIs(call["action"].keywords["model_reference"], source)
                self.assertEqual(call["action"].keywords["application_settings"], runtime)
                self.assertEqual(call["source_references"], [{"manifest_record": source.reference["manifest"]}])
                self.assertEqual(call["payload"]["stage_policy"], stage)
                owner.reset_mock()
                checks = dict(schema_version=1, kind="selected_solid_geometry_v1", selected_step_members=["member_00008"])
                with patch("msplatform.applications.model_execution._inspection_input") as read_report:
                    self.assertIs(api.open_model(source, application="solidworks", context=context, checks=checks), sentinel)
                    read_report.assert_called_once_with(source, checks)
                    self.assertEqual(owner.call_args.kwargs["action"].keywords["checks"], checks)
                    self.assertEqual(owner.call_args.kwargs["payload"]["checks"], checks)
                owner.reset_mock()
                with self.assertRaisesRegex(ValueError, "does not support"):
                    api.open_model(source, application="simion", context=context, checks=checks)
                owner.assert_not_called()
                with self.assertRaisesRegex(ValueError, "prepared_model|PreparedModel|unsolved"):
                    api.open_model(source, application="simion", context=context)
                owner.assert_not_called()
            self.assertFalse(context.workspace.exists())

    def test_simion_view_dispatches_same_model_preparation_and_explicit_gui_graph(self):
        from types import SimpleNamespace
        from msplatform.applications.simion_model_execution import execute_simion_open_model
        from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive
        from msplatform.backends.simion.model_view_preparation import prepare_view
        from msplatform.execution.artifact_reader import OpenedArtifact
        from msplatform.execution.manifest_records import file_record, verify_record

        case, _, _, compiled = compile_example()
        components = {name: compiled.components_resolved[name]
                      for name in compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]}
        drive = project_resolved_drive(compiled, components, pulse=case.drive["pulse"],
            clock=dict(clock_epoch_id="view-transport-fixture", authority_sha256="A" * 64,
                       phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(compiled, components, drive=drive, physics=case.physics)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe, manifest = root / "simion.exe", root / "manifest.json"
            exe.write_bytes(b"INERT_NOT_SIMION")
            manifest.write_text("{}", encoding="utf-8")
            artifact = OpenedArtifact(kind="prepared_model", product_id="model",
                reference=dict(manifest=file_record(manifest, "required_evidence"), product_id="model"),
                metadata={}, records={}, paths={}, producer=dict(status="success"))
            source = SimpleNamespace(model=model, artifact=artifact)
            stage = dict(limits=dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0),
                runtime=dict(simion_allow_asynchronous_io=False),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="View transport fixture"))
            policy = root / "policy.json"

            def write_policy():
                policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
                    stages=dict(open_model=stage))), encoding="utf-8")

            write_policy()
            context = execution_api.load_environment(workspace=root / "uncreated",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable), simion=exe),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=policy))
            sentinel = {"software_transport_fixture": True}
            # Real provider/model/seed and stage policy; source admission and
            # owner transport are separately tested, not claimed native here.
            with patch("msplatform.backends.simion.field_closure.load_field_model", return_value=source), \
                 patch("msplatform.execution.owner.run_managed_stage", return_value=sentinel) as owner, \
                 patch("subprocess.Popen", side_effect=AssertionError("API transport must not launch a tool")):
                for value, application in ((artifact, None), (artifact.reference, "simion")):
                    with self.subTest(application=application):
                        self.assertIs(api.open_model(value, application=application, context=context), sentinel)
                        call = owner.call_args.kwargs
                        ids = ("materialize_geometry", "build_model", "verify_model", "view_model")
                        self.assertEqual(call["expected_operation_ids"], ids)
                        self.assertEqual(call["operation_dependencies"],
                            {name: [ids[index-1]] for index, name in enumerate(ids) if index})
                        self.assertIs(call["action"].func, execute_simion_open_model)
                        self.assertIs(call["action"].keywords["model_reference"], artifact)
                        preparer = call["action"].keywords["prepare_view"]
                        self.assertIs(preparer.func, prepare_view)
                        self.assertIs(preparer.keywords["allow_asynchronous_io"], False)
                        verify_record("preparer", call["action"].keywords["preparer_record"])
                        verify_record("materializer", preparer.keywords["materializer_record"])
                        self.assertEqual(call["source_references"], [{"manifest_record": artifact.reference["manifest"]}])
                        self.assertTrue(call["use_short_execution_path"])
                        self.assertNotIn("Fly", ids)
                for runtime in ({"unexpected": True}, {"simion_allow_asynchronous_io": 1}):
                    with self.subTest(invalid_runtime=runtime):
                        stage["runtime"] = runtime
                        write_policy()
                        owner.reset_mock()
                        with self.assertRaisesRegex(ContractError, "view runtime"):
                            api.open_model(artifact, application="simion", context=context)
                        owner.assert_not_called()
            self.assertFalse(context.workspace.exists())

    def test_tracking_dispatch_preserves_real_source_clock_graph_and_zero_handoff(self):
        from dataclasses import replace
        import hashlib
        from msplatform.assembly.handoff import HandoffClock, HandoffMother, HandoffResult
        from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive
        from msplatform.backends.simion.tracking_execution import execute_tracking
        from msplatform.contracts.clock import ClockIdentity
        from msplatform.execution.artifact_reader import OpenedArtifact
        from msplatform.execution.manifest_records import file_record

        case, _, _, compiled = compile_example()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            epoch = root / "epoch.bin"
            epoch.write_bytes(b"\0" * 32)
            request = case.release
            request["clock"] = dict(clock_epoch_id="software-tracking-fixture",
                                    authority_sha256=hashlib.sha256(epoch.read_bytes()).hexdigest())
            release = api.sample_release(request)
            packet = release.to_dict()
            components = {key: compiled.components_resolved[key]
                          for key in compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]}
            drive = project_resolved_drive(compiled, components, pulse=case.drive["pulse"],
                clock=dict(packet["clock"], phase_reference_instrument_time_us=0.))
            model = compile_prepared_model(compiled, components, drive=drive, physics=case.physics)
            paths = dict(compiled_model=root / "model.json", clock_authority=root / "clock.json", instrument_epoch=epoch)
            paths["compiled_model"].write_text(json.dumps(model.document), encoding="utf-8")
            paths["clock_authority"].write_text('{"software_fixture":true}', encoding="utf-8")
            manifest = root / "fixture-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="fields")
            fields = OpenedArtifact(kind="field_bundle", product_id="fields", reference=reference,
                metadata=dict(backend="simion", field_status="available", source_status="not_requested",
                              model_identity_sha256=model.document["model_identity_sha256"], clock=drive["clock"]),
                records={name: file_record(path, "required_evidence") for name, path in paths.items()},
                paths=paths, producer=dict(status="success"))
            limits = dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0)
            stage = dict(limits=limits, runtime=dict(simion_allow_asynchronous_io=False),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="Software dispatch fixture"))
            policy = root / "policy.json"
            policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy", stages=dict(track=stage))), encoding="utf-8")
            context = execution_api.load_environment(workspace=root / "uncreated",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable), simion=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=policy))
            propagation = dict(schema_version=1, scope="continuous_assembly", end_policy=dict(maximum_particle_age_us=200.),
                               consumed_plane_events=[], stop=None)
            observations = dict(plane_observations=[])
            numerics = dict(maximum_step_us=.001, trajectory_quality=17, rf_steps_per_period=80)
            before = copy.deepcopy((packet, propagation, observations, numerics))
            sentinel = object()
            # Real provider/model/source/clock planning; only owner/publication
            # transport is substituted. This is not a native or full-owner test.
            with patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {"fixture": True}}) as owner, \
                 patch("msplatform.execution.artifact_reader.open_artifact", return_value=sentinel), \
                 patch("subprocess.Popen", side_effect=AssertionError("planning launched a process")):
                result = api.track(fields, release, propagation=propagation, observations=observations, numerics=numerics, context=context)
                self.assertIs(result, sentinel)
                call = owner.call_args.kwargs
                self.assertEqual(call["expected_operation_ids"], ("build_tracking_iob", "verify_tracking_iob", "track_fly"))
                self.assertEqual(call["operation_dependencies"], dict(verify_tracking_iob=["build_tracking_iob"], track_fly=["verify_tracking_iob"]))
                self.assertIs(call["action"].func, execute_tracking)
                self.assertIs(call["action"].keywords["fields_reference"], fields)
                self.assertEqual(call["payload"]["particles"], packet)
                self.assertEqual(call["source_references"], [{"manifest_record": reference["manifest"]}])
                self.assertEqual(call["committed_new_bytes"], limits["transient_run_directory_bytes"])
                common = dict(propagation=propagation, observations=observations, numerics=numerics, context=context)
                self.assertIs(api.track(fields, release, unit_size=27, **common), sentinel)
                split = owner.call_args.kwargs
                self.assertEqual(len(split["expected_operation_ids"]), 12)
                self.assertTrue(split["expected_operation_ids"][-1].endswith("unit_0004"))
                self.assertEqual(split["action"].keywords["unit_size"], 27)
                self.assertEqual(split["payload"]["particles"], packet)
                # Actual manifest/completion verification is exercised by the
                # backend original-owner fixture; this checks API graph wiring.
                recovery_manifest = root / "run_manifest.json"
                recovery_manifest.write_text("{}", encoding="utf-8")
                recovery = file_record(recovery_manifest, "required_evidence")
                with patch("msplatform.backends.simion.tracking_units.inspect_tracking_recovery",
                           return_value=dict(reused_unit_keys=["unit_0001", "unit_0003"])) as inspect_recovery:
                    self.assertIs(api.track(fields, release, unit_size=27, recovery_reference=recovery, **common), sentinel)
                    resumed = owner.call_args.kwargs
                    self.assertEqual(len(resumed["expected_operation_ids"]), 6)
                    self.assertTrue(all(name.endswith(("unit_0002", "unit_0004")) for name in resumed["expected_operation_ids"]))
                    self.assertEqual(resumed["source_references"][-1], {"manifest_record": recovery})
                    self.assertEqual(resumed["action"].keywords["recovery_reference"], recovery)
                    inspected_plan, inspected_record = inspect_recovery.call_args.args
                    self.assertEqual(inspected_record, recovery)
                    self.assertEqual([len(unit["expected_particle_ids"]) for unit in inspected_plan["units"]], [27, 27, 27, 19])
                    self.assertEqual(len(inspected_plan["source_provenance"]["mother_records"]), 100)
                    self.assertEqual(inspected_plan["field_manifest_identity"],
                                     {key: reference["manifest"][key] for key in ("bytes", "sha256")})
                    inspect_recovery.return_value = dict(reused_unit_keys=[f"unit_{i:04d}" for i in range(1, 5)])
                    all_reused = dict(common, context=replace(context, tools={}))
                    self.assertIs(api.track(fields, release, unit_size=27, recovery_reference=recovery, **all_reused), sentinel)
                    self.assertEqual(owner.call_args.kwargs["expected_operation_ids"], ())
                    inspect_recovery.side_effect = ValueError("recovery input changed")
                    owner.reset_mock()
                    with self.assertRaisesRegex(ValueError, "recovery input changed"):
                        api.track(fields, release, unit_size=27, recovery_reference=recovery, **common)
                    owner.assert_not_called()
                for invalid_size in (True, 0, -1, 1.5):
                    with self.subTest(invalid_unit_size=invalid_size), self.assertRaisesRegex(ValueError, "unit_size"):
                        api.track(fields, release, unit_size=invalid_size, **common)
                for invalid_profiles in ("profile.json", {}, [None]):
                    with self.subTest(invalid_profiles=invalid_profiles), self.assertRaisesRegex(ContractError, "dispatch_profiles"):
                        api.track(fields, release, dispatch_profiles=invalid_profiles, **common)
                with self.assertRaisesRegex(ContractError, "absolute predecessor manifest"):
                    api.track(fields, release, recovery_reference={"path": "relative.json"}, **common)
                owner.reset_mock()
                invalid = dict(numerics, refine_convergence_v=1e-5)
                with self.assertRaisesRegex(ValueError, "must not contain"):
                    api.track(fields, release, propagation=propagation, observations=observations, numerics=invalid, context=context)
                unsolved = OpenedArtifact(kind="prepared_model", product_id="model", reference=reference,
                    metadata=fields.metadata, records=fields.data_records, paths=paths, producer=fields.producer)
                with self.assertRaisesRegex(ContractError, "FieldBundle"):
                    api.track(unsolved, release, propagation=propagation, observations=observations, numerics=numerics, context=context)
                owner.assert_not_called()
                records = {row["particle_id"]: row for row in packet["mother"]["records"].values()}
                mother = HandoffMother(records, packet["mother"]["fates"])
                clock = ClockIdentity(**packet["clock"])
                empty = HandoffResult((), (), tuple(records), mother, HandoffClock(clock, clock), "time_snapshot")
                relaunch = dict(propagation, scope="state_relaunch")
                with self.assertRaisesRegex(ContractError, "published trajectory"):
                    api.track(fields, empty, propagation=relaunch, observations=observations, numerics=numerics, context=context)
                prior = OpenedArtifact(kind="trajectory_result", product_id="trajectory", reference=dict(reference, product_id="trajectory"),
                    metadata={}, records={}, paths={}, producer=dict(status="success"))
                no_tool = replace(context, tools={})
                self.assertIs(api.track(fields, empty, propagation=relaunch, observations=observations, numerics=numerics,
                                        context=no_tool, source_reference=prior), sentinel)
                call = owner.call_args.kwargs
                self.assertEqual(call["expected_operation_ids"], ())
                self.assertEqual(len(call["payload"]["particles"]["mother"]["records"]), 100)
                self.assertEqual(len(call["source_references"]), 2)
            self.assertFalse(context.workspace.exists())
            self.assertEqual((release.to_dict(), propagation, observations, numerics), before)

    def test_example_field_numerics_expand_one_geometry_grid_without_mutation(self):
        from msplatform.backends.simion.field_execution import plan_fields_execution
        from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive

        case, _, _, compiled = compile_example()
        before = case.to_dict()
        numerics = case.field_numerics
        self.assertNotIn("frontend_domains", before["numerics"]["fields"])
        self.assertEqual(numerics["rf_reference_voltage_v"], 139.81792)
        self.assertEqual(numerics["downstream_convergence_v"], dict(flight_tube=1e-5, reflectron=1e-5, detector=1e-5))
        for name, domain in numerics["frontend_domains"].items():
            grid = {key: value for key, value in domain.items() if key != "refine_convergence_v"}
            self.assertEqual(grid, case.geometry_numerics["frontend_domains"][name])
        selected = compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]
        components = {name: compiled.components_resolved[name] for name in selected}
        drive = project_resolved_drive(compiled, components, pulse=case.drive["pulse"],
            clock=dict(clock_epoch_id="explicit-software-fixture", authority_sha256="A" * 64,
                       phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(compiled, components, drive=drive, physics=case.physics)
        with patch("subprocess.Popen", side_effect=AssertionError("example planning must not execute tools")):
            plan = plan_fields_execution(model, numerics=numerics)
        self.assertEqual(len(plan["expected_operation_ids"]), 8)
        numerics["frontend_domains"]["parent"]["cell_mm_xyz"]["x"] *= 2
        self.assertEqual(case.to_dict(), before)
        self.assertEqual(case.field_numerics["frontend_domains"]["parent"]["cell_mm_xyz"]["x"],
                         case.geometry_numerics["frontend_domains"]["parent"]["cell_mm_xyz"]["x"])
        invalid = copy.deepcopy(before)
        invalid["numerics"]["fields"]["frontend_refine_convergence_v"]["undeclared"] = {}
        with self.assertRaisesRegex(ContractError, "exact geometry domains"):
            example_api.StudyDefinition(invalid).field_numerics

    def test_versioned_release_keeps_real_physics_and_authors_new_sparse_birth_ids(self):
        import csv
        import hashlib

        case = example_api.load_example("rf_oatof_functional_v1")
        request = case.release
        before = copy.deepcopy(request)
        with patch("subprocess.Popen", side_effect=AssertionError("source sampling must not launch tools")):
            release = api.sample_release(request)
        self.assertEqual(request, before)
        self.assertEqual(len(release.rows), 100)
        self.assertEqual([row["particle_id"] for row in release.rows], request["particle_ids"])
        self.assertEqual(len(release.mother["records"]), 100)
        self.assertGreater(min(row["particle_birth_time_us"] for row in release.rows), 0.)
        self.assertLess(max(row["particle_birth_time_us"] for row in release.rows), 1e6 / 1100000.)
        self.assertTrue(all(row["particle_age_us"] == 0. for row in release.rows))
        # Independent frozen physical rows: new opaque author IDs must not
        # change the historical sampler's draw order, states or birth times.
        path = Path(__file__).resolve().parents[2] / "projects/rf_multipole_ion_optics/config/sources/rf_multipole_family_mother_sample_v1_100.csv"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            "0125c3ab02b2321ef26a3a913cf6ec04325fd0d48597d2cb439d0ce42411662f")
        with path.open(encoding="utf-8", newline="") as stream:
            expected = list(csv.DictReader(stream))
        actual = release.to_dict()["realization"]["generator_rows"]
        for old, new in zip(expected, actual, strict=True):
            self.assertEqual({key: float(value) for key, value in old.items()}, new)
        request["particle_ids"][0] = 99
        self.assertEqual(case.release, before)
        self.assertEqual(release.rows[0]["particle_id"], before["particle_ids"][0])

    def test_prepare_model_binds_geometry_clock_and_original_owner_without_solving(self):
        from dataclasses import asdict
        from types import SimpleNamespace
        from msplatform.backends.simion.model_execution import execute_model
        from msplatform.backends.simion.model import require_prepared_model
        case, _, _, compiled = compile_example()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiled_path = root / "compiled.json"
            compiled_path.write_text(json.dumps(asdict(compiled)), encoding="utf-8")
            stage = dict(limits=dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="Unsolved software fixture"))
            policy = root / "stages.json"
            policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
                stages={"prepare_model": stage})), encoding="utf-8")
            context = execution_api.load_environment(workspace=root / "study",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable), simion=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=policy))
            reference = {"manifest": {"fixture": True}, "product_id": "geometry"}
            source = SimpleNamespace(reference=reference, data_path=lambda name: compiled_path)
            sentinel = object()
            with patch("msplatform.execution.artifact_reader.open_artifact", side_effect=[source, sentinel]) as reader, \
                 patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {"new": True}}) as owner, \
                 patch("subprocess.Popen", side_effect=AssertionError("hidden native work")):
                self.assertIs(api.prepare_model(reference, drive=case.drive, physics=case.physics, context=context), sentinel)
            call = owner.call_args.kwargs
            self.assertEqual(call["expected_operation_ids"], ("materialize_geometry", "build_model", "verify_model"))
            self.assertEqual(call["action"].func, execute_model)
            self.assertEqual(call["source_references"], [{"manifest_record": reference["manifest"]}])
            model = require_prepared_model(call["action"].keywords["model"])
            self.assertEqual(model["drive"]["clock"]["authority_sha256"],
                "6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0")
            self.assertEqual(model["drive"]["pulse"], case.drive["pulse"])
            self.assertNotIn("clock_authority", model["drive"])
            self.assertFalse(context.workspace.exists())
            self.assertEqual(reader.call_args.kwargs["expected_kind"], "prepared_model")
            invalid = case.drive
            invalid["clock_authority"] = {"example_resource": "missing.json"}
            with patch("msplatform.execution.artifact_reader.open_artifact", return_value=source), \
                 patch("msplatform.execution.owner.run_managed_stage") as refused, \
                 self.assertRaisesRegex(ContractError, "unknown versioned"):
                api.prepare_model(reference, drive=invalid, physics=case.physics, context=context)
            refused.assert_not_called()

    def test_cad_export_dispatch_is_independent_of_fields_and_optional_engine_import(self):
        from msplatform.exporters.execution import execute_cad_export
        case, _, assembly, _ = compile_example()
        options = case.cad_export
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "cad-stages.json"
            stage = dict(limits=dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="CAD software fixture"))
            policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy", stages={"export_cad": stage})), encoding="utf-8")
            context = execution_api.load_environment(workspace=root / "new study",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=policy))
            sentinel = object()
            with patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {"fixture": True}}) as owner, \
                 patch("msplatform.execution.artifact_reader.open_artifact", return_value=sentinel) as reader, \
                 patch("subprocess.Popen", side_effect=AssertionError("hidden solver or GUI")):
                self.assertIs(api.export_cad(assembly, format="step", options=options, context=context), sentinel)
            call = owner.call_args.kwargs
            self.assertEqual(call["expected_operation_ids"], ("export_step",))
            self.assertEqual(call["action"].func, execute_cad_export)
            self.assertEqual(call["action"].keywords["snapshot"]["components_resolved"], assembly.components_resolved)
            reader.assert_called_once_with({"manifest": {"fixture": True}, "product_id": "cad_geometry"}, expected_kind="cad_geometry")
            self.assertFalse(context.workspace.exists())
            with patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {"fixture": True}}) as named_owner, \
                 patch("msplatform.execution.artifact_reader.open_artifact", return_value=sentinel):
                api.export_cad(assembly, format="step", options=dict(options,name="RF O'Brien"),context=context)
            named = named_owner.call_args.kwargs
            self.assertEqual(named['expected_relative_paths'][0], "results/RF O'Brien.step")
            self.assertEqual(named['action'].keywords['options'], {k:v for k,v in dict(options,name="RF O'Brien").items() if k!='representation'})
            for name in ('../escape', 'CON', 'bad*', '质谱'):
                with self.subTest(name=name), patch("msplatform.execution.owner.run_managed_stage") as launch:
                    with self.assertRaises(ContractError):
                        api.export_cad(assembly,format="step",options=dict(options,name=name),context=context)
                    launch.assert_not_called()
            stage["artifact_retention"] = dict(policy_version=1, **{"class": "compact"}, reason=None)
            policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy", stages={"export_cad": stage})), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot retain"), patch("msplatform.execution.owner.run_managed_stage") as launch:
                api.export_cad(assembly, format="step", options=options, context=context)
            launch.assert_not_called()

    def test_field_action_binds_real_model_graph_budget_and_explicit_reuse(self):
        from types import SimpleNamespace
        from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive
        from msplatform.backends.simion.field_execution import execute_fields
        from msplatform.execution.manifest_records import file_record, verify_record

        case, _, _, compiled = compile_example()
        selected = compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"]
        components = {name: compiled.components_resolved[name] for name in selected}
        drive = project_resolved_drive(compiled, components, pulse=case.drive["pulse"],
            clock=dict(clock_epoch_id="explicit-software-fixture", authority_sha256="A" * 64,
                       phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(compiled, components, drive=drive, physics=case.physics)
        domains = copy.deepcopy(case.geometry_numerics["frontend_domains"])
        for domain in domains.values():
            domain["refine_convergence_v"] = dict(carrier_off=1e-5, rf_reference=1e-5, pulse_delta=1e-5)
        numerics = dict(frontend_domains=domains, rf_reference_voltage_v=139.81792,
            downstream_convergence_v=dict(flight_tube=1e-5, reflectron=1e-5, detector=1e-5))
        original = copy.deepcopy(numerics)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "fixture-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="model")
            source = SimpleNamespace(model=model, artifact=SimpleNamespace(reference=reference))
            limits = dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0, reserved_run_payload_bytes=1048576)
            stage = dict(limits=limits, runtime=dict(simion_allow_asynchronous_io=False),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="Software dispatch fixture"))
            policy = root / "policy.json"
            policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
                stages=dict(solve_fields=stage))), encoding="utf-8")
            context = execution_api.load_environment(workspace=root / "uncreated",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable), simion=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=policy))
            sentinel = object()
            # Only publication/transport are substituted. Planning uses the real
            # public example/model; this is not a field or native acceptance.
            with patch("msplatform.backends.simion.field_closure.load_field_model", return_value=source), \
                 patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {"fixture": True}}) as owner, \
                 patch("msplatform.execution.artifact_reader.open_artifact", return_value=sentinel) as reader:
                self.assertIs(api.solve_fields(reference, numerics=numerics, context=context), sentinel)
                call = owner.call_args.kwargs
                self.assertEqual(call["expected_operation_ids"], ("materialize_geometry", "frontend_parent_carrier_off",
                    "frontend_parent_rf_reference", "frontend_parent_pulse_delta", "downstream_fields",
                    "materialize_field_responses", "build_fields", "verify_fields"))
                self.assertEqual(call["operation_dependencies"]["verify_fields"], ["build_fields"])
                self.assertEqual(call["action"].func, execute_fields)
                self.assertEqual(call["action"].keywords["limits"], limits)
                self.assertEqual(call["committed_new_bytes"], limits["transient_run_directory_bytes"])
                self.assertEqual(call["source_references"], [{"manifest_record": reference["manifest"]}])
                self.assertEqual(call["payload"]["numerics"], numerics)
                self.assertIsNone(call["payload"]["reuse_fields"])
                self.assertIs(call["action"].keywords["allow_asynchronous_io"], False)
                verify_record("policy", call["commitment_inputs"][0])
                verify_record("payload materializer", call["action"].keywords["materializer_record"])
                reader.assert_called_once_with({"manifest": {"fixture": True}, "product_id": "fields"},
                                               expected_kind="field_bundle")
                reuse = dict(manifest=reference["manifest"], product_id="prior-fields")
                reader.side_effect = [SimpleNamespace(reference=reuse), sentinel]
                self.assertIs(api.solve_fields(reference, numerics=numerics, context=context, reuse_fields=reuse), sentinel)
                call = owner.call_args.kwargs
                self.assertEqual(call["action"].keywords["reuse_fields_reference"], reuse)
                self.assertEqual(call["source_references"], [{"manifest_record": reference["manifest"]},
                    {"manifest_record": reuse["manifest"]}])
            self.assertFalse(context.workspace.exists())
        self.assertEqual(numerics, original)

    def test_field_policy_requires_explicit_reserve_before_any_execution(self):
        from msplatform.execution.stage_policy import read_stage_policy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "stages.json"
            limits = dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0)
            stage = dict(limits=limits, artifact_retention=dict(policy_version=1,
                **{"class": "solver_review"}, reason="Explicit software fixture only"))
            context = execution_api.load_environment(workspace=root / "uncreated",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3", stage_policy_path=path))

            def write(action, value):
                selected = copy.deepcopy(stage)
                selected["limits"] = value
                path.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
                    stages={action: selected})), encoding="utf-8")

            with patch("subprocess.Popen", side_effect=AssertionError("policy validation must not execute tools")):
                for reserve in (0, 1048576, limits["transient_run_directory_bytes"]):
                    with self.subTest(valid_reserve=reserve):
                        expected = dict(limits, reserved_run_payload_bytes=reserve)
                        write("solve_fields", expected)
                        actual, _ = read_stage_policy(context, "solve_fields")
                        self.assertEqual(actual["limits"], expected)
                for reserve in (None, True, -1, 1.5, limits["transient_run_directory_bytes"] + 1):
                    with self.subTest(invalid_reserve=reserve):
                        invalid = dict(limits)
                        if reserve is not None:
                            invalid["reserved_run_payload_bytes"] = reserve
                        write("solve_fields", invalid)
                        with self.assertRaises(ValueError):
                            read_stage_policy(context, "solve_fields")
                write("build_geometry", dict(limits, reserved_run_payload_bytes=0))
                with self.assertRaises(ValueError):
                    read_stage_policy(context, "build_geometry")
            self.assertFalse(context.workspace.exists())

    def test_geometry_action_dispatches_the_bound_plan_budget_and_owner_only(self):
        from msplatform.execution.manifest_records import verify_record
        from msplatform.execution.stage_policy import read_stage_policy
        from msplatform.backends.simion.geometry_execution import execute_geometry
        _, _, _, compiled = compile_example()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            limits = dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0)
            selected = dict(limits=limits, artifact_retention=dict(policy_version=1,
                **{"class": "solver_review"}, reason="Explicit software fixture only"))
            policy = dict(schema_version=1, role="execution_stage_policy", stages={"build_geometry": selected})
            path = root / "stages.json"
            path.write_text(json.dumps(policy), encoding="utf-8")
            context = execution_api.load_environment(workspace=root / "new study",
                tools=dict(python=Path(sys.executable), powershell=Path(sys.executable), simion=Path(sys.executable)),
                policy=dict(host_state_path=root / "state.sqlite3", execution_root=root / "aliases", stage_policy_path=path))
            sentinel = object()
            with patch("msplatform.execution.owner.run_managed_stage", return_value={"manifest": {"fixture": True}}) as owner, \
                 patch("msplatform.execution.artifact_reader.open_artifact", return_value=sentinel) as reader:
                self.assertIs(api.build_geometry(compiled, context=context), sentinel)
            arguments = owner.call_args.kwargs
            self.assertEqual(arguments["committed_new_bytes"], limits["transient_run_directory_bytes"])
            self.assertEqual(arguments["payload"]["stage_policy"], selected)
            self.assertEqual(arguments["action"].func, execute_geometry)
            self.assertEqual(arguments["action"].keywords["limits"], limits)
            self.assertTrue(arguments["use_short_execution_path"])
            self.assertEqual(arguments["expected_operation_ids"][-2:], ("build_geometry", "verify_geometry"))
            verify_record("stage authority", arguments["commitment_inputs"][0])
            self.assertEqual(Path(arguments["commitment_inputs"][0]["path"]), path)
            reader.assert_called_once_with({"manifest": {"fixture": True}, "product_id": "geometry"}, expected_kind="geometry_artifact")
            self.assertFalse(context.workspace.exists())
            for field, invalid in (("wall_clock_seconds", True), ("automatic_retry_count", 1),
                                   ("transient_run_directory_bytes", 0)):
                with self.subTest(field=field):
                    bad = copy.deepcopy(policy)
                    bad["stages"]["build_geometry"]["limits"][field] = invalid
                    path.write_text(json.dumps(bad), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "positive existing process limits"):
                        read_stage_policy(context, "build_geometry")

    def test_public_birth_authoring_keeps_sparse_source_and_full_mother_without_side_effects(self):
        from common.ion_release.test_mt19937_disk_cone_rf_phase import _spec
        request = dict(schema_version=1, role="canonical_birth_source_request", release_spec=_spec(3),
            clock=dict(clock_epoch_id="software_oracle",authority_sha256="a"*64),instrument_origin_us=12.5,
            species_id="test_ion",source_component_id="multipole",particle_ids=[11,101,1009],
            relative_weights={"11":.5,"101":2.,"1009":3.})
        before = copy.deepcopy(request)
        with patch("subprocess.Popen",side_effect=AssertionError("native source action")), \
             patch.object(Path,"mkdir",side_effect=AssertionError("source workspace")), \
             patch.object(Path,"write_text",side_effect=AssertionError("source file")):
            source = api.sample_release(request)
        self.assertEqual(request,before)
        self.assertEqual([row["particle_id"] for row in source.rows],[11,101,1009])
        self.assertEqual([row["particle_weight"] for row in source.rows],[.5,2.,3.])
        self.assertEqual(list(source.mother["records"]),[11,101,1009])
        self.assertEqual(source.clock.clock_epoch_id,"software_oracle")
        self.assertEqual(source.to_dict()["realization"]["spec"]["mother_particle_count"],5000)
        source.rows[0].clear()
        source.mother["records"].clear()
        source.to_dict().clear()
        request.clear()
        self.assertEqual(len(source.rows),3)
        self.assertEqual(len(source.mother["records"]),3)
        invalid = copy.deepcopy(before)
        invalid["relative_weights"][11] = 1.
        with self.assertRaisesRegex(ContractError,"weight keys"):
            api.sample_release(invalid)
        invalid = copy.deepcopy(before)
        invalid["schema_version"] = True
        with self.assertRaisesRegex(ContractError,"version-1"):
            api.sample_release(invalid)

    def test_real_example_full_geometry_without_source_or_side_effects(self):
        with patch("subprocess.Popen", side_effect=AssertionError("native launch")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("workspace creation")), \
             patch.object(Path, "write_text", side_effect=AssertionError("file write")):
            case, components, assembly, compiled = compile_example()
        self.assertNotIn("source", case.to_dict())
        altered = case.to_dict()
        altered["release"] = {"deliberately_invalid_for_sampling": True}
        independent = example_api.StudyDefinition(altered)
        parts = {name: component_api.resolve_component(request) for name, request in independent.component_requests.items()}
        self.assertEqual(simion_api.compile_geometry(assembly_api.assemble(independent.recipe, parts),
                         numerics=independent.geometry_numerics), compiled)
        self.assertEqual(set(components), {"multipole", "oatof"})
        self.assertEqual(len(components["oatof"].assembly_interface["component_electrodes"]), 42)
        self.assertEqual(assembly.composition_plan["schema_version"], 5)
        self.assertTrue(all(compiled.frontend_gems.values()))
        self.assertEqual(len(compiled.downstream_specs), 3)
        self.assertEqual(set(compiled.provider_content_identities), set(components))
        self.assertEqual(compiled.components_resolved, assembly.components_resolved)

    def test_expanded_inputs_are_independent_and_geometry_parameters_are_effective(self):
        case, components, assembly, original = compile_example()
        before = copy.deepcopy((case.to_dict(), components, assembly))
        requests = case.component_requests
        requests["multipole"]["design"]["geometry_mm"]["rod_radius_ratio"] = .55
        changed = {name: component_api.resolve_component(request) for name, request in requests.items()}
        result = simion_api.compile_geometry(assembly_api.assemble(case.recipe, changed),
                                             numerics=case.geometry_numerics)
        self.assertEqual(changed["multipole"].assembly_interface, components["multipole"].assembly_interface)
        self.assertEqual(assembly_api.assemble(case.recipe, changed).composition_plan, assembly.composition_plan)
        self.assertNotEqual(result.frontend_gems, original.frontend_gems)
        self.assertNotEqual(result.provider_content_identities["multipole"],
                            original.provider_content_identities["multipole"])
        self.assertEqual((case.to_dict(), components, assembly), before)

    def test_public_views_and_constructor_inputs_cannot_mutate_existing_objects(self):
        case, components, assembly, compiled = compile_example()
        before = copy.deepcopy((case, components, assembly))
        case.document["component_requests"].clear()
        components["multipole"].resolved_design["geometry_mm"].clear()
        components["multipole"].assembly_interface["ports"].clear()
        assembly.composition_plan["components"].clear()
        assembly.components_resolved["oatof"].clear()
        assembly.components.clear()
        self.assertEqual((case, components, assembly), before)
        rebuilt = simion_api.compile_geometry(assembly, numerics=case.geometry_numerics)
        self.assertEqual(rebuilt, compiled)
        design = components["multipole"].resolved_design
        interface = components["multipole"].assembly_interface
        snapshot = component_api.ResolvedComponent("rf_multipole", design, interface,
                                         source_design=components["multipole"].source_design)
        design.clear()
        interface.clear()
        self.assertEqual(snapshot, components["multipole"])

    def test_mismatched_design_interface_and_parent_layout_are_rejected(self):
        from msplatform.components.catalog import _from_provider

        case, components, assembly, _ = compile_example()
        for name, component in components.items():
            interface = component.assembly_interface
            port = next(iter(interface["ports"].values()))
            port["center_mm"][0] += .1
            with self.subTest(instance=name), self.assertRaisesRegex(ContractError, "interface differs"):
                _from_provider(component.provider_id, component.resolved_design, interface,
                               source_design=component.source_design)
            direct = component_api.ResolvedComponent(component.provider_id, component.resolved_design, interface,
                                                      source_design=component.source_design)
            with self.subTest(instance=name, boundary="public_assembly"), \
                    self.assertRaisesRegex(ContractError, "interface differs"):
                assembly_api.assemble(case.recipe, {**components, name: direct})
        stale = components["multipole"].resolved_design
        stale["geometry_mm"]["rod_array"]["rods"][0]["radius_mm"] += .01
        with self.assertRaisesRegex(ContractError, "hash is stale"):
            _from_provider("rf_multipole", stale, components["multipole"].assembly_interface,
                           source_design=components["multipole"].source_design)
        for version in (99, True):
            invalid = components["oatof"].resolved_design
            invalid["schema_version"] = version
            with self.subTest(version=version), self.assertRaisesRegex(ContractError, "TOF resolved design version"):
                _from_provider("single_reflection_oa_tof", invalid, components["oatof"].assembly_interface,
                               source_design=components["oatof"].source_design)
        with self.assertRaisesRegex(ContractError, "requires its explicit source design"):
            _from_provider("single_reflection_oa_tof", components["oatof"].resolved_design,
                           components["oatof"].assembly_interface, source_design=None)
        stale_tof = components["oatof"].resolved_design
        stale_tof["validation_target"]["mass_amu"] += 1
        with self.assertRaisesRegex(ContractError, "differs from its source design documents"):
            _from_provider("single_reflection_oa_tof", stale_tof,
                           components["oatof"].assembly_interface,
                           source_design=components["oatof"].source_design)
        plan = assembly.composition_plan
        plan["scope"]["instance_ids"].reverse()
        with self.assertRaisesRegex(ContractError, "layout differs"):
            assembly_api.Assembly(plan, components)

    def test_unknown_provider_example_and_nonassembly_input_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "unknown example"):
            example_api.load_example("latest")
        with self.assertRaisesRegex(ContractError, "unsupported component provider"):
            component_api.resolve_component({"provider_id": "unknown", "design": {}})
        with self.assertRaisesRegex(ContractError, "explicitly assembled design"):
            simion_api.compile_geometry(None, numerics={})

    def test_mating_independent_rotated_nonzero_gap_oracle(self):
        upstream = dict(frame_id="world", center_mm=[0., 0., 10.], outward_normal=[0., 0., 1.],
                        cross_section=dict(shape="circle", radius_mm=2.))
        downstream = dict(frame_id="local", center_mm=[1., 2., 3.], outward_normal=[0., 0., -1.],
                          cross_section=dict(shape="circle", radius_mm=2.))
        before = copy.deepcopy((upstream, downstream))
        pose = assembly_api.mate_ports(upstream, downstream, rotation=[[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]], gap_mm=.5)
        self.assertEqual(pose.translation_mm, (2., -1., 7.5))
        self.assertEqual((pose.from_frame_id, pose.to_frame_id), ("local", "world"))
        self.assertEqual((upstream, downstream), before)
        for gap in (-.1, float("nan"), True):
            with self.subTest(gap=gap), self.assertRaises(ValueError):
                assembly_api.mate_ports(upstream, downstream, rotation=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]], gap_mm=gap)
        downstream["outward_normal"] = [0.,0.,1.]
        with self.assertRaisesRegex(ValueError, "normals must oppose"):
            assembly_api.mate_ports(upstream, downstream, rotation=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]], gap_mm=0.)

    def test_rectangular_mating_checks_named_in_plane_axes(self):
        section = dict(shape="rectangle", width_mm=3., height_mm=2., width_axis=[1.,0.,0.], height_axis=[0.,1.,0.])
        up = dict(frame_id="world", center_mm=[0.,0.,0.], outward_normal=[0.,0.,1.], cross_section=section)
        down = dict(frame_id="local", center_mm=[0.,0.,0.], outward_normal=[0.,0.,-1.], cross_section=copy.deepcopy(section))
        assembly_api.mate_ports(up, down, rotation=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]], gap_mm=0.)
        with self.assertRaisesRegex(ValueError, "width_axis"):
            assembly_api.mate_ports(up, down, rotation=[[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]], gap_mm=0.)

    def test_execution_configuration_does_not_create_or_probe_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "new study 中文"
            with patch("subprocess.Popen", side_effect=AssertionError("process probe")), \
                 patch.object(Path, "mkdir", side_effect=AssertionError("directory creation")):
                context = execution_api.load_environment(workspace=workspace,
                    tools={"python": base/"python.exe", "powershell": base/"pwsh.exe"},
                    policy={"host_state_path": base/"shared.sqlite3", "policy_path": base/"policy.json",
                            "execution_root":base/"short_aliases"})
                defaults = execution_api.load_environment(workspace=workspace,
                    tools={"python":base/"python.exe","powershell":base/"pwsh.exe"},
                    policy={"host_state_path":base/"shared.sqlite3"})
            self.assertEqual(context.workspace, workspace)
            self.assertEqual(context.execution_root,base/"short_aliases")
            self.assertEqual(defaults.policy_path.name,"host_resource_policy.json")
            self.assertEqual(defaults.execution_root,workspace/"artifacts/common/execution_aliases")
            self.assertFalse(workspace.exists())


if __name__ == "__main__":
    unittest.main()
