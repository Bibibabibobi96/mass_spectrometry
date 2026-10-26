"""Assemble retained IP metal and canonical OA metal in one real PA domain."""
from __future__ import annotations

import copy
import math
from typing import Any

from common.contracts.rigid_transform import RigidTransform
from common.simion.gem_primitives import format_number
from integrations.runtime.single_flight_frontend import (
    _canonical_grid, finalize_frontend_geometry, prepare_bare_frontend_geometry,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import render_cooled_buncher_gem_fragment


CONDITIONER_ELECTRODE_IDS = dict(zip(
    ("hp_rf_a", "hp_rf_b", "hp_auxiliary", "entrance_gate", "hp_shield", "end_inner_auxiliary", "exit_gate"),
    range(40, 47), strict=True,
))


def compile_cooled_frontend(guide: dict, connection: dict, component: dict, conditioner: dict,
                           *, cell_mm_xyz: dict[str, float], exit_gap_mm: float,
                           numerical_bounds_mm: dict[str, float] | None = None,
                           source_geometry_cell_mm_xyz: dict[str, float] | None = None) -> tuple[str, dict]:
    """Return unified GEM and native MR geometry with unchanged source/guide pose.

    The OA component's declared pose must already place its side aperture after
    the finite conditioner gate. Fields are solved together, never assembled by
    translating an old independently solved PA. Only the enclosing numerical
    domain and identity change; both provider CSG models remain authoritative.
    """
    if isinstance(exit_gap_mm, bool) or not math.isfinite(exit_gap_mm) or exit_gap_mm <= 0:
        raise ValueError("conditioner exit-to-OA gap must be finite and positive")
    if conditioner.get("role") != "ion_processor_hp_end_buncher_provider":
        raise ValueError("explicit cooled buncher provider required")
    if source_geometry_cell_mm_xyz is not None and numerical_bounds_mm is None:
        raise ValueError("source CSG rendering cells are only valid for an explicit numerical crop")
    # Some provider cutter overhangs are mesh-derived. A mesh diagnostic must
    # retain its parent's exact CSG body rather than silently resize cutters.
    geometry_cells = cell_mm_xyz if source_geometry_cell_mm_xyz is None else source_geometry_cell_mm_xyz
    registration = connection["spatial_registration"]
    body, frontend = prepare_bare_frontend_geometry(guide, registration, component, cell_mm_xyz,
        geometry_cells=geometry_cells, target_solver_frame="mrtof_global_cartesian")
    projected = frontend["accelerator_local_region"]
    port = projected["port"]
    gate = conditioner["geometry"]["exit_face_center_mr_mm"]
    tolerance = 32 * math.ulp(max(1., *(abs(float(v)) for v in [*gate, *port["center_mm"]])))
    if abs(port["flange_min_mm"] - gate[1] - exit_gap_mm) > tolerance or any(
        abs(port["center_mm"][a]-gate[a]) > tolerance for a in (0, 2)
    ):
        raise ValueError("OA side aperture must follow and align with the actual conditioner gate")
    pose = RigidTransform.from_contract(conditioner["native_to_mr"])
    if pose.rotation != ((0., 0., -1.), (1., 0., 0.), (0., -1., 0.)):
        raise ValueError("cooled native CSG requires the certified retained-guide MR pose")
    f = format_number
    body.extend([f"locate({','.join(f(v) for v in pose.translation_mm)}) {{",
                 "  rotate_z(90) { rotate_x(-90) {",
                 render_cooled_buncher_gem_fragment(conditioner), "  } }", "}"])
    prior = frontend["instance_bounds_mm"]
    extra = conditioner["bounds_mr_mm"]
    bounds = {f"{a}_{side}": operation(prior[f"{a}_{side}"], extra[key][i] + sign*cell_mm_xyz[a])
              for i, a in enumerate("xyz")
              for side, key, sign, operation in (("min", "min_mm", -1, min), ("max", "max_mm", 1, max))}
    if numerical_bounds_mm is not None:
        if set(numerical_bounds_mm) != set(bounds):
            raise ValueError("explicit numerical crop requires all six MR bounds")
        for axis in "xyz":
            low, high = (numerical_bounds_mm[f"{axis}_{s}"] for s in ("min", "max"))
            if any(isinstance(v, bool) or not math.isfinite(v) for v in (low, high)) or low >= high:
                raise ValueError("finite ordered numerical crop required")
            if low < bounds[f"{axis}_min"] or high > bounds[f"{axis}_max"]:
                raise ValueError("numerical crop must remain within the assembled domain")
        bounds = dict(numerical_bounds_mm)
    numerical = _canonical_grid(bounds, cell_mm_xyz)
    old_ids = {int(i) for i in projected["operating_voltages_v"]} | set(range(1, 9))
    new_ids = set(conditioner["electrode_ids"].values())
    if old_ids & new_ids:
        raise ValueError("conditioner physical IDs overlap guide or OA IDs")
    frontend.update(numerical, role="rf_oatof_cooled_frontend_geometry", conditioner_contract=copy.deepcopy(conditioner),
                    physical_electrode_ids=sorted(old_ids | new_ids),
                    junction_enclosure=dict(geometry="conditioner_metal_then_vacuum_gap", exit_to_oa_gap_mm=exit_gap_mm,
                                            generated_solids="frozen_conditioner_contract"))
    if numerical_bounds_mm is not None:
        frontend["numerical_crop"] = dict(requested_bounds_mm=dict(numerical_bounds_mm),
            source_geometry_cell_mm_xyz=dict(geometry_cells),
            geometry_policy="identical full provider CSG clipped only by the explicit PA domain",
            qualification="local static mesh diagnostic; not a production carrier")
    nodes = math.prod(numerical["dimensions"].values())
    frontend["field_storage_forecast"] = dict(nodes=nodes, potential_bytes_per_array=8*nodes,
                                               seven_working_potential_bytes=7*8*nodes,
                                               scope="potential payload only; header/raw/scratch/evidence are additional")
    return finalize_frontend_geometry(body, frontend), frontend


def compile_field_plan(frontend: dict[str, Any], guide: dict, drive: dict, *,
                       hp_rf_peak_amplitude_v: float, refine_convergence_v: float) -> dict:
    """Compile seed endpoints and two independent real-field calibration controls."""
    names = set(CONDITIONER_ELECTRODE_IDS)
    for stage in ("capture_voltages_v", "closed_voltages_v", "release_voltages_v"):
        if set(drive[stage]) != names or any(isinstance(v, bool) or not math.isfinite(v) for v in drive[stage].values()):
            raise ValueError("every conditioner stage requires exactly seven finite electrode voltages")
    if not 0 < drive["entrance_close_us"] < drive["release_start_us"]:
        raise ValueError("entrance closure must precede axial release")
    if not math.isfinite(refine_convergence_v) or refine_convergence_v <= 0:
        raise ValueError("positive explicit Refine convergence required")
    ids = frontend["physical_electrode_ids"]
    def endpoint(stage):
        result = {str(i): 0. for i in range(1, max(ids)+1)}
        for rod in guide["rod_array"]["rods"]:
            result[str(rod["physical_electrode_id"])] = guide["drive"]["common_mode_v"] + guide["drive"]["group_dc_v"][rod["electrode_group"]-1]
        result.update({str(CONDITIONER_ELECTRODE_IDS[k]): float(v) for k, v in drive[stage].items()})
        return result
    capture, closed, release = (endpoint(s) for s in ("capture_voltages_v", "closed_voltages_v", "release_voltages_v"))
    zero = {k: 0. for k in capture}
    rf = dict(zero)
    peak = float(guide["drive"]["rf_amplitude_v"])
    if peak <= 0 or hp_rf_peak_amplitude_v <= 0 or not math.isfinite(hp_rf_peak_amplitude_v):
        raise ValueError("positive finite guide/HP RF amplitude required")
    for rod in guide["rod_array"]["rods"]:
        rf[str(rod["physical_electrode_id"])] = 1. if rod["electrode_group"] == 1 else -1.
    rf[str(CONDITIONER_ELECTRODE_IDS["hp_rf_a"])], rf[str(CONDITIONER_ELECTRODE_IDS["hp_rf_b"])] = hp_rf_peak_amplitude_v/peak, -hp_rf_peak_amplitude_v/peak
    pulse = dict(zero)
    pulse.update(frontend["accelerator_local_region"]["operating_voltages_v"])
    inner, common = dict(zero), dict(zero)
    inner[str(CONDITIONER_ELECTRODE_IDS["end_inner_auxiliary"])] = 1.
    for name in ("hp_rf_a", "hp_rf_b", "hp_auxiliary", "hp_shield", "end_inner_auxiliary"):
        common[str(CONDITIONER_ELECTRODE_IDS[name])] = 1.
    points = dict(carrier_off=capture, rf_differential_unit=rf,
                  entry_close_delta={k: closed[k]-capture[k] for k in capture},
                  release_delta={k: release[k]-closed[k] for k in capture}, pulse_delta=pulse,
                  inner_auxiliary_unit=inner, hp_common_unit=common)
    return dict(schema_version=1, role="rf_oatof_cooled_frontend_laplace_endpoints",
                boundary_policy="explicit_zero_dirichlet_far_faces_not_mechanical_metal",
                refine_convergence_v=refine_convergence_v, physical_electrode_ids=ids,
                stage_endpoint_voltages_v=dict(capture=capture, closed=closed, release=release),
                independent_calibration_controls=dict(inner_auxiliary_unit="1V on terminal inner auxiliary only",
                    hp_common_unit="1V on HP RF, corner auxiliary, shield and inner; neither gate"),
                working_points=[dict(kind=k, output_basename=f"cooled__{k}.pa", electrode_voltages_v=v) for k, v in points.items()],
                dynamic_coefficients="carrier + RF(t)*rf_unit + step(close)*entry_delta + step(release)*release_delta + step(OA)*pulse_delta + inner_correction(t)*inner_unit + common_correction(t)*HP_common_unit")
