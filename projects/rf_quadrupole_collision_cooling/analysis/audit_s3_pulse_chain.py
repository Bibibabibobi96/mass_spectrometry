"""Audit S3 identity, clock, pulse-state and local-exit continuity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.contracts.component_particle_state import validate_component_particle_state_csv



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


def _boolean_series(values: pd.Series, name: str) -> pd.Series:
    normalized = values.astype(str).str.strip().str.lower()
    accepted = {"true": True, "1": True, "false": False, "0": False}
    if not normalized.isin(accepted).all():
        raise ValueError(f"{name} contains a non-boolean value")
    return normalized.map(accepted).astype(bool)


def audit(source_path: Path, terminal_path: Path, capture_path: Path,
          local_exit_path: Path, schedule_path: Path,
          contract_path: Path) -> dict[str, Any]:
    """Return compact continuity metrics or fail closed on any mismatch."""
    source = pd.read_csv(source_path, keep_default_na=False)
    terminal = pd.read_csv(terminal_path)
    capture = pd.read_csv(capture_path)
    validate_component_particle_state_csv(source_path)
    validate_component_particle_state_csv(local_exit_path)
    local_exit = pd.read_csv(local_exit_path, keep_default_na=False)
    schedule = _load(schedule_path)
    contract = _load(contract_path)
    terminal_required = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
        "lineage_age_us", "particle_age_us", "last_component_elapsed_time_us",
        "mass_amu", "charge_state", "vx_m_s", "vy_m_s", "vz_m_s",
        "event", "status", "first_forward_oatof_entry", "local_accelerator_exit",
    }
    _require_finite_columns(
        terminal,
        terminal_required,
        terminal_required
        - {
            "frame_id",
            "clock_epoch_id",
            "event",
            "status",
            "first_forward_oatof_entry",
            "local_accelerator_exit",
        },
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
        capture_required
        - {
            "frame_id",
            "clock_epoch_id",
            "inside_oatof_ideal_reference_volume",
            "active_at_pulse",
        },
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
    expected_frame = contract["identity_contract"]["frame_id"]
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
    identity_columns = [
        "parent_particle_id",
        "generation",
        "species_id",
        "particle_weight",
        "lineage_birth_time_us",
        "particle_birth_time_us",
        "phase_reference_id",
        "mass_amu",
        "charge_state",
    ]
    local_identity = local_exit.merge(
        source[["particle_id", *identity_columns]],
        on="particle_id",
        suffixes=("_out", "_in"),
        validate="one_to_one",
    )
    exact_identity_columns = {
        "parent_particle_id",
        "generation",
        "species_id",
        "phase_reference_id",
        "charge_state",
    }
    for field in identity_columns:
        output = local_identity[f"{field}_out"]
        source_value = local_identity[f"{field}_in"]
        if field in exact_identity_columns:
            continuous = (output == source_value).all()
        else:
            continuous = np.allclose(output, source_value, rtol=0, atol=0)
        if not continuous:
            raise ValueError(f"S3 canonical local-exit identity field {field} changed")
    adapter = contract["local_exit_adapter"]
    if (
        set(local_exit["source_component_id"]) != {adapter["source_component_id"]}
        or set(local_exit["target_component_id"]) != {adapter["target_component_id"]}
        or set(local_exit["state_event"]) != {adapter["state_event"]}
    ):
        raise ValueError("S3 canonical local-exit event semantics differ from the contract")
    terminal_event = terminal["event"].eq(adapter["terminal_event"])
    terminal_status = terminal["status"].eq(adapter["terminal_status"])
    terminal_flag = _boolean_series(
        terminal["local_accelerator_exit"], "S3 terminal local-exit flag"
    )
    entry_flag = _boolean_series(
        terminal["first_forward_oatof_entry"], "S3 terminal oaTOF-entry flag"
    )
    capture_active = _boolean_series(
        capture["active_at_pulse"], "S3 capture active-at-pulse flag"
    )
    capture_inside = _boolean_series(
        capture["inside_oatof_ideal_reference_volume"],
        "S3 capture inside-reference-volume flag",
    )
    if not (
        terminal_event.equals(terminal_status)
        and terminal_event.equals(terminal_flag)
    ):
        raise ValueError(
            "S3 terminal event, status and local-exit flag are not equivalent"
        )
    terminal_exit = terminal[terminal_event]
    state_pairs = {
        "instrument_time_us": "instrument_time_us",
        "lineage_age_us": "lineage_age_us",
        "particle_age_us": "particle_age_us",
        "last_component_elapsed_time_us": "last_component_elapsed_time_us",
        "mass_amu": "mass_amu",
        "charge_state": "charge_state",
        "position_x_mm": "x_mm",
        "position_y_mm": "y_mm",
        "position_z_mm": "z_mm",
        "velocity_x_m_s": "vx_m_s",
        "velocity_y_m_s": "vy_m_s",
        "velocity_z_m_s": "vz_m_s",
        "phase_rad": "rf_phase_rad",
    }
    terminal_state = terminal_exit[["particle_id", *state_pairs.values()]].rename(
        columns={terminal_name: canonical_name for canonical_name, terminal_name in state_pairs.items()}
    )
    state_check = local_exit.merge(
        terminal_state,
        on="particle_id",
        suffixes=("_canonical", "_terminal"),
        validate="one_to_one",
    )
    if len(state_check) != len(local_exit):
        raise ValueError("S3 canonical local-exit rows do not match terminal exit rows")
    for canonical_name, terminal_name in state_pairs.items():
        canonical_values = state_check[f"{canonical_name}_canonical"]
        terminal_values = state_check[f"{canonical_name}_terminal"]
        if not np.allclose(canonical_values, terminal_values, rtol=0, atol=0):
            raise ValueError(
                f"S3 canonical local-exit field {canonical_name} differs from terminal census"
            )
    elapsed = merged["last_component_elapsed_time_us"]
    residuals = np.concatenate([
        (merged["instrument_time_us_out"]-merged["instrument_time_us_in"]-elapsed).to_numpy(),
        (merged["lineage_age_us_out"]-merged["lineage_age_us_in"]-elapsed).to_numpy(),
        (merged["particle_age_us_out"]-merged["particle_age_us_in"]-elapsed).to_numpy(),
    ])
    maximum_clock_residual = float(np.max(np.abs(residuals)))
    if maximum_clock_residual > 1e-9:
        raise ValueError("S3 clock continuity residual exceeds tolerance")

    pulse_time = float(schedule["derived_pulse_time_us"])
    if not capture.empty and not np.allclose(capture["instrument_time_us"], pulse_time, rtol=0, atol=1e-9):
        raise ValueError("S3 capture rows do not share the scheduled pulse time")
    if not capture.empty and not capture_active.all():
        raise ValueError("S3 capture table contains an inactive particle")
    if set(terminal_exit["particle_id"]) != set(local_exit["particle_id"]):
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
        "oatof_entry_crossings": int(entry_flag.sum()),
        "active_at_pulse": int(len(capture)),
        "inside_ideal_reference_volume_at_pulse": int(capture_inside.sum()),
        "local_accelerator_exit": int(len(local_exit)),
        "pulse_time_us": pulse_time,
        "pulse_width_us": float(schedule["pulse_width_us"]),
        "maximum_clock_residual_us": maximum_clock_residual,
        "canonical_local_exit_validation_status": "PASS",
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
