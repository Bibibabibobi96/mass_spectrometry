"""Write a fail-closed identity manifest for one derived SIMION Candidate run.

The manifest is intentionally separate from the IOB: SIMION workbenches retain
only file paths, whereas this receipt proves which resolved geometry and PA
family the workbench was allowed to load.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import geometry_receipt
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry import (
    ELECTRODE_IDS,
    resolve_simion_iob_origin,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_manifest_common import (
    record_artifact,
    write_manifest,
)


def build_manifest(contract_path: Path, receipt_path: Path, pa0_path: Path, program_path: Path, fly2_path: Path, iob_path: Path | None) -> dict[str, Any]:
    """Bind a PA family and optional IOB to the frozen resolved geometry."""
    contract = load_contract(contract_path)
    expected_receipt = geometry_receipt(contract)
    supplied_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if supplied_receipt.get("resolved_geometry_sha256") != expected_receipt["resolved_geometry_sha256"]:
        raise CandidateContractError("geometry receipt does not match the supplied Candidate contract")
    if supplied_receipt.get("frame_id") != expected_receipt["frame_id"]:
        raise CandidateContractError("geometry receipt frame differs from the Candidate contract")
    if pa0_path.suffix.lower() != ".pa0":
        raise CandidateContractError("manifest must be rooted at the solved pa0 array")

    pa_master = pa0_path.with_suffix(".pa#")
    physical_ids = sorted({
        electrode_id
        for group in ELECTRODE_IDS.values()
        for electrode_id in (group if isinstance(group, tuple) else (group,))
    })
    resolved_ids = sorted({
        electrode_id for role, values in expected_receipt["electrode_ids"].items()
        if role != "detector" for electrode_id in values
    })
    if physical_ids != resolved_ids:
        raise CandidateContractError("SIMION emitter IDs differ from the resolved physical electrode groups")
    # The numerical detector is an event slab, not a PA electrode.  Basis
    # arrays therefore follow only the physical electrode IDs.
    basis = [pa0_path.with_suffix(f".pa{index}") for index in physical_ids]
    origin = resolve_simion_iob_origin(contract)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "project_id": expected_receipt["project_id"],
        "candidate_status": "prototype",
        "geometry": {
            "resolved_geometry_sha256": expected_receipt["resolved_geometry_sha256"],
            "frame_id": expected_receipt["frame_id"],
            "units": "mm",
        },
        "workbench_instance": {
            "must_load": pa0_path.name,
            "origin_mm": list(origin),
            "rotation_deg": [0.0, 0.0, 0.0],
            "scale": 1.0,
        },
        "artifacts": {
            "pa_master": record_artifact(pa_master, missing_error=CandidateContractError),
            "pa0": record_artifact(pa0_path, missing_error=CandidateContractError),
            "basis_arrays": [record_artifact(path, missing_error=CandidateContractError) for path in basis],
            "program": record_artifact(program_path, missing_error=CandidateContractError),
            "fly2": record_artifact(fly2_path, missing_error=CandidateContractError),
            "iob": record_artifact(iob_path, missing_error=CandidateContractError) if iob_path is not None else None,
        },
        "iob_status": "generated" if iob_path is not None else "not_generated",
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--pa0", required=True, type=Path)
    parser.add_argument("--program", required=True, type=Path)
    parser.add_argument("--fly2", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iob", type=Path)
    arguments = parser.parse_args()
    manifest = build_manifest(
        arguments.contract, arguments.receipt, arguments.pa0,
        arguments.program, arguments.fly2, arguments.iob,
    )
    write_manifest(arguments.output, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
