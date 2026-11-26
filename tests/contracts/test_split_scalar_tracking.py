"""Split scalar tracking hook software tests; no native Fly is claimed."""
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion.tracking_program import _instrument_common_scalar


def basis():
    record = dict(path='field.pa', bytes=10, sha256='a'*64)
    valid = dict(path='mask.pa', bytes=10, sha256='b'*64)
    grid = dict(frame_id='world', origin_mm=[0.,0.,0.], pitch_mm=[1.,1.,1.], dimensions=[3,3,3])
    return dict(role='split_off_on_scalar_binding', bases={name: dict(grid=grid,
        records=dict(field_v=record, field_valid=valid), ideal_sheet_projection={}) for name in ('off','on')})


class SplitScalarTrackingTests(unittest.TestCase):
    def test_admission_fails_closed_without_real_world_background(self):
        from msplatform.backends.simion.tracking_execution import _resolve_scalar_basis
        geometry = dict(role='simion_split_oa_tof_geometry', composition_plan=dict(schema_version=6,
            scope=dict(instance_ids=['oa','tof']), components=dict(oa=dict(project_id='orthogonal_accelerator'),
            tof=dict(project_id='single_reflection_tof'))))
        plan = dict(propagation=dict(scope='continuous_assembly'), rows=[{}], observations={})
        selection = dict(geometry_artifact={}, samples={'off': {}, 'on': {}})
        with patch('msplatform.backends.simion.tracking_execution.model_geometry', return_value=SimpleNamespace(frontend_geometry=geometry)), \
             patch('msplatform.backends.simion.split_scalar_binding.resolve_split_scalar_basis', return_value=basis()):
            with self.assertRaisesRegex(ValueError, 'world background PA'):
                _resolve_scalar_basis(SimpleNamespace(metadata={}), None, plan, selection)

    def test_hook_installs_total_field_after_region_and_rejects_unimplemented_observation(self):
        program = ('local single_flight_trace_path=1\n'
                   '    single_flight_frontend=single_flight_frontend_component.new()\n'
                   '  if instance==nil then return end\n'
                   '  end\nend\nfunction segment.instance_adjust()')
        instrumented = _instrument_common_scalar(program, basis(), 'return function() end', 'return {}', False)
        self.assertIn('single_flight_scalar_module.new(single_flight_scalar_adapter,single_flight_pulse,', instrumented)
        self.assertIn('ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=single_flight_scalar(', instrumented)
        self.assertNotIn('single_flight_scalar_rf=', instrumented)
        with self.assertRaisesRegex(ValueError, 'observations'):
            _instrument_common_scalar(program, basis(), 'return function() end', 'return {}', True)

    @unittest.skipUnless(Path('C:/Program Files/SIMION-2020/lua.exe').is_file(), 'standalone Lua unavailable')
    def test_off_on_gate_retains_complete_fields(self):
        source = Path('src/msplatform/backends/simion/resources/split_scalar_field.lua').resolve().as_posix()
        script = """local module=dofile(SOURCE)
local reads={off=0,on=0}
local function adapter(b) return function(instance,x,y,z,support)
  reads[b.name]=reads[b.name]+1
  if b.name=='off' then return 2,3,4 else return 8,9,10 end
end end
local pulse={is_active_at=function(t) return t>=5 and t<10 end}
local sample=module.new(adapter,pulse,{off={name='off'},on={name='on'}})
local x,y,z=sample(1,0,0,0,4);assert(x==2 and y==3 and z==4)
x,y,z=sample(1,0,0,0,5);assert(x==8 and y==9 and z==10)
x,y,z=sample(1,0,0,0,10);assert(x==2 and y==3 and z==4)
assert(reads.off==3 and reads.on==3)
assert(not pcall(sample,nil,0,0,0,1))
""".replace('SOURCE', repr(source))
        completed = subprocess.run(['C:/Program Files/SIMION-2020/lua.exe', '-e', script],
                                   cwd=Path(__file__).parent, timeout=15, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__': unittest.main()
