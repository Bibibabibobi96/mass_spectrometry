from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import resolve_s2_connector_case as resolver
from projects.rf_quadrupole_collision_cooling.analysis import validate_s2_passive_connector as validator


class S2ConnectorCaseTests(unittest.TestCase):
    def test_direct_mating_derives_zero_gap_without_connector_domain(self) -> None:
        result = resolver.resolve_case(
            resolver.DEFAULT_BASE, resolver.DEFAULT_CASES, "direct_mating_gap_0mm")
        registration = result["nominal_registration"]
        geometry = result["passive_connector_geometry"]
        self.assertEqual(registration["connector_gap_mm"], 0.0)
        self.assertEqual(registration["source_exit_center_instrument_mm"],
                         registration["target_entry_center_instrument_mm"])
        self.assertEqual(geometry["length_mm"], 0.0)
        self.assertEqual(geometry["axial_extent_x_mm"], [-67.8, -67.8])
        self.assertFalse(result["runtime_case"]["connector_domain_present"])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resolved.json"
            path.write_text(__import__("json").dumps(result), encoding="utf-8")
            validator.validate_contract(path)

    def test_nominal_case_reproduces_base_registration(self) -> None:
        base = resolver._load(resolver.DEFAULT_BASE)
        result = resolver.resolve_case(
            resolver.DEFAULT_BASE, resolver.DEFAULT_CASES, "nominal_gap_1mm")
        self.assertEqual(result["nominal_registration"], base["nominal_registration"])
        self.assertEqual(result["passive_connector_geometry"]["length_mm"], 1.0)
        self.assertTrue(result["runtime_case"]["connector_domain_present"])

    def test_unknown_case_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "resolve uniquely"):
            resolver.resolve_case(resolver.DEFAULT_BASE, resolver.DEFAULT_CASES, "missing")


if __name__ == "__main__":
    unittest.main()
