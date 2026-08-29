"""Unit tests for continuous-cohort full-flight campaign authoring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_full_flight_campaign_from_pre_pulse import (
    author_campaign,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_CAMPAIGN = REPO_ROOT / (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "config/explorations/ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000.json"
)
PROJECT = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


def _record(path: Path, workspace: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(workspace).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _run_record(path: Path, run_dir: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(run_dir).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


class AuthorFullFlightCampaignFromPrePulseTests(unittest.TestCase):
    def _source_campaign(self, root: Path, *, continuous: bool = True) -> Path:
        campaign = json.loads(SOURCE_CAMPAIGN.read_text(encoding="utf-8"))
        if not continuous:
            campaign["experiments"]["shared"]["source_release_mode"] = "pre_pulse_restart"
        path = root / "source.json"
        path.write_text(json.dumps(campaign), encoding="utf-8")
        return path

    def _parent(self, workspace: Path, *, experiment_id: str, run_id: str) -> Path:
        run_dir = workspace / "artifacts" / "projects" / PROJECT / "runs" / run_id
        results = run_dir / "results"
        results.mkdir(parents=True)
        run_config = run_dir / "run_config.json"
        run_config.write_text(json.dumps({"experiment_id": experiment_id}), encoding="utf-8")
        receipt = results / "candidate_selection.json"
        content_key = "A" * 64
        receipt.write_text(json.dumps({"content_key": content_key}), encoding="utf-8")
        child = workspace / "artifacts" / "projects" / PROJECT / "runs" / "screen-child" / "run_manifest.json"
        child.parent.mkdir(parents=True)
        child.write_text("{}", encoding="utf-8")
        transition = results / "pulse_timing_transition.json"
        transition.write_text(json.dumps({
            "schema_version": 1,
            "role": "rf_oatof_pulse_timing_transition",
            "status": "candidate_selected_confirmation_required",
            "discovery_run_id": run_id,
            "content_key": content_key,
            "candidate_selection_receipt": _record(receipt, workspace),
            "screening_child_manifest": _record(child, workspace),
        }), encoding="utf-8")
        manifest = {
            "status": "success", "project": PROJECT, "run_id": run_id,
            "run_config": _run_record(run_config, run_dir),
            "outputs": [
                _run_record(receipt, run_dir), _run_record(transition, run_dir),
            ],
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run_dir

    def _maps(self, root: Path, experiment_id: str, parent: Path) -> tuple[Path, Path]:
        producers = root / "producers.json"
        runs = root / "runs.json"
        producers.write_text(json.dumps({experiment_id: str(parent)}), encoding="utf-8")
        runs.write_text(json.dumps({experiment_id: "20260829_010000__sim__cross__full__n5000"}), encoding="utf-8")
        return producers, runs

    def test_authors_continuous_full_population_with_manifest_bound_transition(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers, runs = self._maps(root, experiment_id, parent)
            result = author_campaign(
                source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                run_id_mapping_path=runs, output_path=root / "full.json",
                campaign_id="full_flight_test", workspace=workspace,
            )
            self.assertNotIn("pre_pulse_time_series_screening", result)
            shared = result["experiments"]["shared"]
            self.assertEqual(shared["source_release_mode"], "continuous_frontend")
            self.assertEqual(
                shared["single_flight_population"]["population_mode"],
                "continuous_injection_full_population",
            )
            self.assertEqual(shared["single_flight_population"]["postselection_policy"], "prohibited")
            self.assertIn("pulse_timing_transition_authority", result["experiments"]["variation_axes"])
            self.assertEqual(len(result["experiments"]["rows"]), 1)
            self.assertEqual(
                result["experiments"]["rows"][0]["overrides"]
                ["pulse_timing_transition_authority"]["path"],
                "artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/producer-a/results/pulse_timing_transition.json",
            )
            self.assertEqual(
                shared["single_flight_pulse_schedule_policy"]["cache_miss_policy"]["mode"],
                "auto_detector_blind_discovery_and_confirmation_v1",
            )

    def test_rejects_parent_experiment_mapping_drift(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id="wrong", run_id="producer-a")
            producers, runs = self._maps(root, experiment_id, parent)
            with self.assertRaisesRegex(ContractError, "experiment mapping differs"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                    run_id_mapping_path=runs, output_path=root / "full.json",
                    campaign_id="full_flight_test", workspace=workspace,
                )

    def test_rejects_noncontinuous_source_and_existing_output(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers, runs = self._maps(root, experiment_id, parent)
            with self.assertRaisesRegex(ContractError, "not continuous_frontend"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root, continuous=False), producer_mapping_path=producers,
                    run_id_mapping_path=runs, output_path=root / "full.json",
                    campaign_id="full_flight_test", workspace=workspace,
                )
            existing = root / "existing.json"
            existing.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "output already exists"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                    run_id_mapping_path=runs, output_path=existing,
                    campaign_id="full_flight_test", workspace=workspace,
                )


if __name__ == "__main__":
    unittest.main()
