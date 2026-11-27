"""Compare the four explicitly identified independent-OA field interventions."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

_MODES=('native','zone1_ideal','zone2_ideal','full_ideal')


def compare_focus_field_cases(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Compare actual SI case analyses of one fully identical original cohort.

    The caller must authenticate each case selector, field identity and frozen
    source. This reduction makes no vendor or physical-qualification claim.
    """
    if not isinstance(cases,Mapping) or set(cases)!=set(_MODES):
        raise ValueError('focus contrast requires exactly the four OA field modes')
    common=None;widths={};energy={};incomplete=[]
    for mode in _MODES:
        case=cases[mode]
        if not isinstance(case,Mapping) or case.get('field_mode')!=mode:
            raise ValueError('focus case mode identity differs')
        source=case.get('source_identity');initial=case.get('initial_states');metadata=case.get('metadata')
        if (not isinstance(source,Mapping) or not source or not isinstance(initial,list) or not initial
                or not isinstance(metadata,Mapping) or not isinstance(metadata.get('frame_id'),str)
                or not isinstance(metadata.get('clock'),Mapping)):
            raise ValueError('focus case lacks original cohort, frame or clock')
        identity=(source,initial,metadata['frame_id'],metadata['clock'])
        if common is not None and identity!=common:
            raise ValueError('focus cases do not share their original birth cohort and clock')
        common=copy.deepcopy(identity)
        analysis=case.get('analysis')
        if (not isinstance(analysis,Mapping) or analysis.get('role')!='oa_focus_si_analysis'
                or analysis.get('status')!='analyzed'):
            raise ValueError('focus case analysis is absent or incomplete')
        measurement=analysis.get('measurements',{});assessment=analysis.get('energy_assessment',{})
        if (measurement.get('particle_count')!=len(initial) or not isinstance(assessment,Mapping)):
            raise ValueError('focus case analysis cohort or energy evidence differs')
        width=measurement.get('peak_to_peak_arrival_s')
        if width is None:
            widths[mode]=None;incomplete.append(mode)
        elif type(width) not in (int,float) or not math.isfinite(width) or width<0.:
            raise ValueError('focus arrival width must be finite and nonnegative')
        else:
            widths[mode]=float(width)*1e9
        energy[mode]=copy.deepcopy(dict(assessment))
    reductions={mode:(None if widths['native'] is None or widths[mode] is None else widths['native']-widths[mode])
                for mode in _MODES if mode!='native'}
    if incomplete:
        dominant=None;recommendation=None;status='incomplete'
    else:
        z1,z2=reductions['zone1_ideal'],reductions['zone2_ideal']
        dominant=('zone2_finite_field' if z2>z1+.05 else 'zone1_finite_field' if z1>z2+.05
                  else 'distributed_or_indeterminate')
        recommendation={'zone2_finite_field':'increase_zone2_ring_count_before_expanding_y_or_mesh',
            'zone1_finite_field':'inspect_grid1_repeller_transition_before_changing_zone2_ring_count',
            'distributed_or_indeterminate':'inspect_both_zone_boundaries_before_geometry_change'}[dominant]
        status='diagnostic'
    return dict(schema_version=1,role='oa_focus_field_contrast',status=status,field_modes=list(_MODES),
        peak_to_peak_t_ns=widths,exit_energy_assessment=energy,native_reduction_toward_ideal_ns=reductions,
        dominant_finite_field_region=dominant,recommended_next_geometry_action=recommendation,
        incomplete_field_modes=incomplete)
