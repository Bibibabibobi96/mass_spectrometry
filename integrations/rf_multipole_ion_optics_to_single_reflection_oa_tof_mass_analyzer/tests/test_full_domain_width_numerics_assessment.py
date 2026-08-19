"""Regression tests for the governed full-domain five-cell assessment."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure import (
    assess_full_domain_width_numerics as assessment,
)


class PulseEffectiveClockTests(unittest.TestCase):
    def summary(self) -> dict[str, object]:
        return {
            "resolution_time_basis": assessment.EXPECTED_CLOCK,
            "detector_pulse_effective_time_basis": assessment.EXPECTED_PULSE_BASIS,
            "pulse_effective_peak": {
                "std_tof_ns": 1000.0 * 2**0.5,
                "direct_fwhm_tof_ns": 2.0,
                "mass_resolution": 12345.0,
                "significant_kde_modes": 1,
                "mean_tof_us": 10.0,
            },
            "instrument_clock_peak": {
                "std_tof_ns": 999999.0,
                "direct_fwhm_tof_ns": 999999.0,
                "mass_resolution": 999999.0,
                "significant_kde_modes": 99,
                "mean_tof_us": 999999.0,
            },
        }

    def test_uses_only_pulse_effective_peak_for_resolution(self) -> None:
        metrics = assessment._pulse_metrics(
            self.summary(), np.asarray([9.0, 11.0], dtype=float)
        )
        self.assertEqual(metrics["mass_resolution"], 12345.0)
        self.assertEqual(metrics["direct_fwhm_tof_ns"], 2.0)
        self.assertEqual(metrics["population_sigma_tof_ns"], 1000.0)
        self.assertAlmostEqual(metrics["sample_sigma_tof_ns"], 1000.0 * 2**0.5)

    def test_rejects_missing_pulse_effective_peak(self) -> None:
        summary = self.summary()
        del summary["pulse_effective_peak"]
        with self.assertRaisesRegex(ContractError, "pulse_effective_peak"):
            assessment._pulse_metrics(summary, np.asarray([9.0, 11.0]))

    def test_rejects_nonregistered_clock_basis(self) -> None:
        summary = self.summary()
        summary["resolution_time_basis"] = "canonical_instrument_time_us"
        with self.assertRaisesRegex(ContractError, "clock authority"):
            assessment._pulse_metrics(summary, np.asarray([9.0, 11.0]))


class RestartSourceReleaseGateTests(unittest.TestCase):
    def _inputs(self, directory: Path) -> tuple[Path, list[dict[str, str]]]:
        target_path = directory / "target.csv"
        fields = [
            "particle_id", "instrument_time_us", "position_x_mm", "position_y_mm",
            "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
            "kinetic_energy_eV",
        ]
        with target_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for particle_id in range(1, 1001):
                writer.writerow({
                    "particle_id": particle_id, "instrument_time_us": 1.0,
                    "position_x_mm": 2.0, "position_y_mm": 3.0,
                    "position_z_mm": 4.0, "velocity_x_m_s": 5000.0,
                    "velocity_y_m_s": 6000.0, "velocity_z_m_s": 7000.0,
                    "kinetic_energy_eV": 10.0,
                })
        actual = [{
            "particle_id": str(particle_id), "event": "source_release",
            "instrument_time_us": "1", "x_mm": "2", "y_mm": "3", "z_mm": "4",
            "vx_mm_per_us": "5", "vy_mm_per_us": "6", "vz_mm_per_us": "7",
            "kinetic_energy_eV": "10",
        } for particle_id in range(1, 1001)]
        return target_path, actual

    @staticmethod
    def _validation() -> dict[str, object]:
        return {
            "status": "PASS", "checkpoint": "source_release", "particle_count": 1000,
            "ordered_particle_ids_exact": True,
            "position_rowwise_abs_tolerance_mm": 1e-9,
            "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
            "clock_abs_tolerance_us": 1e-9, "energy_abs_tolerance_eV": 5e-9,
            "maximum_position_rowwise_abs_error_mm": 0.0,
            "maximum_velocity_rowwise_abs_error_m_per_s": 3e-7,
            "maximum_clock_abs_error_us": 0.0,
            "maximum_energy_abs_error_eV": 1e-9,
        }

    def test_accepts_finite_registered_restart_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target, actual = self._inputs(Path(directory))
            result = assessment._source_release_errors(
                target, actual, self._validation()
            )
        self.assertEqual(result["status"], "PASS")

    def test_rejects_nonfinite_registered_restart_validation(self) -> None:
        validation = self._validation()
        validation["maximum_energy_abs_error_eV"] = float("nan")
        with tempfile.TemporaryDirectory() as directory:
            target, actual = self._inputs(Path(directory))
            with self.assertRaisesRegex(ContractError, "not finite"):
                assessment._source_release_errors(target, actual, validation)

    def test_rejects_negative_registered_restart_tolerance(self) -> None:
        validation = self._validation()
        validation["energy_abs_tolerance_eV"] = -1.0
        with tempfile.TemporaryDirectory() as directory:
            target, actual = self._inputs(Path(directory))
            result = assessment._source_release_errors(target, actual, validation)
        self.assertEqual(result["status"], "FAIL")


class AssessmentClassificationTests(unittest.TestCase):
    def test_four_claim_outcomes_are_disjoint(self) -> None:
        self.assertEqual(
            assessment._claim_status(
                source_identity_passed=False, width_passed=True,
                numerical_passed=True,
            ),
            "INVALID_IDENTITY_OR_CENSUS",
        )
        self.assertEqual(
            assessment._claim_status(
                source_identity_passed=True, width_passed=False,
                numerical_passed=True,
            ),
            "WIDTH_NOT_SUPPORTED",
        )
        self.assertEqual(
            assessment._claim_status(
                source_identity_passed=True, width_passed=True,
                numerical_passed=False,
            ),
            "INCONCLUSIVE_NUMERICAL",
        )
        self.assertIn(
            "FULL_DOMAIN_PIECEWISE_IDEAL_FIELD",
            assessment._claim_status(
                source_identity_passed=True, width_passed=True,
                numerical_passed=True,
            ),
        )

    def test_registered_checkpoint_census_is_fail_closed(self) -> None:
        rows = []
        census = {"launched": 1000, "multipole_handoff": 0}
        for event in assessment.REGISTERED_CHECKPOINT_EVENTS:
            census[event] = 1000
            rows.extend(
                {"event": event, "particle_id": str(particle_id)}
                for particle_id in range(1, 1001)
            )
        result = assessment._validate_registered_checkpoint_census(
            {"census": census}, rows
        )
        self.assertEqual(result["detector_crossing"], 1000)
        rows.pop()
        with self.assertRaisesRegex(ContractError, "detector_crossing"):
            assessment._validate_registered_checkpoint_census(
                {"census": census}, rows
            )


class BatchResourceUsageTests(unittest.TestCase):
    @staticmethod
    def _record(path: Path) -> dict[str, object]:
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": assessment.file_sha256(path),
        }

    def _manifest(self, directory: Path, count: int) -> dict[str, object]:
        outputs = []
        for index in range(1, count + 1):
            path = directory / f"resource_usage__batch{index:02d}.json"
            path.write_text(
                json.dumps({
                    "status": "completed",
                    "started_at_utc": f"2026-08-19T00:00:0{index}+00:00",
                    "wall_clock_seconds": 2.0,
                    "peak_process_tree_working_set_bytes": 1024 * index,
                }),
                encoding="utf-8",
            )
            outputs.append(self._record(path))
        return {"outputs": outputs}

    def test_uses_manifest_bound_execution_batch_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = assessment._batch_resource_usage(
                self._manifest(Path(directory), 2),
                {"parameters": {
                    "execution_batch_count": 2,
                    "max_parallel_batches": 2,
                }},
            )
        self.assertEqual(result["execution_batch_count"], 2)
        self.assertEqual(result["max_parallel_batches"], 2)
        self.assertEqual(len(result["batches"]), 2)

    def test_rejects_usage_count_different_from_manifest_bound_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ContractError, "manifest-bound run_config"):
                assessment._batch_resource_usage(
                    self._manifest(Path(directory), 1),
                    {"parameters": {
                        "execution_batch_count": 2,
                        "max_parallel_batches": 2,
                    }},
                )


class SingleFlightOwnershipLineageTests(unittest.TestCase):
    upstream_project_id = "rf_octupole_ion_optics"

    def test_accepts_integration_owned_child_with_explicit_upstream_lineage(self) -> None:
        lineage = assessment._single_flight_ownership_lineage(
            child_manifest={"project": assessment.PROJECT_ID},
            child_config={
                "project": assessment.PROJECT_ID,
                "upstream_project_id": self.upstream_project_id,
            },
            expected_upstream_project_id=self.upstream_project_id,
        )
        self.assertEqual(
            lineage, "integration_owned_with_upstream_input_lineage"
        )

    def test_accepts_explicit_legacy_upstream_owned_child_read_only(self) -> None:
        lineage = assessment._single_flight_ownership_lineage(
            child_manifest={"project": self.upstream_project_id},
            child_config={
                "project": self.upstream_project_id,
                "upstream_source_identity": {
                    "project_id": self.upstream_project_id,
                },
            },
            expected_upstream_project_id=self.upstream_project_id,
        )
        self.assertEqual(
            lineage, "legacy_upstream_project_owned_single_flight_read_only"
        )

    def test_rejects_mixed_or_implicit_ownership(self) -> None:
        with self.assertRaisesRegex(ContractError, "ownership lineage"):
            assessment._single_flight_ownership_lineage(
                child_manifest={"project": assessment.PROJECT_ID},
                child_config={"project": self.upstream_project_id},
                expected_upstream_project_id=self.upstream_project_id,
            )


if __name__ == "__main__":
    unittest.main()
