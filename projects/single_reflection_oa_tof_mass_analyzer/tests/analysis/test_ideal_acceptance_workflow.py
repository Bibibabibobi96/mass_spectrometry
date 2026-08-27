"""Theory-first configuration and automatic pipeline regression tests."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.machine_contracts import load_json
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison import acceptance_theory as workflow
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison import run_comparison as runner


class AcceptanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.config = load_json(runner.PROJECT_ROOT / "config/experiments/ideal_acceptance_theory.json")

    def test_declared_domain_and_unknown_fields(self):
        workflow.validate_theory_config(self.config)
        for key, value in (("extra", 1), ("full_widths_mm", [2.8, 2.8]), ("minimum_resolution", -1)):
            invalid = copy.deepcopy(self.config)
            invalid[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                workflow.validate_theory_config(invalid)

    def test_parallel_worker_cap_is_execution_only_and_bounded(self):
        with patch.object(workflow.os, "cpu_count", return_value=32):
            self.assertEqual(workflow._resolve_parallel_workers(None, 12), 8)
            self.assertEqual(workflow._resolve_parallel_workers(2, 12), 2)
            self.assertEqual(workflow._resolve_parallel_workers(20, 3), 3)
        with self.assertRaises(ValueError):
            workflow._resolve_parallel_workers(0, 1)

    def test_single_candidate_automatic_end_to_end(self):
        self.config["design"].update(field1_v_per_mm=[250/3.25], center_to_grid1_mm=[3.25-1.498375640839315],
            grid2_voltage_fraction=[0.868348002459428], reflectron_stage1_energy_fraction=[1701.7426470174573/2000],
            selected_per_width=1)
        self.config["full_widths_mm"] = [2.8]
        self.config["numerics"].update(position_order=8, residual_order=4, population_orders=[[8, 8], [16, 16]])
        self.config["numerics"]["population_resolution_relative_tolerance"] = .9
        self.config["sampling"] = {"particle_count": 64, "replicate_count": 1}
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "experiment.json"
            config_path.write_text(json.dumps(self.config), encoding="utf-8")
            with patch.object(workflow, "_publish_manifest") as publish, contextlib.redirect_stdout(io.StringIO()):
                result = runner.execute(config_path, seed=41, run_id="20260827_210001__analysis__python__theory-test",
                                        artifact_root=Path(directory) / "artifacts", max_workers=2)
            summary = load_json(result / "summary.json")
            self.assertEqual(summary["status"], "success", summary)
            self.assertGreaterEqual(summary["completed_confirmations"], 1)
            self.assertFalse(summary["global_maximum_proved"])
            self.assertTrue((result / "results/all_theory_equations.csv").is_file())
            selected = load_json(result / "results/screened_designs.json")
            self.assertEqual(len(selected["2.8"]), 1)
            self.assertFalse(selected["2.8"][0]["theory"]["particle_peak_optimization_performed"])
            self.assertGreaterEqual(len(list((result / "results").glob("*__seed41.csv"))), 1)
            receipt = load_json(result / "run_config.json")["execution"]
            self.assertEqual(receipt["requested_max_workers"], 2)
            self.assertFalse(receipt["scientific_inputs_changed"])
            publish.assert_called_once_with(result, "success")

    def test_fixed_length_and_direct_density_end_to_end(self):
        config = load_json(runner.PROJECT_ROOT / "config/experiments/ideal_acceptance_fixed_length.json")
        config["design"].update(field1_v_per_mm=[250/3.25], center_to_grid1_mm=[2.5],
            grid2_voltage_fraction=[.975], reflectron_stage1_energy_fraction=[v/2000 for v in range(1800, 1901, 5)])
        config["full_widths_mm"] = [3.0]
        config["numerics"].update(position_order=8, residual_order=4, population_orders=[[8, 201], [16, 401]])
        config["numerics"]["population_resolution_relative_tolerance"] = .9
        config["sampling"] = {"particle_count": 64, "replicate_count": 1}
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "experiment.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(workflow, "_publish_manifest"), contextlib.redirect_stdout(io.StringIO()):
                result = runner.execute(config_path, seed=41, run_id="20260827_210002__analysis__python__theory-test",
                                        artifact_root=Path(directory) / "artifacts")
            summary = load_json(result / "summary.json")
            self.assertEqual(summary["status"], "success", summary)
            self.assertEqual(summary["completed_confirmations"], 1)
            selected = load_json(result / "results/screened_designs.json")["3.0"][0]
            self.assertAlmostEqual(sum(selected["theory"]["zone_lengths_mm"]), 20.25, places=6)
            report = load_json(result / "results" / (selected["design_id"]+"__w3.json"))
            self.assertEqual(report["population"][-1]["method"], "exact_population_pushforward")
            self.assertGreater(report["population"][-1]["resolution_mass"], 25000)
            self.assertEqual(len(list((result / "results").glob("*__population*.csv"))), 4)

    def test_screen_limit_applies_to_every_width(self):
        config = load_json(runner.PROJECT_ROOT / "config/experiments/ideal_acceptance_fixed_length.json")
        config["design"].update(field1_v_per_mm=[250/3.25], center_to_grid1_mm=[2.5],
            grid2_voltage_fraction=[.975], reflectron_stage1_energy_fraction=[v/2000 for v in range(1800, 1901, 5)],
            screened_per_width=1)
        config["full_widths_mm"] = [2.8, 3.0]
        config["numerics"].update(position_order=8, residual_order=4)
        baseline = load_json(runner.PROJECT_ROOT / config["reference_config"])
        spec = workflow.NumericalSourceSpec(**baseline["source"])
        reference = workflow._working_points(baseline)["three_zone_matched"]
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            selected = workflow._select(config, baseline, reference, spec, Path(directory))
        self.assertEqual(set(selected), {2.8, 3.0})
        self.assertTrue(all(len(rows) <= 1 for rows in selected.values()))


if __name__ == "__main__":
    unittest.main()
