"""Neutral OA topology over actual two/three-zone mechanical providers."""
from __future__ import annotations

import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

from projects.orthogonal_accelerator.analysis.electrode_topology import build_electrode_topology
from projects.orthogonal_accelerator.analysis.sectioned_geometry import resolve_bare_three_zone_component
from projects.orthogonal_accelerator.analysis.two_zone_geometry import resolve_closed_two_zone_geometry
from projects.orthogonal_accelerator.tests.analysis.test_assembly_interface import two_zone_requirements, TWO_ZONE_PROFILE
from projects.orthogonal_accelerator.tests.analysis.test_bare_three_zone_component import three_zone_requirements_fixture


def two_zone_inputs():
    resolved = resolve_closed_two_zone_geometry(two_zone_requirements(), geometry_profile_id=TWO_ZONE_PROFILE)
    source = json.loads((Path(__file__).resolve().parents[2] / "config/two_zone_component_focus_campaign.json").read_text())
    names = ["grounded_shield", "repeller", "grid1", "exit_grid", *[f"ring_{i:04d}" for i in range(1, 16)]]
    bindings = {name: {"pointer": f"/operating_point/electrode_voltages_v/{i}"} for i, name in enumerate(names)}
    return resolved, source, bindings


def three_zone_inputs():
    resolved = resolve_bare_three_zone_component(three_zone_requirements_fixture())
    # Explicit small source algorithm fixture, not a published operating point.
    names = ["grounded_shield", "repeller", "grid1", "intermediate2", "exit_grid",
             "ring_0001", "ring_0002", "ring_0003", "ring_0004"]
    source = {"fixture_voltages_v": dict(zip(names, [0., 4000., 3000., 2000., 0., 2800., 2400., 1400., 600.]))}
    bindings = {name: {"pointer": f"/fixture_voltages_v/{name}"} for name in names}
    return resolved, source, bindings


