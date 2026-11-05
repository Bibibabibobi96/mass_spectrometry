"""Scientific group oracles and native-numbering boundaries for real RF models."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from msplatform.components.rf_multipole.compile_design_request import compile_design_request
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from projects.rf_multipole_ion_optics.simion.electrode_mapping import build_simion_electrode_map
from projects.rf_multipole_ion_optics.simion.simion_geometry import physical_electrode_view, render_physical_gem
from projects.rf_multipole_ion_optics.tests.domain.test_simion_geometry import resolved_design, shell
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request


class ElectrodeTopologyTests(unittest.TestCase):
    def test_continuous_groups_reference_every_real_rod_without_backend_import(self):
        source = resolved_design()
        before = copy.deepcopy(source)
        import builtins
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if ".simion" in name:
                raise AssertionError("neutral topology loaded a backend")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded):
            groups = build_electrode_topology(source)
        self.assertEqual([g["electrode_group_id"] for g in groups], ["rod_group_1", "rod_group_2"])
        self.assertEqual(groups[0]["member_refs"], ["/geometry_mm/rod_array/rods/0", "/geometry_mm/rod_array/rods/2"])
        self.assertEqual(groups[1]["member_refs"], ["/geometry_mm/rod_array/rods/1", "/geometry_mm/rod_array/rods/3"])
        self.assertTrue(all(set(g) == {"electrode_group_id", "roles", "member_refs", "voltage_source"} for g in groups))
        self.assertEqual(source, before)

    def test_segments_use_declared_identity_not_embedded_native_number(self):
        source = resolved_design(segmented=True)
        groups = build_electrode_topology(source)
        self.assertEqual([g["electrode_group_id"] for g in groups], [
            "segment_0001_rf_group_1", "segment_0001_rf_group_2", "segment_0002_rf_group_1", "segment_0002_rf_group_2"])
        for member in source["segmentation"]["segmented_rod_array"]["electrodes"]:
            member["electrode_id"] = "not a scientific identity"
        self.assertEqual(build_electrode_topology(source), groups)
        with self.assertRaisesRegex(ValueError, "SIMION namespace"):
            physical_electrode_view(source)
        self.assertEqual(groups[2]["voltage_source"]["common_mode_pointer"],
                         "/segmentation/segmented_rod_array/electrodes/4/common_mode_V")

    def test_shell_and_both_caps_keep_three_members_in_one_ground_group(self):
        cap = dict(aperture_radius_mm=2., thickness_mm=.5)
        source = resolved_design(shell(dict(entrance=cap, exit=cap)), segmented=True)
        groups = build_electrode_topology(source)
        ground = groups[-1]
        self.assertEqual(ground["electrode_group_id"], "grounded_shell")
        self.assertEqual(ground["member_refs"], [f"/geometry_mm/enclosure_layout/bodies/{i}" for i in range(3)])
        self.assertEqual(ground["roles"], [b["role"] for b in source["geometry_mm"]["enclosure_layout"]["bodies"]])
        self.assertEqual(build_simion_electrode_map(source, groups)["grounded_shell"], 5)
        source["geometry_mm"]["enclosure_layout"]["bodies"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            build_electrode_topology(source)

    def test_explicit_permutation_changes_only_backend_map(self):
        source = resolved_design(shell(), segmented=True)
        topology = build_electrode_topology(source)
        requested = dict(zip((r["electrode_group_id"] for r in topology), [23, 17, 31, 29, 37], strict=True))
        self.assertEqual(build_simion_electrode_map(source, topology, requested_native_ids=requested), requested)
        old = physical_electrode_view(source)
        legacy_map = {row["native_electrode_id"]: requested[group["electrode_group_id"]]
                      for row, group in zip(old, topology, strict=True)}
        body = render_physical_gem(source, .2, electrode_ids=legacy_map)
        for value in requested.values():
            self.assertIn(f"e({value})", body)
        self.assertEqual(build_electrode_topology(source), topology)
        self.assertEqual([r["scientific_id"] for r in old[:4]], [f"rod_group_{i}" for i in range(1, 5)])

    def test_missing_extra_bool_collision_zero_and_capacity_are_backend_errors(self):
        source = resolved_design(); topology = build_electrode_topology(source)
        for mapping in ({"rod_group_1": 1}, {"rod_group_1": 1, "rod_group_2": 2, "extra": 3},
                        {"rod_group_1": True, "rod_group_2": 2}, {"rod_group_1": 1, "rod_group_2": 1},
                        {"rod_group_1": 0, "rod_group_2": 2}, {"rod_group_1": 1, "rod_group_2": 1001}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                build_simion_electrode_map(source, topology, requested_native_ids=mapping)

    def test_legacy_actual_relabelled_table_agrees_with_geometry_and_voltage(self):
        from integrations.runtime.single_flight_electrode_contract import physical_multipole_voltages

        for labels in ([2, 1, 4, 3],):
            with self.subTest(labels=labels):
                source = resolved_design(shell(), segmented=True)
                neutral = build_electrode_topology(source)
                remap = dict(zip(range(1, 5), labels, strict=True))
                for member in source["segmentation"]["segmented_rod_array"]["electrodes"]:
                    member["electrode_id"] = remap[member["electrode_id"]]
                ground = max(labels) + 1
                view = physical_electrode_view(source)
                self.assertEqual({r["native_electrode_id"] for r in view}, {*labels, ground})
                self.assertEqual(build_electrode_topology(source), neutral)
                body = render_physical_gem(source, .2)
                for native in labels:
                    self.assertEqual(body.count(f"e({native})"), 2)
                self.assertEqual(body.count(f"e({ground})"), 1)
                volts, rf = physical_multipole_voltages(source, {i: i for i in [*labels, ground]})
                self.assertEqual(volts, {labels[0]: -1., labels[1]: -1., labels[2]: -2., labels[3]: -2., ground: 0.})
                self.assertEqual(rf, {labels[0]: 1, labels[1]: 2, labels[2]: 1, labels[3]: 2})
        source = resolved_design(segmented=True)
        source["segmentation"]["segmented_rod_array"]["electrodes"][2]["electrode_id"] = 3
        with self.assertRaisesRegex(ValueError, "conflicting native"):
            physical_electrode_view(source)

    def test_physically_described_many_segments_do_not_inherit_native_capacity(self):
        source = resolved_design(segmented=True)
        for rod in source["geometry_mm"]["rod_array"]["rods"]:
            rod.update(z_min_mm=2., z_max_mm=1003.)
        table = source["segmentation"]["segmented_rod_array"]
        table["segment_count"] = 501
        table["electrodes"] = [{**rod, "segment_id": segment, "z_min_mm": segment * 2.,
            "z_max_mm": segment * 2. + 1., "common_mode_V": -segment}
            for segment in range(1, 502) for rod in source["geometry_mm"]["rod_array"]["rods"]]
        topology = build_electrode_topology(source)
        self.assertEqual(len(topology), 1002)
        with self.assertRaisesRegex(ValueError, "capacity"):
            build_simion_electrode_map(source, topology)

    def test_incomplete_duplicate_conflicting_members_and_stale_topology_fail(self):
        source = resolved_design(segmented=True)
        for change in (lambda r: r.pop(), lambda r: r.append(copy.deepcopy(r[0])),
                       lambda r: r[2].update(common_mode_V=9), lambda r: r[0].pop("segment_id")):
            bad = copy.deepcopy(source); change(bad["segmentation"]["segmented_rod_array"]["electrodes"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_electrode_topology(bad)
        topology = build_electrode_topology(source)
        topology[0]["member_refs"].pop()
        with self.assertRaisesRegex(ValueError, "differs"):
            build_simion_electrode_map(source, topology)
        for alias in ("segment_0001_rf_group_1", "conflicting_old_group"):
            topology = build_electrode_topology(source)
            topology[0]['scientific_id'] = alias
            with self.subTest(old_alias=alias), self.assertRaisesRegex(ValueError, "differs"):
                build_simion_electrode_map(source, topology)

    def test_actual_compiler_providers_preserve_complete_member_coverage(self):
        for variant in ("quadrupole", "hexapole", "octupole"):
            request = design_request(variant)
            source = compile_design_request(request, expected_identity=request["identity"])
            topology = build_electrode_topology(source)
            members = [ref for group in topology for ref in group["member_refs"]]
            table = source["segmentation"]["segmented_rod_array"]
            expected = len(table["electrodes"]) if table else len(source["geometry_mm"]["rod_array"]["rods"])
            self.assertEqual(len(members), expected)
            self.assertEqual(len(set(members)), expected)


if __name__ == "__main__":
    unittest.main()
