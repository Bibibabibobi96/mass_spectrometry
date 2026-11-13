"""Explicit RF-IP gas selection, placement and coverage."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts.test_simion_native_plans import LUA
from msplatform.backends.simion.gas_runtime import compile_gas_runtime
from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import (
    build_gas_field_spec, validate_continuous_hs1_gas, validate_continuous_parent_coverage
)
from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
from msplatform.gas.field import prepare_gas_field

ROOT = Path(__file__).resolve().parents[2]
SELECTOR = ROOT / 'src/msplatform/backends/simion/resources/rf_ip_gas_selection.lua'
BINDING = ROOT / 'src/msplatform/backends/simion/resources/collision_hs1_gas.lua'


@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class ContinuousIpGasSelectionTests(unittest.TestCase):
    def test_actual_bath_and_explicit_outer_keep_boundaries_and_refuse_unknown(self):
        baseline = json.loads((ROOT/'projects/dual_pressure_rectilinear_ion_processor/config/baseline.json').read_text(encoding='utf-8'))
        box = lambda lo, hi: BoxDomain(lo, hi, (True, True, True), (True, True, True))
        bath = build_gas_field_spec(baseline, domain=box((0, -10, -10), (211, 10, 10)))
        outer = GasFieldSpec(field_id='explicit_outer', frame_id=bath.frame_id, representation='uniform',
            composition_id=bath.composition_id, composition=(GasSpecies('ion_processor_model_gas', baseline['gas']['mass_amu'], 1),),
            domain=box((-50, -20, -20), (250, 20, 20)), source=GasSource('prescribed', 'test_outer', ()),
            uniform_state=GasState('gas', 4, baseline['gas']['temperature_k'], (0, 0, 0)))
        validate_continuous_hs1_gas(bath, outer, gas_mass_amu=baseline['gas']['mass_amu'])
        from msplatform.contracts.rigid_transform import RigidTransform
        placement = RigidTransform(bath.frame_id, 'world', ((0, -1, 0), (1, 0, 0), (0, 0, 1)), (10, 20, 0))
        validate_continuous_parent_coverage(outer, placement=placement,
            parent_domain=box((-10, 20, -10), (30, 220, 10)))
        with self.assertRaisesRegex(ValueError, 'does not cover'):
            validate_continuous_parent_coverage(outer, placement=placement,
                parent_domain=box((-11, 20, -10), (30, 220, 10)))
        with self.assertRaisesRegex(ValueError, 'mass differs'):
            validate_continuous_hs1_gas(bath, outer, gas_mass_amu=29)
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, 'same explicit single gas'):
            validate_continuous_hs1_gas(bath, replace(outer, composition=(GasSpecies('other', 29, 1),)),
                                        gas_mass_amu=baseline['gas']['mass_amu'])
        with self.assertRaisesRegex(ValueError, 'frames and composition'):
            validate_continuous_hs1_gas(bath, replace(outer, frame_id='wrong'), gas_mass_amu=28)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, field in (('bath.lua', bath), ('outer.lua', outer)):
                (root/name).write_text(compile_gas_runtime(prepare_gas_field(field)), encoding='utf-8')
            script = root/'test.lua'
            script.write_text("""
