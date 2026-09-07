"""Contract tests for the managed mirror L0-to-L1 Candidate workflow."""

from __future__ import annotations

import json
import shutil
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
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    MIRROR_MODE,
    MIRROR_QUALIFICATION,
    PROJECT_ID,
    load_managed_mirror_candidate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_shape_diagnostic import (
    build_diagnostic,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"
RUNNER = PROJECT / "analysis" / "run_mirror_l0_l1_candidate.ps1"
SHAPE_DIAGNOSTIC_RUNNER = PROJECT / "analysis" / "run_dual_stripe_shape_diagnostic.ps1"


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

    def test_shape_diagnostic_runner_freezes_inputs_and_uses_common_run_lifecycle(self) -> None:
        source = SHAPE_DIAGNOSTIC_RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "New-RunPackage",
            "Copy-VerifiedRunInput",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "parent_mirror_run_manifest.json",
            "dual_stripe_shape_diagnostic",
            "Test-RunFilesIdentical",
        ):
            self.assertIn(token, source)
        self.assertEqual(source.count("Complete-FailedRun"), 2)
        self.assertNotIn("SIMION", source)
        self.assertNotIn("Refine", source)

    def _managed_manifest(self, root: Path) -> Path:
        inputs = root / "inputs"
        results = root / "results"
        inputs.mkdir()
        results.mkdir()
        contract = inputs / "simion_candidate_two_zone.json"
        shutil.copyfile(CONTRACT, contract)
        l0 = results / "mirror_l0_family_receipt.json"
        l1 = results / "mirror_l0_l1_candidate_receipt.json"
        l0.write_text("{}\n", encoding="utf-8")
        l1.write_text("{}\n", encoding="utf-8")
        summary = root / "summary.json"
        summary.write_text(
            json.dumps(
                {
                    "role": "mrtof_mirror_l0_l1_candidate_summary",
                    "status": "success",
                    "qualification": MIRROR_QUALIFICATION,
                    "input_identity": {
                        "contract_sha256": file_sha256(contract),
                        "l0_receipt_sha256": file_sha256(l0),
                        "l1_receipt_sha256": file_sha256(l1),
                    },
                    "selected_mirror_voltages_v": {
                        "A": 0.0,
                        "B": -5064.599670746161,
                        "C": 3843.4955853153892,
                        "D": 5439.680593141368,
                        "E": 7532.989971925157,
                    },
                }
            ) + "\n",
            encoding="utf-8",
        )
        run_config = root / "run_config.json"
        run_config.write_text(
            json.dumps({"run_id": "managed-test", "project": PROJECT_ID, "mode": MIRROR_MODE}) + "\n",
            encoding="utf-8",
        )

        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}

        manifest = root / "run_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_id": "managed-test",
                    "project": PROJECT_ID,
                    "mode": MIRROR_MODE,
                    "status": "success",
                    "run_config": record(run_config),
                    "inputs": {"candidate_contract": record(contract)},
                    "outputs": [record(summary), record(l0), record(l1)],
                }
            ) + "\n",
            encoding="utf-8",
        )
        return manifest

    def test_downstream_consumer_derives_period_and_w_from_managed_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_manifest(root)
            downstream_contract = root / "downstream_contract.json"
            shutil.copyfile(CONTRACT, downstream_contract)
            candidate = load_managed_mirror_candidate(manifest, downstream_contract)
            downstream_contract_sha256 = file_sha256(downstream_contract)
        self.assertEqual(candidate.design.electrode_voltages_v[0], 0.0)
        self.assertGreater(candidate.nominal_reduced_period_mm_per_sqrt_v, 0.0)
        self.assertGreater(candidate.nominal_axial_width_w_mm, 0.0)
        self.assertAlmostEqual(candidate.nominal_axial_width_w_mm, 540.4499458081797)
        self.assertNotEqual(candidate.contract_sha256, "")
        self.assertEqual(candidate.downstream_contract_sha256, downstream_contract_sha256)

    def test_downstream_consumer_rejects_post_manifest_tampering(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_manifest(root)
            (root / "summary.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "integrity failed"):
                load_managed_mirror_candidate(manifest)

    def test_downstream_consumer_rejects_a_changed_mirror_projection(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_manifest(root)
            downstream_contract = root / "downstream_contract.json"
            document = json.loads(CONTRACT.read_text(encoding="utf-8"))
            document["mirror"]["theory_requirements"]["berdnikov_transverse_half_gap_mm"] = 16.0
            downstream_contract.write_text(json.dumps(document) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "mirror-stage inputs"):
                load_managed_mirror_candidate(manifest, downstream_contract)

    def test_shape_diagnostic_consumes_current_contract_without_reusing_a_stale_whole_file(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_manifest(root)
            downstream_contract = root / "downstream_contract.json"
            shutil.copyfile(CONTRACT, downstream_contract)
            result = build_diagnostic(manifest, downstream_contract)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["managed_mirror_input"]["projection_match"])
        self.assertEqual(
            result["shape_structure"]["drift_length_identifiability"]["status"],
            "underdetermined_from_shape_structure_alone",
        )


if __name__ == "__main__":
    unittest.main()
