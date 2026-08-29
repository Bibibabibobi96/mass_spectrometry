from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure import run_time_series_successor as successor


class TimeSeriesSuccessorTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        producer_dir = root / "producer"
        materialized_dir = root / "materialized"
        producer_dir.mkdir()
        materialized_dir.mkdir()
        source = {"run_id": "upstream", "launched_particle_count": 10,
                  "manifest": {"sha256": "A"}, "state": {"sha256": "B"},
                  "particle_source": {"sha256": "C"}, "metadata": {"sha256": "D"}}
        source_contract = producer_dir / "source.json"
        source_contract.write_text(json.dumps({"source_branches": {"simion": {"source": source}}}))
        producer_config = producer_dir / "run_config.json"
        parameters = {"execution_mode": successor.PRODUCER_MODE, "source_branch_id": "simion",
                      "connection_profile_id": "connection", "layout_profile_id": "layout",
                      "architecture_generation_id": "architecture", "source_profile_id": "source",
                      "field_overlay_id": "field", "three_zone_candidate_sha256": "candidate"}
        producer_config.write_text(json.dumps({"parameters": parameters, "inputs": {"resolved_source_contract": str(source_contract)}}))
        producer_manifest = producer_dir / "run_manifest.json"
        producer_manifest.write_text(json.dumps({"role": "simulation_run_manifest", "project": successor.INTEGRATION_ID,
            "status": "success", "run_id": "producer", "run_config": {"path": str(producer_config)}}))
        receipt = materialized_dir / "results" / "time_series_restart_materialization_receipt.json"
        receipt.parent.mkdir()
        receipt.write_text(json.dumps({"pulse_target_state": {"sha256": "STATE", "particle_count": 3,
            "ordered_particle_id_sha256": "IDS"}}))
        materialized_config = materialized_dir / "run_config.json"
        materialized_config.write_text(json.dumps({"inputs": {"producer_manifest": str(producer_manifest.resolve())}}))
        materialized_manifest = materialized_dir / "run_manifest.json"
        materialized_manifest.write_text(json.dumps({"run_config": {"path": str(materialized_config)}}))
        shared = {"source_release_mode": "pre_pulse_restart",
            "connection_profile_id": "connection", "single_flight_layout_profile_id": "layout",
            "architecture_generation_id": "architecture", "source_profile_id": "source", "field_overlay_id": "field",
            "three_zone_candidate_sha256": "candidate", "source": source,
            "pre_pulse_source_state": {"sha256": "STATE", "particle_count": 3,
                "materialization_receipt": {"sha256": successor.file_sha256(receipt)}},
            "single_flight_population": {"execution_population": {"particle_count": 3, "ordered_particle_id_sha256": "IDS"}}}
        campaign = root / "campaign.json"
        campaign.write_text(json.dumps({"role": "rf_multipole_oatof_experiment_campaign", "integration_id": successor.INTEGRATION_ID,
            "experiments": {"shared": shared, "variation_axes": ["connection_profile_id"], "rows": [{"sequence": 1,
                "experiment_id": "consumer", "run_id": "20260827_200000__sim__cross__successor__n3", "overrides": {}}]}}))
        return producer_manifest, materialized_manifest, campaign

    def test_accepts_exactly_bound_successor_from_shared_row_authoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            producer, materialized, campaign = self._fixture(Path(directory))
            result = successor.validate_successor(producer_manifest_path=producer, consumer_campaign_path=campaign,
                consumer_experiment_id="consumer", materialization_manifest_path=materialized)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["pulse_disabled_transition"], {"producer": True, "consumer": False})

    def test_rejects_layout_drift_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            producer, materialized, campaign = self._fixture(Path(directory))
            document = json.loads(campaign.read_text())
            document["experiments"]["rows"][0]["overrides"] = {
                "connection_profile_id": "other"
            }
            campaign.write_text(json.dumps(document))
            with self.assertRaisesRegex(ContractError, "connection_profile_id"):
                successor.validate_successor(producer_manifest_path=producer, consumer_campaign_path=campaign,
                    consumer_experiment_id="consumer", materialization_manifest_path=materialized)

    def test_orchestration_delegates_only_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            producer, materialized, campaign = self._fixture(Path(directory))
            with patch.object(successor, "materialize_run", return_value=materialized), patch.object(successor, "_run") as dispatch:
                successor.orchestrate(repo_root=Path(directory), producer_manifest_path=producer,
                    materialization_run_dir=Path(directory) / "new", consumer_campaign_path=campaign,
                    consumer_experiment_id="consumer", execute=True)
        command = dispatch.call_args.kwargs.get("command", dispatch.call_args.args[0])
        self.assertIn("execute.ps1", " ".join(command))
        self.assertIn("-SolverAuthorized", command)


if __name__ == "__main__":
    unittest.main()
