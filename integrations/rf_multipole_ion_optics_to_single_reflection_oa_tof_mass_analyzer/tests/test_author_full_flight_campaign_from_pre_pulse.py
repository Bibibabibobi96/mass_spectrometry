"""Unit tests for continuous-cohort full-flight campaign authoring."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from copy import deepcopy
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_full_flight_campaign_from_pre_pulse import (
    author_campaign,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure import (
    author_full_flight_campaign_from_pre_pulse as subject,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _replace_schedule_cohort_with_compact_receipt,
    _resolve_continuous_full_flight_comparator,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pre_pulse_campaign_profile import (
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

    def test_authors_directly_from_compact_profiled_campaign(self) -> None:
        """The public compact campaign is the authoring API, not a template."""

        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers = self._producer_map(root, experiment_id, parent)
            result = author_campaign(
                source_campaign_path=SOURCE_CAMPAIGN, producer_mapping_path=producers,
                output_path=root / "full.json", campaign_id="full_flight_test",
                workspace=workspace,
            )
            self.assertEqual(
                result["experiments"]["shared"]["source_release_mode"],
                "continuous_frontend",
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

    def test_compact_v2_post_pulse_authority_replaces_transition_not_population(self) -> None:
        experiment_id = "ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            parent = self._parent(workspace, experiment_id=experiment_id, run_id="producer-a")
            producers = self._producer_map(root, experiment_id, parent)
            authority = {
                "authority_mode": "manifest_bound_continuous_full_flight_comparator_v1",
                "pre_pulse_producer_manifest": {"path": "pre", "sha256": "A" * 64},
                "pre_pulse_mother_particle_source": {"path": "mother", "sha256": "1" * 64},
                "compact_receipt": {"path": "compact", "sha256": "B" * 64},
                "producer_manifest": {"path": "post", "sha256": "C" * 64},
                "producer_frozen_experiment": {"path": "frozen", "sha256": "2" * 64},
                "producer_pulse_schedule": {"path": "schedule", "sha256": "D" * 64},
                "producer_configuration": {"path": "configuration", "sha256": "E" * 64},
                "producer_region_field_contract": {"path": "field", "sha256": "F" * 64},
                "producer_frontend_grid_profile_id": "frontend_xy025_z010_coarse100_full_bore_main_local_xy050_z010",
            }
            post_map = root / "post-map.json"
            post_map.write_text(json.dumps({experiment_id: "post-pulse"}), encoding="utf-8")
            with patch.object(subject, "_validate_compact_continuous_comparator", return_value=authority) as validate:
                result = author_campaign(
                    source_campaign_path=self._source_campaign(root),
                    producer_mapping_path=producers,
                    post_pulse_producer_mapping_path=post_map,
                    output_path=root / "full.json", campaign_id="full_flight_test",
                    workspace=workspace,
                )
            validate.assert_called_once()
        row = result["experiments"]["rows"][0]
        self.assertEqual(row["values"]["continuous_full_flight_comparator_authority"], authority)
        self.assertNotIn("pulse_timing_transition_authority", row["values"])
        self.assertEqual(result["experiments"]["shared"]["source_release_mode"], "continuous_frontend")
        self.assertEqual(
            result["experiments"]["shared"]["single_flight_frontend_grid_profile_id"],
            authority["producer_frontend_grid_profile_id"],
        )
        self.assertEqual(
            result["experiments"]["shared"]["single_flight_population"]
            ["execution_population"]["particle_count"], 5000,
        )

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


class ContinuousComparatorResolverTests(unittest.TestCase):
    """Portable parent→child receipt topology for the continuous comparator."""

    def test_compact_receipt_replaces_every_analytic_cohort_hint(self) -> None:
        schedule = {
            "population_counts": {
                "transmitted_handoff": 5000,
                "predicted_finite_wall_survivors": 54,
            },
            "selected_particle_ids": [7, 331],
            "mean_entry_time_us": 1.0,
            "predicted_centroid_error_x_mm": 0.1,
        }
        receipt = {
            "selection": {
                "pulse_eligible_count": 2,
                "pulse_eligible_particle_ids": [2, 28],
            },
            "pulse_target_state": {"particle_count": 2},
        }
        _replace_schedule_cohort_with_compact_receipt(schedule, receipt)
        self.assertEqual(schedule["pulse_eligible_count"], 2)
        self.assertEqual(schedule["selected_particle_ids"], [2, 28])
        self.assertNotIn("population_counts", schedule)
        self.assertNotIn("mean_entry_time_us", schedule)
        self.assertNotIn("predicted_centroid_error_x_mm", schedule)

    def _fixture(self, root: Path) -> tuple[dict[str, object], dict[str, object], Path]:
        workspace = root.parent

        def write(relative: str, value: object) -> Path:
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")
            return path

        def record(path: Path, base: Path) -> dict[str, object]:
            try:
                rendered_path = path.relative_to(base).as_posix()
            except ValueError:
                rendered_path = path.as_posix()
            return {
                "path": rendered_path,
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }

        project = PROJECT
        execution = {
            "particle_count": 2,
            "ordered_particle_id_sha256": "A" * 64,
            "selection_algorithm": "all_rows_in_frozen_file_order",
            "selection_seed": 0,
        }
        source = {
            "input_role": "single_flight_materialized_ion_source_volume",
            "table_binding": "prepared_materialized_ion_source_volume",
            "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1",
            "particle_count": 2,
        }
        declaration = {
            "population_id": "fixture_mother",
            "population_mode": "independent_spatial_velocity_ion_source_snapshot",
            "source_authority": source,
            "execution_population": execution,
            "denominators": {"population_count": 2, "eligible_population_count": 2},
            "analysis_randomness": {"bootstrap_resample_count": 1, "bootstrap_seed": 1},
            "postselection_policy": "prohibited",
        }
        mother = workspace / "artifacts/pre-child/inputs/mother_particle_source.csv"
        mother.parent.mkdir(parents=True)
        mother.write_text("particle_id\n1\n2\n", encoding="utf-8")
        population = write("artifacts/pre-child/inputs/resolved_population_contract.json", {
            "role": "rf_oatof_resolved_population_contract",
            "experiment_id": "fixture_pre_pulse",
            "population_mode": declaration["population_mode"],
            "source_release_mode": "continuous_frontend",
            "postselection_policy": "prohibited",
            "single_flight_execution": {"is_pre_pulse_restart": False},
            "execution_population": execution,
            "source_authority": {**source, "table": {"sha256": file_sha256(mother)}},
            "denominators": declaration["denominators"],
        })
        handoff = workspace / "artifacts/pre-child/results/pre_pulse_compact_handoff.csv"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("particle_id\n1\n2\n", encoding="utf-8")
        compact = write("artifacts/pre-child/results/pre_pulse_compact_handoff_receipt.json", {
            "method": "native_trace_detector_blind_pulse_selection_v2",
            "status": "success", "pulse_disabled": True,
            "selection_uses_detector_outcome": False, "detector_results_used": False,
            "selection": {
                "mother_population_count": 2,
                "pulse_eligible_count": 2,
                "pulse_eligible_particle_ids": [1, 2],
                "postselection_prohibited": True,
                "pulse_effective_time_us": 7.25,
            },
            "pulse_target_state": {
                "pulse_effective_time_us": 7.25,
                "particle_count": 2,
                "bytes": handoff.stat().st_size,
                "sha256": file_sha256(handoff),
            },
        })
        pre_child = workspace / "artifacts/pre-child/run_manifest.json"
        pre_child.write_text(json.dumps({
            "role": "simulation_run_manifest", "run_id": "pre-child",
            "status": "success", "project": project,
            "mode": "rf_to_oatof_simion_single_flight",
            "inputs": {"resolved_population_contract": record(population, pre_child.parent),
                       "mother_particle_source": record(mother, pre_child.parent)},
            "outputs": [record(compact, pre_child.parent), record(handoff, pre_child.parent)],
        }), encoding="utf-8")
        pre_parent = workspace / "artifacts/pre-parent/run_manifest.json"
        pre_parent.parent.mkdir(parents=True)
        pre_parent_config = pre_parent.parent / "run_config.json"
        pre_parent_config.write_text(json.dumps({"experiment_id": "fixture_pre_pulse"}), encoding="utf-8")
        pre_parent.write_text(json.dumps({
            "role": "simulation_run_manifest", "run_id": "pre-parent",
            "status": "success", "project": project,
            "mode": "multipole_family_source_closure",
            "run_config": record(pre_parent_config, pre_parent.parent),
            "inputs": {"single_flight_transport_manifest": record(pre_child, pre_parent.parent)},
        }), encoding="utf-8")

        configuration = write("artifacts/post-child/inputs/simion_single_flight.json", {"configuration": "same"})
        field = write("artifacts/post-child/inputs/resolved_region_field_contract.json", {"semantic_sha256": "F" * 64})
        schedule = write("artifacts/post-child/inputs/resolved_single_flight_pulse_schedule.json", {
            "method": "compact_detector_blind_trace_restart_v1",
            "pulse_effective_time_us": 7.25, "pulse_width_us": 1.5,
            "pulse_eligible_count": 2,
            "selected_particle_ids": [1, 2],
            "execution_authority": {"materialization_receipt": {"sha256": file_sha256(compact)}},
        })
        post_child = workspace / "artifacts/post-child/run_manifest.json"
        post_child.write_text(json.dumps({
            "role": "simulation_run_manifest", "run_id": "post-child",
            "status": "success", "project": project,
            "mode": "rf_to_oatof_simion_single_flight", "formal_eligible": False,
            "inputs": {"pulse_schedule": record(schedule, post_child.parent),
                       "configuration": record(configuration, post_child.parent),
                       "resolved_region_field_contract": record(field, post_child.parent)},
        }), encoding="utf-8")
        frozen = write("artifacts/post-parent/inputs/frozen_campaign_experiment.json", {"experiment": {
            "single_flight_frontend_grid_profile_id": "real_full_bore"
        }})
        post_parent = workspace / "artifacts/post-parent/run_manifest.json"
        post_parent.parent.mkdir(parents=True, exist_ok=True)
        post_parent_config = post_parent.parent / "run_config.json"
        post_parent_config.write_text(json.dumps({"experiment_id": "fixture_post_pulse"}), encoding="utf-8")
        post_parent.write_text(json.dumps({
            "role": "simulation_run_manifest", "run_id": "post-parent",
            "status": "success", "project": project,
            "mode": "multipole_family_source_closure",
            "run_config": record(post_parent_config, post_parent.parent),
            "inputs": {"single_flight_transport_manifest": record(post_child, post_parent.parent),
                       "frozen_campaign_experiment": record(frozen, post_parent.parent)},
        }), encoding="utf-8")
        current_config = root / "integrations" / project / "config" / "simion_single_flight.json"
        current_config.parent.mkdir(parents=True)
        current_config.write_text(configuration.read_text(encoding="utf-8"), encoding="utf-8")
        authority = {
            "pre_pulse_producer_manifest": record(pre_parent, workspace),
            "pre_pulse_mother_particle_source": record(mother, workspace),
            "compact_receipt": record(compact, workspace),
            "producer_manifest": record(post_parent, workspace),
            "producer_frozen_experiment": record(frozen, workspace),
            "producer_pulse_schedule": record(schedule, workspace),
            "producer_configuration": record(configuration, workspace),
            "producer_region_field_contract": record(field, workspace),
            "producer_frontend_grid_profile_id": "real_full_bore",
        }
        return authority, declaration, field

    def _replace_pre_pulse_parent_with_recovery(
        self, root: Path, authority: dict[str, object]
    ) -> Path:
        """Build the current successful compact recovery producer topology."""

        workspace = root.parent

        def record(path: Path, base: Path) -> dict[str, object]:
            try:
                rendered = path.relative_to(base).as_posix()
            except ValueError:
                rendered = str(path)
            return {
                "path": rendered,
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }

        failed_dir = workspace / "artifacts/failed-child"
        failed_dir.mkdir(parents=True)
        failed_config = failed_dir / "run_config.json"
        failed_config.write_text(json.dumps({
            "run_id": "failed-child", "project": PROJECT,
            "mode": "rf_to_oatof_simion_single_flight",
            "parameters": {"execution_mode": "real_pa_rf_pre_pulse_time_series"},
        }), encoding="utf-8")
        failed_manifest = failed_dir / "run_manifest.json"
        failed_manifest.write_text(json.dumps({
            "role": "simulation_run_manifest", "run_id": "failed-child",
            "project": PROJECT, "mode": "rf_to_oatof_simion_single_flight",
            "status": "checkpoint",
        }), encoding="utf-8")

        recovery_dir = workspace / "artifacts/recovery"
        recovery_inputs = recovery_dir / "inputs"
        recovery_results = recovery_dir / "results"
        recovery_inputs.mkdir(parents=True)
        recovery_results.mkdir()
        normal_pre = workspace / "artifacts/pre-child"
        population = recovery_inputs / "resolved_population_contract.json"
        mother = recovery_inputs / "mother_particle_source.csv"
        compact = recovery_results / "pre_pulse_compact_handoff_receipt.json"
        handoff = recovery_results / "pre_pulse_compact_handoff.csv"
        for source, target in (
            (normal_pre / "inputs/resolved_population_contract.json", population),
            (normal_pre / "inputs/mother_particle_source.csv", mother),
            (normal_pre / "results/pre_pulse_compact_handoff_receipt.json", compact),
            (normal_pre / "results/pre_pulse_compact_handoff.csv", handoff),
        ):
            target.write_bytes(source.read_bytes())
        recovery_config = recovery_dir / "run_config.json"
        recovery_config.write_text(json.dumps({
            "run_id": "recovery", "project": PROJECT,
            "mode": "rf_oatof_pre_pulse_time_series_analysis_recovery",
            "experiment_id": "fixture_pre_pulse",
            "inputs": {
                "failed_child_manifest": str(failed_manifest),
                "failed_run_config": str(failed_config),
                "resolved_population_contract": str(population),
                "mother_particle_source": str(mother),
            },
        }), encoding="utf-8")
        recovery_receipt = recovery_results / "pre_pulse_time_series_analysis_recovery_receipt.json"
        recovery_receipt.write_text(json.dumps({
            "role": "rf_oatof_pre_pulse_time_series_analysis_recovery_receipt",
            "status": "success", "solver_reexecuted": False,
            "failed_run": {
                "manifest": str(failed_manifest),
                "manifest_sha256": file_sha256(failed_manifest),
                "run_config": str(failed_config),
                "run_config_sha256": file_sha256(failed_config),
            },
            "materialized_outputs": {
                "mode": "selected_pulse_handoff_only_v1",
                "handoff": {"path": str(handoff), "sha256": file_sha256(handoff)},
                "handoff_receipt": {
                    "path": str(compact), "sha256": file_sha256(compact),
                },
            },
        }), encoding="utf-8")
        recovery_manifest = recovery_dir / "run_manifest.json"
        recovery_manifest.write_text(json.dumps({
            "role": "simulation_run_manifest", "run_id": "recovery",
            "project": PROJECT,
            "mode": "rf_oatof_pre_pulse_time_series_analysis_recovery",
            "status": "success", "formal_eligible": False,
            "run_config": record(recovery_config, recovery_dir),
            "inputs": {
                "failed_child_manifest": record(failed_manifest, recovery_dir),
                "failed_run_config": record(failed_config, recovery_dir),
                "resolved_population_contract": record(population, recovery_dir),
                "mother_particle_source": record(mother, recovery_dir),
            },
            "outputs": [
                record(compact, recovery_dir), record(handoff, recovery_dir),
                record(recovery_receipt, recovery_dir),
            ],
        }), encoding="utf-8")

        authority["pre_pulse_producer_manifest"] = _record(
            recovery_manifest, workspace
        )
        authority["pre_pulse_mother_particle_source"] = _record(mother, workspace)
        authority["compact_receipt"] = _record(compact, workspace)
        schedule = workspace / str(authority["producer_pulse_schedule"]["path"])
        schedule_value = json.loads(schedule.read_text(encoding="utf-8"))
        schedule_value["execution_authority"]["materialization_receipt"]["sha256"] = file_sha256(compact)
        schedule.write_text(json.dumps(schedule_value), encoding="utf-8")
        authority["producer_pulse_schedule"] = _record(schedule, workspace)
        post_child = workspace / "artifacts/post-child/run_manifest.json"
        post_child_value = json.loads(post_child.read_text(encoding="utf-8"))
        post_child_value["inputs"]["pulse_schedule"] = record(schedule, post_child.parent)
        post_child.write_text(json.dumps(post_child_value), encoding="utf-8")
        post_parent = workspace / "artifacts/post-parent/run_manifest.json"
        post_parent_value = json.loads(post_parent.read_text(encoding="utf-8"))
        post_parent_value["inputs"]["single_flight_transport_manifest"] = record(
            post_child, post_parent.parent
        )
        post_parent.write_text(json.dumps(post_parent_value), encoding="utf-8")
        authority["producer_manifest"] = _record(post_parent, workspace)
        return recovery_dir

    def test_resolves_parent_child_chain_and_rejects_bound_source_field_or_time_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            authority, population, field = self._fixture(root)
            # Receipt schemas are separately covered; this fixture isolates the
            # parent→child provenance, field, source, and timing checks.
            with patch("integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare.validate_schema"):
                resolved = _resolve_continuous_full_flight_comparator(
                    root=root, authority=authority, population_declaration=population,
                    resolved_region_field_contract_path=field,
                )
                self.assertEqual(resolved["schedule"]["pulse_effective_time_us"], 7.25)
                self.assertEqual(resolved["schedule"]["selected_particle_ids"], [1, 2])
                self.assertEqual(
                    resolved["execution_authority"]["producer_frontend_grid_profile_id"],
                    "real_full_bore",
                )
                bad_source = root.parent / "artifacts" / "other-mother.csv"
                bad_source.parent.mkdir(exist_ok=True)
                bad_source.write_text("particle_id\n1\n2\n", encoding="utf-8")
                bad_authority = deepcopy(authority)
                bad_authority["pre_pulse_mother_particle_source"] = _record(bad_source, root.parent)
                with self.assertRaisesRegex(ContractError, "compact identity differs"):
                    _resolve_continuous_full_flight_comparator(
                        root=root, authority=bad_authority, population_declaration=population,
                        resolved_region_field_contract_path=field,
                    )
                bad_field = root.parent / "bad-field.json"
                bad_field.write_text(json.dumps({"semantic_sha256": "0" * 64}), encoding="utf-8")
                with self.assertRaisesRegex(ContractError, "voltage field"):
                    _resolve_continuous_full_flight_comparator(
                        root=root, authority=authority, population_declaration=population,
                        resolved_region_field_contract_path=bad_field,
                    )
                schedule = root.parent / authority["producer_pulse_schedule"]["path"]
                value = json.loads(schedule.read_text(encoding="utf-8"))
                value["pulse_effective_time_us"] = 7.5
                schedule.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(ContractError, "schedule SHA-256 is stale"):
                    _resolve_continuous_full_flight_comparator(
                        root=root, authority=authority, population_declaration=population,
                        resolved_region_field_contract_path=field,
                    )

    def test_recovery_producer_authors_and_prepare_resolves_same_compact_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            authority, population, field = self._fixture(root)
            recovery_dir = self._replace_pre_pulse_parent_with_recovery(root, authority)
            workspace = root.parent
            source = expand_pre_pulse_campaign_profile(
                json.loads(SOURCE_CAMPAIGN.read_text(encoding="utf-8"))
            )
            source["experiments"]["shared"]["single_flight_population"] = population
            source["experiments"]["rows"] = [{
                "experiment_id": "fixture_pre_pulse", "values": {},
            }]
            source_path = root / "source.json"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(json.dumps(source), encoding="utf-8")
            producer_map = root / "producer-map.json"
            producer_map.write_text(json.dumps({
                "fixture_pre_pulse": str(recovery_dir),
            }), encoding="utf-8")
            post_map = root / "post-map.json"
            post_map.write_text(json.dumps({
                "fixture_pre_pulse": str(workspace / "artifacts/post-parent"),
            }), encoding="utf-8")
            with patch.object(subject, "validate_schema"):
                result = author_campaign(
                    source_campaign_path=source_path,
                    producer_mapping_path=producer_map,
                    post_pulse_producer_mapping_path=post_map,
                    output_path=root / "full.json",
                    campaign_id="recovered_full_flight_test",
                    workspace=workspace,
                )
            authored = result["experiments"]["rows"][0]["values"][
                "continuous_full_flight_comparator_authority"
            ]
            self.assertEqual(
                authored["pre_pulse_producer_manifest"]["path"],
                "artifacts/recovery/run_manifest.json",
            )
            with patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare.validate_schema"
            ):
                resolved = _resolve_continuous_full_flight_comparator(
                    root=root, authority=authored,
                    population_declaration=population,
                    resolved_region_field_contract_path=field,
                )
            self.assertEqual(resolved["schedule"]["pulse_effective_time_us"], 7.25)

    def test_rejects_recovery_that_reexecuted_solver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            authority, population, field = self._fixture(root)
            recovery_dir = self._replace_pre_pulse_parent_with_recovery(root, authority)
            receipt = recovery_dir / "results/pre_pulse_time_series_analysis_recovery_receipt.json"
            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["solver_reexecuted"] = True
            receipt.write_text(json.dumps(value), encoding="utf-8")
            manifest_path = recovery_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"][-1] = _run_record(receipt, recovery_dir)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            authority["pre_pulse_producer_manifest"] = _record(
                manifest_path, root.parent
            )
            with patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare.validate_schema"
            ), self.assertRaisesRegex(ContractError, "recovery receipt identity differs"):
                _resolve_continuous_full_flight_comparator(
                    root=root, authority=authority,
                    population_declaration=population,
                    resolved_region_field_contract_path=field,
                )

    def test_rejects_schedule_cohort_that_differs_from_compact_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            authority, population, field = self._fixture(root)
            schedule = root.parent / authority["producer_pulse_schedule"]["path"]
            value = json.loads(schedule.read_text(encoding="utf-8"))
            value["selected_particle_ids"] = [2, 1]
            schedule.write_text(json.dumps(value), encoding="utf-8")
            authority["producer_pulse_schedule"] = _record(schedule, root.parent)
            post_manifest = root.parent / authority["producer_manifest"]["path"]
            post_value = json.loads(post_manifest.read_text(encoding="utf-8"))
            post_child_path = root.parent / "artifacts/post-child/run_manifest.json"
            post_child = json.loads(post_child_path.read_text(encoding="utf-8"))
            post_child["inputs"]["pulse_schedule"] = _record(
                schedule, post_child_path.parent
            )
            post_child_path.write_text(json.dumps(post_child), encoding="utf-8")
            post_value["inputs"]["single_flight_transport_manifest"] = {
                "path": "../post-child/run_manifest.json",
                "bytes": post_child_path.stat().st_size,
                "sha256": file_sha256(post_child_path),
            }
            post_manifest.write_text(json.dumps(post_value), encoding="utf-8")
            authority["producer_manifest"] = _record(post_manifest, root.parent)
            with patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare.validate_schema"
            ), self.assertRaisesRegex(ContractError, "pulse schedule differs"):
                _resolve_continuous_full_flight_comparator(
                    root=root,
                    authority=authority,
                    population_declaration=population,
                    resolved_region_field_contract_path=field,
                )


if __name__ == "__main__":
    unittest.main()
