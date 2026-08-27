"""Tests for detector-blind J2 real-field candidate selection."""

from __future__ import annotations

import json
from hashlib import sha256
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_j2_real_field_selection import (
    STATE_NAMES,
    select_j2_real_field_candidates,
)


class Paper1J2RealFieldSelectionTests(unittest.TestCase):
    def _write(self, root: Path, name: str, value: object) -> Path:
        path = root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _c1(self) -> dict[str, object]:
        covariance = [[0.0] * 6 for _ in range(6)]
        for index, value in enumerate((1.0, 4.0, 9.0, 1.0, 1.0, 1.0)):
            covariance[index][index] = value
        return {
            "stage_id": "C1", "conclusion": "PASS_CONTINUE",
            "metrics": {"sources": [{"source_id": "S1", "covariance_bins": [
                {"sample_count": 2, "covariance": covariance},
                {"sample_count": 1, "covariance": covariance},
            ]}]},
        }

    def _request(self, receipt_sha256: str) -> dict[str, object]:
        return {
            "role": "oatof_paper1_j2_fair_selection_request", "source_id": "S1",
            "candidate_pool_sha256": "A" * 64, "candidate_ids": ["a", "b"],
            "state_names": list(STATE_NAMES),
            "state_scale": [1.0] * 6, "sensitivity_receipt_sha256": receipt_sha256,
        }

    def test_selects_both_objectives_from_same_detector_blind_pool(self) -> None:
        receipt = {
            "role": "oatof_paper1_real_field_sensitivity_receipt", "source_id": "S1",
            "candidate_pool_sha256": "A" * 64, "state_names": list(STATE_NAMES),
            "candidates": [
                {"candidate_id": "a", "time_gradient_us_per_state": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]},
                {"candidate_id": "b", "time_gradient_us_per_state": [1.5, 0.0, 0.0, 0.0, 0.0, 0.0]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = self._write(root, "receipt.json", receipt)
            result = select_j2_real_field_candidates(
                c1_stage_report=self._write(root, "c1.json", self._c1()),
                request_path=self._write(root, "request.json", self._request(sha256(receipt_path.read_bytes()).hexdigest().upper())),
                sensitivity_receipt=receipt_path,
            )
        self.assertEqual(result["unweighted_selection"]["candidate_id"], "a")
        self.assertEqual(result["source_whitened_selection"]["candidate_id"], "b")
        self.assertEqual([item["candidate_id"] for item in result["scores"]], ["a", "b"])

    def test_rejects_source_or_state_identity_mismatch(self) -> None:
        receipt = {
            "role": "oatof_paper1_real_field_sensitivity_receipt", "source_id": "S2",
            "candidate_pool_sha256": "A" * 64, "state_names": list(STATE_NAMES),
            "candidates": [
                {"candidate_id": "a", "time_gradient_us_per_state": [1.0] * 6},
                {"candidate_id": "b", "time_gradient_us_per_state": [2.0] * 6},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = self._write(root, "receipt.json", receipt)
            with self.assertRaisesRegex(ValueError, "not bound"):
                select_j2_real_field_candidates(
                    c1_stage_report=self._write(root, "c1.json", self._c1()),
                    request_path=self._write(root, "request.json", self._request(sha256(receipt_path.read_bytes()).hexdigest().upper())),
                    sensitivity_receipt=receipt_path,
                )

    def test_rejects_receipt_hash_mismatch(self) -> None:
        receipt = {
            "role": "oatof_paper1_real_field_sensitivity_receipt", "source_id": "S1",
            "candidate_pool_sha256": "A" * 64, "state_names": list(STATE_NAMES),
            "candidates": [
                {"candidate_id": "a", "time_gradient_us_per_state": [1.0] * 6},
                {"candidate_id": "b", "time_gradient_us_per_state": [2.0] * 6},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = self._write(root, "receipt.json", receipt)
            with self.assertRaisesRegex(ValueError, "hash differs"):
                select_j2_real_field_candidates(
                    c1_stage_report=self._write(root, "c1.json", self._c1()),
                    request_path=self._write(root, "request.json", self._request("B" * 64)),
                    sensitivity_receipt=receipt_path,
                )

    def test_rejects_a_sensitivity_subset_or_reordered_pool(self) -> None:
        receipt = {
            "role": "oatof_paper1_real_field_sensitivity_receipt", "source_id": "S1",
            "candidate_pool_sha256": "A" * 64, "state_names": list(STATE_NAMES),
            "candidates": [
                {"candidate_id": "b", "time_gradient_us_per_state": [1.0] * 6},
                {"candidate_id": "a", "time_gradient_us_per_state": [2.0] * 6},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = self._write(root, "receipt.json", receipt)
            with self.assertRaisesRegex(ValueError, "frozen common pool"):
                select_j2_real_field_candidates(
                    c1_stage_report=self._write(root, "c1.json", self._c1()),
                    request_path=self._write(root, "request.json", self._request(sha256(receipt_path.read_bytes()).hexdigest().upper())),
                    sensitivity_receipt=receipt_path,
                )


if __name__ == "__main__":
    unittest.main()
