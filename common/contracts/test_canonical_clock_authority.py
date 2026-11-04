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


    def test_canonical_origin_missing_schema_tamper_and_confinement(self) -> None:
        from unittest.mock import patch
        from jsonschema.exceptions import ValidationError
        from msplatform.execution import clock_authority as canonical
        from common.contracts import canonical_clock_authority as legacy

        self.assertIs(legacy.validate_clock_authority, canonical.validate_clock_authority)
        self.assertEqual(canonical.validate_clock_authority.__module__, "msplatform.execution.clock_authority")
        self.assertEqual(canonical.file_sha256.__module__, "msplatform.io.file_identity")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "explicit_data"
            root.mkdir()
            epoch = root / "epoch.json"
            epoch.write_bytes(b'{"instrument_time_us":0.0}\n')
            value = dict(schema_version=1, role="canonical_clock_authority",
                clock_epoch_id="instrument_clock_epoch_v1", instrument_time_unit="us",
                canonical_time_basis="instrument_epoch_absolute_time",
                authority=dict(path="epoch.json", sha256=file_sha256(epoch), field="instrument_time_us"),
                solver_local_time_basis="elapsed_time_from_zero_us",
                adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
                handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False)
            contract = root / "clock.json"
            contract.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(canonical.validate_clock_authority(contract, root)["authority_sha256"], file_sha256(epoch))
            with self.subTest(missing_schema=True), patch.object(canonical, "SCHEMA_PATH", root / "missing.schema.json"):
                with self.assertRaises(FileNotFoundError):
                    canonical.validate_clock_authority(contract, root)
            original = epoch.read_bytes()
            epoch.write_bytes(b'{"instrument_time_us":1.0}\n')
            with self.subTest(tampered=True), self.assertRaisesRegex(ValueError, "SHA-256"):
                canonical.validate_clock_authority(contract, root)
            epoch.write_bytes(original)
            value["authority"]["sha256"] = value["authority"]["sha256"].lower()
            contract.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(strict_hash=True), self.assertRaises(ValidationError):
                canonical.validate_clock_authority(contract, root)
            value["authority"]["sha256"] = file_sha256(epoch)
            value["authority"]["path"] = "../outside.json"
            contract.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(confinement=True), self.assertRaisesRegex(ValueError, "escapes"):
                canonical.validate_clock_authority(contract, root)
            self.assertEqual(epoch.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
