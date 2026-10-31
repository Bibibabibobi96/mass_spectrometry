from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from common.contracts.machine_contracts import load_json, sha256
from common.contracts import write_run_manifest as terminal_publication
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases
from common.contracts.verify_artifact_layout import verify_project
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import finalize_candidate_run, start_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import PYTHON_BOUND_SOURCES, RELATIVE_PATHS, freeze_candidate_source_closure, frozen_source_path, verify_candidate_source_closure
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers import prepare
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import _registered_candidate_template, prepare_candidate_run, validate_artifact_capacity, validate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate as candidate_entry
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as candidate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import CandidateWorkflowError, CandidateWorkflowInterrupted, CandidateWorkflowTimedOut, StageTimedOut, _powershell, _run_command, _stage_source_paths, _verify_frozen_cad_python, execute_stage, run_candidate_workflow

from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.candidate_fixtures import (
    CandidateFixtures,
    PROJECT_ROOT,
    REPO_ROOT,
)


class CandidateDesignTests(CandidateFixtures, unittest.TestCase):
    def test_candidate_finalization_uses_frozen_request_without_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs" / "candidate"
            request_path = run / "inputs" / "execution_request.json"
            request_path.parent.mkdir(parents=True)
            request_path.write_text(json.dumps({"package": {"project": "single_reflection_oa_tof_mass_analyzer",
                "mode": "design_candidate", "artifact_project_root": str(root), "run_id": run.name}}), encoding="utf-8")
            (run / "summary.json").write_text('{"candidate_decision":"candidate_rejected"}', encoding="utf-8")
            result_path = root / "scratch" / "workflow_results" / run.name / "result.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text('{}', encoding="utf-8")
            def owner(command, log):
                self.assertIn("-ResumeFinalization", command)
                self.assertEqual(Path(command[command.index("-RequestPath") + 1]), request_path)
                self.assertEqual(Path(command[command.index("-ResultPath") + 1]), result_path)
                result_path.write_text('{"terminal_published":true,"capacity_finalized":true,"lease_released":true}', encoding="utf-8")
            with mock.patch.object(candidate_workflow, "_run_command", side_effect=owner), \
                    mock.patch.object(candidate_workflow, "_execute_candidate_stages") as stages:
                self.assertEqual(candidate_workflow.resume_candidate_finalization(run)[0], run)
                stages.assert_not_called()
            def failed_owner(command, log):
                log.write_text("publication failure detail", encoding="utf-8")
                raise RuntimeError("owner failed")
            with mock.patch.object(candidate_workflow, "_run_command", side_effect=failed_owner):
                with self.assertRaisesRegex(CandidateWorkflowError, "publication failure detail"):
                    candidate_workflow.resume_candidate_finalization(run)


    def test_normal_cli_consumes_explicit_numerics_and_public_artifact_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact = root / "explicit-storage"
            project = artifact / "projects" / PROJECT_ROOT.name
            registration = self.registered_template_run(project)
            runtime = root / "runtime.json"
            runtime.write_text(json.dumps({"role": "oa_tof_candidate_runtime",
                "simion_template_run_id": registration.name}), encoding="utf-8")
            numerics = root / "numerics.json"
            values = load_json(PROJECT_ROOT / "config/formal_solver_numerics.json")
            values["comsol"].update(routine_reflectron_hmax_mm=30.0,
                fine_output_step_ns=0.4, field_free_output_step_ns=100.0)
            numerics.write_text(json.dumps(values), encoding="utf-8")
            original = numerics.read_bytes()
            argv = ["run_candidate", "--request", str(source / "design_request.json"),
                "--run-id", "20261031_101001__test__cross__explicit-numerics-root",
                "--particle-source-seed", "20260720", "--solver-numerics-contract", str(numerics), "--dry-run"]
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_ARTIFACT_ROOT": str(artifact)}), \
                    mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime), \
                    mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(candidate_entry, "run_candidate_workflow") as native:
                candidate_entry.main()
                native.assert_not_called()
            plans = list((project / "scratch").rglob("candidate_workflow_plan.json"))
            self.assertEqual(len(plans), 1)
            plan = load_json(plans[0])
            self.assertEqual(Path(plan["run_root"]).parent, project / "runs")
            frozen = Path(plan["candidate_inputs"]["candidate_solver_numerics.json"]["path"])
            self.assertEqual(frozen.read_bytes(), original)
            resolved = load_json(Path(plan["candidate_inputs"]["candidate_resolved_geometry.json"]["path"]))
            self.assertEqual(resolved["comsol_runtime"]["routine_reflectron_hmax_mm"], 30.0)
            self.assertEqual(resolved["comsol_runtime"]["fine_output_step_ns"], 0.4)
            diff = load_json(Path(plan["candidate_inputs"]["candidate_diff.json"]["path"]))
            self.assertFalse(diff["zero_change_reference_reproduction"])
            self.assertEqual(diff["provenance"]["solver_numerics"]["sha256"],
                             plan["candidate_inputs"]["candidate_solver_numerics.json"]["sha256"])
            self.assertEqual(Path(diff["provenance"]["solver_numerics"]["path"]), numerics.resolve())
            self.assertEqual(numerics.read_bytes(), original)

    def test_analysis_and_finalization_reject_new_solver_numerics_before_preparation(self):
        for arguments in (["--postprocess-from", "missing-parent", "--run-id", "unused"],
                          ["--resume-finalization", "missing-run"]):
            with self.subTest(arguments=arguments), mock.patch.object(sys, "argv",
                    ["run_candidate", *arguments, "--solver-numerics-contract", "missing-numerics.json"]), \
                    mock.patch.object(candidate_entry, "prepare_execution") as prepare:
                with self.assertRaises(SystemExit) as error:
                    candidate_entry.main()
                self.assertEqual(error.exception.code, 2)
                prepare.assert_not_called()

    def test_candidate_entry_forwards_explicit_pa_handoff_and_rejects_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pairs = [[root / "transaction1.json", root / "result1.json"], [root / "transaction2.json", root / "result2.json"]]
            output = root / "retained_owner_result.json"
            argv = ["run_candidate", "--request", str(root / "request.json"), "--run-id", "20261029_030000__test__cross__handoff-cli",
                "--particle-source-seed", "7", "--simion-exe", sys.executable, "--pa-handoff-output", str(output)]
            for pair in pairs:
                argv.extend(["--pa-producer-handoff", *map(str, pair)])
            with mock.patch.object(sys, "argv", argv), mock.patch.object(candidate_entry, "prepare_execution", return_value=root / "plan.json"), \
                    mock.patch.object(candidate_entry, "run_candidate_workflow", return_value=(root / "run", {"candidate_decision": "candidate_rejected"})) as execute:
                candidate_entry.main()
                self.assertEqual(execute.call_args.kwargs["pa_handoff_output"], output)
                self.assertEqual(execute.call_args.kwargs["pa_producer_handoffs"], pairs)
            with mock.patch.object(sys, "argv", [*argv, "--dry-run"]), mock.patch.object(candidate_entry, "prepare_execution") as prepare:
                with self.assertRaises(SystemExit) as error:
                    candidate_entry.main()
                self.assertEqual(error.exception.code, 2)
                prepare.assert_not_called()
            with mock.patch.object(candidate_entry, "prepare_execution", return_value=root / "plan.json"), \
                    mock.patch.object(candidate_entry, "run_candidate_workflow", return_value=(root, {})) as execute:
                candidate_entry.execute_request(root / "request.json", "unused", simion_executable=Path(sys.executable),
                    particle_source_seed=7, pa_handoff_output=output, pa_producer_handoffs=pairs)
                self.assertEqual(execute.call_args.kwargs["pa_producer_handoffs"], pairs)


    def test_candidate_pa_handoff_output_preserves_actual_owner_bytes_and_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run = root / "artifacts/projects/fixture/runs/20261029_030001__test__cross__handoff"
                result_path = root / "owner_result.json"
                request = {"package": {"artifact_project_root": str(run.parent.parent), "run_id": run.name,
                    "retention_class": "solver_review", "retention_reason": "original reason"}}
                raw = b'{ "terminal_published":true,"capacity_finalized":true,"lease_released":true,"exception":"original failure" }\n'
                original = RuntimeError("owner exit 7")
                def owner(command, _log):
                    self.assertEqual(Path(command[command.index("-ResultPath") + 1]), result_path)
                    sent = load_json(Path(command[command.index("-RequestPath") + 1]))
                    self.assertEqual(sent["package"]["retention_class"], "solver_review")
                    self.assertIn("Explicit PA producer handoff", sent["package"]["retention_reason"])
                    run.mkdir(parents=True)
                    (run / "summary.json").write_text(json.dumps({"status": "failed" if failed else "success"}), encoding="utf-8")
                    result_path.write_bytes(raw)
                    if failed:
                        raise original
                with mock.patch.object(candidate_workflow, "_prepare_execution_request", return_value=request), \
                        mock.patch.object(candidate_workflow, "_run_command", side_effect=owner):
                    if failed:
                        with self.assertRaises(CandidateWorkflowError) as error:
                            run_candidate_workflow(root / "plan", sys.executable, pa_handoff_output=result_path)
                        self.assertIs(error.exception.__cause__, original)
                    else:
                        self.assertEqual(run_candidate_workflow(root / "plan", sys.executable, pa_handoff_output=result_path)[0], run)
                    self.assertEqual(result_path.read_bytes(), raw)
                with mock.patch.object(candidate_workflow, "_prepare_execution_request", return_value=request), \
                        mock.patch.object(candidate_workflow, "_run_command") as launch:
                    with self.assertRaisesRegex(ValueError, "new path outside"):
                        run_candidate_workflow(root / "plan", sys.executable, pa_handoff_output=result_path)
                    with self.assertRaisesRegex(ValueError, "new path outside"):
                        run_candidate_workflow(root / "plan", sys.executable,
                            pa_handoff_output=run.parent / "prior_run/transport.json")
                    launch.assert_not_called()


    def test_candidate_registers_all_shared_handoff_inputs_before_scientific_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, plan_path = self.native_workflow_plan(root, "20261029_030002")
            request = candidate_workflow._prepare_execution_request(plan_path, sys.executable, None, None)
            handoff_plan = {"sources": ["explicit fixture selection"]}
            session_path = root / "session.json"
            session_path.write_text('{"fixture": "selected session"}', encoding="utf-8")
            def freeze(run, selected, **kwargs):
                self.assertIs(selected, handoff_plan)
                self.assertEqual(kwargs["capacity_session"], {"fixture": "selected session"})
                self.assertEqual(kwargs["expected_cache_keys"], set(request["capacity"]["protected_cache_keys"]))
                folder = run / "inputs/pa_producer_handoffs"
                folder.mkdir()
                index, proof = folder / "handoffs.json", folder / "original_result.json"
                index.write_text('{"fixture": "index"}', encoding="utf-8")
                proof.write_text('{"fixture": "original result"}', encoding="utf-8")
                return {**terminal_publication.file_record(index), "frozen_input_records": [
                    terminal_publication.file_record(proof), terminal_publication.file_record(index)]}
            def stop(stage, plan, _simion):
                self.assertEqual(stage["stage_id"], "static_inputs")
                config = load_json(Path(plan["run_root"]) / "run_config.json")
                self.assertEqual(plan["producer_handoff_path"], config["pa_producer_handoffs"]["path"])
                for name in ("pa_producer_handoff_0", "pa_producer_handoff_1"):
                    self.assertEqual(config["input_sha256"][name], sha256(Path(config["inputs"][name])))
                raise RuntimeError("input registration checked before science")
            with mock.patch.object(candidate_workflow, "freeze_pa_producer_handoffs", side_effect=freeze) as shared:
                with self.assertRaisesRegex(CandidateWorkflowError, "input registration checked"):
                    candidate_workflow._execute_candidate_stages(plan_path, sys.executable, stop, execution_context={
                        "component_pa_plan": request["payload"]["component_pa_plan"], "pa_producer_handoffs": handoff_plan,
                        "capacity_session_path": str(session_path)})
                shared.assert_called_once()
            manifest = load_json(Path(load_json(plan_path)["run_root"]) / "run_manifest.json")
            self.assertIn("pa_producer_handoff_0", manifest["inputs"])
            self.assertIn("pa_producer_handoff_1", manifest["inputs"])


    def test_stage_completion_preserves_actual_failure_and_never_fills_unknown_facts(self):
        for kind in ("closed", "missing", "wrong_context", "malformed", "unknown_worker", "wrong_worker_identity"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "build.json"
                plan = {"run_id": "fixture", "context_sha256": "a" * 64,
                        "writer_completion": {"operations": [], "resource_releases": []}}
                original = RuntimeError("original native exit 7")
                receipt = {"schema_version": 1, "role": "oatof_component_build_completion", "run_id": "fixture",
                    "context_sha256": ("b" if kind == "wrong_context" else "a") * 64,
                    "operations": [{"operation_id": "native", "observation": {"exit_confirmed": True, "returncode": 7},
                                    "managed_process_completion": self.managed_completion_fixture(1)}],
                    "host_release": {"inherited": False, "token": "fixture-token", "result": {"status": "released", "token": "fixture-token"}, "error": None}}
                if kind == "unknown_worker":
                    receipt["operations"][0]["managed_process_completion"]["worker_exit_confirmed"] = False
                if kind == "wrong_worker_identity":
                    receipt["operations"][0]["managed_process_completion"]["worker_started_at_utc_ticks"] = None
                if kind != "missing":
                    path.write_text("{" if kind == "malformed" else json.dumps(receipt), encoding="utf-8")
                with mock.patch.object(candidate_workflow, "_run_command", side_effect=original):
                    with self.assertRaises(RuntimeError) as caught:
                        candidate_workflow._run_managed_stage_command(["fixture"], root / "log.txt", plan, path,
                                                                      "oatof_component_build_completion")
                self.assertIs(caught.exception, original)
                writer = plan["writer_completion"]
                self.assertEqual(len(writer["operations"]), 1)
                if kind == "closed":
                    self.assertEqual(writer["operations"][0]["observation"], {"exit_confirmed": True, "returncode": 7})
                    self.assertEqual(writer["resource_releases"][0]["completion_receipt"], receipt)
                else:
                    self.assertFalse(writer["operations"][0]["observation"]["exit_confirmed"])
                    self.assertIsNone(writer["operations"][0]["observation"]["returncode"])
                    self.assertEqual(writer["resource_releases"], [])
                    if kind != "missing":
                        self.assertIn("Native completion validation also failed", original.__notes__[0])


    def test_stage_completion_does_not_accept_native_zero_after_actual_worker_failure(self):
        for role in ("oatof_component_build_completion", "oatof_candidate_flight_process_result"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "completion.json"
                managed = self.managed_completion_fixture(1)
                receipt = {"schema_version": 1, "role": role, "run_id": "fixture", "context_sha256": "a" * 64,
                    "host_release": {"inherited": False, "token": "fixture-token",
                        "result": {"status": "released", "token": "fixture-token"}, "error": None}}
                if role == "oatof_component_build_completion":
                    receipt["operations"] = [{"operation_id": "native", "observation": {
                        "exit_confirmed": True, "returncode": 0}, "managed_process_completion": managed}]
                else:
                    receipt.update(native_exit_confirmed=True, native_returncode=0, managed_process_completion=managed)
                path.write_text(json.dumps(receipt), encoding="utf-8")
                plan = {"run_id": "fixture", "context_sha256": "a" * 64,
                    "writer_completion": {"operations": [], "resource_releases": []}}
                with mock.patch.object(candidate_workflow, "_run_command"):
                    with self.assertRaisesRegex(RuntimeError, "managed writer failed \\(1\\)"):
                        candidate_workflow._run_managed_stage_command([], root / "log", plan, path, role)
                self.assertEqual(plan["writer_completion"]["operations"][0]["observation"],
                                 {"exit_confirmed": True, "returncode": 0})
                self.assertEqual(plan["writer_completion"]["resource_releases"][0]["completion_receipt"], receipt)


    def test_managed_request_uses_frozen_disk_authorities_before_creating_run(self):
        with tempfile.TemporaryDirectory() as directory:
            _, plan_path = self.native_workflow_plan(Path(directory), "20261028_130000")
            request = candidate_workflow._prepare_execution_request(plan_path, sys.executable, None, None)
            plan = load_json(plan_path)
            self.assertFalse(Path(plan["run_root"]).exists())
            expected = candidate_workflow.sum_component_commitments([request["payload"]["component_pa_plan"]])
            expected += sum(plan["artifact_capacity"][key] for key in ("comsol_bytes", "cad_bytes", "evidence_bytes"))
            self.assertEqual(request["capacity"]["committed_new_bytes"], expected)
            self.assertEqual(request["package"]["run_id"], plan["run_id"])
            self.assertEqual(request["prepared"]["import_root"], plan["execution_source_closure"]["code_root"])
            runtime = Path(plan["candidate_inputs"]["candidate_runtime.json"]["path"])
            self.assertIn(terminal_publication.file_record(runtime), request["capacity"]["commitment_inputs"])
            pairs = [(Path(directory) / "transaction.json", Path(directory) / "owner_result.json")]
            handoff = {"source_records": [terminal_publication.file_record(plan_path)],
                       "protected_paths": [str(Path(directory) / "prior-run")], "sources": []}
            with mock.patch.object(candidate_workflow, "plan_pa_producer_handoffs", return_value=handoff) as preflight:
                selected = candidate_workflow._prepare_execution_request(plan_path, sys.executable, None, None, pairs)
                self.assertEqual(preflight.call_args.args[0], pairs)
                self.assertEqual(preflight.call_args.kwargs["expected_cache_keys"], set(request["capacity"]["protected_cache_keys"]))
                self.assertEqual(preflight.call_args.kwargs["artifact_root"], Path(plan["run_root"]).parents[3])
                self.assertEqual(selected["payload"]["pa_producer_handoffs"], handoff)
                self.assertIn(handoff["protected_paths"][0], selected["capacity"]["protected_paths"])
                self.assertEqual(selected["capacity"]["committed_new_bytes"], expected)
                self.assertEqual(selected["capacity"]["commitment_inputs"][-1], handoff["source_records"][0])
            with mock.patch.object(candidate_workflow, "plan_pa_producer_handoffs", side_effect=ValueError("unknown component")):
                with self.assertRaisesRegex(ValueError, "unknown component"):
                    candidate_workflow._prepare_execution_request(plan_path, sys.executable, None, None, pairs)
            self.assertFalse(Path(plan["run_root"]).exists())
            document = load_json(runtime)
            document["artifact_capacity"]["comsol_bytes"] *= 2
            runtime.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "planned candidate input changed before admission"):
                candidate_workflow._prepare_execution_request(plan_path, sys.executable, None, None)
            self.assertFalse(Path(plan["run_root"]).exists())


    def test_real_public_owner_runs_prepared_candidate_in_one_admitted_root(self):
        # The actual project callback and public owner run; only commercial
        # scientific stages are replaced by an explicit software executor.
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory(prefix="candidate-owner-") as directory:
                root = Path(directory)
                artifact_project, plan_path = self.native_workflow_plan(root, "20261028_130100")
                artifacts = artifact_project.parent.parent
                initialize_capacity_ledger(artifacts, objects=[])
                request = candidate_workflow._prepare_execution_request(plan_path, sys.executable, None, None)
                # This explicit software callback has a separate import root;
                # copy the common handshake bootstrap from the frozen closure.
                (root / "common/contracts").mkdir(parents=True)
                for relative in ("common/host_resource_python.py", "common/contracts/recorded_file_removal.py", "common/contracts/file_identity.py"):
                    shutil.copyfile(Path(request["prepared"]["import_root"]) / relative, root / relative)
                callback = root / "candidate_fixture.py"
                callback.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(request["prepared"]["import_root"]) + ")\n" + r'''
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
original = workflow._execute_candidate_stages
def fixture(stage, plan, _simion):
    root = Path(plan['run_root'])
    if FAIL and stage['stage_id'] == 'simion_candidate':
        raise RuntimeError('deliberate software stage failure')
    if stage['stage_id'] == 'static_inputs':
        particle = Path(stage['pending_output']); particle.write_text('fixture particle\n')
        return {'particle_table': str(particle)}
    output = root/'results'/('fixture_' + stage['stage_id'] + '.txt')
    output.write_text('software fixture; no solver result\n')
    return {'model' if stage['stage_id']=='comsol_candidate' else 'report': str(output)}
def injected(*args, **kwargs):
    kwargs['stage_executor'] = fixture
    return original(*args, **kwargs)
def execute_prepared_run(*args):
    workflow._execute_candidate_stages = injected
    workflow.execute_prepared_run(*args)
'''.replace("FAIL", repr(failed)), encoding="utf-8")
                request["prepared"] = {"module": "candidate_fixture", "function": "execute_prepared_run",
                    "import_root": str(root), "entrypoint": terminal_publication.file_record(callback)}
                request_path, result_path = root / "request.json", root / "result.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                driver = root / "driver.ps1"
                driver.write_text(f". '{REPO_ROOT / 'common/contracts/run_artifact_workflow.ps1'}'\n"
                    "function Invoke-ArtifactCapacityGate { return @{satisfied=$true;fixture_admission=$true} }\n"
                    f"$null=Invoke-RunArtifactWorkflow -RequestPath '{request_path}' -ResultPath '{result_path}'\n", encoding="utf-8")
                process = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver)], cwd=REPO_ROOT,
                    capture_output=True, text=True, encoding="utf-8", check=False, timeout=300)
                diagnostics = "\n".join(path.read_text(encoding="utf-8", errors="replace")[-4000:]
                                        for path in artifacts.rglob("prepared_stderr.log"))
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr + diagnostics)
                result = load_json(result_path)
                self.assertEqual(result["status"], "failed" if failed else "success", result)
                self.assertTrue(result["terminal_published"] and result["capacity_finalized"] and result["lease_released"])
                run = Path(load_json(plan_path)["run_root"])
                config = load_json(run / "run_config.json")
                self.assertEqual(config["schema_version"], 2)
                self.assertEqual(config["run_id"], request["package"]["run_id"])
                self.assertTrue(config["capacity_ledger_lifecycle"]["enabled"])
                self.assertEqual(config["artifact_retention"]["class"], "solver_review")
                from common.contracts.stage_reuse import validate_and_write_stage_reuse
                receipt = load_json(run / "stage_receipts/comsol_candidate.json")
                child = root / "runs/20261028_140100__analysis__python__candidate-v2-reuse"
                child.mkdir(parents=True)
                context = {}
                declared = {}
                for category, records in receipt["context"].items():
                    context[category] = {}
                    for name, record in records.items():
                        original_file = run / record["path"]
                        destination = child / "inputs" / category / (name + original_file.suffix)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(original_file, destination)
                        context[category][name] = destination
                        declared[name] = str(destination)
                declared["stage_reuse_provenance"] = str(child / "inputs/stage_reuse_provenance.json")
                (child / "run_config.json").write_text(json.dumps({"schema_version": 1, "run_id": child.name,
                    "project": config["project"], "inputs": declared}), encoding="utf-8")
                before_parent = (run / "run_manifest.json").read_bytes()
                provenance = validate_and_write_stage_reuse(child, parent_run_root=run, project=config["project"],
                    stage_contexts={"comsol_candidate": context})
                self.assertEqual(load_json(provenance)["parent_run_status"], "failed" if failed else "success")
                self.assertEqual((run / "run_manifest.json").read_bytes(), before_parent)
                self.assertEqual(load_json(run / "summary.json")["status"], result["status"])
                objects = load_capacity_ledger(artifacts)["objects"]
                self.assertEqual(len(objects), 1)
                self.assertNotEqual(objects[0]["status"], "writing")
                self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])
                completion = load_json(run / "results/execution_completion.json")
                self.assertEqual(completion["writer_completion"], {"operations": [], "resource_releases": []})
                if failed:
                    self.assertIn("deliberate software stage failure", completion["exception"]["message"])


    def test_frozen_sources_import_managed_build_and_lifecycle_without_live_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            closure = freeze_candidate_source_closure(root / "code", root / "artifacts")
            report_source = "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_report_model_timing.m"
            self.assertEqual(Path(frozen_source_path(closure, report_source)).read_bytes(), (REPO_ROOT / report_source).read_bytes())
            result = subprocess.run([
                sys.executable, "-B", "-c",
                "from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow; "
                "from projects.single_reflection_oa_tof_mass_analyzer.analysis import simion_component_pa_plan; "
                "from common.contracts import reconcile_artifact_capacity, verify_artifact_layout, capacity_ledger, solver_review_retirement; "
                "from pathlib import Path; "
                "solver_review_retirement._assert_runtime_retirement_unprotected(Path.cwd()/'empty-artifacts', Path.cwd()/'empty-artifacts/run'); "
                "print('FROZEN_IMPORT_PASS')",
            ], cwd=closure["code_root"], capture_output=True, text=True, check=False, timeout=60,
                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FROZEN_IMPORT_PASS", result.stdout)


    def test_artifact_capacity_requires_explicit_positive_bytes_and_basis(self):
        runtime = load_json(PROJECT_ROOT / "config" / "candidate_runtime.json")
        capacity = validate_artifact_capacity(runtime)
        self.assertEqual(capacity["comsol_bytes"], 4 * 1024**3)
        for missing in ("artifact_capacity", "comsol_bytes", "cad_bytes", "evidence_bytes", "basis"):
            invalid = json.loads(json.dumps(runtime))
            if missing == "artifact_capacity":
                del invalid[missing]
            else:
                del invalid["artifact_capacity"][missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                validate_artifact_capacity(invalid)
        for value in (0, -1, True, 1.5, "4294967296"):
            invalid = json.loads(json.dumps(runtime))
            invalid["artifact_capacity"]["comsol_bytes"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_artifact_capacity(invalid)


    def test_source_closure_explicit_workflow_extras_share_freezing_and_identity(self):
        extra = "common/simion/batch_continuation.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            closure = freeze_candidate_source_closure(
                root / "code", root / "artifacts",
                extra_source_ids=(extra, extra, RELATIVE_PATHS[0]),
            )
            records = {item["source_id"]: item for item in closure["sources"]}
            self.assertEqual(len(records), len(RELATIVE_PATHS) + 1)
            self.assertEqual(records[extra]["source_sha256"], sha256(REPO_ROOT / extra))
            reducer = "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_detector_arrival_reducer.m"
            reducer_path = Path(frozen_source_path(closure, reducer))
            self.assertEqual(reducer_path.read_bytes(), (REPO_ROOT / reducer).read_bytes())
            self.assertEqual(records[reducer]["source_sha256"], sha256(REPO_ROOT / reducer))
            frozen = Path(frozen_source_path(closure, extra))
            self.assertEqual(frozen.read_bytes(), (REPO_ROOT / extra).read_bytes())
            verify_candidate_source_closure(closure)
            frozen.write_bytes(frozen.read_bytes() + b"\n# modified fixture\n")
            with self.assertRaisesRegex(ValueError, "frozen candidate source changed"):
                verify_candidate_source_closure(closure)


    def test_source_closure_rejects_invalid_extras_before_copy(self):
        for extra in ("../outside.py", str(Path(__file__).resolve()), "absent_source.py"):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(ValueError):
                    freeze_candidate_source_closure(
                        root / "code", root / "artifacts", extra_source_ids=(extra,),
                    )
                self.assertFalse((root / "code").exists())


    def test_frozen_path_resolution_does_not_rehash_or_scan(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import candidate_source_closure as module
        closure = {"schema_version": 2, "role": module.ROLE,
                   "code_root": str(PROJECT_ROOT), "sources": [{"source_id": "analysis/reference_analysis.py"}]}
        with mock.patch.object(module, "sha256") as digest, mock.patch.object(Path, "rglob") as scan:
            self.assertEqual(frozen_source_path(closure, "analysis/reference_analysis.py"),
                             str((PROJECT_ROOT / "analysis/reference_analysis.py").resolve()))
            digest.assert_not_called()
            scan.assert_not_called()
        with self.assertRaisesRegex(ValueError, "undeclared"):
            frozen_source_path(closure, "missing.py")
        closure["sources"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            frozen_source_path(closure, "analysis/reference_analysis.py")
        closure["sources"] = [{"source_id": "../escape.py"}]
        with self.assertRaisesRegex(ValueError, "invalid candidate source path"):
            frozen_source_path(closure, "../escape.py")


    def test_candidate_freeze_rejects_provider_api_version_before_copy(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import candidate_source_closure as closure
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "projects/orthogonal_accelerator/config/component_contract.json",
                "projects/single_reflection_oa_tof_mass_analyzer/config/accelerator_dependency.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((REPO_ROOT / relative).read_bytes())
            provider_path = root / "projects/orthogonal_accelerator/config/component_contract.json"
            provider = json.loads(provider_path.read_text(encoding="utf-8"))
            provider["api_version"] = 3
            provider_path.write_text(json.dumps(provider), encoding="utf-8")
            with mock.patch.multiple(closure, REPO_ROOT=root,
                                     PROJECT_ROOT=root / "projects/single_reflection_oa_tof_mass_analyzer"):
                with self.assertRaisesRegex(ValueError, "api_version"):
                    freeze_candidate_source_closure(root / "frozen", root / "artifacts")
            self.assertFalse((root / "frozen").exists())


    def test_candidate_runtime_preflight_validates_registered_source_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = (
                root_path
                / "artifacts"
                / "projects"
                / "single_reflection_oa_tof_mass_analyzer"
            )
            registration = self.registered_template_run(artifact_root)
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                preflight = candidate_entry.validate_candidate_runtime(artifact_root)
                self.assertTrue(preflight["template"].samefile(registration))
                source_iob = Path(preflight["registration"]["source_iob"])
                source_iob.write_bytes(b"mutated-after-registration")
                with self.assertRaisesRegex(ValueError, "SHA-256 changed"):
                    candidate_entry.validate_candidate_runtime(artifact_root)


    def test_candidate_run_is_isolated_and_never_contains_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            run_id = "20260720_120000__build__cross__design-candidate__zero-change"
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers.prepare",
                side_effect=AssertionError("live compiler must not execute"),
            ):
                plan = prepare_candidate_run(
                    *inputs, run_id, artifact_root, particle_source_seed=20260713
                )
            expected_run_root = artifact_root / "runs" / run_id
            run_root = Path(plan["run_root"])
            planning_root = Path(plan["planning_root"])
            code_root = Path(plan["execution_source_closure"]["code_root"])
            compiler = code_root / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/prepare_candidate_consumers.py"
            compiler_log = planning_root / "logs/prepare_consumers.stdout.log"
            self.assertIn(f"SOURCE={compiler}", compiler_log.read_text(encoding="utf-8"))
            frozen_resolved = json.loads((planning_root / "inputs/candidate_resolved_geometry.json").read_text())
            from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
                render_fly2, render_program, render_resolved_lua,
            )
            expected = {"oatof_resolved.lua": render_resolved_lua(frozen_resolved),
                        "oatof_ideal_grounded.lua": render_program(frozen_resolved),
                        "oatof_ideal_grounded.fly2": render_fly2(frozen_resolved, particle_source_seed=20260713)}
            for name, text in expected.items():
                self.assertEqual((planning_root / "inputs/prepared_consumers/simion" / name).read_text(), text)
            # GitHub Windows runners may expose the same temporary directory
            # through long and 8.3 path aliases.  Compare the existing project
            # root by file identity, then verify the not-yet-created suffix.
            self.assertTrue(run_root.parents[1].samefile(artifact_root))
            self.assertEqual(run_root.parent.name, "runs")
            self.assertEqual(run_root.name, run_id)
            self.assertFalse(expected_run_root.exists())
            self.assertTrue(planning_root.parents[1].samefile(artifact_root))
            self.assertEqual(planning_root.parent.name, "scratch")
            self.assertFalse(plan["formal_root"]["mutation_allowed"])
            self.assertEqual(plan["status"], "NEEDS_RUNTIME_INPUTS")
            self.assertFalse(plan["promotion"]["included"])
            self.assertFalse(plan["promotion"]["automatic"])
            self.assertFalse(plan["promotion"]["safe_to_promote"])
            self.assertEqual(plan["stages"][-1]["stage_id"], "structural_acceptance")
            self.assertEqual(plan["stages"][-1]["status"], "blocked")
            simion_stage = next(
                stage for stage in plan["stages"]
                if stage["stage_id"] == "simion_candidate"
            )
            self.assertEqual(
                simion_stage["status"],
                "blocked_requires_explicit_nonformal_template",
            )
            serialized = json.dumps(plan)
            self.assertNotIn("NEEDS_CROSS_SOLVER_RUNNER", serialized)
            self.assertNotIn("needs_integrated_candidate_runner", serialized)
            for stage in plan["stages"]:
                for key in ("model_path", "output_dir", "report_path"):
                    if key in stage:
                        Path(stage[key]).resolve().relative_to(run_root.resolve())
            comsol_stage = next(stage for stage in plan["stages"] if stage["stage_id"] == "comsol_candidate")
            self.assertEqual(Path(comsol_stage["environment"]["OATOF_RUNTIME_DIR"]), run_root / "comsol")
            self.assertEqual(
                set(plan["candidate_inputs"]),
                {"candidate_baseline.json", "candidate_resolved_geometry.json", "candidate_solver_numerics.json", "candidate_diff.json", "candidate_analysis_contract.json",
                 "candidate_runtime.json",
                 "candidate_proposal.json", "design_request.json",
                 "candidate_simion_resolved_lua", "candidate_simion_program", "candidate_simion_fly2"},
            )
            analysis_input = plan["candidate_inputs"]["candidate_analysis_contract.json"]
            self.assertEqual(analysis_input["sha256"], sha256(Path(analysis_input["path"])))
            self.assertEqual(Path(analysis_input["path"]).read_bytes(), (PROJECT_ROOT / "config/analysis_contract.json").read_bytes())
            self.assertTrue((planning_root / "run_config.template.json").is_file())
            self.assertTrue((planning_root / "candidate_workflow_plan.json").is_file())
            closure = plan["execution_source_closure"]
            verify_candidate_source_closure(closure)
            source_ids = {item["source_id"] for item in closure["sources"]}
            self.assertEqual(source_ids, set(RELATIVE_PATHS) | {
                "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json",
                "projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json",
            })
            self.assertTrue({
                "projects/orthogonal_accelerator/analysis/accelerator_time_focus.py",
                "projects/orthogonal_accelerator/analysis/component_contract.py",
                "projects/orthogonal_accelerator/config/component_contract.json",
                "projects/single_reflection_oa_tof_mass_analyzer/config/accelerator_dependency.json",
                "projects/orthogonal_accelerator/analysis/three_zone_ideal_theory.py",
                "projects/orthogonal_accelerator/analysis/two_zone_geometry.py",
                "projects/orthogonal_accelerator/comsol/build_sectioned_geometry.m",
                "projects/orthogonal_accelerator/comsol/build_accelerator_grids.m",
                "projects/orthogonal_accelerator/simion/build_two_zone_pa.lua",
                "projects/orthogonal_accelerator/simion/two_zone_accelerator.gem",
            }.issubset(source_ids))
            self.assertIn("common/require_powershell7.ps1", source_ids)
            self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1", source_ids)
            self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_iob.lua", source_ids)
            code_root = Path(closure["code_root"]).resolve()
            for stage in plan["stages"]:
                for key in ("entrypoint", "task_script"):
                    if key in stage:
                        Path(stage[key]).resolve().relative_to(code_root)
            transformed = {
                item["source_id"]
                for item in closure["sources"]
                if "python_runtime_binding" in item["transformations"]
            }
            self.assertEqual(transformed, PYTHON_BOUND_SOURCES)
            for source_id in (
                "common/paths/workspace_paths.m",
                "projects/single_reflection_oa_tof_mass_analyzer/oatof_paths.m",
            ):
                record = next(item for item in closure["sources"] if item["source_id"] == source_id)
                self.assertEqual(record["transformations"], [])
                self.assertEqual(record["source_sha256"], record["sha256"])
                self.assertEqual((code_root / source_id).read_bytes(), (REPO_ROOT / source_id).read_bytes())
            live_root = str(REPO_ROOT.resolve()).encode()
            runtime_path = closure["runtime"]["python_executable"].encode()
            for item in closure["sources"]:
                frozen_path = code_root / item["source_id"]
                payload = frozen_path.read_bytes().replace(
                    runtime_path, b"<FROZEN_PYTHON_RUNTIME>"
                )
                self.assertNotIn(live_root, payload)
            with self.assertRaisesRegex(FileExistsError, "overwrite is forbidden"):
                prepare_candidate_run(
                    *inputs, run_id, artifact_root, particle_source_seed=20260713
                )


    def test_candidate_seed_is_required_at_each_preparation_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            with self.assertRaisesRegex(ValueError, "explicit integer particle source seed"):
                prepare_candidate_run(
                    *inputs,
                    "20260727_165900__test__cross__missing-seed",
                    root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer",
                )
            with self.assertRaisesRegex(ValueError, "explicit particle source seed"):
                prepare(
                    PROJECT_ROOT / "config" / "resolved_geometry.json",
                    root_path / "prepared",
                )


    def test_candidate_comsol_adapter_uses_contract_and_run_config_authorities(self):
        source = (
            PROJECT_ROOT
            / "workflows"
            / "design_candidate"
            / "run_candidate_contract_build.m"
        ).read_text(encoding="utf-8")
        self.assertIn("OATOF_CANDIDATE_RUN_CONFIG_PATH", source)
        self.assertIn("runConfig.run_instance.particle_count", source)
        self.assertIn("runConfig.inputs.candidate_particle_table", source)
        for forbidden in (
            "MassAmu=",
            "FineTimestepNs=",
            "AcceleratorMeshHmaxMm=",
            "DriftTimestepNs=",
            "SolverMode=",
            "FieldMode=",
        ):
            self.assertNotIn(forbidden, source)


    def test_stage_source_identity_does_not_invalidate_upstream_for_cad_only_change(self):
        closure = {
            "sources": [
                {
                    "source_id": "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_model_core.m",
                    "bytes": 1,
                    "sha256": "A" * 64,
                },
                {
                    "source_id": "projects/single_reflection_oa_tof_mass_analyzer/cad/export_oatof_cad_step.m",
                    "bytes": 1,
                    "sha256": "B" * 64,
                },
                {
                    "source_id": "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_stage_execution.py",
                    "bytes": 1,
                    "sha256": "C" * 64,
                },
            ]
        }
        closure["code_root"] = str(PROJECT_ROOT.parents[1])
        comsol = {
            path.relative_to(PROJECT_ROOT.parents[1]).as_posix()
            for path in _stage_source_paths(closure, "comsol_candidate")
        }
        simion = {
            path.relative_to(PROJECT_ROOT.parents[1]).as_posix()
            for path in _stage_source_paths(closure, "simion_candidate")
        }
        cad = {
            path.relative_to(PROJECT_ROOT.parents[1]).as_posix()
            for path in _stage_source_paths(closure, "cad_candidate")
        }
        cad_source = "projects/single_reflection_oa_tof_mass_analyzer/cad/export_oatof_cad_step.m"
        self.assertNotIn(cad_source, comsol)
        self.assertNotIn(cad_source, simion)
        self.assertIn(cad_source, cad)


    def _entry_preview_inputs(self, root):
        source = root / "source"
        source.mkdir()
        self.candidate_run_inputs(source)
        artifact = root / "artifacts"
        project = artifact / "projects" / PROJECT_ROOT.name
        registration = self.registered_template_run(project)
        runtime = root / "runtime.json"
        runtime.write_text(json.dumps({"role": "oa_tof_candidate_runtime",
            "simion_template_run_id": registration.name}), encoding="utf-8")
        return source, artifact, project, runtime

    def test_normal_cli_executes_the_same_completed_preview_without_repreparing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, artifact, project, runtime = self._entry_preview_inputs(root)
            argv = ["run_candidate", "--request", str(source / "design_request.json"),
                "--run-id", "20261031_201101__test__cross__preview-execute",
                "--particle-source-seed", "20260720"]
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_ARTIFACT_ROOT": str(artifact)}), \
                    mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime), \
                    mock.patch.object(sys, "argv", [*argv, "--dry-run"]), \
                    mock.patch.object(candidate_entry, "run_candidate_workflow") as execute:
                candidate_entry.main()
                execute.assert_not_called()
            paths = list((project / "scratch").glob("*__cross__candidate-plan-*/candidate_workflow_plan.json"))
            self.assertEqual(len(paths), 1)
            plan_path = paths[0]
            plan = load_json(plan_path)
            original = {p: p.read_bytes() for p in plan_path.parent.rglob("*") if p.is_file()}
            callbacks = []
            def execute(plan_argument, executable, **kwargs):
                self.assertEqual(plan_argument, plan_path)
                self.assertEqual(executable, str(Path(sys.executable).resolve()))
                self.assertFalse(Path(plan["run_root"]).exists())
                callbacks.append(plan_argument)
                return Path(plan["run_root"]), {"candidate_decision": "candidate_rejected"}
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_ARTIFACT_ROOT": str(artifact)}), \
                    mock.patch.object(sys, "argv", [*argv, "--simion-exe", sys.executable]), \
                    mock.patch.object(candidate_entry, "write_candidate", side_effect=AssertionError("must not recompile")), \
                    mock.patch.object(candidate_entry, "prepare_candidate_run", side_effect=AssertionError("must not reprepare")), \
                    mock.patch.object(candidate_entry, "validate_candidate_runtime", side_effect=AssertionError("must not reread live defaults")), \
                    mock.patch.object(candidate_entry, "run_candidate_workflow", side_effect=execute):
                candidate_entry.main()
            self.assertEqual(callbacks, [plan_path])
            self.assertEqual({p: p.read_bytes() for p in original}, original)
            self.assertFalse(Path(plan["run_root"]).exists())

    def test_completed_preview_rejects_changed_explicit_authorities_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, project, runtime = self._entry_preview_inputs(root)
            numerics = root / "explicit_numerics.json"
            numerics.write_bytes((PROJECT_ROOT / "config/formal_solver_numerics.json").read_bytes())
            campaign = root / "campaign.json"
            campaign.write_text('{"campaign_id":"fixture_campaign"}', encoding="utf-8")
            selection = root / "selection.json"
            run_id = "20261031_201102__test__cross__preview-authority"
            request = source / "design_request.json"
            proposal = source / "candidate_proposal.json"
            selection.write_text(json.dumps({"role": "oatof_campaign_selection", "campaign_id": "fixture_campaign",
                "campaign_run_id": "20261031_201100__test__cross__campaign", "experiment_id": "fixture",
                "candidate_run_id": run_id, "particle_source_seed": 20260720,
                "campaign_sha256": sha256(campaign), "request": {"path": str(request), "sha256": sha256(request)},
                "proposal": {"path": str(proposal), "sha256": sha256(proposal)}}), encoding="utf-8")
            arguments = dict(particle_source_seed=20260720, artifact_project_root=project,
                solver_numerics_contract=numerics, campaign_table=campaign, campaign_selection=selection)
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                plan_path = candidate_entry.prepare_execution(request, run_id, **arguments)
            before = {p: p.read_bytes() for p in plan_path.parent.rglob("*") if p.is_file()}
            originals = {p: p.read_bytes() for p in (request, proposal, numerics, campaign, selection)}
            for case in ("seed", "numerics", "omitted_numerics", "campaign", "omitted_campaign", "request", "proposal"):
                changed = dict(arguments)
                if case == "seed": changed["particle_source_seed"] += 1
                elif case == "omitted_numerics": changed["solver_numerics_contract"] = None
                elif case == "omitted_campaign": changed.update(campaign_table=None, campaign_selection=None)
                elif case in {"numerics", "campaign", "proposal"}:
                    path = {"numerics": numerics, "campaign": campaign, "proposal": proposal}[case]
                    path.write_bytes(originals[path] + b" ")
                else:
                    request.write_bytes(originals[request] + b" ")
                    document = load_json(proposal)
                    document["request"]["sha256"] = sha256(request)
                    proposal.write_text(json.dumps(document), encoding="utf-8")
                try:
                    with self.subTest(case=case), self.assertRaisesRegex(ValueError, "preview.*new run identity"):
                        candidate_entry.prepare_execution(request, run_id, **changed)
                finally:
                    for path, data in originals.items(): path.write_bytes(data)
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                self.assertFalse(Path(load_json(plan_path)["run_root"]).exists())

    def test_preview_preserves_frozen_defaults_and_rejects_incomplete_or_existing_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, project, runtime = self._entry_preview_inputs(root)
            request = source / "design_request.json"
            run_id = "20261031_201103__test__cross__preview-default"
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                plan_path = candidate_entry.prepare_execution(request, run_id, particle_source_seed=20260720,
                    artifact_project_root=project)
            before = plan_path.read_bytes()
            runtime.write_text("unreadable new live default", encoding="utf-8")
            with mock.patch.object(candidate_entry, "validate_candidate_runtime", side_effect=AssertionError("live default reinterpreted")):
                self.assertEqual(candidate_entry.prepare_execution(request, run_id, particle_source_seed=20260720,
                    artifact_project_root=project), plan_path)
            run = Path(load_json(plan_path)["run_root"])
            run.mkdir()
            marker = run / "existing.txt"
            marker.write_text("existing target must remain unchanged", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "candidate run already exists"):
                candidate_entry.prepare_execution(request, run_id, particle_source_seed=20260720, artifact_project_root=project)
            self.assertEqual(marker.read_text(), "existing target must remain unchanged")
            self.assertEqual(plan_path.read_bytes(), before)
            partial = project / "scratch" / ("20261031_201104__cross__candidate-entry-" + sha256(request)[:8].lower())
            contracts = partial / "candidate_contracts"
            contracts.mkdir(parents=True)
            sentinel = contracts / "partial.json"
            sentinel.write_text("incomplete", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete.*new run identity"):
                candidate_entry.prepare_execution(request, "20261031_201104__test__cross__preview-incomplete",
                    particle_source_seed=20260720, artifact_project_root=project)
            self.assertEqual(sentinel.read_text(), "incomplete")
            self.assertEqual(plan_path.read_bytes(), before)

    def test_single_candidate_entry_compiles_one_fixed_plan_without_commercial_tools(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(
                artifact_root,
                "20260727_102100__build__simion__candidate-layout-template-workspace",
            )
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                plan_path = candidate_entry.prepare_execution(
                    source / "design_request.json",
                    "20260727_171000__test__cross__single-entry-dry-run",
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                )
                second_plan_path = candidate_entry.prepare_execution(
                    source / "design_request.json",
                    "20260727_171001__test__cross__single-entry-dry-run",
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                )
            plan = load_json(plan_path)
            second_plan = load_json(second_plan_path)
            self.assertEqual(
                [stage["stage_id"] for stage in plan["stages"]],
                [
                    "static_inputs",
                    "comsol_candidate",
                    "simion_candidate",
                    "cad_candidate",
                    "structural_acceptance",
                ],
            )
            for name in (
                "candidate_baseline.json",
                "candidate_resolved_geometry.json",
                "candidate_solver_numerics.json",
                "candidate_diff.json",
            ):
                self.assertEqual(
                    plan["candidate_inputs"][name]["sha256"],
                    second_plan["candidate_inputs"][name]["sha256"],
                )
            self.assertFalse(Path(plan["run_root"]).exists())


    def test_campaign_table_and_selection_are_frozen_into_child_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact_root = (
                root_path
                / "artifacts"
                / "projects"
                / "single_reflection_oa_tof_mass_analyzer"
            )
            registration = self.registered_template_run(
                artifact_root,
                "20260727_102100__build__simion__candidate-layout-template-workspace",
            )
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            run_id = "20260731_232000__test__cross__campaign-child"
            campaign = root_path / "experiment_campaign.json"
            campaign.write_text(
                json.dumps({"campaign_id": "fixture_campaign"}), encoding="utf-8"
            )
            selection = root_path / "campaign_selection.json"
            selection.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "oatof_campaign_selection",
                        "campaign_id": "fixture_campaign",
                        "campaign_run_id": "20260731_231900__test__cross__campaign-parent",
                        "experiment_id": "fixture_row",
                        "candidate_run_id": run_id,
                        "particle_source_seed": 20260720,
                        "campaign_sha256": sha256(campaign),
                        "request": {
                            "path": str(source / "design_request.json"),
                            "sha256": sha256(source / "design_request.json"),
                        },
                        "proposal": {
                            "path": str(source / "candidate_proposal.json"),
                            "sha256": sha256(source / "candidate_proposal.json"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                plan_path = candidate_entry.prepare_execution(
                    source / "design_request.json",
                    run_id,
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                    campaign_table=campaign,
                    campaign_selection=selection,
                )
            plan = load_json(plan_path)
            self.assertEqual(plan["campaign_binding"]["experiment_id"], "fixture_row")
            self.assertIn("experiment_campaign", plan["candidate_inputs"])
            self.assertIn("campaign_selection", plan["candidate_inputs"])
            child_root = start_candidate_run(plan_path)
            manifest = load_json(child_root / "run_manifest.json")
            self.assertEqual(
                manifest["campaign_binding"]["campaign_sha256"], sha256(campaign)
            )
            self.assertEqual(
                manifest["inputs"]["campaign_selection"]["sha256"],
                plan["campaign_binding"]["selection_sha256"],
            )


    def test_candidate_template_requires_successful_registered_template_build_run(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(artifact_root)
            record = _registered_candidate_template(registration, artifact_root)
            self.assertEqual(record["source_iob"].name, "layout.iob")
            failed = load_json(registration / "summary.json")
            failed["status"] = "failed"
            (registration / "summary.json").write_text(json.dumps(failed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a successful structure-only"):
                _registered_candidate_template(registration, artifact_root)


    def test_candidate_template_accepts_equivalent_noncanonical_manifest_path(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(artifact_root)
            manifest_path = registration / "run_manifest.json"
            manifest = load_json(manifest_path)
            source_iob = Path(manifest["inputs"]["source_iob"]["path"])
            spelling_anchor = source_iob.parent / "equivalent_spelling"
            spelling_anchor.mkdir()
            manifest["inputs"]["source_iob"]["path"] = str(
                spelling_anchor / ".." / source_iob.name
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            record = _registered_candidate_template(registration, artifact_root)
            self.assertEqual(record["source_iob"], source_iob.resolve())


    def test_candidate_template_reports_manifest_hash_mismatch_by_field(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(artifact_root)
            manifest_path = registration / "run_manifest.json"
            manifest = load_json(manifest_path)
            manifest["inputs"]["source_iob"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest SHA-256 differs: source_iob"):
                _registered_candidate_template(registration, artifact_root)


    def test_candidate_prepare_freezes_only_registered_template_sources(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(artifact_root)
            candidate_inputs = root_path / "candidate_inputs"
            candidate_inputs.mkdir()
            inputs = self.candidate_run_inputs(candidate_inputs)
            plan = prepare_candidate_run(
                *inputs,
                "20260726_121000__build__cross__design-candidate__zero-change",
                artifact_root,
                particle_source_seed=20260713,
                simion_template_run=registration,
            )
            self.assertEqual(plan["status"], "EXECUTION_READY")
            stage = next(item for item in plan["stages"] if item["stage_id"] == "simion_candidate")
            self.assertEqual(stage["status"], "ready")
            acceptance = next(
                item for item in plan["stages"]
                if item["stage_id"] == "structural_acceptance"
            )
            self.assertEqual(acceptance["status"], "ready")
            self.assertEqual(stage["template_input"]["role"], "oa_tof_candidate_simion_layout_template")
            self.assertTrue(Path(stage["template_input"]["files"]["iob"]["path"]).is_file())
            self.assertTrue(Path(stage["template_input"]["files"]["con"]["path"]).is_file())
            from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
            observe = preparation.run_observed_process
            payload = b"discarded compiler header\n" + b"x" * 6000 + "\nRuntimeError: 实际编译失败\n".encode()

            def fail_compiler(_command, **kwargs):
                # Exercise the same public observer and real stderr transport;
                # this deliberate Python failure is not a solver result.
                return observe([sys.executable, "-c",
                    f"import sys;sys.stderr.buffer.write({payload!r});sys.exit(17)"], **kwargs)

            with mock.patch.object(preparation, "run_observed_process", side_effect=fail_compiler):
                with self.assertRaises(ValueError) as failed:
                    prepare_candidate_run(*inputs,
                        "20260726_121001__build__cross__design-candidate__compiler-failure", artifact_root,
                        particle_source_seed=20260713, simion_template_run=registration)
            message = str(failed.exception)
            self.assertIn("exit_code=17", message)
            self.assertIn("prepare_consumers.stderr.log", message)
            detail = message.split("stderr_tail=\n", 1)[1]
            self.assertEqual(detail, payload[-4096:].decode("utf-8"))
            self.assertNotIn("discarded compiler header", detail)
            self.assertIn("RuntimeError: 实际编译失败", detail)


    def test_candidate_workflow_rejects_missing_template_before_run_start(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            source = root_path / "candidate_inputs"
            source.mkdir()
            plan = prepare_candidate_run(
                *self.candidate_run_inputs(source),
                "20260726_121001__build__cross__design-candidate__missing-template",
                artifact_root,
                particle_source_seed=20260713,
            )
            plan_path = Path(plan["planning_root"]) / "candidate_workflow_plan.json"
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow.start_candidate_run"
            ) as start:
                with self.assertRaisesRegex(
                    ValueError, "not execution-ready: NEEDS_RUNTIME_INPUTS"
                ):
                    run_candidate_workflow(plan_path, "unused")
            start.assert_not_called()
            self.assertFalse(Path(plan["run_root"]).exists())


    def test_template_registration_is_structure_only_and_rejects_prohibited_sources(self):
        script = (PROJECT_ROOT / "simion" / "workbench" / "register_candidate_layout_template.ps1").read_text(encoding="utf-8")
        for token in (
            "SourceIobPath", "SourceConPath", "oa_tof_simion_candidate_layout_template_build",
            "-TemplateStructureOnly", "formal', 'archive', 'history", "particle_fly_executed = $false",
        ):
            self.assertIn(token, script)
        self.assertNotIn("Copy-Item", script)
        self.assertNotIn(" --nogui fly", script)


    def test_candidate_inputs_cannot_come_from_formal_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root = Path(root) / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            formal = artifact_root / "formal" / "inputs"
            formal.mkdir(parents=True)
            inputs = self.candidate_run_inputs(formal)
            with self.assertRaisesRegex(ValueError, "must not be sourced from formal"):
                prepare_candidate_run(
                    *inputs, "20260720_120001__build__cross__design-candidate__formal-source",
                    artifact_root, particle_source_seed=20260713,
                )


    def test_workflow_rejects_automatic_promotion(self):
        workflow = load_json(PROJECT_ROOT / "config" / "candidate_workflow.json")
        workflow["formal_policy"]["automatic_promotion"] = True
        with self.assertRaisesRegex(ValueError, "disable automatic promotion"):
            validate_workflow(workflow)


    def test_candidate_baseline_and_resolved_hashes_must_match(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            inputs[0].write_text(inputs[0].read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hashes do not match"):
                prepare_candidate_run(
                    *inputs, "20260720_120002__build__cross__design-candidate__hash-mismatch",
                    root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer",
                    particle_source_seed=20260713,
                )


    def test_materialized_run_is_always_layout_complete_and_success_is_not_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, run_root, plan = self.materialize_candidate_run(Path(root))
            initial = load_json(run_root / "summary.json")
            self.assertEqual(initial["status"], "interrupted")
            self.assertEqual(verify_project(artifact_root), (1, 0))
            summary, manifest = finalize_candidate_run(run_root, "success", self.stage_results(plan))
            self.assertEqual(summary["candidate_decision"], "candidate_accepted_not_promoted")
            self.assertFalse(summary["formal_modified"])
            self.assertFalse(summary["safe_to_promote"])
            self.assertFalse(manifest["formal_eligible"])
            self.assertEqual(
                set(manifest["inputs"]),
                {"candidate_baseline.json", "candidate_resolved_geometry.json", "candidate_solver_numerics.json", "candidate_diff.json", "candidate_analysis_contract.json",
                 "candidate_proposal.json", "design_request.json", "candidate_runtime.json",
                 "candidate_simion_resolved_lua", "candidate_simion_program", "candidate_simion_fly2"},
            )
            self.assertEqual(manifest["inputs"]["candidate_analysis_contract.json"]["sha256"],
                             plan["candidate_inputs"]["candidate_analysis_contract.json"]["sha256"])
            self.assertEqual(verify_project(artifact_root), (1, 0))


    def test_candidate_proposal_and_request_cannot_change_before_planning(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            inputs = self.candidate_run_inputs(root_path)
            proposal = root_path / "candidate_proposal.json"
            proposal.write_text(proposal.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "proposal provenance is missing or changed"):
                prepare_candidate_run(
                    *inputs, "20260720_130005__build__cross__design-candidate__provenance-tamper",
                    root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer",
                    particle_source_seed=20260713,
                )


    def test_failed_and_interrupted_runs_close_with_complete_root_records(self):
        cases = (("failed", "comsol_candidate", "20260720_130001"),
                 ("interrupted", "simion_candidate", "20260720_130002"))
        for status, failure_stage, stamp in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as root:
                artifact_root, run_root, plan = self.materialize_candidate_run(Path(root), stamp)
                stage_status = "failed" if status == "failed" else "interrupted"
                summary, manifest = finalize_candidate_run(
                    run_root, status, self.stage_results(plan, stage_status, failure_stage), failure_stage
                )
                self.assertEqual(summary["status"], status)
                self.assertEqual(summary["candidate_decision"], "no_candidate_decision")
                self.assertEqual(manifest["status"], status)
                self.assertTrue((run_root / "run_config.json").is_file())
                self.assertTrue((run_root / "summary.json").is_file())
                self.assertTrue((run_root / "run_manifest.json").is_file())
                self.assertEqual(verify_project(artifact_root), (1, 0))


    def test_terminal_publication_replays_summary_crash_on_finalize_retry(self):
        with tempfile.TemporaryDirectory() as root:
            _, run_root, plan = self.materialize_candidate_run(Path(root))
            original = terminal_publication.write_json_atomic

            def crash_after_summary(path, value):
                original(path, value)
                if path.name == "summary.json":
                    raise RuntimeError("injected summary crash")

            with (
                mock.patch.object(
                    terminal_publication,
                    "write_json_atomic",
                    crash_after_summary,
                ),
                self.assertRaisesRegex(RuntimeError, "injected summary crash"),
            ):
                finalize_candidate_run(run_root, "success", self.stage_results(plan))
            summary, manifest = finalize_candidate_run(
                run_root, "success", self.stage_results(plan)
            )
            self.assertEqual(summary["status"], manifest["status"])
            self.assertFalse(
                (run_root / terminal_publication.TERMINAL_JOURNAL_NAME).exists()
            )


    def test_planned_inputs_cannot_change_before_atomic_run_start(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            source = root_path / "source"
            source.mkdir()
            inputs = self.candidate_run_inputs(source)
            plan = prepare_candidate_run(
                *inputs, "20260720_130003__build__cross__design-candidate__tamper",
                artifact_root, particle_source_seed=20260713,
            )
            planning_root = Path(plan["planning_root"])
            frozen_baseline = planning_root / "inputs" / "candidate_baseline.json"
            frozen_baseline.write_text(frozen_baseline.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed before run start"):
                start_candidate_run(planning_root / "candidate_workflow_plan.json")
            self.assertFalse(Path(plan["run_root"]).exists())


    def test_prepared_solver_text_cannot_change_before_atomic_run_start(self):
        for index, name in enumerate(("oatof_resolved.lua", "oatof_ideal_grounded.lua", "oatof_ideal_grounded.fly2")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                root_path = Path(root)
                artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
                source = root_path / "source"
                source.mkdir()
                inputs = self.candidate_run_inputs(source)
                plan = prepare_candidate_run(
                    *inputs, f"20260720_13000{index + 4}__build__cross__design-candidate__text-tamper",
                    artifact_root, particle_source_seed=20260713,
                )
                planning_root = Path(plan["planning_root"])
                program = planning_root / "inputs" / "prepared_consumers" / "simion" / name
                program.write_text(program.read_text(encoding="utf-8") + "-- changed\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "changed before run start"):
                    start_candidate_run(planning_root / "candidate_workflow_plan.json")
                self.assertFalse(Path(plan["run_root"]).exists())


    def test_frozen_candidate_source_tamper_blocks_start_and_extra_files(self):
        cases = ("modified", "extra")
        for index, case in enumerate(cases):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as root:
                root_path = Path(root)
                artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
                source = root_path / "source"
                source.mkdir()
                plan = prepare_candidate_run(
                    *self.candidate_run_inputs(source),
                    f"20260720_13001{index}__build__cross__design-candidate__source-{case}",
                    artifact_root,
                    particle_source_seed=20260713,
                )
                planning_root = Path(plan["planning_root"])
                code_root = Path(plan["execution_source_closure"]["code_root"])
                if case == "modified":
                    target = code_root / "common" / "require_powershell7.ps1"
                    target.write_text(
                        target.read_text(encoding="utf-8") + "\n# tampered\n",
                        encoding="utf-8",
                    )
                else:
                    (code_root / "undeclared.py").write_text(
                        "raise RuntimeError('undeclared')\n", encoding="utf-8"
                    )
                with self.assertRaisesRegex(
                    ValueError, "frozen candidate source changed|missing or extra"
                ):
                    start_candidate_run(
                        planning_root / "candidate_workflow_plan.json"
                    )
                self.assertFalse(Path(plan["run_root"]).exists())


    def test_frozen_candidate_source_tamper_blocks_stage_and_finalize(self):
        with tempfile.TemporaryDirectory() as root:
            _, run_root, plan = self.materialize_candidate_run(Path(root))
            runtime_plan = load_json(run_root / "candidate_workflow_plan.json")
            code_root = Path(
                runtime_plan["execution_source_closure"]["code_root"]
            )
            target = code_root / "common" / "require_powershell7.ps1"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n# tampered\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "frozen candidate source changed"
            ):
                execute_stage(runtime_plan["stages"][0], runtime_plan, "unused")
            with self.assertRaisesRegex(
                ValueError, "frozen candidate source changed"
            ):
                finalize_candidate_run(
                    run_root, "success", self.stage_results(plan)
                )


    def test_integrated_runner_success_closes_one_root_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.native_workflow_plan(
                Path(root), "20260720_140000"
            )
            observed = []

            def fake_executor(stage, plan, _simion):
                observed.append(stage["stage_id"])
                if stage["stage_id"] == "static_inputs":
                    particle = Path(stage["pending_output"])
                    particle.write_text("particle\n", encoding="utf-8")
                evidence_path = Path(plan["run_root"]) / "results" / f"{stage['stage_id']}.txt"
                evidence_path.write_text("STATUS=PASS\n", encoding="utf-8")
                evidence = {"report": str(evidence_path)}
                if stage["stage_id"] == "comsol_candidate":
                    model = Path(plan["run_root"]) / "comsol" / "candidate.mph"
                    model.write_text("candidate model\n", encoding="utf-8")
                    evidence["model"] = str(model)
                return evidence

            run_root, summary = run_candidate_workflow(
                plan_path, sys.executable, stage_executor=fake_executor
            )
            expected = ["static_inputs", "comsol_candidate", "simion_candidate", "cad_candidate", "structural_acceptance"]
            self.assertEqual(observed, expected)
            self.assertEqual([item["stage_id"] for item in summary["stages"]], expected)
            self.assertEqual(summary["acceptance_scope"], "structural_build_and_contract")
            self.assertFalse(summary["performance_claim_allowed"])
            self.assertEqual(verify_project(artifact_root), (2, 0))
            self.assertEqual(load_json(run_root / "run_manifest.json")["status"], "success")


    def test_integrated_runner_terminal_faults_close_remaining_stages(self):
        cases = (("failed", "simion_candidate", CandidateWorkflowError, "20260720_140001"),
                 ("interrupted", "cad_candidate", CandidateWorkflowInterrupted, "20260720_140002"),
                 ("timeout", "comsol_candidate", CandidateWorkflowTimedOut, "20260720_140003"))
        for outcome, stop_stage, exception_type, stamp in cases:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as root:
                artifact_root, plan_path = self.native_workflow_plan(
                    Path(root), stamp
                )

                def fake_executor(stage, plan, _simion):
                    if stage["stage_id"] == stop_stage:
                        if outcome == "interrupted":
                            raise KeyboardInterrupt("test interruption")
                        if outcome == "timeout":
                            raise StageTimedOut("test timeout")
                        raise RuntimeError("test failure")
                    if stage["stage_id"] == "static_inputs":
                        Path(stage["pending_output"]).write_text(
                            "particle\n", encoding="utf-8"
                        )
                    evidence_path = (
                        Path(plan["run_root"])
                        / "results"
                        / f"{stage['stage_id']}.txt"
                    )
                    evidence_path.write_text("STATUS=PASS\n", encoding="utf-8")
                    evidence = {"report": str(evidence_path)}
                    if stage["stage_id"] == "comsol_candidate":
                        model = Path(plan["run_root"]) / "comsol" / "candidate.mph"
                        model.write_text("candidate model\n", encoding="utf-8")
                        evidence["model"] = str(model)
                    return evidence

                with self.assertRaises(exception_type) as caught:
                    run_candidate_workflow(
                        plan_path, sys.executable, stage_executor=fake_executor
                    )
                run_root = caught.exception.run_root
                summary = load_json(run_root / "summary.json")
                expected_status = "failed" if outcome == "timeout" else outcome
                self.assertEqual(summary["status"], expected_status)
                self.assertEqual(summary["failure_stage"], stop_stage)
                statuses = {item["stage_id"]: item["status"] for item in summary["stages"]}
                self.assertEqual(statuses[stop_stage], expected_status)
                if outcome == "timeout":
                    failed_stage = next(
                        item for item in summary["stages"]
                        if item["stage_id"] == stop_stage
                    )
                    self.assertEqual(failed_stage["failure_class"], "timeout")
                later = False
                for item in summary["stages"]:
                    if later:
                        self.assertEqual(item["status"], "blocked")
                    later = later or item["stage_id"] == stop_stage
                self.assertEqual(verify_project(artifact_root), (2, 0))


    def test_cross_acceptance_requires_identical_candidate_particle_tables(self):
        with tempfile.TemporaryDirectory() as root:
            run_root = Path(root)
            files = {}
            for name in (
                "particle_table", "model", "sync_report", "iob", "ion_n100", "stage_summary",
                "runtime_report", "transport_diagnostics", "cad_report", "analysis_request", "analysis_receipt",
            ):
                path = run_root / f"{name}.dat"
                content = "\n".join(["same particle table"] * 100) if name in ("particle_table", "ion_n100") else "evidence"
                path.write_text(content, encoding="utf-8")
                files[name] = str(path)
            particle_csv = run_root / "simion_particles.csv"
            particle_csv.write_text("Ion\n" + "\n".join(str(index) for index in range(1, 101)) + "\n", encoding="utf-8")
            transport_summary = run_root / "simion_transport_summary.json"
            transport_summary.write_text(json.dumps({
                "status": "success", "expected_particle_count": 100, "trajectory_quality": 8,
                "emitted": 100, "crossed": 100, "hit": 100,
                "ion": {"sha256": sha256(Path(files["ion_n100"]))},
                "particle_csv": {"sha256": sha256(particle_csv)},
            }), encoding="utf-8")
            files["particle_csv"] = str(particle_csv)
            files["transport_summary"] = str(transport_summary)
            plan = {
                "run_root": str(run_root),
                "stage_results_so_far": [
                    {"stage_id": "static_inputs", "evidence": {"particle_table": files["particle_table"]}},
                    {"stage_id": "comsol_candidate", "evidence": {
                        "model": files["model"], "sync_report": files["sync_report"],
                        "analysis_request": files["analysis_request"], "analysis_receipt": files["analysis_receipt"],
                    }},
                    {"stage_id": "simion_candidate", "evidence": {
                        "iob": files["iob"], "ion_n100": files["ion_n100"], "stage_summary": files["stage_summary"],
                        "runtime_report": files["runtime_report"], "transport_summary": files["transport_summary"],
                        "particle_csv": files["particle_csv"], "transport_diagnostics": files["transport_diagnostics"],
                    }},
                    {"stage_id": "cad_candidate", "evidence": {"cad_report": files["cad_report"]}},
                ],
            }
            stage = {
                "stage_id": "structural_acceptance", "output_dir": str(run_root / "results"),
                "acceptance_scope": "structural_build_and_contract", "performance_claim_allowed": False,
            }
            evidence = execute_stage(stage, plan, "unused")
            acceptance = load_json(Path(evidence["acceptance"]))
            self.assertEqual(acceptance["scope"], "structural_build_and_contract")
            self.assertTrue(acceptance["shared_particle_table_sha256"])
            self.assertEqual(acceptance["comsol_simion_particle_level_comparison"], "not_run")
            particle_csv.write_text("Ion\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "transport evidence is incomplete or changed"):
                execute_stage(stage, plan, "unused")
            particle_csv.write_text(
                "Ion\n" + "\n".join(str(index) for index in range(1, 101)) + "\n", encoding="utf-8"
            )
            Path(files["ion_n100"]).write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "particle tables differ"):
                execute_stage(stage, plan, "unused")


    def test_candidate_source_closure_freezes_shared_n100_transport_mechanism(self):
        required = {
            "common/comsol/add_comsol_size_feature.m",
            "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_n100_transport.ps1",
            "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1",
            "projects/single_reflection_oa_tof_mass_analyzer/analysis/solver_diagnostics.py",
        }
        self.assertTrue(required.issubset(set(RELATIVE_PATHS)))
        self.assertIn("projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1", PYTHON_BOUND_SOURCES)


    def test_functional_comsol_runner_uses_short_lived_execution_alias(self):
        runner = (PROJECT_ROOT / "tests/comsol/run_n100_candidate_functional.ps1").read_text(encoding="utf-8")
        self.assertIn("-UseShortExecutionPath", runner)
        self.assertIn("Remove-RunPackageExecutionAlias -Package $package", runner)
        self.assertIn("-CapacityLedgerLifecycleEnabled", runner)
        self.assertIn("Apply-RunArtifactRetention", runner)
        self.assertIn("Write-VerifiedRunManifest", runner)


    def test_simion_candidate_requires_explicit_nonformal_frozen_template_before_builder(self):
        with tempfile.TemporaryDirectory() as root:
            run_root = Path(root)
            stage = {"stage_id": "simion_candidate", "status": "blocked_requires_explicit_nonformal_template"}
            with mock.patch("projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command") as command:
                with self.assertRaisesRegex(RuntimeError, "blocked until an explicit non-Formal template"):
                    execute_stage(stage, {"run_root": str(run_root), "execution_source_closure": {}}, "unused")
            command.assert_not_called()

            formal = run_root / "inputs" / "formal" / "layout.iob"
            formal.parent.mkdir(parents=True)
            formal.write_bytes(b"template")
            stage["status"] = "ready"
            stage["template_input"] = {
                "role": "oa_tof_candidate_simion_layout_template",
                "files": {
                    "iob": {"path": str(formal), "sha256": sha256(formal)},
                    "con": {"path": str(formal.with_suffix('.con')), "sha256": "missing"},
                },
            }
            with self.assertRaisesRegex(RuntimeError, "must not reference a Formal, archive, or history path"):
                execute_stage(stage, {"run_root": str(run_root)}, "unused")

            template = run_root / "inputs" / "simion_template" / "layout.iob"
            template.parent.mkdir(parents=True)
            template.write_bytes(b"template")
            template.with_suffix(".con").write_bytes(b"template-con")
            stage["template_input"] = {
                "role": "oa_tof_candidate_simion_layout_template",
                "files": {
                    "iob": {"path": str(template), "sha256": sha256(template)},
                    "con": {"path": str(template.with_suffix('.con')), "sha256": sha256(template.with_suffix('.con'))},
                },
            }
            with self.assertRaisesRegex(ValueError, "invalid candidate source closure"):
                execute_stage(stage, {"run_root": str(run_root), "execution_source_closure": {}}, "unused")


    def test_formal_asset_entrypoints_preflight_before_paths_or_runs(self):
        scripts = [
            PROJECT_ROOT / "workflows" / "formal_reference" / "verify_geometry_contract.ps1",
            PROJECT_ROOT / "workflows" / "mass_spectrum_candidate" / "run_mass_spectrum_candidate.ps1",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            preflight = text.index("Assert-OaTofFormalAssetsReadable")
            first_asset = min(index for index in (text.find("formal\\"), text.find("New-Item -ItemType Directory")) if index >= 0)
            self.assertLess(preflight, first_asset, script.name)

        formal_cli = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "run_formal_validation.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("-Phase Verify", formal_cli)
        validate_branch = formal_cli[formal_cli.index("$candidateRoot =") :]
        self.assertNotIn("Assert-OaTofFormalAssetsReadable", validate_branch)


    def test_shared_builder_requires_explicit_seed_and_candidate_template(self):
        builder = (PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1").read_text(encoding="utf-8")
        self.assertIn("ParticleSeed is required", builder)
        self.assertIn("Candidate build requires an explicit frozen non-Formal TemplateIob", builder)
        self.assertIn("Candidate TemplateIob must not reference a Formal path", builder)


    def test_frozen_candidate_builder_receives_runtime_artifact_root(self):
        builder = (PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1").read_text(encoding="utf-8")
        self.assertIn("[string]$ArtifactProjectRoot = ''", builder)
        self.assertIn("$artifactRoot = [IO.Path]::GetFullPath($ArtifactProjectRoot)", builder)
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            artifact_root.mkdir(parents=True)
            template_run = self.registered_template_run(artifact_root)
            source = root_path / "candidate_inputs"
            source.mkdir()
            plan = prepare_candidate_run(
                *self.candidate_run_inputs(source),
                "20260727_110000__build__cross__design-candidate__frozen-builder-root",
                artifact_root,
                particle_source_seed=20260713,
                simion_template_run=template_run,
            )
            run_root = start_candidate_run(Path(plan["planning_root"]) / "candidate_workflow_plan.json")
            runtime_plan = load_json(run_root / "candidate_workflow_plan.json")
            runtime_plan.update(capacity_session_path=str(run_root / "logs/capacity_session.json"),
                                component_plan_path=str(run_root / "inputs/component_pa_plan.json"),
                                producer_handoff_path=str(run_root / "inputs/pa_producer_handoffs/handoffs.json"),
                                context_sha256="a" * 64)
            stage = next(item for item in runtime_plan["stages"] if item["stage_id"] == "simion_candidate")
            commands = []

            def stop_after_capturing_command(command, _log_path, _environment=None):
                commands.append(command)
                raise RuntimeError("intentional command capture")

            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command",
                side_effect=stop_after_capturing_command,
            ):
                with self.assertRaisesRegex(RuntimeError, "intentional command capture"):
                    execute_stage(stage, runtime_plan, "unused")

            command = commands[0]
            frozen_builder = Path(command[5]).resolve()
            frozen_builder.relative_to(run_root / "inputs" / "code")
            root_argument = command.index("-ArtifactProjectRoot") + 1
            self.assertEqual(Path(command[root_argument]).resolve(), artifact_root.resolve())
            for name, key in (("CapacitySessionPath", "capacity_session_path"),
                              ("ComponentPlanPath", "component_plan_path"), ("ContextSha256", "context_sha256"),
                              ("ProducerHandoffPath", "producer_handoff_path")):
                self.assertEqual(command[command.index("-" + name) + 1], runtime_plan[key])
            self.assertEqual(command[command.index("-ParticleCount") + 1], "100")


    def test_shared_builder_negative_contracts_fail_before_output_creation(self):
        builder = PROJECT_ROOT / "simion" / "workbench" / "build_formal_delivery.ps1"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            contract = root_path / "candidate.json"
            baseline = root_path / "candidate_baseline.json"
            text_dir = root_path / "candidate_text"
            contract.write_text("{}", encoding="utf-8")
            baseline.write_text("{}", encoding="utf-8")
            text_dir.mkdir()
            shared = ["-ContractPath", str(contract), "-CandidateBaselinePath", str(baseline), "-CandidateTextDir", str(text_dir)]
            nonformal_template = root_path / "candidate_template.iob"
            nonformal_template.write_bytes(b"template")
            cases = [
                (shared + ["-TemplateIob", str(nonformal_template)], "ParticleSeed is required", True),
                (shared + ["-ParticleSeed", "7"], "Candidate build requires an explicit frozen non-Formal TemplateIob", True),
                (shared + ["-ParticleSeed", "7", "-TemplateIob", str(root_path / "formal_template.iob")], "Candidate TemplateIob must not reference a Formal path", True),
                (shared + ["-ParticleSeed", "7", "-TemplateIob", str(nonformal_template)],
                 "PA construction requires the managed Candidate workflow and its existing capacity session", False),
            ]
            for ordinal, (arguments, expected, deferred) in enumerate(cases):
                output = root_path / f"output_{ordinal}"
                artifact_project = root_path / "artifacts/projects/single_reflection_oa_tof_mass_analyzer"
                run_id = f"20261028_14000{ordinal}__test__simion__negative-builder"
                completion = artifact_project / "runs" / run_id / "logs/build_completion.json"
                completion.parent.mkdir(parents=True)
                managed = ["-ArtifactProjectRoot", str(artifact_project), "-RunId", run_id,
                    "-CapacitySessionPath", str(root_path / "absent_session.json"),
                    "-ComponentPlanPath", str(root_path / "absent_plan.json"),
                    "-CompletionPath", str(completion), "-ContextSha256", "a" * 64,
                    "-ParticleCount", "100"]
                if deferred:
                    managed.append("-DeferRunFinalization")
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-File", str(builder), "-OutputDir", str(output), *managed, *arguments],
                    cwd=REPO_ROOT, capture_output=True, timeout=20,
                )
                self.assertNotEqual(result.returncode, 0)
                text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
                self.assertIn(expected, text)
                self.assertFalse(output.exists())


    def test_integrated_runner_uses_powershell_7(self):
        command = _powershell("task.ps1", ["-Value", "test"])
        self.assertEqual(command[0], "pwsh.exe")
        self.assertEqual(command[-3:], ["task.ps1", "-Value", "test"])


    def test_comsol_stage_uses_only_frozen_launcher_and_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root, plan_path = self.prepared_workflow_plan(
                root_path, "20260720_145000"
            )
            plan = load_json(plan_path)
            plan["context_sha256"] = sha256(plan_path)
            stage = next(
                item
                for item in plan["stages"]
                if item["stage_id"] == "comsol_candidate"
            )
            observed = []
            environments = []

            def fake_run(command, _log_path, _environment=None):
                observed.append(command)
                environments.append(_environment)
                if "-ReportPath" in command:
                    report = Path(command[command.index("-ReportPath") + 1])
                    report.parent.mkdir(parents=True, exist_ok=True)
                    task = command[command.index("-TaskScript") + 1]
                    if task.endswith("run_candidate_contract_build.m"):
                        request = report.parent / "analysis_request.json"
                        analysis_dir = report.parent / "analysis"
                        request.write_text(json.dumps({"analysis_output_dir": str(analysis_dir)}), encoding="utf-8")
                        report.write_text(
                            f"PYTHON_ANALYSIS_REQUEST={request}\nSTATUS=PASS\n", encoding="utf-8"
                        )
                    else:
                        report.write_text("STATUS=PASS\n", encoding="utf-8")
                else:
                    request = Path(command[-1])
                    analysis_dir = Path(json.loads(request.read_text(encoding="utf-8"))["analysis_output_dir"])
                    analysis_dir.mkdir(parents=True, exist_ok=True)
                    (analysis_dir / "analysis_receipt.json").write_text("{}", encoding="utf-8")

            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._verify_frozen_cad_python",
                return_value=plan["execution_source_closure"]["runtime"]["python_executable"],
            ), mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command",
                side_effect=fake_run,
            ), mock.patch.object(candidate_workflow, "append_native_stage_completion",
                                 wraps=candidate_workflow.append_native_stage_completion) as completion:
                execute_stage(stage, plan, "unused")
            self.assertEqual(completion.call_count, 2)
            self.assertEqual([call.kwargs["context_sha256"] for call in completion.call_args_list],
                             [sha256(plan_path)] * 2)

            code_root = Path(plan["execution_source_closure"]["code_root"])
            self.assertEqual(len(observed), 3)
            self.assertEqual(environments[0]["OATOF_CANDIDATE_ARTIFACT_ROOT"], str(artifact_root.parents[1]))
            commercial_commands = [command for command in observed if "-TaskScript" in command]
            self.assertEqual(len(commercial_commands), 2)
            for command in commercial_commands:
                Path(command[5]).resolve().relative_to(code_root.resolve())
                task_index = command.index("-TaskScript") + 1
                Path(command[task_index]).resolve().relative_to(
                    code_root.resolve()
                )
            self.assertEqual(
                {Path(command[5]).resolve() for command in commercial_commands},
                {
                    (
                        code_root
                        / "common"
                        / "comsol"
                        / "run_comsol_r2025b.ps1"
                    ).resolve()
                },
            )
            self.assertTrue(artifact_root.is_dir())


    def test_cad_stage_passes_the_same_verified_runtime_artifact_context(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.prepared_workflow_plan(Path(root), "20260720_145001")
            plan = load_json(plan_path)
            plan["context_sha256"] = sha256(plan_path)
            stage = next(item for item in plan["stages"] if item["stage_id"] == "cad_candidate")
            environments = []

            def fake_run(command, _log_path, environment):
                environments.append(environment)
                report = Path(command[command.index("-ReportPath") + 1])
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text("STATUS=PASS\n", encoding="utf-8")
                output = Path(stage["output_dir"])
                output.mkdir(parents=True, exist_ok=True)
                (output / "oaTOF_solidworks_export_report.json").write_text("{}", encoding="utf-8")

            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command",
                side_effect=fake_run,
            ), mock.patch.object(candidate_workflow, "append_native_stage_completion",
                                 wraps=candidate_workflow.append_native_stage_completion) as completion:
                execute_stage(stage, plan, "unused")
            self.assertEqual(completion.call_count, 1)
            self.assertEqual([call.kwargs["context_sha256"] for call in completion.call_args_list],
                             [sha256(plan_path)] * 1)
            self.assertEqual(environments[0]["OATOF_CANDIDATE_ARTIFACT_ROOT"], str(artifact_root.parents[1]))


    def test_cad_python_preflight_blocks_comsol_before_commercial_launcher(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.prepared_workflow_plan(Path(root), "20260727_131000")
            plan = load_json(plan_path)
            stage = next(item for item in plan["stages"] if item["stage_id"] == "comsol_candidate")
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._verify_frozen_cad_python",
                side_effect=RuntimeError("candidate CAD Python runtime preflight failed"),
            ), mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow._run_command"
            ) as commercial_launcher:
                with self.assertRaisesRegex(RuntimeError, "CAD Python runtime preflight failed"):
                    execute_stage(stage, plan, "unused")
            commercial_launcher.assert_not_called()
            self.assertTrue(artifact_root.is_dir())


    def test_cad_python_preflight_reports_missing_pywin32(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            runtime = root_path / "python.exe"
            runtime.write_bytes(b"frozen runtime")
            closure = {"runtime": {"python_executable": str(runtime)}}
            failed = subprocess.CompletedProcess(
                [str(runtime), "-c", "unused"], 1, stdout="", stderr="ModuleNotFoundError: pythoncom"
            )
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow.subprocess.run",
                return_value=failed,
            ) as command:
                with self.assertRaisesRegex(RuntimeError, "cannot import pythoncom and win32com.client"):
                    _verify_frozen_cad_python(closure, root_path / "preflight.log")
            self.assertEqual(command.call_args.args[0][0], str(runtime.resolve()))
            self.assertIn("pythoncom", (root_path / "preflight.log").read_text(encoding="utf-8"))


    def test_command_runner_merges_environment_without_name_error(self):
        with tempfile.TemporaryDirectory() as root:
            log_path = Path(root) / "command.log"
            process = mock.Mock()
            process.poll.return_value = 0
            process.returncode = 0
            with mock.patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow.subprocess.Popen",
                return_value=process,
            ) as command:
                _run_command(["unused"], log_path, {"OATOF_TEST_ENVIRONMENT": "present"})
            self.assertEqual(command.call_args.kwargs["env"]["OATOF_TEST_ENVIRONMENT"], "present")


    def test_command_runner_warns_without_terminating_a_long_running_stage(self):
        with tempfile.TemporaryDirectory() as root:
            log_path = Path(root) / "command.log"
            process = mock.Mock(pid=12345, returncode=0)
            process.poll.side_effect = (None, 0)
            module = "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow"
            with mock.patch(f"{module}.subprocess.Popen", return_value=process), \
                 mock.patch(f"{module}.time.monotonic", side_effect=(0, 4 * 60 * 60 + 1)), \
                 mock.patch(f"{module}.time.sleep"), \
                 mock.patch(f"{module}.warnings.warn") as warned:
                _run_command(["unused"], log_path)
            warned.assert_called_once()
            process.wait.assert_not_called()
            self.assertIn("CANDIDATE_STAGE_WARNING", log_path.read_text(encoding="utf-8"))


    def test_bootstrap_writes_three_manifest_bound_stage_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170000"
            )
            observed = []
            run_root, summary = run_candidate_workflow(
                plan_path,
                sys.executable,
                stage_executor=self.native_fake_executor(observed),
            )
            self.assertEqual(summary["status"], "success")
            self.assertEqual(
                [path.stem for path in sorted((run_root / "stage_receipts").glob("*.json"))],
                list(("cad_candidate", "comsol_candidate", "simion_candidate")),
            )
            manifest = load_json(run_root / "run_manifest.json")
            manifest_paths = {
                Path(record["path"]).resolve()
                for record in manifest["outputs"]
            }
            for stage_id in ("comsol_candidate", "simion_candidate", "cad_candidate"):
                self.assertIn(
                    (run_root / "stage_receipts" / f"{stage_id}.json").resolve(),
                    manifest_paths,
                )
            self.assertNotIn(
                "stage_reuse_provenance",
                load_json(run_root / "run_config.json")["inputs"],
            )
            self.assertEqual(verify_project(artifact_root), (2, 0))


    def test_orchestration_only_change_reuses_all_stages_but_generator_change_rejects(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, parent_plan = self.native_workflow_plan(root, '20260727_180100')
            parent, _ = run_candidate_workflow(parent_plan, sys.executable,
                stage_executor=self.native_fake_executor([]))
            before = {p: p.read_bytes() for p in parent.rglob('*') if p.is_file()}
            freeze = preparation.freeze_candidate_source_closure

            def changed_freeze(*args, **kwargs):
                closure = freeze(*args, **kwargs)
                source_id = 'projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/'+changed_name
                record = next(r for r in closure['sources'] if r['source_id'] == source_id)
                target = Path(closure['code_root'])/source_id
                content = target.read_text(encoding='utf-8')
                if changed_name == 'run_candidate_workflow.py':
                    content += '\n# report wording only\n'
                else:
                    old, new = mutations[changed_name]
                    self.assertEqual(content.count(old), 1)
                    content = content.replace(old, new)
                target.write_text(content, encoding='utf-8', newline='\n')
                record.update(bytes=target.stat().st_size, sha256=sha256(target))
                verify_candidate_source_closure(closure)
                return closure

            mutations = {
                'candidate_simion_stage.py': ('"-ParticleCount", "100"', '"-ParticleCount", "99"'),
                'candidate_cad_stage.py': ('"OATOF_CANDIDATE_CAD_DIR": stage["output_dir"]',
                    '"OATOF_CANDIDATE_CAD_DIR": str(Path(stage["output_dir"]) / "review")'),
                'candidate_comsol_stage.py': ('run_candidate_contract_build.m', 'different_scientific_builder.m'),
            }
            changed_name = 'run_candidate_workflow.py'
            with mock.patch.object(preparation, 'freeze_candidate_source_closure', side_effect=changed_freeze):
                _, child_plan = self.native_workflow_plan(root, '20260727_180200')
            observed = []
            child, summary = run_candidate_workflow(child_plan, sys.executable,
                stage_executor=self.native_fake_executor(observed), reuse_parent=parent, reuse_through='cad_candidate')
            self.assertEqual(observed, ['static_inputs','structural_acceptance'])
            self.assertTrue(all(item['execution'] == 'reused' for item in summary['stages']
                if item['stage_id'] in ('comsol_candidate','simion_candidate','cad_candidate')))
            self.assertEqual({p:p.read_bytes() for p in before}, before)

            changed_name = 'candidate_cad_stage.py'
            with mock.patch.object(preparation, 'freeze_candidate_source_closure', side_effect=changed_freeze):
                _, cad_plan = self.native_workflow_plan(root, '20260727_180250')
            observed = []
            _, cad_summary = run_candidate_workflow(cad_plan, sys.executable,
                stage_executor=self.native_fake_executor(observed), reuse_parent=parent, reuse_through='simion_candidate')
            self.assertEqual(observed, ['static_inputs', 'cad_candidate', 'structural_acceptance'])
            self.assertEqual([item['stage_id'] for item in cad_summary['stages'] if item['execution'] == 'reused'],
                ['comsol_candidate', 'simion_candidate'])
            self.assertEqual({p:p.read_bytes() for p in before}, before)

            changed_name = 'candidate_comsol_stage.py'
            with mock.patch.object(preparation, 'freeze_candidate_source_closure', side_effect=changed_freeze):
                _, comsol_plan = self.native_workflow_plan(root, '20260727_180255')
            observed = []
            with self.assertRaises(CandidateWorkflowError):
                run_candidate_workflow(comsol_plan, sys.executable,
                    stage_executor=self.native_fake_executor(observed), reuse_parent=parent, reuse_through='comsol_candidate')
            self.assertEqual(observed, ['static_inputs'])
            self.assertEqual({p:p.read_bytes() for p in before}, before)

            changed_name = 'candidate_simion_stage.py'
            with mock.patch.object(preparation, 'freeze_candidate_source_closure', side_effect=changed_freeze):
                _, changed_plan = self.native_workflow_plan(root, '20260727_180300')
            observed = []
            with self.assertRaises(CandidateWorkflowError):
                run_candidate_workflow(changed_plan, sys.executable,
                    stage_executor=self.native_fake_executor(observed), reuse_parent=parent, reuse_through='cad_candidate')
            self.assertEqual(observed, ['static_inputs'])
            self.assertEqual({p:p.read_bytes() for p in before}, before)


    def test_native_failed_parent_reuses_prefix_and_runs_only_cad_after_static(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            artifact_root, parent_plan = self.native_workflow_plan(
                root_path, "20260727_170100"
            )
            with self.assertRaises(CandidateWorkflowError) as caught:
                run_candidate_workflow(
                    parent_plan,
                    sys.executable,
                    stage_executor=self.native_fake_executor(
                        [], fail_stage="cad_candidate"
                    ),
                )
            parent = caught.exception.run_root
            self.assertEqual(load_json(parent / "summary.json")["status"], "failed")

            _, child_plan = self.native_workflow_plan(
                root_path, "20260727_170200"
            )
            observed = []
            run_root, summary = run_candidate_workflow(
                child_plan,
                sys.executable,
                stage_executor=self.native_fake_executor(observed),
                reuse_parent=parent,
                reuse_through="simion_candidate",
            )
            self.assertEqual(
                observed,
                ["static_inputs", "cad_candidate", "structural_acceptance"],
            )
            statuses = {item["stage_id"]: item for item in summary["stages"]}
            self.assertEqual(statuses["comsol_candidate"]["execution"], "reused")
            self.assertEqual(statuses["simion_candidate"]["execution"], "reused")
            self.assertEqual(statuses["cad_candidate"]["execution"], "executed")
            self.assertTrue(
                (run_root / "inputs" / "stage_reuse_provenance.json").is_file()
            )


    def test_native_reuse_tamper_fails_before_any_commercial_stage(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            _, parent_plan = self.native_workflow_plan(
                root_path, "20260727_170300"
            )
            parent, _ = run_candidate_workflow(
                parent_plan,
                sys.executable,
                stage_executor=self.native_fake_executor([]),
            )
            _, child_plan = self.native_workflow_plan(
                root_path, "20260727_170400"
            )
            observed = []

            def changed_static(stage, plan, simion):
                evidence = self.native_fake_executor(observed)(stage, plan, simion)
                if stage["stage_id"] == "static_inputs":
                    Path(evidence["particle_table"]).write_text(
                        "changed particle\n", encoding="utf-8"
                    )
                return evidence

            with self.assertRaises(CandidateWorkflowError) as caught:
                run_candidate_workflow(
                    child_plan,
                    sys.executable,
                    stage_executor=changed_static,
                    reuse_parent=parent,
                    reuse_through="simion_candidate",
                )
            self.assertEqual(observed, ["static_inputs"])
            self.assertEqual(
                load_json(caught.exception.run_root / "summary.json")["status"],
                "failed",
            )


    def test_entry_reuse_is_run_id_independent_but_seed_sensitive(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            source.mkdir()
            self.candidate_run_inputs(source)
            artifact_root = root_path / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer"
            registration = self.registered_template_run(
                artifact_root,
                "20260727_102100__build__simion__candidate-layout-template-workspace",
            )
            runtime = root_path / "candidate_runtime.json"
            runtime.write_text(
                json.dumps(
                    {
                        "role": "oa_tof_candidate_runtime",
                        "simion_template_run_id": registration.name,
                    }
                ),
                encoding="utf-8",
            )
            request = source / "design_request.json"
            with mock.patch.object(candidate_entry, "RUNTIME_CONFIG", runtime):
                parent, _ = candidate_entry.execute_request(
                    request,
                    "20260727_170410__test__cross__entry-reuse-parent",
                    simion_executable=Path(sys.executable),
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                    stage_executor=self.native_fake_executor([]),
                )
                same_seed_observed = []
                same_seed_child, _ = candidate_entry.execute_request(
                    request,
                    "20260727_170420__test__cross__entry-reuse-same-seed",
                    simion_executable=Path(sys.executable),
                    particle_source_seed=20260720,
                    artifact_project_root=artifact_root,
                    reuse_parent=parent,
                    reuse_through="simion_candidate",
                    stage_executor=self.native_fake_executor(same_seed_observed),
                )
                different_seed_observed = []
                with self.assertRaises(CandidateWorkflowError) as caught:
                    candidate_entry.execute_request(
                        request,
                        "20260727_170430__test__cross__entry-reuse-different-seed",
                        simion_executable=Path(sys.executable),
                        particle_source_seed=20260721,
                        artifact_project_root=artifact_root,
                        reuse_parent=parent,
                        reuse_through="simion_candidate",
                        stage_executor=self.native_fake_executor(
                            different_seed_observed
                        ),
                    )
            self.assertEqual(
                same_seed_observed,
                ["static_inputs", "cad_candidate", "structural_acceptance"],
            )
            self.assertEqual(different_seed_observed, ["static_inputs"])
            self.assertIn("input", str(caught.exception))
            self.assertIn("changed", str(caught.exception))
            parent_config = load_json(parent / "run_config.json")
            same_seed_config = load_json(same_seed_child / "run_config.json")
            different_seed_config = load_json(
                caught.exception.run_root / "run_config.json"
            )
            resolved_name = "candidate_resolved_geometry.json"
            self.assertEqual(
                parent_config["input_sha256"][resolved_name],
                same_seed_config["input_sha256"][resolved_name],
            )
            self.assertEqual(
                parent_config["input_sha256"][resolved_name],
                different_seed_config["input_sha256"][resolved_name],
            )
            self.assertNotEqual(
                parent_config["input_sha256"]["candidate_particle_table"],
                different_seed_config["input_sha256"]["candidate_particle_table"],
            )


    def test_native_closure_failure_still_writes_failed_triple(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170500"
            )
            with self.assertRaises(CandidateWorkflowError) as caught:
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=self.native_fake_executor(
                        [], tamper_closure=True
                    ),
                )
            run_root = caught.exception.run_root
            self.assertEqual(load_json(run_root / "summary.json")["status"], "failed")
            self.assertEqual(load_json(run_root / "run_manifest.json")["status"], "failed")
            self.assertEqual(verify_project(artifact_root), (2, 0))


    def test_native_cad_rejects_mph_tamper_after_context_before_launch(self):
        with tempfile.TemporaryDirectory() as root:
            _, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170600"
            )
            observed = []
            base = self.native_fake_executor(observed)

            def tamper_after_context(stage, plan, simion):
                evidence = base(stage, plan, simion)
                if stage["stage_id"] == "simion_candidate":
                    model = (
                        Path(plan["run_root"])
                        / "results"
                        / "comsol_candidate_model.dat"
                    )
                    model.write_text("tampered model\n", encoding="utf-8")
                return evidence

            with self.assertRaisesRegex(
                CandidateWorkflowError,
                "Candidate MPH differs from its frozen identity",
            ):
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=tamper_after_context,
                )
            self.assertEqual(
                observed,
                ["static_inputs", "comsol_candidate", "simion_candidate"],
            )


    def test_native_rejects_raw_input_tamper_after_context_before_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            _, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170700"
            )
            observed = []
            base = self.native_fake_executor(observed)

            def tamper_input(stage, plan, simion):
                evidence = base(stage, plan, simion)
                if stage["stage_id"] == "comsol_candidate":
                    baseline = Path(
                        plan["candidate_inputs"]["candidate_baseline.json"]["path"]
                    )
                    baseline.write_text(
                        baseline.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8",
                    )
                return evidence

            with self.assertRaisesRegex(
                CandidateWorkflowError,
                "frozen candidate run input changed",
            ):
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=tamper_input,
                )
            self.assertEqual(observed, ["static_inputs", "comsol_candidate"])


    def test_native_rechecks_candidate_mph_after_cad_executor(self):
        with tempfile.TemporaryDirectory() as root:
            _, plan_path = self.native_workflow_plan(
                Path(root), "20260727_170800"
            )
            observed = []
            base = self.native_fake_executor(observed)

            def mutate_during_cad(stage, plan, simion):
                evidence = base(stage, plan, simion)
                if stage["stage_id"] == "cad_candidate":
                    Path(stage["model_path"]).write_text(
                        "CAD modified its input\n", encoding="utf-8"
                    )
                return evidence

            with self.assertRaisesRegex(
                CandidateWorkflowError,
                "Candidate MPH differs from its frozen identity",
            ):
                run_candidate_workflow(
                    plan_path,
                    sys.executable,
                    stage_executor=mutate_during_cad,
                )
            self.assertEqual(
                observed,
                [
                    "static_inputs",
                    "comsol_candidate",
                    "simion_candidate",
                    "cad_candidate",
                ],
            )




def postprocess_source_fixture(directory, *, unknown=False, cold=False, comsol_bytes=None, retain_model=False, save_state="raw_complete", legacy_save_complete=False, solution_times=None, resolved_alias=False):
    """Producer-shaped small records; no vendor process or model is fabricated."""
    import csv
    from common.contracts.capacity_ledger import record_capacity_object
    from common.contracts.write_run_manifest import publish_run_manifest
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
    artifact = directory / "artifacts"
    parent = artifact / "projects" / PROJECT_ROOT.name / "runs/20261031_121000__sim__comsol__postprocess-parent"
    for name in ("inputs", "results", "logs"):
        (parent / name).mkdir(parents=True)
    physical = parent / "inputs/candidate_resolved_geometry.json"
    physical.write_bytes((PROJECT_ROOT / "config/resolved_geometry.json").read_bytes())
    source = parent / "inputs/source.ion"
    source.write_text("\n".join("0,524,1,0,0,0,0,0,1,1,1" for _ in range(100))+"\n", encoding="utf-8")
    budget = parent / "inputs/candidate_runtime.json"
    budget.write_bytes((PROJECT_ROOT / "config/candidate_runtime.json").read_bytes())
    if comsol_bytes is not None:
        budget_document=load_json(budget)
        budget_document["artifact_capacity"]["comsol_bytes"]=comsol_bytes
        budget.write_text(json.dumps(budget_document),encoding="utf-8")
    events = parent / "results/comsol_detector_events_Fixture.csv"
    with events.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Ion","TofUs","XMm","YMm","Hit","Status","Event","DetectorRadiusMm","X0Mm","Y0Mm","Z0Mm"])
        for index in range(100):
            writer.writerow([index+1,40+index*.00001,0,0,True,"detector_hit","crossing",0,0,0,0])
    analysis = parent / "results/comsol_detector_events_Fixture.analysis_request.json"
    analysis.write_text(json.dumps({"schema_version":1,"role":"oatof_comsol_detector_events_analysis_request",
        "solver":"COMSOL","label":"Fixture","nominal_mass_Da":524,"raw_events_csv":str(events),
        "analysis_output_dir":str(parent / "results/analysis"),"event_extraction":"solver_native_detector_crossing_or_freeze",
        "aggregate_metrics_owner":"python_reference_analysis"}), encoding="utf-8")
    native = parent / "logs/comsol_build_completion.json"
    native.write_text(json.dumps({"schema_version":1,"role":"comsol_launcher_completion","run_id":parent.name,
        "operations":[{"operation_id":"launcher-attempt-1","observation":{"exit_confirmed":not unknown,"returncode":0}}],
        "host_release":{"inherited":False,"token":"fixture-released","result":{"status":"released","token":"fixture-released"},"error":None}}), encoding="utf-8")
    writer = {"operations":[],"resource_releases":[]}
    append_native_stage_completion(writer,native,role="comsol_launcher_completion",run_id=parent.name)
    completion = parent / "results/execution_completion.json"
    completion.write_text(json.dumps({"writer_completion":writer}), encoding="utf-8")
    config = {"schema_version":2,"run_id":parent.name,"project":PROJECT_ROOT.name,"mode":"design_candidate",
        "project_root":str(PROJECT_ROOT),"inputs":{"candidate_resolved_geometry.json":str(physical),
        "candidate_particle_table":str(source),"candidate_runtime.json":str(budget)},
        "artifact_retention":{"policy_version":1,"class":"compact","reason":None},
        "capacity_ledger_lifecycle":{"schema_version":1,"enabled":True,"artifact_root":str(artifact),
                                     "light_evidence_budget_bytes":67108864}}
    if cold or retain_model:
        config["artifact_retention"]={"policy_version":1,"class":"solver_review",
            "reason":"Opaque saved-input metadata fixture retained for cold admission tests; no vendor opens it."}
    if resolved_alias:
        config["inputs"]["simion_candidate_input_001"] = str(physical)
    config_path = parent / "run_config.json"
    from common.contracts.write_run_manifest import file_record
    request_path = parent / "inputs/execution_request.json"
    request_path.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_request",
        "package":{"project":PROJECT_ROOT.name,"run_id":parent.name,"mode":"design_candidate"}}),encoding="utf-8")
    config["inputs"]["execution_request"] = str(request_path)
    config_path.write_text(json.dumps(config),encoding="utf-8")
    completion.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_completion",
        "project":PROJECT_ROOT.name,"run_id":parent.name,"status":"failed","writer_completion":writer,
        "execution_request":file_record(request_path),"run_config":file_record(config_path)}),encoding="utf-8")
    outputs = [events,analysis,native,completion]
    if cold or retain_model:
        # Opaque three-byte admission fixture, never opened by a vendor tool.
        # It proves metadata/capacity transport, not a physically solved model.
        if cold:
            events.unlink();analysis.unlink()
        model=parent/"comsol/model.mph";model.parent.mkdir();model.write_bytes(b"MPH")
        context=model.with_suffix(".mph.postprocess.json")
        context.write_text(json.dumps({"schema_version":1,"role":"oatof_saved_particle_solution",
            "solution_tag":"sol2","dataset_tag":"pdset1","solution_times_s":[0,1e-6] if solution_times is None else solution_times,
            "particle_count":100,"saved_model_bytes":3,"timing":{},"expected_tof":1e-6,
            "fine_tstep":1e-9,"Tsim":1e-6,"detector_z_mm":0,"detector_x_mm":0,
            "detector_radius_mm":1,"flight_length_mm":1,"accelerator_exit_mm":0,
            "contract_path":str(physical),"source_path":str(source)}),encoding="utf-8")
        context_document=load_json(context)
        if save_state is not None:
            context_document["model_save_state"]=save_state
        context.write_text(json.dumps(context_document),encoding="utf-8")
        if retain_model:
            context_document=load_json(context)
            context_document.update(solution_times_s=[0,80e-6],expected_tof=40e-6,Tsim=80e-6)
            context.write_text(json.dumps(context_document),encoding="utf-8")
        outputs=[model,context,native,completion] + ([events,analysis] if retain_model else [])
    if legacy_save_complete:
        report=parent/"logs/comsol_build.txt"
        report.write_text("STATUS=PASS\n",encoding="utf-8")
        outputs.append(report)
    publish_run_manifest(config_path,"failed",output_paths=outputs)
    initialize_capacity_ledger(artifact,objects=[])
    record_capacity_object(artifact,path=parent,object_class="light_evidence",bytes_count=sum(
        path.stat().st_size for path in parent.rglob("*") if path.is_file()),owner=PROJECT_ROOT.name)
    return artifact,parent,config_path,outputs


def postprocess_public_entry(root, artifact):
    author=root/"author"
    for path in REPO_ROOT.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py",".ps1",".json",".m",".lua",".gem",".fly2",".md"}:
            target=author/path.relative_to(REPO_ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
    policy=author/"common/contracts/artifact_capacity_policy.json"
    document=load_json(policy)
    document["minimum_free_gib"]=0
    policy.write_text(json.dumps(document),encoding="utf-8")
    # Real public lifecycle remains intact; this vendor boundary must never execute.
    (author/"common/comsol/run_comsol_r2025b.ps1").write_text("throw 'COMSOL_MUST_NOT_START'",encoding="utf-8")
    env=os.environ.copy()
    env.update(SIMULATION_PYTHON_EXE=sys.executable,MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifact),
               MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/"native"))
    bootstrap="import sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate import main;main()"
    def invoke(arguments):
        return subprocess.run([sys.executable,"-I","-B","-c",bootstrap,str(author),"run_candidate.py",*arguments],
            cwd=author,env=env,capture_output=True,text=True,encoding="utf-8",timeout=240)
    return invoke


def cold_export_failed_child_fixture(directory, *, unknown=False, wrong_source=False, normal_phase=False):
    """Small stopped-cold-export producer fixture; this executes no solver."""
    from common.contracts.capacity_ledger import record_capacity_object
    from common.contracts.write_run_manifest import file_record, publish_run_manifest
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
    artifact,science,_,_=postprocess_source_fixture(directory,retain_model=normal_phase)
    source=select_postprocess_parent(science,artifact)
    if wrong_source:
        source["inputs"]["source_path"]=source["budget_record"]
    child=artifact/"projects"/PROJECT_ROOT.name/"runs/20261031_123000__analysis__comsol__cold-export-failed"
    for name in ("inputs","logs","results"):
        (child/name).mkdir(parents=True)
    source_path=child/"inputs/postprocess_source_selection.json"
    source_path.write_text(json.dumps(source),encoding="utf-8")
    request=child/"inputs/execution_request.json"
    request.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_request",
        "package":{"project":PROJECT_ROOT.name,"run_id":child.name,"mode":"candidate_comsol_postprocess"}}),encoding="utf-8")
    config={"schema_version":2,"project":PROJECT_ROOT.name,"run_id":child.name,"mode":"candidate_comsol_postprocess",
        "project_root":str(PROJECT_ROOT),"inputs":{"execution_request":str(request),"postprocess_source_selection":str(source_path)},
        "provenance":{"science_reference":source["science_reference"]},
        "artifact_retention":{"policy_version":1,"class":"compact","reason":None},
        "capacity_ledger_lifecycle":{"schema_version":1,"enabled":True,"artifact_root":str(artifact),"light_evidence_budget_bytes":67108864}}
    if normal_phase:
        config["mode"]="design_candidate"
        request_document=load_json(request);request_document["package"]["mode"]="design_candidate"
        request.write_text(json.dumps(request_document),encoding="utf-8")
    config_path=child/"run_config.json"
    config_path.write_text(json.dumps(config),encoding="utf-8")
    events=child/"results/comsol_detector_events_Fixture.csv"
    events.write_bytes(Path(source["exports"]["events"]["path"]).read_bytes())
    analysis=child/"results/comsol_detector_events_Fixture.analysis_request.json"
    document=load_json(Path(source["exports"]["request"]["path"]))
    document.update(raw_events_csv=str(events),analysis_output_dir=str(child/"results/analysis"))
    analysis.write_text(json.dumps(document),encoding="utf-8")
    native=child/"logs/cold_postprocess_completion.json"
    receipt=load_json(science/"logs/comsol_build_completion.json")
    receipt["run_id"]=child.name
    receipt["operations"][0]["observation"]["exit_confirmed"]=not unknown
    native.write_text(json.dumps(receipt),encoding="utf-8")
    writer={"operations":[],"resource_releases":[]}
    append_native_stage_completion(writer,native,role="comsol_launcher_completion",run_id=child.name)
    if normal_phase:
        phase_records={}
        for phase in ("native","export","analysis","sync"):
            path=child/"inputs"/(phase+"_implementation.json")
            path.write_text(json.dumps({"software_fixture_phase":phase}),encoding="utf-8")
            config["inputs"]["comsol_phase_"+phase]=str(path)
            phase_records[phase]={"status":"pending","owner_manifest_input":None,"outputs":{}}
        owner_name="comsol_native_source_manifest"
        config["inputs"][owner_name]=str(science/"run_manifest.json")
        phase_records["native"]={"owner_manifest_input":owner_name,"outputs":{
            "model":file_record(science/"comsol/model.mph"),"build_report":file_record(science/"logs/comsol_build_completion.json")}}
        phase_records["export"]={"owner_manifest_input":None,"outputs":{"analysis_request":file_record(analysis),"raw_events":file_record(events)}}
        config["provenance"]["comsol_phases"]=phase_records
        config_path.write_text(json.dumps(config),encoding="utf-8")
    completion=child/"results/execution_completion.json"
    completion.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_completion",
        "project":PROJECT_ROOT.name,"run_id":child.name,"status":"failed","execution_request":file_record(request),
        "run_config":file_record(config_path),"writer_completion":writer,
        "summary":{"status":"failed","scope":"comsol_postprocessing_only","source_identity_verified":True},
        "exception":{"type":"RuntimeError","message":"ANALYSIS_FAILED_AFTER_EXPORT"}}),encoding="utf-8")
    publish_run_manifest(config_path,"failed",output_paths=[events,analysis,native,completion])
    record_capacity_object(artifact,path=child,object_class="light_evidence",bytes_count=sum(
        path.stat().st_size for path in child.rglob("*") if path.is_file()),owner=PROJECT_ROOT.name)
    return artifact,science,child,events


class CandidatePostprocessTests(unittest.TestCase):
    def test_cold_prepared_plan_uses_public_native_view_and_prelaunch_failure_has_no_receipt(self):
        from common.contracts.test_run_artifact_workflow import CALLBACK, RunArtifactWorkflowTests
        from common.contracts.write_run_manifest import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        extra = '''    from unittest import mock
    from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow, candidate_comsol_stage
    def inert_saved(selection, child, closure, plan, *, runtime):
        assert plan['run_root'] == str(root.resolve())
        argv, environment = workflow._native_stage_execution_view([sys.executable, '-I', '-B', '-c', 'pass'],
            {'OATOF_CANDIDATE_MODEL_PATH':selection['model_record']['path']}, plan)
        assert environment['OATOF_CANDIDATE_MODEL_PATH']
        writer_before = json.dumps(plan['writer_completion'], sort_keys=True)
        wrong = dict(plan, run_root=str(root.parent / 'different-owner'))
        with mock.patch.object(workflow, '_run_command') as command, mock.patch.object(workflow, 'append_native_stage_completion') as append:
            try:
                workflow._run_managed_stage_command(argv, root/'logs/not-launched.log', wrong,
                    root/'logs/not-launched.json', 'comsol_launcher_completion', environment)
            except ValueError as error:
                assert 'active public run context' in str(error)
            else:
                raise AssertionError('Mismatched owner must fail before process admission')
            command.assert_not_called()
            append.assert_not_called()
        assert json.dumps(plan['writer_completion'], sort_keys=True) == writer_before
        (root/'results/cold_native_view_probe.json').write_text(json.dumps({'run_root':plan['run_root'],
            'writer_unchanged':True,'prelaunch_command_calls':0,'prelaunch_receipt_calls':0}), encoding='utf-8')
        return {}
    with mock.patch.object(candidate_comsol_stage, 'execute_saved_postprocess', side_effect=inert_saved):
        workflow.execute_prepared_postprocess(config_path, session_path, request_path, root/'results/cold_completion.json')
    cold_completion = json.loads((root/'results/cold_completion.json').read_text(encoding='utf-8'))
    assert cold_completion['status'] == 'success', cold_completion
    assert cold_completion['writer_completion'] == {'operations':[],'resource_releases':[]}
    config = json.loads(config_path.read_text(encoding='utf-8'))
'''
        callback = CALLBACK.replace('    counter = Path(payload["counter_path"])', extra + '    counter = Path(payload["counter_path"])')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, parent, _, _ = postprocess_source_fixture(root / "source", cold=True)
            selected = select_postprocess_parent(parent, artifact)
            closure = freeze_candidate_source_closure(root / "code", artifact / "projects" / PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT / "config/analysis_contract.json")
            selection = root / "selection.json"
            selection.write_text(json.dumps(selected), encoding="utf-8")
            before = {str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            fixture = RunArtifactWorkflowTests()
            (root / "owner").mkdir()
            result, run, _, outcome = fixture.invoke_fixture(root / "owner", {
                "postprocess_selection":file_record(selection),"execution_source_closure":closure,
                "fixture_commitment_bytes":8*1024*1024}, callback_text=callback,
                source_references=selected["source_references"],
                native_input_paths=[selected["model_record"]["path"], selected["context_record"]["path"]])
            self.assertEqual(outcome.returncode,0,outcome.stdout+outcome.stderr+json.dumps(result))
            probe=load_json(run/"results/cold_native_view_probe.json")
            self.assertTrue(probe["writer_unchanged"])
            self.assertEqual(probe["run_root"],str(run.resolve()))
            self.assertEqual(before,{str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_saved_dependency_aliases_require_complete_identity_consensus(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        cases = (("same", None, None), ("case_normalized", "sha256", "lower"),
                 ("bytes_conflict", "bytes", -1), ("sha_conflict", "sha256", "0" * 64),
                 ("missing_alias", "exists", False))
        for name, field, value in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                artifact, parent, _, _ = postprocess_source_fixture(Path(directory), cold=True, resolved_alias=True)
                manifest_path = parent / "run_manifest.json"
                manifest = load_json(manifest_path)
                aliases = manifest["inputs"]
                self.assertEqual(aliases["candidate_resolved_geometry.json"]["path"],
                                 aliases["simion_candidate_input_001"]["path"])
                if field:
                    alias = aliases["simion_candidate_input_001"]
                    alias[field] = alias[field].lower() if value == "lower" else value
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                before = {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                if name in {"same", "case_normalized"}:
                    selected = select_postprocess_parent(parent, artifact)
                    self.assertIsNone(selected["exports"])
                else:
                    with self.assertRaisesRegex(ValueError, "Saved dependency.*manifest"):
                        select_postprocess_parent(parent, artifact)
                self.assertEqual(before, {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_saved_inventory_duplicates_are_preserved_until_guarded_cold_read(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        cases = (("duplicate", [0, 1e-6, 1e-6, 2e-6], True),
                 ("all_equal", [0, 0], False), ("decreasing", [0, 1e-6, 0], False),
                 ("nonfinite", [0, float("nan"), 1e-6], False))
        for name, times, accepted in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                artifact, parent, _, _ = postprocess_source_fixture(Path(directory), cold=True, solution_times=times)
                before = {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                if accepted:
                    selection = select_postprocess_parent(parent, artifact)
                    self.assertIsNone(selection["exports"])
                    context = load_json(parent / "comsol/model.mph.postprocess.json")
                    self.assertEqual(context["solution_times_s"], times)
                else:
                    with self.assertRaisesRegex(ValueError, "original finite increasing solution times"):
                        select_postprocess_parent(parent, artifact)
                self.assertEqual(before, {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_native_execution_paths_use_actual_public_owner_and_preserve_identity(self):
        from common.contracts.test_run_artifact_workflow import CALLBACK, RunArtifactWorkflowTests
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import candidate_native_execution_relative_paths
        relative = "inputs/code/" + "deep/" * 26 + "actual_native_task.m"
        declared = candidate_native_execution_relative_paths({"sources": []}, code_relative_root=Path("inputs/code"))
        self.assertIn("inputs/native_run_config.json", declared)
        extra = """    from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import _native_stage_execution_view, _persist_native_json_paths, _run_command
    import subprocess
    task = root / payload['native_relative']
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('% inert task, never executed', encoding='utf-8')
    source = root / 'inputs/source.ion'
    source.write_text('original-source', encoding='utf-8')
    native_config = root / 'run_config.json'
    doc = json.loads(native_config.read_text(encoding='utf-8-sig'))
    doc['inputs']['particle_table'] = str(source)
    native_config.write_text(json.dumps(doc), encoding='utf-8')
    frozen_before = native_config.read_bytes()
    argv, env = _native_stage_execution_view([sys.executable, str(task)], {'OATOF_CANDIDATE_RUN_CONFIG_PATH':str(native_config)}, {'run_root':str(root)})
    assert len(argv[1]) <= 259 and argv[1] != str(task)
    assert Path(argv[1]).read_bytes() == task.read_bytes()
    transport = json.loads(Path(env['OATOF_CANDIDATE_RUN_CONFIG_PATH']).read_text(encoding='utf-8'))
    assert transport['inputs']['particle_table'] != str(source)
    assert Path(transport['inputs']['particle_table']).read_bytes() == source.read_bytes()
    assert native_config.read_bytes() == frozen_before
    observed = subprocess.run([sys.executable, '-I', '-B', '-c', 'pass'], cwd=os.environ['MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY'], capture_output=True, text=True, encoding='utf-8', check=True)
    failed_log = Path(os.environ['MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY']) / 'logs/inert_failed.log'
    try:
        _run_command([sys.executable, '-I', '-B', '-c', "print('inert diagnostic');raise SystemExit(17)"], failed_log)
    except RuntimeError as error:
        assert 'exit code 17' in str(error)
        assert str(root / 'logs/inert_failed.log') in str(error) and str(failed_log) not in str(error)
    else:
        raise AssertionError('Expected inert child failure was not propagated')
    native_request = root / 'results/inert.analysis_request.json'
    native_request.write_text(json.dumps({'path':argv[1]}), encoding='utf-8')
    _persist_native_json_paths({'run_root':str(root)})
    assert json.loads(native_request.read_text(encoding='utf-8'))['path'] == str(task)
    config = json.loads(config_path.read_text(encoding='utf-8'))
"""
        callback = CALLBACK.replace('    counter = Path(payload["counter_path"])', extra + '    counter = Path(payload["counter_path"])')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = RunArtifactWorkflowTests()
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_EXECUTION_ROOT": str(root / "x")}):
                result, run, _, outcome = fixture.invoke_fixture(root, {"native_relative":relative}, callback_text=callback, expected_execution_relative_paths=[relative, *declared])
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr + json.dumps(result) + "\n".join(path.read_text(encoding="utf-8",errors="replace") for path in (run / "logs").glob("*.log")))
            self.assertTrue(result['execution_alias_removed'])
            self.assertIn('inert diagnostic', (run / 'logs/inert_failed.log').read_text(encoding='utf-8'))
            persisted = load_json(run / 'inputs/native_run_config.json')
            self.assertEqual(persisted['inputs']['particle_table'], str(run / 'inputs/source.ion'))

    def test_native_runtime_reservation_uses_frozen_budget_and_csv_stays_light(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent,prepare_postprocess_request
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for cold in (False,True):
                with self.subTest(cold=cold):
                    artifact,parent,_,_=postprocess_source_fixture(root/str(cold),cold=cold)
                    before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                    selected=select_postprocess_parent(parent,artifact)
                    budget=load_json(Path(selected["budget_record"]["path"]))["artifact_capacity"]
                    self.assertEqual(selected["native_runtime_bytes"],budget["comsol_bytes"] if cold else 0)
                    self.assertEqual(selected["new_bytes"],budget["evidence_bytes"]+(budget["comsol_bytes"] if cold else 0))
                    with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_ARTIFACT_ROOT":str(artifact)}):
                        request=prepare_postprocess_request(parent,"20261031_151000__analysis__python__runtime-budget")
                    self.assertEqual(request["capacity"]["committed_new_bytes"],selected["new_bytes"])
                    self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})
            artifact,parent,_,_=postprocess_source_fixture(root/"insufficient",cold=True,comsol_bytes=2)
            with self.assertRaisesRegex(ValueError,"COLD_RUNTIME_RESERVATION_INSUFFICIENT"):
                select_postprocess_parent(parent,artifact)

    def test_normal_comsol_commands_transport_the_owner_runtime_directory(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/"run";(run/"logs").mkdir(parents=True)
            execution=root/"execution";execution.mkdir()
            closure=freeze_candidate_source_closure(run/"inputs/code",root/"artifacts",
                resolved_contract=PROJECT_ROOT/"config/resolved_geometry.json",
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            request=run/"analysis_request.json";request.write_text("{}",encoding="utf-8")
            commands=[]
            def observe(command,log,plan,receipt,role,environment):
                commands.append(command)
                report=Path(command[command.index("-ReportPath")+1])
                report.write_text("STATUS=PASS\nPYTHON_ANALYSIS_REQUEST="+str(request)+"\n",encoding="utf-8")
            runtime=SimpleNamespace(_verify_frozen_cad_python=lambda *args:sys.executable,_run_managed_stage_command=observe)
            stage={"environment":{},"report_path":str(run/"logs/build.txt"),"model_path":str(run/"model.mph"),"contract_path":str(PROJECT_ROOT/"config/resolved_geometry.json")}
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution)}), \
                    mock.patch.object(adapter,"analyze_detector_request",return_value=run/"analysis_receipt.json"):
                adapter.execute_comsol_stage(stage,{"execution_source_closure":closure,"run_root":str(run),"run_id":run.name},sys.executable,runtime=runtime)
            self.assertEqual(len(commands),2)
            from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_cad_stage import execute_cad_stage
            def stop_cad(command,*args):
                commands.append(command)
                raise RuntimeError("STOP_AT_CAD_NATIVE_BOUNDARY")
            runtime._run_managed_stage_command=stop_cad
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution)}):
                with self.assertRaisesRegex(RuntimeError,"STOP_AT_CAD_NATIVE_BOUNDARY"):
                    execute_cad_stage(dict(stage,output_dir=str(run/"cad")),
                        {"execution_source_closure":closure,"run_root":str(run),"run_id":run.name},sys.executable,runtime=runtime)
            self.assertEqual(len(commands),3)
            self.assertEqual([command[command.index("-RunDir")+1] for command in commands],[str(execution)]*3)
            self.assertFalse((run/"model.mph").exists())
            self.assertFalse((run/"cad/oaTOF_solidworks_export_report.json").exists())

    def test_original_cli_postprocess_is_explicit_and_rejects_new_science(self):
        argv = ["run_candidate.py","--postprocess-from","parent","--run-id","new"]
        for extra in (["--request","request.json"],["--particle-source-seed","0"],["--reuse-parent","other"],
                      ["--resume-finalization","old"],["--simion-exe","simion.exe"],["--dry-run"]):
            with self.subTest(extra=extra), mock.patch.object(sys,"argv",argv+extra), \
                    mock.patch.object(candidate_entry,"prepare_execution") as prepare:
                with self.assertRaises(SystemExit):
                    candidate_entry.main()
                prepare.assert_not_called()
        with mock.patch.object(sys,"argv",argv), mock.patch.object(candidate_workflow,"run_candidate_postprocess",
                return_value=(Path("child"),{"scope":"comsol_postprocessing_only"})) as execute, \
                mock.patch.object(candidate_entry,"prepare_execution") as prepare:
            candidate_entry.main()
        execute.assert_called_once_with(Path("parent"),"new")
        prepare.assert_not_called()

    def test_sealed_exports_need_no_model_and_unknown_writer_is_rejected(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            artifact,parent,config,outputs=postprocess_source_fixture(Path(directory))
            selected=select_postprocess_parent(parent,artifact)
            self.assertIsNone(selected["model_record"])
            self.assertIsNone(selected["context_record"])
            self.assertEqual(selected["exports"]["events"]["path"],str(outputs[0]))
            self.assertFalse(list(parent.rglob("*.mph")))
            artifact,parent,_,_=postprocess_source_fixture(Path(directory)/"unknown",unknown=True)
            with self.assertRaisesRegex(ValueError,"SOURCE_WRITER_UNCONFIRMED"):
                select_postprocess_parent(parent,artifact)

    def test_declared_missing_csv_is_not_silently_replaced_by_cold_solve(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            artifact,parent,_,outputs=postprocess_source_fixture(Path(directory))
            outputs[0].unlink()
            with self.assertRaisesRegex(ValueError,"missing or incomplete"):
                select_postprocess_parent(parent,artifact)

    def test_frozen_only_analyzer_consumes_small_export_and_parent_is_unchanged(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_saved_postprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            selected=select_postprocess_parent(parent,artifact)
            frozen=freeze_candidate_source_closure(root/"code",artifact/"projects"/PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            with mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=AssertionError("native must not start")):
                result=execute_saved_postprocess(selected,child,frozen,{},runtime=candidate_workflow)
            self.assertEqual(result["native_launch_count"],0)
            self.assertFalse(result["parent_model_saved"])
            self.assertTrue(Path(result["analysis_receipt"]).is_file())
            self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_original_cli_child_and_finalization_resume_use_public_owner_zero_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            invoke=postprocess_public_entry(root,artifact)
            child_id="20261031_122000__analysis__python__candidate-postprocess"
            first=invoke(["--postprocess-from",str(parent),"--run-id",child_id])
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            child=artifact/"projects"/PROJECT_ROOT.name/"runs"/child_id
            summary=load_json(child/"summary.json")
            self.assertEqual(summary["scope"],"comsol_postprocessing_only")
            self.assertEqual(summary["evidence"]["native_launch_count"],0)
            self.assertEqual(summary["native_particle_solve_count"],0)
            self.assertFalse(list(child.rglob("*.mph")))
            completion=(child/"results/execution_completion.json").read_bytes()
            resumed=invoke(["--resume-finalization",str(child)])
            self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
            self.assertEqual(completion,(child/"results/execution_completion.json").read_bytes())
            self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_postprocess_failure_preserves_source_identity_and_reports_original_recovery_cli(self):
        from common.contracts.write_run_manifest import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            selected=select_postprocess_parent(parent,artifact)
            closure=freeze_candidate_source_closure(root/"code",artifact/"projects"/PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            selection_path=root/"selection.json"
            selection_path.write_text(json.dumps(selected),encoding="utf-8")
            request=child/"inputs/execution_request.json"
            request.write_text(json.dumps({"payload":{"postprocess_selection":file_record(selection_path),
                "execution_source_closure":closure}}),encoding="utf-8")
            config=child/"run_config.json"
            config.write_text(json.dumps({"schema_version":2,"inputs":{"execution_request":str(request)},
                "parameters":{},"paths":{"sentinel":"preserved"}}),encoding="utf-8")
            session=root/"session.json"
            session.write_text(json.dumps({"protected_paths":[str(child),str(parent)],"artifact_root":str(artifact)}),encoding="utf-8")
            completion=child/"results/execution_completion.json"
            (child/"results").mkdir()
            with mock.patch.object(candidate_comsol_stage,"execute_saved_postprocess",side_effect=RuntimeError("PLOT_FAILURE_SENTINEL")):
                candidate_workflow.execute_prepared_postprocess(config,session,request,completion)
            actual=load_json(completion)
            self.assertEqual(actual["status"],"failed")
            self.assertEqual(actual["summary"]["data_validity"],"unknown")
            self.assertTrue(actual["summary"]["source_identity_verified"])
            self.assertEqual(actual["exception"]["message"],"PLOT_FAILURE_SENTINEL")
            self.assertIn("--postprocess-from",actual["summary"]["recovery_action"])
            self.assertIn("--resume-finalization",actual["summary"]["resume_finalization_command"])
            self.assertEqual(load_json(config)["paths"],{"sentinel":"preserved"})
            self.assertFalse(actual["summary"]["recovery_requires_terminal_publication"])
            self.assertIn(str(parent),actual["summary"]["recovery_action"])
            # Only the consumer's unknown-writer hint is checked here; the
            # stopped/release fault matrix remains at the public validator.
            unknown=child.parent/"unknown-child"
            (unknown/"inputs").mkdir(parents=True)
            (unknown/"logs").mkdir()
            (unknown/"results").mkdir()
            unknown_config=unknown/"run_config.json"
            unknown_request=unknown/"inputs/execution_request.json"
            unknown_request.write_bytes(request.read_bytes())
            unknown_config.write_text(json.dumps({"schema_version":2,"inputs":{"execution_request":str(unknown_request)},
                "parameters":{},"paths":{"sentinel":"preserved"}}),encoding="utf-8")
            unknown_session=unknown/"session.json"
            unknown_session.write_text(json.dumps({"protected_paths":[str(unknown),str(parent)],"artifact_root":str(artifact)}),encoding="utf-8")
            def unknown_export(_selection,_root,_closure,plan,*,runtime):
                plan["postprocess_evidence"]["writer_completion_unconfirmed"]=True
                raise RuntimeError("POSTPROCESS_EXPORT_WRITER_UNCONFIRMED")
            unknown_completion=unknown/"results/execution_completion.json"
            with mock.patch.object(candidate_comsol_stage,"execute_saved_postprocess",side_effect=unknown_export):
                candidate_workflow.execute_prepared_postprocess(unknown_config,unknown_session,unknown_request,unknown_completion)
            blocked=load_json(unknown_completion)
            self.assertEqual(blocked["summary"]["recovery_action"],"inspect_original_writer_completion; retain current protections")
            self.assertFalse(blocked["summary"]["recovery_requires_terminal_publication"])
            self.assertEqual(blocked["required_output_paths"],[])

    def test_cold_dispatch_projects_actual_task_but_keeps_frozen_request_canonical(self):
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_saved_postprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            frozen=freeze_candidate_source_closure(child/"inputs/code",root/"artifacts",
                resolved_contract=PROJECT_ROOT/"config/resolved_geometry.json",
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            selection={"exports":None,"model_record":{"path":str(root/"parent/model.mph")},
                "context_record":{"path":str(root/"parent/model.mph.postprocess.json")},"parent":str(root/"parent")}
            observed=[]
            def stop(command,log,plan,receipt,role):
                observed.append(command)
                raise RuntimeError("STOP_AT_NATIVE_BOUNDARY")
            execution=root/"execution"
            execution.mkdir()
            source_execution=root/"source_execution"
            source_execution.mkdir()
            plan={"context_sha256":"a"*64,"source_execution_context":{
                "schema_version":1,"role":"run_source_execution_context","request_sha256":"a"*64,
                "child_run_directory":str(child),"execution_root":str(root),"sources":[{
                    "target_directory":selection["parent"],"execution_directory":str(source_execution),
                    "execution_alias":str(source_execution),"input_paths":[selection["model_record"]["path"],selection["context_record"]["path"]]}]}}
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution)}), \
                    mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=stop):
                with self.assertRaisesRegex(RuntimeError,"STOP_AT_NATIVE_BOUNDARY"):
                    execute_saved_postprocess(selection,child,frozen,plan,runtime=candidate_workflow)
            command=observed[0]
            self.assertEqual(command[command.index("-TaskScript")+1],str(execution/"inputs/cold_postprocess.m"))
            self.assertEqual(command[command.index("-StartupAttempts")+1],"1")
            self.assertEqual(command[command.index("-RunDir")+1],str(execution))
            request=load_json(child/"inputs/cold_request.json")
            self.assertEqual(request["output_dir"],str(child/"results"))
            self.assertEqual(request["child_run_directory"],str(child))
            self.assertEqual(request["model_path"],selection["model_record"]["path"])
            task=(child/"inputs/cold_postprocess.m").read_text(encoding="utf-8")
            self.assertIn(str(source_execution/"model.mph"),task)
            self.assertIn(str(source_execution/"model.mph.postprocess.json"),task)
            self.assertFalse((child/"results/cold_postprocess_result.json").exists())

    def test_failed_cold_export_child_reanalyzes_via_original_cli_without_model_or_comsol(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,parent,_=cold_export_failed_child_fixture(root)
            before={str(path):path.read_bytes() for folder in (science,parent) for path in folder.rglob("*") if path.is_file()}
            selected=select_postprocess_parent(parent,artifact)
            self.assertIsNone(selected["model_record"])
            self.assertEqual(len(selected["source_references"]),2)
            invoke=postprocess_public_entry(root,artifact)
            author_stage=root/"author/projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_comsol_stage.py"
            author_stage.write_text(author_stage.read_text(encoding="utf-8")+"\n# Explicit software-only cold-export/analysis-failure consumer fixture.\n_fixture_original_saved_postprocess = execute_saved_postprocess\n\ndef execute_saved_postprocess(selection, root, closure, plan, *, runtime):\n    if root.name != '20261031_123500__analysis__comsol__cold-analysis-failure':\n        return _fixture_original_saved_postprocess(selection, root, closure, plan, runtime=runtime)\n    import json, subprocess, sys\n    from types import SimpleNamespace\n    from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion\n    fake_model = Path(selection['parent'])/'inert_fixture_not_a_model.mph'\n    fake_context = Path(selection['parent'])/'inert_fixture_not_a_model.mph.postprocess.json'\n    cold = dict(selection, exports=None, model_record={'path':str(fake_model)}, context_record={'path':str(fake_context)})\n    plan['source_execution_context'] = {\n        'schema_version':1,'role':'run_source_execution_context','request_sha256':plan['context_sha256'],\n        'child_run_directory':str(root),'sources':[{'target_directory':selection['parent'],\n        'execution_directory':selection['parent'],'input_paths':[str(fake_model),str(fake_context)]}]}\n    def software_export(command, log, selected_plan, receipt_path, role):\n        # The process below is actual Python, never MATLAB/COMSOL. Its tiny data\n        # and closed release shape are explicit native-boundary fixture facts.\n        observed = subprocess.run([sys.executable,'-I','-B','-c','pass'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)\n        assert observed.returncode == 0\n        receipt={'schema_version':1,'role':role,'run_id':root.name,\n            'fixture':'SOFTWARE_ONLY_NOT_A_COMSOL_RUN',\n            'operations':[{'operation_id':'inert-software-export','observation':{'exit_confirmed':True,'returncode':observed.returncode}}],\n            'host_release':{'inherited':False,'token':'fixture-closed-release',\n            'result':{'status':'released','token':'fixture-closed-release'},'error':None}}\n        receipt_path.write_text(json.dumps(receipt),encoding='utf-8')\n        append_native_stage_completion(selected_plan['writer_completion'],receipt_path,role=role,run_id=root.name)\n        events=root/'results/comsol_detector_events_Fixture.csv'\n        events.write_bytes(Path(selection['exports']['events']['path']).read_bytes())\n        request=root/'results/comsol_detector_events_Fixture.analysis_request.json'\n        document=json.loads(Path(selection['exports']['request']['path']).read_text(encoding='utf-8'))\n        document.update(raw_events_csv=str(events),analysis_output_dir=str(root/'results/detector_analysis'))\n        request.write_text(json.dumps(document),encoding='utf-8')\n        result={'candidate_model_validation':'passed','model_path':str(fake_model),'raw_detector_events_path':str(events),\n            'analysis_request_path':str(request),'analysis_output_dir':document['analysis_output_dir']}\n        (root/'results/cold_postprocess_result.json').write_text(json.dumps(result),encoding='utf-8')\n        (root/'logs/cold_postprocess.txt').write_text('STATUS=PASS\\n',encoding='utf-8')\n        (root/'logs/inert_cold_boundary.txt').write_text('one software-only invocation\\n',encoding='utf-8')\n    def fail_analysis(*args, **kwargs):\n        raise RuntimeError('ANALYSIS_AFTER_COMPLETED_COLD_EXPORT')\n    original_analyzer=globals()['analyze_detector_request']\n    globals()['analyze_detector_request']=fail_analysis\n    try:\n        return _fixture_original_saved_postprocess(cold,root,closure,plan,\n            runtime=SimpleNamespace(_run_command=runtime._run_command,_run_managed_stage_command=software_export))\n    finally:\n        globals()['analyze_detector_request']=original_analyzer\n",encoding="utf-8")
            failed_id="20261031_123500__analysis__comsol__cold-analysis-failure"
            failed=invoke(["--postprocess-from",str(parent),"--run-id",failed_id])
            self.assertNotEqual(failed.returncode,0)
            failed_child=artifact/"projects"/PROJECT_ROOT.name/"runs"/failed_id
            failed_summary=load_json(failed_child/"summary.json")
            self.assertEqual(failed_summary["status"],"failed")
            self.assertIn("ANALYSIS_AFTER_COMPLETED_COLD_EXPORT",failed_summary["failure_reason"])
            self.assertTrue(failed_summary["evidence"]["detector_exports_ready"])
            self.assertTrue(failed_summary["recovery_requires_terminal_publication"])
            self.assertIn('--postprocess-from "'+str(failed_child)+'"',failed_summary["recovery_action"])
            self.assertTrue((failed_child/"logs/inert_cold_boundary.txt").is_file())
            self.assertEqual(load_json(failed_child/"run_manifest.json")["status"],"failed")
            failed_bytes={str(path):path.read_bytes() for path in failed_child.rglob("*") if path.is_file()}
            select_postprocess_parent(failed_child,artifact)
            run_id="20261031_124000__analysis__python__postprocess-retry"
            first=invoke(["--postprocess-from",str(failed_child),"--run-id",run_id])
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            child=artifact/"projects"/PROJECT_ROOT.name/"runs"/run_id
            summary=load_json(child/"summary.json")
            self.assertEqual(summary["evidence"]["native_launch_count"],0)
            self.assertEqual(summary["native_particle_solve_count"],0)
            completion=(child/"results/execution_completion.json").read_bytes()
            resumed=invoke(["--resume-finalization",str(child)])
            self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
            self.assertEqual(completion,(child/"results/execution_completion.json").read_bytes())
            self.assertEqual(before,{str(path):path.read_bytes() for folder in (science,parent) for path in folder.rglob("*") if path.is_file()})
            self.assertFalse(list(root.rglob("*.mph")))
            self.assertEqual(failed_bytes,{str(path):path.read_bytes() for path in failed_child.rglob("*") if path.is_file()})
            self.assertFalse((child/"logs/inert_cold_boundary.txt").exists())
            again=select_postprocess_parent(child,artifact)
            self.assertEqual(len(again["source_references"]),3)
            self.assertEqual(again["science_reference"],selected["science_reference"])
            self.assertEqual(again["export_source_reference"]["manifest_record"]["path"],str(failed_child/"run_manifest.json"))

    def test_postprocess_export_parent_rejects_missing_unknown_and_tampered_exports(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        for case in ("missing","unknown","tampered","wrong_source"):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                artifact,_,parent,events=cold_export_failed_child_fixture(Path(directory),unknown=case=="unknown",wrong_source=case=="wrong_source")
                if case=="missing":
                    events.unlink()
                elif case=="tampered":
                    content=events.read_text(encoding="utf-8")
                    events.write_text(content.replace("detector_hit","detector_bad",1),encoding="utf-8",newline="")
                with self.assertRaises((ValueError,AssertionError)):
                    select_postprocess_parent(parent,artifact)

    def test_public_request_declares_native_files_only_for_cold_scope(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            selected=preparation.select_postprocess_parent(parent,artifact)
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_ARTIFACT_ROOT":str(artifact),
                                            "MASS_SPECTROMETRY_EXECUTION_ROOT":str(root/"execution")}):
                csv_request=preparation.prepare_postprocess_request(parent,"20261031_132000__analysis__python__prepared-csv")
                self.assertNotIn("native_input_paths",csv_request["prepared"])
                cold=dict(selected,exports=None,model_record={"path":str(parent/"model.mph")},
                          context_record={"path":str(parent/"model.mph.postprocess.json")})
                # This tests request transport only. The real selector/owner,
                # not this mocked scientific selection, owns admission.
                with mock.patch.object(preparation,"select_postprocess_parent",return_value=cold):
                    cold_request=preparation.prepare_postprocess_request(parent,"20261031_133000__analysis__comsol__prepared-cold")
                self.assertEqual(cold_request["prepared"]["native_input_paths"],
                    [cold["model_record"]["path"],cold["context_record"]["path"]])
                self.assertEqual(cold_request["capacity"]["source_references"],selected["source_references"])

    def test_flat_exporter_cannot_substitute_another_science_owner(self):
        from common.contracts.capacity_ledger import record_capacity_object
        from common.contracts.write_run_manifest import file_record,publish_run_manifest
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,_,_=postprocess_source_fixture(root/"science")
            foreign_root,foreign,_,_=postprocess_source_fixture(root/"foreign")
            source=select_postprocess_parent(science,artifact)
            other=select_postprocess_parent(foreign,foreign_root)
            source["exports"]=other["exports"]
            source["export_source_reference"]=other["export_source_reference"]
            parent=artifact/"projects"/PROJECT_ROOT.name/"runs/20261031_134000__analysis__python__wrong-exporter"
            (parent/"inputs").mkdir(parents=True)
            (parent/"results").mkdir()
            selection=parent/"inputs/postprocess_source_selection.json"
            selection.write_text(json.dumps(source),encoding="utf-8")
            request=parent/"inputs/execution_request.json"
            request.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_request",
                "package":{"project":PROJECT_ROOT.name,"run_id":parent.name,"mode":"candidate_comsol_postprocess"}}),encoding="utf-8")
            config=parent/"run_config.json"
            config.write_text(json.dumps({"schema_version":2,"project":PROJECT_ROOT.name,"run_id":parent.name,
                "mode":"candidate_comsol_postprocess","project_root":str(PROJECT_ROOT),
                "inputs":{"execution_request":str(request),"postprocess_source_selection":str(selection)},
                "provenance":{"science_reference":source["science_reference"]},
                "artifact_retention":{"policy_version":1,"class":"compact","reason":None},
                "capacity_ledger_lifecycle":{"schema_version":1,"enabled":True,"artifact_root":str(artifact),"light_evidence_budget_bytes":67108864}}),encoding="utf-8")
            completion=parent/"results/execution_completion.json"
            completion.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_completion",
                "project":PROJECT_ROOT.name,"run_id":parent.name,"status":"failed","execution_request":file_record(request),
                "run_config":file_record(config),"writer_completion":{"operations":[],"resource_releases":[]},
                "summary":{"source_identity_verified":True}}),encoding="utf-8")
            publish_run_manifest(config,"failed",output_paths=[completion])
            record_capacity_object(artifact,path=parent,object_class="light_evidence",bytes_count=sum(
                path.stat().st_size for path in parent.rglob("*") if path.is_file()),owner=PROJECT_ROOT.name)
            with self.assertRaisesRegex(ValueError,"CSV exporter is not"):
                select_postprocess_parent(parent,artifact)


class CandidateAnalysisReuseTests(CandidateFixtures, unittest.TestCase):
    def test_normal_reuse_refreshes_only_changed_or_unrecorded_analysis_authority(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage
        for case in ("same","changed","missing_parent_authority"):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                _,plan=self.native_workflow_plan(root,"20261031_130000")
                observed=[]
                base=self.native_fake_executor(observed)
                def producer(stage,runtime,simion):
                    evidence=base(stage,runtime,simion)
                    if stage["stage_id"]=="comsol_candidate":
                        import csv
                        run=Path(runtime["run_root"])
                        events=run/"results/events.csv"
                        with events.open("w",encoding="utf-8",newline="") as stream:
                            writer=csv.writer(stream)
                            writer.writerow(["Ion","TofUs","XMm","YMm","Hit"])
                            writer.writerows((i+1,40+i*.00001,0,0,True) for i in range(100))
                        request=run/"results/analysis_request.json"
                        request.write_text(json.dumps({"schema_version":1,"role":"oatof_comsol_detector_events_analysis_request",
                            "solver":"COMSOL","label":"ReuseFixture","nominal_mass_Da":524,"raw_events_csv":str(events),
                            "analysis_output_dir":str(run/"results/analysis"),"event_extraction":"solver_native_detector_crossing_or_freeze",
                            "aggregate_metrics_owner":"python_reference_analysis"}),encoding="utf-8")
                        receipt=candidate_comsol_stage.analyze_detector_request(request,runtime["execution_source_closure"],
                            run/"logs/analysis.log",runtime=candidate_workflow)
                        evidence.update(analysis_request=str(request),analysis_receipt=str(receipt))
                        if case!="missing_parent_authority":
                            evidence["analysis_contract"]=frozen_source_path(runtime["execution_source_closure"],
                                "projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json")
                    return evidence
                parent,_=run_candidate_workflow(plan,sys.executable,stage_executor=producer)
                before={path:path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                original_freeze=preparation.freeze_candidate_source_closure
                analysis=root/"explicit_analysis.json"
                document=load_json(PROJECT_ROOT/"config/analysis_contract.json")
                document["kde"]["bandwidth_multiplier"]=1.2
                analysis.write_text(json.dumps(document),encoding="utf-8")
                def freeze(*args,**kwargs):
                    if case=="changed":
                        kwargs["analysis_contract"]=analysis
                    return original_freeze(*args,**kwargs)
                with mock.patch.object(preparation,"freeze_candidate_source_closure",side_effect=freeze):
                    _,child_plan=self.native_workflow_plan(root,"20261031_131000")
                child_observed=[]
                with mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=AssertionError("COMSOL must not start")), \
                        mock.patch.object(candidate_comsol_stage,"analyze_detector_request",wraps=candidate_comsol_stage.analyze_detector_request) as analyze:
                    child,summary=run_candidate_workflow(child_plan,sys.executable,
                        stage_executor=self.native_fake_executor(child_observed),reuse_parent=parent,reuse_through="cad_candidate")
                stage=next(item for item in summary["stages"] if item["stage_id"]=="comsol_candidate")
                self.assertEqual(child_observed,["static_inputs","structural_acceptance"])
                self.assertEqual(stage["native_execution"],"reused")
                self.assertEqual(stage["analysis_execution"],"reused" if case=="same" else "executed")
                self.assertEqual(analyze.call_count,0 if case=="same" else 1)
                self.assertEqual({path:path.read_bytes() for path in before},before)
                if case!="same":
                    self.assertTrue(Path(stage["evidence"]["analysis_receipt"]).is_relative_to(child))


if __name__ == "__main__":
    unittest.main()


class CandidateCausalPhaseTests(CandidateFixtures, unittest.TestCase):
    def test_actual_engine_binds_four_phase_owners_and_successor_flattens_origins(self):
        from common.contracts.write_run_manifest import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan_path = self.native_workflow_plan(root, '20261031_201001')
            original = self.native_fake_executor([])
            def produce(stage, plan, executable):
                evidence = original(stage, plan, executable)
                if stage['stage_id'] == 'comsol_candidate':
                    run = Path(plan['run_root'])
                    events = run/'results/software_detector_events.csv'
                    events.write_text('Ion,Hit,Status\n'+''.join(f'{i},1,detector_hit\n' for i in range(1,101)), encoding='utf-8')
                    request = run/'results/software.analysis_request.json'
                    request.write_text(json.dumps({'role':'oatof_comsol_detector_events_analysis_request','raw_events_csv':str(events),'analysis_output_dir':str(run/'results/analysis')}), encoding='utf-8')
                    receipt = run/'results/software_analysis_receipt.json'
                    receipt.write_text(json.dumps({'raw_events':file_record(events)}), encoding='utf-8')
                    evidence.update(analysis_request=str(request), analysis_receipt=str(receipt),
                        analysis_contract=frozen_source_path(plan['execution_source_closure'], 'projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json'))
                return evidence
            parent, _ = workflow.run_candidate_workflow(plan_path, sys.executable, stage_executor=produce)
            before = {path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            origins = workflow._comsol_phase_sources(parent)
            self.assertEqual(set(origins), {'native','export','analysis','sync'})
            self.assertEqual({row['owner_directory'] for row in origins.values()}, {str(parent)})
            _, child_plan = self.native_workflow_plan(root, '20261031_201002')
            calls = []
            model = Path(next(stage for stage in load_json(parent/'summary.json')['stages'] if stage['stage_id']=='comsol_candidate')['evidence']['model'])
            reads = []
            original_open = Path.open
            def track_open(path, *args, **kwargs):
                mode = args[0] if args else kwargs.get('mode','r')
                if path.resolve() == model.resolve() and 'r' in mode:
                    reads.append(str(path))
                return original_open(path, *args, **kwargs)
            with mock.patch.object(Path, 'open', track_open):
                child, summary = workflow.run_candidate_workflow(child_plan, sys.executable,
                    stage_executor=self.native_fake_executor(calls), reuse_parent=parent, reuse_through='cad_candidate')
            self.assertEqual(len(reads), 1, reads)
            self.assertEqual(calls, ['static_inputs','structural_acceptance'])
            self.assertEqual(summary['status'], 'success')
            child_origins = workflow._comsol_phase_sources(child)
            self.assertEqual({row['owner_directory'] for row in child_origins.values()}, {str(parent)})
            self.assertEqual(before, {path:path.read_bytes() for path in before})

    def test_analysis_implementation_change_runs_only_frozen_csv_analysis(self):
        from common.contracts.write_run_manifest import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import candidate_source_closure as source_owner
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, reference, _, _ = postprocess_source_fixture(root/'event_fixture')
            reference_request = next((reference/'results').glob('*.analysis_request.json'))
            reference_document = load_json(reference_request)
            _, first_plan = self.native_workflow_plan(root, '20261031_202001')
            original = self.native_fake_executor([])
            def produce(stage, plan, executable):
                evidence = original(stage, plan, executable)
                if stage['stage_id'] == 'comsol_candidate':
                    run = Path(plan['run_root'])
                    events = run/'results/events.csv'
                    events.write_bytes(Path(reference_document['raw_events_csv']).read_bytes())
                    document = dict(reference_document, raw_events_csv=str(events), analysis_output_dir=str(run/'results/analysis'))
                    request = run/'results/events.analysis_request.json'
                    request.write_text(json.dumps(document), encoding='utf-8')
                    receipt = run/'results/analysis_receipt.json'
                    receipt.write_text(json.dumps({'raw_events':file_record(events)}), encoding='utf-8')
                    evidence.update(analysis_request=str(request), analysis_receipt=str(receipt),
                        analysis_contract=frozen_source_path(plan['execution_source_closure'], 'projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json'))
                return evidence
            parent, _ = workflow.run_candidate_workflow(first_plan, sys.executable, stage_executor=produce)
            before = {path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            source_id = 'projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis_core.py'
            old_source_path = source_owner._source_path
            changed = root/'current_analysis.py'
            changed.write_bytes(old_source_path(source_id).read_bytes()+b'\n# explicit analysis-only source fixture revision\n')
            def author_source(identifier):
                return changed if identifier == source_id else old_source_path(identifier)
            with mock.patch.object(source_owner, '_source_path', side_effect=author_source):
                _, second_plan = self.native_workflow_plan(root, '20261031_202002')
                calls = []
                child, summary = workflow.run_candidate_workflow(second_plan, sys.executable,
                    stage_executor=self.native_fake_executor(calls), reuse_parent=parent, reuse_through='cad_candidate')
                self.assertEqual(calls, ['static_inputs','structural_acceptance'])
                comsol = next(stage for stage in summary['stages'] if stage['stage_id']=='comsol_candidate')
                self.assertEqual(comsol['phase_execution'], {'native':'reused','export':'reused','analysis':'executed','sync':'reused'})
                self.assertTrue(Path(comsol['evidence']['analysis_receipt']).is_relative_to(child))
                self.assertEqual(workflow._comsol_phase_sources(child)['analysis']['owner_directory'],str(child))
                _, third_plan = self.native_workflow_plan(root, '20261031_202003')
                grandchild, latest = workflow.run_candidate_workflow(third_plan, sys.executable,
                    stage_executor=self.native_fake_executor([]), reuse_parent=child, reuse_through='cad_candidate')
                third = next(stage for stage in latest['stages'] if stage['stage_id']=='comsol_candidate')
                self.assertEqual(set(third['phase_execution'].values()), {'reused'})
                self.assertEqual(third['evidence']['analysis_receipt'],comsol['evidence']['analysis_receipt'])
                self.assertEqual(workflow._comsol_phase_sources(grandchild)['native']['owner_directory'],str(parent))
            self.assertEqual(before, {path:path.read_bytes() for path in before})

    def _observed_raw_save_fixture(self, stage, plan, root, *, exit_code=1, save_state="raw_complete"):
        """Actual registered Python writer, never a COMSOL model or solve."""
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
        run = Path(plan['run_root'])
        config = load_json(run/'run_config.json')
        model = Path(stage['model_path'])
        context = {'schema_version':1,'role':'oatof_saved_particle_solution','solution_tag':'sol2','dataset_tag':'pdset1',
            'native_particle_solve_count':1,'particle_count':100,'solution_times_s':[0,1e-6],
            'saved_model_bytes':len(b'opaque software fixture; not a COMSOL model'),
            'model_save_state':save_state,
            'contract_path':config['inputs']['candidate_resolved_geometry.json'],'source_path':config['inputs']['candidate_particle_table']}
        payload=root/'inert_payload.json'
        payload.write_text(json.dumps({'model':str(model),'context':context,'report':stage['report_path'],'exit_code':exit_code}),encoding='utf-8')
        ready=root/'inert_ready'
        worker=root/'inert_writer.py'
        worker.write_text("import json,sys,time\nfrom pathlib import Path\nwhile not Path(sys.argv[2]).exists():time.sleep(.01)\np=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\nm=Path(p['model']);m.parent.mkdir(parents=True,exist_ok=True);m.write_bytes(b'opaque software fixture; not a COMSOL model')\nPath(str(m)+'.postprocess.json').write_text(json.dumps(p['context']),encoding='utf-8')\nPath(p['report']).write_text('STATUS='+('FAIL' if p['exit_code'] else 'PASS')+'\\nERROR=SAVED_BEFORE_EXTRACT\\n',encoding='utf-8')\nraise SystemExit(p['exit_code'])\n",encoding='utf-8')
        host=REPO_ROOT/'common/host_execution_lease.ps1'
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        script=("$ErrorActionPreference='Stop'; Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue; "
            "$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH="+quote(root/'fixture_host.sqlite3')+"; . "+quote(host)+"; "
            "$b=Get-HostResourceBudget -Role GATE -Stage software_validation;$b.cpu_cores=1;$b.memory_bytes=256MB;"
            "$lease=Enter-HostResourceStage -Role GATE -Stage software_validation -Budget $b;"
            "$p=$null;try{$p=Start-Process -FilePath "+quote(sys.executable)+" -ArgumentList @('-I','-B',"+quote('"'+str(worker)+'"')+","+quote('"'+str(payload)+'"')+","+quote('"'+str(ready)+'"')+") -WorkingDirectory "+quote(root)+" -WindowStyle Hidden -PassThru;"
            "$lease=Register-HostResourceProcess -Lease $lease -ProcessId $p.Id;"
            "[IO.File]::WriteAllText("+quote(ready)+",'ready');"
            "$lease=Wait-HostResourceProcess -Lease $lease -Process $p;"
            "$observation=@{exit_confirmed=[bool]$p.HasExited;returncode=[int]$p.ExitCode};"
            "}finally{[IO.File]::WriteAllText("+quote(ready)+",'ready');if($null-ne$p){$p.WaitForExit()};"
            "$released=Exit-HostResourceStage -Lease $lease -PassThru};"
            "Write-Output ('RECEIPT_JSON='+(@{observation=$observation;host_release=@{inherited=[bool]$lease.inherited;token=$lease.token;result=$released;error=$null}}|ConvertTo-Json -Depth 16 -Compress))")
        observed=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',script],cwd=REPO_ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(observed.returncode,0,observed.stdout+observed.stderr)
        facts=json.loads(next(line.removeprefix('RECEIPT_JSON=') for line in observed.stdout.splitlines() if line.startswith('RECEIPT_JSON=')))
        self.assertEqual(facts['observation'],{'exit_confirmed':True,'returncode':exit_code})
        self.assertFalse(facts['host_release']['inherited'])
        self.assertEqual(facts['host_release']['result']['status'],'released')
        receipt=run/'logs/comsol_build_completion.json'
        receipt.write_text(json.dumps({'schema_version':1,'role':'comsol_launcher_completion','run_id':run.name,
            'fixture':'SOFTWARE_ONLY_REGISTERED_PYTHON_WRITER_NOT_COMSOL',
            'operations':[{'operation_id':'actual-inert-python-writer','observation':facts['observation']}],
            'host_release':facts['host_release']}),encoding='utf-8')
        plan['writer_completion']={'operations':[],'resource_releases':[]}
        append_native_stage_completion(plan['writer_completion'],receipt,role='comsol_launcher_completion',run_id=run.name)
        return model

    def test_stopped_raw_save_then_export_failure_keeps_native_receipt_and_original_failure(self):
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan_path = self.native_workflow_plan(root, '20261031_203001')
            original = self.native_fake_executor([])
            def after_save(stage, plan, executable):
                if stage['stage_id'] != 'comsol_candidate':
                    return original(stage, plan, executable)
                from types import SimpleNamespace
                from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_comsol_native_build
                def fail_after_save(*args,**kwargs):
                    self._observed_raw_save_fixture(stage,plan,root)
                    raise RuntimeError('SAVED_BEFORE_EXTRACT')
                return execute_comsol_native_build(stage,plan,runtime=SimpleNamespace(
                    _run_managed_stage_command=fail_after_save,
                    _record_candidate_native_completion=workflow._record_candidate_native_completion))
            with self.assertRaisesRegex(workflow.CandidateWorkflowError,'SAVED_BEFORE_EXTRACT') as failure:
                workflow.run_candidate_workflow(plan_path,sys.executable,stage_executor=after_save)
            parent=failure.exception.run_root
            summary=load_json(parent/'summary.json')
            self.assertEqual(summary['status'],'failed')
            main=next(row for row in summary['stages'] if row['stage_id']=='comsol_candidate')
            self.assertEqual(main['status'],'failed')
            native=next(row for row in summary['stages'] if row['stage_id']=='comsol_native')
            self.assertEqual(native['status'],'success')
            self.assertEqual(workflow._resolve_reuse_stage_owner(parent,'comsol_candidate')['receipt_stage_id'],'comsol_native')
            origins=workflow._comsol_phase_sources(parent)
            self.assertEqual(origins['native']['status'],'success')
            self.assertEqual({origins[name]['status'] for name in ('export','analysis','sync')},{'pending'})
            # Consume the failed parent's successful native receipt through
            # the real public validator: never require a false whole-stage PASS.
            before={path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            _,child_plan_path=self.native_workflow_plan(root,'20261031_203002')
            child=start_candidate_run(child_plan_path)
            child_plan=load_json(child/'candidate_workflow_plan.json')
            original(child_plan['stages'][0],child_plan,sys.executable)
            context=workflow._stage_context(child,child_plan,'comsol_candidate',sys.executable)
            workflow._declare_context_inputs(child,{'comsol_candidate':context},provenance={'comsol_candidate'})
            receipt=load_json(parent/'stage_receipts/comsol_native.json')['outputs']['model']
            model=parent/receipt['path']
            with workflow.guarded_file_identity(model,expected_bytes=receipt['bytes'],expected_sha256=receipt['sha256']) as guard:
                proof=workflow.validate_and_write_stage_reuse(child,parent_run_root=parent,
                    project=PROJECT_ROOT.name,stage_contexts={'comsol_native':context},
                    allow_provisional_manifest=True,identity_guards={model.resolve():guard},
                    provenance_input_name='stage_reuse_comsol_candidate_provenance')
            proof=load_json(proof)
            self.assertEqual(proof['parent_run_status'],'failed')
            self.assertEqual([row['stage_id'] for row in proof['reused_stages']],['comsol_native'])
            self.assertEqual(before,{path:path.read_bytes() for path in before})

    def test_producer_native_and_full_receipts_share_one_live_model_identity(self):
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            _, plan_path=self.native_workflow_plan(root,'20261031_204001')
            model_path=Path(next(stage for stage in load_json(plan_path)['stages'] if stage['stage_id']=='comsol_candidate')['model_path'])
            calls=[];receipt_reads=[];reads=[]
            original=self.native_fake_executor(calls)
            original_open=Path.open
            original_receipt=workflow.write_stage_receipt
            def track_open(path,*args,**kwargs):
                mode=args[0] if args else kwargs.get('mode','r')
                if path.resolve()==model_path.resolve() and 'r' in mode:
                    reads.append(str(path))
                return original_open(path,*args,**kwargs)
            def write_receipt(*args,**kwargs):
                before=len(reads)
                result=original_receipt(*args,**kwargs)
                if kwargs['stage_id'] in {'comsol_native','comsol_candidate'}:
                    receipt_reads.append((kwargs['stage_id'],before,len(reads)))
                return result
            def produce(stage,plan,executable):
                if stage['stage_id']!='comsol_candidate':
                    return original(stage,plan,executable)
                model=self._observed_raw_save_fixture(stage,plan,root,exit_code=0)
                self.assertTrue(workflow._record_candidate_native_completion(stage,plan))
                run=Path(plan['run_root'])
                csv=run/'results/software.csv'
                csv.write_text('Ion,Hit,Status\n'+''.join(f'{index},1,detector_hit\n' for index in range(1,101)),encoding='utf-8')
                request=run/'results/software.analysis_request.json'
                request.write_text(json.dumps({'role':'oatof_comsol_detector_events_analysis_request','raw_events_csv':str(csv)}),encoding='utf-8')
                analysis=run/'results/software_analysis_receipt.json';analysis.write_text('{}',encoding='utf-8')
                sync=run/'logs/software_sync.txt';sync.write_text('STATUS=PASS\n',encoding='utf-8')
                return {'model':str(model),'build_report':stage['report_path'],'sync_report':str(sync),
                    'analysis_request':str(request),'analysis_receipt':str(analysis),
                    'analysis_contract':frozen_source_path(plan['execution_source_closure'],'projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json')}
            with mock.patch.object(Path,'open',track_open),mock.patch.object(workflow,'write_stage_receipt',side_effect=write_receipt):
                parent,summary=workflow.run_candidate_workflow(plan_path,sys.executable,stage_executor=produce)
            self.assertEqual(summary['status'],'success')
            self.assertEqual([row[0] for row in receipt_reads],['comsol_native','comsol_candidate'])
            self.assertEqual([(before,after) for _,before,after in receipt_reads],[(1,1),(1,1)])
            native=load_json(parent/'stage_receipts/comsol_native.json')['outputs']['model']
            complete=load_json(parent/'stage_receipts/comsol_candidate.json')['outputs']['model']
            self.assertEqual((native['bytes'],native['sha256']),(complete['bytes'],complete['sha256']))
            print('PRODUCER_MODEL_READS='+json.dumps({'guard_and_two_receipts':1,'including_terminal_manifest':len(reads)}),flush=True)
            self.assertEqual(len(reads),2,'one producer identity plus the independent terminal manifest boundary')

    def test_normal_failed_export_parent_uses_original_cli_csv_only_without_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,parent,_=cold_export_failed_child_fixture(root,normal_phase=True)
            # The already exported data, original contract and source are enough.
            # Removing only this explicit opaque fixture model happens before
            # the parent byte snapshot; no production run or solver is touched.
            (science/'comsol/model.mph').unlink()
            before={path:path.read_bytes() for owner in (science,parent) for path in owner.rglob('*') if path.is_file()}
            invoke=postprocess_public_entry(root,artifact)
            child_id='20261031_205001__analysis__python__normal-export-csv'
            result=invoke(['--postprocess-from',str(parent),'--run-id',child_id])
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            child=artifact/'projects'/PROJECT_ROOT.name/'runs'/child_id
            summary=load_json(child/'summary.json')
            self.assertEqual(summary['evidence']['native_launch_count'],0)
            self.assertFalse(list(child.rglob('*.mph')))
            completion=(child/'results/execution_completion.json').read_bytes()
            recovered=invoke(['--resume-finalization',str(child)])
            self.assertEqual(recovered.returncode,0,recovered.stdout+recovered.stderr)
            self.assertEqual(completion,(child/'results/execution_completion.json').read_bytes())
            self.assertEqual(before,{path:path.read_bytes() for path in before})


    def test_report_and_cleanup_do_not_change_native_but_field_and_task_inputs_do(self):
        from common.contracts.machine_contracts import sha256
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import candidate_comsol_source_phases
        with tempfile.TemporaryDirectory() as temporary:
            _,path=self.native_workflow_plan(Path(temporary),'20261031_213001')
            closure=load_json(path)['execution_source_closure']
            original=candidate_comsol_source_phases(closure)
            code=Path(closure['code_root'])
            def replace_source(identifier,transform):
                source=code/identifier
                text=source.read_text(encoding='utf-8')
                source.write_text(transform(text),encoding='utf-8',newline='\n')
                record=next(row for row in closure['sources'] if row['source_id']==identifier)
                record.update(bytes=source.stat().st_size,sha256=sha256(source))
            prefix='projects/single_reflection_oa_tof_mass_analyzer/'
            replace_source(prefix+'comsol/oatof_report_model_timing.m',lambda text:text+'\n% display-only change\n')
            replace_source(prefix+'workflows/design_candidate/run_candidate_workflow.py',lambda text:text+'\n# cleanup presentation only\n')
            self.assertEqual(candidate_comsol_source_phases(closure),original)
            replace_source(prefix+'comsol/oatof_build_saved_particle_solution.m',
                lambda text:text.replace("es.selection.named('sel_vac');","es.selection.named('sel_all');"))
            field_changed=candidate_comsol_source_phases(closure)
            self.assertNotEqual(field_changed['native'],original['native'])
            replace_source(prefix+'workflows/design_candidate/candidate_comsol_stage.py',
                lambda text:text.replace('return "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m", environment',
                    'environment["OATOF_CANDIDATE_CONTRACT_PATH"]="different-science"\n    return "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m", environment'))
            task_changed=candidate_comsol_source_phases(closure)
            self.assertNotEqual(task_changed['native']['dispatch'],field_changed['native']['dispatch'])

    def test_real_normal_native_and_sync_commands_consume_unique_task_environment_builders(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as temporary:
            _,path=self.native_workflow_plan(Path(temporary),'20261031_213002')
            plan=load_json(path);stage=next(row for row in plan['stages'] if row['stage_id']=='comsol_candidate')
            calls=[];publications=[]
            def observed(command,log,actual_plan,completion,role,environment):
                report=Path(command[command.index('-ReportPath')+1]);report.parent.mkdir(parents=True,exist_ok=True)
                report.write_text('STATUS=PASS\n',encoding='utf-8')
                calls.append((command,environment,role))
            runtime=SimpleNamespace(_run_managed_stage_command=observed,
                _record_candidate_native_completion=lambda *args:publications.append('stopped-raw-proof-requested') or True)
            adapter.execute_comsol_native_build(stage,plan,runtime=runtime)
            adapter.execute_comsol_model_sync(stage,plan,runtime=runtime)
            self.assertEqual(len(calls),2)
            self.assertEqual(publications,['stopped-raw-proof-requested'])
            closure=plan['execution_source_closure']
            for actual,builder in zip(calls,(adapter.comsol_native_inputs,adapter.comsol_sync_inputs)):
                task,environment=builder(stage,closure)
                self.assertEqual(actual[0][actual[0].index('-TaskScript')+1],frozen_source_path(closure,task))
                self.assertEqual(actual[1],environment)
                self.assertEqual(actual[2],'comsol_launcher_completion')
                self.assertIn('-RunDir',actual[0])


    def test_actual_formal_consumer_preserves_per_stage_cross_root_proofs_and_rejects_owner_swap(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);inputs=root/'formal/inputs';inputs.mkdir(parents=True)
            candidate=root/'candidate';candidate.mkdir()
            config={'inputs':{},'provenance':{'stage_reuse':{}}}
            original_paths=[];model=None
            for index,stage_id in enumerate(('comsol_candidate','simion_candidate')):
                owner=root/f'root{index}'/'artifacts/projects/p/runs'/f'20261031_22000{index}__sim__cross__owner'
                owner.mkdir(parents=True)
                manifest=owner/'run_manifest.json';manifest.write_text(json.dumps({'run_id':owner.name,'owner':index}),encoding='utf-8')
                source=owner/'same.dat';source.write_bytes(b'original-model' if index==0 else b'original-simion')
                if index==0:model=source
                proof=candidate/f'{stage_id}.json'
                proof.write_text(json.dumps({'parent_run_id':owner.name,'parent_manifest':file_record(manifest),
                    'reused_stages':[{'stage_id':'comsol_native' if index==0 else stage_id,
                        'outputs':{'model':file_record(source)}}]}),encoding='utf-8')
                name=f'stage_reuse_{stage_id}_provenance'
                config['inputs'][name]=str(proof)
                config['inputs'][f'stage_reuse_{stage_id}_source_manifest']=str(manifest)
                config['provenance']['stage_reuse'][stage_id]=file_record(proof)
                original_paths.extend((manifest,source,proof))
            config_path=candidate/'run_config.json';config_path.write_text(json.dumps(config),encoding='utf-8')
            before={path:path.read_bytes() for path in original_paths}
            script=root/'formal_probe.ps1'
            text=r"""$ErrorActionPreference='Stop'
. '@@SUPPORT@@'
$source=Get-Content -Raw -LiteralPath '@@FORMAL@@'
$first=$source.IndexOf('$reuseInputs = [ordered]@{}')
$last=$source.IndexOf('$candidateSimion = Join-Path',$first)
if($first-lt0-or$last-le$first){throw 'Formal consumer boundary missing'}
$consumer=[ScriptBlock]::Create($source.Substring($first,$last-$first))
$candidateConfig=Get-Content -Raw '@@CONFIG@@'|ConvertFrom-Json
$comsolStage=@([pscustomobject]@{execution='reused'})
$candidateRoot='@@CANDIDATE@@';$candidateMphSource='@@MODEL@@'
$inputDir='@@INPUTS@@'
& $consumer
$swap=Get-Content -Raw '@@CONFIG@@'|ConvertFrom-Json
$swap.inputs.stage_reuse_comsol_candidate_source_manifest=$swap.inputs.stage_reuse_simion_candidate_source_manifest
$candidateConfig=$swap
$rejected=$false;$reason=$null
try{& $consumer}catch{$rejected=$true;$reason=$_.Exception.Message}
[ordered]@{rejected=$rejected;reason=$reason;copied=@(Get-ChildItem -LiteralPath $inputDir -File|Select-Object -ExpandProperty Name)}|ConvertTo-Json -Depth 8 -Compress
"""
            values={'SUPPORT':str(REPO_ROOT/'common/contracts/run_artifact_support.ps1'),
                'FORMAL':str(PROJECT_ROOT/'workflows/formal_reference/run_formal_validation.ps1'),
                'CONFIG':str(config_path),'CANDIDATE':str(candidate),'MODEL':str(model),'INPUTS':str(inputs)}
            for key,value in values.items():text=text.replace('@@'+key+'@@',value.replace("'","''"))
            script.write_text(text,encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-File',str(script)],cwd=REPO_ROOT,
                capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            observed=json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(observed['rejected'])
            self.assertIn('original owner',observed['reason'])
            self.assertIn('candidate_stage_reuse_comsol_candidate_source_manifest.json',observed['copied'])
            self.assertIn('candidate_stage_reuse_simion_candidate_source_manifest.json',observed['copied'])
            self.assertEqual(before,{path:path.read_bytes() for path in before})



    def test_same_size_gui_save_failure_is_unknown_and_does_not_publish_native(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            _,plan_path=self.native_workflow_plan(root,'20261031_223001')
            original=self.native_fake_executor([])
            def execute(stage,plan,executable):
                if stage['stage_id']!='comsol_candidate':return original(stage,plan,executable)
                def save_failed(*args,**kwargs):
                    self._observed_raw_save_fixture(stage,plan,root,save_state='gui_update_started')
                    raise RuntimeError('GUI_SAVE_PRIMARY')
                return adapter.execute_comsol_native_build(stage,plan,runtime=SimpleNamespace(
                    _run_managed_stage_command=save_failed,
                    _record_candidate_native_completion=candidate_workflow._record_candidate_native_completion))
            with self.assertRaisesRegex(CandidateWorkflowError,'GUI_SAVE_PRIMARY') as failed:
                run_candidate_workflow(plan_path,sys.executable,stage_executor=execute)
            parent=failed.exception.run_root;summary=load_json(parent/'summary.json')
            self.assertEqual(summary['data_validity'],'unknown')
            self.assertEqual(summary['model_save_status'],'unknown')
            self.assertEqual(summary['scientific_result'],'not_evaluated_save_incomplete')
            self.assertEqual(summary['candidate_decision'],'no_candidate_decision')
            self.assertEqual(summary['failure_substage'],'gui_model_save')
            self.assertIn('--postprocess-from',summary['recovery_action'])
            self.assertFalse((parent/'stage_receipts/comsol_native.json').exists())
            self.assertNotIn('comsol_native',[row['stage_id'] for row in summary['stages']])
            self.assertIn('MODEL_SAVE_COMPLETION_UNKNOWN',' '.join(getattr(failed.exception,'__notes__',[])))

    def test_cold_save_marker_rejects_unfinished_model_but_keeps_csv_and_bound_legacy_completion(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for label,state,events,legacy,accepted in (
                    ('started','gui_update_started',False,False,False),
                    ('complete','gui_update_complete',False,False,True),
                    ('csv','gui_update_started',True,False,True),
                    ('legacy',None,False,True,True),
                    ('missing',None,False,False,False)):
                with self.subTest(label=label):
                    scope=root/label;scope.mkdir()
                    artifact,parent,_,_=postprocess_source_fixture(scope,cold=not events,retain_model=events,
                        save_state=state,legacy_save_complete=legacy)
                    before={path:path.read_bytes() for path in parent.rglob('*') if path.is_file()}
                    if accepted:
                        selected=select_postprocess_parent(parent,artifact)
                        self.assertEqual(selected['exports'] is not None,events)
                    else:
                        with self.assertRaisesRegex(ValueError,'MODEL_SAVE_COMPLETION_'):
                            select_postprocess_parent(parent,artifact)
                    self.assertEqual(before,{path:path.read_bytes() for path in before})
