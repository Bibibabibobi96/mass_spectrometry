from __future__ import annotations

import unittest

from common.multipole.connector_geometry import resolve_connector_section


class ConnectorGeometryTests(unittest.TestCase):
    def test_zero_length_creates_no_section_for_both_shapes(self) -> None:
        for shape in ("rectangular_bore", "cylindrical_bore"):
            self.assertIsNone(
                resolve_connector_section(
                    shape=shape, length_mm=0, aperture_radius_mm=1.2, outer_size_mm=10
                )
            )

    def test_both_supported_shapes_preserve_dimensions(self) -> None:
        for shape in ("rectangular_bore", "cylindrical_bore"):
            section = resolve_connector_section(
                shape=shape, length_mm=1.0, aperture_radius_mm=1.2, outer_size_mm=10
            )
            self.assertEqual(section["shape"], shape)
            self.assertEqual(section["length_mm"], 1.0)

    def test_unknown_shape_and_invalid_wall_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported connector shape"):
            resolve_connector_section(shape="square", length_mm=1, aperture_radius_mm=1, outer_size_mm=2)
        with self.assertRaisesRegex(ValueError, "outer size"):
            resolve_connector_section(
                shape="cylindrical_bore", length_mm=1, aperture_radius_mm=2, outer_size_mm=2
            )


if __name__ == "__main__":
    unittest.main()
