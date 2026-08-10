from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_count_policy import validate_prefix_particle_sources
from common.multipole.sources.generate_rf_multipole_family_mother_sample import (
    build,
    build_steady_batches,
    generate_rows,
    sha256,
)


SOURCE_ROOT = Path(__file__).resolve().parent
N100_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_100.csv"
N1000_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_1000.csv"
METADATA_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1.json"


class RfMultipoleFamilyMotherSampleTests(unittest.TestCase):
    def test_independent_candidate_pool_is_deterministic_and_contiguous(self) -> None:
        first = generate_rows(2026081001, 12)
        second = generate_rows(2026081001, 12)
        self.assertEqual(first, second)
        self.assertEqual([row["particle_id"] for row in first], list(range(1, 13)))
        self.assertNotEqual(first, generate_rows(2026081002, 12))

    def test_candidate_batches_preserve_independence_and_local_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_steady_batches(Path(directory))
            self.assertEqual(len(paths), 4)
            with paths[0].open(encoding="utf-8", newline="") as handle:
                first = list(csv.DictReader(handle))
            with paths[1].open(encoding="utf-8", newline="") as handle:
                second = list(csv.DictReader(handle))
        self.assertEqual(len(first), 500)
        self.assertEqual([int(row["particle_id"]) for row in first], list(range(1, 501)))
        self.assertNotEqual(first, second)

    def test_committed_sample_is_rebuilt_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rebuilt_n100 = Path(directory) / N100_PATH.name
            rebuilt_n1000 = Path(directory) / N1000_PATH.name
            build(rebuilt_n100, rebuilt_n1000)
            self.assertEqual(rebuilt_n100.read_bytes(), N100_PATH.read_bytes())
            self.assertEqual(rebuilt_n1000.read_bytes(), N1000_PATH.read_bytes())

    def test_n100_is_exact_prefix_and_metadata_is_fresh(self) -> None:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        validate_prefix_particle_sources(
            N100_PATH,
            N1000_PATH,
            expected_n100_sha256=metadata["prefix"]["sha256"],
            expected_n1000_sha256=metadata["output"]["sha256"],
        )
        self.assertEqual(metadata["output"]["sha256"], sha256(N1000_PATH))
        self.assertEqual(metadata["prefix"]["provenance"], "generated_exact_prefix")
        with N1000_PATH.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([int(row["particle_id"]) for row in rows], list(range(1, 1001)))


if __name__ == "__main__":
    unittest.main()
