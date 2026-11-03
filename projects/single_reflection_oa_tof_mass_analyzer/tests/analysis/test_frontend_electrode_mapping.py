"""Provider domain and native-label permutations remain separate identities."""
from __future__ import annotations

import copy
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.electrode_topology import resolve_frontend_field_domain
from projects.single_reflection_oa_tof_mass_analyzer.simion.electrode_mapping import (
    native_frontend_electrodes, validate_frontend_electrode_map,
)
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_assembly_interface import (
    candidate_300mm_fixture, projected_candidate,
)


def domain_fixture():
    # Deliberately nonnumeric group order: it is provider order, not native order.
    groups = ["common_ground", "accelerator_repeller", "accelerator_intermediate_grid_1",
              "accelerator_intermediate_grid_2", "accelerator_exit_grid",
              "accelerator_ring_0002", "accelerator_ring_0001"]
    return dict(schema_version=1, role="oatof_frontend_field_domain",
                domain_id="accelerator_frontend", variant_id="three_zone_square",
                electrode_group_ids=groups,
                members=[dict(electrode_group_id=group,
                              member_refs=["/sources/oa_mechanical/" + group]) for group in groups])


class FrontendElectrodeMappingTests(unittest.TestCase):
    def test_asymmetric_planes_and_provider_ring_order_are_preserved(self):
        domain = domain_fixture()
        mapping = dict(zip(domain["electrode_group_ids"], [17, 23, 31, 29, 43, 97, 53], strict=True))
        before = copy.deepcopy((domain, mapping))
        self.assertEqual(native_frontend_electrodes(mapping, frontend_domain=domain), {
            "grounded_shield_id": 17, "accelerator_repeller_id": 23,
            "accelerator_grid1_id": 31, "accelerator_intermediate2_id": 29,
            "accelerator_grid2_id": 43, "accelerator_ring_ids": [97, 53],
        })
        validated = validate_frontend_electrode_map(mapping, frontend_domain=domain)
        self.assertEqual(validated, mapping)
        self.assertIsNot(validated, mapping)
        self.assertEqual((domain, mapping), before)
        permuted = {key: 1000 - value for key, value in mapping.items()}
        self.assertEqual(set(validate_frontend_electrode_map(permuted, frontend_domain=domain)), set(mapping))
        self.assertEqual(native_frontend_electrodes(permuted, frontend_domain=domain)["accelerator_ring_ids"], [903, 947])

    def test_actual_provider_domain_all_planes_and_rings(self):
        resolved = candidate_300mm_fixture()
        projection = projected_candidate(width=1, height=2)
        before = copy.deepcopy((resolved, projection))
        domain = resolve_frontend_field_domain(resolved, projection=projection)
        mapping = {group: 100 + 3 * index for index, group in enumerate(domain["electrode_group_ids"])}
        native = native_frontend_electrodes(mapping, frontend_domain=domain)
        self.assertEqual(native["accelerator_grid1_id"], mapping["accelerator_intermediate_grid_1"])
        self.assertEqual(native["accelerator_intermediate2_id"], mapping["accelerator_intermediate_grid_2"])
        self.assertEqual(native["accelerator_grid2_id"], mapping["accelerator_exit_grid"])
        self.assertEqual(native["accelerator_ring_ids"],
                         [mapping[f"accelerator_ring_{index:04d}"] for index in range(1, 21)])
        self.assertEqual(resolved, before[0])
        self.assertEqual(projection, before[1])

    def test_invalid_map_coverage_values_and_collisions_fail(self):
        domain = domain_fixture()
        valid = dict(zip(domain["electrode_group_ids"], range(1, 8), strict=True))
        missing = dict(valid); missing.pop("accelerator_exit_grid")
        extra = dict(valid, reflectron_backplate=8)
        invalid = [missing, extra]
        for value in (True, False, 1.0, "1", 0, -1, 1001, None):
            changed = dict(valid); changed["common_ground"] = value; invalid.append(changed)
        collision = dict(valid); collision["common_ground"] = collision["accelerator_exit_grid"]
        invalid.append(collision)
        for mapping in invalid:
            before = copy.deepcopy(mapping)
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                native_frontend_electrodes(mapping, frontend_domain=domain)
            self.assertEqual(mapping, before)

    def test_unknown_or_malformed_provider_domain_fails(self):
        domain = domain_fixture()
        mapping = dict(zip(domain["electrode_group_ids"], range(1, 8), strict=True))
        mutations = [lambda d: d.update(schema_version=2), lambda d: d.update(schema_version=True),
                     lambda d: d.update(role="other"), lambda d: d.update(domain_id="other"),
                     lambda d: d.update(variant_id="two_zone_square"),
                     lambda d: d["electrode_group_ids"].append("common_ground"),
                     lambda d: d["electrode_group_ids"].__setitem__(0, "grounded_shield"),
                     lambda d: d["members"][0].update(member_refs=[])]
        for mutate in mutations:
            changed = copy.deepcopy(domain); mutate(changed)
            with self.subTest(domain=changed), self.assertRaises(ValueError):
                validate_frontend_electrode_map(mapping, frontend_domain=changed)
