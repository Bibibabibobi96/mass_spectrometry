"""Shared physical voltage source parsing retains the original lookup contract."""
import unittest
from msplatform.contracts.electrode_sources import physical_voltage_value


class ElectrodeSourceTests(unittest.TestCase):
    def test_escaped_keys_lists_and_finite_values(self):
        source = {'a/b': {'~key': [3, -2.5]}}
        self.assertEqual(physical_voltage_value(source, '/a~1b/~0key/0'), 3.0)
        self.assertEqual(physical_voltage_value(source, '/a~1b/~0key/1'), -2.5)

    def test_missing_and_nonfinite_or_boolean_values_fail(self):
        for pointer in ('/missing', '/items/2', '/items/-1'):
            with self.subTest(pointer=pointer), self.assertRaisesRegex(ValueError, 'voltage source is missing'):
                physical_voltage_value({'items': [1]}, pointer)
        for value in (True, False, float('nan'), float('inf'), float('-inf'), '1'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'voltage source is not finite'):
                physical_voltage_value({'v': value}, '/v')