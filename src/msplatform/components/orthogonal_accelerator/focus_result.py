"""OA-specific focus analysis over validated solver-neutral SI records."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from msplatform.analysis.oa_focus_events import focus_plane_measurements
from msplatform.contracts.particle_physics import AMU_KG
from msplatform.contracts.particle_state import binary64_serialization_close
from msplatform.contracts.species import validate_species
from msplatform.io.file_identity import canonical_json_sha256
from .focus_campaign import validate_campaign
from .focus_theory import _exit_energy_assessment, _ideal_two_zone_contrast


def analyze_focus_result(data: Mapping[str, Any], *, campaign: Mapping[str, Any],
                         geometry_profile: Mapping[str, Any], authority: Mapping[str, Any],
                         projected_birth_rows: list[Mapping[str, Any]], exit_surface_id: str, focus_surface_id: str) -> dict[str, Any]:
    """Analyze one complete SI cohort using the authenticated original focus author.

    The caller authenticates campaign/contract/model, supplies the same frozen
    birth packet projected through the native geometry, and owns source lifetime.
    Nonpositive-charge species retain geometric metrics, but the historical
    positive-ion ideal and energy-target theory is explicitly unavailable.
    """
    campaign=validate_campaign(dict(campaign),geometry_profile=geometry_profile)
    if (data.get('execution_status')!='succeeded' or data.get('data_integrity',{}).get('status')!='complete'):
        raise ValueError('focus analysis requires complete successful particle evidence')
    if (authority.get('role')!='oa_focus_plane_authority' or authority.get('schema_version')!=1
            or authority.get('campaign_content_sha256')!=canonical_json_sha256(campaign)
            or authority.get('geometry_profile_sha256')!=canonical_json_sha256(dict(geometry_profile))
            or authority.get('focus_z_mm')!=campaign['operating_point']['focus_plane_offset_from_exit_mm']
            or authority.get('exit_z_mm')!=0. or authority.get('direction')!='negative_z'):
        raise ValueError('focus analysis authority differs from its original author')
    metadata=data.get('metadata',{});clock=metadata.get('clock',{});declared=authority.get('clock',{})
    if (metadata.get('frame_id')!=authority.get('frame_id')
            or any(clock.get(key)!=declared.get(key) for key in ('clock_epoch_id','authority_sha256'))):
        raise ValueError('focus particle frame or clock differs from its authority')
    initial=data.get('initial_states');terminal=data.get('terminal_states');events=data.get('events')
    if not all(isinstance(value,list) for value in (initial,terminal,events)):
        raise ValueError('focus particle products require explicit lists')
    species=campaign['release_spec']['species'];mass=float(species['mass_amu'])*AMU_KG;charge=species['charge_state']
    registry=metadata.get('species')
    if not isinstance(registry,list) or len(registry)!=1:
        raise ValueError('focus source requires its single explicit species identity')
    registered=validate_species(registry[0])
    if (registered['species_kind']!=species['species_kind'] or registered['charge_state']!=charge
            or not math.isclose(registered['mass_kg'],mass,rel_tol=1e-14,abs_tol=0.)):
        raise ValueError('focus species registry differs from its original author')
    for row in initial:
        if (row.get('species_id')!=registered['species_id'] or row.get('charge_state')!=charge
                or row.get('charge_c')!=registered['charge_c']
                or not math.isclose(float(row.get('mass_kg',math.nan)),mass,rel_tol=1e-14,abs_tol=0.)):
            raise ValueError('focus particle mass or signed charge differs from its original author')
    births=projected_birth_rows
    if not isinstance(births,list) or len(births)!=len(initial):
        raise ValueError('focus source differs from its frozen birth cohort')
    by_id={row.get('particle_id'):row for row in births if isinstance(row,Mapping)}
    if len(by_id)!=len(births) or {row.get('particle_id') for row in initial}!=set(by_id):
        raise ValueError('focus source differs from its frozen birth cohort')
    for row in initial:
        birth=by_id[row['particle_id']]
        if (birth.get('species_id')!=row['species_id'] or birth.get('charge_state')!=charge
                or birth.get('frame_id')!=metadata['frame_id']
                or birth.get('clock_epoch_id')!=clock['clock_epoch_id']
                or not math.isclose(float(birth.get('mass_amu',math.nan))*AMU_KG,mass,rel_tol=1e-14,abs_tol=0.)
                or not binary64_serialization_close(float(birth.get('particle_weight',math.nan)),float(row.get('weight',math.nan)))
                or not binary64_serialization_close(float(birth.get('instrument_time_us',math.nan)),float(row['time_s'])*1e6)
                or any(not binary64_serialization_close(float(birth.get(f'position_{axis}_mm',math.nan)),float(row['position_m'][i])*1e3)
                       or not binary64_serialization_close(float(birth.get(f'velocity_{axis}_m_s',math.nan)),float(row['velocity_m_s'][i]))
                       for i,axis in enumerate('xyz'))):
            raise ValueError('focus source differs from its frozen birth cohort')
    if any(row.get('component_id') != authority.get('component_id') for row in events
           if row.get('surface_id') in {exit_surface_id,focus_surface_id}):
        raise ValueError('focus event component differs from the authenticated authority')
    tolerance=float(campaign['acceptance']['focus_plane_tolerance_mm'])
    measured=focus_plane_measurements(initial,terminal,events,frame_id=authority['frame_id'],
        exit_surface_id=exit_surface_id,focus_surface_id=focus_surface_id,exit_z_m=0.,
        focus_z_m=float(authority['focus_z_mm'])*1e-3,plane_tolerance_m=tolerance*1e-3)
    if species['species_kind']!='ion' or charge<=0:
        return dict(schema_version=1,role='oa_focus_si_analysis',status='analyzed',measurements=measured,
                    energy_assessment={'status':'unsupported_nonpositive_charge'},
                    ideal_contrast={'status':'unsupported_nonpositive_charge'})
    def state(row):
        p=row['position_m'];v=row['velocity_m_s']
        return dict(t_us=row['time_s']*1e6,x_mm=p[0]*1e3,y_mm=p[1]*1e3,z_mm=p[2]*1e3,
                    vx_mm_us=v[0]/1e3,vy_mm_us=v[1]/1e3,vz_mm_us=v[2]/1e3)
    sources={row['particle_id']:dict(state(row),vx_m_s=row['velocity_m_s'][0],
        vy_m_s=row['velocity_m_s'][1],vz_m_s=row['velocity_m_s'][2]) for row in initial}
    by_id={pid:{} for pid in sources}
    for role,key in (('exit','selected_exit_states'),('focus','selected_focus_states')):
        for row in measured[key]:by_id[row['particle_id']][role]=state(row)
    hits={pid:(sources[pid],rows['focus']) for pid,rows in by_id.items() if 'focus' in rows}
    energy=_exit_energy_assessment(sources,by_id,campaign,tolerance,geometry_profile=geometry_profile)
    ideal=_ideal_two_zone_contrast(hits,campaign,geometry_profile=geometry_profile)
    return dict(schema_version=1,role='oa_focus_si_analysis',status='analyzed',measurements=measured,
                energy_assessment=energy,ideal_contrast=ideal)
