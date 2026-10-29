"""Project the existing oaTOF geometry into governed PA build requests.

The public PA cache owns identity normalization, transactions and publication.
Only the surface=none accelerator and reflectron have a supported standalone
response path. The two fractional-surface ground components remain fresh,
producer-owned builds; their surface semantics are never changed for reuse.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from common.contracts.file_identity import file_sha256
from common.contracts.recorded_file_removal import write_json_atomic
from common.simion.pa_family_cache import canonical_pa_family_cache_key
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    resolve_physical_geometry,
)


PROJECT = "projects/single_reflection_oa_tof_mass_analyzer"
ROLE = "oatof_simion_component_pa_plan"
COMPONENTS = {
    "accelerator": (
        "accelerator", "accelerator", True,
        "projects/orthogonal_accelerator/simion/build_two_zone_pa.lua",
        "projects/orthogonal_accelerator/simion/two_zone_accelerator.gem",
    ),
    "reflectron": (
        "reflectron", "reflectron", True,
        PROJECT + "/simion/reflectron/build_reflectron_variant.lua",
        PROJECT + "/simion/reflectron/oatof_reflectron_ideal_10_5.gem",
    ),
    "flight_tube": (
        "flight_tube_shield", "flight_tube_ground", False,
        PROJECT + "/simion/workbench/build_flight_tube_variant.lua",
        PROJECT + "/simion/workbench/oatof_flight_tube_ground.gem",
    ),
    "detector": (
        "detector", "detector_ground", False,
        PROJECT + "/simion/workbench/build_detector_variant.lua",
        PROJECT + "/simion/workbench/oatof_detector_ground.gem",
    ),
}


def _shape(value: Any) -> Any:
    """Keep local geometry and electrode numbering, not operating voltages."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()
                if key not in {"voltage_v", "component_electrode_id"}}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    return value


