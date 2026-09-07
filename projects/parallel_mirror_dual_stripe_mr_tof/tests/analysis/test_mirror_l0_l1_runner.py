"""Contract tests for the managed mirror L0-to-L1 Candidate workflow."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0_l1_run_summary import (
    GAMMA_SELECTION_STATUS,
    L0_STATUS,
    L1_STATUS,
    validate_and_summarize,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"
RUNNER = PROJECT / "analysis" / "run_mirror_l0_l1_candidate.ps1"


class MirrorL0L1RunnerTests(unittest.TestCase):
    def _receipts(self, root: Path) -> tuple[Path, Path]:
        contract_sha = file_sha256(CONTRACT)
        l0 = root / "l0.json"
        l0.write_text(
            json.dumps(
                {
                    "status": L0_STATUS,
                    "input": {"contract_sha256": contract_sha, "actual_parallel_workers": 12},
                    "parallel_restart_search": {
                        "restart_count": 36,
                        "accepted_l0_restart_indices": [2, 7],
                    },
                }
            ),
            encoding="utf-8",
        )
        l1 = root / "l1.json"
        l1.write_text(
            json.dumps(
                {
                    "status": L1_STATUS,
                    "input": {
                        "contract": {"sha256": contract_sha},
                        "l0_receipt": {"sha256": file_sha256(l0)},
                    },
                    "l0_accepted_count": 2,
                    "l1_stable_count": 1,
                    "gamma_target_continuation": {
                        "status": GAMMA_SELECTION_STATUS,
                        "gamma_residual_degrees": 2e-8,
                        "maximum_gamma_residual_degrees": 0.001,
                        "l0_receipt": {
                            "electrode_voltages_v": [0.0, -5000.0, 3800.0, 5400.0, 7500.0],
                            "normalized_period_slopes_per_v": [2e-9, -4e-9, 3e-9],
                            "maximum_abs_normalized_period_slope_per_v": 1e-7,
                        },
                        "l1_screen": {"nominal_mapping": {"gamma_degrees": 90.00000002}},
                    },
                    "gamma_target_probe_convergence": {
                        "status": "pass",
                        "last_adjacent_gamma_change_degrees": 0.0004,
                        "last_adjacent_relative_Tbar_change": 0.006,
                    },
                }
            ),
            encoding="utf-8",
        )
        return l0, l1

    def test_summary_accepts_a_bound_converged_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            l0, l1 = self._receipts(Path(temporary))
            result = validate_and_summarize(CONTRACT, l0, l1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["search"]["restart_count"], 36)
        self.assertEqual(result["selected_mirror_voltages_v"]["D"], 5400.0)
        self.assertEqual(result["selected_mirror_voltages_v"]["E"], 7500.0)

    def test_summary_rejects_a_receipt_that_does_not_bind_l0(self) -> None:
        with TemporaryDirectory() as temporary:
            l0, l1 = self._receipts(Path(temporary))
            document = json.loads(l1.read_text(encoding="utf-8"))
            document["input"]["l0_receipt"]["sha256"] = "0" * 64
            l1.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "does not bind"):
                validate_and_summarize(CONTRACT, l0, l1)

    def test_summary_rejects_failed_probe_convergence(self) -> None:
        with TemporaryDirectory() as temporary:
            l0, l1 = self._receipts(Path(temporary))
            document = json.loads(l1.read_text(encoding="utf-8"))
            document["gamma_target_probe_convergence"]["status"] = "fail"
            l1.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "probe convergence"):
                validate_and_summarize(CONTRACT, l0, l1)

    def test_runner_reuses_the_common_managed_run_contract(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "New-RunPackage",
            "Copy-VerifiedRunInput",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "mirror_l0_hardware_candidate",
            "mirror_l0_l1_hardware_candidate",
            "mirror_l0_l1_run_summary",
            "Assert-FrozenSourcesUnchanged",
        ):
            self.assertIn(token, source)
        self.assertEqual(source.count("Complete-FailedRun"), 2)
        self.assertNotIn("SIMION", source)
        self.assertNotIn("Refine", source)


if __name__ == "__main__":
    unittest.main()
