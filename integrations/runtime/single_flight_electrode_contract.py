"""Published electrode-topology registry for the joint single-flight runtime."""

from __future__ import annotations

import math
from typing import Any, Mapping

from projects.rf_multipole_ion_optics.simion.simion_geometry import physical_electrode_view


ROD_ELECTRODE_IDS = tuple(range(1, 9))
POST_PULSE_FIELD_LOADING_POLICY_ID = "pre_pulse_restart_zero_rod_modes_v1"
THREE_ZONE_PA_PLUS_MODEL_ID = "three_zone_linear_ring_octupole_symmetry_pa_plus_v2"
TWO_ZONE_BARE_VARIANT = "canonical_two_zone_bare_continuous_rods_v1"
TWO_ZONE_BARE_PA_PLUS_MODEL_ID = "two_zone_linear_ring_bare_octupole_pa_plus_v1"
THREE_ZONE_BARE_VARIANT = "canonical_three_zone_bare_continuous_rods_v1"
THREE_ZONE_BARE_PA_PLUS_MODEL_ID = "three_zone_linear_ring_bare_octupole_pa_plus_v1"
SEGMENTED_THROUGH_EXIT_PA_PLUS_MODEL_ID = "three_zone_linear_ring_segmented_through_exit_pa_plus_v1"
PA_PLUS_FIELD_LOADING_POLICY_ID = "octupole_common_differential_pa_plus_v2"


def _physical_voltage_value(document: dict, pointer: str) -> float:
    value: object = document
    for token in pointer.split('/')[1:]:
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdecimal() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValueError(f'physical electrode voltage source is missing: {pointer}')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'physical electrode voltage source is not finite: {pointer}')
    return float(value)


def physical_multipole_voltages(resolved: dict, mapping: dict[int, int]) -> tuple[dict[int, float], dict[int, int]]:
    """Resolve one provider's static volts and RF groups into bound solver IDs."""
    carrier, groups = {}, {}
    for row in physical_electrode_view(resolved):
        native = row['native_electrode_id']
        if native not in mapping:
            raise ValueError('physical electrode binding omits a provider-native group')
        source = row['voltage_source']
        solver = mapping[native]
        if source['kind'] == 'static':
            carrier[solver] = _physical_voltage_value(resolved, source['pointer'])
        elif source['kind'] == 'rf_drive':
            common = _physical_voltage_value(resolved, source['common_mode_pointer'])
            dc = _physical_voltage_value(resolved, source['dc_amplitude_pointer'])
            group = source['rf_group']
            carrier[solver] = common + (dc if group == 1 else -dc)
            groups[solver] = group
        else:
            raise ValueError('physical electrode voltage source kind is unsupported')
    return carrier, groups


