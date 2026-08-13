from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.file_identity import file_sha256


class CanonicalClockAuthorityTests(unittest.TestCase):
    def test_accepts_single_frozen_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "state.csv"
            authority.write_text("particle_id,instrument_time_us\n1,4.5\n", encoding="utf-8")
            contract = root / "clock.json"
            contract.write_text(json.dumps({
                "schema_version": 1, "role": "canonical_clock_authority",
                "clock_epoch_id": "instrument_clock_epoch_v1",
                "instrument_time_unit": "us",
                "canonical_time_basis": "instrument_epoch_absolute_time",
                "authority": {"path": "state.csv", "sha256": file_sha256(authority), "field": "instrument_time_us"},
                "solver_local_time_basis": "elapsed_time_from_zero_us",
                "adapter_materialization": "instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
                "handoff_policy": "preserve_instrument_time_us_and_clock_epoch_id",
                "legacy_new_campaign_allowed": False,
            }), encoding="utf-8")
            self.assertEqual(validate_clock_authority(contract, root)["status"], "PASS")

    def test_rejects_unbound_authority_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "state.csv"
            authority.write_text("x\n", encoding="utf-8")
            contract = root / "clock.json"
            contract.write_text(json.dumps({
                "schema_version": 1, "role": "canonical_clock_authority",
                "clock_epoch_id": "instrument_clock_epoch_v1", "instrument_time_unit": "us",
                "canonical_time_basis": "instrument_epoch_absolute_time",
                "authority": {"path": "state.csv", "sha256": "0" * 64, "field": "instrument_time_us"},
                "solver_local_time_basis": "elapsed_time_from_zero_us",
                "adapter_materialization": "instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
                "handoff_policy": "preserve_instrument_time_us_and_clock_epoch_id",
                "legacy_new_campaign_allowed": False,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                validate_clock_authority(contract, root)


if __name__ == "__main__":
    unittest.main()
