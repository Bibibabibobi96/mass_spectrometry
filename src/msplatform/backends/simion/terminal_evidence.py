"""Strict terminal evidence parsing and fact-only reconciliation.

Capture order is authoritative; transport line order is not. No raw fact here
establishes a physical terminal cause.
"""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

PREFIX = 'SIMION_TERMINAL_V1:'
EVENTS = ('initialize', 'other_actions_before', 'other_actions_after', 'terminate')
COORDINATES = ('x_mm', 'y_mm', 'z_mm', 'vx_mm_per_us', 'vy_mm_per_us', 'vz_mm_per_us')
CLOCKS = ('raw_birth_us', 'raw_tof_us', 'raw_step_us', 'source_origin_us',
          'pipeline_clock_us', 'instrument_time_us')
KEYS = frozenset(('schema_version', 'particle_id', 'ion', 'native_run', 'ion_run',
                  'capture_sequence', 'event', 'instance', 'splat', 'grouped',
                  *CLOCKS, *COORDINATES))


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError('duplicate terminal wire key: ' + key)
        result[key] = value
    return result


def _snapshot(value, *, wire=False):
    if not isinstance(value, Mapping):
        raise ValueError('terminal snapshot must be an object')
    row = dict(value)
    if wire and (set(row) != KEYS or type(row['schema_version']) is not int or row['schema_version'] != 1):
        raise ValueError('terminal wire schema differs')
    for name in ('particle_id', 'ion', 'capture_sequence'):
        if name in row and (type(row[name]) is not int or row[name] < (0 if name == 'capture_sequence' else 1)):
            raise ValueError('invalid terminal ' + name)
    for name in ('ion_run', 'instance', 'splat', 'grouped'):
        if name in row and row[name] is not None and type(row[name]) is not int:
            raise ValueError('invalid terminal ' + name)
    if row.get('instance') is not None and row['instance'] < 0:
        raise ValueError('invalid terminal instance')
    if row.get('ion_run') is not None and row['ion_run'] < 1:
        raise ValueError('invalid terminal ion_run')
    if row.get('grouped') not in (None, 0, 1):
        raise ValueError('invalid terminal grouped')
    if 'native_run' in row and (not isinstance(row['native_run'], str) or not row['native_run']):
        raise ValueError('invalid terminal native_run')
    if 'event' in row and row['event'] not in EVENTS:
        raise ValueError('invalid terminal event')
    for name in (*CLOCKS, *COORDINATES):
        if name in row and row[name] is not None and (type(row[name]) not in (int, float) or not math.isfinite(row[name])):
            raise ValueError('nonfinite or invalid terminal ' + name)
    return copy.deepcopy(row)


UNITS = {'time': 'us', 'position': 'mm', 'velocity': 'mm/us'}


def append_terminal_recorder(program: str, *, recorder_source: str, native_run: str,
                             callbacks: Mapping[str, str] | None = None) -> str:
    """Install the common recorder after all scientific and collision hooks.

    Public Fly sources use zero native birth and carry their absolute origin in
    the frozen row map. Preserve that existing clock; raw TOB/TOF remain separate.
    Explicit internal callback expressions let other Programs supply their own
    existing identities and clocks without changing the recorder or its parser.
    """
    if not isinstance(native_run, str) or not native_run:
        raise ValueError('terminal recorder requires its unit identity')
    selected = {
        'particle_id': 'single_flight_canonical_particle_id',
        'source_origin_us': 'function() return single_flight_time_origin_us[single_flight_source_row_index()] end',
        'pipeline_clock_us': 'single_flight_instrument_time_us',
        'instrument_time_us': 'single_flight_instrument_time_us',
    } if callbacks is None else dict(callbacks)
    if set(selected) != {'particle_id', 'source_origin_us', 'pipeline_clock_us', 'instrument_time_us'} or any(
            not isinstance(expression, str) or not expression.strip() for expression in selected.values()):
        raise ValueError('terminal recorder callback expressions differ')
    bindings = ',\n'.join('  ' + name + '=' + selected[name] for name in (
        'particle_id', 'source_origin_us', 'pipeline_clock_us', 'instrument_time_us'))
    return program + '\nlocal public_terminal_recorder=(function()\n' + recorder_source + '''
end)()
public_terminal_recorder.install(segment,{
  native_run=''' + json.dumps(native_run, ensure_ascii=True) + ''',
''' + bindings + '''
})
'''


