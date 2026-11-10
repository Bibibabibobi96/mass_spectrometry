"""Finite cooled bath in its actual carrier domain; no vendor physics."""
import math
import json
import subprocess
import tempfile
from pathlib import Path
import unittest

from integrations.tests.test_cooled_frontend import LUA, cooled_fixture
from msplatform.backends.simion.cooled_frontend_geometry import compile_cooled_frontend
from msplatform.workflows.cooled_frontend.program import carrier_query_domain
from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import build_cooled_gas_field_spec
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
from msplatform.gas.field import prepare_gas_field, sample_gas
from msplatform.backends.simion.gas_runtime import compile_gas_runtime


class CooledGasRegionsTests(unittest.TestCase):
    def make_field(self, scale=1):
        guide, connection, component, conditioner, _ = cooled_fixture()
        _, frontend = compile_cooled_frontend(guide, connection, component, conditioner,
            cell_mm_xyz=dict(x=.2,y=.5,z=1),exit_gap_mm=1.)
        pose=RigidTransform.from_contract(conditioner['native_to_mr'])
        domain=carrier_query_domain(frontend,pose)
        field=prepare_gas_field(build_cooled_gas_field_spec(conditioner,pressure_scale=scale,domain=domain))
        return field,pose,conditioner

    def test_finite_bath_boundary_and_valid_downstream_vacuum_are_distinct(self):
        field,pose,conditioner=self.make_field()
        domain=conditioner['gas']['domain_native_mm']
        start,end,radius=domain['x_min'],domain['x_max'],domain['transverse_halfwidth']
        pressure=conditioner['gas']['parameters']['hp_pressure_pa']
        vectors=[(math.nextafter(start,-math.inf),0,0),(start,0,pressure),
                 (math.nextafter(end,-math.inf),0,pressure),(end,0,0),
                 (start+1,radius,0),(start+1,math.nextafter(radius,0),pressure),
                 (end+.5,0,0)]
        self.assertGreater(field.spec.domain.maximum_mm[0],end+.5)
        for x,y,expected in vectors:
            with self.subTest(position=(x,y,0)):
                p=FramedPosition(field.spec.frame_id,(x,y,0))
                self.assertEqual(sample_gas(field,p).state.pressure_pa,expected)
                world=pose.transform_position(p)
                # A translated nextafter coordinate may round onto the boundary.
                # Compare the world request with the actual representable inverse,
                # while the local test above retains the exact nextafter oracle.
                local=pose.inverse().transform_position(world).coordinates_mm
                wx,wy,wz=local
                world_expected=pressure if start<=wx<end and abs(wy)<radius and abs(wz)<radius else 0
                self.assertEqual(sample_gas(field,world,placement=pose).state.pressure_pa,world_expected)
        outside=FramedPosition(field.spec.frame_id,(field.spec.domain.maximum_mm[0]+1,0,0))
        self.assertEqual(sample_gas(field,outside).state.status,'outside_domain')

    def test_zero_control_keeps_static_gas_semantics_and_no_release_time_switch(self):
        full,_,conditioner=self.make_field()
        zero,_,_=self.make_field(0)
        p=FramedPosition(full.spec.frame_id,(conditioner['gas']['domain_native_mm']['x_min']+1,0,0))
        for label in ('before_release','at_release','after_release'):
            with self.subTest(label=label):
                self.assertEqual(sample_gas(full,p).state.status,'gas')
                self.assertEqual(sample_gas(zero,p).state.status,'vacuum')
                self.assertEqual(sample_gas(zero,p).number_density_m3,0)
        self.assertEqual(full.spec.source.kind,'prescribed_proxy')

    def test_box_projection_does_not_claim_arbitrary_rotation_support(self):
        field,pose,_=self.make_field()
        s=math.sqrt(.5)
        other=RigidTransform(pose.from_frame_id,pose.to_frame_id,((s,s,0),(-s,s,0),(0,0,1)),(0,0,0))
        with self.assertRaisesRegex(ValueError,'signed-permutation'):
            carrier_query_domain({},other)
        for scale in (True,-1,.5,float('nan')):
            _,_,conditioner=self.make_field()
            with self.subTest(scale=scale),self.assertRaises(ValueError):
                build_cooled_gas_field_spec(conditioner,pressure_scale=scale,domain=field.spec.domain)

    @unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
    def test_actual_emitted_pose_queries_match_legacy_pressure_in_same_frame(self):
        field,pose,conditioner=self.make_field()
        bath=conditioner['gas']['domain_native_mm']
        start,end,radius=bath['x_min'],bath['x_max'],bath['transverse_halfwidth']
        local_points=[(start-1,0,0),(start,0,0),(start+1,0,0),(end,0,0),(end+.5,0,0),
                      (start+1,radius,0),(start+1,0,radius),(start+1,-radius+.5,radius-.5)]
        points=[pose.transform_position(FramedPosition(field.spec.frame_id,p)).coordinates_mm for p in local_points]
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            for scale in (0,1):
                current,_,_=self.make_field(scale)
                runtime=directory/f'gas{scale}.lua'
                runtime.write_text(compile_gas_runtime(current,placement=pose),encoding='utf-8')
                lines=["local field=assert(loadfile(arg[1]))()"]
                for point in points+list(reversed(points)):
                    local=pose.inverse().transform_position(FramedPosition(pose.to_frame_id,point)).coordinates_mm
                    x,y,z=local
                    expected=conditioner['gas']['parameters']['hp_pressure_pa']*scale if start<=x<end and abs(y)<radius and abs(z)<radius else 0
                    vector=','.join(format(v,'.17g') for v in point)
                    lines.append(f'local s=field.sample({vector},{json.dumps(pose.to_frame_id)});assert(s.pressure_pa=={expected!r});assert(s.temperature_k==300);assert(s.bulk_velocity_m_s[1]==0 and s.bulk_velocity_m_s[2]==0 and s.bulk_velocity_m_s[3]==0)')
                lines.append("print('COOLED_POSED_GENERATED=PASS')")
                script=directory/'probe.lua';script.write_text('\n'.join(lines),encoding='utf-8')
                result=subprocess.run([str(LUA),str(script),str(runtime)],cwd=directory,timeout=30,capture_output=True,text=True,encoding='utf-8',check=False)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('COOLED_POSED_GENERATED=PASS',result.stdout)
