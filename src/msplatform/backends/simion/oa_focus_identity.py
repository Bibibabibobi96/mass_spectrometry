"""Pure scientific identity for the existing closed two-zone focus PA."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
from msplatform.io.file_identity import file_sha256


def expected_files(plan: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the native family and detached runtime responses for this profile."""
    electrode_count = int(plan["electrode_count"])
    if electrode_count != 4 + int(plan["layout"]["ring_count"]):
        raise ValueError("component focus electrode count differs from its profile layout")
    return tuple(sorted((
        "orthogonal_accelerator_focus.pa#",
        *(f"orthogonal_accelerator_focus.pa{index}" for index in range(electrode_count + 1)),
        *(f"orthogonal_accelerator_focus.response{index}.pa" for index in range(1, electrode_count + 1)),
        "orthogonal_accelerator_focus.standalone_responses.json",
    )))


def identity(plan: Mapping[str, Any], builder: Path, simion_executable: Path) -> dict[str, Any]:
    if plan.get("role") != "orthogonal_accelerator_component_focus_pa_plan":
        raise ValueError("component focus PA plan identity is invalid")
    domain = plan.get("numerical_domain")
    if not isinstance(domain, Mapping):
        raise ValueError("component focus PA numerical domain is invalid")
    electrode_count = int(plan["electrode_count"])
    expected_files(plan)
    return {
        "geometry": {"role": "orthogonal_accelerator_closed_two_zone_focus_controller", "layout": plan["layout"]},
        "gem": {"sha256": __import__("hashlib").sha256(str(plan["gem"]).encode("utf-8")).hexdigest()},
        "basis_namespace": {
            "native_solution_ids": list(range(electrode_count + 1)),
            "electrode_ids": list(range(1, electrode_count + 1)),
            "runtime": "manifest_bound_standalone_responses__private_native_fast_adjust_family",
        },
        "mesh": {"mm_per_gu": domain["mesh_mm_per_gu"]},
        "grid_phase": {
            "pa_span_mm": domain["span_mm"],
            "stored_span_mm": domain["stored_span_mm"],
            "mirror_axes": domain["mirror_axes"],
            "iob_origin_mm": domain["iob_origin_mm"],
        },
        "surface": "none",
        "simion_identity": {"release": "SIMION 2020", "executable_sha256": file_sha256(simion_executable)},
        "refine_policy": {
            "operation": f"one_native_fast_adjust_family_solutions_0_through_{electrode_count}",
            "response_bank": "new_pa_object_standalone_responses_1_through_electrode_count",
        },
        "builder_identity": {"response_set_contract_sha256": file_sha256(Path(__file__).resolve().parent / "standalone_pa_response_set.py"), "path": "src/msplatform/backends/simion/resources/build_component_focus_pa.lua", "sha256": file_sha256(builder)},
    }
