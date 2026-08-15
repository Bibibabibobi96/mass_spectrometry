from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
import zipfile
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.verify_simion_fly2_loader_characterization import (
    AUTHORIZATION_RAW_FIELDS,
    AUTHORIZATION_RECEIPT,
    CHARACTERIZATION_RAW_FIELDS,
    EXPECTED_SOURCE_SHA256,
    RAW_EVIDENCE_CONTAINER,
    RAW_EVIDENCE_DESCRIPTOR,
    RECEIPT,
    _compact_receipt,
    _deterministic_raw_evidence_zip,
    _json_bytes,
    _verify_raw_evidence,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _resolve_staged_loader_validation,
)


REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent
CANONICAL_SOURCE = (
    WORKSPACE
    / "artifacts/projects/rf_octupole_ion_optics/runs"
    / "20260804_094500__sim__cross__oct-simion-grid2-common-oatof__n34"
    / "inputs/canonical_simion_local_accelerator_exit.csv"
)


class SimionFly2LoaderReceiptCompactionTest(unittest.TestCase):
    def test_git_summaries_are_compact_and_share_raw_evidence(self) -> None:
        characterization = json.loads(RECEIPT.read_text(encoding="utf-8"))
        authorization = json.loads(
            AUTHORIZATION_RECEIPT.read_text(encoding="utf-8")
        )
        self.assertEqual(characterization["schema_version"], 2)
        self.assertEqual(authorization["schema_version"], 2)
        self.assertEqual(
            characterization["raw_evidence"], RAW_EVIDENCE_DESCRIPTOR
        )
        self.assertEqual(authorization["raw_evidence"], RAW_EVIDENCE_DESCRIPTOR)
        for field in CHARACTERIZATION_RAW_FIELDS:
            self.assertNotIn(field, characterization)
        for field in AUTHORIZATION_RAW_FIELDS:
            self.assertNotIn(field, authorization)
        self.assertLess(RECEIPT.stat().st_size, 10_000)
        self.assertLess(AUTHORIZATION_RECEIPT.stat().st_size, 6_000)

    def test_zip_builder_is_deterministic_and_preserves_exact_bytes(self) -> None:
        documents = {"z.json": b"{\"z\":1}\r\n", "a.json": b"{\"a\":2}\n"}
        first = _deterministic_raw_evidence_zip(documents)
        self.assertEqual(first, _deterministic_raw_evidence_zip(documents))
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(), ["a.json", "z.json"])
            self.assertEqual(archive.read("a.json"), documents["a.json"])
            self.assertEqual(archive.read("z.json"), documents["z.json"])

    def test_managed_raw_evidence_recovers_both_legacy_receipts(self) -> None:
        if not RAW_EVIDENCE_CONTAINER.is_file():
            self.skipTest("local artifacts are absent")
        expected = {
            item["name"]: item for item in RAW_EVIDENCE_DESCRIPTOR["members"]
        }
        with zipfile.ZipFile(RAW_EVIDENCE_CONTAINER) as archive:
            documents = {name: archive.read(name) for name in archive.namelist()}
        self.assertEqual(set(documents), set(expected))
        for name, data in documents.items():
            self.assertEqual(len(data), expected[name]["bytes"])
            self.assertEqual(
                hashlib.sha256(data).hexdigest().upper(), expected[name]["sha256"]
            )
        _verify_raw_evidence(documents)
        legacy_characterization = json.loads(documents[RECEIPT.name])
        legacy_authorization = json.loads(documents[AUTHORIZATION_RECEIPT.name])
        compact_characterization = _compact_receipt(
            legacy_characterization, CHARACTERIZATION_RAW_FIELDS
        )
        self.assertEqual(_json_bytes(compact_characterization), RECEIPT.read_bytes())
        compact_authorization = _compact_receipt(
            legacy_authorization, AUTHORIZATION_RAW_FIELDS
        )
        compact_authorization["identities"] = dict(
            compact_authorization["identities"]
        )
        compact_authorization["identities"]["selection_receipt_sha256"] = (
            hashlib.sha256(RECEIPT.read_bytes()).hexdigest().upper()
        )
        self.assertEqual(
            _json_bytes(compact_authorization), AUTHORIZATION_RECEIPT.read_bytes()
        )

    def test_prepare_resolves_compact_v2_without_runtime_decompression(self) -> None:
        if not CANONICAL_SOURCE.is_file() or not RAW_EVIDENCE_CONTAINER.is_file():
            self.skipTest("local staged-grid2 artifacts are absent")
        with CANONICAL_SOURCE.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
        record = {
            "path": RECEIPT.with_name(
                "staged_grid2_n34_simion_fly2_loader_authorization_budget.json"
            ).relative_to(REPO).as_posix(),
            "sha256": hashlib.sha256(AUTHORIZATION_RECEIPT.read_bytes())
            .hexdigest()
            .upper(),
        }
        resolved, container_path = _resolve_staged_loader_validation(
            REPO, record, EXPECTED_SOURCE_SHA256, source_rows
        )
        self.assertEqual(resolved["velocity"]["relative_bound"], 2e-8)
        self.assertEqual(resolved["derived_energy"]["relative_bound"], 3e-8)
        self.assertEqual(container_path, AUTHORIZATION_RECEIPT)


if __name__ == "__main__":
    unittest.main()
