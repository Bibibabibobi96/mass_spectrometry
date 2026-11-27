"""Check coupled geometry at its scientific owner without native software."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

from msplatform.components.single_reflection_oa_tof.geometry_derivation import verify_geometry_derivation


class GeometryDerivationTests(unittest.TestCase):
    def setUp(self):
        source = (Path(__file__).resolve().parents[4] / "src/msplatform/components/"
                  "single_reflection_oa_tof/config/baseline.json")
        self.contract = json.loads(source.read_bytes())

    def test_current_baseline_matches_and_input_is_unchanged(self):
        before = copy.deepcopy(self.contract)
        result = verify_geometry_derivation(self.contract)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["engineering_reflectron_length_mm"],
                         self.contract["geometry_mm"]["L_reflectron"])
        self.assertEqual(self.contract, before)

    def test_coordinate_voltage_and_derivation_metadata_conflicts_reject(self):
        for section, key in (("geometry_mm", "accelerator_grid1_z"),
                             ("electrodes_V", "backplate")):
            with self.subTest(section=section, key=key):
                changed = copy.deepcopy(self.contract)
                changed[section][key] += 1
                with self.assertRaises(AssertionError):
                    verify_geometry_derivation(changed)
        changed = copy.deepcopy(self.contract)
        changed["geometry_derivation"]["reflectron"]["energy_min_V"] += 1
        with self.assertRaises(AssertionError):
            verify_geometry_derivation(changed)

    def test_retired_grade_package_is_absent(self):
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.oa_formal"))


if __name__ == "__main__":
    unittest.main()
