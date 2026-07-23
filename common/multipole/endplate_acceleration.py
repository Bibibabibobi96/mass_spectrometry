"""Resolve continuous-rod acceleration produced by an endplate voltage step."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any


MODEL_ID = "multipole.endplate_potential_step.v1"


def resolve_endplate_acceleration(
    contract: dict[str, Any], *, source_kinetic_energy_ev: float, charge_state: int
) -> dict[str, Any]:
    expected = {
        "schema_version", "role", "project_id", "model_id", "rod_common_mode_V",
        "entrance_plate_V", "exit_plate_V", "output_reference_V",
        "functional_acceptance", "claim_limit",
    }
    if set(contract) != expected:
        raise ValueError("endplate acceleration fields differ")
    if contract["schema_version"] != 1 or contract["role"] != "multipole_endplate_acceleration_contract":
        raise ValueError("endplate acceleration schema or role differs")
    if contract["model_id"] != MODEL_ID:
        raise ValueError("unsupported endplate acceleration model")
    voltages = {
        key: float(contract[key])
        for key in ("rod_common_mode_V", "entrance_plate_V", "exit_plate_V", "output_reference_V")
    }
    if not all(math.isfinite(value) for value in voltages.values()):
        raise ValueError("endplate voltages must be finite")
    if voltages["entrance_plate_V"] != voltages["rod_common_mode_V"]:
        raise ValueError("entrance plate and continuous rods must share one input reference")
    if voltages["exit_plate_V"] != voltages["output_reference_V"]:
        raise ValueError("exit plate and output reference must match")
    source_energy = float(source_kinetic_energy_ev)
    if not math.isfinite(source_energy) or source_energy <= 0 or not isinstance(charge_state, int) or charge_state == 0:
        raise ValueError("source energy and charge state are invalid")
    predicted_gain = charge_state * (voltages["entrance_plate_V"] - voltages["output_reference_V"])
    if predicted_gain <= 0:
        raise ValueError("endplate potential step does not accelerate the selected charge sign")
    acceptance = contract["functional_acceptance"]
    if set(acceptance) != {
        "minimum_transmission", "minimum_mean_energy_gain_eV", "maximum_mean_output_energy_error_eV"
    }:
        raise ValueError("functional acceptance fields differ")
    result = copy.deepcopy(contract)
    result["role"] = "multipole_endplate_acceleration_resolved_contract"
    result["derived"] = {
        "charge_state": charge_state,
        "source_kinetic_energy_eV": source_energy,
        "predicted_energy_gain_eV": predicted_gain,
        "predicted_output_energy_eV": source_energy + predicted_gain,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--source-energy-ev", required=True, type=float)
    parser.add_argument("--charge-state", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    resolved = resolve_endplate_acceleration(
        contract, source_kinetic_energy_ev=args.source_energy_ev, charge_state=args.charge_state
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