def attach_terminal_evidence(result: dict, log_paths: Sequence[str | Path],
                             batches: Sequence[Mapping]) -> dict:
    """Bind raw callbacks to collected terminal states without changing taxonomy.

    Old frozen logs explicitly lack this wire. A current producer declares v1
    and must supply it completely; absence cannot fall back to legacy evidence.
    """
    declarations = [batch.get('build_metadata', {}).get('terminal_evidence') for batch in batches]
    if all(item is None for item in declarations):
        result['terminal_evidence'] = dict(schema_version=1, status='legacy_absent', units=dict(UNITS))
        return result
    if any(not isinstance(item, dict) or set(item) != {'schema_version', 'native_run'}
           or type(item['schema_version']) is not int or item['schema_version'] != 1 for item in declarations):
        raise ValueError('terminal evidence producer declarations differ')
    bindings = [dict(native_run=item['native_run'], expected_particle_ids=batch['expected_particle_ids'])
                for item, batch in zip(declarations, batches, strict=True)]
    recorded = collect_terminal_evidence(log_paths, bindings, require_v1=True)
    terminals = {row['particle_id']: row for row in result['native_terminals']}
    if set(recorded) != set(terminals):
        raise ValueError('raw terminal evidence cohort differs')
    facts = []
    for pid, evidence in recorded.items():
        phases = {row['event']: row for row in evidence['records']}
        terminal = phases['terminate']
        observed = terminals[pid]
        # Both producers serialize the same native terminate reads at %.17g.
        for key in ('instrument_time_us', *COORDINATES):
            if terminal[key] is None or terminal[key] != observed[key]:
                raise ValueError(f'particle {pid}: terminal wire/native state differs: {key}')
        if terminal['instance'] != observed['instance']:
            raise ValueError(f'particle {pid}: terminal wire/native instance differs')
        reconciliation = reconcile_terminal_evidence(terminal,
            phases.get('other_actions_before'), phases.get('other_actions_after'))
        facts.append(dict(particle_id=pid, raw=evidence, reconciliation=reconciliation))
    result['terminal_evidence'] = dict(schema_version=1, status='recorded_v1', units=dict(UNITS),
        particle_evidence=facts, classification_changed=False)
    return result


def render_terminal_6d_rec(evidence: Mapping) -> str:
    """Serialize verified native start/terminal states without assigning a cause."""
    if not isinstance(evidence, Mapping) or evidence.get('status') != 'recorded_v1':
        raise ValueError('REC requires complete current terminal evidence')
    lines = ['Ion,Event,TOF,X,Y,Z,Vx,Vy,Vz']
    for particle in evidence['particle_evidence']:
        phases = {row['event']: row for row in particle['raw']['records']}
        for phase, label in (('initialize', 'Start'), ('terminate', 'Splat')):
            row = phases[phase]
            values = (row['raw_tof_us'], *(row[key] for key in COORDINATES))
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
                raise ValueError('REC requires finite native TOF and 6D')
            lines.append(','.join((str(row['ion']), label,
                *(format(value, '.17g') for value in values))))
    return '\n'.join(lines) + '\n'


def _finalize_records(rows):
    if not rows:
        return {'status': 'legacy_absent', 'records': []}
    sequences = [row['capture_sequence'] for row in rows]
    if len(set(sequences)) != len(sequences):
        raise ValueError('duplicate terminal capture sequence')
    ion_runs = {row['ion_run'] for row in rows if row['ion_run'] is not None}
    if len(ion_runs) > 1:
        raise ValueError('terminal ion_run differs')
    rows.sort(key=lambda row: row['capture_sequence'])
    events = [row['event'] for row in rows]
    if len(set(events)) != len(events) or events[0] != 'initialize' or events[-1] != 'terminate':
        raise ValueError('terminal capture phases differ')
    if events != sorted(events, key=EVENTS.index):
        raise ValueError('terminal capture phase order differs')
    pair_complete = ('other_actions_before' in events and 'other_actions_after' in events)
    return {'status': 'recorded_v1', 'callback_pair_complete': pair_complete, 'records': rows}


