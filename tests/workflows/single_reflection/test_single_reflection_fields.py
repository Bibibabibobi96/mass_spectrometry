"""Pure physical-field checks use their current backend owners."""
import unittest

from msplatform.backends.simion.fields import prepare_field_design, POLICY


class SingleReflectionFieldsTests(unittest.TestCase):
    def test_two_zone_geometry_is_not_claimed_as_a_supported_native_field_driver(self):
        with self.assertRaisesRegex(ValueError,'field/drive execution supports only three_zone_square'):
            prepare_field_design(None,{}, {},variant_id='two_zone_square',pulse_voltage_policy_id=POLICY,
                boundary_policy='native_zero_neumann',frontend_domains={})
    def test_box_intersection_distinguishes_absent_metal_and_unrepresented_metal(self):
        from msplatform.backends.simion.physical_samples import box_sample
        box = dict(x_min_mm=-2.,x_max_mm=2.,y_min_mm=-2.,y_max_mm=2.,z_min_mm=.2,z_max_mm=.3)
        kwargs = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]], translation=[0.,0.,0.],
                      origin=dict(x=-3.,y=-3.,z=0.),pitch=dict(x=1.,y=1.,z=1.),dimensions=dict(nx=7,ny=7,nz=3))
        bounds = dict(x_min=-3.,x_max=3.,y_min=-3.,y_max=3.,z_min=1.,z_max=2.)
        self.assertIsNone(box_sample(box,None,**kwargs,local_bounds_mm=bounds))
        bounds.update(z_min=0.,z_max=1.)
        with self.assertRaisesRegex(ValueError,'strictly inside'):
            box_sample(box,None,**kwargs,local_bounds_mm=bounds)
    def test_narrow_box_intersection_samples_present_metal_and_skips_absent_axes(self):
        from msplatform.backends.simion.physical_samples import box_sample
        box = dict(x_min_mm=-4.,x_max_mm=4.,y_min_mm=-4.,y_max_mm=4.,z_min_mm=-1.,z_max_mm=1.)
        hole = dict(x_min_mm=-2.,x_max_mm=2.,y_min_mm=-2.,y_max_mm=2.,z_min_mm=-2.,z_max_mm=2.)
        bounds = dict(x_min=-4.,x_max=-2.5,y_min=-1.,y_max=1.,z_min=-1.,z_max=1.)
        kwargs = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation=[0.,0.,0.],
            origin=dict(x=-4.,y=-4.,z=-2.),pitch=dict(x=.5,y=.5,z=.5),dimensions=dict(nx=17,ny=17,nz=9))
        gu = box_sample(box,hole,**kwargs,local_bounds_mm=bounds)
        self.assertLess(-4.+gu[0]*.5,-2.)
        self.assertIsNone(box_sample(box,hole,**kwargs,local_bounds_mm=dict(bounds,x_min=5.,x_max=6.)))
        self.assertIsNone(box_sample(box,hole,**kwargs,local_bounds_mm=dict(bounds,y_min=5.,y_max=6.)))
        self.assertIsNone(box_sample(box,hole,**kwargs,local_bounds_mm=dict(bounds,x_min=-1.,x_max=1.)))
        # There is real metal here, but neither neighboring grid node belongs
        # to this numerical intersection. A guard node must not substitute.
        with self.assertRaisesRegex(ValueError,'local numerical bounds'):
            box_sample(box,None,**kwargs,local_bounds_mm=dict(bounds,x_min=.2,x_max=.3))

if __name__ == "__main__":
    unittest.main()
