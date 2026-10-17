"""Independent plane-intersection checks for auxiliary-electrode axial views."""
import unittest
from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import section


class EquatorialSectionTests(unittest.TestCase):
    def test_auxiliary_box_preserves_axial_length_and_transverse_width(self):
        shape=dict(shape='box',min_mm=[168.75,-.15,1.4],max_mm=[171.25,.15,1.6])
        self.assertEqual(section(shape,'top',9.8,9.8),('rect',(168.75,-1.6,171.25,-1.4)))
        self.assertIsNone(section(shape,'top',10.1,9.8))

    def test_cylinder_longitudinal_section_uses_correct_radial_center(self):
        shape=dict(shape='cylinder_x',x_min_mm=0,x_max_mm=29,center_y_mm=0,center_z_mm=2.6,radius_mm=.6)
        kind,bounds=section(shape,'top',9.8,9.8)
        self.assertEqual(kind,'rect')
        for actual,expected in zip(bounds,(0,-3.2,29,-2)):
            self.assertAlmostEqual(actual,expected)


if __name__=='__main__':unittest.main()
