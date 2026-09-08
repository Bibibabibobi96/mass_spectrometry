from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    audit_operating_point,
)


class TwoPrismOperatingPointTest(unittest.TestCase):
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

    def _trial(self, name: str, voltage: list[float], residual: list[float]) -> Path:
        run = self.root / name
        results = run / "results"
        results.mkdir(parents=True)
        run_config = run / "run_config.json"
        run_config.write_text("{}\n", encoding="utf-8")
        observation = results / "two_prism_trial_observation.json"
        observation.write_text(json.dumps({
            "status": "phase_origin_observed",
            "prism_voltages_v": voltage,
            "residuals": {
                "P1_P2_phase_origin_turn_y_mm": residual[0],
                "P1_P2_slow_kinetic_energy_per_charge_v": residual[1],
            },
            "drift_phase_origin_state": {
                "position_mm": [0.0, residual[0], 280.0],
                "velocity_mm_per_us": [0.0, 1.0, 0.0],
            },
        }), encoding="utf-8")
        materialization = results / "two_prism_trial_materialization.json"
        materialization.write_text(json.dumps({
            "inputs": {
                "contract_sha256": "a",
                "reviewed_contract_sha256": "b",
                "mirror_summary_sha256": "c",
                "stripe_summary_sha256": "d",
                "accelerator_receipt_sha256": "e",
            },
            "target_turn_y_mm": 0.0,
            "target_slow_kinetic_energy_per_charge_v": 5.0,
            "phase_origin_mirror_side": 1,
        }), encoding="utf-8")
        manifest = run / "run_manifest.json"
        manifest.write_text(json.dumps({
            "status": "success",
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial",
            "run_id": name,
            "run_config": self._record(run_config),
            "inputs": {},
            "outputs": [self._record(observation), self._record(materialization)],
        }), encoding="utf-8")
        return manifest

    def test_audits_full_rank_jacobian_and_selects_last_iteration(self) -> None:
        seed = self._trial("seed", [100.0, -100.0], [-4.0, 0.05])
        p1 = self._trial("p1", [102.0, -100.0], [-3.6, 0.19])
        p2 = self._trial("p2", [100.0, -98.0], [-3.86, 0.18])
        final = self._trial("final", [133.0, -134.0], [1e-5, 2e-5])
        result = audit_operating_point(
            contract_path=self.contract,
            seed_manifest=seed,
            prism_1_perturbation_manifest=p1,
            prism_2_perturbation_manifest=p2,
            iteration_manifests=[final],
        )
        self.assertEqual(result["classification"]["status"], "square_exact")
        self.assertEqual(result["selected_prism_voltages_v"], [133.0, -134.0])
        self.assertEqual(result["qualification"], "single_center_phase_space_handoff_candidate__K25_pending")

    def test_rejects_mixed_frozen_problem_or_wrong_axis_perturbation(self) -> None:
        seed = self._trial("seed", [100.0, -100.0], [-4.0, 0.05])
        p1 = self._trial("p1", [102.0, -100.0], [-3.6, 0.19])
        p2 = self._trial("p2", [100.0, -98.0], [-3.86, 0.18])
        final = self._trial("final", [133.0, -134.0], [1e-5, 2e-5])
        materialization = p2.parent / "results" / "two_prism_trial_materialization.json"
        changed = json.loads(materialization.read_text(encoding="utf-8"))
        changed["phase_origin_mirror_side"] = -1
        materialization.write_text(json.dumps(changed), encoding="utf-8")
        manifest = json.loads(p2.read_text(encoding="utf-8"))
        manifest["outputs"][1] = self._record(materialization)
        p2.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(CandidateContractError):
            audit_operating_point(
                contract_path=self.contract,
                seed_manifest=seed,
                prism_1_perturbation_manifest=p1,
                prism_2_perturbation_manifest=p2,
                iteration_manifests=[final],
            )


if __name__ == "__main__":
    unittest.main()
