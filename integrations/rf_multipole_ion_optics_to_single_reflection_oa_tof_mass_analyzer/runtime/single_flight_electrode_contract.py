"""Published electrode-topology registry for the joint single-flight runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256


ROD_ELECTRODE_IDS = tuple(range(1, 9))
ACCELERATOR_RING_COUNT = 5
FRONTEND_ELECTRODES: dict[str, Any] = {
    "multipole_rod_ids": list(ROD_ELECTRODE_IDS),
    "grounded_shield_id": 9,
    "accelerator_repeller_id": 10,
    "accelerator_grid1_id": 11,
    "accelerator_ring_ids": list(range(12, 17)),
    "accelerator_grid2_id": 17,
    "entrance_reference_sleeve_id": 18,
    "entrance_plate_id": 19,
}
THREE_ZONE_FRONTEND_ELECTRODES: dict[str, Any] = {
    **FRONTEND_ELECTRODES,
    # Preserve every published two-zone ID. The additional intermediate
    # electrode receives the only new basis ID.
    "accelerator_intermediate2_id": 20,
}
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
    """Resolve an exact published mapping to a contiguous SIMION PA basis."""
    matches = [
        topology_id
        for topology_id, published in PUBLISHED_ELECTRODE_TOPOLOGIES.items()
        if dict(value) == published
    ]
    if len(matches) != 1:
        raise ValueError("frontend electrodes do not match a published topology")
    basis_ids = _flatten_electrode_ids(value)
    expected = tuple(range(basis_ids[-1] + 1))
    if basis_ids != expected:
        raise ValueError("frontend electrode basis must be contiguous from 0")
    return {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_electrode_topology",
        "topology_id": matches[0],
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


def main() -> int:
    """Resolve one frozen frontend contract for the PowerShell runner."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _write_resolved_topology(args.frontend_contract, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
