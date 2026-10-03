"""Static interface guards; actual ES/handoff regression is separately frozen."""
from pathlib import Path
import re
import unittest


SOURCE = (
    Path(__file__).resolve().parents[2]
    / 'comsol/configure_corridor_reference_electrostatics.m'
).read_text(encoding='utf-8')


class CorridorReferenceElectrostaticsTest(unittest.TestCase):
    def test_numeric_mm_interface_keeps_volts_and_rejects_extrapolation(self) -> None:
        self.assertEqual(re.findall(r"f\.set\('argunit',\s*\{([^}]+)\}\)", SOURCE), ["'1','1'"])
        self.assertEqual(re.findall(r"f\.set\('fununit',\s*\{([^}]+)\}\)", SOURCE), ["'V'"])
        self.assertEqual(re.findall(r"f\.set\('extrap',\s*'([^']+)'\)", SOURCE), ['none'])
        self.assertIn("numericMm = sprintf('(%s)/(1[mm])'", SOURCE)
        self.assertIn('snap_endpoint_expression(numericMm,', SOURCE)
        self.assertIn("functionName, snapped{1}, snapped{2}", SOURCE)

    def test_full_domain_reflects_into_positive_half_grid(self) -> None:
        self.assertIn("{'y,z','abs(x),z','abs(x),z','abs(x),y','abs(x),y','y,z'}", SOURCE)
        self.assertIn('gridLow = [0, box(2:3)];', SOURCE)
        self.assertIn('gridHigh = box(4:6);', SOURCE)
        self.assertIn('argumentAxes = [2,3;1,3;1,3;1,2;1,2;2,3];', SOURCE)
        self.assertIn('functionName = faces(1).function_name;', SOURCE)

    def test_endpoint_snap_is_bounded_and_leaves_interior_unchanged(self) -> None:
        self.assertIn('tolerance = 16 * eps(max([1, abs(low), abs(high)]));', SOURCE)
        self.assertIn('if((%s)<%.17g&&(%s)>=%.17g,%.17g,', SOURCE)
        self.assertIn('if((%s)>%.17g&&(%s)<=%.17g,%.17g,(%s)))', SOURCE)
        self.assertIn('value, low, value, low-tolerance, low,', SOURCE)
        self.assertIn('value, high, value, high+tolerance, high, value', SOURCE)


if __name__ == '__main__':
    unittest.main()
