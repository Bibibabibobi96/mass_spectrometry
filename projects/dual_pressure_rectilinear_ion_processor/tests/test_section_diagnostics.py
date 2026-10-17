"""Independent plane-intersection checks for auxiliary-electrode axial views."""
import unittest
from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import section, subtract, parts


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


    def test_aperture_subtraction_keeps_only_the_surrounding_metal(self):
        rectangles = subtract((0, 0, 10, 10), (3, 2, 7, 8))
        self.assertEqual(sum((c-a)*(d-b) for a,b,c,d in rectangles), 76)
        for x,y,expected in ((1,5,True),(5,1,True),(5,9,True),(9,5,True),(5,5,False)):
            self.assertEqual(any(a <= x <= c and b <= y <= d for a,b,c,d in rectangles), expected)
        self.assertEqual(subtract((0,0,1,1),(2,2,3,3)),[(0,0,1,1)])
        self.assertEqual(subtract((0,0,1,1),(-1,-1,2,2)),[])

    def test_longitudinal_cutout_removes_aperture_from_frozen_csg(self):
        electrode = dict(solids=[dict(shape='box',min_mm=[0,-2,-2],max_mm=[10,2,2])],
                         cutouts=[dict(shape='box',min_mm=[3,-1,-3],max_mm=[7,1,3])])
        rectangles = [bounds for kind,bounds in parts(electrode,'long',0,9.8) if kind == 'rect']
        self.assertAlmostEqual(sum((c-a)*(d-b) for a,b,c,d in rectangles), 32)
        self.assertFalse(any(a <= 5 <= c and b <= 9.8 <= d for a,b,c,d in rectangles))

if __name__=='__main__':unittest.main()
