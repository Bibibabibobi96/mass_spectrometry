"""Keep public planning scope bound to the existing functional inputs and runner."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from common.contracts.build_project_registry import validate_descriptor


PROJECT = Path(__file__).resolve().parents[1]


def read(relative: str) -> dict:
    return json.loads((PROJECT / relative).read_text(encoding="utf-8-sig"))


class ExecutionContractTests(unittest.TestCase):
    def test_registered_mode_matches_actual_source_and_retains_prototype_scope(self) -> None:
        descriptor = read("config/project.json")
        validate_descriptor(descriptor, PROJECT / "config/project.json", PROJECT.parents[1])
        self.assertEqual(descriptor["lifecycle_status"], "prototype")
        profile, = read(descriptor["contracts"]["execution"])["profiles"]
        mode = read(f"config/modes/{profile['mode']}.json")
        source = read(mode["inputs"]["source"])
        self.assertEqual(profile["evidence_levels"], ["plan"])
        self.assertEqual(profile["supported_operating_points"], [{
            "mass": {"value": source["species"]["mass_amu"], "unit": "Da"},
            "charge_state": source["species"]["charge_state"],
        }])
        self.assertEqual(mode["source_profile"], "functional")
        self.assertEqual(profile["supported_design_variables"], [])
        self.assertEqual(profile["required_bindings"], [])
        budgets = read(mode["runtime_profiles"])
        self.assertEqual(budgets["role"], "ion_processor_runtime_profiles")
        budget, = [row for row in budgets["profiles"] if row["profile_id"] == mode["runtime_profile_id"]]
        self.assertEqual(budget["retention_class"], "solver_review")
        for key in ("baseline", "numerics", "source", "acceptance", "native_operating_point"):
            self.assertTrue((PROJECT / mode["inputs"][key]).is_file())


if __name__ == "__main__":
    unittest.main()
