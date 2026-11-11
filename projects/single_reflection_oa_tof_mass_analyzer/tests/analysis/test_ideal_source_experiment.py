"""Contract, negative-result, checkpoint and end-to-end ideal comparison tests."""

from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.contracts.machine_contracts import load_json, validate_schema
from msplatform.workflows.oa_tof_design.source_experiment import (
    build_case_plan, summarize_stage, validate_experiment,
)
from msplatform.workflows.oa_tof_design import source_comparison as runner


from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.ideal_source_workflow import (
    copy_input_root, make_context, owned_workflow_environment, retained_workspace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


class IdealExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_json(PROJECT_ROOT / "config/experiments/ideal_source_comparison.json")

    def test_plan_order_and_pairing_seeds(self) -> None:
        plan = build_case_plan(self.config, 71)
        self.assertEqual(len(plan), 84)
        self.assertTrue(all(c["stage"] == "residual_scan" for c in plan[:21]))
        self.assertTrue(all(c["stage"] == "width_scan" for c in plan[21:]))
        self.assertEqual({c["seed"] for c in plan}, {71, 72, 73})
        self.assertEqual(len({c["case_id"] for c in plan}), 84)

    def test_registered_entry_resolves_to_the_science_authority(self) -> None:
        profiles = load_json(PROJECT_ROOT / "config/execution_profiles.json")
        validate_schema(profiles, "execution_profiles.schema.json")
        profile = next(p for p in profiles["profiles"] if p["profile_id"] == "ideal_source_comparison")
        self.assertEqual(profile["action"], "analyze")
        self.assertEqual(profile["qualification_support"], ["none"])
        self.assertEqual(profile["tools"], ["python"])
        self.assertEqual(profile["required_bindings"],
                         ["particle_source_seed", "workspace", "execution_environment", "environment_profile"])
        self.assertEqual(profile["binding_types"], {"particle_source_seed": "integer",
                         "workspace": "directory", "execution_environment": "file", "environment_profile": "string"})
        self.assertEqual(profile["deliverable_outputs"], ["simulation_results", "validation_report"])
        self.assertEqual(profile["fixed_inputs"]["experiment"], "config/experiments/ideal_source_comparison.json")
        self.assertEqual(profile["fixed_inputs"]["analysis_contract"], "config/analysis_contract.json")
        self.assertEqual(len(profile["steps"]), 1)
        step = profile["steps"][0]
        self.assertEqual((step["kind"], step["shell"]), ("analyze", "python"))
        self.assertEqual(step["arguments"][2:], ["--seed", "{particle_source_seed}", "--run-id", "{run_id}",
                         "--input-root", "projects/single_reflection_oa_tof_mass_analyzer",
                         "--workspace", "{workspace}", "--environment", "{execution_environment}",
                         "--profile", "{environment_profile}"])
        self.assertTrue((PROJECT_ROOT / step["entrypoint"]).is_file())
        self.assertEqual((PROJECT_ROOT / step["entrypoint"]).resolve(), Path(runner.__file__).resolve())
        self.assertEqual((PROJECT_ROOT / step["entrypoint"]).resolve().relative_to(REPO_ROOT / "src")
                         .with_suffix("").as_posix().replace("/", "."),
                         "msplatform.workflows.oa_tof_design.source_comparison")
        self.assertEqual((REPO_ROOT / step["arguments"][1]).resolve(), PROJECT_ROOT / "config/experiments/ideal_source_comparison.json")

    def test_contract_rejects_unknown_missing_nonfinite_and_duplicate(self) -> None:
        for key, value in (("three_zone_eta", 0), ("focus_drift_mm", float("nan")), ("extra", 1)):
            changed = copy.deepcopy(self.config)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_experiment(changed)
        changed = copy.deepcopy(self.config)
        del changed["source"]["center_x_mm"]
        with self.assertRaises(ValueError):
            validate_experiment(changed)
        changed = copy.deepcopy(self.config)
        changed["width_scan"]["full_widths_mm"] = [1.0, 1.0]
        with self.assertRaises(ValueError):
            validate_experiment(changed)

    def _records(self, stage: str) -> list[dict]:
        return [{"case": case, "comparison_eligible": True, "resolution_gain_percent": 1.0,
                 "arms": {name: {"resolution": 30000, "model_arrival_fraction": 1.0}
                          for name in ("two_zone_matched", "three_zone_matched")}}
                for case in build_case_plan(self.config, 71) if case["stage"] == stage]

    def test_negative_scientific_result_is_not_execution_failure(self) -> None:
        result = summarize_stage("residual_scan", self._records("residual_scan"), self.config)
        self.assertEqual(result["execution_status"], "success")
        self.assertEqual(result["scientific_status"], "NOT_SUPPORTED")

    def test_missing_and_duplicate_rows_cannot_create_empty_all_pass(self) -> None:
        for stage in ("residual_scan", "width_scan"):
            records = self._records(stage)
            for broken in (records[:-1], records + records[:1], []):
                with self.subTest(stage=stage), self.assertRaises(ValueError):
                    summarize_stage(stage, broken, self.config)

    def test_acceptance_stops_at_first_failing_width(self) -> None:
        records = self._records("width_scan")
        for record in records:
            if record["case"]["full_width_mm"] == 1.0:
                record["arms"]["two_zone_matched"]["model_arrival_fraction"] = 0.99
        result = summarize_stage("width_scan", records, self.config)
        row = result["acceptance"][0]
        self.assertEqual(row["contiguous_tested_accepted_width_mm"], 0.5)
        self.assertEqual(row["first_failing_width_mm"], 1.0)
        self.assertTrue(row["upper_limit_bracketed"])

    def test_undefined_peak_is_not_an_acceptance_failure_boundary(self) -> None:
        records = self._records("width_scan")
        for record in records:
            if record["case"]["full_width_mm"] == 1.0:
                record["arms"]["two_zone_matched"]["resolution"] = None
        row = summarize_stage("width_scan", records, self.config)["acceptance"][0]
        self.assertIsNone(row["first_failing_width_mm"])
        self.assertEqual(row["first_inconclusive_width_mm"], 1.0)
        self.assertFalse(row["upper_limit_bracketed"])

    def test_checkpoint_is_only_visible_after_atomic_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            with patch("msplatform.execution.recorded_file_removal.os.replace",
                       side_effect=OSError("interrupted publish")):
                with self.assertRaises(OSError):
                    runner._write_json(path, {"complete": True})
            self.assertFalse(path.exists())
            self.assertFalse(list(path.parent.glob(f".{path.name}.*")))

    def test_manifest_arguments_stay_short_for_full_matrix_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            for case in build_case_plan(self.config, 7):
                for suffix in (".json", "__particles.csv"):
                    (root / "results" / (case["case_id"] + suffix)).touch()
            request = root / "scientific_request.json"
            outputs = [str(path.relative_to(root)) for path in (root / "results").iterdir()]
            request.write_text(json.dumps({"outputs": outputs}), encoding="utf-8")
            # Transport-only observation stops at the actual managed child call;
            # no worker completion, process receipt or owner success is fabricated.
            session = SimpleNamespace(context=SimpleNamespace(powershell_executable="selected-pwsh"))
            with patch.object(session, "run_process", create=True,
                              side_effect=RuntimeError("observed managed child boundary")) as command:
                with self.assertRaisesRegex(RuntimeError, "observed managed child boundary"):
                    runner._invoke_worker(session, request, [], {"limits": {}})
            arguments = command.call_args.kwargs["arguments"]
            self.assertLess(len(" ".join(arguments)), 30000)
            self.assertEqual(command.call_args.kwargs["environment"],
                             {"OA_TOF_SCIENTIFIC_REQUEST": str(request)})
            self.assertNotIn("--output", arguments)
            self.assertTrue(all(not Path(path).is_absolute() for path in load_json(request)["outputs"]))
            self.assertEqual(len(load_json(request)["outputs"]), 168)

    def test_finalization_cli_transports_the_same_no_particle_completion_policy(self) -> None:
        from msplatform.execution.completion import no_particle_batch_completion_api
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = make_context(root / "study")
            result = root / "result.json"
            # CLI dispatch unit only: actual finalization/unknown-writer behavior
            # remains with the existing owner tests, not this controlled return.
            with patch("msplatform.execution.context.load_environment", return_value=context) as environment, \
                    patch("msplatform.execution.owner.resume_finalization", return_value={"status": "success"}) as resume, \
                    patch.object(runner, "execute", side_effect=AssertionError("finalization cannot rerun science")) as science:
                self.assertEqual(runner.main(["--workspace", str(context.workspace), "--environment", str(root / "machine.json"),
                                              "--profile", "explicit-test", "--resume-finalization", str(result)]), 0)
                resume.assert_called_once_with(context, result_path=result,
                                               completion_api=no_particle_batch_completion_api)
                environment.assert_called_once()
                science.assert_not_called()

    def test_run_failure_resume_manifest_and_tamper_detection(self) -> None:
        config = copy.deepcopy(self.config)
        config["sampling"] = {"particle_count": 100, "replicate_count": 1}
        config["residual_scan"]["residual_sigma_m_per_s"] = [0, 100]
        config["width_scan"]["full_widths_mm"] = [1.0, 2.2]
        config["width_scan"]["residual_sigma_m_per_s"] = [0]
        with retained_workspace() as root, contextlib.redirect_stdout(io.StringIO()):
            input_root = copy_input_root(PROJECT_ROOT, root / "author-inputs")
            context = make_context(root / "study")
            config_path = root / "experiment.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            source_provider = runner._source_package_root()
            provider = root / "controlled-provider/msplatform"
            shutil.copytree(source_provider, provider, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            kernel = provider / "workflows/oa_tof_design/numerical_case.py"
            source = kernel.read_text(encoding="utf-8")
            original_node = next(node for node in ast.parse(source).body
                                 if isinstance(node, ast.FunctionDef) and node.name == "_run_case")
            marker = root / "explicit-case2-fault.json"
            # Only this TEST provider has the one-shot fault. The marker is outside
            # every frozen package/input; no production test flag or fake receipt.
            prologue = (
                '    if case["case_id"] == "residual_scan__0002":\n'
                '        from pathlib import Path as _FixturePath\n'
                f'        _fixture_marker = _FixturePath({str(marker)!r})\n'
                '        if not _fixture_marker.exists():\n'
                '            _fixture_marker.write_text("case2 explicit once-only fixture failure", encoding="utf-8")\n'
                '            raise ArithmeticError("injected exact-model failure")\n'
            )
            lines = source.splitlines(keepends=True)
            lines.insert(original_node.body[0].lineno - 1, prologue)
            kernel.write_text("".join(lines), encoding="utf-8", newline="\n")
            controlled_node = next(node for node in ast.parse(kernel.read_text(encoding="utf-8")).body
                                   if isinstance(node, ast.FunctionDef) and node.name == "_run_case")
            controlled_node.body = controlled_node.body[1:]
            self.assertEqual(ast.dump(controlled_node, include_attributes=False),
                             ast.dump(original_node, include_attributes=False))
            provider_before = {path.relative_to(provider): path.read_bytes()
                               for path in provider.rglob("*") if path.is_file()}
            source_files = runner._source_files

            def selected_sources(*args):
                return {name: (provider / path.relative_to(source_provider)
                               if path.is_relative_to(source_provider) else path)
                        for name, path in source_files(*args).items()}

            with patch.object(runner, "_source_package_root", return_value=provider), \
                    patch.object(runner, "_source_files", side_effect=selected_sources), \
                    owned_workflow_environment():
                self.assertFalse(marker.exists())
                failed = runner.execute(config_path, input_root=input_root, context=context, seed=9,
                    run_id="20260827_010000__test__python__ideal-source-failure")
                self.assertEqual(load_json(failed / "summary.json")["completed_cases"], 1)
                self.assertEqual(load_json(failed / "run_manifest.json")["status"], "failed")
                self.assertIn("ArithmeticError: injected exact-model failure",
                              load_json(failed / "summary.json")["failure_reason"])
                self.assertEqual(marker.read_text(encoding="utf-8"), "case2 explicit once-only fixture failure")
                first_csv = (failed / "results/residual_scan__0001__particles.csv").read_bytes()
                resumed = runner.execute(config_path, input_root=input_root, context=context, seed=9,
                    run_id="20260827_010001__test__python__ideal-source-resume", resume_from=failed)
                summary = load_json(resumed / "summary.json")
                self.assertEqual(summary["status"], "success")
                self.assertEqual(summary["completed_cases"], 4)
                self.assertEqual(summary["reused_cases"], 1)
                self.assertEqual(len(summary["stages"]), 2)
                self.assertEqual((resumed / "results/residual_scan__0001__particles.csv").read_bytes(), first_csv)
                self.assertEqual(load_json(resumed / "run_manifest.json")["schema_version"], 2)
                frozen = load_json(resumed / "run_config.json")
                self.assertIn("entrypoint", frozen["input_sha256"])
                self.assertIn("ideal_source_comparison_plot", frozen["input_sha256"])
                self.assertNotIn("entrypoint", frozen["numerical_input_sha256"])
                self.assertNotIn("ideal_source_comparison_plot", frozen["numerical_input_sha256"])
                self.assertFalse((resumed / "results/resolved_plan.json").exists())
                self.assertEqual(load_json(resumed / "results/working_points.json"),
                                 {"schema_version": 2, "role": "ideal_source_working_points",
                                  "working_points": {name: point.to_dict() for name, point in runner._working_points(config).items()}})
                working_points = load_json(resumed / "results/working_points.json")
                for point in working_points["working_points"].values():
                    self.assertIn("center_extraction_position_mm", point["design_source"])
                    self.assertIn("time_scale_s_sqrt_v_per_mm", point["design_source"])
                    self.assertNotIn("center_x_mm", point["design_source"])
                    self.assertNotIn("time_scale_s_per_mm_sqrt_v", point["design_source"])
                for run in (failed, resumed):
                    completion = load_json(run / "results/execution_completion.json")
                    operations = completion["writer_completion"]["operations"]
                    self.assertEqual([row["operation_id"] for row in operations], ["scientific_analysis"])
                    self.assertEqual(operations[0]["observation"]["returncode"], 0)
                    self.assertGreater(operations[0]["observation"]["process_id"], 0)
                with self.assertRaisesRegex(ValueError, "differs"):
                    runner.execute(config_path, input_root=input_root, context=context, seed=10,
                        run_id="20260827_010002__test__python__ideal-source-mismatch", resume_from=failed)
                fixed_kernel = kernel.read_bytes()
                try:
                    kernel.write_bytes(fixed_kernel + b"\n# Explicit changed scientific-source fixture.\n")
                    with self.assertRaisesRegex(ValueError, "differs"):
                        runner.execute(config_path, input_root=input_root, context=context, seed=9,
                            run_id="20260827_010003__test__python__ideal-source-code-mismatch", resume_from=failed)
                finally:
                    kernel.write_bytes(fixed_kernel)
            self.assertEqual(provider_before, {path.relative_to(provider): path.read_bytes()
                                              for path in provider.rglob("*") if path.is_file()})
            checkpoint = failed / "results/residual_scan__0001.json"
            data = load_json(checkpoint)
            data["resolution_gain_percent"] = 999999
            checkpoint.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "tampered_child/results"
            destination.mkdir(parents=True)
            (destination.parent / "run_config.json").write_text(json.dumps({"inputs": {}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                runner._reuse_case(failed, data["case"], data["identity"], destination)



if __name__ == "__main__":
    unittest.main()
