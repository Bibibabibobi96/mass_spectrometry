"""Production native static provider: rebuild a parent and ordered local fields.

No solver is launched here. The PowerShell entry owns public capacity, execution
and sealing; this module validates requests and emits GEM/binding metadata.
Lengths are mm and electrode potentials are V. Published PA identities are
inherited by sealed record/size, never copied or rehashed on reuse.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import struct
from pathlib import Path
from typing import Any

from common.contracts.verify_run_manifest import verify_record
from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER, PaHeader
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import (
    PS_GROUPS,
    candidate_authority,
    derive_candidate_authority,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import (
    _analyzer_geometry_lines,
    build_static_c0_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import (
    _grid_shape,
    validate_generation_grid_pitch,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import (
    _native_active_box,
    _record,
    _load_operator_ancestry,
    load_binding,
    load_native_response_basis,
    native_response_operator,
    native_numerics_match,
    resolve_native_refine_numerics,
    validate_native_consumer_view,
    validate_ip_fine_response_reuse,
)


def _operator_ancestry_inputs(inputs: dict[str, str], bindings: list[dict]) -> list[dict]:
    """Freeze verified historical dependencies without treating them as field inputs."""
    projections = {}
    for binding in bindings:
        for projection in binding.get("operator_ancestry_projections", []):
            key = projection["target_manifest"]["path"]
            if key in projections and projections[key] != projection:
                # Separate recursive loads may consume different small records.
                previous = projections[key]
                if any(previous[k] != projection[k] for k in projection if k != "consumed_records"):
                    raise ValueError("operator ancestry retirement identity changed during compilation")
                if any(path in previous["consumed_records"] and previous["consumed_records"][path] != record
                       for path, record in projection["consumed_records"].items()):
                    raise ValueError("operator ancestry consumed record changed during compilation")
                previous["consumed_records"].update(projection["consumed_records"])
            else:
                projections[key] = copy.deepcopy(projection)
    for index, projection in enumerate(projections.values()):
        records = [projection["target_manifest"], projection["retirement_receipt"],
                   *projection["consumed_records"].values()]
        for record_index, record in enumerate(records):
            verify_record("operator_ancestry_input", record)
            inputs[f"operator_ancestry_{index}_{record_index}"] = record["path"]
    return list(projections.values())

ROLE = "mrtof_native_static_field_provider_request"
PROJECT = "parallel_mirror_dual_stripe_mr_tof"
# Installed official examples/matlab/simion_pa_save.m: NOTREFINABLE = 2^28.
COLLISION_NOTREFINABLE_FLAG = 1 << 28
# Official SIMION electrode-solution normalization; not an actual workpoint.
RESPONSE_NORMALIZATION_V = 10000.0
TE1_AXIS = "te1"


def read(path: Path) -> dict[str, Any]:
    """Read one small UTF-8 machine authority."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


IP_PROVIDER = "dual_pressure_rectilinear_ion_processor"


def _ip_metadata(source: dict[str, Any]) -> dict[str, Any]:
    """Preserve explicit component identity through response and composition."""
    return ({key: copy.deepcopy(source[key]) for key in
             ("accelerator_provider", "assembly_scope", "replacement_assembly")}
            if source.get("accelerator_provider") == IP_PROVIDER else {})


def _ip_source_layout(source: dict[str, Any]) -> dict[str, Any]:
    """Use sealed actual IP operator pitches, never the older nominal OA layout."""
    levels = [source, *source["refinement_windows"]]
    targets = [{"pitch_mm": copy.deepcopy(level["grid"]["pitch_mm"])} for level in levels]
    return dict(parent=targets[0], windows=targets[1:])


def _static_gem(geometry: dict, authority: dict, grid: dict, *, boundary_mode: str):
    if authority.get("assembly", {}).get("accelerator_provider") != IP_PROVIDER:
        return build_static_c0_gem(geometry, authority, grid, boundary_mode=boundary_mode)
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import _gem
    rows = authority["component_voltages_v"]
    ip = [row["voltage_v"] for row in rows if row["component_namespace"] == "ion_processor"]
    detector = [row["voltage_v"] for row in rows if row["component_namespace"] == "detector"]
    if len(ip) != 15 or len(detector) != 1:
        raise ValueError("IP static emission requires all provider15 and detector voltages")
    return (_gem(geometry, geometry["ion_processor_electrodes"], ip,
                 authority["analyzer_electrode_voltages_v"], detector[0], dict(grid, boundary_mode=boundary_mode)),
            dict(accelerator_provider=IP_PROVIDER, boundary_mode=boundary_mode))


def _pure_axis_authority(source: dict[str, Any], axis: str) -> dict[str, Any]:
    """Keep frozen bodies/assembly while prescribing one normalized excitation."""
    result = copy.deepcopy(source)
    result["analyzer_electrode_voltages_v"] = [0.0] * 20
    for component in result["component_voltages_v"]:
        component["voltage_v"] = 0.0
    for physical_id in PS_GROUPS[axis]:
        result["analyzer_electrode_voltages_v"][physical_id - 1] = RESPONSE_NORMALIZATION_V
    return result


def _te1_excitation(basis: dict[str, Any]) -> list[float]:
    """Return the five physical mirror voltages of one normalized TE1 direction."""
    direction = basis.get("direction_v_per_coordinate")
    if (
        basis.get("axis") != TE1_AXIS
        or basis.get("normalization_v") != RESPONSE_NORMALIZATION_V
        or not isinstance(direction, list)
        or len(direction) != 4
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in direction)
        or max(abs(v) for v in direction) == 0
    ):
        raise ValueError("TE1 response requires a finite nonzero direction and 10000 V normalization")
    magnitude = max(abs(v) for v in direction)
    return [0.0, *[RESPONSE_NORMALIZATION_V * (v / magnitude) for v in direction]]


def _te1_basis_metadata(reference_path: Path) -> dict[str, Any]:
    """Freeze the existing TE1 reference direction; this is not a working voltage."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic import _te1_reference

    _, coordinate, _, delta = _te1_reference(reference_path)
    basis = {
        "axis": TE1_AXIS,
        "normalization_v": RESPONSE_NORMALIZATION_V,
        "direction_v_per_coordinate": [v / coordinate for v in delta],
    }
    excitation = _te1_excitation(basis)
    basis.update(
        physical_electrode_ids=[i + 1 for i, v in enumerate(excitation * 2) if v != 0],
        excitation_semantics="pure normalized TE1 direction; all other analyzer/component potentials zero",
        combination_semantics="base PA plus physical mirror increment / normalized direction times this PA",
    )
    return basis


def _response_authority(source: dict[str, Any], basis: dict[str, Any]) -> dict[str, Any]:
    """Prescribe only the declared pure P/S axis or paired TE1 mirror direction."""
    if basis.get("axis") != TE1_AXIS:
        return _pure_axis_authority(source, basis["axis"])
    excitation = _te1_excitation(basis)
    if basis.get("physical_electrode_ids") != [i + 1 for i, v in enumerate(excitation * 2) if v != 0]:
        raise ValueError("TE1 response physical electrode grouping differs")
    result = copy.deepcopy(source)
    result["analyzer_electrode_voltages_v"] = excitation * 2 + [0.0] * 10
    for component in result["component_voltages_v"]:
        component["voltage_v"] = 0.0
    return result


def compile_response_coefficients(
    base_authority: dict[str, Any],
    target_voltages_v: dict[str, float],
    available_axes: list[str],
    *,
    mirror_voltages_v: list[float] | None = None,
    te1_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan pure-basis increments; no field I/O, solve, or trajectory prediction."""
    if (
        set(target_voltages_v) != set(PS_GROUPS)
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in target_voltages_v.values()
        )
        or len(available_axes) != len(set(available_axes))
        or not set(available_axes) <= set(PS_GROUPS) | {TE1_AXIS}
        or (TE1_AXIS in available_axes) != (te1_basis is not None)
    ):
        raise ValueError("response coefficients require finite complete P/S targets and unique available axes")
    values = base_authority["analyzer_electrode_voltages_v"]
    coefficients = {}
    for axis, ids in PS_GROUPS.items():
        anchor = values[ids[0] - 1]
        if any(values[i - 1] != anchor for i in ids):
            raise ValueError("baseline P/S group does not have one voltage")
        delta = target_voltages_v[axis] - anchor
        if axis not in available_axes and delta != 0:
            raise ValueError("target changes an axis without a pure response")
        if axis in available_axes:
            coefficient = delta / RESPONSE_NORMALIZATION_V
            if not math.isfinite(coefficient):
                raise ValueError("response coefficient is nonfinite")
            coefficients[axis] = coefficient
    target = candidate_authority(base_authority, target_voltages_v, mirror_voltages_v=mirror_voltages_v)
    if te1_basis is not None:
        excitation = _te1_excitation(te1_basis)
        if values[:10] != values[:5] * 2:
            raise ValueError("TE1 baseline requires equal paired mirror voltages")
        delta = [b - a for a, b in zip(values[:5], target["analyzer_electrode_voltages_v"][:5], strict=True)]
        index = max(range(5), key=lambda i: abs(excitation[i]))
        coefficient = delta[index] / excitation[index]
        # Same absolute voltage reconstruction tolerance as mirror authority;
        # compare actual vectors, never apply an absolute coordinate to an offset.
        if not math.isfinite(coefficient) or any(
            not math.isclose(change, coefficient * voltage, rel_tol=0.0, abs_tol=1e-9)
            for change, voltage in zip(delta, excitation, strict=True)
        ):
            raise ValueError("target mirror increment is incompatible with the frozen TE1 direction")
        coefficients[TE1_AXIS] = coefficient
    return {"target_authority": target, "coefficients": coefficients, "normalization_v": RESPONSE_NORMALIZATION_V}


