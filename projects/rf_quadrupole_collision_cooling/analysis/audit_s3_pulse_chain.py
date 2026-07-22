"""Audit S3 identity, clock, pulse-state and local-exit continuity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ATOMIC_MASS_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(source_path: Path, terminal_path: Path, capture_path: Path,
          local_exit_path: Path, schedule_path: Path,
          contract_path: Path) -> dict[str, Any]:
    """Return compact continuity metrics or fail closed on any mismatch."""
    source = pd.read_csv(source_path)
    terminal = pd.read_csv(terminal_path)
    capture = pd.read_csv(capture_path)
    local_exit = pd.read_csv(local_exit_path)
    schedule = _load(schedule_path)
    contract = _load(contract_path)
    if len(source) != int(contract["source"]["source_particles"]):
        raise ValueError("S3 source count differs from the contract")
    if source["particle_id"].duplicated().any() or terminal["particle_id"].duplicated().any():
        raise ValueError("S3 particle identity is not unique")
    source_ids = set(source["particle_id"])
    if set(terminal["particle_id"]) != source_ids:
        raise ValueError("S3 terminal census does not preserve every source ID")
    if not set(capture["particle_id"]).issubset(source_ids):
        raise ValueError("S3 capture state contains an unknown particle ID")
    if not set(local_exit["particle_id"]).issubset(source_ids):
        raise ValueError("S3 local exit contains an unknown particle ID")
    required_local_exit = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
        "lineage_age_us", "particle_age_us", "mass_amu", "charge_state",
        "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s",
        "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV", "source_rf_phase_rad",
    }
    if not required_local_exit.issubset(local_exit.columns):
        raise ValueError("S3 local exit is not a complete canonical particle state")

    merged = terminal.merge(
        source[["particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
                "lineage_age_us", "particle_age_us", "mass_amu", "charge_state"]],
        on="particle_id", suffixes=("_out", "_in"), validate="one_to_one")
    if not (merged["frame_id_out"] == merged["frame_id_in"]).all():
        raise ValueError("S3 terminal frame changed")
    if not (merged["clock_epoch_id_out"] == merged["clock_epoch_id_in"]).all():
        raise ValueError("S3 terminal clock epoch changed")
    if not np.allclose(merged["mass_amu_out"], merged["mass_amu_in"], rtol=0, atol=0):
        raise ValueError("S3 terminal mass changed")
    if not (merged["charge_state_out"] == merged["charge_state_in"]).all():
        raise ValueError("S3 terminal charge changed")
    elapsed = merged["last_component_elapsed_time_us"]
    residuals = np.concatenate([
        (merged["instrument_time_us_out"]-merged["instrument_time_us_in"]-elapsed).to_numpy(),
        (merged["lineage_age_us_out"]-merged["lineage_age_us_in"]-elapsed).to_numpy(),
        (merged["particle_age_us_out"]-merged["particle_age_us_in"]-elapsed).to_numpy(),
    ])
    maximum_clock_residual = float(np.max(np.abs(residuals)))
    if maximum_clock_residual > 1e-9:
        raise ValueError("S3 clock continuity residual exceeds tolerance")
    speed_squared = (
        terminal["vx_m_s"]**2 + terminal["vy_m_s"]**2 + terminal["vz_m_s"]**2)
    energy = 0.5*terminal["mass_amu"]*ATOMIC_MASS_KG*speed_squared/ELEMENTARY_CHARGE_C
    energy_residual = np.abs(energy-terminal["kinetic_energy_eV"])/terminal["kinetic_energy_eV"]
    maximum_energy_residual = float(energy_residual.max())
    if maximum_energy_residual > 1e-10:
        raise ValueError("S3 velocity-energy residual exceeds tolerance")

    pulse_time = float(schedule["derived_pulse_time_us"])
    if not capture.empty and not np.allclose(capture["instrument_time_us"], pulse_time, rtol=0, atol=1e-9):
        raise ValueError("S3 capture rows do not share the scheduled pulse time")
    if not capture.empty and not capture["active_at_pulse"].astype(bool).all():
        raise ValueError("S3 capture table contains an inactive particle")
    transmitted = terminal[terminal["event"].eq("local_accelerator_exit")]
    if set(transmitted["particle_id"]) != set(local_exit["particle_id"]):
        raise ValueError("S3 terminal and canonical local-exit ID sets differ")
    if len(capture) < int(contract["runtime"]["minimum_active_at_pulse"]):
        raise ValueError("S3 active pulse population misses the functional minimum")
    if len(local_exit) < int(contract["runtime"]["minimum_local_accelerator_exit"]):
        raise ValueError("S3 local exit population misses the functional minimum")
    return {
        "schema_version": 1,
        "role": "rf_to_oatof_s3_particle_chain_audit",
        "status": "PASS",
        "source_particles": int(len(source)),
        "oatof_entry_crossings": int(terminal["first_forward_oatof_entry"].astype(bool).sum()),
        "active_at_pulse": int(len(capture)),
        "inside_ideal_reference_volume_at_pulse": int(
            capture["inside_oatof_ideal_reference_volume"].astype(bool).sum()),
        "local_accelerator_exit": int(len(local_exit)),
        "pulse_time_us": pulse_time,
        "pulse_width_us": float(schedule["pulse_width_us"]),
        "maximum_clock_residual_us": maximum_clock_residual,
        "maximum_energy_velocity_relative_residual": maximum_energy_residual,
        "dense_trajectories_saved": False,
        "s3_stage_passed": False,
        "formal_gate_passed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--local-exit", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source, args.terminal, args.capture, args.local_exit,
                   args.schedule, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(
        f"S3_PARTICLE_CHAIN_AUDIT=PASS SOURCE={result['source_particles']} "
        f"ACTIVE={result['active_at_pulse']} LOCAL_EXIT={result['local_accelerator_exit']}"
    )


if __name__ == "__main__":
    main()
