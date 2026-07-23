from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_count_policy import validate_prefix_particle_sources


class ParticleSourcePolicyTests(unittest.TestCase):
    def test_prefix_contract_accepts_exact_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            large = [f"particle-{index}" for index in range(1000)]
            n100 = root_path / "n100.ion"
            n1000 = root_path / "n1000.ion"
            n100.write_text("\n".join(large[:100]) + "\n", encoding="utf-8")
            n1000.write_text("\n".join(large) + "\n", encoding="utf-8")
            validate_prefix_particle_sources(n100, n1000)

    def test_prefix_contract_rejects_independently_changed_n100(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            large = [f"particle-{index}" for index in range(1000)]
            small = large[:100]
            small[50] = "changed"
            n100 = root_path / "n100.ion"
            n1000 = root_path / "n1000.ion"
            n100.write_text("\n".join(small) + "\n", encoding="utf-8")
            n1000.write_text("\n".join(large) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deterministic prefix"):
                validate_prefix_particle_sources(n100, n1000)


if __name__ == "__main__":
    unittest.main()
