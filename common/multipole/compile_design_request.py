"""Compile one RF multipole design request into a solver-neutral resolved design."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.build_project_registry import pointer_value
from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.axial_acceleration import (
    MODEL_ID,
    AxialAccelerationError,
    resolve_axial_acceleration,
    segment_rod_array,
)
from common.multipole.connector_geometry import CONNECTOR_SHAPES
from common.multipole.interface_geometry import (
    InterfaceGeometryError,
    build_axial_interface_layout,
)
from common.multipole.round_rod_geometry import (
    RoundRodGeometryError,
    build_round_rod_array,
)


COMPILER_NAME = "common.multipole.compile_design_request"
COMPILER_VERSION = 1
REQUEST_SCHEMA = "multipole_design_request.schema.json"
RESOLVED_SCHEMA = "multipole_resolved_design.schema.json"
GEOMETRY_EQUALITY_ABS_TOL_MM = 1e-12


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


def _source_records(
    source_files: Mapping[str, Path] | None,
    source_root: Path | None = None,
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for label, source in sorted((source_files or {}).items()):
        if not isinstance(label, str) or not label:
            raise MultipoleDesignCompileError("source labels must be nonempty strings")
        path = Path(source).resolve()
        if not path.is_file():
            raise MultipoleDesignCompileError(f"source file is missing: {path}")
        logical_path = path
        if source_root is not None:
            try:
                logical_path = path.relative_to(Path(source_root).resolve())
            except ValueError as error:
                raise MultipoleDesignCompileError(
                    f"source file escapes the provenance root: {path}"
                ) from error
        records.append(
            {
                "label": label,
                "path": logical_path.as_posix(),
                "sha256": file_sha256(path),
            }
        )
    return records


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
    for side in ("entrance", "exit"):
        plane = float(interfaces[side]["particle_plane_z_mm"])
        if not (
            vacuum_min - GEOMETRY_EQUALITY_ABS_TOL_MM
            <= plane
            <= vacuum_max + GEOMETRY_EQUALITY_ABS_TOL_MM
        ):
            raise MultipoleDesignCompileError(
                f"{side} particle plane must remain inside the explicit vacuum z range"
            )
    if float(enclosure["working_region_radius_mm"]) <= 0:
        raise MultipoleDesignCompileError("working region radius must be positive")

    model = enclosure["model"]
    role = enclosure["role"]
    if model == "cylindrical_grounded_shield_v1":
        if role != "full_length_grounded_shield":
            raise MultipoleDesignCompileError("cylindrical enclosure role differs")
        inner = float(enclosure["shield_inner_radius_mm"])
        outer = float(enclosure["shield_outer_radius_mm"])
        entrance_min = float(enclosure["entrance_endcap_z_min_mm"])
        entrance_max = float(enclosure["entrance_endcap_z_max_mm"])
        exit_min = float(enclosure["exit_endcap_z_min_mm"])
        exit_max = float(enclosure["exit_endcap_z_max_mm"])
        if not 0 < inner < outer:
            raise MultipoleDesignCompileError(
                "cylindrical shield radii must be positive and increasing"
            )
        if not (
            vacuum_min <= entrance_min < entrance_max <= exit_min < exit_max <= vacuum_max
        ):
            raise MultipoleDesignCompileError(
                "cylindrical endcaps must be ordered inside the explicit vacuum z range"
            )
        rod_z_min = float(rod_array["rods"][0]["z_min_mm"])
        rod_z_max = float(rod_array["rods"][0]["z_max_mm"])
        if entrance_max > rod_z_min + GEOMETRY_EQUALITY_ABS_TOL_MM:
            raise MultipoleDesignCompileError("entrance endcap intersects the rod span")
        if exit_min < rod_z_max - GEOMETRY_EQUALITY_ABS_TOL_MM:
            raise MultipoleDesignCompileError("exit endcap intersects the rod span")
        transverse_limit = inner
        rod_extent = max(
            math.hypot(float(rod["center_x_mm"]), float(rod["center_y_mm"]))
            + float(rod["radius_mm"])
            for rod in rod_array["rods"]
        )
    elif model == "rectangular_reference_enclosure_v1":
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
    axial_contract = {
        "schema_version": 2,
        "role": "multipole_axial_acceleration_contract",
        "project_id": identity["project_id"],
        "model_id": MODEL_ID,
        "segmentation": source_segmentation,
        "output_reference_V": segmentation["output_reference_V"],
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
    model = request["geometry_mm"]["enclosure"]["model"]
    if model == "rectangular_reference_enclosure_v1":
        source = float(static["entrance_plate_and_connector"])
        output = float(static["exit_enclosure_and_connector"])
    elif model == "cylindrical_grounded_shield_v1":
        source = float(static["shield_and_entrance_endcap_and_connector"])
        output = float(static["exit_endcap_and_connector"])
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
    elif topology == "endplate_potential_step":
        if segmented:
            raise MultipoleDesignCompileError(
                "endplate_potential_step requires continuous rods"
            )
        source_reference, output_reference = _static_reference_voltages(request)
        rod_reference = float(request["drive"]["common_mode_offset_V"])
        if not math.isclose(source_reference, rod_reference, rel_tol=0, abs_tol=1e-12):
            raise MultipoleDesignCompileError(
                "endplate source reference must equal the continuous-rod common mode"
            )
        static = request["static_electrodes_V"]
        if (
            request["geometry_mm"]["enclosure"]["model"]
            == "rectangular_reference_enclosure_v1"
            and not math.isclose(
                float(static["detector"]), output_reference, rel_tol=0, abs_tol=1e-12
            )
        ):
            raise MultipoleDesignCompileError(
                "rectangular endplate detector must share the output reference"
            )
    elif topology == "none":
        if segmented:
            raise MultipoleDesignCompileError(
                "axial-drive topology none requires segmentation off"
            )
        source_reference, output_reference = _static_reference_voltages(request)
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
    source_files: Mapping[str, Path] | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Validate and compile one request against an immutable project identity."""
    request_document = copy.deepcopy(dict(request))
    try:
        validate_schema(request_document, REQUEST_SCHEMA)
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
    enclosure_model = geometry["enclosure"]["model"]
    expected_static_role = (
        "rectangular_reference_static_electrodes"
        if enclosure_model == "rectangular_reference_enclosure_v1"
        else "cylindrical_shield_static_electrodes"
    )
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
        for side in ("entrance_interface", "exit_interface"):
            shape = geometry[side]["connector_shape"]
            if shape not in CONNECTOR_SHAPES:
                raise MultipoleDesignCompileError(f"{side} connector shape is unsupported")
        interfaces = build_axial_interface_layout(
            rod_z_min_mm=z_min,
            rod_z_max_mm=z_max,
            entrance=geometry["entrance_interface"],
            exit_interface=geometry["exit_interface"],
        )
        enclosure = _validate_enclosure(geometry["enclosure"], interfaces, rod_array)
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
        "schema_version": 1,
        "role": "multipole_resolved_design_do_not_edit",
        "compiler": {"name": COMPILER_NAME, "version": COMPILER_VERSION},
        "governance": None,
        "request": {
            "request_id": request_document["request_id"],
            "sha256": canonical_sha256(request_document),
        },
        "sources": _source_records(source_files, source_root),
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
        "interfaces_mm": interfaces,
        "drive": copy.deepcopy(request_document["drive"]),
        "axial_drive": axial_drive,
        "static_electrodes_V": copy.deepcopy(static_electrodes),
        "particle_source": copy.deepcopy(request_document["particle_source"]),
        "segmentation": segmentation,
    }
    resolved["resolved_sha256"] = resolved_design_sha256(resolved)
    try:
        validate_schema(resolved, RESOLVED_SCHEMA)
    except ContractError as error:
        raise MultipoleDesignCompileError(
            f"compiler produced an invalid resolved design: {error}"
        ) from error
    return resolved


