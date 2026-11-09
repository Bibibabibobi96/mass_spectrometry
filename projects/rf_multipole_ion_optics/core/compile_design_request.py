"""Compile one RF multipole design request into a solver-neutral resolved design."""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from msplatform.io.file_identity import repository_text_sha256
from common.contracts.build_project_registry import pointer_value
from common.paths.repository_root import REPO_ROOT
from msplatform.contracts.machine_contracts import ContractError, validate_schema


from msplatform.components.rf_multipole.compile_design_request import _version_schema as _version_schema
from msplatform.components.rf_multipole.compile_design_request import validate_design_request as validate_design_request
from msplatform.components.rf_multipole.compile_design_request import validate_resolved_design_contract as validate_resolved_design_contract
from msplatform.components.rf_multipole.compile_design_request import MultipoleDesignCompileError as MultipoleDesignCompileError
from msplatform.components.rf_multipole.compile_design_request import canonical_sha256 as canonical_sha256
from msplatform.components.rf_multipole.compile_design_request import resolved_design_sha256 as resolved_design_sha256
from msplatform.components.rf_multipole.compile_design_request import _ensure_finite_numbers as _ensure_finite_numbers
from msplatform.components.rf_multipole.compile_design_request import _normalize_expected_identity as _normalize_expected_identity
from msplatform.components.rf_multipole.compile_design_request import _validate_enclosure as _validate_enclosure
from msplatform.components.rf_multipole.compile_design_request import _validate_current_geometry as _validate_current_geometry
from msplatform.components.rf_multipole.compile_design_request import _resolve_segmentation as _resolve_segmentation
from msplatform.components.rf_multipole.compile_design_request import _static_reference_voltages as _static_reference_voltages
from msplatform.components.rf_multipole.compile_design_request import _nominal_source_energy as _nominal_source_energy
from msplatform.components.rf_multipole.compile_design_request import _resolve_axial_drive as _resolve_axial_drive
from msplatform.components.rf_multipole.compile_design_request import compile_design_request as _compile_document

# Stable v2 serialized contract identifier, not an importable module address.
COMPILER_NAME = "common.multipole.compile_design_request"
COMPILER_VERSION = 3
REQUEST_SCHEMA = "multipole_design_request.schema.json"
RESOLVED_SCHEMA = "multipole_resolved_design.schema.json"
OPERATING_MODE_SCHEMA = "multipole_operating_modes.schema.json"
OPERATING_MODE_SOURCE_PREFIX = "operating_mode_registry__"
GEOMETRY_EQUALITY_ABS_TOL_MM = 1e-12


def _repository_text_source_policy(
    source_root: Path | None,
    requested: bool | None,
) -> bool:
    """Select LF-normalized identities only for repository text authorities."""
    if requested is not None:
        return requested
    return (
        source_root is not None
        and Path(source_root).resolve() == REPO_ROOT.resolve()
    )


def _source_records(
    source_files: Mapping[str, Path] | None,
    source_root: Path | None = None,
    *,
    repository_text_sources: bool = False,
) -> list[dict[str, str]]:
    source_sha256 = (
        repository_text_sha256 if repository_text_sources else file_sha256
    )
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
                "sha256": source_sha256(path),
            }
        )
    return records


def compile_design_request(
    request: Mapping[str, Any], *, expected_identity: Mapping[str, Any],
    source_files: Mapping[str, Path] | None = None, source_root: Path | None = None,
    repository_text_sources: bool = False,
) -> dict[str, Any]:
    """Resolve repository/file provenance, then call the installed document compiler."""
    records = _source_records(source_files, source_root, repository_text_sources=repository_text_sources)
    return _compile_document(request, expected_identity=expected_identity, source_records=records)


