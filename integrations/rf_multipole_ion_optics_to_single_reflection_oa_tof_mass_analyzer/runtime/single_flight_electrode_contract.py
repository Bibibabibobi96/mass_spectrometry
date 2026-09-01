"""Published electrode-topology registry for the joint single-flight runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256


ROD_ELECTRODE_IDS = tuple(range(1, 9))


def resolve_three_zone_pa_plus_solution_model(
    electrodes: Mapping[str, Any],
    *,
    planes_global_z_mm: Mapping[str, Any],
    ring_z_mm: list[Any],
) -> dict[str, Any]:
    """Derive the exact PA+ projection for a three-zone linear ring stack.

    Physical electrode IDs remain the complete frontend namespace.  The PA+
    solution IDs are a separate, compact namespace: only voltage degrees of
    freedom that are independent under the frozen three-zone voltage law own a
    solution array.  Each ring is represented by the two enclosing endpoint
    modes with coefficients that sum to one.
    """
    topology = resolve_frontend_electrode_topology(electrodes)
    if topology["topology_id"] not in {
        "three_zone_frontend_v1", "three_zone_frontend_contract_derived_v1"
    }:
        raise ValueError("PA+ solution model requires a three-zone frontend")
    required_planes = {"repeller", "intermediate1", "intermediate2", "exit"}
    if set(planes_global_z_mm) != required_planes:
        raise ValueError("PA+ solution model requires exactly four accelerator planes")
    planes = {name: float(planes_global_z_mm[name]) for name in required_planes}
    if not all(value == value and abs(value) < float("inf") for value in planes.values()) or not (
        planes["repeller"] < planes["intermediate1"] < planes["intermediate2"] < planes["exit"]
    ):
        raise ValueError("PA+ solution model planes are invalid")
    ring_ids = [int(value) for value in electrodes["accelerator_ring_ids"]]
    if len(ring_z_mm) != len(ring_ids):
        raise ValueError("PA+ solution model ring positions do not match electrode IDs")

    mode_specs: list[tuple[str, int]] = [
        *( (f"rod_{electrode_id}", electrode_id) for electrode_id in ROD_ELECTRODE_IDS ),
        ("repeller", int(electrodes["accelerator_repeller_id"])),
        ("grid1", int(electrodes["accelerator_grid1_id"])),
        ("intermediate2", int(electrodes["accelerator_intermediate2_id"])),
        ("grid2", int(electrodes["accelerator_grid2_id"])),
        ("entrance_reference_sleeve", int(electrodes["entrance_reference_sleeve_id"])),
        ("entrance_plate", int(electrodes["entrance_plate_id"])),
    ]
    modes = [
        {
            "mode_id": 36 + index,
            "name": name,
            "source_physical_electrode_id": electrode_id,
            "physical_electrode_coefficients": {str(electrode_id): 1.0},
        }
        for index, (name, electrode_id) in enumerate(mode_specs)
    ]
    by_name = {mode["name"]: mode for mode in modes}
    for ring_id, raw_z in zip(ring_ids, ring_z_mm):
        z = float(raw_z)
        if not (z == z and abs(z) < float("inf")):
            raise ValueError("PA+ solution model ring position is invalid")
        if planes["intermediate1"] < z < planes["intermediate2"]:
            left, right = "grid1", "intermediate2"
            z0, z1 = planes["intermediate1"], planes["intermediate2"]
        elif planes["intermediate2"] < z < planes["exit"]:
            left, right = "intermediate2", "grid2"
            z0, z1 = planes["intermediate2"], planes["exit"]
        else:
            raise ValueError("PA+ solution model ring is outside its three-zone interval")
        right_weight = (z - z0) / (z1 - z0)
        left_weight = 1.0 - right_weight
        by_name[left]["physical_electrode_coefficients"][str(ring_id)] = left_weight
        by_name[right]["physical_electrode_coefficients"][str(ring_id)] = right_weight
    return {
        "schema_version": 1,
        "model_id": "three_zone_linear_ring_pa_plus_v1",
        # This is deliberately part of the frozen model, rather than an
        # incidental implementation detail.  The existing three-zone Program
        # computes every ring from these four plane voltages; PA+ removes only
        # those already-derived degrees of freedom.  A future per-ring tuning
        # study must select a different model (and therefore a different PA
        # cache identity), not silently reuse this one.
        "voltage_control_policy": {
            "policy_id": "three_zone_linear_ring_interpolation_v1",
            "independent_accelerator_electrode_ids": [
                int(electrodes["accelerator_repeller_id"]),
                int(electrodes["accelerator_grid1_id"]),
                int(electrodes["accelerator_intermediate2_id"]),
                int(electrodes["accelerator_grid2_id"]),
            ],
            "derived_accelerator_ring_ids": ring_ids,
            "per_ring_independent_adjustment_supported": False,
        },
        "mode_ids": [mode["mode_id"] for mode in modes],
        "mode_count": len(modes),
        "modes": modes,
        "grounded_physical_electrode_ids": [int(electrodes["grounded_shield_id"])],
    }


def render_pa_plus_solution_model(model: Mapping[str, Any]) -> str:
    """Render the official SIMION PA+ electrode-to-solution projection."""
    if model.get("model_id") != "three_zone_linear_ring_pa_plus_v1":
        raise ValueError("unsupported PA+ solution model")
    modes = model.get("modes")
    mode_ids = model.get("mode_ids")
    if not isinstance(modes, list) or not isinstance(mode_ids, list) or len(modes) != 14:
        raise ValueError("PA+ solution model modes are invalid")
    lines = ["potential_array {", "  scalable_electrodes = {"]
    observed_mode_ids: list[int] = []
    for mode in modes:
        if not isinstance(mode, Mapping):
            raise ValueError("PA+ solution mode is invalid")
        mode_id = int(mode.get("mode_id", -1))
        coefficients = mode.get("physical_electrode_coefficients")
        if not isinstance(coefficients, Mapping) or not coefficients:
            raise ValueError("PA+ solution coefficients are invalid")
        terms = ", ".join(
            f"[{int(electrode_id)}]={format(float(weight), '.17g')}"
            for electrode_id, weight in sorted(coefficients.items(), key=lambda item: int(item[0]))
        )
        lines.append(f"    [{mode_id}] = {{{terms}}},")
        observed_mode_ids.append(mode_id)
    if observed_mode_ids != [int(value) for value in mode_ids]:
        raise ValueError("PA+ solution mode order is invalid")
    lines.extend(["  }", "}", ""])
    return "\n".join(lines)
def frontend_electrodes(*, ring_count: int, three_zone: bool) -> dict[str, Any]:
    """Derive the contiguous PA electrode namespace from the ring contract."""
    if isinstance(ring_count, bool) or ring_count < 1:
        raise ValueError("accelerator ring count must be a positive integer")
    first_ring_id = 12
    grid2_id = first_ring_id + ring_count
    result: dict[str, Any] = {
        "multipole_rod_ids": list(ROD_ELECTRODE_IDS),
        "grounded_shield_id": 9,
        "accelerator_repeller_id": 10,
        "accelerator_grid1_id": 11,
        "accelerator_ring_ids": list(range(first_ring_id, grid2_id)),
        "accelerator_grid2_id": grid2_id,
        "entrance_reference_sleeve_id": grid2_id + 1,
        "entrance_plate_id": grid2_id + 2,
    }
    if three_zone:
        result["accelerator_intermediate2_id"] = grid2_id + 3
    return result


# Published five-ring mappings remain readable for evidence and tests.  New
# layouts obtain their namespace exclusively through ``frontend_electrodes``.
ACCELERATOR_RING_COUNT = 5
FRONTEND_ELECTRODES = frontend_electrodes(ring_count=ACCELERATOR_RING_COUNT, three_zone=False)
THREE_ZONE_FRONTEND_ELECTRODES = frontend_electrodes(ring_count=ACCELERATOR_RING_COUNT, three_zone=True)
PUBLISHED_ELECTRODE_TOPOLOGIES: dict[str, dict[str, Any]] = {
    "two_zone_frontend_v1": FRONTEND_ELECTRODES,
    "three_zone_frontend_v1": THREE_ZONE_FRONTEND_ELECTRODES,
}
MAXIMUM_ELECTRODE_ID = 19
BASIS_ELECTRODE_IDS = tuple(range(MAXIMUM_ELECTRODE_ID + 1))


def _flatten_electrode_ids(value: Mapping[str, Any]) -> tuple[int, ...]:
    flattened: list[int] = [0]
    for item in value.values():
        if isinstance(item, list):
            flattened.extend(int(electrode_id) for electrode_id in item)
        elif isinstance(item, int) and not isinstance(item, bool):
            flattened.append(item)
        else:
            raise ValueError("frontend electrode IDs must be integers or integer lists")
    if len(flattened) != len(set(flattened)):
        raise ValueError("frontend electrode IDs must not contain duplicates")
    return tuple(sorted(flattened))


def resolve_frontend_electrode_topology(value: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a contract-derived contiguous SIMION PA basis."""
    electrodes = dict(value)
    three_zone = "accelerator_intermediate2_id" in electrodes
    ring_ids = electrodes.get("accelerator_ring_ids")
    if not isinstance(ring_ids, list) or not ring_ids:
        raise ValueError("frontend electrode topology lacks accelerator rings")
    expected = frontend_electrodes(ring_count=len(ring_ids), three_zone=three_zone)
    if electrodes != expected:
        raise ValueError("frontend electrodes do not match the derived topology")
    matches = [
        topology_id
        for topology_id, published in PUBLISHED_ELECTRODE_TOPOLOGIES.items()
        if electrodes == published
    ]
    topology_id = (
        matches[0] if len(matches) == 1 else
        ("three_zone_frontend_contract_derived_v1" if three_zone else
         "two_zone_frontend_contract_derived_v1")
    )
    basis_ids = _flatten_electrode_ids(electrodes)
    expected_basis_ids = tuple(range(basis_ids[-1] + 1))
    if basis_ids != expected_basis_ids:
        raise ValueError("frontend electrode basis must be contiguous from 0")
    return {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_electrode_topology",
        "topology_id": topology_id,
        "basis_electrode_ids": list(basis_ids),
        "basis_count": len(basis_ids),
        "maximum_electrode_id": basis_ids[-1],
    }


