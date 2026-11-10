"""Moments of caller-selected resolved velocities; no collision or thermal model."""
from __future__ import annotations

import math
import numpy as np

from msplatform.analysis.population_moments import population_moments
from msplatform.contracts.particle_physics import AMU_KG, BOLTZMANN_CONSTANT_J_K, kinetic_energy_ev


def velocity_population_diagnostics(velocities_m_s: np.ndarray, *, mass_amu: float,
        charge_state: int, reference_velocity_m_s: tuple[float, float, float],
        relative_weights: np.ndarray | None, frame_id: str, sample_kind: str,
        reference_label: str) -> dict:
    """Describe one explicit homogeneous mass/charge cohort in one fixed frame.

    Weights are positive relative statistical weights, or explicit None for unit
    weights. Reference velocity is caller supplied in m/s in the same frame; it
    is not inferred to be actual gas. Samples are resolved instantaneous particle
    velocities, including RF motion. The second-moment tensor is not secular or
    equilibrium temperature. No SDS microscopic-velocity interpretation is made.
    Empty populations retain metadata with null moments. Invalid values raise.
    """
    if isinstance(mass_amu, bool) or not math.isfinite(mass_amu) or mass_amu <= 0:
        raise ValueError("positive finite cohort mass required")
    if type(charge_state) is not int or charge_state == 0:
        raise ValueError("nonzero integer cohort charge required")
    if not isinstance(frame_id, str) or not frame_id or not isinstance(reference_label, str) or not reference_label:
        raise ValueError("explicit frame and velocity reference label required")
    if sample_kind not in {"time_snapshot", "plane_crossing", "event"}:
        raise ValueError("explicit sample kind required")
    if np.iscomplexobj(velocities_m_s) or np.iscomplexobj(reference_velocity_m_s):
        raise ValueError("velocity and reference must contain real values")
    velocity = np.asarray(velocities_m_s, dtype=float)
    reference = np.asarray(reference_velocity_m_s, dtype=float)
    if velocity.ndim != 2 or velocity.shape[1] != 3 or reference.shape != (3,) or not np.isfinite(reference).all():
        raise ValueError("three finite reference components and Nx3 velocities required")
    moments = population_moments(velocity, relative_weights)
    relative = velocity-reference
    laboratory_energy = np.array([kinetic_energy_ev(mass_amu, *row) for row in velocity]).reshape(-1, 1)
    reference_energy = np.array([kinetic_energy_ev(mass_amu, *row) for row in relative]).reshape(-1, 1)
    laboratory = population_moments(laboratory_energy, relative_weights)
    referenced = population_moments(reference_energy, relative_weights)
    return dict(sample_count=moments.sample_count, weight_sum=moments.weight_sum,
        effective_sample_count=moments.effective_sample_count, mass_amu=float(mass_amu), charge_state=charge_state,
        frame_id=frame_id, sample_kind=sample_kind, velocity_units="m/s", energy_units="eV",
        covariance_normalization="population_ddof_0_divide_by_sum_weights",
        weighting="unit" if relative_weights is None else "explicit_relative",
        reference=dict(label=reference_label, velocity_m_s=reference.tolist(), frame_id=frame_id),
        mean_velocity_m_s=None if moments.mean is None else moments.mean.tolist(),
        velocity_covariance_m2_s2=None if moments.covariance is None else moments.covariance.tolist(),
        effective_second_moment_tensor_k=None if moments.covariance is None else
            (float(mass_amu)*AMU_KG/BOLTZMANN_CONSTANT_J_K*moments.covariance).tolist(),
        mean_laboratory_energy_ev=None if laboratory.mean is None else float(laboratory.mean[0]),
        mean_reference_relative_energy_ev=None if referenced.mean is None else float(referenced.mean[0]),
        interpretation="Resolved instantaneous velocity second moments, including RF motion; not equilibrium, secular temperature, SDS microscopic temperature or a collision count")