def _compile_composition(
    request: dict[str, Any],
    source: dict[str, Any],
    authority: dict[str, Any],
    contract_path: Path,
    numerics: dict[str, Any],
) -> dict[str, Any] | None:
    """Compose from one sealed anchor; undeclared mirror directions need Refine."""
    paths = request["response_basis_paths"]
    if (
        not isinstance(paths, dict)
        or not paths
        or not set(paths) <= set(PS_GROUPS) | {TE1_AXIS}
        or any(not isinstance(value, str) or not value for value in paths.values())
    ):
        raise ValueError("response_basis_paths requires named pure axis descriptors")
    if not native_numerics_match(source, contract_path):
        raise ValueError("composition stopping differs from its current source operator")
    for path in paths.values():
        load_native_response_basis(Path(path), source)
    base_path = (
        source["materialization"]["base_binding"] if "materialization" in source else request["source_binding_path"]
    )
    base = load_binding(Path(base_path))
    view = validate_native_consumer_view(
        read(contract_path)["simion"]["numerical_profiles"]["native_static_field"].get("consumer_view")
    )
    if view != base.get("consumer_view") or view != source.get("consumer_view"):
        raise ValueError("composition consumer view differs from frozen source")
    layout = (_ip_source_layout(base) if _ip_metadata(base) else
              read(contract_path)["simion"]["numerical_profiles"]["native_static_field"].get("target_layout"))
    if (
        not isinstance(layout, dict)
        or not isinstance(layout.get("windows"), list)
        or len(layout["windows"]) != len(base["refinement_windows"])
    ):
        raise ValueError("composition requires its bank-compatible target layout")
    for level, target in zip(
        [base, *base["refinement_windows"]], [layout.get("parent"), *layout["windows"]], strict=True
    ):
        original = read(Path(level["numerical_plan_path"]))
        if (
            not isinstance(target, dict)
            or target.get("pitch_mm") != level["grid"]["pitch_mm"]
            or not view
            and (
                ("stored_xmax_mm" in target) != (original.get("crop") is not None)
                or "stored_xmax_mm" in target
                and target["stored_xmax_mm"] != original["box_mm"][3]
            )
        ):
            raise ValueError("composition target layout differs from its immutable bank operator")
    if native_response_operator(source, base["authority"]) != native_response_operator(base, base["authority"]):
        raise ValueError("bank anchor differs from current native operator")
    bases = {axis: load_native_response_basis(Path(path), base) for axis, path in paths.items()}
    if any(value["response_basis"]["axis"] != axis for axis, value in bases.items()):
        raise ValueError("response axis differs from response_basis_paths key")
    coefficients = compile_response_coefficients(
        base["authority"],
        request["candidate_voltages_v"],
        list(bases),
        mirror_voltages_v=(authority["analyzer_electrode_voltages_v"][:5] if TE1_AXIS in bases else None),
        te1_basis=(bases[TE1_AXIS]["response_basis"] if TE1_AXIS in bases else None),
    )
    if coefficients["target_authority"] != authority:
        mirror_target = candidate_authority(
            coefficients["target_authority"],
            request["candidate_voltages_v"],
            mirror_voltages_v=authority["analyzer_electrode_voltages_v"][:5],
        )
        if mirror_target != authority:
            raise ValueError("composition cannot change fixed components/assembly")
        # Keep the declared bank: the normal direct path builds only the new
        # fixed-mirror offset. Subsequent P/S targets compose from that offset.
        return None
    labels = (
        ["window"]
        if len(base["refinement_windows"]) == 1
        else [f"window_{i}" for i in range(len(base["refinement_windows"]))]
    )
    sources = dict(zip(["parent", *labels], [base, *base["refinement_windows"]]))
    identities = {
        (Path(x["manifest"]).resolve(), Path(x["sources"]["scalar_pa"]).resolve()): label
        for label, x in sources.items()
    }
    levels, protected = {}, [base_path]
    inputs = {
        "source_binding": request["source_binding_path"],
        "combination_base_binding": base_path,
        "numerical_contract": str(contract_path),
    }
    for axis, path in paths.items():
        inputs["response_" + axis] = path
    ancestry = _operator_ancestry_inputs(inputs, [source, base, *bases.values()])
    for label, level in sources.items():
        original = read(Path(level["numerical_plan_path"]))
        parent = (
            None
            if label == "parent"
            else identities[(Path(original["parent_manifest"]).resolve(), Path(original["parent_pa"]).resolve())]
        )
        spec = copy.deepcopy(original)
        for key in (
            "crop",
            "full_solve_plan_path",
            "consumer_grid",
            "gem",
            "response_basis",
            "consumer_view_source",
            "consumer_view_receipt_path",
        ):
            spec.pop(key, None)
        grid = level["grid"]
        pa_bytes = math.prod(grid["dimensions"]) * 8 + 56
        if level["sources"]["surface"] is None:
            raise ValueError("native composition currently requires explicit fractional sidecar provenance")
        surface_bytes = level["records"]["surface"]["bytes"]
        commitment = math.ceil(pa_bytes * 1.05 + surface_bytes * 1.1) + 16 * 1024**2
        responses = []
        index = (["parent", *labels]).index(label)
        for axis, basis in bases.items():
            response = [basis, *basis["refinement_windows"]][index]
            responses.append(
                dict(axis=axis, path=response["sources"]["scalar_pa"], coefficient=coefficients["coefficients"][axis])
            )
        spec.update(
            parent_label=parent,
            **numerics,
            numerical_contract_path=str(contract_path),
            refine_performed=False,
            committed_new_bytes=commitment,
            final_retained_estimate_bytes=commitment,
            source_solve_plan_path=level["numerical_plan_path"],
            source_solve_manifest=level["manifest"],
            composition=dict(base_pa=level["sources"]["scalar_pa"], responses=responses),
        )
        if label != "parent":
            spec.update(name=level["name"], active_box_mm=level["active_box_mm"])
        levels[label] = spec
        inputs[label + "_source_plan"] = level["numerical_plan_path"]
        protected.extend([level["manifest"], *[p for p in level["sources"].values() if p]])
    for basis in bases.values():
        protected.append(basis["descriptor_path"])
        for level in [basis, *basis["refinement_windows"]]:
            protected.extend([level["manifest"], *[p for p in level["sources"].values() if p]])
    for instance in base["instances"]:
        protected.extend([instance["manifest"], instance["pa_path"]])
    order = ["parent"]
    while len(order) < len(levels):
        ready = [label for label in labels if label not in order and levels[label]["parent_label"] in order]
        if not ready:
            raise ValueError("composition parent chain contains a cycle")
        order.extend(ready)
    return dict(
        schema_version=1,
        role="mrtof_native_static_field_provider_plan",
        operation="compose",
        **_ip_metadata(base),
        run_id=request.get("run_id"),
        project=PROJECT,
        inputs=inputs,
        operator_ancestry_projections=ancestry,
        protected_paths=sorted(set(protected)),
        candidate_authority=authority,
        source_authority=base["authority"],
        resolved_geometry=base["geometry"],
        levels=levels,
        execution_order=order,
        window_labels=labels,
        response_basis=None,
        fly_authorized=False,
        refine_performed=False,
        response_basis_paths=paths,
        coefficients=coefficients["coefficients"],
        **({"consumer_view": view} if view else {}),
        combination_base_binding=base_path,
        target_voltages_v=request["candidate_voltages_v"],
        **({"target_mirror_voltages_v": authority["analyzer_electrode_voltages_v"][:5]} if TE1_AXIS in bases else {}),
        collision_instances=[
            {k: i[k] for k in ("role", "manifest", "pa_path", "origin_mm")} for i in base["instances"]
        ],
        committed_new_bytes=sum(x["committed_new_bytes"] for x in levels.values()),
        final_retained_estimate_bytes=sum(x["committed_new_bytes"] for x in levels.values()),
        **numerics,
        automatic_retry_count=0,
        qualification_passed=False,
    )


def _compile_consumer_view(request: dict[str, Any]) -> dict[str, Any]:
    """Plan a storage-only official crop of a sealed field or pure response."""
    allowed = {
        "schema_version",
        "role",
        "run_id",
        "source_binding_path",
        "source_field_manifest",
        "numerical_contract_path",
        "consumer_view_source_path",
    }
    if set(request) - allowed:
        raise ValueError("consumer view creation cannot change voltages or solve inputs")
    contract_path = Path(request["numerical_contract_path"]).resolve()
    profile = read(contract_path)["simion"]["numerical_profiles"]["native_static_field"]
    view = validate_native_consumer_view(profile.get("consumer_view"))
    if view is None:
        raise ValueError("consumer view creation requires numerical consumer_view authority")
    baseline = load_binding(Path(request["source_binding_path"]))
    source_path = Path(request["consumer_view_source_path"]).resolve()
    descriptor = read(source_path)
    source = (
        load_native_response_basis(source_path, baseline)
        if descriptor.get("role") == "mrtof_native_static_field_response_basis"
        else load_binding(source_path)
    )
    if source.get("consumer_view") or source["mode"] != "native_static_pa":
        raise ValueError("consumer view requires an original three-dimensional native field")
    if Path(request["source_field_manifest"]).resolve() != Path(source["manifest"]).resolve():
        raise ValueError("consumer view source manifest differs")
    numerics = resolve_native_refine_numerics(read(contract_path))
    if not native_numerics_match(source, contract_path):
        raise ValueError("consumer view cannot change Refine precision")
    labels = (
        ["window"]
        if len(source["refinement_windows"]) == 1
        else [f"window_{i}" for i in range(len(source["refinement_windows"]))]
    )
    ordered = [source, *source["refinement_windows"]]
    identities = {
        (Path(x["manifest"]).resolve(), Path(x["sources"]["scalar_pa"]).resolve()): label
        for label, x in zip(["parent", *labels], ordered, strict=True)
    }
    levels, protected = {}, [str(source_path), request["source_binding_path"]]
    specs = [descriptor["parent"], *descriptor["refinement_windows"]]
    for label, level, source_spec in zip(["parent", *labels], ordered, specs, strict=True):
        original = read(Path(level["numerical_plan_path"]))
        grid = level["grid"]
        if grid["dimensions"][0] <= view["stored_x_nodes"]:
            raise ValueError("consumer view must crop a wider original field")
        value = copy.deepcopy(original)
        for key in ("crop", "consumer_grid", "full_solve_plan_path", "gem", "materialization_receipt_path"):
            value.pop(key, None)
        value.update(
            consumer_view=view,
            consumer_view_source=copy.deepcopy(source_spec),
            source_solve_plan_path=level["numerical_plan_path"],
            source_solve_manifest=level["manifest"],
            refine_performed=False,
            parent_label=None,
            **numerics,
        )
        value["dimensions"] = [view["stored_x_nodes"], *grid["dimensions"][1:]]
        value["box_mm"] = [
            *grid["origin_mm"],
            *[grid["origin_mm"][a] + (value["dimensions"][a] - 1) * grid["pitch_mm"][a] for a in range(3)],
        ]
        value["pitch_mm"] = grid["pitch_mm"]
        value["boundary_mode"] = "grounded_enclosure" if label == "parent" else "x_mirror_five_faces"
        if label != "parent":
            value["parent_label"] = identities[
                (Path(original["parent_manifest"]).resolve(), Path(original["parent_pa"]).resolve())
            ]
            value.update(
                name=level["name"],
                active_box_mm=[[-2 * grid["pitch_mm"][0], 2 * grid["pitch_mm"][0]], *level["active_box_mm"][1:]],
            )
        size = math.prod(value["dimensions"]) * 8 + 56
        surface_size = level["records"]["surface"]["bytes"] if level["records"]["surface"] else 0
        value.update(
            committed_new_bytes=math.ceil(size * 1.05 + surface_size * 1.1) + 16 * 1024**2,
            final_retained_estimate_bytes=math.ceil(size * 1.05 + surface_size * 1.1) + 16 * 1024**2,
        )
        levels[label] = value
        protected.extend([level["manifest"], *[p for p in level["sources"].values() if p]])
    inputs = {
        "source_binding": request["source_binding_path"],
        "view_source_binding": str(source_path),
        "numerical_contract": str(contract_path),
    }
    if source.get("response_basis", {}).get("axis") == TE1_AXIS:
        inputs["te1_reference"] = descriptor["direction_reference_path"]
    for item in source["instances"]:
        protected.extend([item["manifest"], item["pa_path"]])
    return dict(
        schema_version=1,
        role="mrtof_native_static_field_provider_plan",
        operation="crop_view",
        run_id=request.get("run_id"),
        project=PROJECT,
        inputs=inputs,
        protected_paths=sorted(set(protected)),
        consumer_view=view,
        candidate_authority=source["authority"],
        source_authority=baseline["authority"],
        resolved_geometry=source["geometry"],
        levels=levels,
        execution_order=["parent", *labels],
        window_labels=labels,
        response_basis=source.get("response_basis"),
        fly_authorized=False,
        collision_instances=[
            {k: i[k] for k in ("role", "manifest", "pa_path", "origin_mm")} for i in source["instances"]
        ],
        committed_new_bytes=sum(v["committed_new_bytes"] for v in levels.values()),
        final_retained_estimate_bytes=sum(v["final_retained_estimate_bytes"] for v in levels.values()),
        refine_performed=False,
        automatic_retry_count=0,
        qualification_passed=False,
        **numerics,
    )


