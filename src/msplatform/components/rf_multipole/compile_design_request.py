"""Compile already-read RF design documents; no author paths or execution."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from msplatform.contracts.machine_contracts import ContractError, validate_schema
from msplatform.components.rf_multipole.axial_acceleration import MODEL_ID, NEUTRAL_MODEL_ID, AxialAccelerationError, resolve_axial_acceleration, segment_rod_array
from msplatform.components.rf_multipole.connector_geometry import CONNECTOR_SHAPES
from msplatform.components.rf_multipole.interface_geometry import InterfaceGeometryError, build_axial_interface_layout, build_enclosure_layout
from msplatform.components.rf_multipole.round_rod_geometry import RoundRodGeometryError, build_round_rod_array

# Serialized compiler identity is preserved; it is not an import path.
COMPILER_NAME = "common.multipole.compile_design_request"
COMPILER_VERSION = 3
REQUEST_SCHEMA = "multipole_design_request.schema.json"
RESOLVED_SCHEMA = "multipole_resolved_design.schema.json"
GEOMETRY_EQUALITY_ABS_TOL_MM = 1e-12

def _version_schema(document: Mapping[str, Any], *, resolved: bool) -> str:
    version = document.get("schema_version")
    if type(version) is not int or version not in (3, 4):
        raise MultipoleDesignCompileError("unsupported multipole contract schema_version")
    stem = "multipole_resolved_design" if resolved else "multipole_design_request"
    return stem + ("_v4" if version == 4 else "") + ".schema.json"


def validate_design_request(document: Mapping[str, Any]) -> None:
    """Validate an explicitly versioned author contract, without compiling it."""
    validate_schema(dict(document), _version_schema(document, resolved=False))


def validate_resolved_design_contract(document: Mapping[str, Any]) -> None:
    """Validate version combinations only; provenance recompilation is separate."""
    validate_schema(dict(document), _version_schema(document, resolved=True))
    version = document["schema_version"]
    segmentation = document["segmentation"]
    axial, array = segmentation["axial_acceleration"], segmentation["segmented_rod_array"]
    if segmentation["strategy"] == "off":
        if axial is not None or array is not None:
            raise MultipoleDesignCompileError("continuous topology cannot contain segmented contracts")
        return
    if (not isinstance(axial, dict) or not isinstance(array, dict)
            or type(axial.get("schema_version")) is not int
            or axial["schema_version"] != (2 if version == 3 else 3)
            or axial.get("model_id") != (MODEL_ID if version == 3 else NEUTRAL_MODEL_ID)
            or type(array.get("schema_version")) is not int
            or array["schema_version"] != (1 if version == 3 else 2)):
        raise MultipoleDesignCompileError("mixed multipole resolved/axial/segment contract versions")
    if version == 4 and any("electrode_id" in member for member in array["electrodes"]):
        raise MultipoleDesignCompileError("neutral segment contract cannot contain native electrode_id")


class MultipoleDesignCompileError(ContractError):
    """Raised when a design request cannot be compiled deterministically."""


def canonical_sha256(document: Any) -> str:
    """Return the uppercase SHA-256 of canonical compact JSON."""
    try:
        payload = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MultipoleDesignCompileError("document is not canonical finite JSON") from error
    return hashlib.sha256(payload).hexdigest().upper()


def resolved_design_sha256(document: Mapping[str, Any]) -> str:
    """Hash a resolved design without its self-identifying hash field."""
    payload = copy.deepcopy(dict(document))
    payload.pop("resolved_sha256", None)
    return canonical_sha256(payload)


def _ensure_finite_numbers(value: Any, location: str = "<root>") -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise MultipoleDesignCompileError(f"{location} must be finite")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _ensure_finite_numbers(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _ensure_finite_numbers(item, f"{location}[{index}]")


def _normalize_expected_identity(expected_identity: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "project_id",
        "family_id",
        "radial_order_n",
        "electrode_count",
    }
    if set(expected_identity) != required:
        raise MultipoleDesignCompileError(
            "expected identity fields differ: "
            f"missing={sorted(required - set(expected_identity))}, "
            f"unknown={sorted(set(expected_identity) - required)}"
        )
    normalized = {
        "project_id": expected_identity["project_id"],
        "family_id": expected_identity["family_id"],
        "radial_order_n": expected_identity["radial_order_n"],
        "electrode_count": expected_identity["electrode_count"],
    }
    if not isinstance(normalized["project_id"], str) or not normalized["project_id"]:
        raise MultipoleDesignCompileError("expected project_id must be a nonempty string")
    if normalized["family_id"] != "rf_multipole_ion_optics":
        raise MultipoleDesignCompileError("expected family_id is not the RF multipole family")
    order = normalized["radial_order_n"]
    count = normalized["electrode_count"]
    if (
        not isinstance(order, int)
        or isinstance(order, bool)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or order < 2
        or count != 2 * order
    ):
        raise MultipoleDesignCompileError(
            "expected electrode_count must equal twice radial_order_n"
        )
    return normalized


def _validate_enclosure(
    enclosure: Mapping[str, Any],
    interfaces: Mapping[str, Any],
    rod_array: Mapping[str, Any],
) -> dict[str, Any]:
    values = [
        value
        for key, value in enclosure.items()
        if key not in {"model", "role"}
    ]
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in values
    ):
        raise MultipoleDesignCompileError("enclosure dimensions must be finite numbers")
    vacuum_min = float(enclosure["vacuum_z_min_mm"])
    vacuum_max = float(enclosure["vacuum_z_max_mm"])
    if vacuum_max <= vacuum_min:
        raise MultipoleDesignCompileError("enclosure vacuum z range must be increasing")
    interface_planes = {
        "entrance release": interfaces["entrance"]["release_plane_z_mm"],
        "exit census": interfaces["exit"]["census_plane_z_mm"],
    }
    for label, plane_value in interface_planes.items():
        plane = float(plane_value)
        if not (
            vacuum_min - GEOMETRY_EQUALITY_ABS_TOL_MM
            <= plane
            <= vacuum_max + GEOMETRY_EQUALITY_ABS_TOL_MM
        ):
            raise MultipoleDesignCompileError(
                f"{label} plane must remain inside the explicit vacuum z range"
            )
    working_region_radius = float(enclosure["working_region_radius_mm"])
    if working_region_radius <= 0:
        raise MultipoleDesignCompileError("working region radius must be positive")
    for side in ("entrance", "exit"):
        if (
            float(interfaces[side]["aperture_radius_mm"])
            > working_region_radius + GEOMETRY_EQUALITY_ABS_TOL_MM
        ):
            raise MultipoleDesignCompileError(
                f"{side} aperture radius exceeds the working region radius"
            )

    model = enclosure["model"]
    role = enclosure["role"]
    if model == "rectangular_reference_enclosure_v1":
        if role != "downstream_local_reference_enclosure":
            raise MultipoleDesignCompileError("rectangular enclosure role differs")
        inner = float(enclosure["inner_half_width_mm"])
        outer = float(enclosure["outer_half_width_mm"])
        exit_min = float(enclosure["exit_enclosure_z_min_mm"])
        front_end = float(enclosure["exit_front_wall_end_z_mm"])
        exit_max = float(enclosure["exit_enclosure_z_max_mm"])
        if not 0 < inner < outer:
            raise MultipoleDesignCompileError(
                "rectangular enclosure half-widths must be positive and increasing"
            )
        if not vacuum_min <= exit_min < front_end <= exit_max <= vacuum_max:
            raise MultipoleDesignCompileError(
                "rectangular exit enclosure must be ordered inside the vacuum z range"
            )
        transverse_limit = outer
        rod_extent = None
    else:
        raise MultipoleDesignCompileError(f"unsupported enclosure model: {model}")
    tolerance = GEOMETRY_EQUALITY_ABS_TOL_MM
    radial_values = {
        "working region": float(enclosure["working_region_radius_mm"]),
        "entrance aperture": float(interfaces["entrance"]["aperture_radius_mm"]),
        "exit aperture": float(interfaces["exit"]["aperture_radius_mm"]),
    }
    if rod_extent is not None:
        radial_values["rod outer extent"] = rod_extent
    for label, value in radial_values.items():
        if value > transverse_limit + tolerance:
            raise MultipoleDesignCompileError(
                f"{label} exceeds the explicit enclosure transverse vacuum limit"
            )
    return copy.deepcopy(dict(enclosure))


def _validate_current_geometry(geometry: Mapping[str, Any], rod_array: Mapping[str, Any]) -> tuple:
    enclosure = copy.deepcopy(geometry.get("enclosure", {"model": "bare"}))
    domain = copy.deepcopy(geometry["numerical_domain"])
    observations = copy.deepcopy(geometry["observations"])
    low, high = float(domain["z_min_mm"]), float(domain["z_max_mm"])
    if high <= low:
        raise MultipoleDesignCompileError("numerical domain axial bounds must increase")
    rods = rod_array["rods"]
    radial_extent = max(math.hypot(float(r["center_x_mm"]), float(r["center_y_mm"])) + float(r["radius_mm"]) for r in rods)
    if radial_extent >= float(domain["radius_mm"]):
        raise MultipoleDesignCompileError("rod metal must fit inside the numerical domain")
    if not low <= float(geometry["rod_z_min"]) < float(geometry["rod_z_max"]) <= high:
        raise MultipoleDesignCompileError("rod axial span must fit inside the numerical domain")
    if not observations["acceptance_radius_mm"] <= domain["working_region_radius_mm"] <= domain["radius_mm"]:
        raise MultipoleDesignCompileError("observation and working radii must fit inside the numerical domain")
    if not low <= observations["release_plane_z_mm"] < observations["handoff_plane_z_mm"] <= observations["census_plane_z_mm"] <= high:
        raise MultipoleDesignCompileError("release, handoff and census planes must be ordered inside the numerical domain")
    layout = build_enclosure_layout(geometry)
    for body in layout["bodies"]:
        if not (low <= body["z_min_mm"] < body["z_max_mm"] <= high and body["outer_radius_mm"] <= domain["radius_mm"]):
            raise MultipoleDesignCompileError("physical enclosure must fit inside the numerical domain")
        if body["role"] == "shell":
            if radial_extent >= body["inner_radius_mm"]:
                raise MultipoleDesignCompileError("rod metal intersects the shell")
        elif (max(body["z_min_mm"], float(geometry["rod_z_min"])) <= min(body["z_max_mm"], float(geometry["rod_z_max"]))
              and body["inner_radius_mm"] <= radial_extent):
            raise MultipoleDesignCompileError("endcap intersects the rod metal")
    return enclosure, domain, observations, layout


def _resolve_segmentation(
    request: Mapping[str, Any],
    rod_array: dict[str, Any],
) -> dict[str, Any]:
    segmentation = request["segmentation"]
    strategy = segmentation["strategy"]
    if strategy == "off":
        return {
            "strategy": "off",
            "axial_acceleration": None,
            "segmented_rod_array": None,
        }

    identity = request["identity"]
    particle = request["particle_source"]
    source_segmentation = {
        key: copy.deepcopy(value)
        for key, value in segmentation.items()
        if key != "output_reference_V"
    }
    if source_segmentation["strategy"] == "uniform":
        rod_exit_reference = source_segmentation["exit_common_mode_V"]
    else:
        rod_exit_reference = source_segmentation["segments"][-1]["common_mode_V"]
    if (
        request["axial_drive"]["topology"] == "segmented_rod_axial_acceleration"
        and not math.isclose(
            float(segmentation["output_reference_V"]),
            float(rod_exit_reference),
            rel_tol=0,
            abs_tol=1e-12,
        )
    ):
        raise MultipoleDesignCompileError(
            "segmented acceleration output reference must equal the final rod segment"
        )
    axial_contract = {
        "schema_version": 2 if request["schema_version"] == 3 else 3,
        "role": "multipole_axial_acceleration_contract",
        "project_id": identity["project_id"],
        "model_id": MODEL_ID if request["schema_version"] == 3 else NEUTRAL_MODEL_ID,
        "segmentation": source_segmentation,
        # The segmented-rod helper ends at the final rod segment.  The request-level
        # output_reference_V is the actual downstream terminal and may differ for a
        # terminal potential-step topology.
        "output_reference_V": rod_exit_reference,
        "functional_acceptance": {
            "minimum_transmission": 0.0,
            "minimum_mean_energy_gain_eV": 0.0,
            "maximum_mean_output_energy_error_eV": 0.0,
        },
        "claim_limit": "Compiled geometry and voltage contract only; no functional claim.",
    }
    axial_resolved = resolve_axial_acceleration(
        axial_contract,
        rod_z_min_mm=rod_array["rods"][0]["z_min_mm"],
        rod_z_max_mm=rod_array["rods"][0]["z_max_mm"],
        source_kinetic_energy_ev=_nominal_source_energy(particle),
        charge_state=particle["charge_state"],
        require_positive_energy_gain=(
            request["axial_drive"]["topology"]
            == "segmented_rod_axial_acceleration"
        ),
    )
    axial_resolved.pop("functional_acceptance", None)
    axial_resolved.pop("claim_limit", None)
    return {
        "strategy": strategy,
        "axial_acceleration": axial_resolved,
        "segmented_rod_array": segment_rod_array(rod_array, axial_resolved),
    }


def _static_reference_voltages(
    request: Mapping[str, Any],
) -> tuple[float, float]:
    """Return the canonical entrance and output static-boundary references."""
    static = request["static_electrodes_V"]
    model = request["geometry_mm"].get("enclosure", {"model": "bare"})["model"]
    if model == "rectangular_reference_enclosure_v1":
        source = float(static["entrance_aperture_plate_and_connector_V"])
        output = float(static["exit_outer_enclosure_and_connector_V"])
    elif model == "cylindrical_grounded_shell":
        source = output = float(static["ground_V"])
    elif model == "bare":
        source = output = float(request["drive"]["common_mode_offset_V"])
    else:  # Kept fail-closed even though enclosure validation rejects this first.
        raise MultipoleDesignCompileError(
            f"cannot resolve static references for enclosure model: {model}"
        )
    return source, output


def _nominal_source_energy(particle: Mapping[str, Any]) -> float:
    model = particle["energy_model"]
    if model["kind"] == "monoenergetic":
        return float(model["kinetic_energy_eV"])
    minimum = float(model["minimum_energy_eV"])
    maximum = float(model["maximum_energy_eV"])
    nominal = float(model["nominal_energy_eV"])
    if minimum > maximum:
        raise MultipoleDesignCompileError(
            "bounded source minimum energy exceeds maximum energy"
        )
    if not minimum <= nominal <= maximum:
        raise MultipoleDesignCompileError(
            "bounded source nominal energy is outside its closed interval"
        )
    return nominal


def _resolve_axial_drive(
    request: Mapping[str, Any],
    segmentation: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve one explicit axial-field topology from canonical request fields."""
    topology = request["axial_drive"]["topology"]

    segmented = segmentation["strategy"] != "off"
    rod_reference = float(request["drive"]["common_mode_offset_V"])
    if segmented and topology in {
        "none",
        "exit_aperture_plate_potential_step",
    }:
        segment_voltages = [
            float(segment["common_mode_V"])
            for segment in segmentation["axial_acceleration"]["derived"]["segments"]
        ]
        if not all(
            math.isclose(voltage, rod_reference, rel_tol=0, abs_tol=1e-12)
            for voltage in segment_voltages
        ):
            raise MultipoleDesignCompileError(
                f"{topology} requires every physical rod segment common mode "
                "to equal drive common_mode_offset_V"
            )
    if topology == "segmented_rod_axial_acceleration":
        if not segmented:
            raise MultipoleDesignCompileError(
                "segmented_rod_axial_acceleration requires rod segmentation"
            )
        resolved_acceleration = segmentation["axial_acceleration"]
        source_reference = float(
            resolved_acceleration["derived"]["segments"][0]["common_mode_V"]
        )
        output_reference = float(resolved_acceleration["output_reference_V"])
    elif topology == "exit_aperture_plate_potential_step":
        _, output_reference = _static_reference_voltages(request)
        source_reference = rod_reference
        static = request["static_electrodes_V"]
        if (
            request["geometry_mm"]["enclosure"]["model"]
            == "rectangular_reference_enclosure_v1"
            and not math.isclose(
                float(static["physical_detector_V"]),
                output_reference,
                rel_tol=0,
                abs_tol=1e-12,
            )
        ):
            raise MultipoleDesignCompileError(
                "rectangular physical detector must share the exit aperture-plate output reference"
            )
    elif topology == "none":
        source_reference, output_reference = _static_reference_voltages(request)
        if segmented and not math.isclose(
            source_reference,
            output_reference,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise MultipoleDesignCompileError(
                "axial-drive topology none requires identical static references"
            )
    else:
        raise MultipoleDesignCompileError(
            f"unsupported axial-drive topology: {topology}"
        )

    particle = request["particle_source"]
    energy_gain = int(particle["charge_state"]) * (
        source_reference - output_reference
    )
    if topology != "none" and energy_gain <= 0:
        raise MultipoleDesignCompileError(
            "axial-drive potential profile does not accelerate the selected charge sign"
        )
    return {
        "topology": topology,
        "source_reference_V": source_reference,
        "output_reference_V": output_reference,
        "predicted_energy_gain_eV": energy_gain,
        "predicted_output_energy_eV": _nominal_source_energy(particle) + energy_gain,
    }


def compile_design_request(
    request: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any],
    source_records: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Compile a document with externally verified provenance records.

    Read-only bundled schemas are used for validation. No author files,
    registry, source sampling or solver are accessed; inputs are not modified.
    """
    request_document = copy.deepcopy(dict(request))
    try:
        validate_design_request(request_document)
    except ContractError as error:
        raise MultipoleDesignCompileError(str(error)) from error
    _ensure_finite_numbers(request_document)
    _nominal_source_energy(request_document["particle_source"])

    locked_identity = _normalize_expected_identity(expected_identity)
    if request_document["identity"] != locked_identity:
        raise MultipoleDesignCompileError(
            "request identity differs from the immutable expected project identity"
        )
    order = locked_identity["radial_order_n"]
    count = locked_identity["electrode_count"]
    if count != 2 * order:
        raise MultipoleDesignCompileError(
            "request electrode_count must equal twice radial_order_n"
        )

    geometry = request_document["geometry_mm"]
    static_electrodes = request_document["static_electrodes_V"]
    enclosure_model = geometry.get("enclosure", {"model": "bare"})["model"]
    expected_static_role = {
        "rectangular_reference_enclosure_v1": "rectangular_reference_static_electrodes",
        "cylindrical_grounded_shell": "grounded_shell_static_electrodes",
        "bare": "bare_multipole_static_electrodes",
    }[enclosure_model]
    if static_electrodes["role"] != expected_static_role:
        raise MultipoleDesignCompileError(
            "static-electrode topology differs from the enclosure topology"
        )
    z_min = float(geometry["rod_z_min"])
    z_max = float(geometry["rod_z_max"])
    r0 = float(geometry["inscribed_radius_r0"])
    ratio = float(geometry["rod_radius_ratio"])
    rod_radius = r0 * ratio
    try:
        rod_array = build_round_rod_array(
            radial_order_n=order,
            electrode_count=count,
            inscribed_radius_r0_mm=r0,
            rod_radius_mm=rod_radius,
            rod_z_min_mm=z_min,
            rod_z_max_mm=z_max,
            orientation_rad=float(request_document["coordinate"]["orientation_rad"]),
        )
        interfaces = None
        if enclosure_model == "rectangular_reference_enclosure_v1":
            for side in ("entrance_interface", "exit_interface"):
                if geometry[side]["connector_shape"] not in CONNECTOR_SHAPES:
                    raise MultipoleDesignCompileError(f"{side} connector shape is unsupported")
            interfaces = build_axial_interface_layout(
                rod_z_min_mm=z_min, rod_z_max_mm=z_max,
                entrance=geometry["entrance_interface"], exit_interface=geometry["exit_interface"],
            )
            enclosure = _validate_enclosure(geometry["enclosure"], interfaces, rod_array)
        else:
            enclosure, domain, observations, layout = _validate_current_geometry(geometry, rod_array)
        segmentation = _resolve_segmentation(request_document, rod_array)
        axial_drive = _resolve_axial_drive(request_document, segmentation)
    except MultipoleDesignCompileError:
        raise
    except (
        AxialAccelerationError,
        InterfaceGeometryError,
        RoundRodGeometryError,
    ) as error:
        raise MultipoleDesignCompileError(str(error)) from error

    resolved: dict[str, Any] = {
        "schema_version": request_document["schema_version"],
        "role": "multipole_resolved_design_do_not_edit",
        "compiler": {"name": COMPILER_NAME, "version": request_document["schema_version"]},
        "governance": None,
        "request": {
            "request_id": request_document["request_id"],
            "sha256": canonical_sha256(request_document),
        },
        "sources": copy.deepcopy([dict(record) for record in source_records]),
        "identity": copy.deepcopy(locked_identity),
        "units": copy.deepcopy(request_document["units"]),
        "coordinate": copy.deepcopy(request_document["coordinate"]),
        "geometry_mm": {
            "inscribed_radius_r0": r0,
            "rod_radius_ratio": ratio,
            "rod_radius": rod_array["rod_radius"],
            "rod_center_radius": rod_array["rod_center_radius"],
            "rod_z_min": z_min,
            "rod_z_max": z_max,
            "rod_length": rod_array["rod_length"],
            "enclosure": enclosure,
            "rod_array": rod_array,
        },
        "drive": copy.deepcopy(request_document["drive"]),
        "axial_drive": axial_drive,
        "static_electrodes_V": copy.deepcopy(static_electrodes),
        "particle_source": copy.deepcopy(request_document["particle_source"]),
        "segmentation": segmentation,
    }
    if interfaces is not None:
        resolved["interfaces_mm"] = interfaces
    else:
        resolved["geometry_mm"].update(numerical_domain=domain, observations=observations, enclosure_layout=layout)
    resolved["resolved_sha256"] = resolved_design_sha256(resolved)
    try:
        validate_resolved_design_contract(resolved)
    except ContractError as error:
        raise MultipoleDesignCompileError(
            f"compiler produced an invalid resolved design: {error}"
        ) from error
    return resolved
