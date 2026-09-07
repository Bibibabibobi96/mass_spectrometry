from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import json

from common.contracts.file_identity import file_sha256

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.recover_completed_single_flight import (
    _campaign_source_path,
    _completed_batch_logs,
    _find_failed_child,
    _frozen_input_path,
    _recovery_parent_config,
    _recovery_child_dir,
    _source_region_diagnostic_profile_id,
    _verify_manifest,
    _write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class CompletedSingleFlightRecoveryTests(unittest.TestCase):
    def test_campaign_source_resolves_from_frozen_workspace_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repo = workspace / "simulation_repo"
            campaign = repo / "config" / "campaign.json"
            campaign.parent.mkdir(parents=True)
            campaign.write_text("{}\n", encoding="utf-8")
            resolved = _campaign_source_path(
                repo_root=repo,
                requested_path=repo / "simulation_repo" / "config" / "campaign.json",
                recorded_path="simulation_repo/config/campaign.json",
            )
            self.assertEqual(resolved, campaign)

    def test_recovery_prefers_run_local_frozen_input_over_transient_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            retained = root / "inputs" / "resolved_population_contract.json"
            retained.parent.mkdir()
            retained.write_text('{"frozen": true}\n', encoding="utf-8")
            transient = root / "short" / "resolved_population_contract.json"
            transient.parent.mkdir()
            transient.write_text(retained.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(_frozen_input_path(
                {"resolved_population_contract": str(transient)},
                "resolved_population_contract", child_dir=root,
            ), retained)
            transient.write_text('{"frozen": false}\n', encoding="utf-8")
            with self.assertRaisesRegex(Exception, "identity differs"):
                _frozen_input_path(
                    {"resolved_population_contract": str(transient)},
                    "resolved_population_contract", child_dir=root,
                )

    def test_recovery_parent_config_publishes_all_standard_identity_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repo = workspace / "simulation_repo"
            repo.mkdir()
            runs = workspace / "artifacts" / "projects" / "fixture" / "runs"
            source = runs / "source"
            source.mkdir(parents=True)
            files = {}
            for name in (
                "composition_plan", "campaign", "frozen_campaign_experiment",
                "failed_parent_manifest", "recovered_child_manifest", "recovery_receipt",
            ):
                path = source / f"{name}.json"
                path.write_text("{}\n", encoding="utf-8")
                files[name] = path
            run_dir = runs / "20260905_184202__analysis__cross__recovery-fixture__n5__r02"
            run_dir.mkdir()
            output = run_dir / "summary.json"
            output.write_text('{"status": "success"}\n', encoding="utf-8")
            config = _recovery_parent_config(
                failed_config={
                    "inputs": {"composition_plan": str(files["composition_plan"])},
                    "policy_id": "fixture_policy",
                },
                run_id=run_dir.name,
                repo_root=repo,
                campaign_path=files["campaign"],
                frozen_campaign_path=files["frozen_campaign_experiment"],
                failed_parent_manifest_path=files["failed_parent_manifest"],
                child_manifest_path=files["recovered_child_manifest"],
                receipt_path=files["recovery_receipt"],
                campaign_id="campaign_a",
                experiment_id="experiment_a",
                experiment_row_sha256="A" * 64,
                child_parameters={
                    "connection_profile_id": "connection_a",
                    "source_branch_id": "simion",
                    "launched_particle_count": 5,
                },
            )
            (run_dir / "run_config.json").write_text(
                json.dumps(config), encoding="utf-8",
            )
            manifest = _write_manifest(
                repo_root=REPO_ROOT, run_dir=run_dir, outputs=[output],
            )
            published = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(published["status"], "success")
            self.assertTrue(all(record["exists"] for record in published["inputs"].values()))
            self.assertEqual(config["campaign_id"], "campaign_a")
            self.assertEqual(config["particle_count"], 5)

    def test_recovery_validation_contract_uses_canonical_energy_tolerance_name(self) -> None:
        """Recovery consumes the current restart-validation contract vocabulary."""
        source = (
            Path(__file__).resolve().parents[1]
            / "workflows" / "family_source_closure"
            / "recover_completed_single_flight.py"
        ).read_text(encoding="utf-8")
        self.assertIn('tolerances["energy_abs_tolerance_eV"]', source)
        self.assertNotIn('tolerances["energy_rowwise_abs_tolerance_eV"]', source)

    def test_recovery_binds_the_frozen_experiment_not_a_mutable_campaign_hash(self) -> None:
        """Exploration recovery records its immutable parent input as authority."""
        source = (
            Path(__file__).resolve().parents[1]
            / "workflows" / "family_source_closure"
            / "recover_completed_single_flight.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"frozen_parent_experiment_sha256"', source)
        self.assertNotIn('campaign_source["sha256"]', source)

    def test_recovery_replays_required_terminal_taxonomy(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "workflows" / "family_source_closure"
            / "recover_completed_single_flight.py"
        ).read_text(encoding="utf-8")
        self.assertIn('analysis.append("--require-terminal-taxonomy")', source)

    def test_accepts_interrupted_manifest_only_when_explicitly_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run_manifest.json"
            run_config = Path(directory) / "run_config.json"
            run_config.write_text("{}\n", encoding="utf-8")
            manifest.write_text(json.dumps({
                "role": "simulation_run_manifest", "status": "interrupted",
                "mode": "rf_to_oatof_simion_single_flight", "inputs": {}, "outputs": [],
                "run_config": {
                    "path": str(run_config), "exists": True,
                    "bytes": run_config.stat().st_size, "sha256": file_sha256(run_config),
                },
            }), encoding="utf-8")
            self.assertEqual(
                _verify_manifest(
                    manifest, status=("failed", "interrupted"),
                    mode="rf_to_oatof_simion_single_flight",
                )["status"],
                "interrupted",
            )
            with self.assertRaises(Exception):
                _verify_manifest(
                    manifest, status="failed", mode="rf_to_oatof_simion_single_flight",
                )

    def test_finds_child_from_the_frozen_parent_population_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "20260826_011500__sim__cross__fixed-pulse__n1000__r01"
            parent.mkdir()
            child = root / "20260826_011500__sim__simion__rf-oatof-single-flight-gap0__n900__r01"
            child.mkdir()
            (child / "run_manifest.json").write_text("{}\n", encoding="utf-8")
            resolved = {"connector": {"length_mm": 0}}
            self.assertEqual(_find_failed_child(parent, resolved, 900), child)

    def test_checkpoint_accepts_only_nonphysical_run_config_bookkeeping_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "run_manifest.json"
            run_config = root / "run_config.json"
            identity = {
                "run_id": "20260905_184202__sim__simion__fixture__n1",
                "mode": "rf_to_oatof_simion_single_flight",
            }
            run_config.write_text(json.dumps(identity), encoding="utf-8")
            bound = {
                "path": str(run_config), "exists": True,
                "bytes": run_config.stat().st_size, "sha256": file_sha256(run_config),
            }
            manifest.write_text(json.dumps({
                "role": "simulation_run_manifest", "status": "checkpoint",
                **identity, "run_config": bound, "inputs": {}, "outputs": [],
            }), encoding="utf-8")
            run_config.write_text(json.dumps({
                **identity, "parameters": {"execution_batch_count": 2},
            }), encoding="utf-8")
            self.assertEqual(_verify_manifest(
                manifest, status=("failed", "checkpoint"), mode=identity["mode"],
            )["status"], "checkpoint")
            run_config.write_text(json.dumps({
                **identity, "mode": "different_mode",
            }), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "checkpoint run configuration identity"):
                _verify_manifest(
                    manifest, status=("failed", "checkpoint"), mode=identity["mode"],
                )

    def test_recovery_child_has_a_valid_distinct_retry_identity(self) -> None:
        parent = Path(
            "20260826_011500__analysis__cross__fixed-pulse-recovery__n1000__r01"
        )
        self.assertEqual(
            _recovery_child_dir(parent, 900).name,
            "20260826_011500__analysis__simion__recovered-single-flight__n900__r01",
        )

    def test_uses_sole_frozen_diagnostic_profile_when_campaign_is_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configuration = Path(directory) / "configuration.json"
            configuration.write_text(
                json.dumps({"source_region_diagnostic_profiles": [
                    {"profile_id": "diagnostic-v1"},
                ]}),
                encoding="utf-8",
            )
            self.assertEqual(
                _source_region_diagnostic_profile_id({}, configuration),
                "diagnostic-v1",
            )

    def test_recovers_each_completed_parallel_batch_with_its_own_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            inputs = root / "inputs"
            inputs.mkdir()
            for index in (1, 2, 3):
                (logs / f"simion__batch{index:02d}.stdout.log").write_text(
                    "status,Fly completed.\n", encoding="utf-8",
                )
            (inputs / "simion_execution_batch_plan.json").write_text(
                json.dumps({"batches": [
                    {"count": 3}, {"count": 4}, {"count": 5},
                ]}),
                encoding="utf-8",
            )
            paths, counts = _completed_batch_logs(
                child_dir=root,
                inputs={"simion_execution_batch_plan": "missing-temporary-path.json"},
                launched_count=12,
            )
        self.assertEqual([path.name for path in paths], [
            "simion__batch01.stdout.log", "simion__batch02.stdout.log",
            "simion__batch03.stdout.log",
        ])
        self.assertEqual(counts, [3, 4, 5])
