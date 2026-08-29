"""Tests for immutable pre-pulse receipt-successor campaign authoring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_pre_pulse_receipt_successor import (
    author_successor,
)


class PrePulseReceiptSuccessorTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source.json"
        source.write_text(json.dumps({
            "role": "rf_multipole_oatof_experiment_campaign",
            "campaign_id": "legacy",
            "pre_pulse_time_series_screening": {
                "mode": "real_pa_rf_pre_pulse_time_series"
            },
            "experiments": {"shared": {
                "single_flight_pa_cache_policy": "build_and_publish_if_missing"
            }, "rows": [
                {"run_id": "20260828_180100__sim__cross__square__n5000"},
                {"run_id": "20260828_180200__sim__cross__circle__n5000"},
            ]},
        }), encoding="utf-8")
        return source

    def test_successor_changes_only_campaign_and_run_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            result = author_successor(
                source_path=source, output_path=root / "successor.json",
                campaign_id="receipt_successor", run_stamp="20260830_040000",
            )
            self.assertEqual(result["campaign_id"], "receipt_successor")
            self.assertEqual(
                result["experiments"]["shared"]["single_flight_pa_cache_policy"],
                "require_existing",
            )
            self.assertEqual(
                [row["run_id"] for row in result["experiments"]["rows"]],
                [
                    "20260830_040000__sim__cross__square__n5000",
                    "20260830_040001__sim__cross__circle__n5000",
                ],
            )
            self.assertEqual(
                len({row["run_id"][:15] for row in result["experiments"]["rows"]}),
                len(result["experiments"]["rows"]),
            )
            original = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(original["campaign_id"], "legacy")

    def test_rejects_non_pre_pulse_source_or_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            with self.assertRaisesRegex(ContractError, "run stamp"):
                author_successor(
                    source_path=source, output_path=root / "successor.json",
                    campaign_id="receipt_successor", run_stamp="bad",
                )
            output = root / "exists.json"
            output.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "already exists"):
                author_successor(
                    source_path=source, output_path=output,
                    campaign_id="receipt_successor", run_stamp="20260830_040000",
                )


if __name__ == "__main__":
    unittest.main()
