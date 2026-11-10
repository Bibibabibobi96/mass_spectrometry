"""Reuse complete-mother OA diagnostics and add cooling-stage observations."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.analysis.population_moments import population_moments
from msplatform.analysis.cooling_diagnostics import velocity_population_diagnostics
from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import build_cooled_gas_field_spec
from msplatform.contracts.gas import BoxDomain
from msplatform.contracts.rigid_transform import FramedVector, RigidTransform
from integrations.workflows.local_frontend.analyze import (
    analyze_local_frontend,
)


def _population_diagnostics(output: Path, states: pd.DataFrame, source: pd.DataFrame,
        conditioner: dict, experiment: dict, times: list[float]) -> dict:
    """Select recorded cohorts without inventing states, gas samples or losses."""
    mass_charge = source[["mass_amu", "charge_state"]].to_numpy(dtype=float)
    if (not np.isfinite(mass_charge).all() or (mass_charge[:, 0] <= 0).any()
            or (mass_charge[:, 1] == 0).any()
            or (mass_charge[:, 1] != np.trunc(mass_charge[:, 1])).any()):
        raise ValueError("source mass/charge requires positive finite mass and nonzero finite integer charge")
    # Only the provider's nominal bath state is consumed. This envelope is not
    # queried and does not claim actual gas coverage at observed particle points.
    bounds = conditioner["bounds_native_mm"]
    spec = build_cooled_gas_field_spec(conditioner, pressure_scale=experiment["pressure_scale"],
        domain=BoxDomain(tuple(bounds["min_mm"]), tuple(bounds["max_mm"]), (True,)*3, (True,)*3))
    nominal, = spec.regions
    pose = RigidTransform.from_contract(conditioner["native_to_mr"])
    reference = pose.transform_vector(FramedVector(spec.frame_id, nominal.state.bulk_velocity_m_s)).components
    census = pd.read_csv(output/"all_shared_time_census.csv", float_precision="round_trip")
    terminals = pd.read_csv(output/"all_mother_terminal_census.csv", float_precision="round_trip")
    exit_ids = set(terminals.loc[terminals.terminal_class == "exit", "particle_id"].astype(int))
    mother = source.index.astype(int).tolist()
    by_time = {float(t): frame for t, frame in states.groupby("requested_time_us", sort=True)}
    def selected(time, ids):
        frame = by_time.get(time, states.iloc[:0])
        return frame[frame.particle_id.isin(ids)]
    def groups(frame):
        result=[]
        # The source has mass/charge, not chemical species IDs or weights.
        for (mass, charge), originals in source.groupby(["mass_amu", "charge_state"], sort=True):
            cohort=frame[frame.particle_id.isin(originals.index)]
            ids=cohort.particle_id.astype(int).tolist()
            diagnostic=velocity_population_diagnostics(
                cohort[[f"v{a}_mm_per_us" for a in "xyz"]].to_numpy(dtype=float)*1000.,
                mass_amu=float(mass), charge_state=int(charge), reference_velocity_m_s=reference,
                relative_weights=None, frame_id=conditioner["frame_id"], sample_kind="time_snapshot",
                reference_label="nominal prescribed HS1 bath reference, not actual sampled gas")
            result.append(dict(particle_ids=ids, **diagnostic))
        return result
    clocks=[]
    for time in times:
        actual=selected(time,mother)
        categories={name: rows.particle_id.astype(int).tolist()
            for name,rows in census[census.instrument_time_us == time].groupby("status",sort=False)}
        exit_frame=selected(time,exit_ids)
        clocks.append(dict(instrument_time_us=time, mother_particle_ids=mother,
            particle_ids_by_category=categories, active_groups=groups(actual),
            confirmed_oa_exit_selected=dict(cohort_particle_ids=sorted(exit_ids),
                unobserved_particle_ids=sorted(exit_ids-set(exit_frame.particle_id.astype(int))),
                groups=groups(exit_frame))))
    paired=[]
    for before,after in zip(times,times[1:]):
        left,right=selected(before,mother),selected(after,mother)
        ids=sorted(set(left.particle_id.astype(int)) & set(right.particle_id.astype(int)))
        paired.append(dict(before_time_us=before,after_time_us=after,paired_particle_ids=ids,
            before=groups(selected(before,ids)),after=groups(selected(after,ids))))
    return dict(schema_version=1,role="cooled_recorded_population_diagnostics",
        mother_particle_ids=mother,
        source_record=json.loads((output/"metadata.json").read_text(encoding="utf-8"))["source"],
        source_birth_times_us={str(pid):float(source.loc[pid,"instrument_time_us"]) for pid in mother},
        instrument_time_units="us",moment_method="population_moments_centered_columnwise_numpy_float64_ddof0",weighting="explicit unit test-particle weights from generated source",
        reference=dict(kind="nominal_prescribed_bath",model=conditioner["gas"]["model"],
            source=spec.source.source_id,velocity_m_s=list(reference),frame_id=conditioner["frame_id"],
            actual_gas_sample=False),declared_clocks=clocks,consecutive_recorded_pairs=paired,
        terminal_semantics="Confirmed OA exit, timeout or unresolved native stop; non-exit is not proof of physical collision loss",
        sample_semantics="Exact recorded shared-time observations only; no propagated ended/missing states; instantaneous RF motion retained",
        effective_temperature_scope="Within each source mass/charge group only; velocity second-moment tensor, not secular/equilibrium or SDS microscopic temperature")


def analyze_cooled_frontend(run_directory: Path, log_paths: list[Path], *,
                           shared_times_us: list[float], pulse_time_us: float) -> dict:
    """Keep native stop causes unresolved while publishing every original ID.

    Instantaneous velocities include driven RF motion. Their spread is an
    observable, not a secular temperature estimate or measured gas calibration.
    """
    run = Path(run_directory).resolve()
    inputs = run/"inputs"
    summary = analyze_local_frontend(run, log_paths, phase="extraction",
                                    shared_times_us=shared_times_us, pulse_time_us=pulse_time_us)
    output = run/"results/local_frontend/extraction"
    states = pd.read_csv(output/"active_shared_states_mr.csv",float_precision="round_trip")
    source = pd.read_csv(inputs/"release_global.csv",float_precision="round_trip").set_index("particle_id", verify_integrity=True)
    conditioner = json.loads((inputs/"conditioner_contract.json").read_text())
    experiment = json.loads((inputs/"cooled_experiment.json").read_text())
    drive = json.loads((inputs/"cooled_drive.json").read_text())
    rf = conditioner["drive"]
    rows = []
    for time, population in states.groupby("requested_time_us", sort=True):
        masses = source.loc[population.particle_id, "mass_amu"].to_numpy(dtype=float)
        velocities = population[[f"v{a}_mm_per_us" for a in "xyz"]].to_numpy(dtype=float)*1000.
        position = population[[f"{a}_mm" for a in "xyz"]].to_numpy(dtype=float)
        energy = np.array([[kinetic_energy_ev(float(m), *(v[j] if j == k else 0. for j in range(3)))
                            for k in range(3)] for m,v in zip(masses, velocities, strict=True)])
        moments = population_moments(np.column_stack((position,velocities)))
        covariance = moments.covariance
        energy_moments = population_moments(energy)
        row = dict(instrument_time_us=float(time), active_count=len(population),
                   active_ids=population.particle_id.astype(int).tolist(),
                   rf_phase_rad=float((2*np.pi*rf["frequency_hz"]*time*1e-6+rf["phase_rad"])%(2*np.pi)),
                   phase="capture" if time<drive["entrance_close_us"] else "closed" if time<drive["release_start_us"] else "released",
                   covariance_xyz_mm_velocity_m_s=covariance.tolist())
        for k,axis in enumerate("xyz"):
            row.update({f"mean_{axis}_mm":float(moments.mean[k]),
                        f"sigma_{axis}_mm":float(np.sqrt(covariance[k,k])),
                        f"mean_E{axis}_ev":float(energy_moments.mean[k]),
                        f"sigma_v{axis}_m_s":float(np.sqrt(covariance[k+3,k+3]))})
        rows.append(row)
    document = dict(schema_version=1,role="cooled_frontend_recorded_cooling_evolution",
        pressure_scale=experiment["pressure_scale"],mother_count=len(source),snapshots=rows,
        common_pulse_decision=experiment["common_pulse_decision"],
        interpretation="Conditional active populations at exact recorded clocks; full mother/terminal census retained alongside. RF velocities are instantaneous, not secular temperatures.",
        collision_model=conditioner["gas"]["model"],
        qualification="Local native observations only; HS1 prescribed bath and cross section remain model assumptions")
    (output/"cooling_evolution.json").write_text(json.dumps(document,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    flat = [{k:v for k,v in row.items() if k not in {"active_ids","covariance_xyz_mm_velocity_m_s"}} for row in rows]
    frame = pd.DataFrame(flat)
    frame.to_csv(output/"cooling_evolution.csv",index=False)
    if len(frame):
        figure, axes = plt.subplots(2,3,figsize=(13,7),constrained_layout=True)
        for k,axis in enumerate("xyz"):
            axes[0,k].plot(frame.instrument_time_us,frame[f"mean_E{axis}_ev"],"o-",ms=3)
            axes[0,k].set_ylabel(f"Mean E{axis} (eV), active ions")
            axes[1,k].plot(frame.instrument_time_us,frame[f"sigma_{axis}_mm"],"o-",ms=3)
            axes[1,k].set_ylabel(f"Population sigma {axis} (mm), active ions")
        for ax in axes.flat:
            for label,clock,color in (("Entrance close",drive["entrance_close_us"],"#8F6B2D"),
                                      ("Gate release",drive["release_start_us"],"#675096"),
                                      ("OA pulse",pulse_time_us,"#C04B37")):
                ax.axvline(clock,color=color,lw=.8,label=label)
            ax.set_xlabel("Instrument time (us)")
            ax.grid(alpha=.2)
        axes[0,0].legend(fontsize=7)
        figure.suptitle("Recorded cooling and release evolution — instantaneous RF motion included")
        for ext in ("png","svg"):
            figure.savefig(output/f"cooling_evolution.{ext}",dpi=190)
        plt.close(figure)
    diagnostic_path=output/"cooling_population_diagnostics.json"
    diagnostic_path.write_text(json.dumps(_population_diagnostics(output,states,source,conditioner,experiment,
        shared_times_us),indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    return dict(summary,cooling_population_diagnostics_record=str(diagnostic_path),cooling_evolution_record=str(output/"cooling_evolution.json"),
                output_paths=[str(p) for p in sorted(output.iterdir()) if p.is_file()])
