"""T2 actual generated Lua 5.1 lookup; no SIMION callbacks or collision claims."""
from dataclasses import replace
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts import test_gas_field_sampling as fixtures
from common.contracts.test_simion_prepared_model import LUA
from msplatform.backends.simion.gas_runtime import compile_gas_runtime
from msplatform.backends.simion.source import lua_value
from msplatform.contracts.gas import (AxisymmetricRZData, BoxDomain, CylindricalDomain,
    GasRegion, GasSource, GasState)
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.gas.field import prepare_gas_field, sample_gas


@unittest.skipUnless(LUA.is_file(), "installed standalone Lua 5.1 unavailable")
class GasRuntimeTests(unittest.TestCase):
    def test_actual_joint_cylindrical_and_legacy_annular_grid(self):
        from msplatform.contracts.gas import AxisymmetricGasRegion, AxisymmetricGasValues

        field=prepare_gas_field(fixtures.spec('axisymmetric_piecewise_uniform',domain=CylindricalDomain(-5,120,23.5),
            sampling_profile='legacy_sqrt_v1',axisymmetric_background=AxisymmetricGasValues('vacuum',0,300,0,0),
            axisymmetric_regions=(AxisymmetricGasRegion('rear',3,120,True,True,AxisymmetricGasValues('gas',400,300,-5,100)),)))
        self.assert_matches(field,[(.3,.4,3),(0,0,3),(.3,.4,math.nextafter(3,-math.inf)),(0,0,120),(24,0,3)])
        pose=RigidTransform('local','world',((0,0,1),(1,0,0),(0,1,0)),(10,20,30))
        self.assert_matches(field,[(13,20.3,30.4)],placement=pose)
        data=AxisymmetricRZData((1,2,3),(0,1,2),(True,)*9,(100,)*9,(300,)*9,(-5,)*9,(10,)*9)
        annular=prepare_gas_field(fixtures.spec('axisymmetric_rz_grid',domain=CylindricalDomain(0,2,3,1),
            interpolation_policy='bilinear_fluid_corner_weight_renormalization_v1',sampling_profile='legacy_sqrt_v1'),data=data)
        self.assert_matches(annular,[(0,0,1),(1,0,0),(3,0,2),(math.nextafter(1,0),0,1),(2,0,1)])
        axis=replace(data,r_values_mm=(0,1,2),radial_velocity_m_s=(1e-14,)*9,
                     axis_projection_policy='legacy_axis_projection_v1')
        legacy=prepare_gas_field(fixtures.spec('axisymmetric_rz_grid',domain=CylindricalDomain(0,2,2),
            interpolation_policy='bilinear_fluid_corner_weight_renormalization_v1',sampling_profile='legacy_sqrt_v1'),data=axis)
        self.assert_matches(legacy,[(0,0,1),(1,0,1)])

    def run_lookup(self, field, positions, *, placement=None, extra=""):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "gas.lua"
            generated.write_text(compile_gas_runtime(field, placement=placement), encoding="utf-8", newline="\n")
            frame = field.spec.frame_id if placement is None else placement.to_frame_id
            lines = ["assert(_VERSION=='Lua 5.1',_VERSION)", "local f=assert(loadfile('gas.lua'))()", extra]
            for position in positions:
                lines.append("do local s=f.sample(" + ",".join(format(v, ".17g") for v in position)
                             + "," + lua_value(frame) + "); local u=s.bulk_velocity_m_s or {}; "
                             "local function v(x) return x==nil and 'nil' or string.format('%.17g',x) end; "
                             "print(table.concat({s.status,v(s.pressure_pa),v(s.temperature_k),v(u[1]),v(u[2]),v(u[3]),v(s.number_density_m3),s.frame_id,s.region_id or 'nil'},'|')) end")
            script = root / "probe.lua"
            script.write_text("\n".join(lines), encoding="utf-8", newline="\n")
            result = subprocess.run([str(LUA), str(script)], cwd=root, timeout=30,
                                    capture_output=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return [line.split("|") for line in result.stdout.splitlines()]

    def assert_matches(self, field, positions, *, placement=None):
        rows = self.run_lookup(field, positions, placement=placement)
        self.assertEqual(len(rows), len(positions))
        frame = field.spec.frame_id if placement is None else placement.to_frame_id
        for position, row in zip(positions, rows):
            with self.subTest(position=position):
                sample = sample_gas(field, fixtures.point(*position, frame=frame), placement=placement)
                self.assertEqual(row[0], sample.state.status)
                values = [sample.state.pressure_pa, sample.state.temperature_k,
                          *(sample.state.bulk_velocity_m_s or (None, None, None)), sample.number_density_m3]
                for actual, expected in zip(row[1:7], values):
                    if expected is None:
                        self.assertEqual(actual, "nil")
                    else:
                        # Same serialized binary64 inputs; allow eight operation-rounding ulps.
                        self.assertAlmostEqual(float(actual), expected, delta=8 * math.ulp(expected))
                self.assertEqual(row[7], frame)
                self.assertEqual(row[8], sample.region_id or "nil")

    def test_uniform_states_pose_frame_refusal_and_source_metadata(self):
        pose = RigidTransform("local", "world", ((0, 0, 1), (1, 0, 0), (0, 1, 0)), (10, 20, 30))
        field = prepare_gas_field(fixtures.spec(domain=BoxDomain((0, 0, 0), (2, 3, 4),
            (True,)*3, (True,)*3)))
        self.assert_matches(field, [(13, 21, 32), (100, 100, 100)], placement=pose)
        extra = "assert(not pcall(f.sample,0,0,0,'wrong')); assert(not pcall(f.sample,0/0,0,0,'local'))"
        self.run_lookup(field, [(1, 1, 1)], extra=extra)
        source = GasSource("prescribed_proxy", "explicit ]] source", ("鐪佺暐纰版挒鈥攏ot measured vacuum",),
            dict(path="C:/鏄惧紡/source.json", exists=True, bytes=1, sha256="a"*64))
        vacuum = prepare_gas_field(fixtures.spec(source=source, uniform_state=GasState("vacuum", 0)))
        self.run_lookup(vacuum, [(0, 0, 0)], extra="assert(f.source.kind=='prescribed_proxy'); assert(f.source.source_id=='explicit ]] source'); assert(f.source.reference.path=='C:/鏄惧紡/source.json'); assert(f.source.assumptions[1]=='鐪佺暐纰版挒鈥攏ot measured vacuum')")
        self.assert_matches(vacuum, [(0, 0, 0)])
        for status in ("solid", "no_data", "outside_domain"):
            self.assert_matches(prepare_gas_field(fixtures.spec(uniform_state=GasState(status))), [(0, 0, 0)])

    def test_piecewise_boundary_sequences_and_same_time_positions(self):
        bath = BoxDomain((-.1, -1, -1), (.1, 1, 1), (True, False, False), (False, False, False))
        field = prepare_gas_field(fixtures.spec("piecewise_uniform",
            regions=(GasRegion("thin", bath, fixtures.GAS),), background_state=GasState("vacuum", 0)))
        positions = [(-1, 0, 0), (0, 0, 0), (1, 0, 0), (0, 0, 0), (-1, 0, 0),
                     (-1, -2, 0), (0, 0, 0), (1, 2, 0), (0, 1, 0), (-.1, 0, 0), (.1, 0, 0)]
        self.assert_matches(field, positions)
        # There is no time/particle cache in this static API. These are distinct
        # point queries, not proof that a native step detects the intervening gas.
        self.run_lookup(field, [(0, 0, 0)], extra="local pid,time=7,10; assert(f.sample(-1,0,0,'local').pressure_pa==0); assert(f.sample(0,0,0,'local').pressure_pa==1); assert(f.sample(-1,0,0,'local').pressure_pa==0); assert(pid==7 and time==10)")

    def test_grid_serialized_values_masks_corners_axis_and_endcells(self):
        factory = fixtures.GasSamplingTests()
        for mask in ((True,)*4, (True, True, True, False), (True, False, False, False), (False,)*4):
            field = factory.grid(mask)
            data = replace(field.data,
                pressure_pa=tuple(None if v is None else v+0.123456789 for v in field.data.pressure_pa),
                temperature_k=tuple(None if v is None else v+.987654321 for v in field.data.temperature_k),
                radial_velocity_m_s=tuple(None if v is None else v*1.234567891 for v in field.data.radial_velocity_m_s),
                axial_velocity_m_s=tuple(None if v is None else v+.135792468 for v in field.data.axial_velocity_m_s))
            field = prepare_gas_field(field.spec, data=data)
            rounded = replace(data, **{name: tuple(None if v is None else float(format(v, '.9g'))
                for v in getattr(data, name)) for name in
                ('pressure_pa', 'temperature_k', 'radial_velocity_m_s', 'axial_velocity_m_s')})
            reference = prepare_gas_field(field.spec, data=rounded)
            positions = [(0, 0, 0), (1, 0, 1), (.5, 0, .5), (.25, 0, .25), (0, 0, .5),
                         (.3, .4, .5), (1.01, 0, .5), (0, 0, math.nextafter(1, math.inf))]
            emitted = self.run_lookup(field, positions, extra="assert(f.applicability=='geometry_support_not_separately_proved')")
            expected = self.run_lookup(reference, positions)
            self.assertEqual(emitted, expected)
            self.assert_matches(reference, positions)

    def test_grid_proper_pose_rotates_radial_and_axial_velocity_once(self):
        field = fixtures.GasSamplingTests().grid()
        pose = RigidTransform("local", "world", ((0, 0, 1), (1, 0, 0), (0, 1, 0)), (10, 20, 30))
        self.assert_matches(field, [(10.75, 20.375, 30.5), (10, 20, 30)], placement=pose)
        row = self.run_lookup(field, [(10.75, 20.375, 30.5)], placement=pose)[0]
        self.assertEqual(tuple(map(float, row[3:6])), (100, 3.75, 5))

    def test_chunk_boundary_and_geometry_precision_are_actual_generated_file(self):
        count = 4097
        data = AxisymmetricRZData((0, 1), tuple(range(count)), (True,)*(2*count),
            (101.123456789,)*(2*count), (300,)*(2*count), (0,)*(2*count), (100,)*(2*count))
        field = prepare_gas_field(fixtures.spec("axisymmetric_rz_grid", domain=CylindricalDomain(0, count-1, 1),
            interpolation_policy="bilinear_fluid_corner_weight_renormalization_v1"), data=data)
        rows = self.run_lookup(field, [(0, 0, 4095), (1, 0, 4096), (.5, 0, 4095.5)])
        self.assertEqual([float(row[1]) for row in rows], [101.123457]*3)
        edge = math.nextafter(.1, math.inf)
        uniform = prepare_gas_field(fixtures.spec(domain=BoxDomain((0, -1, -1), (edge, 1, 1), (True,)*3, (True,)*3)))
        self.assert_matches(uniform, [(.1, 0, 0), (edge, 0, 0), (math.nextafter(edge, math.inf), 0, 0)])

    def test_wrong_field_and_placement_reject_before_materialization(self):
        with self.assertRaisesRegex(ValueError, "prepared GasField"):
            compile_gas_runtime(fixtures.spec())
        with self.assertRaisesRegex(ValueError, "placement"):
            compile_gas_runtime(prepare_gas_field(fixtures.spec()), placement=RigidTransform.identity("wrong"))

    def test_emitted_gas_rejects_density_underflow_like_python_sample(self):
        field = prepare_gas_field(fixtures.spec(uniform_state=GasState("gas", 1e-300, 1e300, (0, 0, 0))))
        with self.assertRaisesRegex(ValueError, "gas number density must be positive"):
            sample_gas(field, fixtures.point(0))
        # Run the actual generated file; p and T remain finite positive inputs.
        self.run_lookup(field, [], extra="local ok,err=pcall(f.sample,0,0,0,'local'); assert(not ok and string.find(err,'gas number density must be positive',1,true),tostring(err))")

    def test_emitted_lookup_rejects_transformed_position_overflow_like_python(self):
        field = prepare_gas_field(fixtures.spec())
        pose = RigidTransform("local", "world", ((1, 0, 0), (0, 1, 0), (0, 0, 1)), (-1e308, 0, 0))
        with self.assertRaisesRegex(ValueError, "finite"):
            sample_gas(field, fixtures.point(1e308, frame="world"), placement=pose)
        self.run_lookup(field, [], placement=pose,
            extra="local ok,err=pcall(f.sample,1e308,0,0,'world'); assert(not ok and string.find(err,'transformed gas position must be finite',1,true),tostring(err))")

    def test_emitted_lookup_rejects_rotated_velocity_overflow_like_python(self):
        field = prepare_gas_field(fixtures.spec(uniform_state=GasState("gas", 1, 300, (1.7e308, 1.7e308, 0))))
        s = math.sqrt(.5)
        pose = RigidTransform("local", "world", ((s, s, 0), (-s, s, 0), (0, 0, 1)), (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "finite"):
            sample_gas(field, fixtures.point(0, frame="world"), placement=pose)
        self.run_lookup(field, [], placement=pose,
            extra="local ok,err=pcall(f.sample,0,0,0,'world'); assert(not ok and string.find(err,'transformed gas velocity must be finite',1,true),tostring(err))")

    def test_numeric_sds_projection_preserves_joint_values_and_all_query_failures(self):
        for mask in ((True,)*4, (True,False,False,False), (False,)*4):
            with self.subTest(mask=mask):
                self.run_lookup(fixtures.GasSamplingTests().grid(mask), [], extra="""
for _,point in ipairs{{0,0,0},{.5,0,.5},{1,0,1},{2,0,0}} do
 local x,y,z=unpack(point);local s=f.sample(x,y,z,'local')
 local a,p=f._sample_sds('pressure',x,y,z,'local')
 local b,t=f._sample_sds('temperature',x,y,z,'local')
 local c,vx,vy,vz=f._sample_sds('velocity',x,y,z,'local')
 assert(a==s.status and b==s.status and c==s.status)
 assert(p==s.pressure_pa and t==s.temperature_k)
 local u=s.bulk_velocity_m_s or {};assert(vx==u[1] and vy==u[2] and vz==u[3])
end
""")
        overflow = math.sqrt(.5)
        cases = (
            (fixtures.spec(uniform_state=GasState('gas',1e-300,1e300,(0,0,0))),None,(0,0,0),'gas number density must be positive'),
            (fixtures.spec(uniform_state=GasState('gas',1e300,1e-300,(0,0,0))),None,(0,0,0),'ideal-gas density is not finite'),
            (fixtures.spec(),RigidTransform('local','world',((1,0,0),(0,1,0),(0,0,1)),(-1e308,0,0)),(1e308,0,0),'transformed gas position must be finite'),
            (fixtures.spec(uniform_state=GasState('gas',1,300,(1.7e308,1.7e308,0))),RigidTransform('local','world',((overflow,overflow,0),(-overflow,overflow,0),(0,0,1)),(0,0,0)),(0,0,0),'transformed gas velocity must be finite'),
        )
        for definition,placement,point,message in cases:
            with self.subTest(message=message):
                frame='local' if placement is None else 'world'
                arguments=','.join(format(value,'.17g') for value in point)+','+lua_value(frame)
                extra="""local ok,err=pcall(f.sample,ARGS);assert(not ok and string.find(err,MESSAGE,1,true),tostring(err))
for _,channel in ipairs{'pressure','temperature','velocity'} do
 local ok,err=pcall(f._sample_sds,channel,ARGS);assert(not ok and string.find(err,MESSAGE,1,true),tostring(err))
end""".replace('ARGS',arguments).replace('MESSAGE',lua_value(message))
                self.run_lookup(prepare_gas_field(definition),[],placement=placement,extra=extra)

    def test_decimal_stored_nodes_and_sds_keep_exact_vs_nextafter_support(self):
        factory = fixtures.GasSamplingTests()
        for profile in ("canonical_static_v1", "legacy_sqrt_v1"):
            for ir, iz in ((3, 0), (0, 3), (3, 3), (1, 2), (2, 1)):
                with self.subTest(profile=profile, node=(ir, iz)):
                    field = factory.decimal_grid(profile, ir, iz)
                    r, z = field.data.r_values_mm[ir], field.data.z_values_mm[iz]
                    positions = [(r, 0., z)]
                    if ir:
                        positions.append((math.nextafter(r, 0), 0., z))
                    if iz:
                        positions.append((r, 0., math.nextafter(z, 0)))
                    self.assert_matches(field, positions)
                    args = ','.join(format(v, '.17g') for v in (r, 0., z)) + ",'local'"
                    self.run_lookup(field, [], extra=(
                        "assert(f.sample(" + args + ").status=='no_data'); "
                        "for _,channel in ipairs{'pressure','temperature','velocity'} do "
                        "local status=f._sample_sds(channel," + args + "); assert(status=='no_data') end"))

    def test_canonical_radius_actual_hypot_boundaries_and_extreme_finite_inputs(self):
        vectors = ((.2, .3), (.3, .4), (-.2, .3), (.2, -.3), (1., 1.),
                   (1e308, 1e308), (1e-300, 1e-300), (5e-324, 5e-324),
                   (1e308, 1e-300), (0., 1.), (1.7e308, 1.7e308))
        for x, y in vectors:
            radius = math.hypot(x, y)
            boundaries = ((math.nextafter(radius, 0), radius, math.nextafter(radius, math.inf))
                          if math.isfinite(radius) else (1.7e308,))
            for boundary in boundaries:
                if not (math.isfinite(boundary) and boundary > 0):
                    continue
                for inner in (False, True):
                    if inner and not math.isfinite(boundary * 2):
                        continue
                    domain = (CylindricalDomain(0, 1, boundary * 2, boundary) if inner
                              else CylindricalDomain(0, 1, boundary))
                    with self.subTest(point=(x, y), boundary=boundary, inner=inner):
                        field = prepare_gas_field(fixtures.spec(domain=domain))
                        self.assert_matches(field, [(x, y, .5), (0., 0., .5)])
                        expected = sample_gas(field, fixtures.point(x, y, .5)).state.status
                        args = ','.join(format(v, '.17g') for v in (x, y, .5)) + ",'local'"
                        self.run_lookup(field, [], extra=(
                            "for _,channel in ipairs{'pressure','temperature','velocity'} do "
                            "local status=f._sample_sds(channel," + args + "); assert(status==" + lua_value(expected) + ") end"))
        # Explicit historical profile keeps sqrt(x*x+y*y), including this ULP boundary.
        legacy = prepare_gas_field(fixtures.spec(domain=CylindricalDomain(0, 1, math.hypot(.2, .3)),
                                                sampling_profile='legacy_sqrt_v1'))
        self.assert_matches(legacy, [(.2, .3, .5), (0., 0., .5)])
