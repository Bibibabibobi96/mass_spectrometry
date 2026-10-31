"""Bounded ideal-grid interface checks exercise the actual Lua IOB verifier."""
from __future__ import annotations

import copy
import unittest

from integrations.tests import test_single_reflection_runtime as support
from integrations.workflows.single_reflection_flight.runtime import interface_field_probes


@unittest.skipUnless(support.LUA.is_file(), 'plain Lua interpreter unavailable')
class InterfaceFieldTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.FourSlotIobTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_probe_surfaces_follow_resolved_geometry_and_preserve_inputs(self):
        geometry, oatof = self.fixture.geometry, self.fixture.interface_oatof
        before = copy.deepcopy((geometry, oatof))
        probes = interface_field_probes(geometry, oatof)
        self.assertEqual([p['instance_index'] for p in probes], [3, 2])
        self.assertEqual([p['points_mm'][0][2] for p in probes],
                         [geometry['accelerator_projection']['grid2_z_mm'], oatof['geometry_mm']['L_flight']])
        self.assertEqual([len(p['points_mm']) for p in probes], [5, 5])
        self.assertEqual((geometry, oatof), before)
        for p in probes:
            self.assertEqual(p['expected_potential_v'], 0.)
            self.assertIn('edge coupling unqualified', p['validity_scope'])

    def test_real_verifier_accepts_ideal_sheet_normal_jump_and_reports_world_units(self):
        result = self.fixture.invoke('verify_success')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SINGLE_REFLECTION_INTERFACE_FIELDS=PASS', result.stdout)
        self.assertIn('FINITE_GRID_EDGE_COUPLING=unqualified', result.stdout)
        self.assertEqual(result.stdout.count('SINGLE_REFLECTION_INTERFACE_PLANE '), 20)
        self.assertEqual(result.stdout.count('SINGLE_REFLECTION_INTERFACE_SIDE '), 20)
        # The anisotropic cylindrical axial field is 2.5 V/gu / 0.25 mm/gu,
        # then the official instance orientation maps local X onto world Z.
        row = next(line for line in result.stdout.splitlines()
                   if 'label=reflectron_entry sample=1 side=plus' in line)
        self.assertIn('ez_v_per_mm=10 ', row)
        self.assertIn('normal_jump=allowed_ideal_electrode', row)

    def test_invalid_physical_or_native_interface_facts_fail_closed(self):
        cases = {
            'verify_missing_interfaces': 'resolved interface field probes are required',
            'verify_interface_response': 'interface plane potential differs',
            'verify_interface_potential': 'interface plane potential differs',
            'verify_interface_metal': 'interface physical grounded grid node differs',
            'verify_interface_nonfinite': 'nonfinite interface field',
        }
        for mode, expected in cases.items():
            with self.subTest(mode=mode):
                result = self.fixture.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertNotIn('SINGLE_REFLECTION_INTERFACE_FIELDS=PASS', result.stdout)

    def test_frozen_real_endpoint_roundoff_is_bounded_without_moving_the_plane(self):
        accepted = self.fixture.invoke('verify_interface_endpoint_roundoff')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertIn('original_gu=3200.0000000000005 query_gu=3200', accepted.stdout)
        self.assertIn('z_mm=278.07081319658903', accepted.stdout)
        rejected = self.fixture.invoke('verify_interface_outside')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('fixture z outside PA', rejected.stdout + rejected.stderr)
        self.assertNotIn('SINGLE_REFLECTION_INTERFACE_FIELDS=PASS', rejected.stdout)


if __name__ == '__main__':
    unittest.main()
