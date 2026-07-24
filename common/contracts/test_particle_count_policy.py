from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_count_policy import (
    load_particle_count_policy,
    validate_prefix_particle_sources,
    validate_standard_particle_count,
)


class ParticleCountPolicyTests(unittest.TestCase):
    def test_only_functional_and_statistical_counts_are_standard(self) -> None:
        policy = load_particle_count_policy()
        self.assertEqual(policy["standard_particle_counts"], [100, 1000])
        self.assertEqual(validate_standard_particle_count(100), 100)
        self.assertEqual(validate_standard_particle_count(1000), 1000)
        for count in (1, 25, 30, 99, 101):
            with self.assertRaisesRegex(ValueError, "must be one of"):
                validate_standard_particle_count(count)

    def test_root_readme_matches_machine_policy(self) -> None:
        readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
        self.assertIn("N=100是功能检查", readme)
        self.assertIn("N=1000是峰形", readme)
        self.assertIn("N=100必须是同一种子N=1000母样本的前100行", readme)

    def test_prefix_accepts_matching_headered_sources_and_expected_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_rows = [f"{index},{index + 1}" for index in range(1000)]
            n100 = root / "n100.csv"
            n1000 = root / "n1000.csv"
            n100.write_text(
                "particle_id,value\n" + "\n".join(data_rows[:100]) + "\n",
                encoding="utf-8",
            )
            n1000.write_text(
                "particle_id,value\n" + "\n".join(data_rows) + "\n",
                encoding="utf-8",
            )
            validate_prefix_particle_sources(
                n100,
                n1000,
                expected_n100_sha256=hashlib.sha256(n100.read_bytes()).hexdigest(),
                expected_n1000_sha256=hashlib.sha256(n1000.read_bytes()).hexdigest(),
            )

    def test_prefix_accepts_matching_headerless_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_rows = [f"{index},{index + 1}" for index in range(1000)]
            n100 = root / "n100.ion"
            n1000 = root / "n1000.ion"
            n100.write_text("\n".join(data_rows[:100]) + "\n", encoding="utf-8")
            n1000.write_text("\n".join(data_rows) + "\n", encoding="utf-8")
            validate_prefix_particle_sources(n100, n1000)

    def test_prefix_rejects_mixed_or_different_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_rows = [f"{index},{index + 1}" for index in range(1000)]
            n100 = root / "n100.csv"
            n1000 = root / "n1000.csv"
            n100.write_text(
                "particle_id,value\n" + "\n".join(data_rows[:100]) + "\n",
                encoding="utf-8",
            )
            n1000.write_text("\n".join(data_rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mixed header"):
                validate_prefix_particle_sources(n100, n1000)
            n1000.write_text(
                "particle_id,other\n" + "\n".join(data_rows) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "same header"):
                validate_prefix_particle_sources(n100, n1000)

    def test_prefix_rejects_wrong_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_rows = [f"{index},{index + 1}" for index in range(1000)]
            n100 = root / "n100.ion"
            n1000 = root / "n1000.ion"
            n100.write_text("\n".join(data_rows[:100]) + "\n", encoding="utf-8")
            n1000.write_text("\n".join(data_rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                validate_prefix_particle_sources(
                    n100,
                    n1000,
                    expected_n100_sha256="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
