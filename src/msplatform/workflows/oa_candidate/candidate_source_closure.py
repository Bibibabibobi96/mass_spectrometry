"""Freeze and verify the executable source closure of an oa-TOF candidate run."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import importlib.util
import io
import json
import marshal
import struct
import sys
import types
from pathlib import Path
from typing import Any

from msplatform.contracts.machine_contracts import sha256
from msplatform.execution.inputs import enumerate_python_sources
from msplatform.io.manifest_records import record_path
from msplatform.execution.retention import verify_record
from msplatform.execution.retention import file_record
from msplatform.components.orthogonal_accelerator.component_contract import load_accelerator_dependency


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
ROLE = "oa_tof_candidate_execution_source_closure"

# This is intentionally an auditable allowlist, not dependency discovery.
# Keep paths repository-relative and use forward slashes in the machine record.
SCIENCE_RELATIVE_PATHS = (
    "projects/single_reflection_oa_tof_mass_analyzer/config/candidate_consumers.json",
    "projects/single_reflection_oa_tof_mass_analyzer/config/design_variables.json",
    "src/msplatform/components/orthogonal_accelerator/component_contract.json",
    "projects/orthogonal_accelerator/simion/two_zone_accelerator.gem",
    "projects/single_reflection_oa_tof_mass_analyzer/config/accelerator_dependency.json",
)

RELATIVE_PATHS = (
    "src/msplatform/contracts/particle_count_policy.json",
    "src/msplatform/workflows/resources/run_artifact_workflow.ps1",
    "src/msplatform/workflows/resources/oatof_lifecycle_preflight.ps1",
    "src/msplatform/backends/simion/resources/short_pa_path_support.ps1",
    "src/msplatform/backends/simion/resources/native_fast_adjust_runtime_support.ps1",
    "src/msplatform/backends/simion/resources/assemble_native_fast_adjust_family.lua",
    "src/msplatform/backends/simion/resources/export_standalone_pa.lua",
    "src/msplatform/backends/simion/resources/voltageize_pa0.lua",
    "src/msplatform/backends/comsol/matlab/add_comsol_size_feature.m",
    "src/msplatform/backends/comsol/matlab/read_comsol_mesh_size_controls.m",
    "src/msplatform/backends/comsol/launcher/livelink_environment.ps1",
    "src/msplatform/backends/comsol/launcher/livelink_failure_classification.ps1",
    "src/msplatform/backends/comsol/matlab/comsolstartup.m",
    "src/msplatform/backends/comsol/launcher/resolve_comsol_64.ps1",
    "src/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1",
    "src/msplatform/backends/comsol/matlab/workspace_paths.m",
    "src/msplatform/backends/comsol/matlab/resolve_path_identity.m",
    "src/msplatform/backends/comsol/matlab/build_sectioned_geometry.m",
    "src/msplatform/backends/comsol/matlab/build_accelerator_grids.m",
    "src/msplatform/backends/comsol/matlab/configure_oatof_segmented_output.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_accelerator_geometry.m",
    "src/msplatform/backends/comsol/matlab/oatof_cpt_solver_policy.m",
    "src/msplatform/backends/comsol/matlab/oatof_extract_detector_arrivals.m",
    "src/msplatform/backends/comsol/matlab/oatof_detector_arrival_reducer.m",
    "src/msplatform/backends/comsol/matlab/oatof_read_cartesian_release.m",
    "src/msplatform/backends/comsol/matlab/run_oatof_model.m",
    "src/msplatform/backends/comsol/matlab/load_oatof_contract.m",
    "src/msplatform/backends/comsol/matlab/oatof_paths.m",
    "src/msplatform/backends/comsol/matlab/run_candidate_contract_build.m",
    "src/msplatform/backends/simion/resources/build_reflectron_variant.lua",
    "src/msplatform/backends/simion/resources/oatof_reflectron_ideal_10_5.gem",
    "src/msplatform/backends/simion/resources/build_detector_variant.lua",
    "src/msplatform/backends/simion/resources/build_flight_tube_variant.lua",
    "src/msplatform/backends/simion/resources/oatof_detector_ground.gem",
    "src/msplatform/backends/simion/resources/oatof_flight_tube_ground.gem",
    "src/msplatform/backends/simion/resources/refine_single_pa.lua",
    "src/msplatform/backends/simion/resources/verify_component_pa.lua",
    "src/msplatform/backends/simion/resources/SIMION_DELIVERY_CHECKLIST.md",
    "src/msplatform/backends/simion/resources/oatof_ideal_grounded.lua",
    "src/msplatform/exporters/solidworks/resources/import_step_to_solidworks.m",
    "src/msplatform/backends/simion/resources/build_two_zone_pa.lua",
    *SCIENCE_RELATIVE_PATHS,
    "src/msplatform/backends/comsol/matlab/oatof_build_detector_geometry.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_drift_geometry.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_grid_geometry.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_mesh.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_model_core.m",
    "src/msplatform/backends/comsol/matlab/oatof_validate_candidate_solution.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_saved_particle_solution.m",
    "src/msplatform/backends/comsol/matlab/oatof_save_run_model.m",
    "src/msplatform/backends/comsol/matlab/oatof_write_saved_particle_context.m",
    "src/msplatform/backends/comsol/matlab/oatof_postprocess_saved_solution.m",
    "src/msplatform/backends/comsol/matlab/oatof_report_model_timing.m",
    "src/msplatform/backends/comsol/matlab/reextract_oatof_saved_solution.m",
    "src/msplatform/backends/comsol/matlab/oatof_particle_plot_view.m",
    "src/msplatform/backends/comsol/matlab/oatof_build_reflectron_geometry.m",
    "src/msplatform/backends/comsol/matlab/oatof_configure_particle_model.m",
    "src/msplatform/backends/comsol/matlab/oatof_create_result_nodes.m",
    "src/msplatform/backends/comsol/matlab/oatof_export_detector_events.m",
    "src/msplatform/backends/comsol/matlab/oatof_parse_field_idealization.m",
    "src/msplatform/backends/comsol/matlab/verify_oatof_comsol_sync.m",
    "src/msplatform/backends/comsol/matlab/oatof_assert_formal_write_authorized.m",
    "src/msplatform/backends/simion/resources/generate_comsol_consistent_ions.ps1",
    "src/msplatform/backends/simion/resources/analyze_ideal_field_log.ps1",
    "src/msplatform/backends/simion/resources/build_formal_delivery.ps1",
    "src/msplatform/backends/simion/resources/build_formal_iob.lua",
    "src/msplatform/backends/simion/resources/run_n100_transport.ps1",
    "src/msplatform/backends/simion/resources/run_candidate_flight.ps1",
    "src/msplatform/backends/simion/resources/verify_iob_runtime_contract.lua",
    "src/msplatform/backends/simion/resources/verify_iob_runtime_contract.ps1",
    "src/msplatform/backends/comsol/matlab/run_candidate_cad_sync.m",
    "src/msplatform/workflows/oa_candidate/solver_diagnostics.py",
)

def _package_root() -> Path:
    return Path(str(files("msplatform"))).resolve(strict=True)


def _source_path(source_id: str, science_root: Path) -> Path:
    relative = Path(source_id)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid candidate source path: {source_id}")
    if relative.parts[:2] == ("src", "msplatform"):
        root = _package_root()
        source = root.joinpath(*relative.parts[2:]).resolve()
    else:
        if source_id not in SCIENCE_RELATIVE_PATHS:
            raise ValueError(f"candidate science input is not explicitly declared: {source_id}")
        root = science_root.resolve(strict=True)
        source = root.joinpath(*relative.parts).resolve()
    if not source.is_file() or root not in source.parents:
        raise ValueError(f"candidate source is absent or escapes its declared owner: {source_id}")
    return source


def _execution_resource_source_ids() -> tuple[str, ...]:
    declaration = json.loads((_package_root() / "execution/resources/package_resources.json").read_text(encoding="utf-8"))
    package = _package_root() / "execution"
    selected: set[str] = set()
    if declaration.get("package") != "msplatform.execution":
        raise ValueError("execution package resource declaration has the wrong owner")
    for pattern in declaration["patterns"]:
        matches = [source for source in package.glob(pattern) if source.is_file()]
        if not matches:
            raise FileNotFoundError(f"Declared execution resource pattern has no files: {pattern}")
        for source in matches:
            actual = source.resolve(strict=True)
            if not actual.is_relative_to(package):
                raise ValueError(f"Declared execution resource escapes its package: {source}")
            selected.add("src/msplatform/execution/" + actual.relative_to(package).as_posix())
    return tuple(sorted(selected))


def freeze_candidate_source_closure(
    code_root: Path,
    artifact_root: Path,
    python_executable: Path | None = None,
    *,
    science_root: Path,
    extra_source_ids: tuple[str, ...] = (),
    resolved_contract: Path | None = None,
    analysis_contract: Path | None = None,
) -> dict[str, Any]:
    """Copy the declared closure and return its immutable execution record."""
    code_root = code_root.resolve()
    python_path = Path(python_executable or sys.executable).resolve()
    if not python_path.is_file():
        raise ValueError(f"candidate Python runtime is unavailable: {python_path}")
    artifact_path = artifact_root.resolve()
    science_root = science_root.resolve(strict=True)
    load_accelerator_dependency(
        science_root, science_root / f"projects/{PROJECT_ID}/config/accelerator_dependency.json",
        consumer_project_id=PROJECT_ID, required_variant="two_zone", validate_implementation_sources=False,
    )

    if not isinstance(extra_source_ids, tuple) or any(
        not isinstance(source_id, str) or not source_id for source_id in extra_source_ids
    ):
        raise ValueError("extra candidate source ids must be a tuple of relative paths")
    declarations = list(RELATIVE_PATHS)
    explicit_seen: set[str] = set()
    for source_id in declarations:
        if source_id in explicit_seen:
            raise ValueError(f"duplicate candidate source id: {source_id}")
        explicit_seen.add(source_id)
    for source_id in _execution_resource_source_ids():
        if source_id not in declarations:
            declarations.append(source_id)
    for source_id in enumerate_python_sources(_package_root().parent,
            package_roots=("msplatform",), provider_root="msplatform", resource_suffixes=(".schema.json",)):
        normalized = "src/" + source_id
        if normalized not in declarations:
            declarations.append(normalized)
    for source_id in extra_source_ids:
        normalized = source_id.replace("\\", "/")
        _source_path(normalized, science_root)
        if normalized not in declarations:
            declarations.append(normalized)

    analysis_resources = {}
    if (resolved_contract is None) != (analysis_contract is None):
        raise ValueError("Candidate detector analysis requires both explicit physical and analysis contracts")
    if resolved_contract is not None:
        analysis_resources = {
            "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json": resolved_contract.resolve(strict=True),
            "projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json": analysis_contract.resolve(strict=True),
        }
        declarations.extend(analysis_resources)
    selected: dict[str, Path] = {}
    for declared in declarations:
        source_id = declared.replace("\\", "/")
        if source_id in selected:
            raise ValueError(f"duplicate candidate source id: {source_id}")
        selected[source_id] = analysis_resources.get(source_id) or _source_path(source_id, science_root)
    records: list[dict[str, Any]] = []
    for source_id, source in selected.items():
        source_digest = sha256(source)
        payload = source.read_bytes()
        if sha256(source) != source_digest:
            raise ValueError(f"candidate source changed while frozen: {source_id}")

        target = code_root / source_id
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        records.append(
            {
                "source_id": source_id,
                "source_sha256": source_digest,
                "sha256": hashlib.sha256(payload).hexdigest().upper(),
                "bytes": target.stat().st_size,
                "transformations": [],
            }
        )

    closure = {
        "schema_version": 2,
        "role": ROLE,
        "code_root": str(code_root),
        "runtime": {
            "python_executable": str(python_path),
            "python_sha256": sha256(python_path),
            "candidate_artifact_root": str(artifact_path),
        },
        "sources": records,
    }
    verify_candidate_source_closure(closure)
    return closure


def verify_candidate_source_closure(closure: dict[str, Any]) -> None:
    """Reject malformed, missing, extra, or modified frozen source files."""
    if closure.get("schema_version") != 2 or closure.get("role") != ROLE:
        raise ValueError("invalid candidate source closure")
    records = closure.get("sources")
    if not isinstance(records, list) or not records:
        raise ValueError("invalid candidate source closure")
    runtime = closure.get("runtime", {})
    python_path = Path(runtime.get("python_executable", "")).resolve()
    if not python_path.is_file() or sha256(python_path).lower() != str(runtime.get("python_sha256", "")).lower():
        raise ValueError("candidate Python runtime changed or is unavailable")

    root = Path(closure.get("code_root", "")).resolve()
    expected: set[Path] = set()
    source_ids: set[str] = set()
    for item in records:
        source_id = str(item.get("source_id", "")).replace("\\", "/")
        if source_id in source_ids:
            raise ValueError(f"duplicate frozen candidate source id: {source_id}")
        source_ids.add(source_id)
        relative = Path(source_id)
        path = (root / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or root not in path.parents
            or not path.is_file()
            or path.stat().st_size != item.get("bytes")
            or sha256(path).lower() != str(item.get("sha256", "")).lower()
        ):
            raise ValueError(f"frozen candidate source changed: {source_id}")
        expected.add(path)

    actual = {path.resolve() for path in root.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("candidate source closure has missing or extra files")


def frozen_source_path(closure: dict[str, Any], source_id: str) -> str:
    """Resolve a declared path; execution and publication verify the full closure."""
    if closure.get("schema_version") != 2 or closure.get("role") != ROLE:
        raise ValueError("invalid candidate source closure")
    normalized = source_id.replace("\\", "/")
    declared = [item["source_id"] for item in closure["sources"]]
    if len(declared) != len(set(declared)):
        raise ValueError("duplicate frozen candidate source id")
    if normalized not in declared:
        raise ValueError(f"undeclared candidate source id: {normalized}")
    root = Path(closure["code_root"]).resolve()
    relative = Path(normalized)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or root not in path.parents:
        raise ValueError(f"invalid candidate source path: {normalized}")
    return str(path)


def _same_frozen_code(left: Any, right: Any) -> bool:
    """Compare compiled fields, including metadata ignored by code equality."""
    if type(left) is not type(right):
        return False
    if isinstance(left, types.CodeType):
        fields = (
            "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
            "co_stacksize", "co_flags", "co_code", "co_names", "co_varnames",
            "co_filename", "co_name", "co_qualname", "co_firstlineno",
            "co_linetable", "co_exceptiontable", "co_freevars", "co_cellvars", "co_consts",
        )
        return all(_same_frozen_code(getattr(left, key), getattr(right, key)) for key in fields)
    if isinstance(left, tuple):
        return len(left) == len(right) and all(_same_frozen_code(a, b) for a, b in zip(left, right))
    if isinstance(left, frozenset):
        return left == right
    # Scalars have no marshal object-reference layout; retain float bit patterns.
    return marshal.dumps(left) == marshal.dumps(right)


def derive_candidate_source_closure(
    parent_manifest_path: Path, parent_closure_path: Path, code_root: Path, *,
    embedded_candidate_plan: bool = False,
) -> dict[str, Any]:
    """Derive read-only parent evidence with authenticated CPython 3.11 caches.

    The normal verifier remains strict. No parent code or bytecode is executed;
    only declared sources enter the new evidence root. The caller owns terminal
    consumption guards and publishes the returned closure/derivation in its new run.
    embedded_candidate_plan selects only the known manifest-bound Candidate
    runtime-plan field; it does not synthesize a standalone historical closure.
    PEP 552 defines the timestamp header; Python's marshal warning requires the
    existing manifest identity check before decoding any cached code object.
    """
    parent_manifest_path = parent_manifest_path.resolve()
    parent_closure_path = parent_closure_path.resolve()
    code_root = code_root.resolve()
    parent = parent_manifest_path.parent
    manifest = json.loads(parent_manifest_path.read_bytes())
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") not in {"success", "failed", "interrupted"}:
        raise ValueError("source derivation requires an explicit terminal parent manifest")
    bindings = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]

    def bound(path: Path) -> dict[str, Any]:
        records = [item for item in bindings if isinstance(item, dict) and record_path(item, base_dir=parent) == path]
        if not records or len({(item.get("bytes"), item.get("sha256")) for item in records}) != 1:
            raise ValueError(f"parent manifest lacks a unique source identity: {path}")
        record = {**records[0], "path": str(path)}
        try:
            verify_record("parent source derivation", record)
        except AssertionError as error:
            raise ValueError(str(error)) from error
        return record

    closure_record = bound(parent_closure_path)
    closure = json.loads(parent_closure_path.read_bytes())
    if type(embedded_candidate_plan) is not bool:
        raise ValueError("embedded Candidate plan selection must be boolean")
    if embedded_candidate_plan:
        if (closure.get("schema_version") != 1 or closure.get("role") != "oa_tof_candidate_run_plan"
                or closure.get("run_id") != parent.name or manifest.get("project") != PROJECT_ID
                or Path(str(closure.get("run_root", ""))).resolve() != parent
                or not isinstance(closure.get("execution_source_closure"), dict)):
            raise ValueError("parent source container is not the bound Candidate runtime plan")
        closure = closure["execution_source_closure"]
    source_root = Path(closure.get("code_root", "")).resolve()
    if parent not in source_root.parents or parent not in parent_closure_path.parents:
        raise ValueError("parent source closure escapes its run")
    if code_root.exists() or parent == code_root or parent in code_root.parents:
        raise ValueError("source derivation requires a fresh destination outside the parent")
    runtime = closure.get("runtime", {})
    runtime_path = Path(runtime.get("python_executable", "")).resolve()
    if sys.version_info[:2] != (3, 11) or sys.implementation.name != "cpython" or runtime_path != Path(sys.executable).resolve():
        raise ValueError("source derivation requires the bound CPython 3.11 runtime")
    if sha256(runtime_path).lower() != str(runtime.get("python_sha256", "")).lower():
        raise ValueError("parent Python runtime identity differs")
    # Validate every declared source using the unchanged verifier in a clean
    # destination; first collect bytes without allowing any unbound extra file.
    if closure.get("schema_version") != 2 or closure.get("role") != ROLE or not closure.get("sources"):
        raise ValueError("invalid parent candidate source closure")
    sources: dict[Path, bytes] = {}
    for item in closure["sources"]:
        relative = Path(item["source_id"])
        path = (source_root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or source_root not in path.parents or path in sources:
            raise ValueError("invalid or duplicate parent frozen source")
        payload = path.read_bytes()
        if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest().lower() != str(item["sha256"]).lower():
            raise ValueError(f"parent frozen source changed: {item['source_id']}")
        sources[path] = payload
    caches = []
    extras = {path.resolve() for path in source_root.rglob("*") if path.is_file()} - sources.keys()
    for path in sorted(extras):
        identity = bound(path)  # Authenticate before marshal; never trust arbitrary caches.
        try:
            source = Path(importlib.util.source_from_cache(str(path))).resolve()
        except ValueError as error:
            raise ValueError(f"unknown parent source extra: {path}") from error
        if source not in sources:
            raise ValueError(f"cached code lacks a declared source: {path}")
        expected_cache = Path(importlib.util.cache_from_source(str(source), optimization="")).resolve()
        if path != expected_cache:
            raise ValueError(f"unsupported parent bytecode cache name: {path}")
        payload = path.read_bytes()
        if len(payload) != identity["bytes"] or hashlib.sha256(payload).hexdigest().lower() != str(identity["sha256"]).lower():
            raise ValueError(f"parent bytecode changed while read: {path}")
        if len(payload) < 16 or payload[:4] != importlib.util.MAGIC_NUMBER or struct.unpack("<I", payload[4:8])[0] != 0:
            raise ValueError(f"unsupported parent bytecode header: {path}")
        if struct.unpack("<II", payload[8:16]) != (int(source.stat().st_mtime) & 0xFFFFFFFF, len(sources[source]) & 0xFFFFFFFF):
            raise ValueError(f"parent bytecode source metadata differs: {path}")
        stream = io.BytesIO(payload[16:])
        try:
            cached = marshal.load(stream)
        except (EOFError, ValueError, TypeError) as error:
            raise ValueError(f"invalid authenticated parent bytecode: {path}") from error
        rebuilt = compile(sources[source], str(source), "exec", dont_inherit=True, optimize=0)
        if stream.read() or not isinstance(cached, types.CodeType) or not _same_frozen_code(cached, rebuilt):
            raise ValueError(f"parent bytecode differs from frozen source: {path}")
        caches.append({"record": identity, "source_id": source.relative_to(source_root).as_posix(),
                       "validation": "bound_cpython311_timestamp_code_fields_equal"})
    code_root.mkdir(parents=True)
    for source, payload in sources.items():
        target = code_root / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    derived = {**closure, "code_root": str(code_root)}
    verify_candidate_source_closure(derived)
    return {"closure": derived, "derivation": {
        "schema_version": 1, "role": "oa_tof_parent_source_closure_derivation",
        "parent_manifest": file_record(parent_manifest_path), "parent_closure": closure_record,
        **({"parent_closure_field": "execution_source_closure"} if embedded_candidate_plan else {}),
        "validated_bytecode": caches, "copied_sources": len(sources),
        "parent_modified": False, "bytecode_executed": False,
    }}


def project_comsol_native_implementation(closure: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reuse the actual freezer identities of the sole raw builder/save owners."""
    declared={item["source_id"]:item for item in closure["sources"]}
    current = "src/msplatform/backends/comsol/matlab/"
    historical = "projects/single_reflection_oa_tof_mass_analyzer/comsol/"
    prefix = current if current + "oatof_build_saved_particle_solution.m" in declared else historical
    names={"native_builder":"oatof_build_saved_particle_solution.m",
           "save_model":"oatof_save_run_model.m"}
    result={}
    for role,name in names.items():
        identifier=prefix+name
        if identifier not in declared:
            raise ValueError("Original native implementation has no comparable saved-stage fact; request the necessary new native stage or analyze sufficient sealed CSV with --postprocess-from")
        result[role]={key:declared[identifier][key] for key in ("source_id","bytes","sha256")}
    return result


