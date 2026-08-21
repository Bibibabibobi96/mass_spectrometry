from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    INTEGRATION_ID,
    _canonical_sha256,
    _resolve_three_zone_n1_authorization,
    _three_zone_gate_pairs,
    _validate_observed_pre_pulse_projection,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.observed_pre_pulse_projection import (
    ARM_AFFINE_FIXED_10EV,
    ARM_COLLAPSED,
    project_observed_pre_pulse_states,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_observed_pre_pulse_projection import (
    ObservedPrePulseProjectionTests,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _record(path: Path, base: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(base).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _rows() -> tuple[dict[str, object], dict[str, object]]:
    common = {
        "execution_strategy": "simion_single_flight",
        "connection_profile_id": "direct_mating_gap_0mm",
        "source": {"identity": "same"},
        "single_flight_layout_profile_id": "three_zone_t5_primary_v1",
        "single_flight_three_zone_candidate": {"path": "artifacts/candidate.json", "bytes": 1, "sha256": "A" * 64},
        "architecture_generation_id": "three_zone_t5_frozen_primary_v1",
        "source_profile_id": "canonical_ideal_linear_z_vz_2p2mm_n1000",
        "single_flight_source_materialization_profile_id": "canonical_ideal_linear_z_vz_2p2mm_n1000",
        "single_flight_frontend_grid_profile_id": "three_zone_frontend_z005",
        "single_flight_oatof_numerical_profile_id": "r100",
        "single_flight_trajectory_quality_profile_id": "tqual_8",
        "single_flight_time_integration_profile_id": "dt160",
        "single_flight_pa_cache_policy": "build_and_publish_if_missing",
        "single_flight_accelerator_field_profile_id": "accelerator_real_three_zone_pa_real_reflectron",
        "source_release_mode": "pre_pulse_restart",
        "field_overlay_id": "three_zone_frontend_v1",
        "single_flight_population": {
            "execution_population": {
                "particle_count": 1,
                "ordered_particle_id_sha256": "080A9ED428559EF602668B4C00F114F1A11C3F6B02A435F0BDC154578E4D7F22",
                "selection_algorithm": "all_rows_in_frozen_file_order",
            },
            "denominators": {"population_count": 1, "eligible_population_count": 1},
        },
    }
    producer = {
        **common,
        "sequence": 1,
        "experiment_id": "three_zone_n1",
        "run_id": "20260817_190000__sim__cross__three-zone-n1__n1",
        "generated_pre_pulse_ordered_subset": {"selection_id": "n1_center_source_id_500_v1"},
        "three_zone_solver_gate": {"gate_id": "three_zone_gate_v1", "stage": "n1_smoke_producer"},
    }
    consumer = json.loads(json.dumps(producer))
    consumer.update({
        "sequence": 2,
        "experiment_id": "three_zone_n100",
        "run_id": "20260817_191000__sim__cross__three-zone-n100__n100",
        "generated_pre_pulse_ordered_subset": {"selection_id": "n100_file_order_source_ids_1_to_100_v1"},
        "three_zone_solver_gate": {
            "gate_id": "three_zone_gate_v1",
            "stage": "n100_solver_authorized_consumer",
            "predecessor_experiment_id": "three_zone_n1",
        },
    })
    consumer["single_flight_population"]["execution_population"]["particle_count"] = 100
    consumer["single_flight_population"]["execution_population"]["ordered_particle_id_sha256"] = (
        "F9E2DBDE0AE4640704FB66EE02C101CF84ABE35137363D62647622606DF61279"
    )
    consumer["single_flight_population"]["denominators"]["population_count"] = 100
    consumer["single_flight_population"]["denominators"]["eligible_population_count"] = 100
    return producer, consumer


def _observed_projection(arm_id: str) -> dict[str, object]:
    projection = {
        "authority_manifest": {"path": "artifacts/authority.json", "sha256": "1" * 64},
        "prepared_arms": {"path": "artifacts/prepared.csv", "sha256": "2" * 64},
        "observed_state": {"path": "artifacts/observed.csv", "sha256": "3" * 64},
        "old_geometry": {"path": "artifacts/old_geometry.json", "sha256": "4" * 64},
        "arm_id": arm_id,
    }
    if arm_id in {
        "affine_zvz_fixed_10eV_transverse_collapsed",
        "observed_zvz_fixed_10eV_transverse_collapsed",
    }:
        projection["comparison_claim"] = (
            "frozen_three_zone_observed_z_vz_nonlinearity_relative_to_affine_effect_only"
        )
    return projection


class ThreeZoneSolverGatePrepareTests(unittest.TestCase):
    def test_segmented_rings_full_width_realization_is_supported(self) -> None:
        producer, consumer = _rows()
        for row in (producer, consumer):
            row["single_flight_layout_profile_id"] = (
                "three_zone_t5_primary_shaping_rings_1p4_v1"
            )
            row["architecture_generation_id"] = (
                "three_zone_t5_frozen_primary_shaping_rings_1p4_v1"
            )
        consumer["generated_pre_pulse_ordered_subset"] = {
            "selection_id": "n100_uniform_full_width_source_ids_1_to_1000_v1"
        }
        campaign = {"schema_version": 6, "experiments": [producer, consumer]}

        self.assertEqual(
            _three_zone_gate_pairs(campaign),
            {"three_zone_gate_v1": (producer, consumer)},
        )

    def test_segmented_rings_reject_prefix_n100_selection(self) -> None:
        producer, consumer = _rows()
        for row in (producer, consumer):
            row["single_flight_layout_profile_id"] = (
                "three_zone_t5_primary_shaping_rings_1p4_v1"
            )
            row["architecture_generation_id"] = (
                "three_zone_t5_frozen_primary_shaping_rings_1p4_v1"
            )
        campaign = {"schema_version": 6, "experiments": [producer, consumer]}

        with self.assertRaisesRegex(ContractError, "layout, architecture, or N=100"):
            _three_zone_gate_pairs(campaign)

    def test_generated_simulation_id_digest_is_checked_before_execution(self) -> None:
        producer, consumer = _rows()
        consumer["single_flight_population"]["execution_population"][
            "ordered_particle_id_sha256"
        ] = "0" * 64
        campaign = {"schema_version": 6, "experiments": [producer, consumer]}

        with self.assertRaisesRegex(ContractError, "population or ordered selection"):
            _three_zone_gate_pairs(campaign)

    def test_both_pair_run_ids_are_calendar_validated(self) -> None:
        producer, consumer = _rows()
        consumer["run_id"] = "20260817_236000__sim__cross__invalid-time__n100"
        campaign = {"schema_version": 6, "experiments": [producer, consumer]}

        with self.assertRaisesRegex(ContractError, "run_id is invalid"):
            _three_zone_gate_pairs(campaign)

    def test_pair_requires_exact_frozen_n1_to_n100_relationship(self) -> None:
        producer, consumer = _rows()
        campaign = {"schema_version": 6, "experiments": [producer, consumer]}
        self.assertEqual(
            _three_zone_gate_pairs(campaign),
            {"three_zone_gate_v1": (producer, consumer)},
        )
        # N=1 preflight has no predecessor artifact or receipt dependency.
        self.assertNotIn("predecessor_experiment_id", producer["three_zone_solver_gate"])
        consumer["single_flight_time_integration_profile_id"] = "dt320"
        with self.assertRaisesRegex(ContractError, "differ beyond"):
            _three_zone_gate_pairs(campaign)

    def test_multiple_pairs_are_grouped_by_gate_id(self) -> None:
        producer_c, consumer_c = _rows()
        producer_d = json.loads(json.dumps(producer_c))
        consumer_d = json.loads(json.dumps(consumer_c))
        producer_d.update({
            "sequence": 3,
            "experiment_id": "three_zone_d_n1",
            "run_id": "20260817_192000__sim__cross__three-zone-d-n1__n1",
        })
        producer_d["three_zone_solver_gate"]["gate_id"] = "three_zone_gate_d_v1"
        consumer_d.update({
            "sequence": 4,
            "experiment_id": "three_zone_d_n100",
            "run_id": "20260817_193000__sim__cross__three-zone-d-n100__n100",
        })
        consumer_d["three_zone_solver_gate"].update({
            "gate_id": "three_zone_gate_d_v1",
            "predecessor_experiment_id": "three_zone_d_n1",
        })
        pairs = _three_zone_gate_pairs({
            "schema_version": 6,
            "experiments": [producer_c, producer_d, consumer_c, consumer_d],
        })

        self.assertEqual(
            pairs,
            {
                "three_zone_gate_v1": (producer_c, consumer_c),
                "three_zone_gate_d_v1": (producer_d, consumer_d),
            },
        )

    def test_each_group_requires_exactly_one_complete_pair(self) -> None:
        producer, consumer = _rows()
        orphan = json.loads(json.dumps(producer))
        orphan.update({
            "sequence": 3,
            "experiment_id": "orphan_n1",
            "run_id": "20260817_192000__sim__cross__orphan-n1__n1",
        })
        orphan["three_zone_solver_gate"]["gate_id"] = "orphan_gate_v1"

        with self.assertRaisesRegex(ContractError, "each three-zone solver gate"):
            _three_zone_gate_pairs({
                "schema_version": 6,
                "experiments": [producer, consumer, orphan],
            })

    def test_observed_projection_pairs_differ_only_by_arm_and_run_identity(self) -> None:
        producer_c, consumer_c = _rows()
        for row in (producer_c, consumer_c):
            row["observed_pre_pulse_projection"] = _observed_projection(
                "observed_z_vz_energy_transverse_collapsed"
            )
        producer_d = json.loads(json.dumps(producer_c))
        consumer_d = json.loads(json.dumps(consumer_c))
        for row in (producer_d, consumer_d):
            row["observed_pre_pulse_projection"]["arm_id"] = "full_observed_6d"
        producer_d.update({
            "sequence": 3,
            "experiment_id": "three_zone_d_n1",
            "run_id": "20260817_192000__sim__cross__three-zone-d-n1__n1",
        })
        producer_d["three_zone_solver_gate"]["gate_id"] = "three_zone_gate_d_v1"
        consumer_d.update({
            "sequence": 4,
            "experiment_id": "three_zone_d_n100",
            "run_id": "20260817_193000__sim__cross__three-zone-d-n100__n100",
        })
        consumer_d["three_zone_solver_gate"].update({
            "gate_id": "three_zone_gate_d_v1",
            "predecessor_experiment_id": "three_zone_d_n1",
        })
        campaign = {
            "schema_version": 6,
            "experiments": [producer_c, producer_d, consumer_c, consumer_d],
        }

        pairs = _three_zone_gate_pairs(campaign)
        self.assertEqual(set(pairs), {"three_zone_gate_v1", "three_zone_gate_d_v1"})
        for row in (producer_d, consumer_d):
            row["observed_pre_pulse_projection"]["observed_state"]["sha256"] = (
                "9" * 64
            )
        with self.assertRaisesRegex(ContractError, "differ beyond arm"):
            _three_zone_gate_pairs(campaign)

    def test_affine_and_observed_fixed_energy_pairs_form_one_complete_ab_set(
        self,
    ) -> None:
        producer_a, consumer_a = _rows()
        for row in (producer_a, consumer_a):
            row["observed_pre_pulse_projection"] = _observed_projection(
                "affine_zvz_fixed_10eV_transverse_collapsed"
            )
        producer_b = json.loads(json.dumps(producer_a))
        consumer_b = json.loads(json.dumps(consumer_a))
        for row in (producer_b, consumer_b):
            row["observed_pre_pulse_projection"]["arm_id"] = (
                "observed_zvz_fixed_10eV_transverse_collapsed"
            )
        producer_b.update({
            "sequence": 3,
            "experiment_id": "three_zone_b_n1",
            "run_id": "20260817_192000__sim__cross__three-zone-b-n1__n1",
        })
        producer_b["three_zone_solver_gate"]["gate_id"] = "three_zone_gate_b_v1"
        consumer_b.update({
            "sequence": 4,
            "experiment_id": "three_zone_b_n100",
            "run_id": "20260817_193000__sim__cross__three-zone-b-n100__n100",
        })
        consumer_b["three_zone_solver_gate"].update({
            "gate_id": "three_zone_gate_b_v1",
            "predecessor_experiment_id": "three_zone_b_n1",
        })
        campaign = {
            "schema_version": 6,
            "experiments": [producer_a, consumer_a, producer_b, consumer_b],
        }

        pairs = _three_zone_gate_pairs(campaign)
        self.assertEqual(set(pairs), {"three_zone_gate_v1", "three_zone_gate_b_v1"})
        for row in (producer_b, consumer_b):
            row["observed_pre_pulse_projection"]["arm_id"] = (
                "affine_zvz_fixed_10eV_transverse_collapsed"
            )
        with self.assertRaisesRegex(ContractError, "unique complete"):
            _three_zone_gate_pairs(campaign)

    def test_prepare_validator_closes_four_arm_projection_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = ObservedPrePulseProjectionTests()._fixture(Path(directory))
            authority = {
                "mean_velocity_z_m_per_s": -2.9323518410018137,
                "velocity_z_slope_m_per_s_per_mm": 228.80604377795845,
                "center_z_mm": -61.0,
            }
            receipt = project_observed_pre_pulse_states(
                authority_manifest_path=paths["manifest.json"],
                prepared_arms_path=paths["prepared.json"],
                observed_state_path=paths["observed.csv"],
                old_geometry_path=paths["geometry.json"],
                current_target_path=paths["target.csv"],
                current_subset_receipt_path=paths["subset.json"],
                full_output_path=paths["full.csv"],
                collapsed_output_path=paths["collapsed.csv"],
                receipt_output_path=paths["receipt.json"],
                affine_fixed_10ev_output_path=paths["affine.csv"],
                observed_fixed_10ev_output_path=paths["observed_fixed.csv"],
                affine_mean_velocity_z_m_per_s=authority[
                    "mean_velocity_z_m_per_s"
                ],
                affine_velocity_z_slope_m_per_s_per_mm=authority[
                    "velocity_z_slope_m_per_s_per_mm"
                ],
                affine_center_z_mm=authority["center_z_mm"],
                fixed_kinetic_energy_eV=10.0,
            )
            validation = _validate_observed_pre_pulse_projection(
                receipt=receipt,
                receipt_path=paths["receipt.json"],
                selected_arm=ARM_AFFINE_FIXED_10EV,
                selected_path=paths["affine.csv"],
                full_path=paths["full.csv"],
                collapsed_path=paths["collapsed.csv"],
                affine_fixed_10ev_path=paths["affine.csv"],
                observed_fixed_10ev_path=paths["observed_fixed.csv"],
                current_target_path=paths["target.csv"],
                current_subset_receipt_path=paths["subset.json"],
                pulse_time_us=44.0,
                affine_authority=authority,
                fixed_kinetic_energy_eV=10.0,
            )
            self.assertEqual(validation["projection_arm_id"], ARM_AFFINE_FIXED_10EV)
            receipt["invariants"]["fixed_10eV_arms_energy_equal"] = False
            with self.assertRaisesRegex(ContractError, "receipt is invalid"):
                _validate_observed_pre_pulse_projection(
                    receipt=receipt,
                    receipt_path=paths["receipt.json"],
                    selected_arm=ARM_AFFINE_FIXED_10EV,
                    selected_path=paths["affine.csv"],
                    full_path=paths["full.csv"],
                    collapsed_path=paths["collapsed.csv"],
                    affine_fixed_10ev_path=paths["affine.csv"],
                    observed_fixed_10ev_path=paths["observed_fixed.csv"],
                    current_target_path=paths["target.csv"],
                    current_subset_receipt_path=paths["subset.json"],
                    pulse_time_us=44.0,
                    affine_authority=authority,
                    fixed_kinetic_energy_eV=10.0,
                )
            receipt["invariants"]["fixed_10eV_arms_energy_equal"] = True
            with paths["affine.csv"].open(
                encoding="utf-8", newline=""
            ) as handle:
                affine_rows = list(csv.DictReader(handle))
            affine_rows[0]["charge_state"] = "2"
            with paths["affine.csv"].open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(affine_rows[0]), lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(affine_rows)
            receipt["arms"][ARM_AFFINE_FIXED_10EV]["sha256"] = file_sha256(
                paths["affine.csv"]
            )
            with self.assertRaisesRegex(ContractError, "species"):
                _validate_observed_pre_pulse_projection(
                    receipt=receipt,
                    receipt_path=paths["receipt.json"],
                    selected_arm=ARM_AFFINE_FIXED_10EV,
                    selected_path=paths["affine.csv"],
                    full_path=paths["full.csv"],
                    collapsed_path=paths["collapsed.csv"],
                    affine_fixed_10ev_path=paths["affine.csv"],
                    observed_fixed_10ev_path=paths["observed_fixed.csv"],
                    current_target_path=paths["target.csv"],
                    current_subset_receipt_path=paths["subset.json"],
                    pulse_time_us=44.0,
                    affine_authority=authority,
                    fixed_kinetic_energy_eV=10.0,
                )

    def test_prepare_validator_keeps_legacy_cd_v1_receipt_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = ObservedPrePulseProjectionTests()._fixture(Path(directory))
            receipt = project_observed_pre_pulse_states(
                authority_manifest_path=paths["manifest.json"],
                prepared_arms_path=paths["prepared.json"],
                observed_state_path=paths["observed.csv"],
                old_geometry_path=paths["geometry.json"],
                current_target_path=paths["target.csv"],
                current_subset_receipt_path=paths["subset.json"],
                full_output_path=paths["full.csv"],
                collapsed_output_path=paths["collapsed.csv"],
                receipt_output_path=paths["receipt.json"],
            )
            validation = _validate_observed_pre_pulse_projection(
                receipt=receipt,
                receipt_path=paths["receipt.json"],
                selected_arm=ARM_COLLAPSED,
                selected_path=paths["collapsed.csv"],
                full_path=paths["full.csv"],
                collapsed_path=paths["collapsed.csv"],
                affine_fixed_10ev_path=None,
                observed_fixed_10ev_path=None,
                current_target_path=paths["target.csv"],
                current_subset_receipt_path=paths["subset.json"],
                pulse_time_us=44.0,
                affine_authority=None,
                fixed_kinetic_energy_eV=None,
            )
            self.assertEqual(validation["projection_arm_id"], ARM_COLLAPSED)

    def test_n100_consumes_only_parent_bound_pass_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            producer, consumer = _rows()
            campaign = {
                "schema_version": 6,
                "campaign_id": "three_zone_gate_campaign",
                "experiments": [producer, consumer],
            }
            campaign_path = workspace / "simulation_repo/campaign.json"
            _write(campaign_path, campaign)
            source_identity = {"source_branch_id": "simion", "sha256": "B" * 64}
            layout = {
                "topology_id": "three_zone_accelerator_ideal_v1",
                "geometry_id": "three_zone_focus_origin_planes_v1",
                "frontend_electrode_topology_id": "three_zone_frontend_v1",
            }
            field = {"field_id": "three_zone_refined_pa_field_v1"}
            region = {"semantic_sha256": "C" * 64}
            identities = {
                "candidate_sha256": "A" * 64,
                "layout_profile_id": "three_zone_t5_primary_v1",
                "architecture_generation_id": "three_zone_t5_frozen_primary_v1",
                "topology_id": layout["topology_id"],
                "geometry_id": layout["geometry_id"],
                "frontend_electrode_topology_id": layout["frontend_electrode_topology_id"],
                "accelerator_field_profile_id": "accelerator_real_three_zone_pa_real_reflectron",
                "field_id": field["field_id"],
                "resolved_region_field_semantic_sha256": "C" * 64,
                "source_identity_sha256": _canonical_sha256(source_identity),
            }
            receipt = {
                "schema_version": 1,
                "role": "rf_oatof_three_zone_n1_solver_authorization_receipt",
                "gate_id": "three_zone_gate_v1",
                "decision": "PASS",
                "authorization_status": "N100_SOLVER_AUTHORIZED",
                "campaign": {"campaign_id": campaign["campaign_id"], "campaign_sha256": repository_text_sha256(campaign_path)},
                "producer": {
                    "experiment_id": producer["experiment_id"],
                    "experiment_row_sha256": _canonical_sha256(producer),
                    "integration_run_id": producer["run_id"],
                    "transport_run_id": "child",
                    "transport_manifest": {"path": "artifacts/child.json", "bytes": 1, "sha256": "D" * 64},
                },
                "authorized_successor": {
                    "experiment_id": consumer["experiment_id"],
                    "experiment_row_sha256": _canonical_sha256(consumer),
                    "particle_count": 100,
                },
                "identities": identities,
                "evidence": {
                    "summary": {"path": "artifacts/summary.json", "bytes": 1, "sha256": "E" * 64},
                    "checkpoints": {"path": "artifacts/checkpoints.csv", "bytes": 1, "sha256": "F" * 64},
                    "particle_id": 500,
                    "census": {key: 1 for key in (
                        "launched", "accelerator_grid1_forward", "accelerator_intermediate2_forward",
                        "local_accelerator_exit", "reflectron_entrance_forward", "reflectron_turning_point",
                        "reflectron_exit_return", "detector_crossing",
                    )},
                    "required_event_sequence": [
                        "source_release", "pre_pulse_state",
                        "accelerator_grid1_forward", "accelerator_intermediate2_forward",
                        "local_accelerator_exit", "reflectron_entrance_forward",
                        "reflectron_turning_point", "reflectron_exit_return", "detector_crossing",
                    ],
                },
                "failure_codes": [],
                "claim_limit": "functional authorization only",
                "formal_gate_passed": False,
            }
            run = workspace / "artifacts/projects" / INTEGRATION_ID / "runs" / producer["run_id"]
            run_config = run / "run_config.json"
            receipt_path = run / "results/three_zone_n1_solver_authorization_receipt.json"
            _write(run_config, {"role": "simulation_run_config"})
            _write(receipt_path, receipt)
            manifest_path = run / "run_manifest.json"
            manifest = {
                "role": "simulation_run_manifest", "status": "success",
                "run_id": producer["run_id"], "project": INTEGRATION_ID,
                "mode": "multipole_family_source_closure", "formal_eligible": False,
                "run_config": _record(run_config, run), "inputs": {},
                "outputs": [_record(receipt_path, run)],
            }
            _write(manifest_path, manifest)
            frozen = _resolve_three_zone_n1_authorization(
                workspace=workspace, campaign=campaign, campaign_path=campaign_path,
                producer=producer, consumer=consumer, source_identity=source_identity,
                layout_profile=layout, selected_field_profile=field,
                resolved_region_field_contract=region,
            )
            self.assertEqual(frozen["three_zone_n1_authorization_receipt_sha256"], file_sha256(receipt_path))
            self.assertEqual(frozen["three_zone_source_identity_sha256"], identities["source_identity_sha256"])

            receipt["decision"] = "FAIL"
            receipt["authorization_status"] = "N100_SOLVER_NOT_AUTHORIZED"
            receipt["failure_codes"] = ["DETECTOR_STATUS"]
            _write(receipt_path, receipt)
            with self.assertRaisesRegex(ContractError, "manifest verification failed"):
                _resolve_three_zone_n1_authorization(
                    workspace=workspace, campaign=campaign, campaign_path=campaign_path,
                    producer=producer, consumer=consumer, source_identity=source_identity,
                    layout_profile=layout, selected_field_profile=field,
                    resolved_region_field_contract=region,
                )
            manifest["outputs"] = [_record(receipt_path, run)]
            _write(manifest_path, manifest)
            with self.assertRaisesRegex(ContractError, "identity or decision"):
                _resolve_three_zone_n1_authorization(
                    workspace=workspace, campaign=campaign, campaign_path=campaign_path,
                    producer=producer, consumer=consumer, source_identity=source_identity,
                    layout_profile=layout, selected_field_profile=field,
                    resolved_region_field_contract=region,
                )
            manifest_path.unlink()
            with self.assertRaisesRegex(ContractError, "parent manifest is missing"):
                _resolve_three_zone_n1_authorization(
                    workspace=workspace, campaign=campaign, campaign_path=campaign_path,
                    producer=producer, consumer=consumer, source_identity=source_identity,
                    layout_profile=layout, selected_field_profile=field,
                    resolved_region_field_contract=region,
                )


if __name__ == "__main__":
    unittest.main()
