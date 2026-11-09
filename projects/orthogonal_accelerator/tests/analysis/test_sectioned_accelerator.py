"""Byte-level migration regressions for two/three-zone square/circular CSG."""
from __future__ import annotations

import hashlib
import unittest


def sample_geometry(cross_section: str, three_zone: bool) -> tuple[dict, dict]:
    """Small resolved fixture independent of any instrument artifacts."""
    geometry = {
        'axis_x_mm': 1.2, 'axis_y_mm': -0.4, 'cross_section': cross_section,
        'shield_center_z_mm': 5.0, 'shield_outer_width_mm': 12.0,
        'shield_inner_width_mm': 10.0, 'shield_span_z_mm': 14.0,
        'negative_x_face_mm': -4.8, 'shield_wall_mm': 1.0,
        'port_center_y_mm': -0.4, 'port_center_z_mm': 1.5,
        'numerical_port_width_mm': 2.0, 'numerical_port_height_mm': 1.0,
        'shield_back_z_mm': -2.0, 'repeller_front_z_mm': 0.0,
        'repeller_thickness_mm': 1.0, 'electrode_width_mm': 8.0,
        'grid1_z_mm': 3.0, 'grid2_z_mm': 12.0, 'intermediate2_z_mm': 7.0,
        'ring_thickness_mm': 1.0, 'bore_width_mm': 4.0,
        'ring_count': 2, 'ring_pitch_mm': 3.0,
        'ring_z_mm': [5.0, 9.0] if three_zone else [6.0, 9.0],
    }
    electrodes = {
        'grounded_shield_id': 9, 'accelerator_repeller_id': 10,
        'accelerator_grid1_id': 11, 'accelerator_ring_ids': [13, 14],
        'accelerator_grid2_id': 15,
    }
    if three_zone:
        electrodes['accelerator_intermediate2_id'] = 12
    return geometry, electrodes


class SectionedAcceleratorTest(unittest.TestCase):
    def test_migration_preserves_two_three_zone_square_circular_bytes(self) -> None:
        from msplatform.backends.simion.accelerator_renderer import render_accelerator_local_geometry

        # Square projections remain frozen; cylindrical side-entry tools now
        # cross the curved inner wall instead of leaving off-axis metal.
        expected = {
            ('square', False): 'db18f736e354c16c0e9481ea6614487e2ba1494cfd3eb3646e199776ea1be510',
            ('square', True): '891986898a8eefa73ccbd102684342c177d888f4f090bb53da182fcc7c71fe74',
            ('cylindrical', False): '8f0a85afff7acaad3cbc51ae369747ab68fcbd197362f7a4db2583f1a2d2c349',
            ('cylindrical', True): '3ccf4a082e8f8c37a4fce7ede262e2c5104e30dff7ac55062a8190d4651638f3',
        }
        for (cross_section, three_zone), digest in expected.items():
            with self.subTest(cross_section=cross_section, three_zone=three_zone):
                geometry, electrodes = sample_geometry(cross_section, three_zone)
                lines = render_accelerator_local_geometry(
                    geometry, cell_x_mm=0.25, cell_z_mm=0.1,
                    electrodes=electrodes, render_intermediate2_sheet=three_zone,
                )
                self.assertEqual(hashlib.sha256('\n'.join(lines).encode()).hexdigest(), digest)
        self.assertEqual(len(expected), 4)


if __name__ == '__main__':
    unittest.main()
