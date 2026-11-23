"""Explicit synthetic terminal wire for inert owner fixtures only."""
import inspect
import json
import re
from pathlib import Path


def native_run_from_program(path):
    program = Path(path).read_text(encoding='utf8')
    matches = re.findall(r'\bnative_run=("(?:[^"\\\\]|\\\\.)*")', program)
    if len(matches) != 1:
        raise ValueError('fixture requires one generated terminal recorder token')
    return json.loads(matches[0])


def terminal_wire_lines(row, ion, native_run, terminal_time, instance):
    import json
    t = row['instrument_time_us']
    shared = dict(schema_version=1, particle_id=row['particle_id'], ion=ion,
        native_run=native_run, ion_run=1, raw_birth_us=0., raw_step_us=None,
        source_origin_us=t, instance=instance, grouped=0, splat=None)
    shared.update({axis+'_mm': row['position_'+axis+'_mm'] for axis in 'xyz'})
    shared.update({'v'+axis+'_mm_per_us': row['velocity_'+axis+'_m_s']/1000 for axis in 'xyz'})
    result = []
    for event, sequence, clock in [('initialize', 1, t), ('terminate', 2, terminal_time)]:
        value = dict(shared, event=event, capture_sequence=sequence, raw_tof_us=clock-t,
                     pipeline_clock_us=clock, instrument_time_us=clock)
        result.append('SIMION_TERMINAL_V1:'+json.dumps(value, allow_nan=False))
    return result


def inert_wire_source():
    return inspect.getsource(terminal_wire_lines) + '\n'