def compile_component_pa_plan(
    contract: dict[str, Any], *, repository_root: Path, simion_exe: Path,
) -> dict[str, Any]:
    """Return the frozen component requests without writing or opening a PA."""
    physical = resolve_physical_geometry(contract)
    repo = repository_root.resolve(strict=True)
    executable = simion_exe.resolve(strict=True)
    mesh = contract["simion_geometry_build"]
    # The existing instrument's instance projection describes this closed,
    # unpadded accelerator domain. Do not invent another dimension authority.
    if any(mesh["accelerator"][name] != 0 for name in (
        "vacuum_margin_mm", "back_domain_margin_mm", "front_domain_margin_mm",
    )):
        raise ValueError("managed oaTOF PA reuse requires its declared unpadded accelerator domain")
    instances = {item["role"]: item for item in contract["derived"]["simion_instances"]}
    if set(instances) != {item[0] for item in COMPONENTS.values()}:
        raise ValueError("component PA plan requires the existing four-instance geometry")
    executable_identity = {"release": "SIMION 2020", "executable_sha256": file_sha256(executable)}
    records = []
    for role, (instance_role, stem, cacheable, builder, gem) in COMPONENTS.items():
        instance = instances[instance_role]
        dimensions = [instance[axis] for axis in ("nx", "ny", "nz")]
        if any(type(value) is not int or value < 1 for value in dimensions):
            raise ValueError(f"{role} has invalid provider grid dimensions")
        if role == "accelerator":
            geometry = deepcopy(physical["accelerator"]["geometry"])
            electrical = physical["accelerator"]["electrical"]["operating_voltages_v"]
            operating_values = [electrical["repeller"], electrical["grid1"],
                                *electrical["rings"], electrical["grid2"], electrical["shield"]]
            count = 4 + contract["rings"]["accelerator_count"]
            cells = [mesh[role]["cell_xy_mm"]] * 2 + [mesh[role]["cell_z_mm"]]
            symmetry = "3dplanar"
        elif role in ("reflectron", "flight_tube"):
            geometry = _shape(physical["simion"][role])
            operating_values = [item["voltage_v"] for item in physical["simion"][role]["electrodes"]]
            count = len(geometry["electrodes"])
            cells = [mesh[role]["cell_axial_mm"], mesh[role]["cell_radial_mm"], mesh[role]["cell_radial_mm"]]
            symmetry = "2dcylindrical"
        else:
            geometry = physical["simion"]["detector_marker"]
            operating_values = [0.0]
            count = 1
            cells = [geometry["cell_xy_mm"]] * 2 + [geometry["cell_z_mm"]]
            symmetry = "3dplanar"
        if type(count) is not int or count < 1 or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0 for value in cells
        ):
            raise ValueError(f"{role} has invalid electrode or mesh metadata")
        source_ids = [builder, gem]
        if role == "reflectron":
            source_ids.append(PROJECT + "/simion/reflectron/refine_single_pa.lua")
        if cacheable:
            source_ids += ["common/simion/export_standalone_pa.lua", "common/simion/standalone_pa_response_set.py"]
        identity = {
            "geometry": {"role": role, "physical_geometry": geometry},
            "gem": {"path": gem, "sha256": file_sha256(repo / gem)},
            "basis_namespace": {"electrode_ids": list(range(1, count + 1))},
            "mesh": {"dimensions": dimensions, "cell_mm": cells, "symmetry_type": symmetry},
            "grid_phase": {"z_mm": mesh[role].get("grid_phase_z_mm", 0)},
            "surface": "none" if cacheable else "fractional",
            "simion_identity": executable_identity,
            "refine_policy": {"builder_default": True, "reflectron_independent_responses": role == "reflectron"},
            "builder_identity": {name: file_sha256(repo / name) for name in source_ids},
        }
        member_bytes = math.prod(dimensions) * 8 + 4096
        # Include native staging, standalone publication plus XOR, private
        # controller/responses, and the two sequential reconstruction copies.
        # Fractional builders already enforce their declared total-family cap.
        if cacheable:
            native = member_bytes * (count + 2)
            publication = member_bytes * (count + 2) + 65536
            runtime = member_bytes * (count + 3)
        else:
            limit = (mesh[role]["max_gib"] * 1024**3 if role == "flight_tube"
                     else mesh[role]["max_mib"] * 1024**2)
            native, publication, runtime = 0, 0, math.ceil(limit)
        filenames = sorted((f"{stem}.pa#", f"{stem}.standalone_responses.json",
                            *(f"{stem}.response{index}.pa" for index in range(1, count + 1)))) if cacheable else []
        records.append({
            "role": role, "stem": stem, "cacheable": cacheable,
            "identity": identity, "cache_key": canonical_pa_family_cache_key(identity) if cacheable else None,
            "expected_files": filenames, "response_ids": list(range(1, count + 1)),
            "operating_voltages_v": {str(index): value for index, value in enumerate(operating_values, 1)},
            "grid": {"dimensions": dimensions, "cell_mm": cells, "symmetry_type": symmetry},
            "bytes": {"native_staging": native, "publication_and_parity": publication, "private_runtime": runtime},
        })
    plan = {"schema_version": 1, "role": ROLE, "components": records,
            "evidence_allowance_bytes": 64 * 1024**2}
    plan["committed_new_bytes"] = sum_component_commitments([plan])
    return plan


def sum_component_commitments(plans: Iterable[Mapping[str, Any]]) -> int:
    """Reserve shared cached construction once, every private runtime separately."""
    total, seen = 0, set()
    for plan in plans:
        if plan.get("role") != ROLE or plan.get("schema_version") != 1:
            raise ValueError("component capacity plan role differs")
        total += int(plan["evidence_allowance_bytes"])
        for item in plan["components"]:
            sizes = item["bytes"]
            if any(type(value) is not int or value < 0 for value in sizes.values()):
                raise ValueError("component capacity plan contains invalid bytes")
            total += sizes["private_runtime"]
            if item["cacheable"] and item["cache_key"] not in seen:
                total += sizes["native_staging"] + sizes["publication_and_parity"]
                seen.add(item["cache_key"])
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--simion-exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    if args.output.exists():
        raise ValueError("component PA plan output already exists")
    write_json_atomic(args.output, compile_component_pa_plan(
        contract, repository_root=args.repository_root, simion_exe=args.simion_exe,
    ))


if __name__ == "__main__":
    main()
