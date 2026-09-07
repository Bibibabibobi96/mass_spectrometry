"""Device-independent regression for the legacy-GEM serialization primitives."""
import unittest

from common.simion.gem_primitives import centered_box3d, cylinder_z, format_number


class GemPrimitivesTest(unittest.TestCase):
    def test_box_and_sheet_bytes(self) -> None:
        self.assertEqual(centered_box3d(1.2, -.4, 3, 8, 8, 0),
                         'centered_box3D(1.2,-0.4,3,8,8,0)')

    def test_cylinder_bytes(self) -> None:
        self.assertEqual(cylinder_z(1.2, -.4, 3, 4, 0),
                         'locate(1.2,-0.4,3) { cylinder(0,0,0,4,,0) }')

    def test_nonfinite_values_fail_closed(self) -> None:
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                format_number(value)


if __name__ == '__main__':
    unittest.main()
