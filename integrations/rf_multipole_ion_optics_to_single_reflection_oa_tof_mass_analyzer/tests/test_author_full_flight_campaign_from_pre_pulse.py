"""Unit tests for continuous-cohort full-flight campaign authoring."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_full_flight_campaign_from_pre_pulse import (
    author_campaign,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    expand_pre_pulse_campaign_profile,
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
        campaign = expand_pre_pulse_campaign_profile(
            json.loads(SOURCE_CAMPAIGN.read_text(encoding="utf-8"))
        )
        campaign["experiments"]["shared"]["source_release_mode"] = (
            "continuous_frontend" if continuous else "pre_pulse_restart"
        )
        path = root / "source.json"
        path.write_text(json.dumps(campaign), encoding="utf-8")
        return path

    def _full_mother_population(self) -> dict[str, object]:
        """Return the active complete-cohort profile, not a hand-made subset."""

        campaign = expand_pre_pulse_campaign_profile(
            json.loads(SOURCE_CAMPAIGN.read_text(encoding="utf-8"))
        )
        return deepcopy(campaign["experiments"]["shared"]["single_flight_population"])

    def _parent(
        self, workspace: Path, *, experiment_id: str, run_id: str,
        with_transition: bool = True,
    ) -> Path:
        run_dir = workspace / "artifacts" / "projects" / PROJECT / "runs" / run_id
        results = run_dir / "results"
        inputs = run_dir / "inputs"
        results.mkdir(parents=True)
        inputs.mkdir()
        run_config = run_dir / "run_config.json"
        run_config.write_text(json.dumps({"experiment_id": experiment_id}), encoding="utf-8")
        population = inputs / "resolved_population_contract.json"
        mother_source = inputs / "mother_particle_source.csv"
        source_sha = "B" * 64
        shared_population = self._full_mother_population()
        execution_population = shared_population["execution_population"]
        source_authority = shared_population["source_authority"]
        mother_source.write_text(
            "particle_id\n" + "".join(f"{particle_id}\n" for particle_id in range(1, 5001)),
            encoding="utf-8",
        )
        population.write_text(json.dumps({
            "role": "rf_oatof_resolved_population_contract",
            "experiment_id": experiment_id,
            "population_mode": shared_population["population_mode"],
            "source_release_mode": "continuous_frontend",
            "postselection_policy": "prohibited",
            "single_flight_execution": {"is_pre_pulse_restart": False},
            "source_authority": {
                **source_authority,
                "particle_count": 5000,
                "table": {"sha256": source_sha},
            },
            "execution_population": execution_population,
            "denominators": shared_population["denominators"],
        }), encoding="utf-8")
        # The fixture uses the actual file identity in both the resolved
        # population and screening receipt, just as a real producer does.
        source_sha = file_sha256(mother_source)
        population_value = json.loads(population.read_text(encoding="utf-8"))
        population_value["source_authority"]["table"]["sha256"] = source_sha
        population.write_text(json.dumps(population_value), encoding="utf-8")
        screening = results / "pre_pulse_time_series_screening_receipt.json"
        screening.write_text(json.dumps({
            "role": "rf_oatof_pre_pulse_time_series_screening_receipt",
            "status": "success", "qualification": "FUNCTIONAL_ONLY",
            "execution_mode": "real_pa_rf_pre_pulse_time_series",
            "pulse_disabled": True, "resolution_claim_allowed": False,
            "particle_count": 5000,
            "identities": {
                "experiment_id": experiment_id,
                "resolved_population_contract_sha256": file_sha256(population),
                "mother_particle_source_sha256": source_sha,
                "ordered_particle_id_sha256": execution_population["ordered_particle_id_sha256"],
            },
            "sample_census": [{"sample_index": 1, "alive_count": 3}],
            "terminal_census": {"window_complete": {"count": 3}},
        }), encoding="utf-8")
        receipt = results / "candidate_selection.json"
        content_key = "A" * 64
        receipt.write_text(json.dumps({"content_key": content_key}), encoding="utf-8")
        child = workspace / "artifacts" / "projects" / PROJECT / "runs" / "screen-child" / "run_manifest.json"
        child.parent.mkdir(parents=True)
        child.write_text("{}", encoding="utf-8")
        transition = results / "pulse_timing_transition.json"
        if with_transition:
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
            "inputs": {
                "resolved_population_contract": _run_record(population, run_dir),
                "mother_particle_source": _run_record(mother_source, run_dir),
            },
            "outputs": [_run_record(screening, run_dir)] + (
                [_run_record(receipt, run_dir), _run_record(transition, run_dir)]
                if with_transition else []
            ),
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run_dir

    def _producer_map(self, root: Path, experiment_id: str, parent: Path) -> Path:
        producers = root / "producers.json"
        producers.write_text(json.dumps({experiment_id: str(parent)}), encoding="utf-8")
        return producers

    def test_authors_continuous_full_population_with_manifest_bound_transition(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers = self._producer_map(root, experiment_id, parent)
            result = author_campaign(
                source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                output_path=root / "full.json",
                campaign_id="full_flight_test", workspace=workspace,
            )
            self.assertNotIn("pre_pulse_time_series_screening", result)
            shared = result["experiments"]["shared"]
            self.assertEqual(shared["source_release_mode"], "continuous_frontend")
            self.assertEqual(
                shared["single_flight_population"]["population_mode"],
                "independent_spatial_velocity_ion_source_snapshot",
            )
            self.assertEqual(shared["single_flight_population"]["postselection_policy"], "prohibited")
            self.assertIn("pulse_timing_transition_authority", result["experiments"]["variation_axes"])
            self.assertEqual(len(result["experiments"]["rows"]), 1)
            self.assertEqual(
                result["experiments"]["rows"][0]["values"]
                ["pulse_timing_transition_authority"]["path"],
                "artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/producer-a/results/pulse_timing_transition.json",
            )
            self.assertEqual(
                shared["single_flight_pulse_schedule_policy"]["cache_miss_policy"]["mode"],
                "auto_detector_blind_discovery_and_confirmation_v1",
            )

    def test_accepts_workspace_relative_producer_path(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers = root / "producers.json"
            producers.write_text(
                json.dumps({experiment_id: str(parent.relative_to(workspace))}),
                encoding="utf-8",
            )
            result = author_campaign(
                source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                output_path=root / "full.json", campaign_id="full_flight_test",
                workspace=workspace,
            )
            self.assertEqual(len(result["experiments"]["rows"]), 1)

    def test_rejects_parent_experiment_mapping_drift(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id="wrong", run_id="producer-a")
            producers = self._producer_map(root, experiment_id, parent)
            with self.assertRaisesRegex(ContractError, "experiment mapping differs"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                    output_path=root / "full.json",
                    campaign_id="full_flight_test", workspace=workspace,
                )

    def test_authors_from_successful_screening_without_preexisting_transition(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(
                workspace, experiment_id=experiment_id, run_id="producer-a",
                with_transition=False,
            )
            producers = self._producer_map(root, experiment_id, parent)
            result = author_campaign(
                source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                output_path=root / "full.json",
                campaign_id="full_flight_test", workspace=workspace,
            )
            row = result["experiments"]["rows"][0]
            self.assertNotIn("pulse_timing_transition_authority", row["values"])
            self.assertNotIn(
                "pulse_timing_transition_authority", result["experiments"]["variation_axes"],
            )
            self.assertEqual(
                result["experiments"]["shared"]["source_release_mode"],
                "continuous_frontend",
            )
            self.assertEqual(
                result["experiments"]["shared"]["single_flight_population"]
                ["execution_population"]["selection_algorithm"],
                "all_rows_in_frozen_file_order",
            )

    def test_rejects_screening_without_full_mother_population(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(
                workspace, experiment_id=experiment_id, run_id="producer-a",
                with_transition=False,
            )
            population = parent / "inputs" / "resolved_population_contract.json"
            value = json.loads(population.read_text(encoding="utf-8"))
            value["execution_population"]["selection_algorithm"] = "survivors_only"
            population.write_text(json.dumps(value), encoding="utf-8")
            # The changed file deliberately invalidates the producer manifest.
            producers = self._producer_map(root, experiment_id, parent)
            with self.assertRaisesRegex(ContractError, "population.*identity differs"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                    output_path=root / "full.json",
                    campaign_id="full_flight_test", workspace=workspace,
                )

    def test_rejects_noncontinuous_source_and_existing_output(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers = self._producer_map(root, experiment_id, parent)
            with self.assertRaisesRegex(ContractError, "not continuous_frontend"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root, continuous=False), producer_mapping_path=producers,
                    output_path=root / "full.json",
                    campaign_id="full_flight_test", workspace=workspace,
                )
            existing = root / "existing.json"
            existing.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "output already exists"):
                author_campaign(
                    source_campaign_path=self._source_campaign(root), producer_mapping_path=producers,
                    output_path=existing,
                    campaign_id="full_flight_test", workspace=workspace,
                )


if __name__ == "__main__":
    unittest.main()