def candidate_comsol_source_phases(closure: dict[str, Any]) -> dict[str, Any]:
    """Publish this project's four real COMSOL dependency projections.

    These descriptors do not replace the complete execution source closure.
    They only decide which already-supported operation consumes changed code.
    No process-owner/path transport file is a scientific field identity.
    """
    prefix = "projects/single_reflection_oa_tof_mass_analyzer/"
    sources = {item["source_id"]: item for item in closure["sources"]}
    matlab_prefix = "src/msplatform/backends/comsol/matlab/"
    workflow_prefix = "src/msplatform/workflows/oa_candidate/"
    if matlab_prefix + "oatof_build_model_core.m" not in sources:
        matlab_prefix = prefix + "comsol/"
        workflow_prefix = prefix + "analysis/"
    def records(names: tuple[str, ...]) -> list[dict[str, Any]]:
        missing = set(names)-sources.keys()
        if missing:
            raise ValueError(f"COMSOL phase lacks declared frozen sources: {sorted(missing)}")
        return [{key: sources[name][key] for key in ("source_id", "bytes", "sha256")}
                for name in sorted(names)]
    native_names = ("src/msplatform/backends/comsol/matlab/load_oatof_contract.m",
        "src/msplatform/backends/comsol/matlab/configure_oatof_segmented_output.m")
    native_names += tuple(matlab_prefix+name for name in (
        "oatof_build_detector_geometry.m", "oatof_build_drift_geometry.m",
        "oatof_build_grid_geometry.m", "oatof_build_mesh.m",
        "oatof_build_reflectron_geometry.m", "oatof_configure_particle_model.m",
        "oatof_parse_field_idealization.m"))
    old_mesh = "common/comsol/add_comsol_size_feature.m"
    new_mesh = ("src/msplatform/backends/comsol/matlab/add_comsol_size_feature.m",
                "src/msplatform/backends/comsol/matlab/read_comsol_mesh_size_controls.m")
    if old_mesh in sources and any(name in sources for name in new_mesh):
        raise ValueError("COMSOL phase declares both historical and current mesh helpers")
    native_names += (old_mesh,) if old_mesh in sources else new_mesh
    native_names += ("src/msplatform/backends/comsol/matlab/oatof_cpt_solver_policy.m",
        "src/msplatform/backends/comsol/matlab/oatof_read_cartesian_release.m",
        "src/msplatform/backends/comsol/matlab/oatof_build_accelerator_geometry.m",
        "src/msplatform/backends/comsol/matlab/build_sectioned_geometry.m",
        "src/msplatform/backends/comsol/matlab/build_accelerator_grids.m")
    export_names = ("src/msplatform/backends/comsol/matlab/oatof_extract_detector_arrivals.m",
        "src/msplatform/backends/comsol/matlab/oatof_detector_arrival_reducer.m")
    export_names += ("src/msplatform/backends/comsol/matlab/run_candidate_contract_build.m",)
    export_names += tuple(matlab_prefix+name for name in (
        "oatof_build_model_core.m", "oatof_postprocess_saved_solution.m", "reextract_oatof_saved_solution.m",
        "oatof_write_saved_particle_context.m", "oatof_export_detector_events.m",
        "oatof_particle_plot_view.m", "oatof_create_result_nodes.m",
        "oatof_validate_candidate_solution.m"))
    analysis_names = tuple(workflow_prefix+name for name in (
        "analyze_comsol_detector_events.py", "reference_analysis.py", "reference_analysis_core.py"))
    analysis_names += tuple(name for name in sources if name.startswith("common/analysis/"))
    analysis_names += tuple(name for name in sources if (
        name == "src/msplatform/__init__.py"
        or name.startswith(("src/msplatform/analysis/", "src/msplatform/io/"))))
    # Preserve the actual selected package and reader records without backfilling old closures.
    analysis_names += tuple(name for name in sources if name in (
        "src/msplatform/results/__init__.py", "src/msplatform/results/single_reflection_particle_table.py"))
    # Historical closures retain the source authority they actually froze.
    analysis_names += tuple(name for name in sources if name == "common/contracts/file_identity.py")
    analysis_names += (prefix+"config/analysis_contract.json",)
    sync_names = (matlab_prefix+"verify_oatof_comsol_sync.m",
                  "src/msplatform/backends/comsol/matlab/load_oatof_contract.m", "src/msplatform/backends/comsol/matlab/oatof_cpt_solver_policy.m")
    import ast
    identifier = "src/msplatform/workflows/oa_candidate/candidate_comsol_stage.py"
    tree = ast.parse(candidate_frozen_source_text(closure)[identifier])
    return {"native": {"sources": records(native_names),
                        "implementation": project_comsol_native_implementation(closure),
                        "dispatch": _comsol_dispatch_from_tree(tree,"native"),
                        "entrypoint": project_comsol_named_entry(closure),
                        "task_invocation": project_comsol_build_invocation(closure)},
            "export": {"sources": records(export_names)},
            "analysis": {"sources": records(analysis_names)},
            "sync": {"sources": records(sync_names),"dispatch": _comsol_dispatch_from_tree(tree,"sync")}}