def _resolve_new_geometry(path: Path, source: dict[str, Any], numerical_contract: dict[str, Any]) -> dict[str, Any]:
    """Replace only analyzer mirror solids; retain the frozen component assembly."""
    contract = load_contract(path)
    for key in ("coordinate_system", "accelerator", "detector"):
        if contract.get(key) != numerical_contract.get(key):
            raise ValueError(f"geometry contract changes {key}; component/frame changes require a new assembly")
    geometry = resolve_geometry(contract, accelerator_assembly=source["authority"]["assembly"])
    mutable = {
        "mirror_electrodes",
        "mirror_ground_shields",
        "mirror_e_closures",
        "mirror_convergence_transform",
        "metadata",
    }
    # The upper vacuum interval is mirror-derived; the chosen observation plane
    # and prism-side bound remain fixed, rather than silently moving a target.
    reference_key = "two_prism_low_field_reference_section"
    if reference_key in geometry or reference_key in source["geometry"]:
        references = []
        for item in (geometry[reference_key], source["geometry"][reference_key]):
            reference = copy.deepcopy(item)
            reference["open_project_z_interval_mm"] = reference["open_project_z_interval_mm"][:1]
            for key in ("upper_boundary_candidates_mm", "selected_upper_boundary_mm", "mirror_inner_face"):
                reference["derivation"].pop(key, None)
            references.append(reference)
        if references[0] != references[1]:
            raise ValueError("new mirror geometry must retain the observation plane and prism-side reference")
        mutable.add(reference_key)
    for key in set(geometry) | set(source["geometry"]):
        if key not in mutable and geometry.get(key) != source["geometry"].get(key):
            raise ValueError(f"geometry contract changes {key}; only mirror solids may change in this provider")
    if geometry["detector"] != source["authority"]["assembly"]["detector"]:
        raise ValueError("geometry contract differs from frozen detector assembly")
    return geometry


def _check_mirror_parent_bounds(geometry: dict[str, Any], bounds: list[float]) -> None:
    """The x-mirrored parent must contain every changed mirror conductor AABB."""
    for key in ("mirror_electrodes", "mirror_ground_shields", "mirror_e_closures"):
        for solid in geometry[key]:
            box = solid["box"]
            if (
                len(box) != 6
                or not all(math.isfinite(v) for v in box)
                or max(abs(box[0]), abs(box[3])) > bounds[3]
                or any(box[a] < bounds[a] or box[a + 3] > bounds[a + 3] for a in (1, 2))
            ):
                raise ValueError("new mirror conductor lies outside the grounded parent grid")


