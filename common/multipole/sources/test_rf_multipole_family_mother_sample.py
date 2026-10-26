from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_count_policy import validate_prefix_particle_sources
from common.multipole.sources.generate_rf_multipole_family_mother_sample import (
    generate_rows,
    sha256,
)


SOURCE_ROOT = Path(__file__).resolve().parent
N100_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_100.csv"
N1000_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_1000.csv"
N5000_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_5000.csv"
METADATA_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1.json"
PAPER1_PROSPECTIVE_PATH = SOURCE_ROOT / "rf_multipole_paper1_prospective_mother_sample_v1_5000.csv"
PAPER1_PROSPECTIVE_N1000_PATH = SOURCE_ROOT / "rf_multipole_paper1_prospective_mother_sample_v1_1000.csv"
PAPER1_PROSPECTIVE_METADATA_PATH = SOURCE_ROOT / "rf_multipole_paper1_prospective_mother_sample_v1.json"


class RfMultipoleFamilyMotherSampleTests(unittest.TestCase):
    def test_independent_seed_is_deterministic_and_contiguous(self) -> None:
        first = generate_rows(2026081001, 12)
        second = generate_rows(2026081001, 12)
        self.assertEqual(first, second)
        self.assertEqual([row["particle_id"] for row in first], list(range(1, 13)))
        self.assertNotEqual(first, generate_rows(2026081002, 12))

    def test_family_cli_rebuilds_committed_samples_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rebuilt_n100 = Path(directory) / N100_PATH.name
            rebuilt_n1000 = Path(directory) / N1000_PATH.name
            rebuilt_n5000 = Path(directory) / N5000_PATH.name
            actual = subprocess.run(
                [sys.executable, "-B", "-m", "common.multipole.sources.generate_rf_multipole_family_mother_sample",
                 "--output-n100", str(rebuilt_n100), "--output-n1000", str(rebuilt_n1000),
                 "--output-n5000", str(rebuilt_n5000)],
                cwd=SOURCE_ROOT.parents[2], capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
            self.assertIn("RF_MULTIPOLE_FAMILY_MOTHER_SAMPLE=PASS", actual.stdout)
            self.assertEqual(rebuilt_n100.read_bytes(), N100_PATH.read_bytes())
            self.assertEqual(rebuilt_n1000.read_bytes(), N1000_PATH.read_bytes())
            self.assertEqual(rebuilt_n5000.read_bytes(), N5000_PATH.read_bytes())

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

    def test_n1000_is_exact_prefix_of_n5000(self) -> None:
        with N1000_PATH.open(encoding="utf-8", newline="") as handle:
            n1000_rows = list(csv.DictReader(handle))
        with N5000_PATH.open(encoding="utf-8", newline="") as handle:
            n5000_rows = list(csv.DictReader(handle))
        self.assertEqual(n5000_rows[:1000], n1000_rows)
        self.assertEqual([int(row["particle_id"]) for row in n5000_rows], list(range(1, 5001)))

    def test_independent_cli_rebuilds_paper1_sample_and_keeps_its_identity(self) -> None:
        metadata = json.loads(PAPER1_PROSPECTIVE_METADATA_PATH.read_text(encoding="utf-8"))
        generated = generate_rows(metadata["generator"]["seed"], 5000)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "independent.csv"
            actual = subprocess.run(
                [sys.executable, "-B", "-m", "common.multipole.sources.generate_rf_multipole_family_mother_sample",
                 "--output-sample", str(output), "--sample-count", "5000",
                 "--seed", str(metadata["generator"]["seed"])],
                cwd=SOURCE_ROOT.parents[2], capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
            self.assertIn("RF_MULTIPOLE_INDEPENDENT_MOTHER_SAMPLE=PASS", actual.stdout)
            self.assertEqual(output.read_bytes(), PAPER1_PROSPECTIVE_PATH.read_bytes())
        with PAPER1_PROSPECTIVE_PATH.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        with PAPER1_PROSPECTIVE_N1000_PATH.open(encoding="utf-8", newline="") as handle:
            n1000_rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 5000)
        self.assertEqual([int(row["particle_id"]) for row in rows], list(range(1, 5001)))
        self.assertEqual(metadata["output"]["sha256"], sha256(PAPER1_PROSPECTIVE_PATH))
        self.assertEqual(metadata["n1000_reference"]["sha256"], sha256(PAPER1_PROSPECTIVE_N1000_PATH))
        self.assertEqual(rows[:1000], n1000_rows)
        self.assertNotEqual(rows[0], generate_rows(2026072801, 5000)[0])
        self.assertEqual(rows[0], {key: str(value) for key, value in generated[0].items()})


if __name__ == "__main__":
    unittest.main()
