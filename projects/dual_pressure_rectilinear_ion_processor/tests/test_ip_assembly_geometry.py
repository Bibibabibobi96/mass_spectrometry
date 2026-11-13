"""Selected IP body serialization at the joint-model adapter boundary."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from msplatform.backends.simion.ip_assembly_geometry import render_selected_ip_body
from msplatform.backends.simion.ip_geometry import render_projection_electrodes, represent_selected_ip_design
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import select_legacy_physical_design

ROOT = Path(__file__).resolve().parents[3]


class IpAssemblyBodyTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads((ROOT / "projects/dual_pressure_rectilinear_ion_processor/config/baseline.json").read_text(encoding="utf-8"))
        self.baseline["physical_design_selection"] = {"native_grid_mm": 0.1, "native_aux_segments": 60}
        self.selected = select_legacy_physical_design(self.baseline, selection_grid_mm=0.1, auxiliary_segments=60)
        self.ids = {row["name"]: row["electrode_id"] for row in self.selected["projection"]["electrodes"]}

    def test_identity_preserves_complete_legacy_body_and_selected_source(self):
        before = copy.deepcopy((self.baseline, self.selected, self.ids))
        body, mapping = render_selected_ip_body(self.selected, baseline=self.baseline, native_ids=self.ids)
        self.assertEqual(body, render_projection_electrodes(self.selected["projection"]))
        self.assertEqual(mapping, self.ids)
        self.assertEqual((self.baseline, self.selected, self.ids), before)
        self.assertEqual(len(mapping), 15)
        for pitch in (0.1, 0.2):
            represented = represent_selected_ip_design(self.selected, baseline=self.baseline, grid_mm=pitch)
            self.assertEqual(body, render_projection_electrodes(represented))
        self.assertNotIn("pa_define", body)

    def test_remap_preserves_all_ordered_solids_and_tools(self):
        remapped = {name: value + 20 for name, value in self.ids.items()}
        actual, mapping = render_selected_ip_body(self.selected, baseline=self.baseline, native_ids=remapped)
        expected = copy.deepcopy(self.selected["projection"])
        for row in expected["electrodes"]:
            row["electrode_id"] = remapped[row["name"]]
        self.assertEqual(actual, render_projection_electrodes(expected))
        self.assertEqual(mapping, remapped)
        self.assertIn("notin_inside", actual)

    def test_tampered_source_and_bad_mapping_fail(self):
        changed = copy.deepcopy(self.selected)
        changed["projection"]["electrodes"][0]["solids"].pop()
        with self.assertRaisesRegex(ValueError, "source authority"):
            render_selected_ip_body(changed, baseline=self.baseline, native_ids=self.ids)
        for mapping in ({}, {**self.ids, "guide_negative": self.ids["guide_positive"]},
                        {**self.ids, "guide_negative": True}, {**self.ids, "guide_negative": 0}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                render_selected_ip_body(self.selected, baseline=self.baseline, native_ids=mapping)
        baseline = copy.deepcopy(self.baseline)
        del baseline["physical_design_selection"]
        with self.assertRaisesRegex(ValueError, "explicit physical design selection"):
            render_selected_ip_body(self.selected, baseline=baseline, native_ids=self.ids)


if __name__ == "__main__":
    unittest.main()
