"""Gas lookup behavior oracles at physical boundaries, masks and proper poses."""
from dataclasses import replace
import math
import unittest
from unittest.mock import patch
from msplatform.contracts.gas import (AxisymmetricRZData, BoxDomain, CylindricalDomain,
    GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState, UnboundedDomain)
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
from msplatform.gas.field import prepare_gas_field, sample_gas

GAS = GasState("gas", 1, 300, (100, 0, 0))
COMPOSITION = (GasSpecies("N2", 28, 1),)


def spec(kind="uniform", **kwargs):
    values = dict(field_id="declared", frame_id="local", representation=kind, composition_id="n2",
                  composition=COMPOSITION, domain=UnboundedDomain(), source=GasSource("prescribed", "explicit_input", ()),
                  uniform_state=GAS if kind == "uniform" else None)
    values.update(kwargs)
    return GasFieldSpec(**values)


def point(x, y=0, z=0, frame="local"):
    return FramedPosition(frame, (x, y, z))


class GasSamplingTests(unittest.TestCase):
    def test_uniform_uses_explicit_domain_and_distinguishes_vacuum_from_outside(self):
        domain = BoxDomain((0, -2, -2), (10, 2, 2), (True,)*3, (False,)*3)
        field = prepare_gas_field(spec(domain=domain))
        self.assertEqual(sample_gas(field, point(0)).state.pressure_pa, 1)
        self.assertEqual(sample_gas(field, point(10)).state.status, "outside_domain")
        vacuum = prepare_gas_field(spec(uniform_state=GasState("vacuum", 0)))
        self.assertEqual(sample_gas(vacuum, point(10000)).number_density_m3, 0)
        self.assertIsNone(sample_gas(field, point(10)).number_density_m3)
        # No 400Pa-specific restriction in the neutral provider.
        self.assertEqual(sample_gas(prepare_gas_field(spec(uniform_state=GasState("gas", 713, 310, (0, 0, 0)))), point(0)).state.pressure_pa, 713)

    def test_ip_regions_keep_half_open_interface_strict_transverse_and_no_210_cap(self):
        hp = GasRegion("hp", BoxDomain((30, -2, -2), (130, 2, 2), (True, False, False), (False, False, False)), GAS)
        lp = GasRegion("lp", BoxDomain((130, -2, -2), (250, 2, 2), (True, False, False), (True, False, False)), GasState("gas", .2, 300, (0, 0, 0)))
        field = prepare_gas_field(spec("piecewise_uniform", regions=(hp, lp), background_state=GasState("vacuum", 0), domain=BoxDomain((0,-5,-5),(250,5,5),(True,)*3,(True,)*3)))
        for x, expected in ((math.nextafter(30, -math.inf), 0), (30, 1),
                            (math.nextafter(130, -math.inf), 1), (130, .2), (211, .2)):
            self.assertEqual(sample_gas(field, point(x)).state.pressure_pa, expected)
        self.assertEqual(sample_gas(field, point(50, 2)).state.status, "vacuum")
        self.assertEqual(sample_gas(field, point(50, math.nextafter(2, 0))).state.status, "gas")
        self.assertEqual(sample_gas(field, point(251)).state.status, "outside_domain")

    def test_overlap_rejects_shared_closed_face_but_not_half_open_neighbors(self):
        a = GasRegion("a", BoxDomain((0,0,0),(1,1,1),(True,)*3,(True,)*3), GAS)
        b = GasRegion("b", BoxDomain((1,0,0),(2,1,1),(True,)*3,(True,)*3), GAS)
        with self.assertRaisesRegex(ValueError, "overlap"):
            prepare_gas_field(spec("piecewise_uniform", regions=(a,b), background_state=GasState("no_data")))
        a = replace(a, domain=replace(a.domain, upper_closed=(False,True,True)))
        self.assertEqual(sample_gas(prepare_gas_field(spec("piecewise_uniform", regions=(a,b), background_state=GasState("no_data"))), point(1,.5,.5)).region_id, "b")

    def test_noncommuting_pose_rotates_velocity_without_translation_or_pitch(self):
        # Ry(90) @ Rz(90): local(1,2,3) -> (3,1,2); vector(100,0,0)->(0,100,0).
        pose = RigidTransform("local", "world", ((0,0,1),(1,0,0),(0,1,0)), (10,20,30))
        field = prepare_gas_field(spec(domain=BoxDomain((0,0,0),(2,3,4),(True,)*3,(True,)*3)))
        result = sample_gas(field, point(13,21,32,"world"), placement=pose)
        self.assertEqual(result.state.bulk_velocity_m_s, (0,100,0))
        self.assertEqual(result.state.pressure_pa, 1)
        self.assertEqual(result.frame_id, "world")
        with self.assertRaises(ValueError):
            sample_gas(field, point(1,frame="unbound"))
        with self.assertRaises(ValueError):
            sample_gas(field, point(13,21,32,"world"), placement=RigidTransform.identity("other"))

    def grid(self, mask=(True,True,True,True)):
        arrays = [(100,200,300,400), (300,300,300,300), (0,10,0,10), (100,100,100,100)]
        arrays = [tuple(v if m else None for v,m in zip(a,mask)) for a in arrays]
        data = AxisymmetricRZData((0,1),(0,1),mask,*arrays)
        field = prepare_gas_field(spec("axisymmetric_rz_grid",domain=CylindricalDomain(0,1,1), interpolation_policy="bilinear_fluid_corner_weight_renormalization_v1"), data=data)
        return field

    def test_grid_corner_bilinear_mask_renormalization_axis_and_last_cell(self):
        field = self.grid()
        self.assertEqual(sample_gas(field, point(0,0,0)).state.pressure_pa, 100)
        self.assertEqual(sample_gas(field, point(1,0,1)).state.pressure_pa, 400)
        self.assertEqual(sample_gas(field, point(.5,0,.5)).state.pressure_pa, 250)
        self.assertEqual(sample_gas(field, point(0,0,.5)).state.bulk_velocity_m_s, (0,0,100))
        off_axis = sample_gas(field, point(.3,.4,.5))
        self.assertEqual(off_axis.state.bulk_velocity_m_s, (3,4,100))
        masked = self.grid((True,True,True,False))
        self.assertEqual(sample_gas(masked, point(.5,0,.5)).state.pressure_pa, 200)
        self.assertEqual(sample_gas(masked, point(1,0,1)).state.status, "no_data")
        self.assertEqual(sample_gas(field, point(1.01)).state.status, "outside_domain")

    def test_sampling_preserves_raw_data_precision_and_no_support_is_not_solid(self):
        field = self.grid((False,False,False,False))
        self.assertEqual(sample_gas(field, point(.5,0,.5)).state.status, "no_data")
        self.assertIsNone(sample_gas(field, point(.5,0,.5)).state.pressure_pa)
        field = self.grid()
        data = replace(field.data,pressure_pa=(100.123456789,)*4)
        field = prepare_gas_field(field.spec,data=data)
        self.assertEqual(sample_gas(field,point(0)).state.pressure_pa,100.123456789)

    def test_query_does_not_read_hash_launch_or_draw_random(self):
        field = prepare_gas_field(spec())
        with patch("builtins.open", side_effect=AssertionError("no IO")), patch("subprocess.Popen", side_effect=AssertionError("no process")), patch("random.random", side_effect=AssertionError("no RNG")):
            self.assertEqual(sample_gas(field,point(0)).state.pressure_pa,1)

    def test_grid_data_is_explicit_and_representation_not_guessed(self):
        with self.assertRaises(ValueError):
            prepare_gas_field(spec("axisymmetric_rz_grid",domain=CylindricalDomain(0,1,1),interpolation_policy="bilinear_fluid_corner_weight_renormalization_v1"))
        with self.assertRaises(ValueError):
            prepare_gas_field(spec(),data=self.grid().data)

    def test_axis_regularity_violation_rejects_instead_of_discarding_radial_flow(self):
        field = self.grid()
        for radial in ((10,10,0,10), (0,10,1e-300,10)):
            with self.subTest(radial=radial):
                with self.assertRaisesRegex(ValueError, "zero radial velocity at r=0"):
                    replace(field.data, radial_velocity_m_s=radial)
        # A masked axis node is unavailable, not an inferred solid or a zero-flow sample.
        missing = self.grid((False,True,False,True))
        self.assertEqual(sample_gas(missing,point(0,0,.5)).state.status,"no_data")

    def test_cooled_bath_half_open_strict_boundaries_and_explicit_zero_control(self):
        bath = BoxDomain((30,-2,-2),(130,2,2),(True,False,False),(False,False,False))
        valid = BoxDomain((0,-5,-5),(250,5,5),(True,)*3,(True,)*3)
        full = prepare_gas_field(spec("piecewise_uniform", domain=valid,
            regions=(GasRegion("cooled_bath",bath,GasState("gas",1,300,(0,0,0))),),
            background_state=GasState("vacuum",0)))
        zero = prepare_gas_field(spec("piecewise_uniform", domain=valid,
            regions=(GasRegion("cooled_bath",bath,GasState("vacuum",0,300,(0,0,0))),),
            background_state=GasState("vacuum",0)))
        # Independent original finite-bath boundary vectors. Voltage release is not
        # a gas-field argument: the same static field remains present after release.
        vectors = ((30,0,0,1),(math.nextafter(30,-math.inf),0,0,0),
                   (math.nextafter(130,-math.inf),0,0,1),(130,0,0,0),
                   (50,2,0,0),(50,0,-2,0),(50,math.nextafter(2,0),0,1))
        for x,y,z,pressure in vectors:
            with self.subTest(position=(x,y,z)):
                self.assertEqual(sample_gas(full,point(x,y,z)).state.pressure_pa,pressure)
                sample = sample_gas(zero,point(x,y,z))
                self.assertEqual(sample.state.status,"vacuum")
                self.assertEqual(sample.state.pressure_pa,0)
                self.assertEqual(sample.number_density_m3,0)
        self.assertEqual(sample_gas(zero,point(251)).state.status,"outside_domain")

    def test_prepared_field_retains_proxy_semantics_and_rejects_opaque_source_label(self):
        source = GasSource("prescribed_proxy", "zero_collision_control", ("collisions omitted, not measured vacuum",))
        field = prepare_gas_field(spec(source=source,uniform_state=GasState("vacuum",0)))
        self.assertIs(field.spec.source, source)
        self.assertEqual(field.spec.source.kind,"prescribed_proxy")
        self.assertIn("not measured vacuum",field.spec.source.assumptions[0])
        with self.assertRaisesRegex(ValueError,"typed kind"):
            spec(source="opaque")

    def test_exact_valid_corner_needs_no_zero_weight_neighbor_support(self):
        field = self.grid((True, False, False, False))
        sample = sample_gas(field, point(0, 0, 0))
        self.assertEqual(sample.state.status, "gas")
        self.assertEqual(sample.state.pressure_pa, 100)
        self.assertEqual(sample.state.temperature_k, 300)
        self.assertEqual(sample.state.bulk_velocity_m_s, (0, 0, 100))
        # Neighbor mask bits describe missing data, never trusted solid geometry.
        self.assertEqual(sample_gas(field, point(.5, 0, .5)).state.pressure_pa, 100)

    def test_exact_missing_corner_cannot_borrow_zero_weight_valid_neighbors(self):
        field = self.grid((True, True, True, False))
        sample = sample_gas(field, point(1, 0, 1))
        self.assertEqual(sample.state.status, "no_data")
        self.assertIsNone(sample.state.pressure_pa)
        self.assertIsNone(sample.state.temperature_k)
        self.assertIsNone(sample.state.bulk_velocity_m_s)
        self.assertIsNone(sample.number_density_m3)
        # Moving into the cell restores positive support; all quantities use it.
        supported = sample_gas(field, point(.25, 0, .25))
        self.assertEqual(supported.state.pressure_pa, 160)
        self.assertEqual(supported.state.temperature_k, 300)
        self.assertEqual(supported.state.bulk_velocity_m_s, (2, 0, 100))

    def test_thin_bath_point_sequences_do_not_claim_step_crossing_resolution(self):
        bath = BoxDomain((-.1, -1, -1), (.1, 1, 1),
                         (True, False, False), (False, False, False))
        field = prepare_gas_field(spec("piecewise_uniform",
            regions=(GasRegion("thin", bath, GAS),),
            background_state=GasState("vacuum", 0)))
        sequences = (
            ("forward", ((-1, 0, 0), (0, 0, 0), (1, 0, 0)), (0, 1, 0)),
            ("reverse", ((1, 0, 0), (0, 0, 0), (-1, 0, 0)), (0, 1, 0)),
            ("diagonal", ((-1, -2, 0), (0, 0, 0), (1, 2, 0)), (0, 1, 0)),
            ("tangent", ((-1, 1, 0), (0, 1, 0), (1, 1, 0)), (0, 0, 0)),
            ("endpoints_only", ((-1, 0, 0), (1, 0, 0)), (0, 0)),
        )
        for name, positions, pressures in sequences:
            with self.subTest(sequence=name):
                self.assertEqual(tuple(sample_gas(field, point(*p)).state.pressure_pa
                                       for p in positions), pressures)
        # This is a point sampler, not an integrator: vacuum endpoints do not
        # certify a vacuum path or a resolved collision history through the bath.
        self.assertEqual(sample_gas(field, point(-.1)).state.status, "gas")
        self.assertEqual(sample_gas(field, point(.1)).state.status, "vacuum")

    def test_same_particle_time_labels_do_not_replace_query_position(self):
        bath = BoxDomain((30, -2, -2), (130, 2, 2),
                         (True, False, False), (False, False, False))
        field = prepare_gas_field(spec("piecewise_uniform",
            regions=(GasRegion("bath", bath, GAS),),
            background_state=GasState("vacuum", 0)))
        # Labels belong to a future callback consumer, not the static sampler API.
        # The same ID/time at separate substage positions must query independently.
        requests = ((7, 10, point(29)), (7, 10, point(31)), (7, 10, point(29)))
        self.assertEqual({(pid, time) for pid, time, _ in requests}, {(7, 10)})
        self.assertEqual(tuple(sample_gas(field, position).state.pressure_pa
                               for _, _, position in requests), (0, 1, 0))
