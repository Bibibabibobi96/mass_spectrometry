from __future__ import annotations

import copy
import unittest

from common.multipole.evaluate_transport_evidence import evaluate


class TransportEvidenceTest(unittest.TestCase):
    def test_rf_metrics_are_scored_only_by_explicit_evidence(self) -> None:
        metrics = {
            "primary_case_id": "rf_on",
            "control_case_id": "zero_rf_control",
            "cases": {
                "rf_on": {"transmission_fraction": 0.9},
                "zero_rf_control": {"transmission_fraction": 0.2},
            },
        }
        evidence = {
            "schema_version": 1,
            "role": "multipole_transport_evidence_contract",
            "project_id": "fixture",
            "design_profile_id": "baseline",
            "evaluation": "rf_vs_zero_rf",
            "thresholds": {
                "minimum_primary_transmission": 0.8,
                "minimum_transmission_improvement": 0.5,
            },
        }
        self.assertEqual(
            evaluate(
                metrics,
                evidence,
                project_id="fixture",
                design_profile_id="baseline",
            )["status"],
            "PASS",
        )
        failed = copy.deepcopy(evidence)
        failed["thresholds"]["minimum_primary_transmission"] = 0.95
        self.assertEqual(
            evaluate(
                metrics,
                failed,
                project_id="fixture",
                design_profile_id="baseline",
            )["status"],
            "FAIL",
        )

    def test_evidence_identity_cannot_be_reused_for_another_profile(self) -> None:
        evidence = {
            "schema_version": 1,
            "role": "multipole_transport_evidence_contract",
            "project_id": "fixture",
            "design_profile_id": "baseline",
            "evaluation": "rf_vs_zero_rf",
            "thresholds": {
                "minimum_primary_transmission": 0.0,
                "minimum_transmission_improvement": -1.0,
            },
        }
        with self.assertRaisesRegex(ValueError, "identity differs"):
            evaluate(
                {
                    "primary_case_id": "a",
                    "control_case_id": "b",
                    "cases": {
                        "a": {"transmission_fraction": 1.0},
                        "b": {"transmission_fraction": 0.0},
                    },
                },
                evidence,
                project_id="fixture",
                design_profile_id="other",
            )

    def test_axial_evidence_requires_schema_valid_paired_metrics(self) -> None:
        evidence = {
            "schema_version": 1,
            "role": "multipole_transport_evidence_contract",
            "project_id": "fixture",
            "design_profile_id": "explicit_axial_reference",
            "evaluation": "axial_drop_vs_zero_drop",
            "thresholds": {
                "minimum_primary_transmission": 0.8,
                "minimum_mean_energy_gain_eV": 2.5,
                "maximum_mean_output_energy_error_eV": 0.5,
            },
        }
        metrics = {
            "schema_version": 1,
            "role": "multipole_paired_axial_drive_metrics",
            "status": "UNQUALIFIED",
            "project_id": "fixture",
            "parent_resolved_design_sha256": "A" * 64,
            "axial_drive_topology": "segmented_rod_axial_acceleration",
            "primary_case_id": "axial_acceleration_rf_on",
            "control_case_id": "zero_axial_drop_rf_on",
            "paired_population_policy": "intersection_of_transmitted_particle_ids",
            "particles": 100,
            "accelerated_transmitted_particles": 90,
            "control_transmitted_particles": 85,
            "paired_transmitted_particles": 82,
            "accelerated_transmission": 0.9,
            "control_transmission": 0.85,
            "mean_control_output_energy_eV": 2.0,
            "mean_accelerated_output_energy_eV": 5.0,
            "mean_energy_gain_eV": 3.0,
            "expected_axial_energy_gain_eV": 3.0,
            "paired_expected_mean_output_energy_eV": 5.0,
            "nominal_source_energy_eV": 2.0,
            "sample_source_mean_energy_eV": 2.0,
            "source_model_predicted_mean_energy_eV": None,
            "nominal_predicted_output_energy_eV": 5.0,
            "absolute_mean_output_energy_error_eV": 0.0,
            "mean_control_divergence_angle_deg": 1.0,
            "mean_accelerated_divergence_angle_deg": 1.2,
            "mean_divergence_change_deg": 0.2,
            "control_rms_radial_position_mm": 0.4,
            "accelerated_rms_radial_position_mm": 0.5,
            "rms_radial_position_change_mm": 0.1,
            "claim_limit": "functional only",
        }
        result = evaluate(
            metrics,
            evidence,
            project_id="fixture",
            design_profile_id="explicit_axial_reference",
        )
        self.assertEqual(result["status"], "PASS")
        invalid = copy.deepcopy(metrics)
        del invalid["paired_population_policy"]
        with self.assertRaises(Exception):
            evaluate(
                invalid,
                evidence,
                project_id="fixture",
                design_profile_id="explicit_axial_reference",
            )


if __name__ == "__main__":
    unittest.main()
