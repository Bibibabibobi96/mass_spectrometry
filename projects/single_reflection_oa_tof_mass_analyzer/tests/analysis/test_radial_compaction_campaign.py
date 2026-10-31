from __future__ import annotations

import copy
from contextlib import contextmanager, ExitStack
import json
import sys
import inspect
import shutil
import subprocess
import tempfile
import unittest
import pandas as pd
from pathlib import Path
from unittest.mock import patch
from common.contracts.artifact_retention import apply_retention
from common.contracts.write_run_manifest import build_run_manifest, publish_terminal_state


PROJECT_ROOT = Path(__file__).resolve().parents[2]
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction import run_campaign as radial
from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign import (
    NUMERICS_PATH,
    _assert_only_allowed_changes,
    _overrides,
    _run_parallel_flights,
)


def managed_process_fixture(exit_code: int = 0) -> dict:
    """Synthetic protocol data; these identifiers are never real process evidence."""
    return {"schema_version": 1, "role": "repository_managed_python_completion", "software_fixture": True,
            "launcher_process_id": 101, "worker_process_id": 102, "worker_started_at_utc_ticks": 103,
            "ownership_confirmed": True, "worker_exit_confirmed": True, "launcher_exit_confirmed": True,
            "stdout_drained": True, "stderr_drained": True, "exit_code": exit_code}


