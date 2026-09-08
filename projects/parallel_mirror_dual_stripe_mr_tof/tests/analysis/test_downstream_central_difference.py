from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_central_difference import (
    audit_central_difference,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class DownstreamCentralDifferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contract = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _record(path: Path) -> dict[str, object]:
        return {
            "path": str(path),
            "exists": True,
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }

    def _trial(self, name: str, parameters: list[float], residuals: list[float]) -> Path:
        run = self.root / name
        results = run / "results"
        results.mkdir(parents=True)
        run_config = run / "run_config.json"
        run_config.write_text("{}\n", encoding="utf-8")
        summary = run / "summary.json"
        names = (
            "P1_P2_phase_origin_turn_y_mm",
            "P1_P2_slow_kinetic_energy_per_charge_v",
            "Stripe_slow_turn_y_minus_L_mm",
            "Stripe_fractional_K_minus_target",
        )
        summary.write_text(
            json.dumps(
                {
                    "transport_status": "full_drift_observed",
                    "stripe_biases_v": parameters[:2],
                    "prism_voltages_v": parameters[2:],
                    "residuals": dict(zip(names, residuals)),
                }
            ),
            encoding="utf-8",
        )
        materialization = results / "two_prism_trial_materialization.json"
        materialization.write_text(
            json.dumps(
                {
                    "inputs": {"contract_sha256": "same"},
                    "mirror_voltages_v": [0, 1, 2, 3, 4],
                    "target_slow_turn_y_mm": 340.0,
                    "target_oscillation_count": 25,
                    "target_turn_y_mm": 0.0,
                    "target_slow_kinetic_energy_per_charge_v": 5.0,
                    "particle_mass_th": 524.0,
                    "charge_state": 1,
                }
            ),
            encoding="utf-8",
        )
        manifest = run / "run_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "status": "success",
                    "project": "parallel_mirror_dual_stripe_mr_tof",
                    "mode": "finite_3d_two_prism_voltage_trial",
                    "run_id": name,
                    "run_config": self._record(run_config),
                    "outputs": [self._record(summary), self._record(materialization)],
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_reports_exact_central_jacobian_and_effective_response(self) -> None:
        p0 = [-50.0, 100.0, 180.0, -180.0]
        r0 = [1.0, 2.0, 3.0, 4.0]
        matrix = [
            [1.0, 0.0, 2.0, 0.0],
            [0.0, 1.0, 0.0, 2.0],
            [2.0, 0.0, 1.0, 0.0],
            [0.0, 3.0, 0.0, 1.0],
        ]
        baseline = self._trial("base", p0, r0)
        plus: list[Path] = []
        minus: list[Path] = []
        for column in range(4):
            pp = p0.copy(); pp[column] += 0.02
            pm = p0.copy(); pm[column] -= 0.02
            rp = [r0[row] + 0.02 * matrix[row][column] for row in range(4)]
            rm = [r0[row] - 0.02 * matrix[row][column] for row in range(4)]
            plus.append(self._trial(f"plus{column}", pp, rp))
            minus.append(self._trial(f"minus{column}", pm, rm))
        result = audit_central_difference(
            contract_path=self.contract,
            baseline_manifest=baseline,
            plus_manifests=plus,
            minus_manifests=minus,
        )
        self.assertEqual(result["classifications"]["central"]["status"], "square_exact")
        np.testing.assert_allclose(result["physical_jacobians"]["central"], matrix)
        self.assertEqual(result["effective_two_stripe_responses"]["central"]["status"], "evaluated")
        self.assertTrue(
            all(
                item["relative_to_scaled_central_column_norm_2"] < 1e-10
                for item in result["scaled_forward_backward_column_disagreement"]
            )
        )
        self.assertIn("not_executed", result["iteration_status"])

    def test_rejects_asymmetric_pair(self) -> None:
        p0 = [-50.0, 100.0, 180.0, -180.0]
        r0 = [1.0, 2.0, 3.0, 4.0]
        baseline = self._trial("base", p0, r0)
        plus: list[Path] = []
        minus: list[Path] = []
        for column in range(4):
            pp = p0.copy(); pp[column] += 0.02
            pm = p0.copy(); pm[column] -= 0.02 if column else 0.03
            plus.append(self._trial(f"plus{column}", pp, r0))
            minus.append(self._trial(f"minus{column}", pm, r0))
        with self.assertRaises(CandidateContractError):
            audit_central_difference(
                contract_path=self.contract,
                baseline_manifest=baseline,
                plus_manifests=plus,
                minus_manifests=minus,
            )

    def test_rejects_wrong_negative_axis(self) -> None:
        p0 = [-50.0, 100.0, 180.0, -180.0]
        r0 = [1.0, 2.0, 3.0, 4.0]
        baseline = self._trial("base", p0, r0)
        plus: list[Path] = []
        minus: list[Path] = []
        for column in range(4):
            pp = p0.copy(); pp[column] += 0.02
            pm = p0.copy(); pm[column] -= 0.02
            if column == 0:
                pm[1] -= 0.02
            plus.append(self._trial(f"plus{column}", pp, r0))
            minus.append(self._trial(f"minus{column}", pm, r0))
        with self.assertRaises(CandidateContractError):
            audit_central_difference(
                contract_path=self.contract,
                baseline_manifest=baseline,
                plus_manifests=plus,
                minus_manifests=minus,
            )


if __name__ == "__main__":
    unittest.main()