def require_pa_plus_solution_model(
    model: Mapping[str, Any], *, allow_post_pulse_projection: bool = False,
) -> dict[str, Any]:
    """Validate supported physical PA+ bases without inventing a new model."""
    model_id = model.get("model_id")
    if model_id not in {THREE_ZONE_PA_PLUS_MODEL_ID, TWO_ZONE_BARE_PA_PLUS_MODEL_ID, THREE_ZONE_BARE_PA_PLUS_MODEL_ID, SEGMENTED_THROUGH_EXIT_PA_PLUS_MODEL_ID}:
        raise ValueError("unsupported PA+ solution model")
    two_zone = model_id == TWO_ZONE_BARE_PA_PLUS_MODEL_ID
    segmented = model_id == SEGMENTED_THROUGH_EXIT_PA_PLUS_MODEL_ID
    bare = model_id in {TWO_ZONE_BARE_PA_PLUS_MODEL_ID, THREE_ZONE_BARE_PA_PLUS_MODEL_ID} or segmented
    expected_names = ["rod_common", "rod_differential", "repeller", "grid1"]
    if not two_zone:
        expected_names.append("intermediate2")
    expected_names.append("grid2")
    if not bare:
        expected_names.extend(["entrance_reference_sleeve", "entrance_plate"])
    modes, ids = model.get("modes"), model.get("mode_ids")
    if not isinstance(modes, list) or not isinstance(ids, list) or model.get("mode_count") != len(modes):
        raise ValueError("PA+ solution model modes are invalid")
    names = [item.get("name") if isinstance(item, Mapping) else None for item in modes]
    projected = names == expected_names[2:] and allow_post_pulse_projection
    if names != expected_names and not projected:
        raise ValueError("PA+ solution model named modes are invalid")
    policy = model.get("voltage_control_policy", {})
    expected_policy = "two_zone_linear_ring_interpolation_v1" if two_zone else "three_zone_linear_ring_interpolation_v1"
    if policy.get("policy_id") != expected_policy or policy.get("per_ring_independent_adjustment_supported") is not False:
        raise ValueError("PA+ solution model voltage policy is invalid")
    endpoint_ids = policy.get("independent_accelerator_electrode_ids")
    ring_ids = policy.get("derived_accelerator_ring_ids")
    if not isinstance(endpoint_ids, list) or len(endpoint_ids) != (3 if two_zone else 4) or not isinstance(ring_ids, list) or not ring_ids:
        raise ValueError("PA+ solution model electrode policy is invalid")
    grounds = [9, 10, 11] if segmented else [9]
    physical_ids = set(ROD_ELECTRODE_IDS) | set(grounds) | set(endpoint_ids) | set(ring_ids)
    if segmented:
        declared = model.get("physical_electrode_ids")
        all_ids = [*ROD_ELECTRODE_IDS, *grounds, *endpoint_ids, *ring_ids]
        groups = model.get("rod_electrical_groups")
        piece_counts = {row.get("physical_piece_count") for row in groups} if isinstance(groups, list) else set()
        if len(piece_counts) != 1 or any(type(count) is not int or count <= 0 for count in piece_counts):
            raise ValueError("segmented PA+ physical piece counts are invalid")
        expected_groups = [{"electrode_id": i, "electrode_group": 1 if i % 2 else 2,
                            "physical_piece_count": next(iter(piece_counts))} for i in ROD_ELECTRODE_IDS]
        if (len(all_ids) != len(physical_ids) or declared != sorted(physical_ids)
                or groups != expected_groups):
            raise ValueError("segmented PA+ physical electrode mapping is invalid")
    if not bare:
        physical_ids |= {int(endpoint_ids[-1]) + 1, int(endpoint_ids[-1]) + 2}
    first = max(physical_ids) + 1 if bare else 36
    expected_ids = list(range(first + (2 if projected else 0), first + len(expected_names)))
    if ids != expected_ids or [mode.get("mode_id") for mode in modes] != ids:
        raise ValueError("PA+ solution model IDs are invalid")
    shapes: dict[str, dict[int, float]] = {}
    for mode in modes:
        try:
            shape = {int(k): float(v) for k, v in mode["physical_electrode_coefficients"].items()}
            projection = {int(k): float(v) for k, v in mode["voltage_projection_coefficients"].items()}
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("PA+ solution model coefficients are invalid") from exc
        if not shape or not projection or any(not (v == v and abs(v) < float("inf")) for v in [*shape.values(), *projection.values()]):
            raise ValueError("PA+ solution model coefficients are non-finite or empty")
        name = mode["name"]
        if name in {"rod_common", "rod_differential"}:
            expected = {i: (1. if name == "rod_common" or i % 2 else -1.) for i in ROD_ELECTRODE_IDS}
            if shape != expected or projection != {i: v / 8 for i, v in expected.items()}:
                raise ValueError("PA+ rod symmetry coefficients are invalid")
        else:
            if len(projection) != 1 or list(projection.values()) != [1.]:
                raise ValueError("PA+ endpoint projection is invalid")
            own = next(iter(projection))
            if shape.get(own) != 1. or set(shape) - {own} - set(ring_ids) or any(v < 0. or v > 1. for v in shape.values()):
                raise ValueError("PA+ endpoint shape is invalid")
        shapes[name] = shape
    endpoint_names = [name for name in expected_names[2:] if name not in {"entrance_reference_sleeve", "entrance_plate"}]
    for ring in ring_ids:
        if abs(sum(shapes[name].get(ring, 0.) for name in endpoint_names) - 1.) > 1e-12:
            raise ValueError("PA+ ring partition is invalid")
    if model.get("grounded_physical_electrode_ids") != grounds:
        raise ValueError("PA+ grounded electrode policy is invalid")
    return dict(model)


