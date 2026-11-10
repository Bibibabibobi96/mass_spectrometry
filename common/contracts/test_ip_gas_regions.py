"""Actual IP region/compiler/HS1 binding software probes, not collision physics."""
import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_simion_prepared_model import LUA
from msplatform.backends.simion.gas_runtime import compile_gas_runtime
from msplatform.backends.simion.resources import native_resource_path
from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import build_gas_field_spec
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
from msplatform.contracts.gas import BoxDomain, GasState
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.gas.field import prepare_gas_field, sample_gas
from common.contracts.test_gas_field_sampling import point

ROOT = Path(__file__).resolve().parents[2]


def inputs():
    directory = ROOT / "projects/dual_pressure_rectilinear_ion_processor/config"
    return tuple(json.loads((directory / (name + ".json")).read_text(encoding="utf-8")) for name in ("baseline", "numerics"))


def field_for(baseline, numerics):
    projection = native_projection(baseline, numerics)
    return prepare_gas_field(build_gas_field_spec(baseline, domain=BoxDomain(
        projection["origin_mm"], projection["maximum_mm"], (True,)*3, (True,)*3)))


class IpGasRegionsTests(unittest.TestCase):
    def test_actual_native_domain_preserves_hp_lp_boundaries_and_lp211(self):
        baseline, numerics = inputs()
        before = copy.deepcopy(baseline)
        field = field_for(baseline, numerics)
        self.assertEqual(baseline, before)
        frame = field.spec.frame_id
        for x, y, expected in ((math.nextafter(30, -math.inf), 0, 0), (30, 0, 1),
                (math.nextafter(130, -math.inf), 0, 1), (130, 0, .2), (211, 0, .2),
                (50, 2, 0), (50, math.nextafter(2, 0), 1)):
            with self.subTest(x=x, y=y):
                self.assertEqual(sample_gas(field, point(x, y, frame=frame)).state.pressure_pa, expected)
        self.assertGreater(field.spec.domain.maximum_mm[0], 211)
        self.assertEqual(sample_gas(field, point(213, frame=frame)).state.status, "outside_domain")
        self.assertEqual(field.spec.source.kind, "prescribed_proxy")

    def test_zero_pressure_is_explicit_control_not_missing_data(self):
        baseline, numerics = inputs()
        baseline["gas"]["hp_pressure_pa"] = 0
        field = field_for(baseline, numerics)
        state = sample_gas(field, point(50, frame=field.spec.frame_id)).state
        self.assertEqual(state, GasState("vacuum", 0, 300, (0, 0, 0)))
        self.assertEqual(sample_gas(field, point(150, frame=field.spec.frame_id)).state.pressure_pa, .2)

    @unittest.skipUnless(LUA.is_file(), "installed standalone Lua unavailable")
    def test_actual_binding_uses_world_mm_pascal_kelvin_mm_us_and_no_cache(self):
        baseline, numerics = inputs()
        field = field_for(baseline, numerics)
        pose = RigidTransform(field.spec.frame_id, "world", ((0, 0, 1), (1, 0, 0), (0, 1, 0)), (10, 20, 30))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "gas.lua").write_text(compile_gas_runtime(field, placement=pose), encoding="utf-8")
            (root / "binding.lua").write_bytes(native_resource_path("collision_hs1_gas.lua").read_bytes())
            script = """assert(_VERSION=='Lua 5.1')
local f=assert(loadfile('gas.lua'))();local binding=assert(loadfile('binding.lua'))()
local hs={};local x,y,z=10,70,30;local calls=0
binding.bind(hs,f,function() calls=calls+1;return x,y,z end,'world')
assert(hs.pressure(999,999,999)==1);assert(hs.temperature()==300)
local a,b,c=hs.velocity();assert(a==0 and b==0 and c==0)
y=231;assert(hs.pressure()==.2);y=49;assert(hs.pressure()==0);y=70;assert(hs.pressure()==1)
assert(calls==6,'each vendor callback queries its actual position; no ID/time cache')
-- An explicit inert field isolates the adapter's official velocity units, not HS1 physics.
binding.bind(hs,{sample=function() return {status='gas',pressure_pa=2,temperature_k=310,bulk_velocity_m_s={100,-200,300}} end},function() return 0,0,0 end,'world')
local u,v,w=hs.velocity();assert(u==.1 and v==-.2 and w==.3)
binding.bind(hs,{sample=function() return {status='no_data'} end},function() return 0,0,0 end,'world')
local ok,err=pcall(hs.pressure);assert(not ok and string.find(err,'gas field coverage lost',1,true))
print('IP_GAS_BINDING_PASS')
"""
            (root / "probe.lua").write_text(script, encoding="utf-8")
            result = subprocess.run([str(LUA), str(root / "probe.lua")], cwd=root, timeout=30,
                capture_output=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("IP_GAS_BINDING_PASS", result.stdout)
