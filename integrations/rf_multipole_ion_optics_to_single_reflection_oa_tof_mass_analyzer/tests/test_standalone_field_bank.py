from __future__ import annotations

import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.standalone_field_bank import (
    MODE_IDS,
    _selection_records,
    composition_terms,
)


class StandaloneFieldBankTests(unittest.TestCase):
    def test_composition_uses_mode36_as_geometry_carrier(self) -> None:
        records = [
            {"response_id": mode_id, "path": f"C:/response_{mode_id}.pa"}
            for mode_id in MODE_IDS
        ]
        coefficients = {mode_id: 0.0 for mode_id in MODE_IDS}
        coefficients[36] = 12.0
        coefficients[42] = -3.0
        base, terms = composition_terms(records, coefficients)
        self.assertEqual(base, "C:/response_36.pa")
        self.assertEqual(
            terms,
            [
                {"path": "C:/response_36.pa", "coefficient": 11.0},
                {"path": "C:/response_42.pa", "coefficient": -3.0},
            ],
        )

    def test_composition_requires_exact_eight_mode_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "36 through 43"):
            composition_terms(
                [{"response_id": 36, "path": "C:/response_36.pa"}],
                {mode_id: 0.0 for mode_id in MODE_IDS},
            )

    def test_composition_chooses_nonzero_base_and_preserves_negative_rf_sign(self) -> None:
        records = [
            {"response_id": mode_id, "path": f"C:/response_{mode_id}.pa"}
            for mode_id in MODE_IDS
        ]
        coefficients = {mode_id: 0.0 for mode_id in MODE_IDS}
        coefficients[37] = -1.0
        base, terms = composition_terms(records, coefficients)
        self.assertEqual(base, "C:/response_37.pa")
        self.assertEqual(
            terms,
            [{"path": "C:/response_37.pa", "coefficient": -2.0}],
        )

    def test_selection_schema_is_strict_and_role_bound(self) -> None:
        records = [
            {
                "response_id": mode_id,
                "name": f"frontend.response_{mode_id}.pa",
                "path": f"C:/cache/frontend.response_{mode_id}.pa",
                "bytes": 10,
                "sha256": "A" * 64,
            }
            for mode_id in MODE_IDS
        ]
        selection = {
            "schema_version": 1,
            "role": "rf_oatof_standalone_pa_response_selection",
            "prefix": "frontend",
            "records": records,
        }
        self.assertEqual(
            len(_selection_records("coarse_frontend", selection)), len(MODE_IDS)
        )
        selection["prefix"] = "accelerator_main"
        with self.assertRaisesRegex(ValueError, "identity differs"):
            _selection_records("coarse_frontend", selection)


if __name__ == "__main__":
    unittest.main()
