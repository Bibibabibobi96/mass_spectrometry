from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_grid_voltage_correction import (
    _native_gamma_trace,
    _solve_corrected_l0_slice,
    constrained_secant_update,
    decompose_l0_l1_correction,
    rank_one_secant_update,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class FixedGridVoltageCorrectionTests(unittest.TestCase):
    def test_independent_corrected_l0_slice_closes_three_equations(self) -> None:
        def linear_slopes(_basis, voltages, _energies, _step):
            return np.asarray(voltages[:3], dtype=float) - np.asarray([1.0, -2.0, 3.0])

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "mirror_fixed_grid_voltage_correction.normalized_slopes",
            side_effect=linear_slopes,
        ):
            trial = _solve_corrected_l0_slice(
                object(), (3900.0, 4000.0, 4100.0), 1.0, np.zeros(3),
                np.full(4, -10.0), np.full(4, 10.0), np.zeros(3),
                1e-4, 1e-12, 120, 1e-10, 4.0,
            )
        np.testing.assert_allclose(trial, [1.0, -2.0, 3.0, 4.0], atol=1e-10)

    def test_native_l1_trace_requires_the_frozen_native_probe_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe_path = root / "native_probe.json"
            probe_path.write_text(json.dumps({
                "role": "mrtof_native_simion_transverse_l1_probe",
                "status": "prepared",
                "nominal_energy_ev": 4000.0,
            }), encoding="utf-8")
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            probe["_path"] = str(probe_path)
            native = {
                "role": "mrtof_native_simion_transverse_l1_analysis",
                "status": "native_l1_diagnostic_complete",
                "source_native_l1_probe_contract_sha256": file_sha256(probe_path),
                "nominal_energy_ev": 4000.0,
                "directions": {
                    "-1": {"stable": True, "trace_half": -0.001},
                    "1": {"stable": True, "trace_half": 0.003},
                },
            }
            self.assertAlmostEqual(_native_gamma_trace(native, probe, 4000.0), 0.001)
            native["source_native_l1_probe_contract_sha256"] = "0" * 64
            with self.assertRaisesRegex(CandidateContractError, "identity"):
                _native_gamma_trace(native, probe, 4000.0)

    def test_l0_is_closed_before_l1_moves_along_null_space(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 2.0, 0.0, -1.0],
            [0.0, 0.0, 4.0, 0.5],
        ])
        gamma = np.array([0.5, -0.25, 0.75, 1.0])
        slopes = np.array([0.1, -0.2, 0.3])
        trace = -0.4
        result = decompose_l0_l1_correction(jacobian, gamma, slopes, trace)
        delta = np.asarray(result["voltage_correction_v"])
        np.testing.assert_allclose(slopes + jacobian @ delta, 0.0, atol=1e-12)
        self.assertAlmostEqual(trace + float(gamma @ delta), 0.0, places=12)
        self.assertEqual(result["l0_jacobian_rank"], 3)
        self.assertEqual(result["l0_family_nullity"], 1)
        self.assertEqual(result["augmented_jacobian_rank"], 4)

    def test_rank_deficient_l0_fails_closed(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "rank three"):
            decompose_l0_l1_correction(
                [[1.0, 0.0, 0.0, 0.0]] * 3,
                [0.0, 0.0, 0.0, 1.0],
                [0.0, 0.0, 0.0],
                0.0,
            )

    def test_gamma_stationary_on_l0_family_fails_closed(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        with self.assertRaisesRegex(CandidateContractError, "stationary"):
            decompose_l0_l1_correction(
                jacobian,
                [1.0, 1.0, 1.0, 0.0],
                [0.0, 0.0, 0.0],
                0.1,
            )

    def test_rank_one_secant_update_satisfies_matrix_chord(self) -> None:
        jacobian = np.array([
            [1.0, 2.0, 0.0, -1.0],
            [0.0, 1.0, 3.0, 0.5],
            [2.0, 0.0, -1.0, 1.0],
        ])
        step = np.array([2.0, -1.0, 0.5, 3.0])
        observed = np.array([0.25, -0.5, 1.5])
        updated = rank_one_secant_update(jacobian, step, observed)
        np.testing.assert_allclose(updated @ step, observed, atol=1e-12)
        self.assertEqual(np.linalg.matrix_rank(updated), 3)

    def test_rank_one_secant_update_supports_gradient(self) -> None:
        gradient = np.array([1.0, -2.0, 0.5, 4.0])
        step = np.array([1.0, 2.0, -1.0, 0.25])
        updated = rank_one_secant_update(gradient, step, np.asarray(0.75))
        self.assertAlmostEqual(float(updated @ step), 0.75, places=12)

    def test_rank_one_secant_update_rejects_zero_chord(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "zero"):
            rank_one_secant_update(np.eye(3, 4), np.zeros(4), np.ones(3))

    def test_constrained_update_preserves_first_chord_and_adds_second(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        first = np.array([1.0, 2.0, 0.0, 0.0])
        second = np.array([0.5, -1.0, 2.0, 1.0])
        first_response = jacobian @ first
        second_response = np.array([0.2, -0.3, 0.4])
        updated = constrained_secant_update(
            jacobian, [first], second, second_response,
        )
        np.testing.assert_allclose(updated @ first, first_response, atol=1e-12)
        np.testing.assert_allclose(updated @ second, second_response, atol=1e-12)

    def test_constrained_update_rejects_redundant_direction(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "no independent"):
            constrained_secant_update(
                np.eye(3, 4), [[1.0, 0.0, 0.0, 0.0]],
                [2.0, 0.0, 0.0, 0.0], [1.0, 2.0, 3.0],
            )

    def test_constrained_update_preserves_two_chords_and_adds_third(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        first = np.array([1.0, 0.5, 0.0, 0.0])
        second = np.array([0.0, 1.0, 2.0, 0.0])
        third = np.array([0.25, -0.5, 1.0, 2.0])
        first_response = jacobian @ first
        second_response = jacobian @ second
        third_response = np.array([-0.2, 0.4, 0.7])
        updated = constrained_secant_update(
            jacobian, [first, second], third, third_response,
        )
        np.testing.assert_allclose(updated @ first, first_response, atol=1e-12)
        np.testing.assert_allclose(updated @ second, second_response, atol=1e-12)
        np.testing.assert_allclose(updated @ third, third_response, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
