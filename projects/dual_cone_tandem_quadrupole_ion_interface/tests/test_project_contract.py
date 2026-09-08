"""Static ownership and registration checks for the COMSOL-to-SIMION chain."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.build_project_registry import validate_descriptor
from common.contracts.machine_contracts import REPO_ROOT, validate_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_descriptor_and_execution_profiles_are_valid(self) -> None:
        descriptor_path = PROJECT_ROOT / "config/project.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        validate_descriptor(descriptor, descriptor_path, REPO_ROOT)
        profiles = json.loads(
            (PROJECT_ROOT / "config/execution_profiles.json").read_text(encoding="utf-8")
        )
        validate_schema(profiles, "execution_profiles.schema.json")
        self.assertEqual(
            {profile["mode"] for profile in profiles["profiles"]},
            {
                "axisymmetric_gas_flow_screening",
                "gas_field_driven_simion_transport",
            },
        )
        self.assertTrue(
            all(profile["evidence_levels"] == ["plan"] for profile in profiles["profiles"])
        )

    def test_retired_python_integrator_is_not_an_active_entry(self) -> None:
        profiles = (PROJECT_ROOT / "config/execution_profiles.json").read_text(
            encoding="utf-8"
        )
        descriptor = (PROJECT_ROOT / "config/project.json").read_text(encoding="utf-8")
        self.assertNotIn("pressure_drag_screening", profiles)
        self.assertNotIn("pressure_drag_screening", descriptor)
        for relative in (
            "analysis/reduced_order_transport.py",
            "analysis/run_reduced_order_transport.py",
            "config/modes/pressure_drag_screening.json",
        ):
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
