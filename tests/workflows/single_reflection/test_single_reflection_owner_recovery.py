"""The retired SFI producer package and PowerShell entry are absent."""
import importlib.util
from pathlib import Path
import unittest


class SingleReflectionOwnerRecoveryTests(unittest.TestCase):
    def test_retired_package_and_script_are_absent(self):
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.single_reflection_flight"))
        root = Path(__file__).resolve().parents[3]
        self.assertFalse((root / "src/msplatform/workflows/resources/single_reflection_flight.ps1").exists())
