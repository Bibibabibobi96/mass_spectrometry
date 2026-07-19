from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "analysis" / "assess_interface_integration_gate.py"
SPEC = importlib.util.spec_from_file_location("integration_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IntegrationGateTests(unittest.TestCase):
    def test_contract_requires_all_frozen_sections(self) -> None:
        self.assertFalse(MODULE.integration_contract_complete(None))
        self.assertFalse(MODULE.integration_contract_complete({"status": "draft"}))
        self.assertFalse(MODULE.integration_contract_complete({"status": "frozen", "coordinate_transform": {"x": 1}}))
        self.assertTrue(MODULE.integration_contract_complete({
            "status": "frozen",
            "coordinate_transform": {"matrix": "identity"},
            "timing_contract": {"time_zero": "handoff"},
            "acceptance_criteria": {"transmission_min": 0.8},
        }))

    def test_regression_failure_cannot_pass(self) -> None:
        status, _, reason = MODULE.decide_gate(False, True, True, "PASS")
        self.assertEqual(status, "FAIL")
        self.assertEqual(reason, "component_regression_failed")

    def test_missing_contract_cannot_pass(self) -> None:
        status, blockers, reason = MODULE.decide_gate(True, True, False, "NOT_EVALUATED")
        self.assertEqual(status, "FAIL")
        self.assertIn("missing_integration_contract", blockers)
        self.assertEqual(reason, "missing_integration_contract")

    def test_strict_pass_with_complete_contract(self) -> None:
        status, _, reason = MODULE.decide_gate(True, True, True, "NOT_EVALUATED")
        self.assertEqual((status, reason), ("PASS", "none"))

    def test_functional_pass_is_conditional(self) -> None:
        status, _, reason = MODULE.decide_gate(True, False, True, "PASS")
        self.assertEqual(status, "CONDITIONAL_PASS")
        self.assertIn("functional_acceptance_passed", reason)

    def test_unresolved_or_failed_functional_gate_fails(self) -> None:
        self.assertEqual(MODULE.decide_gate(True, False, True, "NOT_EVALUATED")[0], "FAIL")
        self.assertEqual(MODULE.decide_gate(True, False, True, "FAIL")[0], "FAIL")


if __name__ == "__main__":
    unittest.main()
