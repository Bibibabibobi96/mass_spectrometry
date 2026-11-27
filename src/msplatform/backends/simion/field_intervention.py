"""SIMION projection and result analysis for a single frozen field intervention.

The caller owns the source, field, geometry, clock, process and result lifecycle.
This adapter neither selects scientific cases nor launches a solver.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from msplatform.backends.simion.detector_census import analyze_simion_log


from msplatform.contracts.field_intervention import _case
from msplatform.contracts.field_intervention import resolve_field_selector as resolve_field_selector


def build_field_intervention_argv(*, case: Mapping[str, Any], particle_count: int,
                                  particle_table: Path, iob: Path,
                                  trajectory_quality: int) -> list[str]:
    """Project a case and explicit inputs; do not execute or generate a cohort."""
    _, flags = _case(case)
    if type(particle_count) is not int or particle_count < 1:
        raise ValueError('particle_count must be a positive integer')
    if type(trajectory_quality) is not int or trajectory_quality < 1:
        raise ValueError('trajectory_quality must be a positive integer')
    particle_table, iob = Path(particle_table), Path(iob)
    if not particle_table.is_absolute() or not iob.is_absolute():
        raise ValueError('particle and IOB paths must be absolute')
    return [
        '--default-num-particles', str(particle_count), '--nogui', 'fly', '--retain-trajectories', '0',
        '--particles', str(particle_table), '--adjustable', f'trajectory_quality={trajectory_quality}',
        '--adjustable', 'ideal_accel_enable=0', '--adjustable', f'ideal_refl_stage1_enable={flags.get("S1_FULL", 0)}',
        '--adjustable', f'ideal_refl_stage2_enable={flags.get("S2_FULL", 0)}',
        '--adjustable', f'ideal_accel_ez_enable={flags["A"]}',
        '--adjustable', f'ideal_drift_ez_enable={flags["D"]}',
        '--adjustable', f'ideal_refl_stage1_ez_enable={flags["S1"]}',
        '--adjustable', f'ideal_refl_stage2_ez_enable={flags["S2"]}',
        '--adjustable', 'trajectory_log_enable=1', str(iob),
    ]


def analyze_field_intervention(*, case: Mapping[str, Any], log: Path, particle_table: Path,
                               particle_count: int, detector_radius_mm: float):
    """Read a complete detector census and preserve unavailable metrics as null."""
    case_id, _ = _case(case)
    if type(particle_count) is not int or particle_count < 1:
        raise ValueError('particle_count must be a positive integer')
    frame, summary = analyze_simion_log(Path(log), Path(particle_table), mode=case_id,
        distribution='shared', detector_radius_mm=detector_radius_mm, allow_incomplete_census=False)
    if summary['Emitted'] != particle_count:
        raise ValueError('Diagnostic source particle count differs from its frozen run control.')
    return frame, summary
