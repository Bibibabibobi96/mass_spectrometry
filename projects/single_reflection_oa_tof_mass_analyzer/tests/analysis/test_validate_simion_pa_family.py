from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.validate_simion_pa_family import (
    validate_family,
)


class SimionPaFamilyTests(unittest.TestCase):
    def test_surface_none_family_requires_pa_hash_and_every_basis_without_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("model.pa#", "model.pa0", "model.pa1", "model.pa2"):
                (root / name).write_bytes(b"test")
            self.assertEqual(len(validate_family(root, "model", 2)), 4)

    def test_missing_basis_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("model.pa#", "model.pa0", "model.pa2"):
                (root / name).write_bytes(b"test")
            with self.assertRaisesRegex(ValueError, "model.pa1"):
                validate_family(root, "model", 2)

    def test_pa_surface_is_forbidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("model.pa#", "model.pa0", "model.pa1", "model.pa-surf"):
                (root / name).write_bytes(b"test")
            with self.assertRaisesRegex(ValueError, "unexpectedly contains pa-surf"):
                validate_family(root, "model", 1)


if __name__ == "__main__":
    unittest.main()