def compile_design_request_file(
    request_path: Path,
    *,
    expected_identity: Mapping[str, Any],
    source_files: Mapping[str, Path] | None = None,
    source_root: Path | None = None,
    repository_text_sources: bool | None = None,
) -> dict[str, Any]:
    """Load a request and include its governed source identity in provenance."""
    path = Path(request_path)
    request = json.loads(path.read_text(encoding="utf-8-sig"))
    sources = dict(source_files or {})
    if "design_request" in sources:
        raise MultipoleDesignCompileError(
            "source label design_request is reserved for the request file"
        )
    sources["design_request"] = path
    use_repository_text = _repository_text_source_policy(
        source_root,
        repository_text_sources,
    )
    return compile_design_request(
        request,
        expected_identity=expected_identity,
        source_files=sources,
        source_root=source_root,
        repository_text_sources=use_repository_text,
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


def operating_mode_source_label(mode_id: str) -> str:
    """Return the reversible resolved-source label for one selected mode."""
    return f"{OPERATING_MODE_SOURCE_PREFIX}{mode_id}"


def apply_typed_operating_mode(
    base_request: Mapping[str, Any],
    mode_registry: Mapping[str, Any],
    mode_id: str,
) -> dict[str, Any]:
    """Apply the narrow electrical mode vocabulary to a deep-copied request."""
    request = copy.deepcopy(dict(base_request))
    registry = copy.deepcopy(dict(mode_registry))
    try:
        validate_design_request(request)
        validate_schema(registry, OPERATING_MODE_SCHEMA)
    except ContractError as error:
        raise MultipoleDesignCompileError(str(error)) from error
    _ensure_finite_numbers(registry, "operating_mode_registry")
    if (
        registry["project_id"] != request["identity"]["project_id"]
        or registry["family_id"] != request["identity"]["family_id"]
    ):
        raise MultipoleDesignCompileError(
            "operating mode registry identity differs from the base request"
        )
    selected = [mode for mode in registry["modes"] if mode["mode_id"] == mode_id]
    if len(selected) != 1:
        raise MultipoleDesignCompileError(
            f"operating mode is not unique: {mode_id!r}"
        )
    segmentation = request["segmentation"]
    if segmentation["strategy"] != "uniform":
        raise MultipoleDesignCompileError(
            "typed operating modes require one uniform physical rod segmentation baseline"
        )
    mode = selected[0]
    topology = mode["axial_drive_topology"]
    terminal_voltage = float(registry["terminal_reference_V"])
    entrance_relative = float(mode["rod_entrance_relative_to_terminal_V"])
    exit_relative = float(mode["rod_exit_relative_to_terminal_V"])
    if topology == "none" and not (
        math.isclose(entrance_relative, 0.0, rel_tol=0, abs_tol=1e-12)
        and math.isclose(exit_relative, 0.0, rel_tol=0, abs_tol=1e-12)
    ):
        raise MultipoleDesignCompileError(
            "topology none requires zero rod potentials relative to the terminal"
        )
    if topology == "segmented_rod_axial_acceleration" and not math.isclose(
        exit_relative, 0.0, rel_tol=0, abs_tol=1e-12
    ):
        raise MultipoleDesignCompileError(
            "segmented acceleration must end at the terminal potential"
        )
    entrance_voltage = terminal_voltage + entrance_relative
    exit_voltage = terminal_voltage + exit_relative
    request["axial_drive"]["topology"] = mode["axial_drive_topology"]
    segmentation["entrance_common_mode_V"] = entrance_voltage
    segmentation["exit_common_mode_V"] = exit_voltage
    segmentation["output_reference_V"] = terminal_voltage
    request["drive"]["common_mode_offset_V"] = entrance_voltage
    static = request["static_electrodes_V"]
    if static["role"] == "grounded_shell_static_electrodes":
        static["ground_V"] = 0.0
    elif static["role"] == "bare_multipole_static_electrodes":
        pass
    elif static["role"] == "rectangular_reference_static_electrodes":
        static["entrance_aperture_plate_and_connector_V"] = entrance_voltage
        static["exit_outer_enclosure_and_connector_V"] = 0.0
        static["physical_detector_V"] = terminal_voltage
    else:
        raise MultipoleDesignCompileError(
            "typed operating mode cannot map the static-electrode role"
        )
    try:
        validate_design_request(request)
    except ContractError as error:
        raise MultipoleDesignCompileError(str(error)) from error
    return request


def compile_governed_design_request_file(
    request_path: Path,
    design_variables_path: Path,
    optimization_envelope_path: Path,
    *,
    expected_identity: Mapping[str, Any],
    provenance_root: Path,
    operating_mode_registry_path: Path | None = None,
    mode_id: str | None = None,
    repository_text_sources: bool | None = None,
) -> dict[str, Any]:
    """Compile a governed base with explicit mechanical and typed electrical choices."""
    request_path = Path(request_path)
    variables_path = Path(design_variables_path)
    envelope_path = Path(optimization_envelope_path)
    base_request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    if (operating_mode_registry_path is None) != (mode_id is None):
        raise MultipoleDesignCompileError(
            "operating_mode_registry_path and mode_id must be provided together"
        )
    mode_sources: dict[str, Path] = {}
    if operating_mode_registry_path is None:
        request = copy.deepcopy(base_request)
    else:
        mode_path = Path(operating_mode_registry_path)
        mode_registry = json.loads(mode_path.read_text(encoding="utf-8-sig"))
        request = apply_typed_operating_mode(base_request, mode_registry, mode_id)
        mode_sources[operating_mode_source_label(mode_id)] = mode_path
    variables = json.loads(variables_path.read_text(encoding="utf-8-sig"))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8-sig"))
    use_repository_text = _repository_text_source_policy(
        provenance_root,
        repository_text_sources,
    )
    source_sha256 = (
        repository_text_sha256 if use_repository_text else file_sha256
    )
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
    if envelope["reference"]["design_request_sha256"] != source_sha256(request_path):
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
    resolved = compile_design_request(
        request,
        expected_identity=identity,
        source_files={
            "design_request": request_path,
            "design_variables": variables_path,
            "optimization_envelope": envelope_path,
            **mode_sources,
        },
        source_root=provenance_root,
        repository_text_sources=use_repository_text,
    )
    resolved["governance"] = {
        "design_variables_sha256": source_sha256(variables_path),
        "optimization_envelope_sha256": source_sha256(envelope_path),
        "design_request_file_sha256": source_sha256(request_path),
    }
    resolved["resolved_sha256"] = resolved_design_sha256(resolved)
    validate_resolved_design_contract(resolved)
    return resolved


def validate_resolved_design(
    resolved: Mapping[str, Any],
    *,
    request_path: Path,
    source_root: Path,
    expected_identity: Mapping[str, Any],
    repository_text_sources: bool | None = None,
) -> dict[str, Any]:
    """Recompile a resolved design's original request and require exact equality."""
    document = copy.deepcopy(dict(resolved))
    try:
        validate_resolved_design_contract(document)
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
    use_repository_text = _repository_text_source_policy(
        root,
        repository_text_sources,
    )
    source_sha256 = (
        repository_text_sha256 if use_repository_text else file_sha256
    )
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
        if not path.is_file() or source_sha256(path) != record["sha256"]:
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
            repository_text_sources=use_repository_text,
        )
    else:
        try:
            variables_path = source_files.pop("design_variables")
            envelope_path = source_files.pop("optimization_envelope")
        except KeyError as error:
            raise MultipoleDesignCompileError(
                "governed resolved design is missing governance source records"
            ) from error
        mode_sources = {
            label: path
            for label, path in source_files.items()
            if label.startswith(OPERATING_MODE_SOURCE_PREFIX)
        }
        if len(mode_sources) > 1 or set(source_files) != set(mode_sources):
            raise MultipoleDesignCompileError(
                "governed resolved design has unknown additional sources"
            )
        mode_registry_path = None
        mode_id = None
        if mode_sources:
            label, mode_registry_path = next(iter(mode_sources.items()))
            mode_id = label.removeprefix(OPERATING_MODE_SOURCE_PREFIX)
        rebuilt = compile_governed_design_request_file(
            requested_path,
            variables_path,
            envelope_path,
            expected_identity=locked_identity,
            provenance_root=source_root,
            operating_mode_registry_path=mode_registry_path,
            mode_id=mode_id,
            repository_text_sources=use_repository_text,
        )
    if document != rebuilt:
        raise MultipoleDesignCompileError(
            "resolved design differs from deterministic request recompilation"
        )
    return document


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
    parser.add_argument("--operating-mode-registry", type=Path)
    parser.add_argument("--mode-id")
    args = parser.parse_args()
    expected_identity = {
        "project_id": args.project_id,
        "family_id": "rf_multipole_ion_optics",
        "radial_order_n": args.radial_order_n,
        "electrode_count": args.electrode_count,
    }
    resolved = compile_governed_design_request_file(
        args.request,
        args.design_variables,
        args.optimization_envelope,
        expected_identity=expected_identity,
        provenance_root=args.provenance_root,
        operating_mode_registry_path=args.operating_mode_registry,
        mode_id=args.mode_id,
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