class RadialCompactionCampaignTests(unittest.TestCase):
    def test_default_owner_result_is_retained_and_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "20261029_120000__test__simion__retained"
            request = {"package": {"run_id": run_id}, "payload": {"pa_handoff_output": None}}
            expected = root / "scratch" / "workflow_results" / run_id / "result.json"
            def owner(command, **kwargs):
                self.assertEqual(Path(command[command.index("-ResultPath") + 1]), expected)
                expected.write_text('{"status":"failed"}', encoding="utf-8")
                kwargs["stderr"].write_text("owner failure", encoding="utf-8")
                return subprocess.CompletedProcess(command, 1), None
            with patch.object(radial, "ARTIFACT_ROOT", root), patch.object(radial, "run_observed_process", side_effect=owner) as launch:
                with self.assertRaisesRegex(RuntimeError, "owner failure"):
                    radial._invoke_workflow_owner(request)
                self.assertEqual(radial.load_json(expected)["status"], "failed")
                with self.assertRaisesRegex(ValueError, "already exists"):
                    radial._invoke_workflow_owner(request)
                self.assertEqual(launch.call_count, 1)

    def test_finalization_uses_frozen_request_and_retained_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "20261029_120000__test__simion__finalize"
            request_path = root / "runs" / run_id / "inputs" / "execution_request.json"
            request_path.parent.mkdir(parents=True)
            request_path.write_text(json.dumps({"package": {"project": radial.PROJECT_ID,
                "mode": "simion_radial_compaction"}, "payload": {}}), encoding="utf-8")
            result_path = root / "scratch" / "workflow_results" / run_id / "result.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text("{}", encoding="utf-8")
            def owner(command, **kwargs):
                self.assertIn("-ResumeFinalization", command)
                self.assertEqual(Path(command[command.index("-RequestPath") + 1]), request_path)
                self.assertEqual(Path(command[command.index("-ResultPath") + 1]),
                                 root / "scratch" / "workflow_results" / run_id / "result.json")
                return subprocess.CompletedProcess(command, 0), None
            with patch.object(radial, "ARTIFACT_ROOT", root), patch.object(radial, "run_observed_process", side_effect=owner), \
                    patch.object(sys, "argv", ["run_campaign", "--run-id", run_id, "--resume-finalization"]):
                radial.main()

    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(
            (PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8")
        )
        cls.config = json.loads(
            (PROJECT_ROOT / "config" / "radial_compaction_campaign.json").read_text(
                encoding="utf-8"
            )
        )

    @contextmanager
    def software_campaign(self, root: Path):
        """Run the real campaign driver with explicit software-only native fixtures."""
        campaign = copy.deepcopy(self.config)
        campaign["radius_screen"] = campaign["radius_screen"][:2]
        campaign["ring_count_compensation"].update(
            target_case_id=campaign["radius_screen"][0]["case_id"],
            execute_when_target_fails=False, cases=[], ideal_field_diagnostic_case_ids=[],
        )
        campaign["ideal_field_attribution"]["execute_for_failed_radius_cases"] = False
        ions = "software fixture; not a SIMION ion population\n"
        reference = root / "reference"
        reference.mkdir()
        reference_summary, reference_particles = reference / "summary.json", reference / "particles.csv"
        reference_summary.write_text("{}", encoding="utf-8")
        reference_particles.write_text(ions, encoding="utf-8")
        campaign["fixed_contract"]["particle_table_sha256"] = radial.sha256(reference_particles)
        config_path = root / "campaign.json"
        config_path.write_text(json.dumps(campaign), encoding="utf-8")
        template = root / "runs/20261028_110000__build__simion__radial-template"
        source = root / "runs/20261028_105000__test__simion__radial-layout/simion"
        source.mkdir(parents=True)
        for extension in ("iob", "con"):
            (source / f"layout.{extension}").write_text("software-only layout fixture", encoding="utf-8")
        template_inputs = {"source_iob": str(source / "layout.iob"), "source_con": str(source / "layout.con")}
        radial._write_json(template / "run_config.json", {
            "role": "oa_tof_simion_candidate_layout_template_build", "project": radial.PROJECT_ID,
            "mode": "candidate_layout_template_build", "run_id": template.name,
            "template_role": "oa_tof_candidate_simion_layout_template", "inputs": template_inputs,
            "input_sha256": {key: radial.sha256(Path(path)) for key, path in template_inputs.items()},
        })
        radial._write_json(template / "summary.json", {
            "role": "oa_tof_simion_candidate_layout_template_build_summary", "status": "success",
            "runtime_structure_verified": True, "particle_fly_executed": False, "formal_modified": False,
        })
        radial._write_json(template / "run_manifest.json", {"status": "success", "run_id": template.name,
            "inputs": {key: radial.file_record(Path(path)) for key, path in template_inputs.items()}})
        (template / "simion_layout_runtime_report.txt").write_text(
            "STATUS=PASS INSTANCE_COUNT=4 TEMPLATE_STRUCTURE_ONLY=true\nsoftware fixture", encoding="utf-8")
        runtime_path = root / "candidate_runtime.json"
        radial._write_json(runtime_path, {"role": "oa_tof_candidate_runtime", "simion_template_run_id": template.name})
        control = {"native_fail": set(), "native_incomplete": set(), "analysis_fail": set(),
                   "native_calls": [], "build_calls": [], "stage_calls": [], "owner_requests": []}
        original_request = radial._prepare_execution_request
        source_id = radial.EXTRA_SOURCE_IDS[0]
        analysis_id = "projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/analysis.py"
        analysis_source = root / "analysis_fixture.py"
        analysis_source.write_text("# software analysis revision 1\n", encoding="utf-8")
        control["analysis_source"] = analysis_source

        def request(*args, **kwargs):
            value = original_request(*args, **kwargs)
            value["source_sha256"] = {source_id: value["source_sha256"][source_id],
                                      analysis_id: radial.sha256(analysis_source)}
            return value

        def freeze(code, artifact, python, **kwargs):
            target = code / source_id
            target.parent.mkdir(parents=True)
            shutil.copyfile(Path(radial.__file__), target)
            digest = radial.sha256(target)
            analysis_target = code / analysis_id
            analysis_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(analysis_source, analysis_target)
            analysis_digest = radial.sha256(analysis_target)
            return {"schema_version": 2, "role": "oa_tof_candidate_execution_source_closure",
                    "code_root": str(code), "runtime": {"python_executable": str(python),
                    "python_sha256": radial.sha256(python), "candidate_artifact_root": str(artifact)}, "sources": [{"source_id": source_id,
                    "source_sha256": digest, "sha256": digest, "bytes": target.stat().st_size},
                    {"source_id": analysis_id, "source_sha256": analysis_digest, "sha256": analysis_digest,
                     "bytes": analysis_target.stat().st_size}]}

        def owner(request):
            """Software lifecycle fixture; the real common owner is tested separately."""
            control["owner_requests"].append(request)
            run = root / "runs" / request["package"]["run_id"]
            run.mkdir(parents=True)
            config = {"schema_version": 2, "run_id": run.name, "project": radial.PROJECT_ID,
                      "mode": request["package"]["mode"], "inputs": {},
                      "parameters": {"lifecycle_stage": "run_package_initialized"},
                      "artifact_retention": {"policy_version": 1, "class": request["package"]["retention_class"],
                                             "reason": request["package"]["retention_reason"] or None},
                      "capacity_ledger_lifecycle": {"schema_version": 1, "enabled": True,
                      "artifact_root": str(root), "light_evidence_budget_bytes": 26214400}}
            request_path = run / "inputs/execution_request.json"
            radial._write_json(request_path, request)
            config["inputs"]["execution_request"] = str(request_path)
            config_path = run / "run_config.json"
            radial._write_json(config_path, config)
            radial._write_json(run / "summary.json", {"schema_version": 1,
                "role": "run_package_initialization_summary", "status": "checkpoint"})
            radial._write_json(run / "run_manifest.json", build_run_manifest(
                config_path, "checkpoint", output_paths=[run / "summary.json"], software=["software fixture"]))
            session = run / "logs/capacity_session.json"
            radial._write_json(session, {"schema_version": 1, "role": "artifact_workflow_capacity_session",
                "status": "active", "lease_id": "software-fixture", "artifact_root": str(root),
                "owner": "software-owner", "protected_paths": [str(run), *request["capacity"]["protected_paths"]]})
            completion_path = run / "results/execution_completion.json"
            control["worker_error"] = None
            failure = None
            try:
                radial.execute_prepared_run(config_path, session, request_path, completion_path)
            except BaseException as error:
                failure = control["worker_error"] or error
            if completion_path.is_file():
                self.assertFalse((completion_path.parent / "frozen_execution_completion.json").exists())
                completion = radial.load_json(completion_path)
                operations = completion["writer_completion"]["operations"]
                if all(item["observation"]["exit_confirmed"] for item in operations):
                    summary = {**completion["summary"], "writers_stopped": True}
                    apply_retention(config_path,
                                    preserve_paths=[Path(path) for path in completion["retention_preserve_paths"]],
                                    failed_run=completion["status"] != "success")
                    outputs = [path for path in run.rglob("*") if path.is_file()
                               and path.name not in {"run_config.json", "run_manifest.json"}]
                    manifest = build_run_manifest(config_path, summary["status"], output_paths=outputs,
                        virtual_documents={run / "summary.json": summary}, software=["software fixture"])
                    publish_terminal_state(run, summary, manifest)
            if failure is not None:
                raise failure

        def build(case, **kwargs):
            if case.get("build_complete"):
                return
            control["build_calls"].append(case["case_id"])
            case["simion_dir"].mkdir(parents=True)
            (case["simion_dir"] / "oatof_ideal_grounded.iob").write_text("software fixture", encoding="utf-8")
            (case["simion_dir"] / "oatof_comsol_524amu_gaussian_N1000.ion").write_text(ions, encoding="utf-8")
            case.update(pa_build_seconds=0.0, build_complete=True)

        def managed(command, *, cwd, stdout, stderr, **kwargs):
            self.assertEqual(command[:2], ["-B", "-c"])
            self.assertTrue(command[2].startswith(
                "from common.host_resource_python import await_managed_process_start; await_managed_process_start(); "))
            exit_code = 0
            stdout.parent.mkdir(parents=True, exist_ok=True)
            stdout.write_text("software-only frozen-dispatch fixture; not a real handshake", encoding="utf-8")
            try:
                with patch.object(radial, "__file__", str(cwd / source_id)):
                    radial._execute_frozen_campaign(*(Path(value) for value in command[-4:]))
            except BaseException as error:
                control["worker_error"] = error
                stderr.write_text(str(error), encoding="utf-8")
                exit_code = 1
            else:
                stderr.write_text("", encoding="utf-8")
            return managed_process_fixture(exit_code)

        def analyze(log, ion, **kwargs):
            if log.parents[1].name in control["analysis_fail"]:
                raise RuntimeError("analysis failed: software fixture")
            return pd.DataFrame({"Hit": [True], "TofUs": [1.0]}), {"Hit": 1000, "Emitted": 1000}

        def observe(command, *, cwd, stdout, stderr, **kwargs):
            case_id = cwd.parent.name
            control["native_calls"].append(case_id)
            stdout.parent.mkdir(parents=True, exist_ok=True)
            text = "software-only native fixture\n"
            if case_id not in control["native_incomplete"]:
                text += "status,Fly completed. 1000 splats, 0.01 seconds\n"
            stdout.write_text(text, encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(command, 7 if case_id in control["native_fail"] else 0), 4096

        def dispatch(cases, request, profiles):
            return {"waves": [{"cases": [{"case_id": row["case_id"]} for row in cases]}]}

        def stage(module, function, *args, completion_receipt):
            control["stage_calls"].append(function)
            completion_receipt.update(software_fixture=True, bridge_process_exit_confirmed=True,
                bridge_process_returncode=0, host_release={"inherited": False, "token": "software-fixture",
                "result": {"status": "released", "token": "software-fixture"}, "error": None})
            return getattr(radial, function)(*args)

        def fly(case, mode, command, stdout, stderr):
            result, peak = radial._observe_operation(command, cwd=case["simion_dir"], stdout=stdout, stderr=stderr,
                receipt_path=case["case_root"] / "results" / f"{mode}_native_operation.json",
                operation_id=f"{case['case_id']}.{mode}.native", resource_release_id=case.get("_resource_release_id"),
                warning_seconds=1800)
            return result.returncode, peak, 0.01

        with ExitStack() as stack:
            stack.enter_context(patch.dict(radial.os.environ, {
                "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(root / "software-fixture-scheduler.sqlite3"),
            }))
            for name, value in {
                "CONFIG_PATH": config_path, "ARTIFACT_ROOT": root, "CANDIDATE_RUNTIME_PATH": runtime_path,
            }.items():
                stack.enter_context(patch.object(radial, name, value))
            for name, kwargs in {
                "_verify_authorities": {"return_value": (reference_summary, reference_particles)},
                "freeze_candidate_source_closure": {"side_effect": freeze},
                "_prepare_execution_request": {"side_effect": request},
                "_invoke_workflow_owner": {"side_effect": owner},
                "_run_guarded_flight": {"side_effect": fly},
                "prepare": {},
                "_build_case": {"side_effect": build},
                "run_observed_process": {"side_effect": observe},
                "run_managed_python_process": {"side_effect": managed},
                "plan_simion_case_dispatch": {"side_effect": dispatch},
                "discover_case_resource_profiles": {"return_value": []},
                "run_heavy_function": {"side_effect": stage},
            }.items():
                stack.enter_context(patch.object(radial, name, **kwargs))
            stack.enter_context(patch.object(radial.analysis, "canonical_metrics", return_value={"mass_resolution": 1000.0, "significant_kde_modes": 1}))
            stack.enter_context(patch.object(radial.analysis, "analyze_simion_log", side_effect=analyze))
            yield control

    def run_fixture(self, root: Path, suffix: str, parent: Path | None = None,
                    campaign: Path | None = None, extra: list[str] | None = None) -> Path:
        run_id = f"20261028_120000__test__simion__radial-{suffix}"
        argv = ["run_campaign", "--run-id", run_id, "--simion-exe", sys.executable]
        if parent:
            argv.extend(["--resume-from", str(parent)])
        if campaign:
            argv.extend(["--campaign", str(campaign)])
        argv.extend(extra or [])
        with patch.object(sys, "argv", argv):
            radial.main()
        return root / "runs" / run_id

    def test_cli_pa_handoff_options_reject_dry_run_and_unsafe_result_before_planning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.json"
            existing.write_bytes(b"original owner result")
            run_id = "20261029_120000__test__simion__handoff-options"
            for options in (["--dry-run", "--pa-handoff-output", str(root / "result.json")],
                            ["--dry-run", "--pa-producer-handoff", "missing-transaction", "missing-result"]):
                result = subprocess.run([sys.executable, "-B", "-m", radial.__name__, "--run-id", run_id,
                    "--simion-exe", sys.executable, *options], cwd=radial.REPO_ROOT,
                    capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("cannot be combined with --dry-run", result.stderr)
            with patch.object(radial, "ARTIFACT_ROOT", root), patch.object(radial, "_source_inputs") as science:
                for output in (existing, root / "runs" / run_id / "result.json", root / "missing" / "result.json"):
                    with self.subTest(output=output), self.assertRaisesRegex(ValueError, "PA handoff output"):
                        radial._prepare_execution_request(run_id, Path(sys.executable), None, False, pa_handoff_output=output)
                science.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"original owner result")
            self.assertFalse((root / "runs").exists())

    def test_handoff_output_preserves_public_owner_result_bytes_and_failure(self) -> None:
        raw = b'{ "role": "run_artifact_workflow_result", "software_fixture":true }\r\n'
        for status in (0, 7, "exception"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "owner_result.json"
                error = RuntimeError("software owner observation failed")
                request = {"payload": {"pa_handoff_output": str(output)}}

                def owner(command, **kwargs):
                    self.assertEqual(Path(command[command.index("-ResultPath") + 1]), output)
                    self.assertEqual(radial.load_json(Path(command[command.index("-RequestPath") + 1])), request)
                    output.write_bytes(raw)
                    kwargs["stderr"].write_text("original owner failure", encoding="utf-8")
                    if status == "exception":
                        raise error
                    return subprocess.CompletedProcess(command, status), None

                with patch.object(radial, "run_observed_process", side_effect=owner) as observed:
                    if status == 0:
                        radial._invoke_workflow_owner(request)
                    else:
                        with self.assertRaises(RuntimeError) as caught:
                            radial._invoke_workflow_owner(request)
                        if status == "exception":
                            self.assertIs(caught.exception, error)
                        else:
                            self.assertIn("original owner failure", str(caught.exception))
                self.assertEqual(output.read_bytes(), raw)
                self.assertFalse(observed.call_args.kwargs["stdout"].parent.exists())

    def test_handoff_preflight_uses_all_plans_and_keeps_full_capacity_before_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pair = (root / "transaction.json", root / "result.json")
            for path in pair:
                path.write_text("software preflight fixture", encoding="utf-8")
            plan = {"sources": [{"transaction_path": str(pair[0]), "owner_result_path": str(pair[1])}],
                    "source_records": [radial.file_record(path) for path in pair],
                    "protected_paths": [str(root / "prior"), str(root / "verification")], "declared_cache_keys": []}
            with self.software_campaign(root) as control:
                plain = radial._prepare_execution_request("20261029_120000__test__simion__plan-plain",
                                                          Path(sys.executable), None, False)
                with patch.object(radial, "plan_pa_producer_handoffs", return_value=plan) as preflight:
                    planned = radial._prepare_execution_request("20261029_120000__test__simion__plan-handoff",
                        Path(sys.executable), None, False, pa_producer_handoffs=[pair, pair])
                self.assertEqual(preflight.call_args.args, ([pair, pair],))
                self.assertEqual(preflight.call_args.kwargs["expected_cache_keys"], set(plain["protected_cache_keys"]))
                self.assertEqual(planned["committed_new_bytes"], plain["committed_new_bytes"])
                self.assertTrue(set(plan["protected_paths"]) <= set(planned["dependency_run_dirs"]))
                with patch.object(radial, "plan_pa_producer_handoffs", side_effect=ValueError("same-key handoff conflict")):
                    with self.assertRaisesRegex(ValueError, "same-key handoff conflict"):
                        self.run_fixture(root, "invalid-handoff", extra=["--pa-producer-handoff", *map(str, pair)])
                self.assertEqual(control["owner_requests"], [])

    def test_cli_freezes_shared_handoff_records_once_and_retention_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pair = (root / "transaction.json", root / "owner_result.json")
            for path in pair:
                path.write_text("software-only handoff seam", encoding="utf-8")
            plan = {"sources": [{"transaction_path": str(pair[0]), "owner_result_path": str(pair[1])}],
                    "source_records": [radial.file_record(path) for path in pair],
                    "protected_paths": [str(root / "prior"), str(root / "verification")], "declared_cache_keys": []}
            frozen_records = []

            def freeze(run, actual_plan, *, expected_cache_keys, capacity_session):
                self.assertEqual(actual_plan, plan)
                self.assertTrue(set(plan["protected_paths"]) <= set(capacity_session["protected_paths"]))
                self.assertEqual(expected_cache_keys, set(control["owner_requests"][-1]["payload"]["protected_cache_keys"]))
                # Explicit shared-helper seam: only its file records are consumed here.
                frozen_records.clear()
                for name in ("handoffs.json", "owner_result.json", "original_build_completion.json"):
                    path = run / "inputs" / "pa_producer_handoffs" / name
                    radial._write_json(path, {"software_fixture": True, "name": name})
                    frozen_records.append(radial.file_record(path))
                return {**frozen_records[0], "frozen_input_records": frozen_records.copy()}

            with self.software_campaign(root) as control, \
                    patch.object(radial, "plan_pa_producer_handoffs", return_value=plan) as preflight, \
                    patch.object(radial, "freeze_pa_producer_handoffs", side_effect=freeze) as freezer:
                output = root / "retained_owner_result.json"
                run = self.run_fixture(root, "retained-handoff", extra=["--pa-handoff-output", str(output),
                    "--pa-producer-handoff", *map(str, pair), "--pa-producer-handoff", *map(str, pair)])
                self.assertEqual(preflight.call_args.args, ([[*pair], [*pair]],))
                freezer.assert_called_once()
                config = radial.load_json(run / "run_config.json")
                self.assertEqual(config["pa_producer_handoffs"], frozen_records[0])
                self.assertTrue({record["path"] for record in frozen_records} <= set(config["inputs"].values()))
                self.assertEqual(config["artifact_retention"]["class"], "solver_review")
                self.assertEqual(config["artifact_retention"]["reason"], radial.PA_HANDOFF_RETENTION_REASON)
                request = control["owner_requests"][-1]
                self.assertTrue(all(record in request["capacity"]["commitment_inputs"] for record in plan["source_records"]))
                self.assertEqual(request["payload"]["pa_handoff_output"], str(output))
                self.assertEqual(request["capacity"]["committed_new_bytes"], request["payload"]["committed_new_bytes"])
                # A published whole-unit parent is independent of PA handoff selection.
                child = self.run_fixture(root, "handoff-reanalysis", parent=run,
                                         extra=["--pa-producer-handoff", *map(str, pair)])
                self.assertEqual(radial.load_json(child / "run_config.json")["artifact_retention"]["class"], "compact")
                self.assertEqual(freezer.call_count, 2)

    def test_cli_explicit_campaign_freezes_selected_contract_and_rejects_resume_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                selected = root / "selected_campaign.json"
                selected.write_bytes(radial.CONFIG_PATH.read_bytes())
                radial.CONFIG_PATH.write_text("{}", encoding="utf-8")
                run = self.run_fixture(root, "selected-contract", campaign=selected)
                frozen = Path(radial.load_json(run / "run_config.json")["inputs"]["campaign"])
                self.assertEqual(frozen.read_bytes(), selected.read_bytes())
                with self.assertRaises(SystemExit) as caught:
                    self.run_fixture(root, "conflict", run, selected)
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse((root / "runs" / "20261028_120000__test__simion__radial-conflict").exists())

    def test_capacity_plan_is_pure_and_uses_the_same_case_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                existing_runs = set((root / "runs").iterdir())
                request = radial._prepare_execution_request(
                    "20261028_120000__test__simion__radial-plan", Path(sys.executable), None, False,
                    radial.CONFIG_PATH,
                )
                self.assertEqual(set((root / "runs").iterdir()), existing_runs)
                self.assertEqual(set(request["component_plans"]), {"shield260", "shield200"})
                self.assertEqual(request["committed_new_bytes"], radial.sum_component_commitments(
                    request["component_plans"].values(),
                ))
                self.assertGreater(request["committed_new_bytes"], 0)
                for plan in request["component_plans"].values():
                    self.assertEqual({item["role"] for item in plan["components"] if item["cacheable"]},
                                     {"accelerator", "reflectron"})
                    self.assertEqual({item["identity"]["surface"] for item in plan["components"] if not item["cacheable"]},
                                     {"fractional"})

    def test_template_bundle_is_frozen_and_resume_ignores_live_registration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="radial-template-inputs-") as directory:
            root = Path(directory)
            with self.software_campaign(root) as control:
                request = radial._prepare_execution_request(
                    "20261028_120000__test__simion__radial-template-plan", Path(sys.executable), None, False,
                )
                self.assertEqual({Path(path).name for path in request["dependency_run_dirs"]}, {
                    "20261028_110000__build__simion__radial-template",
                    "20261028_105000__test__simion__radial-layout",
                })
                parent = self.run_fixture(root, "frozen-template")
                inputs = radial.load_json(parent / "run_config.json")["inputs"]
                iob, con = Path(inputs["template_iob"]), Path(inputs["template_con"])
                self.assertEqual(iob.name, "layout.iob")
                self.assertEqual(con, iob.with_suffix(".con"))
                self.assertEqual(iob.parent, parent / "inputs/template")
                self.assertEqual(iob.read_bytes(), Path(request["input_paths"]["template_iob"]).read_bytes())
                for name in radial.FROZEN_INPUTS[6:]:
                    self.assertEqual(radial.sha256(Path(inputs[name])), request["scientific_input_sha256"][name])
                radial.CANDIDATE_RUNTIME_PATH.write_text("changed active runtime", encoding="utf-8")
                Path(request["input_paths"]["template_iob"]).write_text("changed active template", encoding="utf-8")
                control["build_calls"].clear()
                control["native_calls"].clear()
                child = self.run_fixture(root, "frozen-template-reanalysis", parent)
                child_inputs = radial.load_json(child / "run_config.json")["inputs"]
                self.assertEqual(Path(child_inputs["template_iob"]).read_bytes(), iob.read_bytes())
                self.assertEqual(Path(child_inputs["candidate_runtime"]).read_bytes(), Path(inputs["candidate_runtime"]).read_bytes())
                self.assertEqual(control["build_calls"], [])
                self.assertEqual(control["native_calls"], [])

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows managed Python boundary")
    def test_frozen_source_import_uses_actual_worker_and_shared_control_plane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="radial-frozen-import-") as directory:
            root = Path(directory)
            code_root = root / "code"
            closure = radial.freeze_candidate_source_closure(
                code_root, root / "artifacts", Path(sys.executable), extra_source_ids=radial.EXTRA_SOURCE_IDS,
            )
            shared_state = root / "selected-host-state.sqlite3"
            worker = (
                "from common.host_resource_python import await_managed_process_start; await_managed_process_start(); "
                "import json, os; from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction "
                "import run_campaign; print(json.dumps({'source': run_campaign.__file__, "
                "'host_state': os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'], 'pid': os.getpid()}), flush=True)"
            )
            stdout, stderr = root / "stdout.log", root / "stderr.log"
            receipt = radial.run_managed_python_process(
                ["-B", "-c", worker], cwd=code_root, stdout=stdout, stderr=stderr,
                environment={**radial.os.environ, "PYTHONPATH": str(code_root),
                             "PYTHONDONTWRITEBYTECODE": "1",
                             "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(shared_state)},
            )
            self.assertEqual(receipt["exit_code"], 0, stdout.read_text() + stderr.read_text())
            self.assertEqual(receipt["role"], "repository_managed_python_completion")
            self.assertTrue(receipt["ownership_confirmed"] and receipt["worker_exit_confirmed"])
            self.assertTrue(receipt["stdout_drained"] and receipt["stderr_drained"])
            self.assertGreater(receipt["worker_started_at_utc_ticks"], 0)
            self.assertGreater(receipt["launcher_process_id"], 0)
            self.assertTrue(receipt["launcher_exit_confirmed"] and receipt["ack_attempted"])
            observed = json.loads(stdout.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(receipt["worker_process_id"], observed["pid"])
            print("FROZEN_ACTUAL_WORKER=" + json.dumps({"python": sys.executable, "actual": observed, "completion": receipt}))
            self.assertEqual(Path(observed["source"]).resolve(),
                             Path(radial.frozen_source_path(closure, radial.EXTRA_SOURCE_IDS[0])).resolve())
            self.assertEqual(observed["host_state"], str(shared_state))
            self.assertFalse(shared_state.exists())
            self.assertFalse(list(code_root.rglob("*.sqlite3")))

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows resource bridge")
    def test_real_pool_bridge_reimport_binds_guard_to_selected_python(self) -> None:
        with tempfile.TemporaryDirectory(prefix="radial-pool-reimport-") as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            run = artifacts / "runs/20261028_120000__test__simion__pool-import"
            code_root = run / "inputs/code"
            closure = radial.freeze_candidate_source_closure(
                code_root, artifacts, Path(sys.executable), extra_source_ids=radial.EXTRA_SOURCE_IDS,
            )
            case_root = run / "cases/shield260"
            (case_root / "simion").mkdir(parents=True)
            radial._write_json(run / "inputs/closure.json", closure)
            radial._write_json(run / "inputs/execution_request.json", {
                "schema_version": 1, "role": "run_artifact_workflow_request", "python_executable": sys.executable,
                "payload": {"run_id": run.name, "project": radial.PROJECT_ID, "artifact_project_root": str(artifacts)},
            })
            radial._write_json(run / "run_config.json", {"role": radial.RUN_ROLE, "run_id": run.name,
                "project": radial.PROJECT_ID, "context_sha256": "A" * 64, "inputs": {
                "execution_request": str(run / "inputs/execution_request.json"),
                "execution_source_closure": str(run / "inputs/closure.json")}})
            # Only the Fly boundary is a software fixture. The whole-pool entry,
            # fresh module import, frozen binding and public resource grant run.
            fixture = '''import json, subprocess, sys
from pathlib import Path
def run(case_root, run_id, context, managed):
    from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction import run_campaign as radial
    before=str(radial.PYTHON)
    assert not radial.PYTHON.exists(), 'fixture did not start from a fresh frozen import'
    case={'case_root':case_root,'simion_dir':case_root/'simion','case_id':case_root.name,
          'run_id':run_id,'context_sha256':context,'capacity_session_path':case_root.parents[1]/'session.json',
          '_resource_release_id':'software-pool'}
    captured=[]
    def observe(command, **kwargs):
        captured.append(command)
        radial._write_json(case_root/'results/actual_process_result.json', {
            'schema_version':1,'role':'oatof_candidate_flight_process_result','run_id':run_id,
            'case_id':case_root.name,'mode':'actual','context_sha256':context,'native_exit_confirmed':True,
            'native_returncode':0,'native_peak_working_set_bytes':1,'native_elapsed_seconds':0,
            'managed_process_completion':managed,'software_fixture':True})
        radial._write_json(kwargs['receipt_path'], {'operation':{'operation_id':kwargs['operation_id'],
            'resource_release_id':kwargs['resource_release_id'],'observation':{'exit_confirmed':True,'returncode':0}}})
        return subprocess.CompletedProcess(command,0),None
    def fly(case, mode, *args):
        radial._run_guarded_flight(case,mode,[sys.executable],case_root/'out.log',case_root/'err.log')
        return {'python_argument':captured[-1][captured[-1].index('-PythonExe')+1]}
    radial._observe_operation=observe
    radial._fly=fly
    radial._case_resource_identity=lambda *args: {}
    radial.plan_simion_case_dispatch=lambda *args: {'waves':[{'cases':[{'case_id':case_root.name}]}]}
    output=radial._run_parallel_flights([case],'actual',Path(sys.executable),100,8)
    return {'output':output,'before':before,'artifact_root':str(radial.ARTIFACT_ROOT)}
'''
            (root / "pool_fixture.py").write_text(fixture, encoding="utf-8")
            controller = (
                "from common.host_resource_python import await_managed_process_start; await_managed_process_start(); "
                "import json, sys; from pathlib import Path; from common.host_resource_python import run_heavy_function; "
                "receipt={}; result=run_heavy_function('pool_fixture','run',Path(sys.argv[1]),sys.argv[2],sys.argv[3],"
                "json.loads(sys.argv[4]),role='GATE',stage='theory_compute',completion_receipt=receipt); "
                "print(json.dumps({'result':result,'release':receipt}),flush=True)"
            )
            stdout, stderr = root / "controller.log", root / "controller.stderr.log"
            receipt = radial.run_managed_python_process(
                ["-B", "-c", controller, str(case_root), run.name, "A" * 64, json.dumps(managed_process_fixture())],
                cwd=code_root, stdout=stdout, stderr=stderr, environment={
                    **radial.os.environ, "PYTHONPATH": radial.os.pathsep.join((str(code_root), str(root))),
                    "PYTHONDONTWRITEBYTECODE": "1", "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "",
                    "MASS_SPECTROMETRY_PYTHON_HEAVY_REENTRY": "",
                    "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(root / "fixture-host.sqlite3")},
            )
            self.assertEqual(receipt["exit_code"], 0, stdout.read_text() + stderr.read_text())
            outcome = json.loads(stdout.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(Path(outcome["result"]["output"]["shield260"]["python_argument"]).resolve(),
                             Path(sys.executable).resolve())
            self.assertEqual(Path(outcome["result"]["artifact_root"]), artifacts)
            self.assertTrue(outcome["release"]["host_release_confirmed"])
            self.assertFalse(outcome["release"]["host_release"]["inherited"])
            self.assertFalse(list(code_root.rglob("*.sqlite3")))

    def test_frozen_worker_refuses_to_derive_a_private_scheduler_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root) as control, patch.dict(radial.os.environ, clear=True):
                with self.assertRaisesRegex(ValueError, "absolute shared scheduler path"):
                    self.run_fixture(root, "missing-shared-scheduler")
                self.assertEqual(control["native_calls"], [])
                self.assertEqual(control["build_calls"], [])
                self.assertEqual(list(root.rglob("*.sqlite3")), [])

    def test_full_driver_retention_keeps_required_native_logs_without_trace_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            retained = {}
            public_retention = apply_retention

            def retain(config_path, **kwargs):
                run = config_path.parent
                completion = radial.load_json(run / "results/execution_completion.json")
                required = [Path(path) for path in completion["required_output_paths"]]
                retained.update({path: path.read_bytes() for path in required})
                ordinary_logs = [path for path in required if path.name == "actual.log"]
                self.assertTrue(ordinary_logs)
                # The original misuse is rejected before a retention plan exists.
                with self.assertRaisesRegex(ValueError, "only a run-local native TRACE"):
                    public_retention(config_path, preserve_paths=ordinary_logs)
                self.assertFalse((run / "retention_actions.json").exists())
                return public_retention(config_path, **kwargs)

            with self.software_campaign(root), patch(__name__ + ".apply_retention", side_effect=retain):
                run = self.run_fixture(root, "required-log-retention")
            completion = radial.load_json(run / "results/execution_completion.json")
            self.assertEqual(completion["retention_preserve_paths"], [])
            self.assertEqual({path: path.read_bytes() for path in retained}, retained)
            self.assertEqual(radial.load_json(run / "run_manifest.json")["status"], "success")

    def test_full_replay_avoids_solver_grants_and_passes_public_writer_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root) as control:
                parent = self.run_fixture(root, "replay-owner-parent")
                control["native_calls"].clear()
                control["build_calls"].clear()
                control["stage_calls"].clear()
                child = self.run_fixture(root, "replay-owner-child", parent)
                validator = root / "validate_writer.ps1"
                validator.write_text(
                    "param([string]$Repo,[string]$CompletionPath)\n"
                    "$ErrorActionPreference='Stop'\n"
                    ". (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')\n"
                    "$completion=Get-Content -LiteralPath $CompletionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable\n"
                    "Assert-WorkflowWriterCompletion $completion.writer_completion\n",
                    encoding="utf-8",
                )
                checked = subprocess.run([
                    "pwsh", "-NoProfile", "-File", str(validator), str(radial.REPO_ROOT),
                    str(child / "results/execution_completion.json"),
                ], cwd=radial.REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertEqual(control["stage_calls"], [])
                self.assertEqual(control["native_calls"], [])
                self.assertEqual(control["build_calls"], [])

    def test_full_driver_analysis_failure_reuses_complete_native_units_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root) as control:
                control["analysis_fail"].add("shield260")
                with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                    self.run_fixture(root, "parent")
                parent = root / "runs" / "20261028_120000__test__simion__radial-parent"
                before = {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                self.assertEqual(radial.load_json(parent / "run_manifest.json")["status"], "failed")
                self.assertEqual(len(radial.load_json(parent / "summary.json")["native_units"]), 2)
                control["analysis_fail"].clear()
                control["native_calls"].clear()
                control["build_calls"].clear()
                # Live scientific input changes must not leak into continuation.
                radial.CONFIG_PATH.write_text("{}", encoding="utf-8")
                child = self.run_fixture(root, "child", parent)
                grandchild = self.run_fixture(root, "grandchild", child)
                self.assertEqual(control["native_calls"], [])
                self.assertEqual(control["build_calls"], [])
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                for run in (child, grandchild):
                    manifest = radial.load_json(run / "run_manifest.json")
                    self.assertEqual(manifest["status"], "success")
                    self.assertEqual(manifest["run_id"], run.name)
                    result = radial.load_json(run / "cases/shield260/results/actual_summary.json")
                    self.assertEqual(result["run_id"], run.name)
                    self.assertTrue(result["flight_reused_from_interrupted_run"])

    def test_full_driver_replays_only_the_incomplete_native_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root) as control:
                control["native_fail"].add("shield200")
                with self.assertRaisesRegex(RuntimeError, "command failed"):
                    self.run_fixture(root, "failed-native")
                parent = root / "runs" / "20261028_120000__test__simion__radial-failed-native"
                self.assertEqual(len(radial.load_json(parent / "summary.json")["native_units"]), 1)
                control["native_fail"].clear()
                control["native_calls"].clear()
                control["build_calls"].clear()
                self.run_fixture(root, "replayed", parent)
                self.assertEqual(control["native_calls"], ["shield200"])
                self.assertEqual(control["build_calls"], ["shield200"])

    def test_analysis_source_change_reuses_native_units_across_generations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root) as control:
                parent = self.run_fixture(root, "analysis-parent")
                control["analysis_source"].write_text("# software analysis revision 2\n", encoding="utf-8")
                control["native_calls"].clear()
                control["build_calls"].clear()
                child = self.run_fixture(root, "analysis-child", parent)
                self.run_fixture(root, "analysis-grandchild", child)
                self.assertEqual(control["native_calls"], [])
                self.assertEqual(control["build_calls"], [])
                old = radial.load_json(parent / "run_config.json")
                new = radial.load_json(child / "run_config.json")
                self.assertNotEqual(old["context_sha256"], new["context_sha256"])
                receipt = radial.load_json(child / "cases/shield260/results/actual_native.json")
                self.assertEqual(receipt["context_sha256"], new["context_sha256"])
                self.assertIsNotNone(receipt["reused_from_receipt"])

    def test_flight_dependency_comparison_keeps_science_and_driver_identity(self) -> None:
        original = {"inputs": {"campaign": "same"}, "campaign_driver_sha256": "same",
                    "simion_sha256": "same", "python_sha256": "same", "sources": {
                        "common/analysis/peak_metrics.py": "old", "physical.lua": "same"}}
        changed = copy.deepcopy(original)
        changed["sources"]["common/analysis/peak_metrics.py"] = "new"
        self.assertTrue(radial._same_flight_dependencies(changed, original))
        for section, key in (("sources", "physical.lua"), ("inputs", "campaign")):
            altered = copy.deepcopy(changed)
            altered[section][key] = "different"
            self.assertFalse(radial._same_flight_dependencies(altered, original))
        changed["campaign_driver_sha256"] = "different"
        self.assertFalse(radial._same_flight_dependencies(changed, original))

    def test_zero_exit_without_native_completion_is_not_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root) as control:
                control["native_incomplete"].add("shield200")
                with self.assertRaisesRegex(ValueError, "exactly one SIMION native Fly completion"):
                    self.run_fixture(root, "incomplete-native")
                parent = root / "runs" / "20261028_120000__test__simion__radial-incomplete-native"
                summary = radial.load_json(parent / "summary.json")
                self.assertEqual(set(summary["native_units"]), {"shield260.actual"})

    def test_continuation_refuses_tampered_published_log_and_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                parent = self.run_fixture(root, "intact")
                with self.assertRaisesRegex(ValueError, "already exists"):
                    self.run_fixture(root, "intact", parent)
                (parent / "cases/shield260/logs/actual.log").write_text("partial", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "hash differs"):
                    self.run_fixture(root, "tampered", parent)

    def test_hard_kill_unpublished_receipt_is_not_a_predecessor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                parent = root / "runs" / "20261028_120000__test__simion__radial-unpublished"
                radial._freeze_run(parent, Path(sys.executable), None)
                with self.assertRaises((FileNotFoundError, ValueError)):
                    self.run_fixture(root, "cannot-reuse", parent)

    def test_pending_terminal_journal_and_changed_execution_identity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                parent = self.run_fixture(root, "published")
                with patch.object(radial, "freeze_candidate_source_closure", return_value={
                    "sources": [{"source_id": "changed.py", "source_sha256": "F" * 64}],
                }):
                    with self.assertRaisesRegex(ValueError, "execution (identity differs|sources changed)"):
                        self.run_fixture(root, "changed-source", parent)
                (parent / radial.TERMINAL_JOURNAL_NAME).write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "terminal publication is incomplete"):
                    self.run_fixture(root, "journal-pending", parent)

    def test_scientific_input_change_during_copy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = radial.freeze_file

            def drift(source, target):
                if target.name == "campaign.json":
                    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                return original(source, target)

            with self.software_campaign(root), patch.object(radial, "freeze_file", side_effect=drift):
                with self.assertRaisesRegex(ValueError, "scientific input changed while freezing: campaign"):
                    self.run_fixture(root, "input-drift", campaign=radial.CONFIG_PATH)
                manifest = root / "runs/20261028_120000__test__simion__radial-input-drift/run_manifest.json"
                self.assertEqual(radial.load_json(manifest)["status"], "checkpoint")

    def test_manifest_bound_wrong_case_identity_is_rejected_by_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                parent = self.run_fixture(root, "wrong-identity")
                manifest = radial.load_json(parent / "run_manifest.json")
                summary = radial.load_json(parent / "summary.json")
                summary["native_units"]["shield260.actual"]["case_id"] = "other"
                rewritten = build_run_manifest(
                    parent / "run_config.json", "success",
                    output_paths=[Path(row["path"]) for row in manifest["outputs"]],
                    virtual_documents={parent / "summary.json": summary},
                )
                # Construct a self-consistent but semantically wrong external asset.
                # Production terminal publication correctly refuses this rewrite.
                from common.contracts.recorded_file_removal import write_json_atomic
                write_json_atomic(parent / "summary.json", summary)
                write_json_atomic(parent / "run_manifest.json", rewritten)
                with self.assertRaisesRegex(ValueError, "native unit identity differs"):
                    self.run_fixture(root, "identity-rejected", parent)

    def test_completion_recording_does_not_hide_original_worker_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = RuntimeError("original campaign failure")
            original.observed_process_exit_confirmed = True
            write = radial._write_json

            def record(path, value):
                if path.name == "frozen_execution_completion.json":
                    raise OSError("completion failure")
                write(path, value)

            with self.software_campaign(root), \
                    patch.object(radial, "_execute_campaign", side_effect=original), \
                    patch.object(radial, "_write_json", side_effect=record):
                with self.assertRaises(RuntimeError) as caught:
                    self.run_fixture(root, "dual-failure")
                self.assertIs(caught.exception, original)
                self.assertTrue(any("completion failure" in note for note in original.__notes__))

    def test_unconfirmed_observer_exit_does_not_publish_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            error = RuntimeError("native exit unknown")
            error.observed_process_exit_confirmed = False
            with self.software_campaign(root), \
                    patch.object(radial, "_execute_campaign", side_effect=error):
                with self.assertRaises(RuntimeError):
                    self.run_fixture(root, "live-writer")
                run = root / "runs" / "20261028_120000__test__simion__radial-live-writer"
                self.assertEqual(radial.load_json(run / "run_manifest.json")["status"], "checkpoint")

    def test_frozen_completion_is_not_delivered_when_managed_worker_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                managed = radial.run_managed_python_process.side_effect
                original = RuntimeError("actual frozen worker completion unknown")
                original.managed_python_completion = None

                def unknown(*args, **kwargs):
                    result = managed(*args, **kwargs)
                    if "_execute_frozen_campaign" not in args[0][2]:
                        return result
                    self.assertTrue(Path(args[0][-1]).is_file())
                    raise original

                with patch.object(radial, "run_managed_python_process", side_effect=unknown), \
                        patch(__name__ + ".apply_retention") as retention, \
                        patch(__name__ + ".publish_terminal_state") as publication:
                    with self.assertRaises(RuntimeError) as caught:
                        self.run_fixture(root, "unknown-frozen-worker")
                self.assertIs(caught.exception, original)
                retention.assert_not_called()
                publication.assert_not_called()
                run = root / "runs" / "20261028_120000__test__simion__radial-unknown-frozen-worker"
                self.assertFalse((run / "results/execution_completion.json").exists())
                self.assertTrue((run / "results/frozen_execution_completion.json").is_file())
                self.assertEqual(radial.load_json(run / "run_manifest.json")["status"], "checkpoint")

    def test_nonzero_frozen_worker_cannot_deliver_successful_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                managed = radial.run_managed_python_process.side_effect

                def nonzero(*args, **kwargs):
                    result = managed(*args, **kwargs)
                    return {**result, "exit_code": 7} if "_execute_frozen_campaign" in args[0][2] else result

                with patch.object(radial, "run_managed_python_process", side_effect=nonzero):
                    with self.assertRaisesRegex(ValueError, "success contradicts"):
                        self.run_fixture(root, "nonzero-frozen-worker")
                run = root / "runs" / "20261028_120000__test__simion__radial-nonzero-frozen-worker"
                self.assertFalse((run / "results/execution_completion.json").exists())
                self.assertEqual(radial.load_json(run / "run_manifest.json")["status"], "checkpoint")

    def test_missing_exit_evidence_does_not_publish_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.software_campaign(root):
                existing_observer = radial.run_observed_process.side_effect

                def fail(command, **kwargs):
                    if "--nogui" in command:
                        raise RuntimeError("unknown worker exit")
                    return existing_observer(command, **kwargs)

                with patch.object(radial, "run_observed_process", side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError, "unknown worker exit"):
                        self.run_fixture(root, "no-exit-evidence")
                run = root / "runs" / "20261028_120000__test__simion__radial-no-exit-evidence"
                self.assertEqual(radial.load_json(run / "run_manifest.json")["status"], "checkpoint")

    def test_prepared_execution_rejects_unbound_or_unprotected_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs" / "20261028_120000__test__simion__radial-prepared"
            run.mkdir(parents=True)
            config = {
                "schema_version": 2, "run_id": run.name, "project": radial.PROJECT_ID,
                "mode": "simion_radial_compaction_n1000", "inputs": {},
                "parameters": {"lifecycle_stage": "run_package_initialized"},
                "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
                "capacity_ledger_lifecycle": {"schema_version": 1, "enabled": True,
                                              "artifact_root": str(root), "light_evidence_budget_bytes": 26214400},
            }
            config_path, session_path = run / "run_config.json", root / "session.json"
            radial._write_json(config_path, config)
            radial._write_json(run / "summary.json", {
                "schema_version": 1, "role": "run_package_initialization_summary", "status": "checkpoint",
            })
            radial._write_json(run / "run_manifest.json", build_run_manifest(
                config_path, "checkpoint", software=["software fixture"], output_paths=[run / "summary.json"],
            ))
            session = {"schema_version": 1, "role": "artifact_workflow_capacity_session",
                       "status": "active", "lease_id": "software-session-fixture",
                       "artifact_root": str(root), "protected_paths": [str(run)]}
            radial._write_json(session_path, session)
            with patch.object(radial, "ARTIFACT_ROOT", root):
                self.assertEqual(radial._validate_prepared_run(config_path, session_path), config)
                session["protected_paths"] = []
                radial._write_json(session_path, session)
                with self.assertRaisesRegex(ValueError, "not protected"):
                    radial._validate_prepared_run(config_path, session_path)
                radial._write_json(config_path, {**config, "project": "another-project"})
                with self.assertRaisesRegex(ValueError, "fresh public run package"):
                    radial._validate_prepared_run(config_path, session_path)

    def test_parallel_wave_keeps_unconfirmed_exit_from_any_failed_worker(self) -> None:
        cases = [{"case_id": name, "simion_dir": Path(name)} for name in ("one", "two", "later")]
        original = RuntimeError("one failed")
        original.observed_process_exit_confirmed = True
        unconfirmed = RuntimeError("two has an unconfirmed native exit")
        unconfirmed.observed_process_exit_confirmed = False
        called = []

        def fly(case, *args):
            called.append(case["case_id"])
            raise original if case["case_id"] == "one" else unconfirmed

        with patch.object(radial, "_bind_pool_execution_context"), \
                patch.object(radial, "_case_resource_identity", return_value={}), \
                patch.object(radial, "plan_simion_case_dispatch", return_value={
                    "waves": [{"cases": [{"case_id": "one"}, {"case_id": "two"}]}],
                }), patch.object(radial, "_fly", side_effect=fly):
            with self.assertRaises(RuntimeError) as caught:
                radial._run_parallel_flights(cases, "actual", Path(sys.executable), 1000, 8)
        self.assertFalse(caught.exception.observed_process_exit_confirmed)
        self.assertEqual(set(called), {"one", "two"})

    def test_parallel_wave_missing_worker_evidence_is_not_inferred_from_pool_exit(self) -> None:
        cases = [{"case_id": name, "simion_dir": Path(name)} for name in ("one", "two")]
        known = RuntimeError("analysis failed after native stopped")
        known.observed_process_exit_confirmed = True
        unknown = RuntimeError("transport returned no native exit evidence")

        def fly(case, *args):
            raise known if case["case_id"] == "one" else unknown

        with patch.object(radial, "_bind_pool_execution_context"), \
                patch.object(radial, "_case_resource_identity", return_value={}), \
                patch.object(radial, "plan_simion_case_dispatch", return_value={
                    "waves": [{"cases": [{"case_id": "one"}, {"case_id": "two"}]}],
                }), patch.object(radial, "_fly", side_effect=fly):
            with self.assertRaises(RuntimeError) as caught:
                radial._run_parallel_flights(cases, "actual", Path(sys.executable), 1000, 8)
        self.assertFalse(caught.exception.observed_process_exit_confirmed)

    def test_confirmed_controlled_interruption_is_published_as_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            error = KeyboardInterrupt("after owned process stopped")
            error.observed_process_exit_confirmed = True
            with self.software_campaign(root), patch.object(radial, "_execute_campaign", side_effect=error):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    self.run_fixture(root, "interrupted")
                self.assertIs(caught.exception, error)
                run = root / "runs" / "20261028_120000__test__simion__radial-interrupted"
                self.assertEqual(radial.load_json(run / "run_manifest.json")["status"], "interrupted")

    def test_bare_summary_and_partial_logs_never_skip_native_execution(self) -> None:
        for existing in ("results/actual_summary.json", "logs/actual.log"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / existing
                path.parent.mkdir(parents=True)
                path.write_text('{"status":"failed","case_id":"wrong","mode":"ideal_all"}', encoding="utf-8")
                case = {"case_id": "expected", "case_root": root, "simion_dir": root / "simion"}
                with patch.object(radial, "run_observed_process") as native:
                    with self.assertRaisesRegex(ValueError, "new run"):
                        radial._fly(case, "actual", Path(sys.executable), 1000, 8)
                native.assert_not_called()

    def test_only_complete_pool_calls_cross_the_stage_bridge(self) -> None:
        for replay_first in (False, True):
            with self.subTest(replay_first=replay_first):
                cases = [{"case_id": "one", "replay_units": {"actual": "parent-receipt"} if replay_first else {}},
                         {"case_id": "two", "replay_units": {}}]
                receipts = []
                with patch.object(radial, "run_heavy_function", return_value={}) as stage:
                    radial._run_flight_stage(cases, "actual", Path(sys.executable), 100, 8, [], receipts)
                stage.assert_called_once_with(radial.__name__, "_run_parallel_flights", cases,
                    "actual", Path(sys.executable), 100, 8, [], completion_receipt=receipts[0]["completion_receipt"])
                self.assertEqual({case["_resource_release_id"] for case in cases}, {receipts[0]["release_id"]})

    def test_stage_keeps_real_owner_receipt_on_worker_failure(self) -> None:
        receipts = []
        original = RuntimeError("worker failure")
        proof = {"bridge_process_exit_confirmed": True, "host_release": {
            "inherited": False, "token": "software-fixture-token", "error": None,
            "result": {"status": "released", "token": "software-fixture-token"},
        }}

        def fail(*args, completion_receipt):
            completion_receipt.update(proof)
            raise original

        with patch.object(radial, "run_heavy_function", side_effect=fail):
            with self.assertRaises(RuntimeError) as caught:
                radial._run_flight_stage([{"case_id": "native", "replay_units": {}}],
                                         "actual", Path(sys.executable), 100, 8, [], receipts)
        self.assertIs(caught.exception, original)
        self.assertEqual(receipts, [{"release_id": "flight:0:actual", "completion_receipt": proof}])

    def test_preparation_failure_does_not_request_a_flight_grant(self) -> None:
        argv = ["run_campaign", "--run-id", "20260914_160000__sim__simion__permit-fixture",
                "--simion-exe", sys.executable]
        with patch.object(sys, "argv", argv), \
                patch.object(radial, "run_heavy_function") as permit, \
                patch.object(radial, "_verify_authorities", side_effect=ValueError("input-failure")):
            with self.assertRaisesRegex(ValueError, "input-failure"):
                radial.main()
        permit.assert_not_called()

    def test_dry_run_does_not_request_heavy_permission_or_build_pa(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = ["run_campaign", "--run-id", "20260914_160001__sim__simion__plan-fixture",
                    "--simion-exe", sys.executable, "--dry-run"]
            with self.software_campaign(root), patch.object(sys, "argv", argv), \
                    patch.object(radial, "run_heavy_function") as permit, \
                    patch.object(radial, "_build_case") as build:
                radial.main()
            permit.assert_not_called()
            build.assert_not_called()
            summary = radial.load_json(next((root / "runs").glob("*/summary.json")))
            self.assertEqual(summary["role"], "oatof_radial_compaction_plan_summary")
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["native_units"], {})
            with self.assertRaisesRegex(ValueError, "not a published radial campaign"):
                radial._read_parent(next((root / "runs").iterdir()))

    def test_radius_rows_change_only_the_three_governed_radii(self) -> None:
        for row in self.config["radius_screen"]:
            candidate, _ = compile_design_overrides(self.baseline, _overrides(row))
            _assert_only_allowed_changes(
                self.baseline, candidate, allow_ring_counts=False
            )
            self.assertEqual(candidate["geometry_mm"]["flight_tube_wall"], 10.0)

    def test_case_preparation_rejects_existing_case_without_overwriting_contracts(self) -> None:
        case = self.config["radius_screen"][0]
        mesh = self.config["fixed_contract"]["default_reflectron_mesh_mm"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(radial, "prepare") as prepare:
                prepared = radial._prepare_case(case, root, self.baseline, 17, mesh)
            prepare.assert_called_once_with(
                prepared["resolved_path"], prepared["case_root"] / "prepared",
                particle_source_seed=17,
            )
            contracts = prepared["baseline_path"].parent
            self.assertEqual({path.name for path in contracts.iterdir()}, {
                "candidate_baseline.json", "candidate_resolved_geometry.json",
                "candidate_solver_numerics.json",
            })
            self.assertNotIn("diff_path", prepared)
            baseline_bytes = prepared["baseline_path"].read_bytes()
            resolved_bytes = prepared["resolved_path"].read_bytes()
            with patch.object(radial, "compile_design_overrides") as compiler, \
                    patch.object(radial, "prepare") as prepare:
                with self.assertRaisesRegex(ValueError, "new run identity"):
                    radial._prepare_case(case, root, self.baseline, 17, mesh)
            compiler.assert_not_called()
            prepare.assert_not_called()
            self.assertEqual(prepared["baseline_path"].read_bytes(), baseline_bytes)
            self.assertEqual(prepared["resolved_path"].read_bytes(), resolved_bytes)

    def test_case_preparation_does_not_accept_stale_or_incomplete_contracts(self) -> None:
        case = self.config["radius_screen"][0]
        mesh = self.config["fixed_contract"]["default_reflectron_mesh_mm"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(radial, "prepare"):
                prepared = radial._prepare_case(case, root, self.baseline, 17, mesh)
            (prepared["baseline_path"].parent / "candidate_solver_numerics.json").unlink()
            changed = {**case, "shared_shield_inner_radius_mm": 250.0}
            before = prepared["baseline_path"].read_bytes()
            with self.assertRaisesRegex(ValueError, "new run identity"):
                radial._prepare_case(changed, root, self.baseline, 18, mesh)
            self.assertEqual(prepared["baseline_path"].read_bytes(), before)

    def test_build_parent_uses_observation_without_hard_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = ["pwsh.exe", "-NoProfile", "-File", "builder.ps1"]
            with patch.object(radial, "run_observed_process", return_value=(
                    subprocess.CompletedProcess(command, 0), None)) as observe:
                result, _ = radial._observe_operation(command, cwd=root, stdout=root / "out", stderr=root / "err",
                    receipt_path=root / "operation.json", operation_id="build", resource_release_id="build", warning_seconds=1800)
            self.assertEqual(result.returncode, 0)
            observe.assert_called_once_with(
                command, cwd=root, stdout=root / "out", stderr=root / "err",
                warning_seconds=1800,
            )

    def test_process_observation_records_native_nonzero_without_calling_it_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(radial, "run_observed_process", return_value=(
                    subprocess.CompletedProcess(["pwsh.exe"], 7), None)):
                result, _ = radial._observe_operation(["pwsh.exe"], cwd=root, stdout=root / "out", stderr=root / "err",
                    receipt_path=root / "operation.json", operation_id="build", resource_release_id="build", warning_seconds=1800)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(radial.load_json(root / "operation.json")["operation"]["observation"],
                             {"exit_confirmed": True, "returncode": 7})

    def test_guarded_flight_consumes_native_profile_and_rejects_incomplete_owner_receipts(self) -> None:
        for arm in ("complete", "wrong_identity", "unknown_worker", "undrained_log", "worker_nonzero", "owner_nonzero"):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory(prefix="radial-guard-fixture-") as directory:
                root = Path(directory)
                case_root = root / "cases/shield260"
                case = {"case_root": case_root, "simion_dir": case_root / "simion",
                        "case_id": "shield260", "run_id": root.name, "context_sha256": "A" * 64,
                        "capacity_session_path": root / "session.json", "_resource_release_id": "flight:0:actual"}
                radial._write_json(root / "closure.json", {})
                radial._write_json(root / "run_config.json", {"inputs": {"execution_source_closure": str(root / "closure.json")}})
                receipt = {"schema_version": 1, "role": "oatof_candidate_flight_process_result",
                           "run_id": root.name, "case_id": case["case_id"], "mode": "actual",
                           "context_sha256": case["context_sha256"], "native_exit_confirmed": True,
                           "native_returncode": 0, "native_peak_working_set_bytes": 4096,
                           "native_elapsed_seconds": 2.75, "software_fixture": True,
                           "managed_process_completion": managed_process_fixture()}
                if arm == "wrong_identity": receipt["case_id"] = "other"
                if arm == "unknown_worker": receipt["managed_process_completion"]["worker_exit_confirmed"] = False
                if arm == "undrained_log": receipt["managed_process_completion"]["stdout_drained"] = False
                if arm == "worker_nonzero": receipt["managed_process_completion"] = managed_process_fixture(7)

                def observe(command, **kwargs):
                    radial._write_json(case_root / "results/actual_process_result.json", receipt)
                    radial._write_json(kwargs["receipt_path"], {"operation": {
                        "operation_id": kwargs["operation_id"], "resource_release_id": kwargs["resource_release_id"],
                        "observation": {"exit_confirmed": True, "returncode": 0}}})
                    return subprocess.CompletedProcess(command, 9 if arm == "owner_nonzero" else 0), 999999

                with patch.object(radial, "frozen_source_path", return_value=str(root / "guard.ps1")), \
                        patch.object(radial, "_observe_operation", side_effect=observe):
                    if arm == "complete":
                        self.assertEqual(radial._run_guarded_flight(case, "actual", ["fixture.exe"],
                            case_root / "logs/actual.log", case_root / "logs/actual.stderr.log"), (0, 4096, 2.75))
                    else:
                        with self.assertRaises((ValueError, RuntimeError)) as caught:
                            radial._run_guarded_flight(case, "actual", ["fixture.exe"],
                                case_root / "logs/actual.log", case_root / "logs/actual.stderr.log")
                        confirmed = arm in {"worker_nonzero", "owner_nonzero"}
                        self.assertEqual(caught.exception.observed_process_exit_confirmed, confirmed)
                        observation = radial.load_json(case_root / "results/actual_native_operation.json")
                        self.assertEqual(observation["operation"]["observation"]["exit_confirmed"], confirmed)

    def test_direct_analysis_matches_real_cli_diagnostics_and_csv(self) -> None:
        with tempfile.TemporaryDirectory(prefix="radial-analysis-equivalence-") as directory:
            root = Path(directory)
            ion, log = root / "source.ion", root / "source.log"
            ion.write_text("0,524,1,0,0,0,0,0,5,1,0\n" * 3, encoding="ascii")
            log.write_text("".join(
                f"TRACE: detector_crossing ion={i} t={t} x=0 y=0 z=0 r=0 zmax=4\n"
                for i, t in ((1, 1.0), (2, 1.1))
            ), encoding="utf-8")
            native = root / "predecessor_native.json"
            radial._write_json(native, {
                "schema_version": 1, "role": "oatof_radial_compaction_native_unit", "run_id": "predecessor",
                "case_id": "case", "mode": "actual", "context_sha256": "A" * 64,
                "particle_count": 3, "trajectory_quality": 8, "native_returncode": 0, "native_splats": 3,
                "stdout": str(log), "stderr": str(root / "native.stderr"), "ion": str(ion), "resource_profile": {},
            })
            case_root = root / "cases/case"
            case = {"case_root": case_root, "simion_dir": case_root / "simion", "case_id": "case",
                    "run_id": "software-fixture", "context_sha256": "A" * 64, "replay_units": {"actual": native}}
            with patch.object(radial.analysis, "canonical_metrics", return_value={}), \
                    patch.object(radial, "_run_guarded_flight") as fly, \
                    patch.object(radial, "run_managed_python_process") as managed:
                result = radial._fly(case, "actual", Path(sys.executable), 3, 8)
            fly.assert_not_called()
            managed.assert_not_called()
            cli_csv = root / "cli.csv"
            cli = subprocess.run([
                sys.executable, "-B", "-m", "projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics",
                "analyze-simion-log", "--log", str(log), "--ion-file", str(ion), "--mode", "actual",
                "--distribution", "fixedN3", "--detector-radius-mm", "40", "--particle-csv", str(cli_csv),
                "--allow-incomplete-census",
            ], cwd=radial.REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=True, timeout=120)
            self.assertEqual(result["diagnostics"], json.loads(cli.stdout))
            self.assertEqual((case_root / "results/actual_particles.csv").read_bytes(), cli_csv.read_bytes())
            self.assertFalse(list(case_root.rglob("*analysis*")))

    @unittest.skipUnless(shutil.which("pwsh"), "Production ION generator requires PowerShell")
    def test_campaign_source_rebuilds_its_named_mother_population(self) -> None:
        from common.ion_release.dotnet_gaussian_box_ion11 import generate_ion_source, _serialized_ion_source

        with tempfile.TemporaryDirectory(prefix="radial-source-identity-") as directory:
            root = Path(directory)
            fixed = self.config["fixed_contract"]
            case = radial._prepare_case(self.config["radius_screen"][0], root, self.baseline,
                                        fixed["particle_source_seed"], fixed["default_reflectron_mesh_mm"])
            resolved = radial.load_json(case["resolved_path"])
            source, target = resolved["particle_source"], resolved["validation_target"]
            options = {"MassAmu": target["mass_amu"], "Charge": 1,
                       "EnergyMeanEv": target["initial_energy_mean_ev"], "EnergyStdEv": target["initial_energy_sigma_ev"],
                       **{f"HalfWidth{axis.upper()}mm": source[f"size_{axis}_mm"] / 2 for axis in "xyz"},
                       **{f"Center{axis.upper()}mm": source[f"center_{axis}_mm"] for axis in "xyz"},
                       "Seed": fixed["particle_source_seed"]}
            outputs = {}
            for count in (100, fixed["particle_count"]):
                path = root / f"N{count}.ion"
                result = subprocess.run(["pwsh", "-NoProfile", "-File",
                    str(PROJECT_ROOT / "simion/workbench/generate_comsol_consistent_ions.ps1"),
                    "-PythonExe", sys.executable, "-N", str(count), "-Output", str(path),
                    *[value for key, value in options.items() for value in (f"-{key}", str(value))]],
                    cwd=radial.REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
                    env={**radial.os.environ, "PYTHONPATH": str(radial.REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                outputs[count] = path.read_bytes()
            self.assertEqual(radial.hashlib.sha256(outputs[1000]).hexdigest().upper(), fixed["particle_table_sha256"])
            self.assertEqual(outputs[100], b"\r\n".join(outputs[1000].splitlines()[:100]) + b"\r\n")
            self.assertEqual(radial.hashlib.sha256(outputs[100]).hexdigest().upper(),
                             "3BD65B6CD43C5C122708D98BBD0BC0D9BD599D9FBBF17C5BB76B469613ECF26D")
            old_source = _serialized_ion_source(generate_ion_source(
                particle_count=fixed["particle_count"], mass_amu=target["mass_amu"], charge=1,
                energy_mean_ev=target["initial_energy_mean_ev"], energy_std_ev=target["initial_energy_sigma_ev"],
                half_width_xyz_mm=tuple(source[f"size_{axis}_mm"] / 2 for axis in "xyz"),
                center_xyz_mm=tuple(source[f"center_{axis}_mm"] for axis in "xyz"), seed=20260713,
            ))
            self.assertNotEqual(radial.hashlib.sha256(old_source).hexdigest().upper(), fixed["particle_table_sha256"])

    def test_runtime_requires_authorized_campaign(self) -> None:
        self.assertEqual(self.config["status"], "authorized")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "campaign.json"
            path.write_text(json.dumps({**self.config, "status": "retired"}), encoding="utf-8")
            with patch.object(radial, "CONFIG_PATH", path), \
                    patch.object(radial, "_verify_authorities", return_value=(path, path)):
                with self.assertRaisesRegex(ValueError, "not an active authorized"):
                    radial._freeze_run(root / "runs" / "20261028_120000__test__simion__radial", Path(sys.executable), None)
            self.assertFalse((root / "runs").exists())

    def test_case_flights_delegate_wave_selection_to_the_shared_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for case_id in ("one", "two"):
                case_root = root / case_id
                simion_dir = case_root / "simion"
                simion_dir.mkdir(parents=True)
                (simion_dir / "oatof_ideal_grounded.iob").write_text("iob", encoding="utf-8")
                (simion_dir / "oatof_comsol_524amu_gaussian_N2.ion").write_text("ions", encoding="utf-8")
                cases.append({"case_id": case_id, "case_root": case_root, "simion_dir": simion_dir})
            selected = []

            def fake_fly(case, mode, simion_exe, particle_count, trajectory_quality):
                selected.append(case["case_id"])
                return {
                    "resource_profile": {
                        "resource_identity": {"case_input_sha256": case["case_id"] * 64},
                        "per_batch_peak_working_set_bytes": 10,
                    }
                }

            dispatch = {
                "waves": [{"cases": [{"case_id": "one"}, {"case_id": "two"}]}]
            }
            with patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign.plan_simion_case_dispatch",
                return_value=dispatch,
            ) as planner, patch(
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign._fly",
                side_effect=fake_fly,
            ), patch.object(radial, "_bind_pool_execution_context"):
                results = _run_parallel_flights(cases, "actual", Path("simion.exe"), 2, 8)
            self.assertEqual(set(results), {"one", "two"})
            self.assertEqual(set(selected), {"one", "two"})
            request = planner.call_args.args[1]
            self.assertEqual(request, {"solver": "SIMION", "field_kind": "electrostatic"})

    def test_smallest_shield_contains_offset_detector(self) -> None:
        smallest = min(
            self.config["radius_screen"],
            key=lambda row: row["shared_shield_inner_radius_mm"],
        )
        convention = self.baseline["coordinate_convention"]
        required = abs(convention["detector_x"]) + self.baseline["geometry_mm"][
            "detector_radius"
        ]
        self.assertGreaterEqual(smallest["shared_shield_inner_radius_mm"], required)

    def test_ring_compensation_changes_only_counts_in_addition_to_radii(self) -> None:
        target_id = self.config["ring_count_compensation"]["target_case_id"]
        target = next(row for row in self.config["radius_screen"] if row["case_id"] == target_id)
        for ring_case in self.config["ring_count_compensation"]["cases"]:
            row = {**target, **ring_case}
            candidate, _ = compile_design_overrides(self.baseline, _overrides(row))
            _assert_only_allowed_changes(
                self.baseline, candidate, allow_ring_counts=True,
                allowed_geometry_keys={
                    "ring_thickness", "shield_bore_z_max", "shield_outer_z_max"
                }
                if "ring_thickness_mm" in row else set(),
            )

    def test_stable_grid_override_is_explicit_and_only_changes_reflectron_axial_cell(self) -> None:
        self.assertEqual(
            self.config["fixed_contract"]["default_reflectron_mesh_mm"],
            {"axial": 0.1, "radial": 1.0},
        )
        grid_cases = [
            row
            for row in self.config["ring_count_compensation"]["cases"]
            if "reflectron_cell_axial_mm" in row
        ]
        self.assertGreaterEqual(len(grid_cases), 1)
        self.assertEqual(
            {row["reflectron_cell_axial_mm"] for row in grid_cases},
            {0.05, 0.1, 0.4},
        )
        source = json.loads(NUMERICS_PATH.read_text(encoding="utf-8"))
        changed = copy.deepcopy(source)
        changed["simion"]["geometry_build"]["reflectron"]["cell_axial_mm"] = 0.4
        source["simion"]["geometry_build"]["reflectron"].pop("cell_axial_mm")
        changed["simion"]["geometry_build"]["reflectron"].pop("cell_axial_mm")
        self.assertEqual(changed, source)

    def test_compensation_ideal_field_targets_are_declared_cases(self) -> None:
        compensation = self.config["ring_count_compensation"]
        case_ids = {row["case_id"] for row in compensation["cases"]}
        self.assertTrue(
            set(compensation["ideal_field_diagnostic_case_ids"]).issubset(case_ids)
        )

    def test_one_millimetre_manufacturing_gap_is_enforced(self) -> None:
        target = next(
            row for row in self.config["radius_screen"] if row["case_id"] == "shield100"
        )
        invalid = {**target, "stage1_count": 7, "stage2_count": 17}
        with self.assertRaisesRegex(ValueError, "stage-2 ring gap"):
            compile_design_overrides(self.baseline, _overrides(invalid))
        valid = {**target, "stage1_count": 7, "stage2_count": 15}
        candidate, _ = compile_design_overrides(self.baseline, _overrides(valid))
        gap = candidate["geometry_mm"]["L_stage2"] / 16 - candidate["geometry_mm"][
            "ring_thickness"
        ]
        self.assertGreaterEqual(gap, 1.0)

    def test_nonradius_change_is_rejected(self) -> None:
        candidate = copy.deepcopy(self.baseline)
        candidate["geometry_mm"]["L_flight"] -= 1.0
        with self.assertRaisesRegex(ValueError, "non-authorized"):
            _assert_only_allowed_changes(
                self.baseline, candidate, allow_ring_counts=False
            )

    def test_simion_flights_use_elapsed_warnings_not_process_timeouts(self) -> None:
        source = inspect.getsource(radial._run_guarded_flight)
        self.assertIn("warning_seconds=1800", source)
        self.assertNotIn("timeout_seconds=1800", source)

    def test_builder_consumes_frozen_plan_and_same_capacity_session_without_file_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_root = root / "cases" / "case"
            simion = case_root / "simion"
            simion.mkdir(parents=True)
            for name in ("reflectron.pa#", "reflectron.pa0", "reflectron.pa1"):
                (simion / name).write_text("incomplete native fixture", encoding="utf-8")
            source_id = "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1"
            closure = root / "inputs" / "closure.json"
            radial._write_json(closure, {"schema_version": 2,
                "role": "oa_tof_candidate_execution_source_closure", "code_root": str(root / "frozen"),
                "sources": [{"source_id": source_id}]})
            radial._write_json(root / "run_config.json", {"inputs": {"execution_source_closure": str(closure)}})
            case = {"case_id": "case", "case_root": case_root, "simion_dir": simion,
                    "baseline_path": case_root / "baseline.json", "resolved_path": case_root / "resolved.json",
                    "text_dir": case_root / "text", "context_sha256": "A" * 64,
                    "capacity_session_path": root / "session.json", "component_plan_path": root / "inputs/plan.json"}
            build = {"schema_version": 1, "role": "oatof_component_build_completion",
                     "run_id": "20261028_120000__test__simion__radial-build", "context_sha256": "A" * 64,
                     "operations": [{"operation_id": "build", "observation": {"exit_confirmed": True, "returncode": 0},
                                     "managed_process_completion": managed_process_fixture()}]}
            radial._write_json(case_root / "logs/build_completion.json", build)
            with patch.object(radial, "_observe_operation", return_value=(subprocess.CompletedProcess([], 0), None)) as run:
                radial._build_case(case, simion_exe=Path(sys.executable), template_iob=root / "template.iob",
                                   seed=17, run_id="20261028_120000__test__simion__radial-build", particle_count=100)
                command = run.call_args.args[0]
                for option, value in (("-ComponentPlanPath", case["component_plan_path"]),
                                      ("-CapacitySessionPath", case["capacity_session_path"]),
                                      ("-ParticleCount", 100)):
                    self.assertEqual(command[command.index(option) + 1], str(value))
                self.assertEqual(command[command.index("-File") + 1], str(root / "frozen" / source_id))
                self.assertFalse({"-ReuseComponents", "-ReusableComponentDir", "-ResumeRefinedReflectron"} & set(command))
                self.assertNotIn("-ProducerHandoffPath", command)
                self.assertTrue(case["build_complete"])
                handoff = root / "inputs/pa_producer_handoffs/handoffs.json"
                radial._write_json(handoff, {"software_fixture": True})
                radial._write_json(root / "run_config.json", {
                    "inputs": {"execution_source_closure": str(closure), "pa_producer_handoffs": str(handoff)},
                    "pa_producer_handoffs": radial.file_record(handoff),
                })
                case.pop("build_complete")
                radial._build_case(case, simion_exe=Path(sys.executable), template_iob=root / "template.iob",
                                   seed=17, run_id=build["run_id"], particle_count=100)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index("-ProducerHandoffPath") + 1], str(handoff))
                for arm in ("worker_nonzero", "worker_unknown", "native_unknown"):
                    with self.subTest(arm=arm):
                        case.pop("build_complete", None)
                        changed = copy.deepcopy(build)
                        operation = changed["operations"][0]
                        if arm == "worker_nonzero": operation["managed_process_completion"] = managed_process_fixture(1)
                        if arm == "worker_unknown": operation["managed_process_completion"]["worker_started_at_utc_ticks"] = None
                        if arm == "native_unknown": operation["observation"]["exit_confirmed"] = False
                        radial._write_json(case_root / "logs/build_completion.json", changed)
                        with self.assertRaisesRegex(RuntimeError, "native/helper completion failed") as caught:
                            radial._build_case(case, simion_exe=Path(sys.executable), template_iob=root / "template.iob",
                                               seed=17, run_id=build["run_id"], particle_count=100)
                        self.assertEqual(caught.exception.observed_process_exit_confirmed, arm == "worker_nonzero")
                        self.assertFalse(case.get("build_complete", False))

    def test_builder_closeout_keeps_native_and_managed_facts_separate(self) -> None:
        for arm in ("worker_nonzero", "worker_unknown", "native_unknown"):
            with self.subTest(arm=arm):
                managed = managed_process_fixture(1 if arm == "worker_nonzero" else 0)
                if arm == "worker_unknown": managed["worker_exit_confirmed"] = False
                native = {"exit_confirmed": arm != "native_unknown", "returncode": 0,
                          "native_peak_working_set_bytes": 4096, "error": "original observation failure"}
                build = {"operations": [{"operation_id": "refine", "observation": native,
                                         "managed_process_completion": managed}]}
                before = copy.deepcopy(build)
                rows = radial._builder_writer_operations(build, "case")
                self.assertEqual(rows[0]["observation"], {key: native[key] for key in ("exit_confirmed", "returncode")})
                self.assertEqual(rows[1]["observation"]["exit_confirmed"], arm != "worker_unknown")
                self.assertEqual(rows[1]["observation"]["returncode"], managed["exit_code"])
                self.assertEqual(build, before)
                self.assertTrue(all(row["resource_release_id"] == "build:case" for row in rows))


if __name__ == "__main__":
    unittest.main()
