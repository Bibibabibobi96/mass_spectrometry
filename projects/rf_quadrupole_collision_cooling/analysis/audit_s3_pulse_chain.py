"""Audit S3 identity, clock, pulse-state and local-exit continuity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.contracts.component_particle_state import validate_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev



def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_finite_columns(
    table: pd.DataFrame,
    required: set[str],
    numeric: set[str],
    name: str,
) -> None:
    missing = required - set(table.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")
    if numeric and not np.isfinite(
        table[list(numeric)].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    ).all():
        raise ValueError(f"{name} contains non-finite values")


def audit(source_path: Path, terminal_path: Path, capture_path: Path,
          local_exit_path: Path, schedule_path: Path,
          contract_path: Path) -> dict[str, Any]:
    """Return compact continuity metrics or fail closed on any mismatch."""
    source = pd.read_csv(source_path)
    terminal = pd.read_csv(terminal_path)
    capture = pd.read_csv(capture_path)
    validate_component_particle_state_csv(source_path)
    validate_component_particle_state_csv(local_exit_path)
    local_exit = pd.read_csv(local_exit_path)
    schedule = _load(schedule_path)
    contract = _load(contract_path)
    terminal_required = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
        "lineage_age_us", "particle_age_us", "last_component_elapsed_time_us",
        "mass_amu", "charge_state", "vx_m_s", "vy_m_s", "vz_m_s",
        "kinetic_energy_eV", "event", "first_forward_oatof_entry",
    }
    _require_finite_columns(
        terminal,
        terminal_required,
        terminal_required
        - {"frame_id", "clock_epoch_id", "event"},
        "S3 terminal census",
    )
    capture_required = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
        "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s",
        "inside_oatof_ideal_reference_volume", "active_at_pulse",
    }
    _require_finite_columns(
        capture,
        capture_required,
        capture_required - {"frame_id", "clock_epoch_id"},
        "S3 pulse state",
    )
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
    expected_frame = "oatof_global"
    expected_epoch = contract["source"]["clock_epoch_id"]
    if (
        set(source["frame_id"]) != {expected_frame}
        or set(source["clock_epoch_id"]) != {expected_epoch}
        or set(terminal["frame_id"]) != {expected_frame}
        or set(terminal["clock_epoch_id"]) != {expected_epoch}
        or (not capture.empty and set(capture["frame_id"]) != {expected_frame})
        or (not capture.empty and set(capture["clock_epoch_id"]) != {expected_epoch})
        or set(local_exit["frame_id"]) != {expected_frame}
        or set(local_exit["clock_epoch_id"]) != {expected_epoch}
    ):
        raise ValueError("S3 frame or clock epoch is not continuous")
    target_species = schedule.get("target_species", {})
    if (
        schedule.get("stage") != "S3"
        or float(target_species.get("mass_amu", float("nan")))
        != float(contract["source"]["target_mass_amu"])
        or target_species.get("charge_state")
        != contract["source"]["target_charge_state"]
    ):
        raise ValueError("S3 schedule target species differs from the contract")
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
    local_identity = local_exit.merge(
        source[["particle_id", "species_id", "mass_amu", "charge_state"]],
        on="particle_id",
        suffixes=("_out", "_in"),
        validate="one_to_one",
    )
    if (
        not (local_identity["species_id_out"] == local_identity["species_id_in"]).all()
        or not np.allclose(
            local_identity["mass_amu_out"],
            local_identity["mass_amu_in"],
            rtol=0,
            atol=0,
        )
        or not (
            local_identity["charge_state_out"]
            == local_identity["charge_state_in"]
        ).all()
    ):
        raise ValueError("S3 canonical local-exit species identity changed")
    elapsed = merged["last_component_elapsed_time_us"]
    residuals = np.concatenate([
        (merged["instrument_time_us_out"]-merged["instrument_time_us_in"]-elapsed).to_numpy(),
        (merged["lineage_age_us_out"]-merged["lineage_age_us_in"]-elapsed).to_numpy(),
        (merged["particle_age_us_out"]-merged["particle_age_us_in"]-elapsed).to_numpy(),
    ])
    maximum_clock_residual = float(np.max(np.abs(residuals)))
    if maximum_clock_residual > 1e-9:
        raise ValueError("S3 clock continuity residual exceeds tolerance")
    energy = kinetic_energy_ev(
        terminal["mass_amu"],
        terminal["vx_m_s"],
        terminal["vy_m_s"],
        terminal["vz_m_s"],
    )
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
