"""Reuse complete-mother OA diagnostics and add cooling-stage observations."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.workflows.local_frontend.analyze import (
    analyze_local_frontend,
)


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
        covariance = np.cov(np.column_stack((position,velocities)), rowvar=False, bias=True) if len(population)>1 else np.zeros((6,6))
        row = dict(instrument_time_us=float(time), active_count=len(population),
                   active_ids=population.particle_id.astype(int).tolist(),
                   rf_phase_rad=float((2*np.pi*rf["frequency_hz"]*time*1e-6+rf["phase_rad"])%(2*np.pi)),
                   phase="capture" if time<drive["entrance_close_us"] else "closed" if time<drive["release_start_us"] else "released",
                   covariance_xyz_mm_velocity_m_s=covariance.tolist())
        for k,axis in enumerate("xyz"):
            row.update({f"mean_{axis}_mm":float(position[:,k].mean()),
                        f"sigma_{axis}_mm":float(position[:,k].std()),
                        f"mean_E{axis}_ev":float(energy[:,k].mean()),
                        f"sigma_v{axis}_m_s":float(velocities[:,k].std())})
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
    return dict(summary,cooling_evolution_record=str(output/"cooling_evolution.json"),
                output_paths=[str(p) for p in sorted(output.iterdir()) if p.is_file()])
