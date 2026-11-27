"""Focus measurements from canonical SI particle and plane-event records."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any
from msplatform.contracts.particle_state import binary64_serialization_close


def _states(rows: Sequence[Mapping[str, Any]], label: str) -> dict[int, Mapping[str, Any]]:
    found={}
    for row in rows:
        pid=row.get('particle_id')
        if type(pid) is not int or pid<=0 or pid in found:
            raise ValueError(label+' requires unique positive particle identities')
        if not isinstance(row.get('species_id'),str) or not row['species_id']:
            raise ValueError(label+' requires explicit species identity')
        for name in ('position_m','velocity_m_s'):
            values=row.get(name)
            if not isinstance(values,(list,tuple)) or len(values)!=3 or any(
                    type(x) not in (int,float) or not math.isfinite(x) for x in values):
                raise ValueError(label+' requires finite SI 6D coordinates')
        t=row.get('time_s')
        if type(t) not in (int,float) or not math.isfinite(t):
            raise ValueError(label+' requires finite experiment-clock time')
        found[pid]=row
    if not found:
        raise ValueError(label+' cohort is empty')
    return found


def focus_plane_measurements(initial_states: Sequence[Mapping[str, Any]],
                             terminal_states: Sequence[Mapping[str, Any]],
                             events: Sequence[Mapping[str, Any]], *,
                             frame_id: str, exit_surface_id: str, focus_surface_id: str,
                             exit_z_m: float, focus_z_m: float,
                             plane_tolerance_m: float) -> dict[str, Any]:
    """Measure observed directed crossings; absent crossings remain absent.

    All inputs share one explicitly chosen OA local frame and experiment clock.
    This makes no physical-loss or scientific-qualification decision.
    """
    if any(not isinstance(x,str) or not x for x in (frame_id,exit_surface_id,focus_surface_id)):
        raise ValueError('explicit frame, exit and focus surface identities are required')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in (exit_z_m,focus_z_m,plane_tolerance_m)) or plane_tolerance_m<=0:
        raise ValueError('finite plane coordinates and positive tolerance are required')
    if exit_surface_id==focus_surface_id and exit_z_m!=focus_z_m:
        raise ValueError('one surface cannot identify two distinct planes')
    starts=_states(initial_states,'initial states');ends=_states(terminal_states,'terminal states')
    if set(starts)!=set(ends):
        raise ValueError('initial and terminal cohorts differ')
    for pid,start in starts.items():
        if ends[pid]['species_id']!=start['species_id'] or ends[pid]['time_s']<start['time_s']:
            raise ValueError('terminal species or experiment-clock lifetime differs')
    chosen={pid:{} for pid in starts};seen=set()
    for row in events:
        pid=row.get('particle_id')
        if pid not in starts or row.get('species_id')!=starts[pid]['species_id']:
            raise ValueError('plane event has foreign particle or species identity')
        name=row.get('surface_id')
        if name not in {exit_surface_id,focus_surface_id}:
            continue
        validated=_states([row],'plane event')[pid]
        if validated.get('event_kind')!='observation':
            raise ValueError('focus planes require observation events')
        if not starts[pid]['time_s']<=row['time_s']<=ends[pid]['time_s']:
            raise ValueError('plane event is outside the particle lifetime')
        seq=row.get('event_sequence')
        if type(seq) is not int or seq<1 or (pid,seq) in seen:
            raise ValueError('plane event sequence is absent or duplicated')
        seen.add((pid,seq))
        if row['velocity_m_s'][2]>=0:
            continue
        expected=exit_z_m if name==exit_surface_id else focus_z_m
        if abs(row['position_m'][2]-expected)>plane_tolerance_m:
            raise ValueError('plane event is outside its declared surface tolerance')
        for role,surface in (('exit',exit_surface_id),('focus',focus_surface_id)):
            if name==surface:
                previous=chosen[pid].get(role)
                if previous is None or (row['time_s'],seq)<(previous['time_s'],previous['event_sequence']):
                    chosen[pid][role]=row
    for pid,items in chosen.items():
        if 'focus' in items and 'exit' not in items:
            raise ValueError('focus crossing lacks the earlier exit observation')
        if 'exit' in items and 'focus' in items and items['exit']['time_s']>items['focus']['time_s']:
            raise ValueError('focus crossing precedes the exit crossing')
        if 'exit' in items and 'focus' in items and exit_z_m==focus_z_m:
            a,b=items['exit'],items['focus']
            if (not binary64_serialization_close(a['time_s'],b['time_s']) or any(
                    not binary64_serialization_close(x,y) for name in ('position_m','velocity_m_s')
                    for x,y in zip(a[name],b[name],strict=True))):
                raise ValueError('same-plane exit and focus observations differ')
    hits=[(starts[pid],parts['focus']) for pid,parts in chosen.items() if 'focus' in parts]
    times=[hit['time_s'] for _,hit in hits]
    durations=[hit['time_s']-start['time_s'] for start,hit in hits]
    rms=math.sqrt(fmean(hit['position_m'][0]**2+hit['position_m'][1]**2 for _,hit in hits)) if hits else None
    return dict(schema_version=1,role='oa_focus_plane_measurements',frame_id=frame_id,particle_count=len(starts),
        focus_particle_count=len(hits),not_reached_focus_particle_ids=sorted(pid for pid in starts if 'focus' not in chosen[pid]),
        transport_fraction=len(hits)/len(starts),mean_arrival_s=fmean(times) if times else None,
        peak_to_peak_arrival_s=max(times)-min(times) if len(times)>=2 else None,
        mean_propagation_s=fmean(durations) if durations else None,
        peak_to_peak_propagation_s=max(durations)-min(durations) if len(durations)>=2 else None,
        transverse_rms_radius_m=rms,
        exit_observed_particle_ids=sorted(pid for pid in starts if 'exit' in chosen[pid]),
        selected_exit_states=[dict(chosen[pid]['exit']) for pid in sorted(chosen) if 'exit' in chosen[pid]],
        selected_focus_states=[dict(chosen[pid]['focus']) for pid in sorted(chosen) if 'focus' in chosen[pid]])