def _new_collision_plan(source: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    """Reuse the sealed collision grid, not its old conductor occupancy."""
    instance = source["instances"][1]
    path = Path(instance["pa_path"])
    with path.open("rb") as stream:
        raw = stream.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise ValueError("collision source header is truncated")
    header = PaHeader(*HEADER.unpack(raw))
    # A sealed .pa0 has family flags/footer which the ordinary composer rightly
    # rejects. Only its spatial header is reused; gem2pa writes a new plain PA.
    if (
        header.mode != -2
        or header.symmetry != 1
        or header.raw_mirror & 7 != 1
        or header.raw_mirror & 8
        or min(header.nx, header.ny, header.nz) < 2
        or any(not math.isfinite(v) or v <= 0 for v in (header.dx_mm, header.dy_mm, header.dz_mm))
        or path.stat().st_size < header.file_bytes
    ):
        raise ValueError("collision source must retain the x-mirrored planar grid")
    origin = instance["origin_mm"]
    pitch = [header.dx_mm, header.dy_mm, header.dz_mm]
    dimensions = [header.nx, header.ny, header.nz]
    gem = (
        "; Collision occupancy only; no Refine or Fast Adjust.\npa_define("
        + ",".join(map(str, dimensions))
        + ",planar,x,electrostatic,,"
        + ",".join(format(v, ".17g") for v in pitch)
        + ",surface=fractional)\nlocate("
        + ",".join(format(-v, ".17g") for v in origin)
        + ") {\n"
        + "\n".join(_analyzer_geometry_lines(geometry))
        + "\n}\n"
    )
    surface = Path(str(path) + "-surf")
    allowance = math.ceil(surface.stat().st_size * 1.1) if surface.is_file() else 0
    return dict(
        source_instance=copy.deepcopy(instance),
        origin_mm=origin,
        pitch_mm=pitch,
        source_header=header.__dict__,
        source_footer_bytes=path.stat().st_size - header.file_bytes,
        dimensions=dimensions,
        symmetry="x",
        header_bytes=len(header.pack()),
        pa_bytes=header.file_bytes,
        committed_new_bytes=header.file_bytes + allowance + 16 * 1024**2,
        surface_allowance_bytes=allowance,
        gem=gem,
        refine_performed=False,
        fast_adjust_performed=False,
        occupancy_geometry="same frozen resolved_geometry.json",
    )


def _compile_ip_fine_extension(request: dict[str, Any]) -> dict[str, Any]:
    """Reuse one ordinary operator, rebuilding only its extended IP fine domain."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import (
        _gem, extend_fine_z_domain, ordinary_pa_file_bytes,
    )
    required = {"schema_version", "role", "source_binding_path", "source_field_manifest",
                "numerical_contract_path", "reuse_source_levels", "ion_processor_local_domain_update"}
    if (set(request) - {"run_id"} != required or request["schema_version"] != 1
            or request["role"] != ROLE
            or request["reuse_source_levels"] != ["parent", "window_1", "window_2", "window_3"]):
        raise ValueError("IP fine extension requires its closed ordinary-only request and four exact reused levels")
    source_path = Path(request["source_binding_path"]).resolve()
    descriptor = read(source_path)
    source = load_binding(source_path)
    if (not _ip_metadata(source) or source.get("consumer_view") or descriptor.get("local_domain_update")
            or descriptor.get("role") != "mrtof_native_static_field_binding"
            or [w["name"] for w in source["refinement_windows"]]
            != ["ion_processor_local", "positive_integer_grid_a", "negative_integer_grid_a", "covered_local"]):
        raise ValueError("IP fine extension requires an ordinary complete IP source with unchanged route order")
    source_owner = Path(source["manifest"])
    verify_record("IP extension source binding", _record(source_owner, source_path), base_dir=source_owner.parent)
    contract_path = Path(request["numerical_contract_path"]).resolve()
    if not native_numerics_match(source, contract_path):
        raise ValueError("IP fine extension cannot change actual Refine stopping")
    if Path(request["source_field_manifest"]).resolve() != source_owner.resolve():
        raise ValueError("IP fine extension source manifest differs")
    fine_source = source["refinement_windows"][0]
    fine_grid, active = extend_fine_z_domain(fine_source["grid"], fine_source["active_box_mm"],
        request["ion_processor_local_domain_update"], source["grid"])
    # Compile through the ordinary public provider; no response bank or solver.
    ordinary = {k: request[k] for k in required - {"reuse_source_levels", "ion_processor_local_domain_update"}}
    if "run_id" in request:
        ordinary["run_id"] = request["run_id"]
    ordinary["candidate_voltages_v"] = {name: source["authority"]["analyzer_electrode_voltages_v"][ids[0]-1]
                                       for name, ids in PS_GROUPS.items()}
    plan = compile_request(ordinary)
    if plan["candidate_authority"] != source["authority"] or plan["resolved_geometry"] != source["geometry"]:
        raise ValueError("IP fine extension must preserve all voltages and geometry")
    labels = ["parent", *plan["window_labels"]]
    for label, original in zip(labels, [descriptor["parent"], *descriptor["refinement_windows"]], strict=True):
        if label == "window_0":
            continue
        plan["levels"][label]["reuse_source"] = copy.deepcopy(original)
        plan["levels"][label]["committed_new_bytes"] = 0
        plan["levels"][label]["final_retained_estimate_bytes"] = 0
        plan["levels"][label].pop("gem", None)
    fine = plan["levels"]["window_0"]
    if fine["parent_label"] != "parent":
        raise ValueError("IP fine extension must retain its direct global parent dependency")
    fine.update(box_mm=fine_grid["origin_mm"] + [fine_grid["origin_mm"][a]
        + (fine_grid["dimensions"][a]-1)*fine_grid["pitch_mm"][a] for a in range(3)],
        dimensions=fine_grid["dimensions"], active_box_mm=active)
    _native_active_box(active, fine_grid)
    fine["gem"], fine["geometry_report"] = _static_gem(plan["resolved_geometry"], plan["candidate_authority"],
        fine, boundary_mode="x_mirror_five_faces")
    pa_bytes = ordinary_pa_file_bytes(fine["dimensions"], fine["pitch_mm"])
    surface_allowance = math.ceil(Path(fine_source["sources"]["surface"]).stat().st_size
                                  * fine_grid["dimensions"][2] / fine_source["grid"]["dimensions"][2])
    committed = math.ceil(pa_bytes*1.05 + surface_allowance*1.1) + 16*1024**2
    fine.update(committed_new_bytes=committed, final_retained_estimate_bytes=committed,
        capacity_basis=dict(pa_node_bytes=pa_bytes, source_surface_bytes=surface_allowance,
            allowance="5% PA + 10% z-extent-scaled source surface + 16MiB evidence; no reused PA copies"))
    plan["ip_collision_build"] = dict(origin_mm=fine_grid["origin_mm"], pitch_mm=fine_grid["pitch_mm"],
        dimensions=fine_grid["dimensions"], symmetry="x", pa_bytes=pa_bytes,
        committed_new_bytes=committed, surface_allowance_bytes=surface_allowance,
        refine_performed=False, fast_adjust_performed=False)
    rows = source["authority"]["component_voltages_v"]
    plan["ip_collision_build"]["gem"] = _gem(source["geometry"], source["geometry"]["ion_processor_electrodes"],
        [r["voltage_v"] for r in rows if r["component_namespace"] == "ion_processor"],
        source["authority"]["analyzer_electrode_voltages_v"], 0, fine, occupancy=True)
    plan["local_domain_update"] = dict(schema_version=1, role="mrtof_ip_fine_domain_update",
        update=copy.deepcopy(request["ion_processor_local_domain_update"]),
        reused_levels=copy.deepcopy(request["reuse_source_levels"]),
        source_manifest=dict(path=str(source_owner.resolve()), bytes=source_owner.stat().st_size,
                             sha256=file_sha256(source_owner)))
    plan["committed_new_bytes"] = plan["final_retained_estimate_bytes"] = 2*committed
    plan["protected_paths"] = sorted(set(plan["protected_paths"] + [str(source_owner.parent)]
        + [str(Path(i["manifest"]).parent) for i in source["instances"]]
        + [i["pa_path"] for i in source["instances"]]))
    return plan


def _compile_ip_fine_response_reuse(request: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the extended fine response with four sealed same-axis pure fields."""
    required = {"schema_version", "role", "source_binding_path", "source_field_manifest",
                "numerical_contract_path", "response_axis", "reuse_response_basis_path", "reuse_source_levels"}
    if (set(request) - {"run_id"} != required or request["schema_version"] != 1 or request["role"] != ROLE
            or request["response_axis"] not in {"p1", "p2"}
            or request["reuse_source_levels"] != ["parent", "window_1", "window_2", "window_3"]):
        raise ValueError("IP fine response reuse requires its closed pure P1/P2 request")
    source = load_binding(Path(request["source_binding_path"]))
    old_path = Path(request["reuse_response_basis_path"]).resolve()
    old_descriptor = read(old_path)
    if old_descriptor.get("response_level_reuse"):
        raise ValueError("IP fine response reuse requires an original complete pure response")
    old_source = _load_operator_ancestry(Path(old_descriptor["source_binding_path"]),
        copy_owner=Path(old_descriptor["refinement_windows"][0]["manifest"]))
    old = load_native_response_basis(old_path, old_source)
    validate_ip_fine_response_reuse(old, source, request["response_axis"])
    ordinary_request = {k: v for k, v in request.items() if k not in {"reuse_response_basis_path", "reuse_source_levels"}}
    plan = compile_request(ordinary_request)
    if plan["candidate_authority"] != old["authority"]:
        raise ValueError("IP fine response reuse differs from exact pure voltage authority")
    for label, original in zip(["parent", *plan["window_labels"]],
            [old_descriptor["parent"], *old_descriptor["refinement_windows"]], strict=True):
        if label == "window_0":
            continue
        spec = plan["levels"][label]
        spec.update(reuse_source=copy.deepcopy(original), committed_new_bytes=0, final_retained_estimate_bytes=0)
        spec.pop("gem", None)
    if plan["levels"]["window_0"]["parent_label"] != "parent":
        raise ValueError("IP fine response requires its direct reused pure parent")
    old_owner = Path(old["refinement_windows"][0]["manifest"])
    plan["response_level_reuse"] = dict(schema_version=1, role="mrtof_ip_fine_response_reuse",
        axis=request["response_axis"], reused_levels=copy.deepcopy(request["reuse_source_levels"]),
        source_basis=dict(path=str(old_path), bytes=old_path.stat().st_size, sha256=file_sha256(old_path)),
        source_basis_manifest=dict(path=str(old_owner.resolve()), bytes=old_owner.stat().st_size,
                                   sha256=file_sha256(old_owner)))
    plan["inputs"]["reused_response_basis"] = str(old_path)
    plan["protected_paths"] = sorted(set(plan["protected_paths"] + [str(old_owner.parent), str(old_path)]
        + [str(Path(i["manifest"]).parent) for i in source["instances"]]
        + [i["pa_path"] for i in source["instances"]]))
    fine = plan["levels"]["window_0"]
    plan["committed_new_bytes"] = fine["committed_new_bytes"]
    plan["final_retained_estimate_bytes"] = fine["final_retained_estimate_bytes"]
    return plan


def collision_pa_header(path: Path) -> PaHeader:
    """Read occupancy bounds only, including SIMION's ordinary unit-grid format.

    Installed SIMION 2020 lib/python/SIMION/PA.py load/save defines mode -1
    with 32 header bytes and implicit unit pitch. The affine composer remains
    mode -2 only; this reader cannot authorize field composition or PA families.
    """
    with path.open("rb") as stream:
        raw = stream.read(32)
        pitch_raw = stream.read(24)
    if len(raw) != 32:
        raise ValueError("collision occupancy header is truncated")
    values = struct.unpack("<iidiiii", raw)
    if values[0] == -2 and len(pitch_raw) != 24:
        raise ValueError("collision occupancy pitch header is truncated")
    header = PaHeader(*values, *(struct.unpack("<ddd", pitch_raw) if values[0] == -2 else (1, 1, 1)))
    # The collision-only reader accepts the documented persistent not-refinable
    # flag; affine composition and all source field readers remain unchanged.
    known_flags = ((1 << 21)-1) | COLLISION_NOTREFINABLE_FLAG
    if (path.suffix.lower() != ".pa" or header.mode not in (-1, -2) or header.symmetry != 1
            or header.raw_mirror < 0 or header.raw_mirror & 8 or header.raw_mirror & ~known_flags
            or min(header.nx, header.ny, header.nz) < 1
            or not math.isfinite(header.max_voltage) or header.max_voltage <= 0
            or any(not math.isfinite(v) or v <= 0 for v in (header.dx_mm, header.dy_mm, header.dz_mm))
            or path.stat().st_size != (56 if header.mode == -2 else 32)+header.node_count*8):
        raise ValueError("invalid ordinary collision occupancy header or payload")
    return header


def collision_overlay_plan(source: dict[str, Any], update: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Compile same-CSG occupancy; its vacuum replaces the coarse PA too."""
    from .ion_processor_assembly import ordinary_pa_file_bytes
    if (not isinstance(update, dict) or set(update) != {"box_mm", "pitch_mm", "priority_probes"}
            or "collision_overlay" in source or source.get("consumer_view")
            or source.get("accelerator_provider") != IP_PROVIDER
            or [i["role"] for i in source["instances"]] != ["global_fallback", "native_corridor", "ion_processor_collision", "detector"]):
        raise ValueError("collision overlay requires one complete four-role IP source and explicit patch numerics")
    box, pitch = update["box_mm"], update["pitch_mm"]
    if (not isinstance(box, list) or len(box) != 6
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
            or box[0] != 0 or any(box[a] >= box[a+3] for a in range(3))):
        raise ValueError("collision overlay requires a finite x-mirrored nonempty box")
    validate_generation_grid_pitch(contract, pitch)
    dimensions = _grid_shape(box, pitch)
    if min(dimensions) < 3:
        raise ValueError("collision overlay requires at least three nodes on every axis")
    def bounds(instance):
        header = collision_pa_header(Path(instance["pa_path"]))
        if header.symmetry != 1 or header.raw_mirror & 7 not in (0, 1):
            raise ValueError("collision overlay requires planar independent collision instances")
        origin = instance["origin_mm"]
        extent = [(n-1)*d for n, d in zip((header.nx, header.ny, header.nz),
                  (header.dx_mm, header.dy_mm, header.dz_mm), strict=True)]
        return [origin[0]-extent[0] if header.raw_mirror & 1 else origin[0], *origin[1:],
                *[origin[a]+extent[a] for a in range(3)]]
    effective = [-box[3], box[1], box[2], *box[3:]]
    corridor = bounds(source["instances"][1])
    if any(effective[a] < corridor[a] or effective[a+3] > corridor[a+3] for a in range(3)):
        raise ValueError("collision overlay must remain inside the original corridor")
    for instance in source["instances"][2:]:
        other = bounds(instance)
        if all(effective[a] <= other[a+3] and other[a] <= effective[a+3] for a in range(3)):
            raise ValueError("collision overlay cannot mask the IP or detector PA volume")
    probes = update["priority_probes"]
    if not isinstance(probes, list) or not probes:
        raise ValueError("collision overlay requires declared metal, vacuum and exterior priority probes")
    labels, categories = set(), set()
    for probe in probes:
        if (not isinstance(probe, dict) or set(probe) != {"label", "point_mm", "expected_electrode", "expected_instance"}
                or not isinstance(probe["label"], str) or not probe["label"] or probe["label"] in labels
                or type(probe["expected_electrode"]) is not bool or type(probe["expected_instance"]) is not int
                or probe["expected_instance"] not in (2, 5)):
            raise ValueError("invalid collision overlay priority probe")
        point = probe["point_mm"]
        if (not isinstance(point, list) or len(point) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)):
            raise ValueError("collision overlay probe requires finite project coordinates")
        inside = all(effective[a] <= point[a] <= effective[a+3] for a in range(3))
        if inside != (probe["expected_instance"] == 5) or not all(corridor[a] <= point[a] <= corridor[a+3] for a in range(3)):
            raise ValueError("collision overlay probe instance contradicts its declared box")
        for instance in source["instances"][2:]:
            other = bounds(instance)
            if all(other[a] <= point[a] <= other[a+3] for a in range(3)):
                raise ValueError("collision overlay exterior probe is masked by another instance")
        labels.add(probe["label"])
        categories.add((inside, probe["expected_electrode"]))
    if not {(True, True), (True, False)} <= categories or not any(not inside for inside, _ in categories):
        raise ValueError("collision overlay probes must cover interior metal, interior vacuum and exterior")
    bracket = any(
        sum(a != b for a, b in zip(inner["point_mm"], outer["point_mm"], strict=True)) == 1
        and all(abs(inner["point_mm"][a]-outer["point_mm"][a]) <= 2*pitch[a] for a in range(3))
        for inner in probes if inner["expected_instance"] == 5
        for outer in probes if outer["expected_instance"] == 2)
    if not bracket:
        raise ValueError("collision overlay probes require an adjacent inside/outside face bracket")
    gem = ("; Same complete analyzer CSG; collision only, no Refine or Fast Adjust.\npa_define("
           + ",".join(map(str, dimensions)) + ",planar,x,electric_,,"
           + ",".join(format(v, ".17g") for v in pitch) + ",surface=fractional)\nlocate("
           + ",".join(format(-v, ".17g") for v in box[:3]) + ") {\n"
           + "\n".join(_analyzer_geometry_lines(source["geometry"])) + "\n}\n")
    pa_bytes = ordinary_pa_file_bytes(dimensions, pitch)
    # Fractional surface storage is unknown before native GEM conversion. Reserve
    # another full PA plus evidence; the owner still measures the actual output.
    committed = 2*pa_bytes + 16*1024**2
    return dict(box_mm=box, origin_mm=box[:3], pitch_mm=pitch, dimensions=dimensions,
                symmetry="x", pa_bytes=pa_bytes, committed_new_bytes=committed,
                surface_allowance_bytes=pa_bytes, priority_probes=copy.deepcopy(probes), gem=gem,
                refine_performed=False, fast_adjust_performed=False, refinable=False)


def _compile_collision_overlay(request: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "role", "source_binding_path", "source_field_manifest",
                "numerical_contract_path", "collision_overlay_update"}
    if set(request)-{"run_id"} != required or request["schema_version"] != 1 or request["role"] != ROLE:
        raise ValueError("unsupported collision-only overlay request")
    run_id = request.get("run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id or run_id in {".", ".."} or any(c in run_id for c in "/\\")):
        raise ValueError("invalid overlay run_id")
    path = Path(request["source_binding_path"]).resolve()
    if read(path).get("role") != "mrtof_native_static_field_binding":
        raise ValueError("collision overlay source must be an original ordinary or materialized native binding")
    source = load_binding(path)
    owner = Path(source.get("descriptor_owner", source["manifest"])).resolve()
    if Path(request["source_field_manifest"]).resolve() != owner:
        raise ValueError("collision overlay source descriptor owner differs")
    record = _record(owner, path)
    verify_record("collision overlay source", record, base_dir=owner.parent)
    contract_path = Path(request["numerical_contract_path"]).resolve()
    patch = collision_overlay_plan(source, request["collision_overlay_update"], read(contract_path))
    source_plan = read(Path(source["sources"]["numerical_plan"]))
    limits = copy.deepcopy(source_plan["resource_limits"])
    if limits.get("automatic_retry_count") != 0:
        raise ValueError("collision overlay cannot enable automatic retry")
    protected = [str(owner.parent), str(path)]
    for level in [source, *source["refinement_windows"]]:
        protected += [level["manifest"], *[v for v in level["sources"].values() if v]]
    for instance in source["instances"]:
        protected += [instance["manifest"], instance["pa_path"]]
    return dict(schema_version=1, role="mrtof_native_static_field_provider_plan", operation="collision_overlay",
                run_id=run_id, project=PROJECT, inputs=dict(source_binding=str(path), source_manifest=str(owner),
                numerical_contract=str(contract_path)), protected_paths=sorted(set(protected)), levels={},
                execution_order=[], window_labels=[], source_authority=source["authority"],
                candidate_authority=source["authority"], resolved_geometry=source["geometry"],
                source_binding_record={k: record[k] for k in ("path", "bytes", "sha256")}, source_descriptor_owner=str(owner), resource_limits=limits,
                guard_paths=sorted({v for v in protected if Path(v).suffix.lower() == ".pa" or v.endswith(".pa-surf")}),
                analyzer_collision_patch_build=patch, committed_new_bytes=patch["committed_new_bytes"],
                final_retained_estimate_bytes=patch["committed_new_bytes"], automatic_retry_count=0,
                refine_stopping="not_performed_collision_only", fly_authorized=False, qualification_passed=False,
                official_sources=[dict(title="SIMION Multiple PAs", url="https://simion.com/info/multiple_pas.html",
                    consulted="2026-10-18", installed_version="SIMION 2020",
                    method="Highest-priority instance replaces the complete overlap volume, including vacuum; project collision-only overlay uses unchanged field callback."),
                    dict(title="SIMION GEM Geometry File", url="https://simion.com/info/gem_geometry_file.html",
                    consulted="2026-10-18", installed_version="SIMION 2020",
                    method="Native gem2pa of the same complete analyzer CSG; fractional surface; electric_ persists refinable=false (supported since 8.1.1.0); no Refine/Fast Adjust."),
                    dict(title="SIMION 2020 official MATLAB PA writer", path="C:/Program Files/SIMION-2020/examples/matlab/simion_pa_save.m",
                    consulted="2026-10-18", installed_version="SIMION 2020",
                    method="NOTREFINABLE = 2^28 in mirrordata; collision-only header validation accepts this documented flag, leaving affine composition readers unchanged.")])


def compile_request(request: dict[str, Any]) -> dict[str, Any]:
    """Validate a native source and derive one four-coordinate candidate."""
    if "collision_overlay_update" in request:
        return _compile_collision_overlay(request)
    if "reuse_response_basis_path" in request:
        return _compile_ip_fine_response_reuse(request)
    if "ion_processor_local_domain_update" in request:
        return _compile_ip_fine_extension(request)
    if "replacement_assembly_path" in request:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import (
            compile_materializable_fields,
        )

        return compile_materializable_fields(request)
    allowed = {
        "schema_version",
        "role",
        "source_binding_path",
        "source_field_manifest",
        "candidate_voltages_v",
        "mirror_voltage_variation_path",
        "mirror_reference_trial_manifest",
        "mirror_contract_path",
        "run_id",
        "numerical_contract_path",
        "response_axis",
        "response_basis_paths",
        "te1_reference_path",
        "consumer_view_source_path",
        "geometry_contract_path",
        "reuse_source_levels",
    }
    if request.get("schema_version") != 1 or request.get("role") != ROLE or set(request) - allowed:
        raise ValueError("unsupported native static provider request")
    run_id = request.get("run_id")
    if run_id is not None and (
        not isinstance(run_id, str) or not run_id or run_id in {".", ".."} or any(c in run_id for c in "/\\")
    ):
        raise ValueError("invalid provider run_id")
    geometry_path = request.get("geometry_contract_path")
    if "geometry_contract_path" in request:
        if not isinstance(geometry_path, str) or not geometry_path:
            raise ValueError("geometry_contract_path must identify an explicit geometry contract")
        if any(key in request for key in ("consumer_view_source_path", "response_axis", "response_basis_paths")):
            raise ValueError("new geometry requires direct build, not an old response or consumer view")
        geometry_path = Path(geometry_path).resolve()
    if "consumer_view_source_path" in request:
        return _compile_consumer_view(request)
    response_axis = request.get("response_axis")
    if "response_axis" in request:
        if (
            not isinstance(response_axis, str)
            or response_axis not in set(PS_GROUPS) | {TE1_AXIS}
            or "response_basis_paths" in request
            or any(
                key in request
                for key in (
                    "candidate_voltages_v",
                    "mirror_voltage_variation_path",
                    "mirror_reference_trial_manifest",
                    "mirror_contract_path",
                )
            )
        ):
            raise ValueError("response_axis requires one pure axis and no candidate or mirror update")
    if (response_axis == TE1_AXIS) != ("te1_reference_path" in request):
        raise ValueError("te1_reference_path is required only for the pure TE1 response_axis")
    if response_axis is None:
        candidate = request.get("candidate_voltages_v")
        if (
            not isinstance(candidate, dict)
            or set(candidate) != set(PS_GROUPS)
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in candidate.values()
            )
        ):
            raise ValueError("candidate requires exactly four finite P/S voltages")
    contract_path = request.get("numerical_contract_path")
    if not isinstance(contract_path, str) or not contract_path:
        raise ValueError("native provider requires numerical_contract_path")
    contract_path = Path(contract_path).resolve()
    numerical_contract = read(contract_path)
    numerics = resolve_native_refine_numerics(numerical_contract)
    requested_layout = numerical_contract["simion"]["numerical_profiles"]["native_static_field"].get(
        "target_layout", {}
    )
    if any(
        isinstance(item, dict) and "box_mm" in item
        for item in [requested_layout.get("parent"), *requested_layout.get("windows", [])]
    ) and (
        request.get("reuse_source_levels") != ["parent", "window_2"]
        or any(
            key in request for key in ("response_basis_paths", "consumer_view_source_path", "geometry_contract_path")
        )
        or response_axis not in (None, "s1")
    ):
        raise ValueError("box override requires ordinary mirror-only level reuse")
    reused = request.get("reuse_source_levels", [])
    reused_basis = None
    if reused and response_axis is not None:
        if response_axis != "s1":
            raise ValueError("response level reuse requires the same pure S1 excitation")
        descriptor_path = Path(request["source_binding_path"])
        descriptor = read(descriptor_path)
        if descriptor.get("role") != "mrtof_native_static_field_response_basis":
            raise ValueError("response level reuse requires a sealed pure response source")
        ordinary = load_binding(Path(descriptor["source_binding_path"]))
        source = load_native_response_basis(descriptor_path, ordinary)
        reused_basis = source
    else:
        source = load_binding(Path(request["source_binding_path"]))
    if "reuse_source_levels" in request and (
        reused != ["parent", "window_2"]
        or len(source["refinement_windows"]) != 3
        or any(key in request for key in ("response_basis_paths", "geometry_contract_path"))
    ):
        raise ValueError("level reuse requires ordinary same-geometry parent/window_2 and two new mirror solves")
    if source["mode"] != "native_static_pa" or len(source["refinement_windows"]) not in ({4} if _ip_metadata(source) else {1, 3}):
        raise ValueError("native static provider requires native parent and local windows")
    if Path(request["source_field_manifest"]).resolve() != Path(source.get("descriptor_owner", source["manifest"])).resolve():
        raise ValueError("source field manifest differs from native parent")
    if response_axis is not None and not native_numerics_match(source, contract_path):
        raise ValueError("response stopping contract must match its actual baseline")
    response_basis = None
    if response_axis is not None:
        response_basis = (
            _te1_basis_metadata(Path(request["te1_reference_path"]).resolve())
            if response_axis == TE1_AXIS
            else {
                "axis": response_axis,
                "normalization_v": RESPONSE_NORMALIZATION_V,
                "physical_electrode_ids": list(PS_GROUPS[response_axis]),
                "excitation_semantics": "pure axis response; all other analyzer/component potentials zero",
                "combination_semantics": "base PA plus (target axis minus base axis)/normalization_v times this PA",
            }
        )
        authority = _response_authority(source["authority"], response_basis)
        mirror_paths = {}
        if reused_basis is not None and response_basis != reused_basis["response_basis"]:
            raise ValueError("reused response axis or normalization differs")
    else:
        authority, mirror_paths = derive_candidate_authority(request, source["authority"])
    if reused and (authority != source["authority"] or not native_numerics_match(source, contract_path)):
        raise ValueError("reused levels require identical complete voltage authority and stopping contract")
    if "response_basis_paths" in request:
        composition = _compile_composition(request, source, authority, contract_path, numerics)
        if composition is not None:
            return composition
        if "materialization" in source:
            source = load_binding(Path(source["materialization"]["base_binding"]))
    if source.get("consumer_view"):
        raise ValueError("a consumer view cannot be Refined or supply a new solve boundary")
    if _ip_metadata(source) and (geometry_path is not None or reused or response_axis == TE1_AXIS):
        raise ValueError("IP P/S operator cannot change geometry, reuse levels or vary mirrors")
    geometry = (
        source["geometry"]
        if geometry_path is None
        else _resolve_new_geometry(geometry_path, source, numerical_contract)
    )
    layout = (_ip_source_layout(source) if _ip_metadata(source) else
              numerical_contract["simion"]["numerical_profiles"]["native_static_field"].get("target_layout"))
    if (
        not isinstance(layout, dict)
        or set(layout) != {"parent", "windows"}
        or not isinstance(layout["windows"], list)
        or len(layout["windows"]) != len(source["refinement_windows"])
    ):
        raise ValueError("explicit target_layout must match source window priority length")
    labels = ["window"] if len(layout["windows"]) == 1 else [f"window_{i}" for i in range(len(layout["windows"]))]
    sources = dict(zip(["parent", *labels], [source, *source["refinement_windows"]]))
    identities = {
        (Path(level["manifest"]).resolve(), Path(level["sources"]["scalar_pa"]).resolve()): label
        for label, level in sources.items()
    }
    if len(identities) != len(sources):
        raise ValueError("source levels require distinct sealed PA identities")
    levels = {}
    inputs = {
        "source_binding": str(Path(request["source_binding_path"]).resolve()),
        "numerical_contract": str(contract_path),
        "grid_validator": str(Path(__file__).with_name("native_corridor_plan.py").resolve()),
    }
    ancestry_bindings = [source]
    if _ip_metadata(source):
        inputs["ion_processor_emitter"] = str(Path(__file__).with_name("ion_processor_assembly.py").resolve())
        inputs["gem_primitives"] = str(Path(__file__).resolve().parents[3] / "common/simion/gem_primitives.py")
    if reused_basis is not None:
        inputs["source_response_basis"] = inputs["source_binding"]
        inputs["source_binding"] = reused_basis["source_binding_path"]
    if geometry_path is not None:
        inputs["geometry_contract"] = str(geometry_path)
    if response_axis == TE1_AXIS:
        inputs["te1_reference"] = str(Path(request["te1_reference_path"]).resolve())
    protected = [request["source_binding_path"]]
    targets = dict(zip(["parent", *labels], [layout["parent"], *layout["windows"]]))
    for label, level in sources.items():
        manifest = Path(level["manifest"])
        path = Path(level["sources"]["numerical_plan"])
        _record(manifest, path)
        original = read(path)
        source_plan = original
        # Composition stores the consumer grid, not the original full solve.
        # Recover only sealed small numerical ancestry; no retired PA is opened.
        solve_manifest = manifest
        seen = {path.resolve()}
        while original.get("source_solve_plan_path") is not None:
            ancestor = Path(original["source_solve_plan_path"]).resolve()
            solve_manifest = Path(original["source_solve_manifest"]).resolve()
            if ancestor in seen:
                raise ValueError("source numerical solve ancestry contains a cycle")
            verify_record("source_solve_plan", _record(solve_manifest, ancestor), base_dir=solve_manifest.parent)
            inherited = read(ancestor)
            if any(
                inherited.get(key) != original.get(key)
                for key in (
                    "box_mm",
                    "pitch_mm",
                    "dimensions",
                    "mirror_axes",
                    "surface",
                    "boundary_mode",
                    "ordinary_static_pa",
                )
            ):
                raise ValueError("composition consumer grid differs from its sealed source solve")
            inputs[label + "_solve_ancestor_" + str(len(seen))] = str(ancestor)
            inputs[label + "_solve_manifest_" + str(len(seen))] = str(solve_manifest)
            seen.add(ancestor)
            original, path = inherited, ancestor
        consumer_plan = original
        if original.get("crop") is not None:
            full_path = original.get("full_solve_plan_path")
            if not isinstance(full_path, str) or not full_path:
                raise ValueError("cropped source requires sealed full_solve_plan_path")
            path = Path(full_path).resolve()
            verify_record("full_solve_plan", _record(solve_manifest, path), base_dir=solve_manifest.parent)
            original = read(path)
            if (
                path == Path(level["sources"]["numerical_plan"]).resolve()
                or original.get("full_solve_plan_path") is not None
                or any(
                    original.get(k) != consumer_plan.get(k)
                    for k in (
                        "pitch_mm",
                        "mirror_axes",
                        "surface",
                        "parent_pa",
                        "parent_manifest",
                        "frozen_input",
                        "resolved_geometry",
                        "boundary_mode",
                        "ordinary_static_pa",
                    )
                )
                or original["box_mm"][:3] != consumer_plan["box_mm"][:3]
                or original["box_mm"][4:] != consumer_plan["box_mm"][4:]
                or original["box_mm"][3] <= consumer_plan["box_mm"][3]
                or original.get("crop", {}).get("consumer_dimensions") != consumer_plan["dimensions"]
                or original.get("crop", {}).get("consumer_box_mm") != consumer_plan["box_mm"]
            ):
                raise ValueError("full solve source differs from its cropped physical grid")
        grid = {k: copy.deepcopy(original[k]) for k in ("box_mm", "pitch_mm", "dimensions", "mirror_axes", "surface")}
        target = targets[label]
        if (
            not isinstance(target, dict)
            or not {"pitch_mm"} <= set(target)
            or set(target) - {"pitch_mm", "stored_xmax_mm", "box_mm"}
            or label == "parent"
            and "stored_xmax_mm" in target
        ):
            raise ValueError("invalid target layout level")
        grid["pitch_mm"] = copy.deepcopy(target["pitch_mm"])
        active = copy.deepcopy(level.get("active_box_mm"))
        if "box_mm" in target:
            box = target["box_mm"]
            if (
                not reused
                or label not in {"window_0", "window_1"}
                or not isinstance(box, list)
                or len(box) != 6
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
                or any(box[a] != original["box_mm"][a] for a in (0, 1, 2, 3, 5))
                or box[4] < original["box_mm"][4]
                or grid["pitch_mm"] != original["pitch_mm"]
            ):
                raise ValueError("mirror box override may only extend y maximum at unchanged pitch")
            grid["box_mm"] = copy.deepcopy(box)
            active[1][1] += box[4] - original["box_mm"][4]
        if response_basis is not None and (
            grid["pitch_mm"] != source_plan["pitch_mm"]
            or ("stored_xmax_mm" in target) != (consumer_plan.get("crop") is not None)
            or "stored_xmax_mm" in target
            and target["stored_xmax_mm"] != source_plan["box_mm"][3]
        ):
            raise ValueError("response target layout must match the actual baseline grid and crop")
        quantum = validate_generation_grid_pitch(numerical_contract, grid["pitch_mm"])
        if "box_mm" in target and not math.isclose(
            grid["box_mm"][4] / quantum, round(grid["box_mm"][4] / quantum), abs_tol=1e-8, rel_tol=0
        ):
            raise ValueError("mirror y maximum must align with grid generation quantum")
        grid["dimensions"] = _grid_shape(grid["box_mm"], grid["pitch_mm"])
        if geometry_path is not None and label == "parent":
            _check_mirror_parent_bounds(geometry, grid["box_mm"])
        parent_label = None
        if label != "parent":
            identity = (Path(source_plan["parent_manifest"]).resolve(), Path(source_plan["parent_pa"]).resolve())
            parent_label = identities.get(identity)
            if parent_label is None or parent_label == label:
                raise ValueError("source window boundary parent is not a declared distinct level")
        mode = "grounded_enclosure" if label == "parent" else "x_mirror_five_faces"
        gem, report = _static_gem(geometry, authority, grid, boundary_mode=mode)
        if original.get("resource_limits", {}).get("automatic_retry_count") != 0:
            raise ValueError("native provider requires no automatic retry")
        pa_bytes = math.prod(grid["dimensions"]) * 8 + 56
        surface_bytes = Path(level["sources"]["surface"]).stat().st_size
        committed_bytes = math.ceil(pa_bytes * 1.05 + surface_bytes * 1.1) + 16 * 1024**2
        levels[label] = dict(
            grid,
            boundary_mode=mode,
            ordinary_static_pa=True,
            parent_label=parent_label,
            **numerics,
            numerical_contract_path=str(contract_path),
            resource_budget=copy.deepcopy(original["resource_budget"]),
            resource_limits=copy.deepcopy(original["resource_limits"]),
            committed_new_bytes=committed_bytes,
            capacity_basis={
                "pa_node_bytes": pa_bytes,
                "source_surface_bytes": surface_bytes,
                "allowance": "5% PA + 10% surface + 16MiB small evidence per level; no PA copies",
            },
            geometry_report=report,
            gem=gem,
        )
        if response_basis is not None:
            levels[label]["response_basis"] = copy.deepcopy(response_basis)
        if label != "parent":
            levels[label].update(name=level["name"], active_box_mm=active)
        if "stored_xmax_mm" in target:
            xmax = target["stored_xmax_mm"]
            if (
                isinstance(xmax, bool)
                or not isinstance(xmax, (int, float))
                or not math.isfinite(xmax)
                or not grid["box_mm"][0] < xmax < grid["box_mm"][3]
            ):
                raise ValueError("stored_xmax_mm must lie inside full solved x domain")
            consumer = copy.deepcopy(grid)
            consumer["box_mm"][3] = xmax
            consumer["dimensions"] = _grid_shape(consumer["box_mm"], consumer["pitch_mm"])
            if max(abs(v) for v in active[0]) + grid["pitch_mm"][0] > xmax:
                raise ValueError("crop consumer lacks active x gradient halo")
            levels[label]["consumer_grid"] = consumer
            levels[label]["crop"] = {
                "method": "pa:crop",
                "start_grid": [0, 0, 0],
                "width_grid": [n - 1 for n in consumer["dimensions"]],
                "persist": False,
                "overwrite_private_working_pa": True,
                "refine_after_crop": False,
                "consumer_box_mm": consumer["box_mm"],
                "consumer_dimensions": consumer["dimensions"],
                "expected_consumer_pa_bytes": math.prod(consumer["dimensions"]) * 8 + 56,
            }
        stored = levels[label].get("consumer_grid", grid)
        if label != "parent":
            _native_active_box(
                active,
                {
                    "origin_mm": stored["box_mm"][:3],
                    "pitch_mm": stored["pitch_mm"],
                    "dimensions": stored["dimensions"],
                    "symmetry": "x",
                },
            )
        retained_bytes = math.prod(stored["dimensions"]) * 8 + 56
        levels[label]["capacity_basis"].update(
            final_pa_bytes=retained_bytes, crop_storage="same private PA path; no permanent full-plus-crop pair"
        )
        levels[label]["final_retained_estimate_bytes"] = (
            math.ceil(retained_bytes * 1.05 + surface_bytes * 1.1) + 16 * 1024**2
        )
        if reused:
            if ("box_mm" not in target and grid["box_mm"] != original["box_mm"]) or grid["pitch_mm"][:2] != original[
                "pitch_mm"
            ][:2]:
                raise ValueError("mirror-only refinement must retain full boxes and x/y pitches")
            if label in reused:
                if (
                    grid["pitch_mm"] != source_plan["pitch_mm"]
                    or stored["box_mm"] != source_plan["box_mm"]
                    or stored["dimensions"] != source_plan["dimensions"]
                ):
                    raise ValueError("reused level target grid or crop differs from its sealed source")
                for role in ("numerical_plan", "geometry_authority", "voltage_authority"):
                    verify_record(role, _record(manifest, Path(level["sources"][role])), base_dir=manifest.parent)
                descriptor = {
                    "manifest": level["manifest"],
                    "pa_path": level["sources"]["scalar_pa"],
                    "surface_path": level["sources"]["surface"],
                    "numerical_plan_path": level["sources"]["numerical_plan"],
                    "geometry_authority_path": level["sources"]["geometry_authority"],
                    "voltage_authority_path": level["sources"]["voltage_authority"],
                    "grid": copy.deepcopy(level["grid"]),
                }
                if label != "parent":
                    descriptor.update(
                        name=level["name"],
                        active_box_mm=copy.deepcopy(level["active_box_mm"]),
                        parent_manifest=source_plan["parent_manifest"],
                    )
                levels[label]["reuse_source"] = descriptor
                levels[label]["committed_new_bytes"] = 0
                levels[label]["final_retained_estimate_bytes"] = 0
        for role in ("numerical_plan", "geometry_authority", "voltage_authority"):
            inputs[label + "_" + role] = level["sources"][role]
        inputs[label + "_manifest"] = str(manifest.resolve())
        inputs[label + "_full_solve_plan"] = str(path.resolve())
        protected.extend([str(manifest.parent), *level["sources"].values()])
    for name, path in mirror_paths.items():
        inputs["mirror_" + Path(name).stem] = path
    execution_order = ["parent"]
    while len(execution_order) < len(levels):
        ready = [
            label
            for label in labels
            if label not in execution_order and levels[label]["parent_label"] in execution_order
        ]
        if not ready:
            raise ValueError("native source boundary dependency contains a cycle")
        execution_order.extend(ready)
    for label in labels:
        child, parent = levels[label], levels[levels[label]["parent_label"]]
        parent_grid = parent.get("consumer_grid", parent)
        if any(
            child["box_mm"][a] < parent_grid["box_mm"][a] or child["box_mm"][a + 3] > parent_grid["box_mm"][a + 3]
            for a in range(3)
        ):
            raise ValueError("target full solve lies outside its actual parent")
    for instance in source["instances"][1:]:
        protected.extend([instance["manifest"], instance["pa_path"]])
    if "response_basis_paths" in request:
        # A fixed-offset solve still freezes/protects the declared reusable bank.
        for axis, path in request["response_basis_paths"].items():
            basis = load_native_response_basis(Path(path), source)
            ancestry_bindings.append(basis)
            inputs["response_" + axis] = path
            protected.append(path)
            for level in [basis, *basis["refinement_windows"]]:
                protected.extend([level["manifest"], *[p for p in level["sources"].values() if p]])
    ancestry = _operator_ancestry_inputs(inputs, ancestry_bindings)
    retained, peak = 0, 0
    for label in execution_order:
        peak = max(peak, retained + levels[label]["committed_new_bytes"])
        retained += levels[label]["final_retained_estimate_bytes"]
    collision = None
    if geometry_path is not None:
        collision = _new_collision_plan(source, geometry)
        peak += collision["committed_new_bytes"]
        retained += collision["committed_new_bytes"]
    return {
        "schema_version": 1,
        "role": "mrtof_native_static_field_provider_plan",
        "operation": "refine",
        **_ip_metadata(source),
        "run_id": run_id,
        "project": PROJECT,
        "inputs": inputs,
        "operator_ancestry_projections": ancestry,
        "protected_paths": sorted(set(protected)),
        "candidate_authority": authority,
        "source_authority": (reused_basis["source_authority"] if reused_basis is not None else source["authority"]),
        "resolved_geometry": geometry,
        "levels": levels,
        "window_labels": labels,
        "execution_order": execution_order,
        "target_layout": copy.deepcopy(layout),
        "response_basis": response_basis,
        "fly_authorized": False,
        "collision_instances": [
            {k: item[k] for k in ("role", "manifest", "pa_path", "origin_mm")} for item in source["instances"]
        ],
        **({"collision_build": collision} if collision is not None else {}),
        "committed_new_bytes": peak,
        "final_retained_estimate_bytes": retained,
        **numerics,
        "refine_options": {"convergence": numerics["convergence_v"]},
        "grid_generation": {"spacing_quantum_mm": quantum},
        "automatic_retry_count": 0,
        "qualification_passed": False,
        "official_sources": [
            {
                "url": "https://simion.com/info/gem_geometry_file.html",
                "title": "SIMION GEM Geometry File",
                "consulted": "2026-10-10",
                "installed_version": "SIMION 2020",
                "method": "ordinary fractional x-mirrored GEM; supported since 8.1/8.2",
            },
            {
                "url": "https://simion.com/info/refine.html",
                "title": "SIMION Refine",
                "consulted": "2026-10-10",
                "installed_version": "SIMION 2020",
                "method": "ordinary Refine with contract-owned convergence; all other options installed defaults",
            },
        ],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def prepare_run(plan: dict[str, Any], run_directory: Path) -> dict[str, Any]:
    """Emit full-solve GEMs and consumer plans, without PA I/O or solver calls."""
    inputs = run_directory / "inputs"
    if plan.get("operation") == "collision_overlay":
        source = load_binding(inputs / "source_binding.json")
        verify_record("collision overlay frozen source", dict(plan["source_binding_record"],
                      path=str((inputs / "source_binding.json").resolve())))
        update = {k: plan["analyzer_collision_patch_build"][k] for k in ("box_mm", "pitch_mm", "priority_probes")}
        patch = collision_overlay_plan(source, update, read(inputs / "numerical_contract.json"))
        if (patch != plan["analyzer_collision_patch_build"] or source["authority"] != plan["candidate_authority"]
                or source["geometry"] != plan["resolved_geometry"]):
            raise ValueError("collision overlay frozen source or compiled plan differs")
        write_json(inputs / "frozen_input.json", source["authority"])
        write_json(inputs / "resolved_geometry.json", source["geometry"])
        directory = run_directory / "simion/analyzer_collision_patch"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "analyzer_collision_patch.gem").write_text(patch.pop("gem"), encoding="utf-8", newline="\n")
        patch.update(resolved_geometry=str((inputs / "resolved_geometry.json").resolve()),
                     numerical_contract_path=str((inputs / "numerical_contract.json").resolve()))
        write_json(inputs / "analyzer_collision_patch_plan.json", patch)
        return plan
    if plan.get("operator_ancestry_projections"):
        projection_path = inputs / "operator_ancestry_projection.json"
        write_json(projection_path, {
            "schema_version": 1, "role": "mrtof_native_operator_ancestry_consumption",
            "projections": plan["operator_ancestry_projections"],
            "claim": "Historical operator metadata only; current field payloads remain required.",
        })
        for level in plan["levels"].values():
            if "reuse_source" not in level:
                level["operator_ancestry_projection_path"] = str(projection_path.resolve())
    if plan.get("accelerator_provider") == IP_PROVIDER and "replacement_assembly" in plan["inputs"]:
        return _prepare_replacement_run(plan, run_directory)
    if plan.get("operation") == "crop_view":
        profile = read(inputs / "numerical_contract.json")["simion"]["numerical_profiles"]["native_static_field"]
        if validate_native_consumer_view(profile.get("consumer_view")) != plan["consumer_view"]:
            raise ValueError("consumer view differs from frozen numerical contract")
        write_json(inputs / "frozen_input.json", plan["candidate_authority"])
        write_json(inputs / "resolved_geometry.json", plan["resolved_geometry"])
        write_json(inputs / "source_authority.json", plan["source_authority"])
        manifest = str((run_directory / "run_manifest.json").resolve())
        for label, value in plan["levels"].items():
            (run_directory / "simion" / label).mkdir(parents=True, exist_ok=True)
            value.update(
                numerical_contract_path=str((inputs / "numerical_contract.json").resolve()),
                frozen_input=str((inputs / "frozen_input.json").resolve()),
                resolved_geometry=str((inputs / "resolved_geometry.json").resolve()),
                consumer_view_receipt_path=str((run_directory / "results" / (label + "_crop_receipt.json")).resolve()),
            )
            if label != "parent":
                parent = value["parent_label"]
                value.update(
                    parent_manifest=manifest,
                    parent_pa=str(
                        (
                            run_directory
                            / "simion"
                            / parent
                            / ("c0_static.pa" if parent == "parent" else "c0_local.pa")
                        ).resolve()
                    ),
                )
            write_json(inputs / (label + "_plan.json"), value)
        write_json(inputs / "plan.json", plan)
        return plan
    basis = plan.get("response_basis")
    if basis is not None:
        if (
            basis.get("axis") not in set(PS_GROUPS) | {TE1_AXIS}
            or basis.get("normalization_v") != RESPONSE_NORMALIZATION_V
            or basis.get("axis") != TE1_AXIS
            and basis.get("physical_electrode_ids") != list(PS_GROUPS[basis["axis"]])
            or plan.get("fly_authorized") is not False
            or plan["candidate_authority"] != _response_authority(plan["source_authority"], basis)
            or any(level.get("response_basis") != basis for level in plan["levels"].values())
        ):
            raise ValueError("pure response excitation or no-Fly identity differs")
        if basis["axis"] == TE1_AXIS and basis != _te1_basis_metadata(inputs / "te1_reference.json"):
            raise ValueError("pure TE1 response differs from its frozen reference direction")
    numerical_contract = read(inputs / "numerical_contract.json")
    if "geometry_contract" in plan["inputs"]:
        frozen_geometry = _resolve_new_geometry(
            inputs / "geometry_contract.json",
            {"authority": plan["source_authority"], "geometry": plan["resolved_geometry"]},
            numerical_contract,
        )
        if frozen_geometry != plan["resolved_geometry"]:
            raise ValueError("compiled geometry differs from frozen geometry contract")
    numerics = resolve_native_refine_numerics(numerical_contract)
    if plan.get("operation") == "compose":
        if any(plan.get(key) != value for key, value in numerics.items()):
            raise ValueError("composition stopping differs from frozen operator")
        return _prepare_composition(plan, run_directory)
    layout = (_ip_source_layout(load_binding(inputs / "source_binding.json")) if _ip_metadata(plan) else
              numerical_contract["simion"]["numerical_profiles"]["native_static_field"].get("target_layout"))
    if (
        layout != plan.get("target_layout")
        or not isinstance(layout, dict)
        or set(layout) != {"parent", "windows"}
        or not isinstance(layout["windows"], list)
        or len(layout["windows"]) != len(plan["window_labels"])
    ):
        raise ValueError("compiled target layout differs from its frozen numerical contract")
    targets = dict(zip(["parent", *plan["window_labels"]], [layout["parent"], *layout["windows"]]))
    for label, level in plan["levels"].items():
        target = targets[label]
        if (
            level["pitch_mm"] != target.get("pitch_mm")
            or "box_mm" in target
            and level["box_mm"] != target["box_mm"]
            or level["dimensions"] != _grid_shape(level["box_mm"], level["pitch_mm"])
            or ("crop" in level) != ("stored_xmax_mm" in target)
            or "crop" in level
            and level["consumer_grid"]["box_mm"][3] != target["stored_xmax_mm"]
        ):
            raise ValueError("compiled target layout differs from its frozen numerical contract")
        quantum = validate_generation_grid_pitch(numerical_contract, level["pitch_mm"])
        if plan.get("grid_generation") != {"spacing_quantum_mm": quantum}:
            raise ValueError("compiled native grid policy differs from its frozen numerical contract")
    if (
        any(plan.get(key) != value for key, value in numerics.items())
        or plan.get("refine_options") != {"convergence": numerics["convergence_v"]}
        or any(any(level.get(key) != value for key, value in numerics.items()) for level in plan["levels"].values())
    ):
        raise ValueError("compiled native stopping differs from its frozen numerical contract")
    write_json(inputs / "frozen_input.json", plan["candidate_authority"])
    write_json(inputs / "resolved_geometry.json", plan["resolved_geometry"])
    if plan.get("response_level_reuse"):
        write_json(inputs / "ip_fine_response_reuse.json", plan["response_level_reuse"])
    if plan.get("local_domain_update"):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import extend_fine_z_domain
        frozen_source = inputs / "source_binding.json"
        source = load_binding(frozen_source)
        fine_grid, active = extend_fine_z_domain(source["refinement_windows"][0]["grid"],
            source["refinement_windows"][0]["active_box_mm"], plan["local_domain_update"]["update"], source["grid"])
        fine = plan["levels"]["window_0"]
        if (fine["dimensions"] != fine_grid["dimensions"] or fine["box_mm"][:3] != fine_grid["origin_mm"]
                or fine["active_box_mm"] != active or plan["candidate_authority"] != source["authority"]):
            raise ValueError("IP fine extension differs from its frozen source and declared domain update")
        lineage = copy.deepcopy(plan["local_domain_update"])
        lineage["source_binding"] = dict(path=str(frozen_source.resolve()), bytes=frozen_source.stat().st_size,
                                         sha256=file_sha256(frozen_source))
        write_json(inputs / "ip_fine_domain_update.json", lineage)
        occupancy = copy.deepcopy(plan["ip_collision_build"])
        directory = run_directory / "simion/ip_collision"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "ip_collision.gem").write_text(occupancy.pop("gem"), encoding="utf-8")
        occupancy["resolved_geometry"] = str((inputs / "resolved_geometry.json").resolve())
        write_json(inputs / "ip_collision_plan.json", occupancy)
    if "collision_build" in plan:
        collision = copy.deepcopy(plan["collision_build"])
        directory = run_directory / "simion/collision"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "collision.gem").write_text(collision.pop("gem"), encoding="utf-8")
        collision["resolved_geometry"] = str((inputs / "resolved_geometry.json").resolve())
        write_json(inputs / "collision_plan.json", collision)
    if plan.get("response_basis") is not None:
        write_json(inputs / "source_authority.json", plan["source_authority"])
    manifest = str((run_directory / "run_manifest.json").resolve())
    for label in plan["execution_order"]:
        if "reuse_source" in plan["levels"][label]:
            continue
        target = run_directory / "simion" / label
        target.mkdir(parents=True, exist_ok=True)
        level = copy.deepcopy(plan["levels"][label])
        level["numerical_contract_path"] = str((inputs / "numerical_contract.json").resolve())
        if _ip_metadata(plan):
            level["ip_source_binding_path"] = str((inputs / "source_binding.json").resolve())
        if plan.get("local_domain_update"):
            level["local_domain_update_path"] = str((inputs / "ip_fine_domain_update.json").resolve())
        if plan.get("response_level_reuse"):
            level["response_level_reuse_path"] = str((inputs / "ip_fine_response_reuse.json").resolve())
        gem = level.pop("gem")
        level.update(
            frozen_input=str((inputs / "frozen_input.json").resolve()),
            resolved_geometry=str((inputs / "resolved_geometry.json").resolve()),
        )
        if label != "parent":
            parent_label = level["parent_label"]
            parent_name = "c0_static.pa" if parent_label == "parent" else "c0_local.pa"
            parent_source = plan["levels"][parent_label].get("reuse_source")
            level.update(
                parent_manifest=parent_source["manifest"] if parent_source else manifest,
                parent_pa=parent_source["pa_path"]
                if parent_source
                else str((run_directory / "simion" / parent_label / parent_name).resolve()),
            )
        write_json(inputs / (label + "_plan.json"), level)
        if "crop" in level:
            consumer = copy.deepcopy(level)
            consumer.update(consumer.pop("consumer_grid"))
            consumer["full_solve_plan_path"] = str((inputs / (label + "_plan.json")).resolve())
            consumer["crop"]["receipt_path"] = str(
                (run_directory / "results" / (label + "_crop_receipt.json")).resolve()
            )
            write_json(inputs / (label + "_consumer_plan.json"), consumer)
        (target / ("c0_static.gem" if label == "parent" else "c0_local.gem")).write_text(gem, encoding="utf-8")
    return plan


def _prepare_replacement_run(plan: dict[str, Any], run_directory: Path) -> dict[str, Any]:
    """Freeze one new full-IP assembly through the same field-provider owner."""
    inputs = run_directory / "inputs"
    if (
        read(inputs / "replacement_geometry.json") != plan["resolved_geometry"]
        or read(inputs / "replacement_assembly.json")["old_oa_removed"] is not True
        or plan.get("fly_authorized") is not False
        or plan.get("qualification_passed") is not False
    ):
        raise ValueError("replacement frozen geometry or preparation scope differs")
    numerics = resolve_native_refine_numerics(read(inputs / "numerical_contract.json"))
    if any(plan.get(key) != value for key, value in numerics.items()):
        raise ValueError("replacement Refine stopping differs from frozen numerical contract")
    write_json(inputs / "frozen_input.json", plan["candidate_authority"])
    write_json(inputs / "resolved_geometry.json", plan["resolved_geometry"])
    manifest = str((run_directory / "run_manifest.json").resolve())
    for label in plan["execution_order"]:
        level = copy.deepcopy(plan["levels"][label])
        if level["dimensions"] != _grid_shape(level["box_mm"], level["pitch_mm"]) or any(
            level.get(key) != value for key, value in numerics.items()
        ):
            raise ValueError("replacement level grid or stopping differs")
        validate_generation_grid_pitch(read(inputs / "numerical_contract.json"), level["pitch_mm"])
        level.update(
            numerical_contract_path=str((inputs / "numerical_contract.json").resolve()),
            **({"ip_source_binding_path": str((inputs / "source_binding.json").resolve())} if _ip_metadata(plan) else {}),
            frozen_input=str((inputs / "frozen_input.json").resolve()),
            resolved_geometry=str((inputs / "resolved_geometry.json").resolve()),
        )
        if label != "parent":
            parent = level["parent_label"]
            basename = "c0_static.pa" if parent == "parent" else "c0_local.pa"
            level.update(
                parent_manifest=manifest, parent_pa=str((run_directory / "simion" / parent / basename).resolve())
            )
        directory = run_directory / "simion" / label
        directory.mkdir(parents=True, exist_ok=True)
        gem = level.pop("gem")
        (directory / ("c0_static.gem" if label == "parent" else "c0_local.gem")).write_text(
            gem, encoding="utf-8", newline="\n"
        )
        write_json(inputs / (label + "_plan.json"), level)
    for name in ("collision", "ip_collision", "detector"):
        value = copy.deepcopy(plan[name + "_build"])
        directory = run_directory / "simion" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (name + ".gem")).write_text(value.pop("gem"), encoding="utf-8", newline="\n")
        value["resolved_geometry"] = str((inputs / "resolved_geometry.json").resolve())
        write_json(inputs / (name + "_plan.json"), value)
    return plan


def _prepare_composition(plan: dict[str, Any], run_directory: Path) -> dict[str, Any]:
    """Freeze target metadata only; source solve ancestry is retained separately."""
    inputs = run_directory / "inputs"
    write_json(inputs / "frozen_input.json", plan["candidate_authority"])
    write_json(inputs / "resolved_geometry.json", plan["resolved_geometry"])
    write_json(inputs / "source_authority.json", plan["source_authority"])
    metadata = dict(
        base_binding=plan["combination_base_binding"],
        response_basis_paths=plan["response_basis_paths"],
        target_voltages_v=plan["target_voltages_v"],
        plan_path=str((inputs / "plan.json").resolve()),
        receipts={},
    )
    if TE1_AXIS in plan["response_basis_paths"]:
        metadata["target_mirror_voltages_v"] = plan["target_mirror_voltages_v"]
    manifest = str((run_directory / "run_manifest.json").resolve())
    for label in plan["execution_order"]:
        directory = run_directory / "simion" / label
        directory.mkdir(parents=True, exist_ok=True)
        value = copy.deepcopy(plan["levels"][label])
        value.update(
            numerical_contract_path=str((inputs / "numerical_contract.json").resolve()),
            **({"ip_source_binding_path": str((inputs / "source_binding.json").resolve())} if _ip_metadata(plan) else {}),
            frozen_input=str((inputs / "frozen_input.json").resolve()),
            resolved_geometry=str((inputs / "resolved_geometry.json").resolve()),
        )
        if label != "parent":
            parent = value["parent_label"]
            value.update(
                parent_manifest=manifest,
                parent_pa=str(
                    (
                        run_directory / "simion" / parent / ("c0_static.pa" if parent == "parent" else "c0_local.pa")
                    ).resolve()
                ),
            )
        receipt = str((run_directory / "results" / (label + "_composition_receipt.json")).resolve())
        value["materialization_receipt_path"] = receipt
        metadata["receipts"][label] = receipt
        write_json(inputs / (label + "_plan.json"), value)
    plan["materialization"] = metadata
    write_json(inputs / "plan.json", plan)
    return plan


def compose_run(plan: dict[str, Any], run_directory: Path) -> None:
    """Write one candidate set in bounded blocks; the caller owns leases/sealing."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import compose_standalone_pa

    if plan.get("operation") != "compose" or plan.get("refine_performed") is not False:
        raise ValueError("compose requires a prepared no-Refine composition plan")
    for label in plan["execution_order"]:
        level = plan["levels"][label]
        output = run_directory / "simion" / label / ("c0_static.pa" if label == "parent" else "c0_local.pa")
        receipt = compose_standalone_pa(
            Path(level["composition"]["base_pa"]),
            output,
            [(Path(r["path"]), r["coefficient"]) for r in level["composition"]["responses"]],
        )
        write_json(Path(plan["materialization"]["receipts"][label]), receipt)


def binding_spec(plan: dict[str, Any], run_directory: Path) -> dict[str, Any]:
    """Describe new fields; a geometry rebuild also replaces analyzer collision occupancy."""
    manifest = str((run_directory / "run_manifest.json").resolve())
    if plan.get("operation") == "collision_overlay":
        return dict(schema_version=1, role="mrtof_native_collision_overlay_binding", manifest=manifest,
                    source_binding=dict(plan["source_binding_record"], manifest=plan["source_descriptor_owner"]),
                    source_binding_copy=str((run_directory / "inputs/source_binding.json").resolve()),
                    patch_plan_path=str((run_directory / "inputs/analyzer_collision_patch_plan.json").resolve()),
                    patch_pa_path=str((run_directory / "simion/analyzer_collision_patch/analyzer_collision_patch.pa").resolve()),
                    patch_surface_path=str((run_directory / "simion/analyzer_collision_patch/analyzer_collision_patch.pa-surf").resolve()))

    def level(label: str) -> dict[str, Any]:
        spec = plan["levels"][label]
        if "reuse_source" in spec:
            return copy.deepcopy(spec["reuse_source"])
        grid = spec.get("consumer_grid", spec)
        path = run_directory / "simion" / label / ("c0_static.pa" if label == "parent" else "c0_local.pa")
        return {
            "manifest": manifest,
            "pa_path": str(path.resolve()),
            "surface_path": str(path.resolve()) + "-surf",
            "voltage_authority_path": str((run_directory / "inputs/frozen_input.json").resolve()),
            "geometry_authority_path": str((run_directory / "inputs/resolved_geometry.json").resolve()),
            "numerical_plan_path": str(
                (
                    run_directory / "inputs" / (label + ("_consumer_plan.json" if "crop" in spec else "_plan.json"))
                ).resolve()
            ),
            "grid": {
                "origin_mm": grid["box_mm"][:3],
                "pitch_mm": grid["pitch_mm"],
                "dimensions": grid["dimensions"],
                "symmetry": "x",
            },
        }

    parent = level("parent")
    windows = []
    for label in plan["window_labels"]:
        spec = plan["levels"][label]
        window = level(label)
        parent_source = plan["levels"][spec["parent_label"]].get("reuse_source")
        window.update(
            name=spec["name"],
            active_box_mm=spec["active_box_mm"],
            parent_manifest=parent_source["manifest"] if parent_source else manifest,
        )
        windows.append(window)
    if plan.get("accelerator_provider") == IP_PROVIDER and "collision_build" in plan:
        instances = [
            {
                "role": "global_fallback",
                "manifest": manifest,
                "pa_path": parent["pa_path"],
                "origin_mm": parent["grid"]["origin_mm"],
            }
        ]
        for role, name in (
            ("native_corridor", "collision"),
            ("ion_processor_collision", "ip_collision"),
            ("detector", "detector"),
        ):
            instances.append(
                {
                    "role": role,
                    "manifest": manifest,
                    "pa_path": str((run_directory / "simion" / name / (name + ".pa")).resolve()),
                    "origin_mm": plan[name + "_build"]["origin_mm"],
                }
            )
        return {
            "schema_version": 1,
            "role": "mrtof_native_static_field_binding",
            "accelerator_provider": plan["accelerator_provider"],
            "assembly_scope": plan["assembly_scope"],
            "replacement_assembly": plan["replacement_assembly"],
            "parent": parent,
            "refinement_windows": windows,
            "instances": instances,
        }
    instances = copy.deepcopy(plan["collision_instances"])
    if not plan.get("consumer_view"):
        instances[0] = {
            "role": "global_fallback",
            "manifest": parent["manifest"],
            "pa_path": parent["pa_path"],
            "origin_mm": parent["grid"]["origin_mm"],
        }
    if "collision_build" in plan:
        instances[1] = {
            "role": "native_corridor",
            "manifest": manifest,
            "pa_path": str((run_directory / "simion/collision/collision.pa").resolve()),
            "origin_mm": plan["collision_build"]["origin_mm"],
        }
    if plan.get("local_domain_update"):
        instances[2] = dict(role="ion_processor_collision", manifest=manifest,
            pa_path=str((run_directory / "simion/ip_collision/ip_collision.pa").resolve()),
            origin_mm=plan["ip_collision_build"]["origin_mm"])
    result = {
        "schema_version": 1,
        "role": "mrtof_native_static_field_binding",
        **_ip_metadata(plan),
        "parent": parent,
        "refinement_windows": windows,
        "instances": instances,
    }
    if plan.get("consumer_view"):
        result["consumer_view"] = plan["consumer_view"]
    if plan.get("local_domain_update"):
        lineage = run_directory / "inputs/ip_fine_domain_update.json"
        result["local_domain_update"] = dict(path=str(lineage.resolve()), bytes=lineage.stat().st_size,
                                             sha256=file_sha256(lineage))
    if plan.get("response_level_reuse"):
        lineage = run_directory / "inputs/ip_fine_response_reuse.json"
        result["response_level_reuse"] = dict(path=str(lineage.resolve()), bytes=lineage.stat().st_size,
                                               sha256=file_sha256(lineage))
    if plan.get("response_basis") is not None:
        result.update(
            role="mrtof_native_static_field_response_basis",
            fly_authorized=False,
            response_basis=copy.deepcopy(plan["response_basis"]),
            source_authority_path=str((run_directory / "inputs/source_authority.json").resolve()),
        )
        result["source_binding_path"] = str((run_directory / "inputs/source_binding.json").resolve())
        if plan["response_basis"]["axis"] == TE1_AXIS:
            result["direction_reference_path"] = str((run_directory / "inputs/te1_reference.json").resolve())
    if plan.get("operation") == "compose":
        result["materialization"] = copy.deepcopy(plan["materialization"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--binding", action="store_true")
    parser.add_argument("--compose", action="store_true")
    args = parser.parse_args()
    if args.request:
        print(json.dumps(compile_request(read(args.request)), allow_nan=False))
    else:
        if args.plan is None or args.run_directory is None or sum((args.prepare, args.binding, args.compose)) != 1:
            parser.error("plan/run-directory and exactly one prepare, compose or binding required")
        plan = read(args.plan)
        if args.prepare:
            prepare_run(plan, args.run_directory)
        elif args.compose:
            compose_run(plan, args.run_directory)
        else:
            path = (
                args.run_directory
                / "results"
                / ("response_basis.json" if plan.get("response_basis") is not None else "field_binding.json")
            )
            write_json(path, binding_spec(plan, args.run_directory))
            print(str(path.resolve()))


if __name__ == "__main__":
    main()