def require_published_frontend_electrodes(value: Mapping[str, Any]) -> None:
    """Fail closed unless a frontend uses an exact published Program PA basis."""
    resolve_frontend_electrode_topology(value)


def _write_resolved_topology(frontend_contract: Path, output: Path) -> None:
    frontend = json.loads(frontend_contract.read_text(encoding="utf-8"))
    if frontend.get("role") != "rf_oatof_simion_single_flight_frontend_contract":
        raise ValueError("single-flight electrode topology requires a frontend contract")
    resolved = resolve_frontend_electrode_topology(frontend.get("electrodes", {}))
    resolved["frontend_contract_sha256"] = file_sha256(frontend_contract)
    output.write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_pa_plus(contract: Path, output: Path) -> None:
    document = json.loads(contract.read_text(encoding="utf-8"))
    model = document.get("pa_plus_solution_model", document)
    if not isinstance(model, dict):
        raise ValueError("PA+ solution model contract is invalid")
    output.write_text(render_pa_plus_solution_model(model), encoding="utf-8", newline="\n")


def main() -> int:
    """Resolve one frozen frontend contract for the PowerShell runner."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pa-plus-contract", type=Path)
    parser.add_argument("--pa-plus-output", type=Path)
    args = parser.parse_args()
    if (args.pa_plus_contract is None) != (args.pa_plus_output is None):
        raise ValueError("PA+ contract and output must be provided together")
    if args.pa_plus_contract is not None:
        if args.frontend_contract is not None or args.output is not None:
            raise ValueError("PA+ rendering does not accept frontend topology arguments")
        _write_pa_plus(args.pa_plus_contract, args.pa_plus_output)
    else:
        if args.frontend_contract is None or args.output is None:
            raise ValueError("frontend contract and output are required")
        _write_resolved_topology(args.frontend_contract, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