def compile_design_request_file(
    request_path: Path,
    *,
    expected_identity: Mapping[str, Any],
    source_files: Mapping[str, Path] | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Load a request and include its byte identity in resolved provenance."""
    path = Path(request_path)
    request = json.loads(path.read_text(encoding="utf-8-sig"))
    sources = dict(source_files or {})
    if "design_request" in sources:
        raise MultipoleDesignCompileError(
            "source label design_request is reserved for the request file"
        )
    sources["design_request"] = path
    return compile_design_request(
        request,
        expected_identity=expected_identity,
        source_files=sources,
        source_root=source_root,
    )


def _pointer_unit(pointer: str) -> str:
    if pointer.startswith("/static_electrodes_V/"):
        return "V"
    leaf = pointer.rsplit("/", 1)[-1]
    if leaf.endswith("_mm") or leaf in {"inscribed_radius_r0", "rod_z_min", "rod_z_max"}:
        return "mm"
    if leaf.endswith("_V") or "_V_" in leaf:
        return "V"
    if leaf.endswith("_Hz"):
        return "Hz"
    if leaf.endswith("_rad"):
        return "rad"
    if leaf.endswith("_ratio"):
        return "ratio"
    if leaf.endswith("_count"):
        return "count"
    raise MultipoleDesignCompileError(f"cannot determine canonical unit for {pointer}")


def compile_governed_design_request_file(
    request_path: Path,
    design_variables_path: Path,
    optimization_envelope_path: Path,
    *,
    expected_identity: Mapping[str, Any],
    provenance_root: Path,
) -> dict[str, Any]:
    """Validate governance bounds and compile the exact referenced request."""
    request_path = Path(request_path)
    variables_path = Path(design_variables_path)
    envelope_path = Path(optimization_envelope_path)
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    variables = json.loads(variables_path.read_text(encoding="utf-8-sig"))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8-sig"))
    try:
        validate_schema(variables, "design_variable_catalog.schema.json")
        validate_schema(envelope, "optimization_envelope.schema.json")
    except ContractError as error:
        raise MultipoleDesignCompileError(str(error)) from error
    identity = _normalize_expected_identity(expected_identity)
    for document, label in ((variables, "design variables"), (envelope, "optimization envelope")):
        if document["project_id"] != identity["project_id"]:
            raise MultipoleDesignCompileError(f"{label} project identity differs")
        if document["family_id"] != identity["family_id"]:
            raise MultipoleDesignCompileError(f"{label} family identity differs")
    if envelope["reference"]["design_request_sha256"] != file_sha256(request_path):
        raise MultipoleDesignCompileError("optimization envelope request hash is stale")
    catalog_pointers: set[str] = set()
    for variable in variables["variables"]:
        pointer = variable["json_pointer"]
        if pointer in catalog_pointers:
            raise MultipoleDesignCompileError(f"duplicate catalog pointer: {pointer}")
        catalog_pointers.add(pointer)
        try:
            value = pointer_value(request, pointer)
        except (KeyError, TypeError) as error:
            raise MultipoleDesignCompileError(f"catalog pointer is missing: {pointer}") from error
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise MultipoleDesignCompileError(f"catalog pointer is not numeric: {pointer}")
        if variable["kind"] == "integer" and not isinstance(value, int):
            raise MultipoleDesignCompileError(f"integer catalog pointer is not integer: {pointer}")
        if variable["unit"] != _pointer_unit(pointer):
            raise MultipoleDesignCompileError(f"catalog unit differs from request field: {pointer}")
        if not float(variable["minimum"]) <= float(value) <= float(variable["maximum"]):
            raise MultipoleDesignCompileError(f"request value is outside catalog bounds: {pointer}")
    constraint_pointers: set[str] = set()
    for constraint in envelope["constraints"]:
        for pointer in constraint["request_json_pointers"]:
            try:
                pointer_value(request, pointer)
            except (KeyError, TypeError) as error:
                raise MultipoleDesignCompileError(
                    f"envelope constraint pointer is missing: {pointer}"
                ) from error
            constraint_pointers.add(pointer)
    if not catalog_pointers <= constraint_pointers:
        raise MultipoleDesignCompileError(
            "optimization envelope does not constrain every catalog variable"
        )
    resolved = compile_design_request_file(
        request_path,
        expected_identity=identity,
        source_files={
            "design_variables": variables_path,
            "optimization_envelope": envelope_path,
        },
        source_root=provenance_root,
    )
    resolved["governance"] = {
        "design_variables_sha256": file_sha256(variables_path),
        "optimization_envelope_sha256": file_sha256(envelope_path),
        "design_request_file_sha256": file_sha256(request_path),
    }
    resolved["resolved_sha256"] = resolved_design_sha256(resolved)
    validate_schema(resolved, RESOLVED_SCHEMA)
    return resolved


def validate_resolved_design(
    resolved: Mapping[str, Any],
    *,
    request_path: Path,
    source_root: Path,
    expected_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompile a resolved design's original request and require exact equality."""
    document = copy.deepcopy(dict(resolved))
    try:
        validate_schema(document, RESOLVED_SCHEMA)
    except ContractError as error:
        raise MultipoleDesignCompileError(str(error)) from error
    _ensure_finite_numbers(document)
    locked_identity = _normalize_expected_identity(expected_identity)
    if document["identity"] != locked_identity:
        raise MultipoleDesignCompileError(
            "resolved design identity differs from the immutable expected project identity"
        )
    source_files: dict[str, Path] = {}
    design_request_source = None
    root = Path(source_root).resolve()
    for record in document["sources"]:
        logical = Path(record["path"])
        if logical.is_absolute() or ".." in logical.parts:
            raise MultipoleDesignCompileError(
                f"resolved design source path is not portable: {record['path']}"
            )
        path = (root / logical).resolve()
        if root != path.parent and root not in path.parents:
            raise MultipoleDesignCompileError(
                f"resolved design source escapes its provenance root: {record['path']}"
            )
        if not path.is_file() or file_sha256(path) != record["sha256"]:
            raise MultipoleDesignCompileError(
                f"resolved design source cannot be verified: {path}"
            )
        if record["label"] == "design_request":
            design_request_source = path
        else:
            source_files[record["label"]] = path
    requested_path = Path(request_path)
    if design_request_source is None or requested_path.resolve() != design_request_source.resolve():
        raise MultipoleDesignCompileError(
            "resolved design must be checked against its recorded original request"
        )
    if document["governance"] is None:
        rebuilt = compile_design_request_file(
            requested_path,
            expected_identity=locked_identity,
            source_files=source_files,
            source_root=source_root,
        )
    else:
        try:
            variables_path = source_files.pop("design_variables")
            envelope_path = source_files.pop("optimization_envelope")
        except KeyError as error:
            raise MultipoleDesignCompileError(
                "governed resolved design is missing governance source records"
            ) from error
        if source_files:
            raise MultipoleDesignCompileError(
                "governed resolved design has unknown additional sources"
            )
        rebuilt = compile_governed_design_request_file(
            requested_path,
            variables_path,
            envelope_path,
            expected_identity=locked_identity,
            provenance_root=source_root,
        )
    if document != rebuilt:
        raise MultipoleDesignCompileError(
            "resolved design differs from deterministic request recompilation"
        )
    return document


def validate_resolved_design_file(
    path: Path,
    *,
    request_path: Path,
    source_root: Path,
    expected_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Load a resolved design and compare it with deterministic recompilation."""
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return validate_resolved_design(
        document,
        request_path=request_path,
        source_root=source_root,
        expected_identity=expected_identity,
    )


def _parse_source_bindings(values: list[str]) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for value in values:
        label, separator, path = value.partition("=")
        if not separator or not label or not path:
            raise MultipoleDesignCompileError(
                "each --source binding must have the form label=path"
            )
        if label in bindings:
            raise MultipoleDesignCompileError(f"duplicate source label: {label}")
        bindings[label] = Path(path)
    return bindings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--design-variables", required=True, type=Path)
    parser.add_argument("--optimization-envelope", required=True, type=Path)
    parser.add_argument("--provenance-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--radial-order-n", required=True, type=int)
    parser.add_argument("--electrode-count", required=True, type=int)
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Additional source file to freeze; may be repeated.",
    )
    args = parser.parse_args()
    expected_identity = {
        "project_id": args.project_id,
        "family_id": "rf_multipole_ion_optics",
        "radial_order_n": args.radial_order_n,
        "electrode_count": args.electrode_count,
    }
    if args.source:
        raise MultipoleDesignCompileError(
            "--source is unavailable on the governed production compiler"
        )
    resolved = compile_governed_design_request_file(
        args.request,
        args.design_variables,
        args.optimization_envelope,
        expected_identity=expected_identity,
        provenance_root=args.provenance_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "MULTIPOLE_DESIGN_COMPILE=PASS "
        f"PROJECT={resolved['identity']['project_id']} "
        f"SHA256={resolved['resolved_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