local bath=assert(loadfile(arg[1]))()
local outer=assert(loadfile(arg[2]))()
local selector=assert(loadfile(arg[3]))().new(bath,outer)
local hs={};local xyz={0,0,0}; local frame=arg[5]
assert(loadfile(arg[4]))().bind(hs,selector,function() return unpack(xyz) end,frame)
local function pressure(x,y,z) xyz={x,y,z};return hs.pressure() end
assert(pressure(-1,0,0)==4)
assert(pressure(0,0,0)==0)
assert(pressure(30,0,0)==1)
assert(pressure(130,0,0)==0.2)
assert(pressure(211,0,0)==0.2)
assert(pressure(212,0,0)==4)
assert(not pcall(function() pressure(251,0,0) end))
local calls=0;local missing={sample=function() return {status='no_data'} end}
local forbidden={sample=function() calls=calls+1;return {status='vacuum',pressure_pa=0,temperature_k=300,bulk_velocity_m_s={0,0,0}} end}
local bad=assert(loadfile(arg[3]))().new(missing,forbidden);local hs2={}
assert(loadfile(arg[4]))().bind(hs2,bad,function() return 0,0,0 end,frame)
assert(not pcall(hs2.pressure));assert(calls==0)
print('RF_IP_GAS_SELECTOR=PASS')
""", encoding='utf-8')
            result = subprocess.run([str(LUA), str(script), str(root/'bath.lua'), str(root/'outer.lua'),
                str(SELECTOR), str(BINDING), bath.frame_id], cwd=root, capture_output=True,
                text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('RF_IP_GAS_SELECTOR=PASS', result.stdout)


@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class ContinuousIpHs1CompositionTests(unittest.TestCase):
    def test_inert_hs1_single_particle_activation_and_no_reentry_seed(self):
        import re
        source = (ROOT/'src/msplatform/backends/simion/resources/rf_ip_tracking_hs1.lua').read_text(encoding='utf-8')
        source, count = re.subn(r'(?m)^(\s*)adjustable ', r'\1', source)
        self.assertEqual(count, 9)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'composition.lua').write_text(source,encoding='utf-8')
            script=root/'test.lua'
            script.write_text("""
local init,steps,actions,seeds,base=0,0,0,{},{}
seed=function(x) seeds[#seeds+1]=x end
segment={initialize_run=function() base.run=(base.run or 0)+1 end,
 tstep_adjust=function() base.step=(base.step or 0)+1 end,
 other_actions=function() base.actions=(base.actions or 0)+1 end,
 terminate=function() base.terminal=(base.terminal or 0)+1 end}
local hs={segment={}}
function hs.reset_run_state() end
function hs.bound_parameters() return {gas_mass_amu=_gas_mass_amu,temperature_k=_temperature_k,pressure_pa=_pressure_pa,
 sigma_m2=_sigma_m2,mean_free_path_mm=_mean_free_path_mm,steps_per_mfp=_steps_per_MFP,random_seed=_random_seed,
 mark_collisions=_mark_collisions,trace_level=_trace_level} end
function hs.segment.initialize() init=init+1;seed(_random_seed) end
function hs.segment.tstep_adjust() steps=steps+1 end
local pressures={}
function hs.segment.other_actions() actions=actions+1;pressures[#pressures+1]=hs.pressure() end
local gas={sample=function(x) return {status=x>0 and 'gas' or 'vacuum',pressure_pa=x>0 and 2 or 0,temperature_k=300,bulk_velocity_m_s={0,0,0}} end}
local binder=assert(loadfile(arg[2]))();local wave={cap_before_edge=function(t,dt,e)return math.min(dt,e-t) end}
local conf={baseline={gas={mass_amu=28,temperature_k=300,cross_section_m2=2e-18,mean_free_path_mm=-1}},
 numerics={seed=40,hs1_steps_per_mfp=20},query_frame_id='ip',schedule_edges_us={1}}
ion_px_mm,ion_py_mm,ion_pz_mm=0,0,0;ion_time_step=.5;ion_number=1
local id=7;local t=.75
assert(loadfile(arg[1]))().install(hs,gas,binder,conf,function() return t end,function() return id end,wave)
segment.initialize_run();segment.tstep_adjust();assert(ion_time_step==.25)
segment.other_actions();ion_px_mm=1;segment.other_actions();ion_px_mm=0;segment.tstep_adjust();assert(init==2 and steps==2 and actions==2)
assert(pressures[1]==0 and pressures[2]==2)
ion_number=2;id=101;local before_interleave=#seeds;assert(not pcall(segment.tstep_adjust));assert(#seeds==before_interleave)
ion_number=1;id=7
assert(#seeds==4 and seeds[1]==41 and seeds[2]==40 and seeds[3]==41 and seeds[4]==46)
segment.terminate();local before=#seeds;assert(not pcall(segment.tstep_adjust));assert(#seeds==before)
ion_number=2;id=101;segment.tstep_adjust();assert(init==3 and seeds[#seeds]==140)
assert(base.run==1 and base.actions==2 and base.terminal==1)
print('RF_IP_HS1_LIFECYCLE=PASS')
""",encoding='utf-8')
            result=subprocess.run([str(LUA),str(script),str(root/'composition.lua'),str(BINDING)],cwd=root,
                capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('RF_IP_HS1_LIFECYCLE=PASS',result.stdout)
