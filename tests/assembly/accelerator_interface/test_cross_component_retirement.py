"""Retired cross-component re-release and private interface owner are absent."""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
RESOURCES = ROOT / "src/msplatform/workflows/resources"


class CrossComponentRetirementTests(unittest.TestCase):
    def test_old_joint_execution_owner_and_admission_are_absent(self):
        from msplatform.workflows.historical_joint_analysis import publish_joint_analysis

        self.assertFalse((RESOURCES / "prepared_joint_execute.ps1").exists())
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.prepared_joint"))
        self.assertTrue(callable(publish_joint_analysis))

    def test_accelerator_interface_private_owner_is_absent(self):
        self.assertFalse((RESOURCES / "accelerator_interface.ps1").exists())
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.accelerator_interface"))
        self.assertIsNotNone(importlib.util.find_spec("msplatform.assembly.accelerator_interface"))
        self.assertIsNotNone(importlib.util.find_spec("msplatform.workflows.mr_design.accelerator_interface"))


if __name__ == "__main__":
    unittest.main()
