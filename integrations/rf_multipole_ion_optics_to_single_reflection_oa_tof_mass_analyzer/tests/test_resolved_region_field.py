from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    FULL_ID,
    build_resolved_region_field_contract,
    resolved_region_field_lua,
    validate_resolved_region_field_contract,
)


ROOT = Path(__file__).resolve().parents[3]
GEOMETRY = ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"


class ResolvedRegionFieldTests(unittest.TestCase):
    def _build(self, profile_id: str) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "resolved.json"
            return build_resolved_region_field_contract(GEOMETRY, output, profile_id)

    def test_rr_ri_ir_ii_are_one_five_region_contract(self) -> None:
        expected = {
            "accelerator_real_pa": ("real_pa_field", "real_pa_field"),
            "accelerator_ideal_stage1_real_stage2": ("analytic_ideal_field", "real_pa_field"),
            "accelerator_real_stage1_ideal_stage2": ("real_pa_field", "analytic_ideal_field"),
            "accelerator_ideal_stage1_stage2_real_reflectron": ("analytic_ideal_field", "analytic_ideal_field"),
        }
        for profile_id, accelerator in expected.items():
            contract = self._build(profile_id)
            modes = contract["semantic"]["region_modes"]
            self.assertEqual(tuple(modes.values())[:2], accelerator)
            self.assertEqual(tuple(modes.values())[2:], ("real_pa_field",) * 3)
            validate_schema(contract, "rf_oatof_resolved_region_field_contract.schema.json")

    def test_full_ideal_has_no_real_pa_region_or_blending(self) -> None:
        contract = self._build(FULL_ID)
        self.assertNotIn("real_pa_field", contract["semantic"]["region_modes"].values())
        self.assertFalse(contract["semantic"]["real_pa_field_blending_allowed"])
        lua = resolved_region_field_lua(contract)
        self.assertNotIn("bore", lua.lower())
        self.assertIn("analytic_field", contract["semantic"]["effective_domain"]["transverse"])
        self.assertIn("error('particle escaped resolved region-field", lua)

    def test_bore_fallback_or_real_pa_blending_fails_closed(self) -> None:
        contract = self._build(FULL_ID)
        invalid = copy.deepcopy(contract)
        invalid["semantic"]["effective_domain"]["transverse"] = "bore_fallback_to_real_pa"
        from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import semantic_sha256
        invalid["semantic_sha256"] = semantic_sha256(invalid["semantic"])
        with self.assertRaisesRegex(ValueError, "cannot silently fall back"):
            validate_resolved_region_field_contract(invalid)
        invalid = copy.deepcopy(contract)
        invalid["semantic"]["real_pa_field_blending_allowed"] = True
        invalid["semantic_sha256"] = semantic_sha256(invalid["semantic"])
        with self.assertRaisesRegex(ValueError, "prohibit real-PA blending"):
            validate_resolved_region_field_contract(invalid)

    def test_semantic_sha_is_path_free_and_stable(self) -> None:
        one = self._build(FULL_ID)
        two = self._build(FULL_ID)
        self.assertEqual(one["semantic_sha256"], two["semantic_sha256"])
        self.assertFalse(any(key == "path" for key in one["semantic"]))


if __name__ == "__main__":
    unittest.main()
