"""Contract, negative-result, checkpoint and end-to-end ideal comparison tests."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.machine_contracts import load_json, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_experiment import (
    build_case_plan, summarize_stage, validate_experiment,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison import run_comparison as runner


class IdealExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_json(runner.DEFAULT_CONFIG)

    def test_plan_order_and_pairing_seeds(self) -> None:
        plan = build_case_plan(self.config, 71)
        self.assertEqual(len(plan), 84)
        self.assertTrue(all(c["stage"] == "residual_scan" for c in plan[:21]))
        self.assertTrue(all(c["stage"] == "width_scan" for c in plan[21:]))
        self.assertEqual({c["seed"] for c in plan}, {71, 72, 73})
        self.assertEqual(len({c["case_id"] for c in plan}), 84)

    def test_registered_entry_resolves_to_the_science_authority(self) -> None:
        profiles = load_json(runner.PROJECT_ROOT / "config/execution_profiles.json")
        validate_schema(profiles, "execution_profiles.schema.json")
        profile = next(p for p in profiles["profiles"] if p["profile_id"] == "ideal_source_comparison")
        self.assertEqual(profile["evidence_levels"], ["static"])
        step = profile["steps"][0]
        self.assertTrue((runner.PROJECT_ROOT / step["entrypoint"]).is_file())
        self.assertEqual((runner.REPO_ROOT / step["arguments"][1]).resolve(), runner.DEFAULT_CONFIG)

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
            with patch.object(Path, "replace", side_effect=OSError("interrupted publish")):
                with self.assertRaises(OSError):
                    runner._write_json(path, {"complete": True})
            self.assertFalse(path.exists())
            self.assertTrue(path.with_suffix(".json.pending").exists())

    def test_manifest_arguments_stay_short_for_full_matrix_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            for case in build_case_plan(self.config, 7):
                for suffix in (".json", "__particles.csv"):
                    (root / "results" / (case["case_id"] + suffix)).touch()
            with patch.object(runner, "_command", return_value="PASS") as command, contextlib.redirect_stdout(io.StringIO()):
                runner._publish_manifest(root, "success")
            arguments = command.call_args_list[0].args[0]
            self.assertLess(len(" ".join(arguments)), 30000)
            output_arguments = [arguments[i+1] for i, value in enumerate(arguments) if value == "--output"]
            self.assertTrue(all(not Path(path).is_absolute() for path in output_arguments))

    def test_run_failure_resume_manifest_and_tamper_detection(self) -> None:
        config = copy.deepcopy(self.config)
        config["sampling"] = {"particle_count": 100, "replicate_count": 1}
        config["residual_scan"]["residual_sigma_m_per_s"] = [0, 100]
        config["width_scan"]["full_widths_mm"] = [1.0, 2.2]
        config["width_scan"]["residual_sigma_m_per_s"] = [0]
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            config_path = root / "experiment.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            original = runner._run_case

            def fail_second(case, *args):
                if case["case_id"] == "residual_scan__0002":
                    raise ArithmeticError("injected exact-model failure")
                return original(case, *args)

            with patch.object(runner, "_run_case", side_effect=fail_second):
                failed = runner.execute(config_path, seed=9, run_id="20260827_010000__test__python__ideal-source-failure", artifact_root=root)
            self.assertEqual(load_json(failed / "summary.json")["completed_cases"], 1)
            self.assertEqual(load_json(failed / "run_manifest.json")["status"], "failed")
            resumed = runner.execute(config_path, seed=9, run_id="20260827_010001__test__python__ideal-source-resume", resume_from=failed, artifact_root=root)
            summary = load_json(resumed / "summary.json")
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["completed_cases"], 4)
            self.assertEqual(summary["reused_cases"], 1)
            self.assertEqual(len(summary["stages"]), 2)
            self.assertEqual(load_json(resumed / "run_manifest.json")["schema_version"], 2)
            with self.assertRaisesRegex(ValueError, "differs"):
                runner.execute(config_path, seed=10, run_id="20260827_010002__test__python__ideal-source-mismatch", resume_from=failed, artifact_root=root)
            checkpoint = failed / "results/residual_scan__0001.json"
            data = load_json(checkpoint)
            data["resolution_gain_percent"] = 999999
            checkpoint.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "copy"
            destination.mkdir()
            with self.assertRaisesRegex(ValueError, "mismatch"):
                runner._reuse_case(failed, data["case"], data["identity"], destination)


if __name__ == "__main__":
    unittest.main()