class ElectrodeTopologyTests(unittest.TestCase):
    def test_two_zone_real_campaign_covers_every_member_and_drive(self):
        resolved, source, bindings = two_zone_inputs()
        original = copy.deepcopy((resolved, source, bindings))
        topology = build_electrode_topology(resolved, voltage_sources=bindings, source_document=source)
        self.assertEqual(len(topology), 19)
        self.assertEqual([r["scientific_id"] for r in topology[:4]], ["grounded_shield", "repeller", "grid1", "exit_grid"])
        self.assertEqual(topology[0]["roles"], ["shield", "rear_cap"])
        self.assertIn("/enclosure/rear_cap_outer_z_mm", topology[0]["member_refs"])
        self.assertIn("/side_entry/physical_cutout_box_mm", topology[0]["member_refs"])
        self.assertEqual(topology[1]["member_refs"][:2], ["/local_repeller_z_mm", "/repeller_thickness_mm"])
        self.assertEqual(topology[2]["member_refs"], ["/grid_supports/0"])
        self.assertEqual(topology[3]["member_refs"], ["/grid_supports/1"])
        for i, row in enumerate(topology[4:]):
            self.assertEqual(row["scientific_id"], f"ring_{i + 1:04d}")
            self.assertIn(f"/rings/{i}", row["member_refs"])
            self.assertEqual(row["voltage_source"], {"pointer": f"/operating_point/electrode_voltages_v/{i + 4}"})
        self.assertEqual((resolved, source, bindings), original)
        self.assertEqual(asdict(resolved)["grid_supports"][0]["grid_z_mm"], 30.)

    def test_three_zone_real_sheets_rings_and_shield_have_complete_references(self):
        resolved, source, bindings = three_zone_inputs()
        topology = build_electrode_topology(resolved, voltage_sources=bindings, source_document=source)
        self.assertEqual(len(topology), 9)
        self.assertEqual([r["scientific_id"] for r in topology[2:5]], ["grid1", "intermediate2", "exit_grid"])
        for i, row in enumerate(topology[2:5]):
            self.assertEqual(row["roles"], ["ideal_zero_thickness_sheet"])
            self.assertEqual(row["member_refs"], [f"/canonical_electrodes/ideal_sheets/{i}"])
            sheet = resolved["canonical_electrodes"]["ideal_sheets"][i]["sheet_box_mm"]
            self.assertEqual(sheet["z_min_mm"], sheet["z_max_mm"])
        self.assertIn("/geometry/shield_back_z_mm", topology[0]["member_refs"])
        self.assertIn("/geometry/numerical_port_width_mm", topology[0]["member_refs"])
        for i, row in enumerate(topology[5:]):
            self.assertEqual(row["scientific_id"], f"ring_{i+1:04d}")
            self.assertIn(f"/geometry/ring_z_mm/{i}", row["member_refs"])
            self.assertIn("/geometry/bore_width_mm", row["member_refs"])
            self.assertEqual(row["voltage_source"], bindings[row["scientific_id"]])

    def test_native_number_permutation_never_changes_scientific_groups(self):
        two, source, bindings = two_zone_inputs()
        changed = replace(two, grid_supports=tuple({**r, "id": 200+i} for i, r in enumerate(two.grid_supports)),
                          rings=tuple({**r, "id": 300+i} for i, r in enumerate(two.rings)))
        self.assertEqual(build_electrode_topology(two, voltage_sources=bindings, source_document=source),
                         build_electrode_topology(changed, voltage_sources=bindings, source_document=source))
        three, source, bindings = three_zone_inputs()
        changed = copy.deepcopy(three)
        changed["electrodes"] = {k: [v+100 for v in value] if isinstance(value, list) else value+100
                                  for k, value in changed["electrodes"].items()}
        for member in [changed["canonical_electrodes"]["repeller"], *changed["canonical_electrodes"]["ideal_sheets"]]:
            member["component_electrode_id"] += 100
        self.assertEqual(build_electrode_topology(three, voltage_sources=bindings, source_document=source),
                         build_electrode_topology(changed, voltage_sources=bindings, source_document=source))

    def test_missing_extra_or_invalid_source_binding_is_rejected(self):
        for factory in (two_zone_inputs, three_zone_inputs):
            resolved, source, bindings = factory()
            cases = []
            value = copy.deepcopy(bindings); del value["ring_0001"]; cases.append(value)
            value = copy.deepcopy(bindings); value["unexpected"] = {"pointer": "/nope"}; cases.append(value)
            for pointer in ("", "/missing", "/bad~", "/bad~2", "/operating_point/electrode_voltages_v/-1"):
                value = copy.deepcopy(bindings); value["repeller"] = {"pointer": pointer}; cases.append(value)
            value = copy.deepcopy(bindings); value["repeller"]["value_v"] = 1.; cases.append(value)
            for value in cases:
                with self.subTest(factory=factory.__name__, binding=value), self.assertRaises(ValueError):
                    build_electrode_topology(resolved, voltage_sources=value, source_document=source)
            for bad in (True, None, "4", float("nan"), float("inf"), {}, []):
                value = copy.deepcopy(bindings); value["repeller"] = {"pointer": "/invalid_v"}
                with self.subTest(value=bad), self.assertRaises(ValueError):
                    build_electrode_topology(resolved, voltage_sources=value, source_document={**source, "invalid_v": bad})

    def test_shared_drive_does_not_merge_groups_and_ground_is_not_native_zero(self):
        resolved, source, bindings = three_zone_inputs()
        bindings["grid1"] = dict(bindings["repeller"])
        topology = build_electrode_topology(resolved, voltage_sources=bindings, source_document=source)
        self.assertEqual(len(topology), 9)
        self.assertEqual(topology[1]["voltage_source"], topology[2]["voltage_source"])
        source["fixture_voltages_v"]["grounded_shield"] = 1.
        with self.assertRaisesRegex(ValueError, "grounded shield"):
            build_electrode_topology(resolved, voltage_sources=bindings, source_document=source)

    def test_incomplete_mechanical_member_coverage_is_rejected(self):
        resolved, source, bindings = two_zone_inputs()
        with self.assertRaises(ValueError):
            build_electrode_topology(replace(resolved, grid_supports=resolved.grid_supports[:1]),
                                     voltage_sources=bindings, source_document=source)
        resolved, source, bindings = three_zone_inputs()
        resolved["canonical_electrodes"]["ideal_sheets"].pop()
        with self.assertRaises(ValueError):
            build_electrode_topology(resolved, voltage_sources=bindings, source_document=source)


if __name__ == "__main__":
    unittest.main()