def project_pa_plus_mode_voltages(
    model: Mapping[str, Any], physical_voltages_v: Mapping[int, float]
) -> dict[int, float]:
    """Project a complete physical electrode table onto a PA+ mode family.

    The v2 octupole model has two rod shapes: the all-rod common mode and the
    alternating-polarity differential mode.  Projecting and reconstructing
    the physical table here makes that reduction an explicit contract rather
    than a Program-only assumption.
    """
    model = require_pa_plus_solution_model(model)
    modes = model.get("modes")
    mode_ids = model.get("mode_ids")
    if (
        not isinstance(modes, list)
        or not isinstance(mode_ids, list)
        or model.get("mode_count") != len(modes)
        or len(modes) != len(mode_ids)
    ):
        raise ValueError("PA+ voltage projection modes are invalid")
    try:
        physical = {int(key): float(value) for key, value in physical_voltages_v.items()}
    except (TypeError, ValueError) as error:
        raise ValueError("PA+ physical voltages are invalid") from error
    if any(not (value == value and abs(value) < float("inf")) for value in physical.values()):
        raise ValueError("PA+ physical voltages are non-finite")

    if (model["model_id"] == SEGMENTED_THROUGH_EXIT_PA_PLUS_MODEL_ID
            and set(physical) != set(model["physical_electrode_ids"])):
        raise ValueError("PA+ physical electrode coverage must exactly match the declared electrical groups")
    if any(physical.get(int(i), 0.0) != 0.0 for i in model["grounded_physical_electrode_ids"]):
        raise ValueError("PA+ ground voltage must be zero")
    projected: dict[int, float] = {}
    reconstructed: dict[int, float] = {}
    for raw_mode in modes:
        if not isinstance(raw_mode, Mapping):
            raise ValueError("PA+ voltage projection mode is invalid")
        try:
            mode_id = int(raw_mode["mode_id"])
            shape = {
                int(key): float(value)
                for key, value in raw_mode["physical_electrode_coefficients"].items()
            }
            projection = {
                int(key): float(value)
                for key, value in raw_mode["voltage_projection_coefficients"].items()
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PA+ voltage projection mode is invalid") from error
        if not shape or not projection or not set(projection).issubset(physical):
            raise ValueError("PA+ voltage projection inputs are incomplete")
        value = sum(weight * physical[electrode_id] for electrode_id, weight in projection.items())
        projected[mode_id] = value
        for electrode_id, weight in shape.items():
            reconstructed[electrode_id] = reconstructed.get(electrode_id, 0.0) + weight * value
    if [int(value) for value in mode_ids] != list(projected):
        raise ValueError("PA+ voltage projection mode order is invalid")
    for electrode_id, actual in reconstructed.items():
        expected = physical.get(electrode_id)
        if expected is None or not abs(actual - expected) <= 1e-9:
            raise ValueError(
                "physical electrode voltages are outside the PA+ model subspace"
            )
    return projected


def resolve_post_pulse_pa_plus_solution_projection(
    model: Mapping[str, Any],
    *,
    rod_physical_electrode_ids: list[Any],
    upstream_rod_electrodes: list[Any],
    source_release_mode: str,
) -> dict[str, Any]:
    """Project a full PA+ model to the zero-rod post-pulse solution family.

    This is deliberately a runtime projection, not a new cache model.  The
    full PA+ family remains the authority for continuous flight.  A restart
    consumer may omit only modes whose physical electrodes are proved to stay
    at zero for its whole lifetime.  The upstream contract records the held
    pre-pulse DC common mode, whereas this restart has no upstream PA or RF
    kernel at all.  Keep both facts in the receipt: the former proves the
    physical rod namespace; ``pre_pulse_restart`` is the explicit runtime
    policy that makes the latter's effective values zero.
    """
    if source_release_mode != "pre_pulse_restart":
        raise ValueError("post-pulse PA+ projection requires a pre-pulse restart")
    model = require_pa_plus_solution_model(model)
    modes = model.get("modes")
    mode_ids = model.get("mode_ids")
    expected_count = {TWO_ZONE_BARE_PA_PLUS_MODEL_ID: 5, THREE_ZONE_BARE_PA_PLUS_MODEL_ID: 6,
                      THREE_ZONE_PA_PLUS_MODEL_ID: 8, SEGMENTED_THROUGH_EXIT_PA_PLUS_MODEL_ID: 6}[model["model_id"]]
    if (
        not isinstance(modes, list)
        or not isinstance(mode_ids, list)
        or model.get("mode_count") != expected_count
        or len(modes) != expected_count
        or len(mode_ids) != expected_count
    ):
        raise ValueError("post-pulse PA+ projection modes are invalid")
    try:
        rod_ids = {int(value) for value in rod_physical_electrode_ids}
        dc_by_id = {
            int(item["electrode_id"]): float(item["potential_V"])
            for item in upstream_rod_electrodes
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("post-pulse rod-voltage proof is invalid") from error
    if not rod_ids or set(dc_by_id) != rod_ids:
        raise ValueError("post-pulse rod-voltage proof does not cover every rod")
    effective_dc_by_id = {electrode_id: 0.0 for electrode_id in rod_ids}

    normalized_modes: list[dict[str, Any]] = []
    rod_mode_ids: list[int] = []
    for raw_mode in modes:
        if not isinstance(raw_mode, Mapping):
            raise ValueError("post-pulse PA+ projection mode is invalid")
        raw_coefficients = raw_mode.get("physical_electrode_coefficients")
        if not isinstance(raw_coefficients, Mapping):
            raise ValueError("post-pulse PA+ projection coefficients are invalid")
        try:
            mode_id = int(raw_mode["mode_id"])
            name = str(raw_mode["name"])
            coefficients = {
                int(electrode_id): float(weight)
                for electrode_id, weight in raw_coefficients.items()
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("post-pulse PA+ projection mode is invalid") from error
        if (
            len(coefficients) != len(raw_coefficients)
        ):
            raise ValueError("post-pulse PA+ projection coefficients are invalid")
        has_rod = any(electrode_id in rod_ids for electrode_id in coefficients)
        if has_rod:
            if name not in {"rod_common", "rod_differential"}:
                raise ValueError("post-pulse PA+ rod mode role is invalid")
            if set(coefficients) != rod_ids:
                raise ValueError("post-pulse PA+ rod mode basis is invalid")
            rod_mode_ids.append(mode_id)
        normalized_modes.append(dict(raw_mode))
    if len(rod_mode_ids) != 2:
        raise ValueError("post-pulse PA+ model does not contain both rod modes")
    if [int(value) for value in mode_ids] != [
        int(mode["mode_id"]) for mode in normalized_modes
    ]:
        raise ValueError("post-pulse PA+ source mode order is invalid")
    retained_modes = [
        mode for mode in normalized_modes
        if int(mode["mode_id"]) not in rod_mode_ids
    ]
    if len(retained_modes) != expected_count - 2:
        raise ValueError("post-pulse PA+ projection has an invalid non-rod mode count")
    projected_model = {
        **dict(model),
        "mode_ids": [int(mode["mode_id"]) for mode in retained_modes],
        "mode_count": len(retained_modes),
        "modes": retained_modes,
    }
    return {
        "schema_version": 1,
        "role": "rf_oatof_post_pulse_pa_plus_projection",
        "projection_id": POST_PULSE_FIELD_LOADING_POLICY_ID,
        "source_release_mode": source_release_mode,
        "rod_voltage_proof": {
            "policy_id": "pre_pulse_restart_rf_and_rod_dc_disabled_v1",
            "physical_electrode_ids": sorted(rod_ids),
            "upstream_static_voltages_v": {
                str(key): dc_by_id[key] for key in sorted(dc_by_id)
            },
            "effective_post_pulse_voltages_v": {
                str(key): effective_dc_by_id[key]
                for key in sorted(effective_dc_by_id)
            },
        },
        "omitted_mode_ids": rod_mode_ids,
        "projected_pa_plus_solution_model": projected_model,
    }


def _resolve_linear_ring_pa_plus_solution_model(
    electrodes: Mapping[str, Any],
    *,
    planes_global_z_mm: Mapping[str, Any],
    ring_z_mm: list[Any],
    two_zone_bare: bool,
    acceleration_direction: int = 1,
    three_zone_bare: bool = False,
    segmented_through_exit: bool = False,
) -> dict[str, Any]:
    """Derive the exact PA+ projection for a three-zone linear ring stack.

    Physical electrode IDs remain the complete frontend namespace.  The PA+
    solution IDs are a separate, compact namespace: only voltage degrees of
    freedom that are independent under the frozen three-zone voltage law own a
    solution array.  Each ring is represented by the two enclosing endpoint
    modes with coefficients that sum to one.
    """
    topology = (dict(topology_id="segmented_through_exit", maximum_electrode_id=max(_flatten_electrode_ids(electrodes)))
                if segmented_through_exit else resolve_frontend_electrode_topology(electrodes))
    bare = two_zone_bare or three_zone_bare or segmented_through_exit
    accepted = {THREE_ZONE_BARE_VARIANT} if three_zone_bare else {TWO_ZONE_BARE_VARIANT} if two_zone_bare else {
        "three_zone_frontend_v1", "three_zone_frontend_contract_derived_v1"
    }
    if segmented_through_exit:
        accepted = {"segmented_through_exit"}
    if topology["topology_id"] not in accepted:
        raise ValueError("PA+ solution model requires a three-zone frontend")
    required_planes = ({"repeller", "grid1", "exit"} if two_zone_bare else
                       {"repeller", "grid1", "intermediate2", "exit"} if three_zone_bare or segmented_through_exit else
                       {"repeller", "intermediate1", "intermediate2", "exit"})
    if set(planes_global_z_mm) != required_planes:
        raise ValueError("PA+ solution model requires exactly four accelerator planes")
    if type(acceleration_direction) is not int or acceleration_direction not in (-1, 1):
        raise ValueError("PA+ acceleration direction must be +1 or -1")
    # Use a signed longitudinal coordinate only while computing interpolation.
    # Callers continue to own and freeze the actual world-z plane positions.
    planes = {name: acceleration_direction * float(planes_global_z_mm[name]) for name in required_planes}
    first_grid = "grid1" if bare else "intermediate1"
    ordered_planes = ("repeller", "grid1", "exit") if two_zone_bare else ("repeller", first_grid, "intermediate2", "exit")
    if not all(value == value and abs(value) < float("inf") for value in planes.values()) or not all(
        planes[left] < planes[right] for left, right in zip(ordered_planes, ordered_planes[1:])
    ):
        raise ValueError("PA+ solution model planes are invalid")
    ring_ids = [int(value) for value in electrodes["accelerator_ring_ids"]]
    if len(ring_z_mm) != len(ring_ids):
        raise ValueError("PA+ solution model ring positions do not match electrode IDs")

    alternating_polarity = {
        electrode_id: 1.0 if electrode_id % 2 else -1.0
        for electrode_id in ROD_ELECTRODE_IDS
    }
    first_mode_id = topology["maximum_electrode_id"] + 1 if bare else 36
    modes = [
        {
            "mode_id": first_mode_id,
            "name": "rod_common",
            "physical_electrode_coefficients": {
                str(electrode_id): 1.0 for electrode_id in ROD_ELECTRODE_IDS
            },
            "voltage_projection_coefficients": {
                str(electrode_id): 1.0 / len(ROD_ELECTRODE_IDS)
                for electrode_id in ROD_ELECTRODE_IDS
            },
        },
        {
            "mode_id": first_mode_id + 1,
            "name": "rod_differential",
            "physical_electrode_coefficients": {
                str(electrode_id): polarity
                for electrode_id, polarity in alternating_polarity.items()
            },
            "voltage_projection_coefficients": {
                str(electrode_id): polarity / len(ROD_ELECTRODE_IDS)
                for electrode_id, polarity in alternating_polarity.items()
            },
        },
    ]
    endpoints = [
        ("repeller", int(electrodes["accelerator_repeller_id"])),
        ("grid1", int(electrodes["accelerator_grid1_id"])),
    ]
    if not two_zone_bare:
        endpoints.append(("intermediate2", int(electrodes["accelerator_intermediate2_id"])))
    endpoints.append(("grid2", int(electrodes["accelerator_grid2_id"])))
    if not bare:
        endpoints.extend([
            ("entrance_reference_sleeve", int(electrodes["entrance_reference_sleeve_id"])),
            ("entrance_plate", int(electrodes["entrance_plate_id"])),
        ])
    for index, (name, electrode_id) in enumerate(endpoints, start=first_mode_id + 2):
        modes.append(
            {
                "mode_id": index,
                "name": name,
                "physical_electrode_coefficients": {str(electrode_id): 1.0},
                "voltage_projection_coefficients": {str(electrode_id): 1.0},
            }
        )
    by_name = {mode["name"]: mode for mode in modes}
    for ring_id, raw_z in zip(ring_ids, ring_z_mm):
        z = acceleration_direction * float(raw_z)
        if not (z == z and abs(z) < float("inf")):
            raise ValueError("PA+ solution model ring position is invalid")
        if two_zone_bare and planes["grid1"] < z < planes["exit"]:
            left, right = "grid1", "grid2"
            z0, z1 = planes["grid1"], planes["exit"]
        elif two_zone_bare:
            raise ValueError("PA+ solution model ring is outside its two-zone interval")
        elif planes[first_grid] < z < planes["intermediate2"]:
            left, right = "grid1", "intermediate2"
            z0, z1 = planes[first_grid], planes["intermediate2"]
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
        "model_id": (SEGMENTED_THROUGH_EXIT_PA_PLUS_MODEL_ID if segmented_through_exit else
                     TWO_ZONE_BARE_PA_PLUS_MODEL_ID if two_zone_bare else
                     THREE_ZONE_BARE_PA_PLUS_MODEL_ID if three_zone_bare else THREE_ZONE_PA_PLUS_MODEL_ID),
        "field_loading_policy_id": PA_PLUS_FIELD_LOADING_POLICY_ID,
        # This is deliberately part of the frozen model, rather than an
        # incidental implementation detail.  The existing three-zone Program
        # computes every ring from these four plane voltages; PA+ removes only
        # those already-derived degrees of freedom.  A future per-ring tuning
        # study must select a different model (and therefore a different PA
        # cache identity), not silently reuse this one.
        "voltage_control_policy": {
            "policy_id": "two_zone_linear_ring_interpolation_v1" if two_zone_bare else "three_zone_linear_ring_interpolation_v1",
            "independent_accelerator_electrode_ids": [
                int(electrodes["accelerator_repeller_id"]),
                int(electrodes["accelerator_grid1_id"]),
                *([] if two_zone_bare else [int(electrodes["accelerator_intermediate2_id"])]),
                int(electrodes["accelerator_grid2_id"]),
            ],
            "derived_accelerator_ring_ids": ring_ids,
            "per_ring_independent_adjustment_supported": False,
        },
        "rod_voltage_control_policy": {
            "policy_id": "octupole_common_plus_alternating_differential_v1",
            "physical_electrode_ids": list(ROD_ELECTRODE_IDS),
            "common_mode_name": "rod_common",
            "differential_mode_name": "rod_differential",
        },
        "mode_ids": [mode["mode_id"] for mode in modes],
        "mode_count": len(modes),
        "modes": modes,
        "grounded_physical_electrode_ids": ([9, 10, 11] if segmented_through_exit else
                                             [int(electrodes["grounded_shield_id"])]),
    }



def segmented_through_exit_rod_pieces(upstream: Mapping[str, Any]) -> list[dict]:
    """Validate all provider rod pieces for the supported four-segment topology.

    Electrical IDs identify segment/RF groups, not individual physical rods.
    The provider's parent rods determine how many pieces share each group.
    """
    segmented = upstream["segmentation"]["segmented_rod_array"]
    parents = upstream["geometry_mm"]["rod_array"]["rods"]
    parent_groups = {row["rod_id"]: row["electrode_group"] for row in parents}
    count = upstream["identity"]["electrode_count"]
    if (segmented["segment_count"] != 4 or segmented["electrode_count_per_segment"] != count
            or len(parents) != count or len(parent_groups) != count
            or set(parent_groups.values()) != {1, 2}
            or sum(group == 1 for group in parent_groups.values()) * 2 != count):
        raise ValueError("segmented through-exit requires four segments of the complete two-RF-group provider rods")
    pieces = segmented["electrodes"]
    expected = {(segment, rod) for segment in range(1, 5) for rod in parent_groups}
    if len(pieces) != len(expected) or {(row["segment_id"], row["parent_rod_id"]) for row in pieces} != expected:
        raise ValueError("segmented through-exit requires every unique segment/parent rod piece")
    for row in pieces:
        group = parent_groups[row["parent_rod_id"]]
        if row["electrode_group"] != group or row["electrode_id"] != 2 * (row["segment_id"] - 1) + group:
            raise ValueError(f"conflicting provider RF group for electrode {row['electrode_id']}: "
                             f"segment {row['segment_id']} parent rod {row['parent_rod_id']}")
    return pieces


def resolve_segmented_through_exit_pa_plus_solution_model(
    upstream: Mapping[str, Any], *, multipole_electrode_ids: Mapping[int, int],
    accelerator_electrodes: Mapping[str, Any], planes_global_z_mm: Mapping[str, Any],
    ring_z_mm: list[Any],
) -> dict[str, Any]:
    """Compile six voltage modes for four multipole segments and a three-zone OA.

    Native electrical groups 1..8 retain all provider rod pieces; the actual entrance
    shield, exit cap and OA shield remain separate groups 9, 10 and 11. This
    model holds those three groups at zero and supports only common/differential
    rod voltages, not independent axial segment tuning. No field is generated.
    """
    if (upstream.get("role") != "multipole_resolved_design_do_not_edit"
            or upstream["geometry_mm"]["enclosure"]["model"] != "cylindrical_grounded_shield_through_exit_v1"
            or dict(multipole_electrode_ids) != {i: i for i in range(1, 11)}
            or accelerator_electrodes["grounded_shield_id"] != 11):
        raise ValueError("segmented through-exit PA+ requires explicit native groups 1..10 and OA shield 11")
    static = upstream["static_electrodes_V"]
    for name in ("shield_entrance_outer_endcap_aperture_plate_connector_V",
                 "exit_outer_endcap_aperture_plate_connector_V"):
        if float(static[name]) != 0.:
            raise ValueError(f"PA+ ground voltage must be zero: static_electrodes_V.{name}")
    pieces = segmented_through_exit_rod_pieces(upstream)
    groups: dict[int, tuple[int, float]] = {}
    counts: dict[int, int] = {}
    for row in pieces:
        eid, group, common = int(row["electrode_id"]), int(row["electrode_group"]), float(row["common_mode_V"])
        if eid in groups and groups[eid] != (group, common):
            raise ValueError(f"conflicting segmented physical pieces for electrode {eid}")
        if eid not in ROD_ELECTRODE_IDS or group != (1 if eid % 2 else 2):
            raise ValueError(f"segmented electrode {eid} has unsupported RF group {group}")
        groups[eid] = group, common
        counts[eid] = counts.get(eid, 0) + 1
    if counts != dict.fromkeys(ROD_ELECTRODE_IDS, upstream["identity"]["electrode_count"] // 2):
        raise ValueError("segmented PA+ electrical groups must cover all provider rod pieces")
    electrodes = dict(accelerator_electrodes, multipole_rod_ids=list(ROD_ELECTRODE_IDS),
                      multipole_shield_id=9, multipole_exit_cap_id=10)
    basis_ids = _flatten_electrode_ids(electrodes)
    if basis_ids[0] != 0:
        raise ValueError("segmented PA+ electrical IDs must be positive")
    physical_ids = list(basis_ids[1:])
    model = _resolve_linear_ring_pa_plus_solution_model(
        electrodes, planes_global_z_mm=planes_global_z_mm, ring_z_mm=ring_z_mm,
        two_zone_bare=False, segmented_through_exit=True,
    )
    model.update(physical_electrode_ids=physical_ids, rod_electrical_groups=[
        dict(electrode_id=eid, electrode_group=groups[eid][0], physical_piece_count=counts[eid])
        for eid in ROD_ELECTRODE_IDS])
    physical = dict.fromkeys(physical_ids, 0.)
    differential_dc = float(upstream["drive"]["dc_amplitude_V_per_group"])
    for eid, (group, common) in groups.items():
        physical[eid] = common + (differential_dc if group == 1 else -differential_dc)
    project_pa_plus_mode_voltages(model, physical)
    return model


def resolve_three_zone_pa_plus_solution_model(
    electrodes: Mapping[str, Any], *, planes_global_z_mm: Mapping[str, Any], ring_z_mm: list[Any],
) -> dict[str, Any]:
    """Preserve the published three-zone model and its solution IDs."""
    return _resolve_linear_ring_pa_plus_solution_model(
        electrodes, planes_global_z_mm=planes_global_z_mm, ring_z_mm=ring_z_mm, two_zone_bare=False,
    )


def resolve_two_zone_bare_pa_plus_solution_model(
    electrodes: Mapping[str, Any], *, planes_global_z_mm: Mapping[str, Any], ring_z_mm: list[Any],
    acceleration_direction: int = 1,
) -> dict[str, Any]:
    """Derive five modes for eight continuous rods and a bare two-zone OA."""
    return _resolve_linear_ring_pa_plus_solution_model(
        electrodes, planes_global_z_mm=planes_global_z_mm, ring_z_mm=ring_z_mm, two_zone_bare=True,
        acceleration_direction=acceleration_direction,
    )


def render_pa_plus_solution_model(model: Mapping[str, Any]) -> str:
    """Render the official SIMION PA+ electrode-to-solution projection."""
    model = require_pa_plus_solution_model(model, allow_post_pulse_projection=True)
    modes = model.get("modes")
    mode_ids = model.get("mode_ids")
    if (
        not isinstance(modes, list)
        or not isinstance(mode_ids, list)
        or not modes
        or len(modes) != len(mode_ids)
        or model.get("mode_count") != len(modes)
    ):
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
def frontend_electrodes(*, ring_count: int, three_zone: bool, variant: str | None = None) -> dict[str, Any]:
    """Derive the contiguous PA electrode namespace from the ring contract."""
    if (variant not in {None, TWO_ZONE_BARE_VARIANT, THREE_ZONE_BARE_VARIANT}
            or (variant == TWO_ZONE_BARE_VARIANT and three_zone)
            or (variant == THREE_ZONE_BARE_VARIANT and not three_zone)):
        raise ValueError("frontend electrode variant is unsupported for this topology")
    if isinstance(ring_count, bool) or not isinstance(ring_count, int) or ring_count < 1:
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
    if variant in {TWO_ZONE_BARE_VARIANT, THREE_ZONE_BARE_VARIANT}:
        del result["entrance_reference_sleeve_id"]
        del result["entrance_plate_id"]
    if three_zone:
        result["accelerator_intermediate2_id"] = grid2_id + (1 if variant == THREE_ZONE_BARE_VARIANT else 3)
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


def resolve_three_zone_bare_pa_plus_solution_model(
    electrodes: Mapping[str, Any], *, planes_global_z_mm: Mapping[str, Any], ring_z_mm: list[Any],
    acceleration_direction: int = 1,
) -> dict[str, Any]:
    """Derive six real modes, without adding a sleeve or entrance plate."""
    return _resolve_linear_ring_pa_plus_solution_model(
        electrodes, planes_global_z_mm=planes_global_z_mm, ring_z_mm=ring_z_mm,
        two_zone_bare=False, three_zone_bare=True, acceleration_direction=acceleration_direction,
    )


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
    bare = "entrance_reference_sleeve_id" not in electrodes and "entrance_plate_id" not in electrodes
    bare_variant = THREE_ZONE_BARE_VARIANT if three_zone else TWO_ZONE_BARE_VARIANT
    expected = frontend_electrodes(ring_count=len(ring_ids), three_zone=three_zone, variant=bare_variant if bare else None)
    if electrodes != expected:
        raise ValueError("frontend electrodes do not match the derived topology")
    matches = [
        topology_id
        for topology_id, published in PUBLISHED_ELECTRODE_TOPOLOGIES.items()
        if electrodes == published
    ]
    topology_id = (
        bare_variant if bare else matches[0] if len(matches) == 1 else
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
