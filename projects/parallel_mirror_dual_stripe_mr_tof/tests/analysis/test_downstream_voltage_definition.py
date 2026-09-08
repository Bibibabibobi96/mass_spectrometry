from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_voltage_definition import (
    audit_downstream_definition,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class DownstreamVoltageDefinitionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contract = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _record(path: Path) -> dict[str, object]:
        return {
            "path": str(path), "exists": True, "bytes": path.stat().st_size,
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
        summary.write_text(json.dumps({
            "transport_status": "full_drift_observed",
            "stripe_biases_v": parameters[:2],
            "prism_voltages_v": parameters[2:],
            "residuals": dict(zip(names, residuals)),
        }), encoding="utf-8")
        materialization = results / "two_prism_trial_materialization.json"
        materialization.write_text(json.dumps({
            "inputs": {"contract_sha256": "same"},
            "mirror_voltages_v": [0, 1, 2, 3, 4],
            "target_slow_turn_y_mm": 340.0,
            "target_oscillation_count": 25,
            "target_turn_y_mm": 0.0,
            "target_slow_kinetic_energy_per_charge_v": 5.0,
            "particle_mass_th": 524.0,
            "charge_state": 1,
        }), encoding="utf-8")
        manifest = run / "run_manifest.json"
        manifest.write_text(json.dumps({
            "status": "success",
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial",
            "run_id": name,
            "run_config": self._record(run_config),
            "outputs": [self._record(summary), self._record(materialization)],
        }), encoding="utf-8")
        return manifest

    def test_classifies_full_rank_square_system_without_accepting_step(self) -> None:
        baseline = self._trial("base", [-50, 100, 180, -180], [1, 2, 3, 4])
        axes = [
            self._trial("s1", [-49.8, 100, 180, -180], [1.2, 2, 3, 4]),
            self._trial("s2", [-50, 100.2, 180, -180], [1, 2.2, 3, 4]),
            self._trial("p1", [-50, 100, 180.2, -180], [1, 2, 3.2, 4]),
            self._trial("p2", [-50, 100, 180, -179.8], [1, 2, 3, 4.2]),
        ]
        result = audit_downstream_definition(
            contract_path=self.contract, baseline_manifest=baseline, axis_manifests=axes
        )
        self.assertEqual(result["classification"]["status"], "square_exact")
        self.assertEqual(result["classification"]["nullity"], 0)
        self.assertIn("not_executed", result["iteration_status"])

    def test_rejects_mixed_axis(self) -> None:
        baseline = self._trial("base", [-50, 100, 180, -180], [1, 2, 3, 4])
        axes = [
            self._trial("s1", [-49.8, 100.1, 180, -180], [1.2, 2, 3, 4]),
            self._trial("s2", [-50, 100.2, 180, -180], [1, 2.2, 3, 4]),
            self._trial("p1", [-50, 100, 180.2, -180], [1, 2, 3.2, 4]),
            self._trial("p2", [-50, 100, 180, -179.8], [1, 2, 3, 4.2]),
        ]
        with self.assertRaises(CandidateContractError):
            audit_downstream_definition(
                contract_path=self.contract, baseline_manifest=baseline, axis_manifests=axes
            )


if __name__ == "__main__":
    unittest.main()
