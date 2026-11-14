"""Small deterministic regressions for the ideal numerical-source comparison."""

from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api

from dataclasses import replace
from concurrent.futures import Future
from types import SimpleNamespace
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack

import numpy as np

from msplatform.analysis.peak_metrics import AnalysisSettings
from msplatform.components.single_reflection_oa_tof.ideal_source_comparison import (
    AxialParticleSource,
    NumericalSourceSpec,
    build_numerical_source,
    build_working_point,
    propagate_ideal_source,
)
from msplatform.components.single_reflection_oa_tof.three_zone_ideal_theory import (
    InnerSolution,
    ReflectronGeometry,
    exact_total_normalized_time,
)
from msplatform.components.orthogonal_accelerator.three_zone_ideal_theory import (
    OuterGeometry,
)
from msplatform.workflows.oa_tof_design import slope_scan, acceptance_theory
from msplatform.workflows.oa_tof_design import source_comparison as run_comparison
from msplatform.io.file_identity import file_sha256


from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.ideal_source_workflow import (
    copy_input_root, make_context, owned_workflow_environment, retained_workspace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


class IdealSourceComparisonTests(unittest.TestCase):
    """Cover pairing, fixed geometry, exact time parity, and complete loss accounting."""

    def setUp(self) -> None:
        self.spec = NumericalSourceSpec(100.0, 1.498375640839315, -2.9323518410018137, 228.80604377795845)
        self.outer = OuterGeometry(3.25, 17.0, 0.3, 250.0, 2000.0)
        self.reflectron = ReflectronGeometry(120.0, 96.1563, 600.0, 600.0)
        self.settings = AnalysisSettings(grid_points=201, standardized_grid_points=101)

    def worker_package_record(self, root: Path) -> dict:
        """Actual selected-provider roots for direct worker units, not OS receipts."""
        from msplatform.io.manifest_records import file_record
        package = root / "selected_worker_package.json"
        package.write_text(json.dumps({"package_roots": [
            str(Path(run_comparison.__file__).resolve().parents[2])]}), encoding="utf-8")
        return file_record(package)

    def point(self, slope: float | None = None, eta: float = -1.0391326394747527):
        return build_working_point(
            self.spec, self.outer, self.reflectron,
            design_velocity_slope_m_per_s_per_mm=self.spec.velocity_slope_m_per_s_per_mm if slope is None else slope,
            eta=eta, focus_drift_mm=42.742615461548496,
        )

    def sample(self, count: int = 31, width: float = 1.0, sigma: float = 3.0):
        return build_numerical_source(self.spec, particle_count=count, seed=73, full_width_mm=width, residual_sigma_m_per_s=sigma)

    def test_random_pairs_preserve_prefix_and_residual_scaling(self) -> None:
        small, large = self.sample(17), self.sample(31)
        np.testing.assert_array_equal(small.source_x_mm, large.source_x_mm[:17])
        np.testing.assert_array_equal(small.residual_m_per_s, large.residual_m_per_s[:17])
        wide = self.sample(width=2.0, sigma=6.0)
        np.testing.assert_allclose(wide.source_x_mm-self.spec.center_x_mm, 2*(large.source_x_mm-self.spec.center_x_mm), atol=1e-15)
        np.testing.assert_array_equal(wide.residual_m_per_s, 2*large.residual_m_per_s)

    def test_managed_slope_role_consumes_explicit_external_scalar_receipt_and_full_cohort(self):
        import csv
        with retained_workspace() as root:
            input_root = copy_input_root(PROJECT_ROOT, root / "explicit author inputs")
            context = make_context(root / "study")
            config = json.loads((input_root / "config/experiments/ideal_source_affine_slope_scan.json").read_text(encoding="utf-8"))
            config["sampling"] = {"particle_count": 100, "replicate_count": 1}
            # A declared SOFTWARE scalar fixture, not the historical population
            # or its scientific receipt. Original slopes/arms/controls stay exact.
            receipt_root = root / "external receipt inputs"
            receipt = receipt_root / "declared scalar.json"
            receipt.parent.mkdir()
            receipt.write_text(json.dumps({"role": "test_owned_scalar_reference",
                "source_state": {"ols_slope_vz_m_per_s_per_mm": config["historical_slope_receipt"]["slope_m_per_s_per_mm"]}}), encoding="utf-8")
            config["historical_slope_receipt"].update(path=receipt.name, sha256=file_sha256(receipt))
            config_path = root / "explicit slope.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            original_inputs = {path: path.read_bytes() for path in (config_path, receipt,
                               input_root / "config/analysis_contract.json")}
            with owned_workflow_environment():
                result = run_comparison.execute(config_path, input_root=input_root, receipt_root=receipt_root,
                    context=context, seed=73, run_id="20260827_210003__analysis__python__slope-test")
            summary = json.loads((result / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "success", summary)
            self.assertEqual([row["source_slope_m_per_s_per_mm"] for row in summary["groups"]],
                             config["source_slopes_m_per_s_per_mm"])
            self.assertTrue(all(row["completed_replicates"] == 1 for row in summary["groups"]))
            csv_paths = list((result / "results").glob("*__particles.csv"))
            self.assertEqual(len(csv_paths), 3)
            for path in csv_paths:
                with path.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual([int(row["particle_id"]) for row in rows], list(range(1, 101)))
            run_config = json.loads((result / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(run_config["input_sha256"]["historical_slope_receipt"], file_sha256(receipt))
            completion = json.loads((result / "results/execution_completion.json").read_text(encoding="utf-8"))
            operations = completion["writer_completion"]["operations"]
            self.assertEqual([row["operation_id"] for row in operations], ["scientific_analysis"])
            self.assertEqual(operations[0]["observation"]["returncode"], 0)
            self.assertGreater(operations[0]["observation"]["process_id"], 0)
            self.assertEqual(original_inputs, {path: path.read_bytes() for path in original_inputs})
            receipt.write_text("{}", encoding="utf-8")
            with patch.object(run_comparison, "_source_references") as owner_sources:
                with self.assertRaisesRegex(ValueError, "receipt hash differs"):
                    run_comparison.execute(config_path, input_root=input_root, receipt_root=receipt_root,
                        context=context, seed=73, run_id="20260827_210004__analysis__python__slope-tampered")
                owner_sources.assert_not_called()
            receipt.unlink()
            with self.assertRaisesRegex(ValueError, "receipt is unavailable"):
                run_comparison._resolve_inputs(config_path, input_root=input_root, receipt_root=receipt_root)

    def test_long_artifact_owner_uses_short_cwd_and_keeps_canonical_package_and_figure_parent(self):
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        with retained_workspace() as root:
            input_root = copy_input_root(PROJECT_ROOT, root / "explicit-author-inputs")
            workspace = root / ("long-research-workspace-" + "x" * 48) / ("scientific-artifacts-" + "y" * 48)
            context = replace(make_context(workspace), execution_root=root / "short-execution")
            config = json.loads((input_root / "config/experiments/ideal_source_comparison.json").read_text(encoding="utf-8"))
            config["sampling"] = {"particle_count": 100, "replicate_count": 1}
            config["residual_scan"]["residual_sigma_m_per_s"] = [0.0, 100.0]
            config["width_scan"]["full_widths_mm"] = [1.0, 2.2]
            config["width_scan"]["residual_sigma_m_per_s"] = [0.0]
            config_path = root / "explicit-comparison.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            run_id = "20260827_210005__analysis__python__long-artifact"
            with owned_workflow_environment():
                result = run_comparison.execute(config_path, input_root=input_root, context=context,
                    seed=9, run_id=run_id)
            self.assertEqual(result.name, run_id)
            self.assertEqual(json.loads((result / "summary.json").read_text(encoding="utf-8"))["status"], "success")
            request = json.loads((result / "inputs/scientific_request.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(request["run_directory"]), result)
            alias = Path(request["working_directory"])
            self.assertNotEqual(alias, result)
            self.assertTrue(alias.is_relative_to(context.execution_root))
            self.assertFalse(alias.exists(), "the actual owner's execution alias must be removed after closure")
            code_root = result / "inputs/analysis_code"
            self.assertGreaterEqual(len(str(code_root)), 265)
            package = json.loads(Path(request["package_receipt"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(Path(package["code_root"]), code_root)
            self.assertTrue(all(Path(path).is_relative_to(code_root) for path in package["package_roots"]))
            self.assertTrue(all(Path(row["path"]).is_relative_to(code_root) for row in package["files"]))
            for row in package["files"]:
                self.assertEqual(file_sha256(Path(row["path"])).upper(), row["sha256"])
            environment = json.loads((result / "results/scientific_environment.json").read_text(encoding="utf-8"))
            self.assertEqual(environment["working_directory"], request["working_directory"])
            self.assertTrue(all(Path(path).is_relative_to(code_root) for path in environment["package_roots"]))
            origins = [json.loads(line.split("=", 1)[1]) for line in
                (result / "logs/scientific_module.stdout.log").read_text(encoding="utf-8").splitlines()
                if line.startswith("OA_TOF_WORKER_ORIGIN=")]
            self.assertTrue(origins)
            self.assertTrue(all(Path(path).is_relative_to(code_root)
                for origin in origins for path in origin["modules"].values()))
            figures = json.loads((result / "results/ideal-source-comparison__figures.json").read_text(encoding="utf-8"))
            self.assertEqual(figures["parent_run_id"], run_id)
            completion = json.loads((result / "results/execution_completion.json").read_text(encoding="utf-8"))
            operations = completion["writer_completion"]["operations"]
            self.assertEqual([row["operation_id"] for row in operations], ["scientific_analysis"])
            self.assertEqual(operations[0]["observation"]["returncode"], 0)
            self.assertGreater(operations[0]["observation"]["process_id"], 0)
            owner_result = (context.workspace / "artifacts/projects" / result.parent.parent.name /
                "scratch/workflow_results" / run_id / "result.json")
            public = json.loads(owner_result.read_text(encoding="utf-8"))
            self.assertIs(public["writers_confirmed"], True)
            self.assertIsNone(public["resume_action"])
            self.assertEqual(public["capacity_session"]["status"], "released")
            self.assertFalse(load_capacity_protection_leases(context.workspace / "artifacts")["audit"])
        self.assertFalse(root.exists(), "a fully closed healthy owned workspace must be cleaned")

    def legacy_ideal_parent(self, root):
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        from msplatform.execution.manifest_publication import publish_run_manifest
        import hashlib
        from msplatform.workflows.oa_tof_design import source_experiment
        input_root = copy_input_root(PROJECT_ROOT, root / "author-inputs")
        context = make_context(root / "study")
        project = Path(PROJECT_ROOT)
        config = json.loads((project / "config/experiments/ideal_source_comparison.json").read_text(encoding="utf-8"))
        config["sampling"] = {"particle_count": 31, "replicate_count": 1}
        config["residual_scan"]["residual_sigma_m_per_s"] = [1.0, 3.0]
        config["width_scan"]["residual_sigma_m_per_s"] = [3.0]
        config["width_scan"]["full_widths_mm"] = [1.0]
        config["scope"] = "Pure Python legacy projection fixture; no solver or scientific qualification"
        config_path = root / "experiment.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        artifact_root = context.workspace / "artifacts/projects" / project.name
        artifact_root.mkdir(parents=True)
        initialize_capacity_ledger(artifact_root.parents[1], objects=[])
        parent = artifact_root / "runs/20261031_150100__analysis__python__legacy-ideal"
        (parent / "inputs").mkdir(parents=True)
        (parent / "results").mkdir()
        inputs = run_comparison._source_files(config_path, input_root / "config/analysis_contract.json")
        original_entrypoint = Path(__file__).with_name("test_support") / "legacy_ideal_source_producer.py"
        self.assertEqual(file_sha256(original_entrypoint).lower(),
                         "007a1946b6fe7e7839e9df5445a4a415b0471bfcea60b387e8e310879d947e17")
        old_inputs = {name: path for name, path in inputs.items()
                      if name not in {"numerical_case", "particle_physics"}}
        old_inputs["entrypoint"] = original_entrypoint
        # Exact old source witnesses are inspected only, never imported. These
        # four pre-existing wrappers are provenance, not current implementations.
        for name, relative, expected in (
            ("oatof_oaaccelerator_coupling", "projects/single_reflection_oa_tof_mass_analyzer/analysis/oatof_oaaccelerator_coupling.py", "0D5D37C11D35A98E494DD2A76A152F2FA0AEDD36D9669978154676DD2F1395A2"),
            ("reflectron_dual_stage_solver", "projects/single_reflection_oa_tof_mass_analyzer/analysis/reflectron_dual_stage_solver.py", "EE7D5D21F8E34A0601451FC79054A048452307CD304E67161978F7CD8F21591D"),
            ("accelerator_time_focus", "projects/orthogonal_accelerator/analysis/accelerator_time_focus.py", "09888DE7F7929E074EF38C1B17E5AEE5CA7342FF647794E716B31EB5E95C31C7"),
            ("accelerator_two_zone_geometry", "projects/orthogonal_accelerator/analysis/two_zone_geometry.py", "C85505DF65FB9ACD0C19085EDE5CC802A6F5729C33181AE0C4A69947B1D93D3C"),
        ):
            old_inputs[name] = REPO_ROOT / relative
            self.assertEqual(file_sha256(old_inputs[name]).upper(), expected)
        current = Path(source_experiment.__file__).read_text(encoding="utf-8")
        modern = ('if not isinstance(config["analysis_contract"], str) or not config["analysis_contract"].strip():\n'
                  '        raise ValueError("analysis_contract must declare an explicit input path")')
        historical = ('if config["analysis_contract"] != "config/analysis_contract.json":\n'
                      '        raise ValueError("use the project\'s canonical analysis contract")')
        self.assertEqual(current.count(modern), 1)
        old_experiment = current.replace(modern, historical).encode("utf-8")
        self.assertEqual(hashlib.sha256(old_experiment).hexdigest().upper(),
                         "7E29AC168E92E2B04ED6E403A6D7BA35823B8C725D8B7298A4BE7D3304EE9ECB")
        witness = root / "original-source-experiment.py"
        witness.write_bytes(old_experiment)
        old_inputs["ideal_source_experiment"] = witness
        hashes, frozen = {}, {}
        for name, source in old_inputs.items():
            destination = parent / "inputs" / (name + source.suffix)
            destination.write_bytes(source.read_bytes())
            hashes[name] = file_sha256(destination)
            frozen[name] = str(destination)
        identity = run_comparison._digest({"inputs": hashes, "seed": 73, "python": run_comparison.python_runtime_version(),
            "numpy": np.__version__, "scipy": run_comparison.scipy.__version__})
        config_document = {"schema_version": 2, "run_id": parent.name, "project": project.name, "mode": "ideal_source_comparison",
            "inputs": frozen, "input_sha256": hashes, "numerical_identity": identity, "run_instance": {"seed": 73, "resume_from": None},
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None}}
        (parent / "run_config.json").write_text(json.dumps(config_document), encoding="utf-8")
        cases = run_comparison.build_case_plan(config, 73)
        points = run_comparison._working_points(config)
        settings = run_comparison._settings(Path(frozen["analysis_contract"]))
        for case in cases:
            document = run_comparison._run_case(case, config, points, settings, parent / "results")
            document["identity"] = identity
            document["record_sha256"] = run_comparison._digest(document)
            (parent / "results" / (case["case_id"] + ".json")).write_text(json.dumps(document), encoding="utf-8")
        (parent / "summary.json").write_text(json.dumps({"role": "ideal_source_comparison_summary", "status": "success",
            "completed_cases": len(cases), "planned_cases": len(cases)}), encoding="utf-8")
        outputs = [path for path in parent.rglob("*") if path.is_file() and path.name != "run_config.json"]
        publish_run_manifest(parent / "run_config.json", "success", output_paths=outputs, retention_api=_manifest_retention_api)
        return artifact_root, parent, config_path, cases, input_root, context

    def test_legacy_numeric_csv_is_referenced_through_public_source_owner_without_resampling(self):
        from common.contracts.capacity_protection import load_capacity_protection_leases
        with retained_workspace() as root:
            artifact_root, parent, config_path, cases, input_root, context = self.legacy_ideal_parent(root)
            before = {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            projection = run_comparison._legacy_ideal_projection
            checked = []

            def protected_projection(*args):
                from msplatform.execution.manifest_publication import publish_run_manifest
                active = load_capacity_protection_leases(artifact_root.parents[1])
                self.assertIn(parent.resolve(), active["protected_paths"])
                stage = json.loads(context.stage_policy_path.read_text(encoding="utf-8"))
                own_commitment = stage["stages"]["ideal_source_comparison"]["limits"]["transient_run_directory_bytes"]
                # Same-root source protection is merged into the actual owning
                # lease. It adds no second capacity reservation.
                self.assertEqual(active["committed_new_bytes"], own_commitment)
                self.assertEqual(len(active["audit"]), 1)
                lease = active["audit"][0]
                self.assertEqual(lease["committed_new_bytes"], own_commitment)
                self.assertIn(str(parent.resolve()), lease["protected_paths"])
                self.assertTrue(any(Path(path).parent == artifact_root / "runs"
                                    and Path(path) != parent for path in lease["protected_paths"]))
                if not checked:
                    with self.assertRaisesRegex(ValueError, "already published terminal"):
                        publish_run_manifest(parent / "run_config.json", "failed", retention_api=_manifest_retention_api)
                    checked.append(True)
                return projection(*args)

            with patch.object(run_comparison, "_legacy_ideal_projection", side_effect=protected_projection), owned_workflow_environment():
                child = run_comparison.execute(config_path, input_root=input_root, context=context, seed=73,
                    run_id="20261031_150200__analysis__python__legacy-projected", resume_from=parent)
                descendant = run_comparison.execute(config_path, input_root=input_root, context=context, seed=73,
                    run_id="20261031_150300__analysis__python__legacy-descendant", resume_from=child)
                self.assertEqual(json.loads((descendant / "summary.json").read_text(encoding="utf-8"))["reused_cases"], len(cases))
            self.assertTrue(checked)
            summary = json.loads((child / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "success", summary)
            self.assertEqual(summary["reused_cases"], len(cases))
            child_config = json.loads((child / "run_config.json").read_text(encoding="utf-8"))
            execution_request = json.loads((child / "inputs/execution_request.json").read_text(encoding="utf-8"))
            self.assertTrue(execution_request["capacity"]["source_references"])
            self.assertEqual(child_config["paths"]["artifact_root"], str(artifact_root.parents[1]))
            self.assertEqual(child_config["paths"]["execution_root"], str(context.execution_root))
            proof = json.loads(Path(child_config["inputs"]["legacy_numerical_projection"]).read_text(encoding="utf-8"))
            self.assertEqual(proof["execution_context"], child_config["paths"])
            self.assertEqual(child_config["paths"]["host_resource_state_path"], str(context.host_state_path.resolve()))
            for case in cases:
                document = json.loads((child / "results" / (case["case_id"] + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(Path(document["particles"]["path"]).parent, parent / "results")
                self.assertFalse((child / "results" / Path(document["particles"]["path"]).name).exists())
                self.assertIn(case["case_id"], child_config["legacy_external_case_inputs"])
                self.assertEqual(document["derived_from"]["source_owner"], str(parent))
            self.assertEqual(before, {path:path.read_bytes() for path in parent.rglob("*") if path.is_file()})
            protection = load_capacity_protection_leases(artifact_root.parents[1])
            self.assertFalse(protection["protected_paths"])

    def test_legacy_reference_rejects_unmanaged_target_before_capacity_or_source_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent"
            parent.mkdir()
            (parent / "run_config.json").write_text('{"inputs":{},"input_sha256":{}}', encoding="utf-8")
            (parent / "run_manifest.json").write_text('{}', encoding="utf-8")
            before = {path: path.read_bytes() for path in parent.iterdir()}
            context = make_context(root / "arbitrary-target")
            # A pre-existing uncalibrated artifact tree is not silently adopted.
            (context.workspace / "artifacts").mkdir()
            with patch.object(run_comparison, "_resolve_inputs") as command, \
                    patch.object(run_comparison, "_source_references") as source_reads:
                with self.assertRaisesRegex(ValueError, "explicit calibrated capacity ledger"):
                    run_comparison.execute(root / "unread-experiment.json", input_root=root,
                        context=context, seed=73, resume_from=parent,
                        run_id="20261031_152000__analysis__python__legacy-unmanaged")
                command.assert_not_called()
                source_reads.assert_not_called()
            self.assertEqual(before, {path: path.read_bytes() for path in parent.iterdir()})
            self.assertFalse((context.workspace / "artifacts/projects").exists())

    def test_legacy_association_requires_both_exact_source_identities(self):
        for name, original, current in (
            ("oatof_oaaccelerator_coupling", "0D5D37C11D35A98E494DD2A76A152F2FA0AEDD36D9669978154676DD2F1395A2", "C63A4E996780C519A7F05B20F12B927EEAB8CE6B4832F49C5FF8E07B274C5178"),
            ("reflectron_dual_stage_solver", "EE7D5D21F8E34A0601451FC79054A048452307CD304E67161978F7CD8F21591D", "C73B0E452A2688FB05F4141ED6455F36C61824EE6C4EF125359DD1A419C620D2"),
            ("accelerator_time_focus", "09888DE7F7929E074EF38C1B17E5AEE5CA7342FF647794E716B31EB5E95C31C7", "28FA9E54FF3E62292B92C07AC1DC736E5D8BC923D8024988406890C6AEF96F8D"),
            ("ideal_source_experiment", "7E29AC168E92E2B04ED6E403A6D7BA35823B8C725D8B7298A4BE7D3304EE9ECB", "124774594D4A242B0A9307CF837784E3E5EA4371238338FD0CD0F651015F4CA8"),
        ):
            with self.subTest(source=name):
                self.assertTrue(run_comparison._legacy_scientific_binding(name, original, current))
                self.assertFalse(run_comparison._legacy_scientific_binding(name, "F" * 64, current))
                self.assertFalse(run_comparison._legacy_scientific_binding(name, original, "F" * 64))
                self.assertFalse(run_comparison._legacy_scientific_binding("another_role", original, current))

    def test_frozen_package_matches_the_already_bound_scientific_source(self):
        from msplatform.execution.inputs import freeze_file
        from msplatform.execution.resources import resource_path
        for mutate in (False, True, "missing_executor"):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                provider = root / "provider/msplatform"
                provider.mkdir(parents=True)
                (provider / "__init__.py").write_text("", encoding="utf-8")
                for relative in ("analysis", "contracts", "execution", "io", "components/orthogonal_accelerator",
                                 "components/single_reflection_oa_tof", "components/rf_multipole", "workflows/oa_tof_design"):
                    package = provider / relative
                    package.mkdir(parents=True, exist_ok=True)
                    (package / "__init__.py").write_text("", encoding="utf-8")
                for relative in ("components/catalog.py", "components/model.py"):
                    (provider / relative).write_text("", encoding="utf-8")
                source = provider / "components/single_reflection_oa_tof/selected_science.py"
                source.write_text("VALUE = 1\n", encoding="utf-8")
                executor = provider / "execution/resources/frozen_python_package.ps1"
                executor.parent.mkdir(parents=True)
                executor.write_bytes(resource_path("frozen_python_package.ps1").read_bytes())
                run = root / "run"
                for name in ("inputs", "results", "logs"):
                    (run / name).mkdir(parents=True)
                frozen = {"selected_science": freeze_file(source, run / "inputs/science.py")}
                if mutate is True:
                    source.write_text("VALUE = 2\n", encoding="utf-8")
                elif mutate == "missing_executor":
                    executor.unlink()
                records = {}
                run_config = run / "run_config.json"
                run_config.write_text(json.dumps({"numerical_input_sha256":
                    {name: record["sha256"] for name, record in frozen.items()}}), encoding="utf-8")

                def declare(path, role):
                    self.assertEqual(role, "required_evidence")
                    return Path(path)

                # Preparation-only sink; neither a writer nor an OS receipt is
                # supplied. The real public-owner parents execute full packages.
                session = SimpleNamespace(input_dir=run / "inputs", result_dir=run / "results",
                    log_dir=run / "logs", run_dir=run, artifact_run_dir=run, run_config=run_config, capacity_session={},
                    context=SimpleNamespace(python_executable=Path("selected-python")),
                    declare_file=declare, add_input=lambda name, record: records.update({name: record}),
                    add_inputs=records.update)
                with patch.object(run_comparison, "_source_package_root", return_value=provider), \
                        patch.object(run_comparison, "_invoke_worker", side_effect=AssertionError("preparation cannot launch")) as invoke:
                    if mutate == "missing_executor":
                        with self.assertRaisesRegex(FileNotFoundError, "Required frozen Python executor missing"):
                            run_comparison._freeze_worker_package(session, frozen, seed=73,
                                identity="explicit-preparation-fixture", resume_from=None, max_workers=None)
                    elif mutate:
                        with self.assertRaisesRegex(ValueError, "scientific role differs from selected package member: selected_science"):
                            run_comparison._freeze_worker_package(session, frozen, seed=73,
                                identity="explicit-preparation-fixture", resume_from=None, max_workers=None)
                        self.assertFalse((run / "inputs/scientific_request.json").exists())
                    else:
                        request, _ = run_comparison._freeze_worker_package(session, frozen, seed=73,
                            identity="explicit-preparation-fixture", resume_from=None, max_workers=None)
                        self.assertTrue(request.is_file())
                        self.assertEqual((run / "inputs/analysis_code/msplatform/components/single_reflection_oa_tof/selected_science.py").read_bytes(),
                                         Path(frozen["selected_science"]["path"]).read_bytes())
                    invoke.assert_not_called()

    def test_selected_tof_package_isolated_executor_rejects_missing_module_and_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            for name in ("inputs", "results", "logs"):
                (run / name).mkdir(parents=True)
            run_config = run / "run_config.json"
            run_config.write_text(json.dumps({"numerical_input_sha256": {}}), encoding="utf-8")
            records = {}
            session = SimpleNamespace(input_dir=run / "inputs", result_dir=run / "results",
                log_dir=run / "logs", run_dir=run, artifact_run_dir=run, run_config=run_config, capacity_session={},
                context=SimpleNamespace(python_executable=Path(sys.executable)),
                declare_file=lambda path, role: Path(path),
                add_input=lambda name, record: records.update({name: record}), add_inputs=records.update)
            request, guards = run_comparison._freeze_worker_package(session, {}, seed=73,
                identity="selected-closure-test", resume_from=None, max_workers=None)
            package = json.loads(Path(records["analysis_package"]["path"]).read_text(encoding="utf-8"))
            selected = {entry["relative_path"]: entry for entry in package["files"]}
            module = "msplatform/workflows/oa_tof_design/numerical_case.py"
            resource = "msplatform/execution/resources/frozen_python_package.ps1"
            self.assertIn(module, selected)
            self.assertIn(resource, selected)
            self.assertIn("msplatform/components/rf_multipole/grounded_shield.py", selected)
            self.assertNotIn("msplatform/backends/simion/ip_geometry.py", selected)
            executor = Path(selected[resource]["path"])
            driver = root / "probe.ps1"
            driver.write_text("""param($Executor,$Package,$Python,$Forbidden)
$ErrorActionPreference = 'Stop'
. $Executor
$p = Get-Content -LiteralPath $Package -Raw -Encoding UTF8 | ConvertFrom-Json
$r = Invoke-IsolatedFrozenPythonModule -Python $Python -Package $p `
  -Module 'msplatform.workflows.oa_tof_design.source_comparison' -Arguments @('--help') `
  -RequiredModuleNames @('msplatform.workflows.oa_tof_design.numerical_case') `
  -ForbiddenRoots @($Forbidden) -ProbeOnly
$r | ConvertTo-Json -Depth 20 -Compress
""", encoding="utf-8")
            powershell = shutil.which("pwsh")
            self.assertIsNotNone(powershell, "the actual frozen executor requires pwsh")
            package_path = Path(records["analysis_package"]["path"])
            provider = run_comparison._source_package_root()
            command = [powershell, "-NoProfile", "-NonInteractive", "-File", str(driver),
                       str(executor), str(package_path), sys.executable, str(provider.parent)]
            positive = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(positive.returncode, 0, positive.stderr)
            observation = json.loads(positive.stdout)
            origins = {row["name"]: Path(row["origin"]).resolve() for row in observation["frozen_modules"]}
            self.assertEqual(origins["msplatform.workflows.oa_tof_design.numerical_case"],
                             (run / "inputs/analysis_code" / module).resolve())
            session.run_process = Mock()
            original_executor = executor.read_bytes()
            try:
                executor.unlink()
                with self.assertRaisesRegex(AssertionError, "manifest frozen TOF input .* is missing"):
                    run_comparison._invoke_worker(session, request, guards, {})
                session.run_process.assert_not_called()
                executor.write_bytes(bytes([original_executor[0] ^ 1]) + original_executor[1:])
                self.assertEqual(executor.stat().st_size, len(original_executor))
                with self.assertRaisesRegex(AssertionError, "manifest frozen TOF input .* SHA-256 changed"):
                    run_comparison._invoke_worker(session, request, guards, {})
                session.run_process.assert_not_called()
            finally:
                executor.write_bytes(original_executor)
            # Preserve a complete author provider while removing the selected copy.
            # Excluding the missing entry from the test receipt forces the actual
            # isolated module-origin probe to refuse an ambient installation too.
            target = Path(selected[module]["path"])
            target.unlink()
            missing = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("Frozen Python dependency is missing", missing.stderr)
            package["files"] = [row for row in package["files"] if row["relative_path"] != module]
            package_path.write_text(json.dumps(package), encoding="utf-8")
            no_fallback = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(no_fallback.returncode, 0)
            self.assertIn("required frozen module has no file origin", no_fallback.stderr)
            self.assertNotIn('"modules":', no_fallback.stdout)
            isolated = ("import importlib,pathlib,sys; "
                "sys.path.insert(0,sys.argv[1]); "
                "sys.path=[p for p in sys.path if not p or not pathlib.Path(p).resolve().is_relative_to(pathlib.Path(sys.argv[2]).resolve())]; "
                "sys.meta_path=[f for f in sys.meta_path if not getattr(f,'__module__','').startswith('__editable__')]; "
                "importlib.import_module('msplatform.workflows.oa_tof_design.numerical_case')")
            cold = subprocess.run([sys.executable, "-I", "-B", "-c", isolated,
                str(run / "inputs/analysis_code"), str(provider.parent)], cwd=root, capture_output=True,
                text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(cold.returncode, 0)
            self.assertIn("ModuleNotFoundError: No module named 'msplatform.workflows.oa_tof_design.numerical_case'", cold.stderr)
            self.assertTrue(provider.is_dir())
            self.assertTrue(request.is_file())

    def test_worker_rejects_environment_or_numerical_role_mismatch_before_science(self):
        from msplatform.io.manifest_records import file_record
        for scenario in ("environment", "role_record"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "bound.json"
                source.write_text("{}", encoding="utf-8")
                frozen = {"experiment": file_record(source)}
                numerical = {name: record["sha256"] for name, record in frozen.items()}
                identity = run_comparison._numerical_identity(numerical, seed=73)
                if scenario == "role_record":
                    numerical["experiment"] = "F" * 64
                request = root / "request.json"
                request.write_text(json.dumps(dict(schema_version=1, role="oa_tof_design_scientific_request",
                    scientific_inputs=frozen, package_receipt=self.worker_package_record(root),
                    numerical_input_sha256=numerical,
                    numerical_identity=identity, seed=73)), encoding="utf-8")
                # Direct rejection at the actual worker boundary; no process or
                # arbitrary host-environment support is claimed by this control.
                with patch.object(run_comparison, "python_runtime_version",
                                  return_value="explicit-other-worker-python" if scenario == "environment"
                                  else run_comparison.python_runtime_version()), \
                        patch.object(run_comparison, "_settings") as settings, \
                        patch.object(run_comparison, "_renew_selected_capacity") as renew, \
                        patch.object(run_comparison, "_run_comparison_cases") as science:
                    reason = "worker Python/NumPy/SciPy environment differs" if scenario == "environment" else "numerical input identity differs"
                    with self.assertRaisesRegex(ValueError, reason):
                        run_comparison._scientific_worker(request)
                    settings.assert_not_called()
                    renew.assert_not_called()
                    science.assert_not_called()

    def test_explicit_worker_context_restores_prior_binding_and_ignores_ambient_request(self):
        from msplatform.io.manifest_records import file_record
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / "experiment.json"
                config.write_text(json.dumps({"role": "ideal_source_comparison"}), encoding="utf-8")
                analysis = root / "analysis.json"
                analysis.write_text(json.dumps({"kde": {"grid_points": 201,
                    "bandwidth_multiplier": 1.06, "significant_mode_threshold_fraction": 0.1}}), encoding="utf-8")
                frozen = {"experiment": file_record(config), "analysis_contract": file_record(analysis)}
                numerical = {name: record["sha256"] for name, record in frozen.items()}
                completion = root / "completion.json"
                payload = dict(schema_version=1, role="oa_tof_design_scientific_request",
                    scientific_inputs=frozen, package_receipt=self.worker_package_record(root),
                    numerical_input_sha256=numerical,
                    numerical_identity=run_comparison._numerical_identity(numerical, seed=73),
                    seed=73, run_directory=str(root), capacity_session={}, resume_from=None,
                    max_workers=None, outputs={"completion": str(completion)})
                request = root / "explicit_request.json"
                request.write_text(json.dumps(payload), encoding="utf-8")
                ambient = root / "ambient_request.json"
                ambient.write_text('{"role":"must_not_be_selected"}', encoding="utf-8")
                ambient_before = ambient.read_bytes()
                prior = {"prior_explicit_context": "preserve"}
                failure = RuntimeError("original direct scientific failure")

                def cases(config, **kwargs):
                    self.assertEqual(run_comparison._BOUND_SCIENTIFIC_REQUEST, payload)
                    self.assertTrue(run_comparison._WORKER_ORIGIN_REPORTED)
                    self.assertEqual(kwargs["run_dir"], root)
                    if fail:
                        raise failure
                    return {"summary": {"status": "success"}}

                # Direct scientific dispatch: selected package metadata is real;
                # only scientific work/renewal is isolated, not OS completion.
                with patch.dict(os.environ, {"OA_TOF_SCIENTIFIC_REQUEST": str(ambient)}), \
                        patch.object(run_comparison, "_BOUND_SCIENTIFIC_REQUEST", prior), \
                        patch.object(run_comparison, "_WORKER_ORIGIN_REPORTED", True), \
                        patch.object(run_comparison, "_renew_selected_capacity"), \
                        patch.object(run_comparison, "_run_comparison_cases", side_effect=cases) as science:
                    if fail:
                        with self.assertRaises(RuntimeError) as caught:
                            run_comparison._scientific_worker(request)
                        self.assertIs(caught.exception, failure)
                        self.assertFalse(completion.exists())
                    else:
                        run_comparison._scientific_worker(request)
                        self.assertEqual(json.loads(completion.read_text())["result"]["summary"]["status"], "success")
                    science.assert_called_once()
                    self.assertIs(run_comparison._BOUND_SCIENTIFIC_REQUEST, prior)
                    self.assertTrue(run_comparison._WORKER_ORIGIN_REPORTED)
                self.assertEqual(ambient.read_bytes(), ambient_before)

    def test_legacy_ideal_projection_rejects_unproven_inputs_environment_settings_and_owner(self):
        from msplatform.execution.manifest_publication import build_run_manifest
        from msplatform.execution.retention import file_record
        from common.contracts.capacity_protection import load_capacity_protection_leases
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_root, parent, config_path, cases, input_root, context = self.legacy_ideal_parent(root)
            originals = {path:path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            _, protection = run_comparison._source_references(parent)
            # Direct rejected-reader cases do not claim source-lease acquisition;
            # the positive parent above observes the actual owner's protection.
            protection["execution_context"] = {}
            identities = {name:file_sha256(path) for name,path in run_comparison._source_files(config_path, input_root / "config/analysis_contract.json").items()}
            for scenario in ("missing_source", "environment", "changed_generator", "changed_execution", "unbound_input"):
                with self.subTest(scenario=scenario):
                    original_config = json.loads((parent / "run_config.json").read_text(encoding="utf-8"))
                    if scenario == "missing_source":
                        Path(original_config["inputs"]["entrypoint"]).unlink()
                    elif scenario == "environment":
                        original_config["numerical_identity"] = "unproven historical environment"
                        (parent / "run_config.json").write_text(json.dumps(original_config), encoding="utf-8")
                    elif scenario in {"changed_generator", "changed_execution"}:
                        path = Path(original_config["inputs"]["entrypoint"])
                        content = path.read_text(encoding="utf-8")
                        old, changed = (
                            ('full_width_mm=case["full_width_mm"]', 'full_width_mm=0.5')
                            if scenario == "changed_generator" else
                            ('plan = build_case_plan(config, seed)', 'plan = build_case_plan(config, seed + 1)')
                        )
                        self.assertEqual(content.count(old), 1)
                        path.write_text(content.replace(old, changed), encoding="utf-8")
                        original_config["input_sha256"]["entrypoint"] = file_sha256(path)
                        original_config["numerical_identity"] = run_comparison._digest({"inputs":original_config["input_sha256"], "seed":73,
                            "python":run_comparison.python_runtime_version(), "numpy":np.__version__, "scipy":run_comparison.scipy.__version__})
                        (parent / "run_config.json").write_text(json.dumps(original_config), encoding="utf-8")
                    paths = [path for path in parent.rglob("*") if path.is_file() and path.name not in {"run_config.json", "run_manifest.json"}]
                    if scenario == "missing_source":
                        # Keep the original binding to expose the missing frozen producer.
                        manifest = json.loads(originals[parent / "run_manifest.json"])
                    else:
                        manifest = build_run_manifest(parent / "run_config.json", "success", output_paths=paths, retention_api=_manifest_retention_api)
                    if scenario == "unbound_input":
                        missing = Path(original_config["inputs"]["analysis_contract"])
                        manifest["inputs"] = {name:record for name,record in manifest["inputs"].items() if Path(record["path"]) != missing}
                        manifest["outputs"] = [record for record in manifest["outputs"] if Path(record["path"]) != missing]
                    (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                    protection["source_reference"]["manifest_record"] = file_record(parent / "run_manifest.json")
                    before = {path:path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                    with self.assertRaises((ValueError, AssertionError, OSError)):
                        run_comparison._legacy_ideal_projection(parent, identities, 73, "ideal_source_comparison", protection)
                    self.assertEqual(before, {path:path.read_bytes() for path in parent.rglob("*") if path.is_file()})
                    for path,content in originals.items():
                        path.write_bytes(content)
            document = json.loads((parent / "results" / (cases[0]["case_id"] + ".json")).read_text(encoding="utf-8"))
            bad = AnalysisSettings(grid_points=203, bandwidth_multiplier=1.25)
            with self.assertRaisesRegex(ValueError, "frozen analysis contract"):
                run_comparison._legacy_csv_analysis(parent, document, json.loads(config_path.read_text(encoding="utf-8")), bad)
            for scenario in ("unfinished_journal", "active_writer", "missing_owner"):
                with self.subTest(scenario=scenario):
                    if scenario == "unfinished_journal":
                        (parent / ".run_terminal_publication.json").write_text("{}", encoding="utf-8")
                    elif scenario == "active_writer":
                        manifest = json.loads(originals[parent / "run_manifest.json"])
                        manifest.update(status="interrupted", lifecycle_state="provisional")
                        (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                    else:
                        manifest = json.loads(originals[parent / "run_manifest.json"])
                        config = json.loads(originals[parent / "run_config.json"])
                        config["project"] = "another-owner"
                        (parent / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
                        manifest["run_config"] = file_record(parent / "run_config.json")
                        (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                    protection["source_reference"]["manifest_record"] = file_record(parent / "run_manifest.json")
                    with self.assertRaises((RuntimeError, ValueError, AssertionError)):
                        run_comparison._legacy_ideal_projection(parent, identities, 73,
                            "ideal_source_comparison", protection)
                    (parent / ".run_terminal_publication.json").unlink(missing_ok=True)
                    for path,content in originals.items():
                        path.write_bytes(content)
            self.assertFalse(load_capacity_protection_leases(artifact_root.parents[1])["protected_paths"])

    def test_resume_retains_numeric_cases_after_plot_or_report_change_but_rejects_numeric_change(self):
        from msplatform.execution.inputs import freeze_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root/(name+'.py') for name in
                     ('entrypoint','ideal_source_comparison_plot','numerical_case')}
            for name, path in paths.items():
                path.write_text(name+' initial\n', encoding='utf-8')
            config = root/'experiment.json'
            config.write_text(json.dumps(dict(scope='inert dependency fixture')), encoding='utf-8')
            inputs = dict(experiment=config, **paths)
            identities = {name: file_sha256(path) for name, path in inputs.items()}
            identity = run_comparison._numerical_identity(identities, seed=7)
            parent = root/'parent'
            (parent/'results').mkdir(parents=True)
            (parent/'inputs').mkdir()
            frozen = {}
            for name, path in inputs.items():
                record = freeze_file(path, parent/'inputs'/(name+path.suffix))
                frozen[name] = record['path']
            (parent/'run_config.json').write_text(json.dumps(dict(inputs=frozen,
                input_sha256=identities, numerical_identity=identity)), encoding='utf-8')
            case = dict(case_id='fixture')
            particles = parent/'results/fixture.csv'
            particles.write_text('particle_id,tof_us\n1,2\n', encoding='utf-8')
            document = dict(identity=identity, case=case,
                particles=dict(path=particles.name, bytes=particles.stat().st_size, sha256=file_sha256(particles)))
            document['record_sha256'] = run_comparison._digest(document)
            (parent/'results/fixture.json').write_text(json.dumps(document), encoding='utf-8')
            before = {path: path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            paths['entrypoint'].write_text('changed reporting only\n', encoding='utf-8')
            paths['ideal_source_comparison_plot'].write_text('changed display only\n', encoding='utf-8')
            changed = {name: file_sha256(path) for name, path in inputs.items()}
            child_identity = run_comparison._numerical_identity(changed, seed=7)
            child = root/'child'
            (child/'results').mkdir(parents=True)
            self.assertEqual(child_identity, identity)
            self.assertEqual(run_comparison._reuse_case(parent, case, child_identity, child/'results',
                frozen_inputs={}, settings=self.settings), document)
            self.assertEqual((child/'results/fixture.csv').read_bytes(), particles.read_bytes())
            self.assertIn('entrypoint', changed)
            self.assertIn('ideal_source_comparison_plot', changed)
            scientific = {name: value for name, value in changed.items()
                          if name not in {'entrypoint', 'ideal_source_comparison_plot'}}
            self.assertNotIn('entrypoint', scientific)
            self.assertNotIn('ideal_source_comparison_plot', scientific)
            paths['numerical_case'].write_text('changed propagation formula\n', encoding='utf-8')
            different = run_comparison._numerical_identity(
                {name: file_sha256(path) for name, path in inputs.items()}, seed=7)
            self.assertNotEqual(different, child_identity)
            with self.assertRaisesRegex(ValueError, 'checkpoint identity/content mismatch'):
                run_comparison._reuse_case(parent, case, different, child/'results',
                    frozen_inputs={}, settings=self.settings)
            self.assertEqual({path: path.read_bytes() for path in before}, before)


    def test_legacy_comparison_without_frozen_numerical_case_fails_before_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / 'legacy'
            legacy.mkdir()
            (legacy / 'run_config.json').write_text(json.dumps(dict(
                schema_version=2, input_sha256={}, inputs={}, numerical_identity='old-full-runner-identity')),
                encoding='utf-8')
            before = (legacy / 'run_config.json').read_bytes()
            # The migrated public source reader now rejects the missing bound
            # terminal manifest even before scientific-projection/owner creation.
            with self.assertRaisesRegex(ValueError, 'resume source lacks its bound terminal manifest'):
                run_comparison._source_references(legacy)
            self.assertFalse((root / 'runs').exists())
            self.assertEqual((legacy / 'run_config.json').read_bytes(), before)


    def test_execute_uses_frozen_settings_after_active_drift_and_rejects_invalid_frozen_settings(self):
        from msplatform.execution.inputs import freeze_file
        from msplatform.io.manifest_records import file_record
        for scenario in ('active_drift', 'invalid_frozen', 'frozen_tamper'):
            invalid_frozen = scenario == 'invalid_frozen'
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run = root / 'run'
                for name in ('inputs', 'results', 'logs'):
                    (run / name).mkdir(parents=True, exist_ok=True)
                config = root / 'experiment.json'
                config.write_text(json.dumps(dict(role='ideal_source_comparison')), encoding='utf-8')
                active = root / 'active_analysis_contract.json'
                good = dict(kde=dict(grid_points=4001, bandwidth_multiplier=1.06,
                                     significant_mode_threshold_fraction=0.10))
                bad = dict(kde=dict(grid_points=1, bandwidth_multiplier=1.06,
                                    significant_mode_threshold_fraction=0.10))
                active.write_text(json.dumps(bad if invalid_frozen else good), encoding='utf-8')
                frozen = {'experiment': freeze_file(config, run/'inputs/experiment.json'),
                          'analysis_contract': freeze_file(active, run/'inputs/analysis_contract.json')}
                active.write_text(json.dumps(good if invalid_frozen else bad), encoding='utf-8')
                if scenario == 'frozen_tamper':
                    Path(frozen['analysis_contract']['path']).write_text(json.dumps(bad), encoding='utf-8')
                numerical = {name: record['sha256'] for name, record in frozen.items()}
                request = root/'request.json'
                request.write_text(json.dumps(dict(schema_version=1, role='oa_tof_design_scientific_request',
                    scientific_inputs=frozen, package_receipt=self.worker_package_record(root),
                    seed=7, run_directory=str(run), numerical_input_sha256=numerical,
                    numerical_identity=run_comparison._numerical_identity(numerical, seed=7),
                    capacity_session={}, resume_from=None, max_workers=None,
                    outputs=dict(completion=str(run/'results/completion.json')))), encoding='utf-8')
                # Direct scientific-dispatch unit boundary: no owner/process or
                # OS completion is claimed by the capacity-renewal isolation.
                with patch.object(run_comparison, '_settings', wraps=run_comparison._settings) as settings, \
                     patch.object(run_comparison, '_renew_selected_capacity'), \
                     patch.object(run_comparison, '_run_comparison_cases', return_value=dict(summary=dict(status='success'))) as cases, \
                     patch.object(run_comparison, '_run_case', side_effect=AssertionError('propagation must not start')) as propagation:
                    if scenario == 'active_drift':
                        run_comparison._scientific_worker(request)
                        self.assertEqual(json.loads((run/'results/completion.json').read_text())['result']['summary']['status'], 'success')
                    elif scenario == 'frozen_tamper':
                        with self.assertRaises(AssertionError):
                            run_comparison._scientific_worker(request)
                    else:
                        with self.assertRaisesRegex(ValueError, 'grid_points must be an integer of at least three'):
                            run_comparison._scientific_worker(request)
                    if scenario == 'frozen_tamper':
                        settings.assert_not_called()
                    else:
                        settings.assert_called_once_with(Path(frozen['analysis_contract']['path']))
                        self.assertNotEqual(settings.call_args.args[0], active)
                    if scenario == 'active_drift':
                        cases.assert_called_once()
                        self.assertEqual(cases.call_args.kwargs['settings'].grid_points, 4001)
                    else:
                        cases.assert_not_called()
                    propagation.assert_not_called()
                self.assertEqual(file_record(config)['sha256'], frozen['experiment']['sha256'])


    def test_other_comparison_consumers_transport_the_same_explicit_settings(self):
        source = self.sample(count=7)
        point = self.point()
        result = SimpleNamespace(classification=np.array(['hit'] * 7), tof_us=np.arange(7) / 10 + 1,
            summary=dict(status='COMPUTED', peak_metrics=dict(mass_resolution=1000.0, direct_fwhm_tof_ns=1.0)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slope_config = dict(sampling=dict(particle_count=7), full_width_mm=1.0, residual_sigma_m_per_s=1.0)
            with patch.object(slope_scan, '_source', return_value=self.spec), \
                 patch.object(slope_scan, 'build_numerical_source', return_value=source), \
                 patch.object(slope_scan, '_arms', return_value=dict(zero_slope_design=point, matching_slope_design=point)), \
                 patch.object(slope_scan, 'propagate_ideal_source', return_value=result) as propagated:
                slope_scan._record_case(slope_config, 1.0, 73, root, settings=self.settings)
            self.assertEqual(propagated.call_count, 2)
            self.assertTrue(all(call.kwargs['settings'] is self.settings for call in propagated.call_args_list))
            launched = []

            class ImmediateExecutor:
                def __init__(self, max_workers, *, initializer, initargs):
                    launched.append(max_workers)
                    initializer(*initargs)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def submit(self, function, *args):
                    future = Future()
                    future.set_result(function(*args))
                    return future

            config = dict(full_widths_mm=[1.0], residual_sigma_m_per_s=1.0, minimum_resolution=1000.0,
                          sampling=dict(particle_count=7, replicate_count=1),
                          numerics=dict(population_orders=[], population_resolution_relative_tolerance=0.1),
                          design=dict(selected_per_width=1, selection='transport fixture'))
            with patch.object(acceptance_theory, 'ProcessPoolExecutor', ImmediateExecutor), \
                 patch.object(acceptance_theory, 'source_at_point', return_value=self.spec), \
                 patch.object(acceptance_theory, 'build_numerical_source', return_value=source), \
                 patch.object(acceptance_theory, 'accepted', return_value=False), \
                 patch.object(acceptance_theory, 'propagate_ideal_source', return_value=result) as propagated:
                reports, _ = acceptance_theory._confirm_widths_parallel(
                    config, self.spec, point, {1.0: []}, 73, root, 1, settings=self.settings)
            self.assertEqual(launched, [1])
            self.assertEqual(len(reports), 1)
            self.assertFalse(reports[0]['theoretical_population_pass'])
            propagated.assert_called_once()
            self.assertIs(propagated.call_args.kwargs['settings'], self.settings)

    def test_supported_role_entries_read_frozen_settings_once_before_cases_or_workers(self):
        from msplatform.io.manifest_records import file_record
        for mode in ('slope', 'acceptance'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                run = root/'run'
                for name in ('inputs','results','logs'):
                    (run/name).mkdir(parents=True, exist_ok=True)
                contract = run/'inputs/analysis_contract.json'
                contract.write_text(json.dumps(dict(kde=dict(grid_points=self.settings.grid_points,
                    bandwidth_multiplier=self.settings.bandwidth_multiplier,
                    significant_mode_threshold_fraction=self.settings.mode_threshold_fraction))), encoding='utf-8')
                config = run/'inputs/experiment.json'
                config.write_text(json.dumps(dict(role='ideal_source_slope_scan' if mode=='slope' else 'ideal_acceptance_theory')), encoding='utf-8')
                frozen = dict(experiment=file_record(config), analysis_contract=file_record(contract))
                module = slope_scan if mode=='slope' else acceptance_theory
                if mode=='acceptance':
                    baseline = run/'inputs/reference.json'
                    baseline.write_text(json.dumps(dict(source=vars(self.spec))), encoding='utf-8')
                    frozen['reference_config'] = file_record(baseline)
                numerical = {name: record['sha256'] for name, record in frozen.items()}
                request = root/'request.json'
                request.write_text(json.dumps(dict(schema_version=1, role='oa_tof_design_scientific_request',
                    scientific_inputs=frozen, package_receipt=self.worker_package_record(root),
                    seed=73, run_directory=str(run), numerical_input_sha256=numerical,
                    numerical_identity=run_comparison._numerical_identity(numerical, seed=73),
                    capacity_session={}, resume_from=None, max_workers=1,
                    outputs=dict(completion=str(run/'results/completion.json')))), encoding='utf-8')
                # These two original transport-purpose branches exercise actual
                # scientific dispatch, not a fabricated managed owner or receipt.
                stack.enter_context(patch.object(run_comparison, '_renew_selected_capacity'))
                settings = stack.enter_context(patch.object(run_comparison, '_settings', wraps=run_comparison._settings))
                consumer = stack.enter_context(patch.object(module,
                    '_run_slope_cases' if mode=='slope' else '_run_theory_cases',
                    return_value=dict(summary=dict(status='success'))))
                run_comparison._scientific_worker(request)
                settings.assert_called_once_with(contract)
                consumer.assert_called_once()
                self.assertIsInstance(consumer.call_args.kwargs['settings'], AnalysisSettings)
                self.assertEqual(consumer.call_args.kwargs['settings'].grid_points, self.settings.grid_points)
                self.assertEqual(json.loads((run/'results/completion.json').read_text())['result']['summary']['status'], 'success')


    def test_quadratic_mean_and_no_detector_fit(self) -> None:
        spec = replace(self.spec, velocity_quadratic_m_per_s_per_mm2=17.0)
        source = build_numerical_source(spec, particle_count=17, seed=73, full_width_mm=1.0, residual_sigma_m_per_s=0.0)
        offset = source.source_x_mm-spec.center_x_mm
        np.testing.assert_allclose(source.velocity_z_m_per_s, spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*offset+17*offset**2)
        np.testing.assert_array_equal(source.residual_m_per_s, np.zeros(17))

    def test_reflectron_retuning_does_not_move_any_geometry_or_accelerator_voltage(self) -> None:
        before, after = self.point(0.0), self.point()
        self.assertEqual(before.reflectron, after.reflectron)
        self.assertEqual(before.focus_drift_mm, after.focus_drift_mm)
        for name in ("repeller_v", "grid1_v", "grid2_v", "field1_v_per_mm", "field2_v_per_mm", "field3_v_per_mm"):
            self.assertEqual(getattr(before.state, name), getattr(after.state, name))
        self.assertNotEqual(before.inner.stage1_voltage_drop_v, after.inner.stage1_voltage_drop_v)
        self.assertLess(abs(after.reflectron_solution.total_first_derivative_residual), 1e-12)
        self.assertLess(abs(after.reflectron_solution.total_second_derivative_residual), 1e-12)

    def test_zero_residual_matches_existing_affine_exact_total_time(self) -> None:
        source, point = self.sample(sigma=0.0), self.point()
        result = propagate_ideal_source(source, point, settings=self.settings)
        expected = exact_total_normalized_time(point.design_source, point.state, point.reflectron, point.inner, source.source_x_mm, point.focus_drift_mm)*point.design_source.time_scale_s_sqrt_v_per_mm*1e6
        np.testing.assert_allclose(result.tof_us, expected, atol=2e-14, rtol=1e-14)
        self.assertEqual(result.summary["detector_arrival_count"], 31)
        self.assertEqual(result.summary["status"], "SUCCESS")

    def test_fixed_reference_plane_closure_in_full_particle_times(self) -> None:
        point = self.point()
        offsets = np.linspace(-0.003, 0.003, 7)
        times = np.asarray(exact_total_normalized_time(
            point.design_source, point.state, point.reflectron, point.inner,
            self.spec.center_x_mm + offsets, point.focus_drift_mm,
        ))
        coefficients = np.polynomial.polynomial.polyfit(offsets, times-times[3], 4)
        # Finite-time differencing amplifies float64 roundoff by h^-order;
        # these bounds are tied to the evaluated time magnitude and stencil.
        roundoff = 64.0*np.spacing(float(np.max(times)))
        self.assertLess(abs(coefficients[1]), roundoff/0.001)
        self.assertLess(abs(coefficients[2]), roundoff/0.001**2)

    def test_two_zone_degeneration_independent_of_arbitrary_split(self) -> None:
        first = self.point(eta=0.0)
        second = build_working_point(self.spec, replace(self.outer, split_fraction=.7), self.reflectron, design_velocity_slope_m_per_s_per_mm=self.spec.velocity_slope_m_per_s_per_mm, eta=0.0, focus_drift_mm=first.focus_drift_mm)
        left = propagate_ideal_source(self.sample(), first, settings=self.settings)
        right = propagate_ideal_source(self.sample(), second, settings=self.settings)
        np.testing.assert_allclose(left.tof_us, right.tof_us, rtol=1e-14, atol=2e-14)

    def test_loss_labels_keep_full_mother_and_no_common_hit_filter(self) -> None:
        point = self.point()
        source = AxialParticleSource(np.arange(1, 5), np.array([-1., .01, 1.5, 1.5]), np.array([0., -2000., 0., 50000.]), np.zeros(4), 100.)
        result = propagate_ideal_source(source, point, settings=self.settings)
        self.assertEqual(result.classification.tolist(), ["source_outside_first_acceleration_zone", "repeller_collision", "detector_arrival", "reflectron_backplate_collision"])
        self.assertEqual(sum(result.summary["classification_counts"].values()), 4)
        self.assertFalse(result.summary["full_cohort_reachable"])
        self.assertTrue(np.isnan(result.tof_us[[0, 1, 3]]).all())

    def test_first_stage_mirror_turn_is_unsupported_not_fabricated_arrival(self) -> None:
        point = self.point()
        point = replace(point, inner=InnerSolution(2100.0, 10.0, point.inner.eta))
        result = propagate_ideal_source(self.sample(sigma=0.0), point, settings=self.settings)
        self.assertEqual(result.summary["classification_counts"], {"reflectron_stage1_turn_model_unsupported": 31})
        self.assertEqual(result.summary["status"], "NO_ARRIVALS")

    def test_identical_arrivals_have_no_infinite_or_fabricated_resolution(self) -> None:
        result = propagate_ideal_source(self.sample(width=0.0, sigma=0.0), self.point(), settings=self.settings)
        self.assertEqual(result.summary["status"], "SINGULAR_OR_NUMERICALLY_UNRESOLVED_PEAK")
        self.assertIsNone(result.summary["peak_metrics"])

    def test_invalid_source_and_mismatched_mass_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.sample(sigma=-1.0)
        with self.assertRaises(ValueError):
            AxialParticleSource(np.array([1, 1]), np.zeros(2), np.zeros(2), np.zeros(2), 100.)
        with self.assertRaises(ValueError):
            propagate_ideal_source(replace(self.sample(), mass_to_charge_th=300.), self.point(), settings=self.settings)

    def test_slope_scan_uses_theory_derived_matching_and_zero_slope_arms(self) -> None:
        config = slope_scan.load_json(Path(__file__).parents[2] / "config" / "experiments" / "ideal_source_affine_slope_scan.json")
        slope_scan.validate_slope_scan_config(config)
        zero = slope_scan._arms(config, 0.0)
        self.assertEqual(zero["zero_slope_design"], zero["matching_slope_design"])
        historical = slope_scan._arms(config, 37.79182865654923)
        self.assertNotEqual(historical["matching_slope_design"].design_source.chi_slope_sqrt_v_per_mm, 0.0)
        self.assertEqual(historical["zero_slope_design"].design_source.chi_slope_sqrt_v_per_mm, 0.0)
        self.assertNotEqual(historical["matching_slope_design"].inner, historical["zero_slope_design"].inner)
        self.assertNotEqual(
            historical["matching_slope_design"].state.field3_v_per_mm,
            historical["zero_slope_design"].state.field3_v_per_mm,
        )


if __name__ == "__main__":
    unittest.main()
