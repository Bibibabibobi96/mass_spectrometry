from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import validate_rf_energy_match as module  # noqa: E402


class RfEnergyMatchTests(unittest.TestCase):
    def test_repository_contract_is_valid(self) -> None:
        contract = module.validate()
        self.assertEqual(contract["input_candidate"]["kinetic_energy_eV"], 5.0)
        self.assertFalse(contract["model_changes"]["velocity_rewrite_at_handoff_allowed"])

    def test_velocity_rewrite_is_rejected(self) -> None:
        contract = module.load(module.CONTRACT_PATH)
        contract["model_changes"]["velocity_rewrite_at_handoff_allowed"] = True
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rewrite"):
                module.validate(path)

    def test_arbitrary_pulse_time_is_rejected(self) -> None:
        contract = module.load(module.CONTRACT_PATH)
        contract["physical_port_pulse_evidence"]["derived_pulse_time_us"] += 0.1
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "candidate.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pulse time"):
                module.validate(path)


if __name__ == "__main__":
    unittest.main()
