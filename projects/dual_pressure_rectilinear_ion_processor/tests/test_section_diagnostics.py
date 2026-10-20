"""Independent plane-intersection checks for auxiliary-electrode axial views."""
import unittest
from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import (
    section, subtract, parts, section_centroid, SectionDiagnostics, world_bounds,
)


def wedge():
    """Triangular yz prism with exact area 2 mm² and longitudinal length 10 mm."""
    return dict(shape='convex_polyhedron', vertices_mm=[
        [x,y,z] for x in (0,10) for y,z in ((0,0),(2,0),(0,2))])


def area(points):
    points=list(points)
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(points,points[1:]+points[:1]))/2)


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

    def test_wedge_sections_use_actual_sloped_faces(self):
        shape=wedge()
        kind,polygon=section(shape,'cross',5,9.8)
        self.assertEqual(kind,'polygon')
        self.assertEqual(len(polygon),3)
        self.assertAlmostEqual(area(polygon),2)
        center=section_centroid(kind,polygon)
        self.assertAlmostEqual(center[0],-2/3)
        self.assertAlmostEqual(center[1],9.8-2/3)
        self.assertIsNone(section(shape,'cross',11,9.8))
        self.assertAlmostEqual(area(section(shape,'top',9.3,9.8)[1]),15)
        low,high=world_bounds(shape,9.8)
        self.assertEqual(low,[-2,0,7.800000000000001])
        self.assertEqual(high,[0,10,9.8])

    def test_wedge_rectangular_cut_retains_exact_metal_area(self):
        electrode=dict(electrode_id=9,solids=[wedge()],cutouts=[
            dict(shape='box',min_mm=[0,0,0],max_mm=[10,.5,2])])
        pieces=parts(electrode,'cross',5,9.8)
        self.assertTrue(all(kind=='polygon' for kind,p in pieces))
        self.assertAlmostEqual(sum(area(p) for kind,p in pieces),1.125)
        self.assertTrue(all(section_centroid(kind,p)[1] <= 9.3 for kind,p in pieces))

    def test_polygon_render_and_field_outlines_are_headless_and_not_bounds(self):
        from matplotlib import pyplot as plt
        from matplotlib.patches import Polygon
        from projects.dual_pressure_rectilinear_ion_processor.analysis.field_diagnostics import add_electrode_outlines
        electrode=dict(electrode_id=9,solids=[wedge()],cutouts=[])
        context=SectionDiagnostics();context.ELECTRODES=[electrode];context.origin_z_mm=9.8
        figure,axes=plt.subplots(1,3)
        context.draw_geometry(axes[0],'cross',5)
        context.draw_e9_projection(axes[1])
        add_electrode_outlines(axes[2],dict(electrodes=[electrode]),5)
        for ax in axes:
            self.assertTrue(all(isinstance(p,Polygon) for p in ax.patches))
            self.assertGreater(len(ax.patches),0)
        self.assertAlmostEqual(area(axes[0].patches[0].get_xy()),2)
        self.assertAlmostEqual(area(axes[2].patches[0].get_xy()),2)
        figure.canvas.draw()
        plt.close(figure)

    def test_polygon_cut_outlines_rotate_vertices_not_bounding_rectangles(self):
        from matplotlib import pyplot as plt
        from projects.dual_pressure_rectilinear_ion_processor.analysis.field_diagnostics import add_electrode_outlines
        config=dict(coordinate_transform=dict(schema_version=1,role='rigid_transform',
            from_frame_id='dual_pressure_ion_processor_local_v1',to_frame_id='fixture_world',
            rotation=[[0,0,-1],[1,0,0],[0,-1,0]],translation_mm=[0,0,9.8]))
        electrode=dict(electrode_id=9,solids=[wedge()],cutouts=[
            dict(shape='box',min_mm=[0,0,0],max_mm=[10,.5,2])])
        figure,ax=plt.subplots()
        add_electrode_outlines(ax,dict(electrodes=[electrode]),5,config)
        self.assertAlmostEqual(sum(area(p.get_xy()) for p in ax.patches),1.125)
        self.assertEqual(len(ax.texts),len(ax.patches))
        figure.canvas.draw();plt.close(figure)

if __name__=='__main__':unittest.main()