def project_comsol_dispatch(closure: dict[str, Any], phase: str) -> str:
    """Bind the sole pure scientific task/env constructor used by production."""
    import ast
    if phase not in {"native", "sync"}:
        raise ValueError("COMSOL dispatch needs native or sync")
    identifier = "src/msplatform/workflows/oa_candidate/candidate_comsol_stage.py"
    source = candidate_frozen_source_text(closure)[identifier]
    return _comsol_dispatch_from_tree(ast.parse(source), phase)


def _comsol_dispatch_from_tree(tree: Any, phase: str) -> str:
    """Project one unchanged task identity from this operation's parsed source."""
    import ast
    functions = {node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    name = "comsol_native_inputs" if phase == "native" else "comsol_sync_inputs"
    if sum(isinstance(node,ast.FunctionDef) and node.name == name for node in tree.body) != 1:
        raise ValueError("COMSOL scientific inputs need one actual production constructor")
    return ast.dump(functions[name],include_attributes=False)


def project_comsol_named_entry(closure: dict[str, Any]) -> str:
    """Bind the actual named native parameter entry, with no historical lowering."""
    path=Path(closure["code_root"])/"src/msplatform/backends/comsol/matlab/run_oatof_model.m"
    return path.read_bytes().decode("utf-8")


def project_comsol_build_invocation(closure: dict[str, Any]) -> str:
    """Bind the actual local scientific input reader/build, not its report tail."""
    path=Path(closure["code_root"])/"src/msplatform/backends/comsol/matlab/run_candidate_contract_build.m"
    source=path.read_bytes().decode("utf-8")
    marker="function [result,contract,modelPath,contractPath]=build_candidate_model()\n"
    if source.count(marker)!=1:
        raise ValueError("Candidate build task needs its unique actual scientific input/build function")
    return marker+source.split(marker,1)[1]


def candidate_frozen_source_text(closure: dict[str, Any]) -> dict[str, str]:
    """Read only the already verified small text members of this exact closure."""
    verify_candidate_source_closure(closure)
    root = Path(closure['code_root'])
    return {record['source_id']:(root/record['source_id']).read_bytes().decode('utf-8')
            for record in closure['sources'] if Path(record['source_id']).suffix in {'.py','.m','.ps1','.txt'}}
