"""Selected IP body serialization at the joint-model adapter boundary."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from msplatform.backends.simion.ip_assembly_geometry import render_selected_ip_body
from msplatform.backends.simion.ip_geometry import render_projection_electrodes, represent_selected_ip_design
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import select_legacy_physical_design
from msplatform.components.dual_pressure_rectilinear_ion_processor.provider import resolve_component

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

    def test_explicit_60mm_lp_rebuilds_complete_selected_design(self):
        before = copy.deepcopy(self.baseline)
        shorter = copy.deepcopy(self.baseline)
        shorter['geometry']['lp_length_mm'] = 60
        default = resolve_component({'baseline': self.baseline})
        selected = resolve_component({'baseline': shorter})
        default_rows = default['resolved_design']['projection']['electrodes']
        rows = selected['resolved_design']['projection']['electrodes']
        self.assertEqual([row['name'] for row in rows], [row['name'] for row in default_rows])
        self.assertEqual(len(rows), 15)
        self.assertEqual([row['electrode_group_id'] for row in selected['assembly_interface']['component_electrodes']],
                         [row['name'] for row in rows])
        self.assertEqual([len(row['solids']) for row in rows], [len(row['solids']) for row in default_rows])
        self.assertEqual({a['name'] for a,b in zip(rows,default_rows,strict=True) if a != b},
                         {'lp_pull','lp_push','lp_side_upper','lp_side_lower','lp_outer_auxiliary',
                          'exit_lens','lp_commonmode_shield'})
        by_name = {row['name']: row for row in rows}
        self.assertEqual(by_name['lp_pull']['solids'][0]['max_mm'][0], 189.5)
        self.assertEqual(by_name['exit_lens']['solids'][0]['min_mm'][0], 190.)
        self.assertEqual(by_name['lp_commonmode_shield']['cutouts'][0]['min_mm'][0], 166.)
        self.assertEqual(shorter['geometry']['lp_center_mm'], 170)
        self.assertEqual(selected['assembly_interface']['ports']['extraction_exit']['center_mm'], [170., 3.5, 0.])
        self.assertEqual(selected['assembly_interface']['ports']['guide_inlet'], default['assembly_interface']['ports']['guide_inlet'])
        self.assertNotEqual(selected['resolved_design']['baseline_sha256'], default['resolved_design']['baseline_sha256'])
        self.assertEqual(self.baseline, before)
        self.assertEqual(self.baseline['geometry']['lp_length_mm'], 80)
        self.assertEqual(resolve_component({'baseline': self.baseline}), default)
        ids = {row['name']: row['electrode_id'] for row in rows}
        with self.assertRaisesRegex(ValueError, 'source authority'):
            render_selected_ip_body(selected['resolved_design'], baseline=self.baseline, native_ids=ids)
        broken = copy.deepcopy(shorter)
        broken['geometry']['lp_length_mm'] = 0
        with self.assertRaises(ValueError):
            resolve_component({'baseline': broken})

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
