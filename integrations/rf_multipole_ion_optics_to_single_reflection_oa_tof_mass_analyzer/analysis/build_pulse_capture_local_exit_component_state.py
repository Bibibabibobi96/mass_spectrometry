"""Build the integration-owned canonical pulse-capture local-exit state."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
    write_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th


TERMINAL_REQUIRED_COLUMNS = {
    "particle_id",
    "event",
    "status",
    "frame_id",
    "clock_epoch_id",
    "instrument_time_us",
    "lineage_age_us",
    "particle_age_us",
    "last_component_elapsed_time_us",
    "mass_amu",
    "charge_state",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "rf_phase_rad",
    "local_accelerator_exit",
}
LOCAL_EXIT_EVENT = "local_accelerator_exit"
LOCAL_EXIT_STATUS = "transmitted"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _integer(value: str, field: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(
            f"pulse-capture terminal {field} is not an integer: {value!r}"
        ) from error
    if str(parsed) != value.strip():
        raise ValueError(
            f"pulse-capture terminal {field} is not canonical: {value!r}"
        )
    return parsed


def _number(value: str, field: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(
            f"pulse-capture terminal {field} is not numeric: {value!r}"
        ) from error
    if not math.isfinite(parsed):
        raise ValueError(f"pulse-capture terminal {field} must be finite")
    return parsed


def _boolean(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"pulse-capture terminal {field} is not boolean: {value!r}")


def build_local_exit_component_state(
    source_path: Path,
    terminal_path: Path,
    pulse_capture_contract_path: Path,
    pre_pulse_contract_path: Path,
    resolved_connection_path: Path,
    output_path: Path,
    validation_path: Path | None = None,
) -> dict[str, Any]:
    """Join source identity to terminal exit states and validate canonical output."""
    source_report = validate_component_particle_state_csv(source_path)
    source_columns, source_rows = _read_rows(source_path)
    if source_columns != csv_columns():
        raise ValueError(
            "pulse-capture source columns changed after common validation"
        )
    terminal_columns, terminal_rows = _read_rows(terminal_path)
    missing = TERMINAL_REQUIRED_COLUMNS - set(terminal_columns)
    if missing:
        raise ValueError(
            "pulse-capture terminal census is missing columns: "
            f"{sorted(missing)}"
        )
    if not terminal_rows:
        raise ValueError(
            "pulse-capture terminal census must contain at least one row"
        )

    pulse_capture = _load(pulse_capture_contract_path)
    pre_pulse = _load(pre_pulse_contract_path)
    resolved_connection = _load(resolved_connection_path)
    if pulse_capture.get("role") != "rf_to_oatof_pulse_capture":
        raise ValueError("pulse-capture contract role is invalid")
    if pre_pulse.get("role") != "rf_to_oatof_pre_pulse_interface_transport":
        raise ValueError("pre-pulse contract role is invalid")
    if resolved_connection.get("role") != "resolved_connection_do_not_edit":
        raise ValueError("resolved connection role is invalid")
    if resolved_connection.get("compatibility", {}).get("status") != "pass":
        raise ValueError("resolved connection compatibility did not pass")
    if source_report["particles"] != int(
        pre_pulse["particle_runtime"]["source_particles"]
    ):
        raise ValueError("pulse-capture source count differs from pre-pulse")
    expected_frame = resolved_connection["transition_aperture"][
        "coordinate_frame_id"
    ]
    expected_epoch = pre_pulse["particle_runtime"]["clock_epoch_id"]
    source_component_id = resolved_connection["integration_id"]
    target_component_id = resolved_connection["selection"][
        "downstream_project_id"
    ]
    if source_report["frame_ids"] != [expected_frame] or source_report[
        "clock_epoch_ids"
    ] != [expected_epoch]:
        raise ValueError(
            "pulse-capture source frame or clock epoch differs from authority"
        )

    source_by_id = {int(row["particle_id"]): row for row in source_rows}
    if len(source_by_id) != len(source_rows):
        raise ValueError("pulse-capture source particle identity is not unique")
    terminal_ids: set[int] = set()
    canonical_rows: list[dict[str, Any]] = []
    for terminal in terminal_rows:
        particle_id = _integer(terminal["particle_id"], "particle_id")
        if particle_id in terminal_ids:
            raise ValueError(
                "pulse-capture terminal census duplicates particle_id "
                f"{particle_id}"
            )
        terminal_ids.add(particle_id)
        source = source_by_id.get(particle_id)
        if source is None:
            raise ValueError(
                "pulse-capture terminal census contains unknown particle_id "
                f"{particle_id}"
            )
        if (
            terminal["frame_id"] != expected_frame
            or terminal["clock_epoch_id"] != expected_epoch
        ):
            raise ValueError(
                "pulse-capture terminal frame or clock epoch differs from authority"
            )
        is_local_exit_event = terminal["event"] == LOCAL_EXIT_EVENT
        is_local_exit_status = terminal["status"] == LOCAL_EXIT_STATUS
        is_local_exit_flag = _boolean(
            terminal["local_accelerator_exit"], "local_accelerator_exit"
        )
        if not (
            is_local_exit_event
            == is_local_exit_status
            == is_local_exit_flag
        ):
            raise ValueError(
                "pulse-capture terminal event, status and local-exit flag "
                "are not equivalent"
            )
        if not is_local_exit_event:
            continue

        mass_amu = _number(terminal["mass_amu"], "mass_amu")
        charge_state = _integer(terminal["charge_state"], "charge_state")
        if mass_amu != float(source["mass_amu"]) or charge_state != int(
            source["charge_state"]
        ):
            raise ValueError(
                "pulse-capture terminal species differs from source identity"
            )
        velocity = tuple(
            _number(terminal[f"v{axis}_m_s"], f"v{axis}_m_s") for axis in "xyz"
        )
        canonical_rows.append(
            {
                "particle_id": particle_id,
                "parent_particle_id": source["parent_particle_id"],
                "generation": source["generation"],
                "species_id": source["species_id"],
                "particle_weight": source["particle_weight"],
                "source_component_id": source_component_id,
                "target_component_id": target_component_id,
                "state_event": LOCAL_EXIT_EVENT,
                "frame_id": terminal["frame_id"],
                "clock_epoch_id": terminal["clock_epoch_id"],
                "instrument_time_us": _number(
                    terminal["instrument_time_us"], "instrument_time_us"
                ),
                "lineage_age_us": _number(
                    terminal["lineage_age_us"], "lineage_age_us"
                ),
                "particle_age_us": _number(
                    terminal["particle_age_us"], "particle_age_us"
                ),
                "last_component_elapsed_time_us": _number(
                    terminal["last_component_elapsed_time_us"],
                    "last_component_elapsed_time_us",
                ),
                "lineage_birth_time_us": source["lineage_birth_time_us"],
                "particle_birth_time_us": source["particle_birth_time_us"],
                "mass_to_charge_Th": mass_to_charge_th(mass_amu, charge_state),
                "mass_amu": mass_amu,
                "charge_state": charge_state,
                **{
                    f"position_{axis}_mm": _number(
                        terminal[f"{axis}_mm"], f"{axis}_mm"
                    )
                    for axis in "xyz"
                },
                **{
                    f"velocity_{axis}_m_s": velocity[index]
                    for index, axis in enumerate("xyz")
                },
                "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity),
                "phase_reference_id": source["phase_reference_id"],
                "phase_rad": _number(terminal["rf_phase_rad"], "rf_phase_rad"),
            }
        )

    if terminal_ids != set(source_by_id):
        raise ValueError(
            "pulse-capture terminal census does not preserve every source particle ID"
        )
    if len(canonical_rows) < int(
        pulse_capture["runtime"]["minimum_local_accelerator_exit"]
    ):
        raise ValueError(
            "pulse-capture local-exit population misses the functional minimum"
        )

    report = write_component_particle_state_csv(output_path, canonical_rows)
    if validation_path is not None:
        validation_path.parent.mkdir(parents=True, exist_ok=True)
        validation_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--pulse-capture-contract", type=Path, required=True)
    parser.add_argument("--pre-pulse-contract", type=Path, required=True)
    parser.add_argument("--resolved-connection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    args = parser.parse_args()
    report = build_local_exit_component_state(
        args.source,
        args.terminal,
        args.pulse_capture_contract,
        args.pre_pulse_contract,
        args.resolved_connection,
        args.output,
        args.validation,
    )
    print(
        "PULSE_CAPTURE_LOCAL_EXIT_COMPONENT_STATE=PASS "
        f"SCHEMA_VERSION={report['schema_version']} PARTICLES={report['particles']}"
    )


if __name__ == "__main__":
    main()
