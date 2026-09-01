from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import json

from common.contracts.file_identity import file_sha256

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.recover_completed_single_flight import (
    _completed_batch_logs,
    _find_failed_child,
    _recovery_child_dir,
    _source_region_diagnostic_profile_id,
    _verify_manifest,
)


class CompletedSingleFlightRecoveryTests(unittest.TestCase):
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