def _collect_terminal_log(lines, *, native_run, expected_particle_ids):
    """Parse a native log once; bind one-based ions to its ordered canonical IDs."""
    ids = list(expected_particle_ids)
    if (not ids or any(type(pid) is not int or pid < 1 for pid in ids)
            or len(set(ids)) != len(ids) or not isinstance(native_run, str) or not native_run):
        raise ValueError('invalid terminal expected identities')
    by_ion = {index: [] for index in range(1, len(ids) + 1)}
    for line in lines:
        if PREFIX not in line:
            continue
        try:
            obj = json.loads(line.split(PREFIX, 1)[1], object_pairs_hook=_pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid terminal wire JSON') from exc
        row = _snapshot(obj, wire=True)
        if row['native_run'] != native_run:
            raise ValueError('terminal wire run differs')
        ion = row['ion']
        if ion not in by_ion or row['particle_id'] != ids[ion - 1]:
            raise ValueError('terminal wire ion/particle mapping differs')
        by_ion[ion].append(row)
    return {ids[ion - 1]: _finalize_records(rows) for ion, rows in by_ion.items()}


def collect_terminal_evidence(log_paths: Sequence[str | Path], batches: Sequence[Mapping],
                              *, require_v1: bool = False) -> dict[int, dict]:
    """Parse each unit log once using its explicit run token and ordered IDs."""
    if type(require_v1) is not bool:
        raise ValueError('require_v1 must be boolean')
    paths, units = list(log_paths), list(batches)
    if not paths or len(paths) != len(units):
        raise ValueError('terminal log/batch binding differs')
    result = {}
    for path, batch in zip(paths, units, strict=True):
        if not isinstance(batch, Mapping) or set(batch) != {'native_run', 'expected_particle_ids'}:
            raise ValueError('terminal batch identity differs')
        with Path(path).open(encoding='utf-8-sig') as stream:
            rows = _collect_terminal_log(stream, native_run=batch['native_run'],
                                         expected_particle_ids=batch['expected_particle_ids'])
        if require_v1 and any(row['status'] != 'recorded_v1' for row in rows.values()):
            raise ValueError('required terminal v1 evidence missing')
        if set(result) & set(rows):
            raise ValueError('terminal batch particle identities overlap')
        result.update(rows)
    return result


def parse_terminal_wire(lines: Iterable[str], *, native_run: str, ion: int, particle_id: int) -> dict:
    """Parse an individual ion in a log, preserving foreign-ion rows as unrelated."""
    rows = []
    ion_ids = {}
    particle_ions = {}
    for line in lines:
        if PREFIX not in line:
            continue
        try:
            obj = json.loads(line.split(PREFIX, 1)[1], object_pairs_hook=_pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid terminal wire JSON') from exc
        row = _snapshot(obj, wire=True)
        if row['native_run'] != native_run:
            raise ValueError('terminal wire run differs')
        prior_id = ion_ids.setdefault(row['ion'], row['particle_id'])
        prior_ion = particle_ions.setdefault(row['particle_id'], row['ion'])
        if prior_id != row['particle_id'] or prior_ion != row['ion']:
            raise ValueError('terminal wire ion/particle mapping differs')
        if row['ion'] == ion:
            if row['particle_id'] != particle_id:
                raise ValueError('terminal wire identity differs')
            rows.append(row)
    return _finalize_records(rows)


def reconcile_terminal_evidence(terminal: Mapping, pre_action: Mapping | None = None,
                                post_action: Mapping | None = None, request: Mapping | None = None,
                                native_event: Mapping | None = None) -> dict:
    """Preserve recorded facts and report relationships without assigning cause."""
    values = [None if x is None else _snapshot(x) for x in (terminal, pre_action, post_action, request, native_event)]
    terminal, pre, post, request, native = values
    if terminal is None:
        raise ValueError('terminal snapshot required')
    for key in ('particle_id', 'ion', 'native_run', 'ion_run'):
        seen = [x[key] for x in values if x is not None and key in x and x[key] is not None]
        if len(set(seen)) > 1:
            raise ValueError('terminal evidence identity differs: ' + key)
    sequences = [x['capture_sequence'] for x in values if x is not None and 'capture_sequence' in x]
    if len(set(sequences)) != len(sequences):
        raise ValueError('duplicate terminal capture sequence')
    def relation(row):
        if row is None:
            return 'absent'
        a, b = row.get('instrument_time_us'), terminal.get('instrument_time_us')
        return 'unavailable' if a is None or b is None else ('before' if a < b else 'after' if a > b else 'equal')
    def exact(row, keys):
        if row is None:
            return 'absent'
        if any(row.get(k) is None or terminal.get(k) is None for k in keys):
            return 'unavailable'
        return 'equal' if all(row[k] == terminal[k] for k in keys) else 'different'
    before = None if pre is None else pre.get('splat')
    after = None if post is None else post.get('splat')
    changed = None if before is None or after is None else before == 0 and after != 0
    return {'physical_cause': 'unknown', 'observation_status': 'not_supplied', 'terminal_6d_complete': all(terminal.get(k) is not None for k in COORDINATES),
            'raw_clock_available': {k: terminal.get(k) is not None for k in CLOCKS},
            'pre_action_time_relation': relation(pre), 'post_action_time_relation': relation(post),
            'pre_action_6d': exact(pre, COORDINATES), 'post_action_6d': exact(post, COORDINATES),
            'pre_action_instance': exact(pre, ('instance',)), 'post_action_instance': exact(post, ('instance',)),
            'native_splat_before': before, 'native_splat_after': after, 'program_changed_stop': changed,
            'program_changed_stop_scope': 'retained_other_actions_pair_only',
            'facts': dict(terminal=terminal, pre_action=pre, post_action=post, request=request, native_event=native)}
