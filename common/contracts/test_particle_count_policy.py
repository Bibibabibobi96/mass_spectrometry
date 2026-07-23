from __future__ import annotations

import unittest
from pathlib import Path

from common.contracts.particle_count_policy import (
    load_particle_count_policy,
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


if __name__ == "__main__":
    unittest.main()
