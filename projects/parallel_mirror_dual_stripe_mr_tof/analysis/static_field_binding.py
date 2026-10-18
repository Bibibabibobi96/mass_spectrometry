"""Fixed COMSOL scalar-V flight binding; inherit sealed PA identities without copying."""
from __future__ import annotations

import argparse
import csv
import copy
import json
import math
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Mapping

from common.contracts.verify_run_manifest import verify_record


_record_indexes: ContextVar[dict | None] = ContextVar("static_field_record_indexes", default=None)
_retired_operator_records: ContextVar[dict | None] = ContextVar("retired_operator_records", default=None)
_operator_projections: ContextVar[dict | None] = ContextVar("operator_projections", default=None)


def _within_record_lookup(function):
    """Reuse sealed metadata only within one recursive load, releasing it on exit."""
    @wraps(function)
    def load(*args, **kwargs):
        if _record_indexes.get() is not None:
            return function(*args, **kwargs)
        token = _record_indexes.set({})
        projection_token = _operator_projections.set({})
        try:
            result = function(*args, **kwargs)
            if isinstance(result, dict) and _operator_projections.get():
                result["operator_ancestry_projections"] = copy.deepcopy(list(_operator_projections.get().values()))
            return result
        finally:
            _operator_projections.reset(projection_token)
            _record_indexes.reset(token)
    return load


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sealed_record(manifest_path: Path, path: Path) -> dict[str, Any]:
    """Read a unique successful seal; this alone does not authorize asset use."""
    indexes = _record_indexes.get()
    key = manifest_path.resolve()
    index = indexes.get(key) if indexes is not None else None
    if index is None:
        manifest = _read(manifest_path)
        if manifest.get("status") != "success":
            raise ValueError("static field asset manifest must be successful")
        index = {}
        for record in [*manifest["outputs"], *manifest.get("inputs", {}).values()]:
            if isinstance(record, dict):
                index.setdefault(Path(record.get("path", "")).resolve(), []).append(record)
        if indexes is not None:
            indexes[key] = index
    resolved_path = path.resolve()
    matches = index.get(resolved_path, [])
    identities = {(r["bytes"], r.get("sha256")) for r in matches}
    if not matches or len(identities) != 1:
        raise ValueError(f"static asset lacks a unique sealed record: {path}")
    record = matches[0]
    return copy.deepcopy(record)


def _record(manifest_path: Path, path: Path) -> dict[str, Any]:
    record = _sealed_record(manifest_path, path)
    if not path.is_file() or path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"static asset is missing or changed size: {path}")
    projections = _operator_projections.get()
    if (projections is not None and str(manifest_path.resolve()) in projections
            and path.suffix.lower() in {".json", ".gem", ".lua", ".log", ".txt"}):
        verify_record("operator_ancestry_consumed_record", record, base_dir=manifest_path.parent)
        projections[str(manifest_path.resolve())]["consumed_records"][str(path.resolve())] = record
    return record


def _native_payload_record(manifest: Path, path: Path) -> dict[str, Any]:
    """Use retired identities only inside the named non-live ancestry loader."""
    allowed = _retired_operator_records.get() or {}
    identity = (manifest.resolve(), path.resolve())
    if identity not in allowed:
        return _record(manifest, path)
    record = _sealed_record(manifest, path)
    if record != allowed[identity]:
        raise ValueError("retired operator payload differs from its approved original seal")
    return record


def _validate_operator_consumption(plan: dict, owner: Path) -> None:
    """Bind a new consumer's historical projection to its own immutable seal."""
    value = plan.get("operator_ancestry_projection_path")
    if value is None:
        return
    path = Path(value)
    verify_record("operator_ancestry_projection", _record(owner, path), base_dir=owner.parent)
    document = _read(path)
    if (set(document) != {"schema_version", "role", "projections", "claim"}
            or document["schema_version"] != 1
            or document["role"] != "mrtof_native_operator_ancestry_consumption"
            or not isinstance(document["projections"], list) or not document["projections"]):
        raise ValueError("unsupported frozen operator ancestry consumption")
    for index, projection in enumerate(document["projections"]):
        if (set(projection) != {"schema_version", "role", "consumer_projection_id", "usable_as_field_source",
                               "target_manifest", "retirement_receipt", "consumed_records"}
                or projection["schema_version"] != 1
                or projection["role"] != "mrtof_native_operator_ancestry_projection"
                or projection["consumer_projection_id"] != "ip-retired-scalar-operator-ancestry"
                or projection["usable_as_field_source"] is not False):
            raise ValueError("invalid frozen non-live operator ancestry projection")
        records = [projection["target_manifest"], projection["retirement_receipt"],
                   *projection["consumed_records"].values()]
        for record_index, record in enumerate(records):
            source = Path(record["path"])
            frozen = owner.parent / "inputs" / (f"operator_ancestry_{index}_{record_index}" + source.suffix)
            sealed = _record(owner, frozen)
            if any(record.get(k) != sealed.get(k) for k in ("bytes", "sha256")):
                raise ValueError("operator ancestry input differs from its consumer seal")
            verify_record("frozen_operator_ancestry_copy", sealed)
            verify_record("frozen_operator_ancestry_input", record)


@_within_record_lookup
def _load_operator_ancestry(path: Path, *, copy_owner: Path | None = None,
                            frozen_copy: Path | None = None) -> dict[str, Any]:
    """Validate historical operator metadata, never a usable scalar-field source.

    Only a completed public retirement of all five IP scalar/surface pairs
    permits absent payloads. All current loads retain the ordinary strict path.
    """
    from common.contracts.solver_review_retirement import RECEIPT_NAME, verify_retirement
    from common.contracts.file_identity import file_sha256

    descriptor = _read(path)
    owner = Path(descriptor["parent"]["manifest"]).resolve()
    receipt_path = owner.parent / RECEIPT_NAME
    if not receipt_path.is_file():
        return load_binding(path)
    if (descriptor.get("role") != "mrtof_native_static_field_binding"
            or descriptor.get("accelerator_provider") != "dual_pressure_rectilinear_ion_processor"
            or any(key in descriptor for key in ("materialization", "local_domain_update", "response_level_reuse", "consumer_view"))
            or len(descriptor.get("refinement_windows", [])) != 4):
        raise ValueError("retired operator ancestry requires the original full five-level ordinary IP binding")
    expected = {}
    for level in (descriptor["parent"], *descriptor["refinement_windows"]):
        if Path(level["manifest"]).resolve() != owner or not level.get("surface_path"):
            raise ValueError("retired operator requires five same-owner scalar/surface pairs")
        pa, surface = Path(level["pa_path"]).resolve(), Path(level["surface_path"]).resolve()
        if surface != Path(str(pa) + "-surf"):
            raise ValueError("retired operator fractional surface is not paired with its PA")
        for payload in (pa, surface):
            expected[payload] = _sealed_record(owner, payload)
    if len(expected) != 10:
        raise ValueError("retired operator requires ten distinct scalar/surface records")
    receipt = _read(receipt_path)
    target_record = dict(path=str(owner), bytes=owner.stat().st_size, sha256=file_sha256(owner))
    if any(receipt.get("target_manifest", {}).get(k) != target_record[k] for k in ("bytes", "sha256")):
        raise ValueError("retired operator target manifest differs from its public receipt")
    removed = receipt.get("removed_files", [])
    actual = {owner.parent / row["path"]: row for row in removed}
    if (len(actual) != 10 or len(removed) != 10 or set(actual) != set(expected)
            or receipt.get("selected_heavy_paths") != sorted(p.relative_to(owner.parent).as_posix() for p in expected)
            or any(any(actual[p].get(k) != r.get(k) for k in ("bytes", "sha256")) for p, r in expected.items())):
        raise ValueError("retired operator receipt must remove exactly the original five scalar/surface pairs")
    projections = _operator_projections.get()
    key = str(owner)
    receipt_record = dict(path=str(receipt_path), bytes=receipt_path.stat().st_size, sha256=file_sha256(receipt_path))
    if key not in projections:
        verify_retirement(owner.parent)
        projections[key] = dict(schema_version=1, role="mrtof_native_operator_ancestry_projection",
            consumer_projection_id="ip-retired-scalar-operator-ancestry", usable_as_field_source=False,
            target_manifest=target_record,
            retirement_receipt=receipt_record, consumed_records={})
    elif (projections[key]["retirement_receipt"] != receipt_record
          or projections[key]["target_manifest"] != target_record):
        raise ValueError("operator retirement receipt changed during recursive load")
    canonical = owner.parent / "results/field_binding.json"
    sealed = _record(owner, canonical)
    verify_record("operator_ancestry_binding", sealed)
    if descriptor != _read(canonical):
        raise ValueError("operator ancestry descriptor differs from the complete original declaration")
    if copy_owner is not None:
        copy_path = frozen_copy if frozen_copy is not None else path
        copy_record = _record(copy_owner, copy_path)
        verify_record("operator_ancestry_binding_copy", copy_record, base_dir=copy_owner.parent)
        if _read(copy_path) != descriptor:
            raise ValueError("operator ancestry locator differs from its consumer-owned frozen declaration")
        projections[key]["consumed_records"].update({str(copy_path.resolve()): copy_record,
            str(copy_owner.resolve()): dict(path=str(copy_owner.resolve()), bytes=copy_owner.stat().st_size,
                                           sha256=file_sha256(copy_owner))})
    elif path.resolve() != canonical.resolve() or frozen_copy is not None:
        raise ValueError("operator ancestry copy requires its explicit sealed consumer owner")
    token = _retired_operator_records.set({**(_retired_operator_records.get() or {}),
        **{(owner, p): r for p, r in expected.items()}})
    try:
        result = load_binding(path)
    finally:
        _retired_operator_records.reset(token)
    result["usable_as_field_source"] = False
    return result


def resolve_native_refine_numerics(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the sole contract-owned native Refine stopping value, in volts."""
    try:
        refine = contract["simion"]["numerical_profiles"]["native_static_field"]["refine"]
    except (KeyError, TypeError) as exc:
        raise ValueError("native field requires its numerical contract Refine profile") from exc
    if not isinstance(refine, Mapping) or set(refine) != {"convergence_v"}:
        raise ValueError("native Refine profile requires only convergence_v")
    value = refine["convergence_v"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("native convergence_v must be finite and positive")
    return dict(refine_stopping="contract_convergence", convergence_v=float(value))


def native_refine_numerics(plan: Mapping[str, Any], manifest: Path) -> dict[str, Any]:
    """Verify a sealed plan's stopping authority; read legacy defaults without rewriting them."""
    remaining = dict(plan)
    path = remaining.pop("numerical_contract_path", None)
    if path is not None:
        if not isinstance(path, str) or not path:
            raise ValueError("native numerical_contract_path must identify its frozen contract")
        contract_path = Path(path)
        verify_record("numerical_contract", _record(manifest, contract_path), base_dir=manifest.parent)
        numerics = resolve_native_refine_numerics(_read(contract_path))
        if isinstance(remaining.get("convergence_v"), bool):
            raise ValueError("native plan convergence_v must be numeric, not Boolean")
        if any(remaining.pop(key, None) != value for key, value in numerics.items()):
            raise ValueError("native plan stopping differs from its sealed numerical contract")
    else:
        if remaining.get("refine_stopping", "installed_default") != "installed_default":
            raise ValueError("native nondefault stopping lacks its numerical contract")
        numerics = dict(refine_stopping="installed_default")

    def has_convergence(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any("convergence" in key.lower() or has_convergence(item) for key, item in value.items())
        return isinstance(value, list) and any(has_convergence(item) for item in value)

    if has_convergence(remaining):
        raise ValueError("native plan contains an unbound convergence override")
    return dict(solver="SIMION2020", **numerics, surface="fractional")


def native_numerics_match(binding: Mapping[str, Any], numerical_contract_path: str | Path) -> bool:
    """Check every loaded native level against the requested contract, without PA I/O."""
    expected = resolve_native_refine_numerics(_read(Path(numerical_contract_path)))
    if binding.get("mode") != "native_static_pa":
        raise ValueError("native numerical matching requires a loaded native binding")
    return all(all(level["native_solver_numerics"].get(key) == value for key, value in expected.items())
               for level in (binding, *binding["refinement_windows"]))


def _validate_pitch_mm(grid: dict[str, Any]) -> list[float]:
    """Require current scalar-grid spacing [dx, dy, dz] in mm; no scalar fallback."""
    pitch = grid.get("pitch_mm")
    if not isinstance(pitch, list) or len(pitch) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v <= 0 for v in pitch):
        raise ValueError("pitch_mm must be [dx, dy, dz] with finite positive numeric spacing")
    return [float(v) for v in pitch]


def ideal_sheet_projection(assembly: dict[str, Any], grid: dict[str, Any]) -> list[dict[str, Any]]:
    """Project frozen transparent OA sheets to scalar nodes, without snapping z.

    These are interpolation markers only, not collision solids or PA voltages.
    Lua applies each range only at valid-mask nodes and keeps the raw potential.
    """
    oa = assembly["accelerator_resolved_electrodes"]
    translation = [float(a) + float(b) for a, b in zip(
        oa["local_to_pa_translation_mm"], assembly["accelerator_iob_origin_mm"])]
    origin = [float(v) for v in grid["origin_mm"]]
    pitch = _validate_pitch_mm(grid)
    dimensions = grid["dimensions"]
    projected = []
    for support in oa["grid_supports"]:
        sheet = support["ideal_sheet_mm"]
        z = float(sheet["z_mm"]) + translation[2]
        box = [float(sheet[f"{axis}_{edge}_mm"]) + translation[a]
               for a, axis in enumerate(("x", "y")) for edge in ("min", "max")]
        if not all(math.isfinite(v) for v in box) or box[0] > box[1] or box[2] > box[3]:
            raise ValueError("invalid frozen OA ideal sheet aperture")
        if not math.isfinite(z):
            raise ValueError("invalid frozen OA ideal sheet z")
        if z < origin[2] or z > origin[2] + (int(dimensions[2])-1)*pitch[2] or any(
                box[2*a+1] < origin[a] or box[2*a] > origin[a] + (int(dimensions[a])-1)*pitch[a]
                for a in range(2)):
            continue
        qz = (z - origin[2]) / pitch[2]
        if not qz.is_integer():
            raise ValueError("OA ideal sheet z must align with the scalar grid; snapping is forbidden")
        low = [max(0, math.ceil((box[2*a] - origin[a]) / pitch[a])) for a in range(2)]
        high = [min(int(dimensions[a])-1, math.floor((box[2*a+1] - origin[a]) / pitch[a]))
                for a in range(2)]
        k = int(qz)
        if k < 0 or k >= int(dimensions[2]) or any(lo > hi for lo, hi in zip(low, high)):
            continue
        projected.append({"component_electrode_id": int(support["component_electrode_id"]),
                          "global_box_mm": [*box, z], "i_min": low[0], "i_max": high[0],
                          "j_min": low[1], "j_max": high[1], "k": k})
    return projected


def _load_export(manifest: Path, export_sources: dict[str, str | dict[str, str]] | None = None) -> dict[str, Any]:
    """Read one sealed scalar export's small metadata and inherited asset records."""
    filenames = dict((
        ("voltage_authority", "frozen_input.json"), ("geometry_authority", "resolved_geometry.json"),
        ("scalar_pa", "field_v.pa"), ("valid_pa", "field_valid.pa"), ("export_result", "result.json")))
    if export_sources is None:
        sources = {name: manifest.parent / "inputs" / filename for name, filename in filenames.items()}
        asset_manifests = {name: manifest for name in sources}
    else:
        if not isinstance(export_sources, dict) or set(export_sources) != set(filenames):
            raise ValueError("export_sources requires all five named export paths with their role filenames")
        sources, asset_manifests = {}, {}
        for name, spec in export_sources.items():
            if isinstance(spec, dict):
                if set(spec) != {"path", "manifest"} or any(not isinstance(v, str) or not v for v in spec.values()):
                    raise ValueError("export source descriptor requires path/manifest only")
                p, owner = spec["path"], Path(spec["manifest"])
                owner = owner if owner.is_absolute() else manifest.parent / owner
                _record(manifest, owner)
            else:
                p, owner = spec, manifest
            if not isinstance(p, str) or not p or Path(p).name != filenames[name]:
                raise ValueError("export_sources requires all five named export paths with their role filenames")
            sources[name] = Path(p) if Path(p).is_absolute() else manifest.parent / p
            asset_manifests[name] = owner
    records = {name: _record(asset_manifests[name], p) for name, p in sources.items()}
    authority, geometry, grid = (_read(sources[n]) for n in ("voltage_authority", "geometry_authority", "export_result"))
    if grid.get("status") != "success" or grid.get("field_units") != "V":
        raise ValueError("static binding requires a successful scalar-V export")
    _validate_pitch_mm(grid)
    return dict(sources={n: str(p.resolve()) for n, p in sources.items()}, records=records,
                authority=authority, geometry=geometry, grid=grid)


def _validate_active_box_mm(box: Any, grid: dict[str, Any]) -> list[list[float]]:
    """Require a finite 3-D takeover box with full native gradient support halo."""
    if not isinstance(box, list) or len(box) != 3 or any(
            not isinstance(axis, list) or len(axis) != 2 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in axis) or axis[0] >= axis[1] for axis in box):
        raise ValueError("active_box_mm must contain three finite increasing [min,max] bounds")
    pitch = _validate_pitch_mm(grid)
    origin, dimensions = grid.get("origin_mm"), grid.get("dimensions")
    if not isinstance(origin, list) or len(origin) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in origin):
        raise ValueError("refinement grid requires three finite origin_mm coordinates")
    if not isinstance(dimensions, list) or len(dimensions) != 3 or any(
            isinstance(v, bool) or not isinstance(v, int) or v < 3 for v in dimensions):
        raise ValueError("refinement grid requires three integer dimensions with support halo")
    for a, (lower, upper) in enumerate(box):
        qlo, qhi = (lower-origin[a])/pitch[a], (upper-origin[a])/pitch[a]
        if not all(math.isfinite(q) for q in (qlo, qhi)) or (
                math.floor(qlo)-1 < 0 or math.ceil(qhi)+1 >= dimensions[a]):
            raise ValueError(f"refinement active_box_mm axis {a} lacks floor-1..ceil+1 support halo")
    return [[float(v) for v in axis] for axis in box]


def _validate_native_surface_absence(manifest: Path, pa: Path) -> None:
    """Accept no sidecar only when the successful build sealed its non-generation."""
    evidence = _read(manifest)
    companion = Path(str(pa.resolve()) + "-surf")
    if companion.exists() or any(
            isinstance(r, dict) and Path(r.get("path", "")).resolve() == companion
            for r in [*evidence.get("outputs", []), *evidence.get("inputs", {}).values()]):
        raise ValueError("native surface absence conflicts with a file or sealed surface record")
    summary_path = manifest.parent / "summary.json"
    verify_record("summary", _record(manifest, summary_path), base_dir=manifest.parent)
    summary = _read(summary_path)
    if summary.get("refine_performed") is False:
        receipt_path = manifest.parent / "results" / "crop_receipt.json"
        plan_path = manifest.parent / "results" / "consumer_plan.json"
        for name, path in (("crop_receipt", receipt_path), ("consumer_plan", plan_path)):
            verify_record(name, _record(manifest, path), base_dir=manifest.parent)
        receipt, plan = _read(receipt_path), _read(plan_path)
        crop = plan.get("crop", {})
        if (summary.get("status") != "success" or summary.get("crop_completed") is not True
                or summary.get("failure_stage") is not None
                or any(summary.get(key) != {"exists": False, "bytes": None}
                       for key in ("surface_before_crop", "surface_after_crop"))
                or receipt.get("status") != "PASS" or receipt.get("refine_after_crop") is not False
                or crop.get("refine_after_crop") is not False
                or Path(crop.get("receipt_path", "")).resolve() != receipt_path.resolve()
                or Path(receipt.get("output_pa", "")).resolve() != pa.resolve()
                or crop.get("consumer_dimensions") != plan.get("dimensions")
                or any(crop.get(key) != receipt.get(key) for key in (
                    "source_manifest", "source_pa", "full_dimensions", "consumer_dimensions"))):
            raise ValueError("native surface absence lacks successful no-Refine crop evidence")
        samples = [*receipt.get("retained_node_samples", []),
                   *receipt.get("signed_vc_field_samples", [])]
        if (not receipt.get("retained_node_samples") or not receipt.get("signed_vc_field_samples")
                or receipt.get("retained_sample_count") != len(samples)
                or any(not isinstance(row, dict) or "before" not in row
                       or row["before"] != row.get("after") or row["before"] != row.get("reloaded")
                       for row in samples)):
            raise ValueError("native crop retained samples differ before/after/reload")
        source_manifest, source_pa = Path(receipt["source_manifest"]), Path(receipt["source_pa"])
        if source_manifest.resolve() == manifest.resolve() or source_pa.resolve() == pa.resolve():
            raise ValueError("native crop must preserve a distinct original successful source")
        verify_record("crop_source_manifest", _record(manifest, source_manifest), base_dir=manifest.parent)
        original = _record(source_manifest, source_pa)
        inherited = _record(manifest, source_pa)
        if any(original.get(key) != inherited.get(key) for key in ("bytes", "sha256")):
            raise ValueError("native crop source PA identity differs from its original seal")
        source_plan_path = source_manifest.parent / "inputs" / "plan.json"
        verify_record("crop_source_plan", _record(source_manifest, source_plan_path),
                      base_dir=source_manifest.parent)
        source_plan = _read(source_plan_path)
        for name in ("frozen_input", "resolved_geometry"):
            frozen_path = source_manifest.parent / "inputs" / f"{name}.json"
            verify_record(name, _record(source_manifest, frozen_path),
                          base_dir=source_manifest.parent)
            if _read(frozen_path) != _read(Path(plan[name])):
                raise ValueError("native crop authority differs from original sealed source copy")
        if (source_plan.get("dimensions") != crop["full_dimensions"]
                or source_plan.get("pitch_mm") != plan.get("pitch_mm")
                or source_plan.get("box_mm", [])[:3] != plan.get("box_mm", [])[:3]
                or any(source_plan.get(key) != plan.get(key) for key in (
                    "frozen_input", "resolved_geometry", "parent_manifest", "parent_pa", "active_box_mm",
                    "boundary_mode", "mirror_axes", "surface", "ordinary_static_pa"))
                or any(not isinstance(n, int) or isinstance(n, bool) or n < 3 or n > full
                       for n, full in zip(crop["consumer_dimensions"], crop["full_dimensions"]))
                or _read(source_manifest.parent / "summary.json").get("refine_completed") is not True):
            raise ValueError("native crop differs from the original solved grid")
        _validate_native_surface_absence(source_manifest, source_pa)
        return
    for name, path in (("gem2pa_log", manifest.parent / "logs" / "gem2pa.log"),):
        record = _record(manifest, path)
        verify_record(name, record, base_dir=manifest.parent)
    if (summary.get("status") != "success" or summary.get("refine_completed") is not True
            or summary.get("failure_stage") is not None
            or any(summary.get(key) != {"exists": False, "bytes": None}
                   for key in ("surface_before_builder", "surface_after_builder"))
            or "gem2pa_seconds" not in summary.get("stage_seconds", {})
            or any(row.get("name") == companion.name for row in summary.get("native_outputs", []))
            or not any(row.get("name") == pa.name for row in summary.get("native_outputs", []))):
        raise ValueError("native surface absence lacks successful compile/Refine non-generation evidence")


def _load_native_level(spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve ordinary native PA/surface and sealed physical/numerical authorities."""
    manifest = Path(spec["manifest"])
    paths = {name: Path(spec[key]) for name, key in (
        ("scalar_pa", "pa_path"),
        ("voltage_authority", "voltage_authority_path"),
        ("geometry_authority", "geometry_authority_path"),
        ("numerical_plan", "numerical_plan_path"))}
    records = {name: (_native_payload_record(manifest, path) if name == "scalar_pa" else _record(manifest, path))
               for name, path in paths.items()}
    if spec["surface_path"] is None:
        _validate_native_surface_absence(manifest, paths["scalar_pa"])
    else:
        paths["surface"] = Path(spec["surface_path"])
        records["surface"] = _native_payload_record(manifest, paths["surface"])
        if str(paths["surface"].resolve()) != str(paths["scalar_pa"].resolve()) + "-surf":
            raise ValueError("native PA requires its same-basename fractional surface")
    plan = _read(paths["numerical_plan"])
    _validate_operator_consumption(plan, manifest)
    if spec["surface_path"] is None and plan.get("crop") is not None:
        for name, key in (("voltage_authority", "frozen_input"), ("geometry_authority", "resolved_geometry")):
            original_path = Path(plan[key])
            verify_record(name, _record(manifest, original_path), base_dir=manifest.parent)
            if _read(original_path) != _read(paths[name]):
                raise ValueError("native crop authority differs from its solved source")
    numerics = native_refine_numerics(plan, manifest)
    grid = spec["grid"]
    pitch = _validate_pitch_mm(grid)
    origin, dimensions = grid.get("origin_mm"), grid.get("dimensions")
    if (grid.get("symmetry") != "x" or not isinstance(origin, list) or len(origin) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in origin)
            or origin[0] != 0 or not isinstance(dimensions, list) or len(dimensions) != 3
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 3 for v in dimensions)):
        raise ValueError("native grid requires x symmetry, x origin zero and finite 3-D dimensions")
    box = plan.get("box_mm")
    if (not isinstance(box, list) or len(box) != 6 or box[:3] != origin
            or plan.get("pitch_mm") != pitch or plan.get("dimensions") != dimensions
            or plan.get("mirror_axes") != ["x"] or plan.get("surface") != "fractional"
            or plan.get("ordinary_static_pa") is not True
            or any(not math.isclose(box[a+3], origin[a] + (dimensions[a]-1)*pitch[a],
                                    rel_tol=0, abs_tol=1e-9) for a in range(3))):
        raise ValueError("native grid differs from sealed numerical plan")
    return dict(mode="native_static_pa", manifest=str(manifest.resolve()), grid=grid,
                numerical_plan_path=str(paths["numerical_plan"].resolve()),
                native_solver_numerics=numerics,
                authority=_read(paths["voltage_authority"]), geometry=_read(paths["geometry_authority"]),
                sources={**{name: str(p.resolve()) for name, p in paths.items()},
                         "surface": str(paths["surface"].resolve()) if "surface" in paths else None},
                records={**records, "surface": records.get("surface")})


def _native_active_box(box: Any, grid: dict[str, Any]) -> list[list[float]]:
    """Allow x-axis support across the symmetry plane, never across the outer faces."""
    if (not isinstance(box, list) or len(box) != 3 or not isinstance(box[0], list)
            or len(box[0]) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                    or not math.isfinite(v) for v in box[0]) or box[0][0] >= box[0][1]):
        raise ValueError("invalid native active_box_mm")
    mirrored = copy.deepcopy(box)
    extent = max(abs(v) for v in box[0])
    # Validate y/z unchanged; x lower halo is supplied by the actual native mirror.
    mirrored[0] = [0, extent]
    support_grid = copy.deepcopy(grid)
    support_grid["origin_mm"][0] = -grid["pitch_mm"][0]
    support_grid["dimensions"][0] += 1
    _validate_active_box_mm(mirrored, support_grid)
    return [[float(v) for v in axis] for axis in box]


def validate_native_consumer_view(value: Any) -> dict[str, Any] | None:
    """Validate the storage-only centre-plane view, not a reduced field solve."""
    if value is None:
        return None
    if value != {"kind": "x_symmetry_plane", "stored_x_nodes": 5}:
        raise ValueError("unsupported native consumer_view; five-node x symmetry plane required")
    return dict(value)


def _load_native_binding(binding: dict[str, Any], *, pure_response: bool = False) -> dict[str, Any]:
    """Consume sealed native static fields, with independent explicit collision assets."""
    provider = binding.get("accelerator_provider")
    ip_replacement = provider == "dual_pressure_rectilinear_ion_processor"
    required = {"schema_version", "role", "parent", "refinement_windows", "instances"}
    if ip_replacement:
        required |= {"accelerator_provider", "assembly_scope", "replacement_assembly"}
    optional = {"consumer_view", "local_domain_update", "response_level_reuse"} if ip_replacement else {"consumer_view"}
    if (binding.get("schema_version") != 1 or set(binding) - optional != required):
        raise ValueError("unsupported native static binding declaration")
    base = _load_native_level(binding["parent"])
    view = validate_native_consumer_view(binding.get("consumer_view"))
    contract = _read(Path(_read(Path(base["numerical_plan_path"]))["numerical_contract_path"])) if view else None
    if view and contract["simion"]["numerical_profiles"]["native_static_field"].get("consumer_view") != view:
        raise ValueError("native consumer view differs from frozen numerical authority")
    parent_plan = _read(Path(base["numerical_plan_path"]))
    parent_boundary = parent_plan.get("boundary_mode")
    # The original sealed parent predates the named boundary field; its actual
    # geometry declaration explicitly records five ground faces and no x0 wall.
    if parent_boundary is None and "Five outer e(0) faces, no x=0 wall" in parent_plan.get("physical_expression", ""):
        parent_boundary = "grounded_enclosure"
    if parent_boundary != "grounded_enclosure":
        raise ValueError("native parent requires the frozen grounded enclosure boundary")
    base["native_solver_numerics"]["boundary_mode"] = parent_boundary
    authority, geometry = base["authority"], base["geometry"]
    values = authority.get("analyzer_electrode_voltages_v")
    if (not isinstance(values, list) or len(values) != 20
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)):
        raise ValueError("native field requires complete finite full20 voltage authority")
    windows, names = [], set()
    if not isinstance(binding["refinement_windows"], list):
        raise ValueError("native refinement_windows must be ordered")
    for spec in binding["refinement_windows"]:
        name = spec["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("native window names must be unique and nonempty")
        local = _load_native_level(spec)
        plan = _read(Path(local["sources"]["numerical_plan"]))
        if (local["authority"] != authority or local["geometry"] != geometry
                or Path(plan["parent_manifest"]).resolve() != Path(spec["parent_manifest"]).resolve()
                or plan.get("boundary_mode") != "x_mirror_five_faces"):
            raise ValueError("native window physical authority or five-face parent differs")
        local.update(name=name, active_box_mm=_native_active_box(spec["active_box_mm"], local["grid"]))
        local["native_solver_numerics"]["boundary_mode"] = plan["boundary_mode"]
        windows.append(local)
        names.add(name)
    # Boundary ancestry is independent of first-match flight priority. Resolve
    # sealed PA identities, so a fine window may precede its E-level source.
    levels = [base, *windows]
    if view:
        for level in levels:
            if level["grid"]["dimensions"][0] != view["stored_x_nodes"]:
                raise ValueError("native consumer view dimensions differ")
            plan = _read(Path(level["numerical_plan_path"]))
            if plan.get("consumer_view") != view or plan.get("refine_performed") is not False:
                raise ValueError("consumer view must retain its original three-dimensional solve")
            if "consumer_view_source" in plan:
                source = _load_native_level(plan["consumer_view_source"])
                expected = copy.deepcopy(source["grid"])
                expected["dimensions"][0] = view["stored_x_nodes"]
                receipt_path = Path(plan["consumer_view_receipt_path"])
                owner = Path(level["manifest"])
                verify_record("consumer_view_crop", _record(owner, receipt_path), base_dir=owner.parent)
                receipt = _read(receipt_path)
                if (level["grid"] != expected or level["authority"] != source["authority"]
                        or level["geometry"] != source["geometry"] or receipt.get("status") != "PASS"
                        or receipt.get("refine_after_crop") is not False
                        or receipt.get("full_dimensions") != source["grid"]["dimensions"]
                        or receipt.get("consumer_dimensions") != expected["dimensions"]):
                    raise ValueError("consumer view crop differs from sealed three-dimensional source")
            elif "materialization_receipt_path" not in plan:
                raise ValueError("consumer view lacks crop or materialization evidence")
    identities = [(Path(level["manifest"]).resolve(), Path(level["sources"]["scalar_pa"]).resolve())
                  for level in levels]
    parents = {}
    for index, local in enumerate(windows, 1):
        plan = _read(Path(local["numerical_plan_path"]))
        identity = (Path(plan["parent_manifest"]).resolve(), Path(plan["parent_pa"]).resolve())
        if identity not in identities:
            raise ValueError("native window parent differs from declared sealed levels")
        parent_index = identities.index(identity)
        if identity == identities[index]:
            raise ValueError("native boundary source contains a self-reference or cycle")
        if any(levels[other]["grid"] != levels[parent_index]["grid"]
               for other, candidate in enumerate(identities) if candidate == identity):
            raise ValueError("native boundary source aliases have conflicting grids")
        parents[index] = parent_index
        source_grid = levels[parent_index]["grid"]
        box = plan["box_mm"]
        if any(box[a] < source_grid["origin_mm"][a] or box[a+3] >
               source_grid["origin_mm"][a] + (source_grid["dimensions"][a]-1)*source_grid["pitch_mm"][a]
               for a in range(3)):
            raise ValueError("native five-face window extends outside its boundary source domain")
    for index in parents:
        visited = set()
        while index:
            if index in visited:
                raise ValueError("native boundary source contains a self-reference or cycle")
            visited.add(index)
            index = parents[index]
    instances = binding["instances"]
    roles = ["global_fallback", "native_corridor",
             "ion_processor_collision" if ip_replacement else "accelerator", "detector"]
    if not isinstance(instances, list) or [i.get("role") for i in instances] != roles:
        raise ValueError("native binding requires four ordered independent collision instances")
    resolved = []
    for instance in instances:
        origin = instance["origin_mm"]
        if (not isinstance(origin, list) or len(origin) != 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in origin)):
            raise ValueError("collision instance requires finite origin_mm")
        path, manifest = Path(instance["pa_path"]), Path(instance["manifest"])
        resolved.append(dict(instance, pa_path=str(path.resolve()), manifest=str(manifest.resolve()),
                             record=_native_payload_record(manifest, path)))
    assembly = authority["assembly"]
    if ip_replacement:
        _validate_ip_replacement(binding, base, windows, resolved, pure_response=pure_response)
        return dict(binding, **base, instances=resolved, refinement_windows=windows,
                    accelerator_front_z_mm=None)
    if assembly.get("accelerator_provider") == "dual_pressure_rectilinear_ion_processor":
        raise ValueError("IP assembly requires its explicit replacement binding identity")
    if (resolved[2]["origin_mm"] != assembly["accelerator_iob_origin_mm"]
            or geometry["detector"]["box"] != assembly["detector"]["box"]):
        raise ValueError("native collision assembly poses or detector geometry differ")
    oa = assembly["accelerator_resolved_electrodes"]
    solids = [oa["grounded_enclosure"]["outer_box_mm"], oa["repeller"]["solid_box_mm"],
              *[e["frame_outer_box_mm"] for e in oa["grid_supports"]], *[e["outer_box_mm"] for e in oa["rings"]]]
    front = min(b["z_min_mm"] for b in solids) + oa["local_to_pa_translation_mm"][2] + resolved[2]["origin_mm"][2]
    return dict(binding, **base, instances=resolved, refinement_windows=windows, accelerator_front_z_mm=front)


def _validate_ip_fine_extension(binding: dict, base: dict, windows: list, instances: list) -> None:
    """Verify the one declared mixed-owner exception without weakening ordinary fields."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import (
        extend_fine_z_domain, ordinary_pa_file_bytes,
    )
    if [w["name"] for w in windows] != ["ion_processor_local", "positive_integer_grid_a",
                                          "negative_integer_grid_a", "covered_local"]:
        raise ValueError("IP fine extension must retain all four ordered windows")
    fine = windows[0]
    owner = Path(fine["manifest"])
    record = binding["local_domain_update"]
    path = Path(record["path"])
    sealed = _record(owner, path)
    if any(record.get(k) != sealed.get(k) for k in ("path", "bytes", "sha256")):
        raise ValueError("IP fine extension provenance differs from its new owner")
    verify_record("IP fine extension provenance", sealed, base_dir=owner.parent)
    lineage = _read(path)
    if (set(lineage) != {"schema_version", "role", "update", "reused_levels", "source_manifest", "source_binding"}
            or lineage["schema_version"] != 1 or lineage["role"] != "mrtof_ip_fine_domain_update"
            or lineage["reused_levels"] != ["parent", "window_1", "window_2", "window_3"]
            or binding.get("consumer_view") or owner.resolve() == Path(base["manifest"]).resolve()):
        raise ValueError("IP fine extension requires its closed ordinary mixed-owner provenance")
    source_record = lineage["source_binding"]
    source_path = Path(source_record["path"])
    expected_record = _record(owner, source_path)
    if any(source_record.get(k) != expected_record.get(k) for k in ("path", "bytes", "sha256")):
        raise ValueError("IP fine extension source binding differs from its new owner")
    verify_record("IP fine extension source", source_record, base_dir=owner.parent)
    source_descriptor = _read(source_path)
    if source_descriptor.get("local_domain_update") or source_descriptor.get("consumer_view"):
        raise ValueError("IP fine extension source must be an ordinary unextended field")
    source = load_binding(source_path)
    verify_record("IP fine extension source manifest", lineage["source_manifest"])
    if (Path(lineage["source_manifest"]["path"]).resolve() != Path(source["manifest"]).resolve()
            or source["accelerator_provider"] != binding["accelerator_provider"]
            or source["authority"] != base["authority"] or source["geometry"] != base["geometry"]
            or binding["parent"] != source_descriptor["parent"]
            or binding["refinement_windows"][1:] != source_descriptor["refinement_windows"][1:]
            or any(binding["instances"][i] != source_descriptor["instances"][i] for i in (0, 1, 3))):
        raise ValueError("IP fine extension changes reused fields, voltages, geometry or collision ancestry")
    old = source["refinement_windows"][0]
    expected_grid, active = extend_fine_z_domain(old["grid"], old["active_box_mm"], lineage["update"], source["grid"])
    fine_plan = _read(Path(fine["numerical_plan_path"]))
    if (fine["grid"] != expected_grid or fine["active_box_mm"] != active or fine["name"] != old["name"]
            or fine["native_solver_numerics"] != old["native_solver_numerics"]
            or Path(fine_plan["local_domain_update_path"]).resolve() != path.resolve()
            or Path(fine_plan["parent_manifest"]).resolve() != Path(source["manifest"]).resolve()
            or Path(fine_plan["parent_pa"]).resolve() != Path(source["sources"]["scalar_pa"]).resolve()
            or instances[2]["manifest"] != str(owner.resolve())
            or instances[2]["origin_mm"] != expected_grid["origin_mm"]
            or Path(instances[2]["pa_path"]).resolve() != (owner.parent / "simion/ip_collision/ip_collision.pa").resolve()
            or len({i["pa_path"] for i in instances}) != 4
            or instances[2]["pa_path"] == fine["sources"]["scalar_pa"]):
        raise ValueError("IP fine extension changes its declared grid, route, stopping, parent or occupancy owner")
    occupancy_path = owner.parent / "inputs/ip_collision_plan.json"
    verify_record("IP fine occupancy plan", _record(owner, occupancy_path), base_dir=owner.parent)
    occupancy = _read(occupancy_path)
    geometry_path = Path(occupancy["resolved_geometry"])
    verify_record("IP fine occupancy geometry", _record(owner, geometry_path), base_dir=owner.parent)
    if (any(occupancy[k] != expected_grid[k] for k in ("dimensions", "pitch_mm", "symmetry"))
            or occupancy["origin_mm"] != expected_grid["origin_mm"]
            or occupancy.get("refine_performed") is not False or occupancy.get("fast_adjust_performed") is not False
            or _read(geometry_path) != source["geometry"]
            or instances[2]["record"]["bytes"] != ordinary_pa_file_bytes(expected_grid["dimensions"], expected_grid["pitch_mm"])):
        raise ValueError("IP fine occupancy differs from its new full-domain geometry and grid")


def validate_ip_fine_response_reuse(old: dict, source: dict, axis: str) -> None:
    """Accept only the existing pure P1/P2 operator outside its extended fine domain."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_static_field_provider import _response_authority
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import extend_fine_z_domain
    if (axis not in {"p1", "p2"} or old["response_basis"]["axis"] != axis
            or source.get("accelerator_provider") != "dual_pressure_rectilinear_ion_processor"
            or not source.get("local_domain_update") or source.get("consumer_view")
            or _response_authority(source["authority"], old["response_basis"]) != old["authority"]):
        raise ValueError("IP fine response reuse requires same-axis pure35 and an extended ordinary source")
    before = native_response_operator(old, source["authority"])
    after = native_response_operator(source, source["authority"])
    if (before["geometry"] != after["geometry"]
            or before["boundary_parent_indices"] != after["boundary_parent_indices"]
            or len(before["full_solve_grids"]) != 5 or len(after["full_solve_grids"]) != 5
            or any(before["full_solve_grids"][i] != after["full_solve_grids"][i] for i in (0, 2, 3, 4))):
        raise ValueError("IP fine response reuse changes geometry, full solve grids or parent dependencies")
    old_levels, new_levels = [old, *old["refinement_windows"]], [source, *source["refinement_windows"]]
    for i, (left, right) in enumerate(zip(old_levels, new_levels, strict=True)):
        keys = ("native_solver_numerics",) if i == 1 else ("grid", "active_box_mm", "name", "native_solver_numerics")
        if any(left.get(k) != right.get(k) for k in keys):
            raise ValueError("IP fine response reuse changes route, pitch or actual stopping")
    update = _read(Path(source["local_domain_update"]["path"]))["update"]
    grid, active = extend_fine_z_domain(old_levels[1]["grid"], old_levels[1]["active_box_mm"], update, source["grid"])
    if grid != new_levels[1]["grid"] or active != new_levels[1]["active_box_mm"]:
        raise ValueError("IP fine response reuse is not the same declared lower-z extension")
    for i in (1, 3):
        if old["instances"][i] != source["instances"][i]:
            raise ValueError("IP fine response reuse changes retained collision assets")


def _validate_ip_response_level_reuse(binding: dict, base: dict, windows: list, instances: list) -> None:
    """Verify a sealed new fine response and four original pure-response owners."""
    owner = Path(windows[0]["manifest"])
    record = binding["response_level_reuse"]
    sealed = _record(owner, Path(record["path"]))
    if any(record.get(k) != sealed.get(k) for k in ("path", "bytes", "sha256")):
        raise ValueError("IP response reuse provenance differs from its new fine owner")
    verify_record("IP response reuse provenance", sealed, base_dir=owner.parent)
    lineage = _read(Path(record["path"]))
    if (set(lineage) != {"schema_version", "role", "axis", "reused_levels", "source_basis", "source_basis_manifest"}
            or lineage["schema_version"] != 1 or lineage["role"] != "mrtof_ip_fine_response_reuse"
            or lineage["reused_levels"] != ["parent", "window_1", "window_2", "window_3"]):
        raise ValueError("unsupported IP response reuse provenance")
    for name in ("source_basis", "source_basis_manifest"):
        verify_record("IP reused " + name, lineage[name])
    old_path = Path(lineage["source_basis"]["path"])
    old_descriptor = _read(old_path)
    if old_descriptor.get("response_level_reuse"):
        raise ValueError("IP response reuse requires the original complete pure response")
    old_source = _load_operator_ancestry(Path(old_descriptor["source_binding_path"]),
        copy_owner=Path(old_descriptor["refinement_windows"][0]["manifest"]))
    old = load_native_response_basis(old_path, old_source)
    if Path(lineage["source_basis_manifest"]["path"]).resolve() != Path(old["refinement_windows"][0]["manifest"]).resolve():
        raise ValueError("IP reused response manifest differs")
    fine = windows[0]
    fine_plan = _read(Path(fine["numerical_plan_path"]))
    source_path = Path(fine_plan["ip_source_binding_path"])
    verify_record("IP response ordinary source", _record(owner, source_path), base_dir=owner.parent)
    source = load_binding(source_path)
    validate_ip_fine_response_reuse(old, source, lineage["axis"])
    if (binding["parent"] != old_descriptor["parent"]
            or binding["refinement_windows"][1:] != old_descriptor["refinement_windows"][1:]
            or fine["grid"] != source["refinement_windows"][0]["grid"]
            or fine["active_box_mm"] != source["refinement_windows"][0]["active_box_mm"]
            or fine["name"] != "ion_processor_local" or base["authority"] != old["authority"]
            or Path(fine_plan["response_level_reuse_path"]).resolve() != Path(record["path"]).resolve()
            or owner.resolve() == Path(base["manifest"]).resolve()
            or Path(fine_plan["parent_pa"]).resolve() != Path(old["sources"]["scalar_pa"]).resolve()
            or Path(fine_plan["parent_manifest"]).resolve() != Path(old["manifest"]).resolve()
            or instances[0]["pa_path"] != base["sources"]["scalar_pa"]
            or instances[1:] != source["instances"][1:]):
        raise ValueError("IP response reuse changes fields, pure excitation, parent, route or collision ancestry")


def _validate_ip_replacement(binding: dict[str, Any], base: dict[str, Any],
                             windows: list[dict[str, Any]], instances: list[dict[str, Any]], *, pure_response: bool = False) -> None:
    """Bind fresh full-C0 IP fields and thin-metal occupancy to their sealed design.

    Only small authority documents are hashed here. PA records retain the common
    immutable-source/consumer verification boundary used by native field flights.
    """
    provider = "dual_pressure_rectilinear_ion_processor"
    scope = "full_c0_ion_processor_replacement"
    assembly, geometry = base["authority"]["assembly"], base["geometry"]
    if (binding.get("assembly_scope") != scope or assembly.get("assembly_scope") != scope
            or assembly.get("accelerator_provider") != provider
            or assembly.get("post_extraction_state") != "pulse_held_rf_zero"
            or "accelerator_resolved_electrodes" in assembly or "accelerator_component_layout" in geometry):
        raise ValueError("IP binding requires fresh complete replacement without old OA assets")
    owner = Path(base["manifest"])
    for level in (base, *windows):
        for name in ("voltage_authority", "geometry_authority", "numerical_plan"):
            verify_record("IP frozen " + name, level["records"][name], base_dir=Path(level["manifest"]).parent)
    design_manifest = assembly["replacement_assembly_manifest"]
    verify_record("IP design owner manifest", design_manifest)
    design_owner = Path(design_manifest["path"])
    replacement = assembly["replacement_assembly"]
    if binding["replacement_assembly"] != replacement:
        raise ValueError("IP replacement receipt identity differs from voltage authority")
    path = Path(replacement["path"])
    sealed = _record(design_owner, path)
    if any(replacement.get(key) != sealed.get(key) for key in ("path", "bytes", "sha256")):
        raise ValueError("IP replacement receipt differs from its owning manifest")
    verify_record("IP replacement receipt", sealed, base_dir=design_owner.parent)
    receipt = _read(path)
    geometry_path = Path(receipt["assembly_geometry_path"])
    verify_record("IP replacement geometry", _record(design_owner, geometry_path), base_dir=design_owner.parent)
    point_path = Path(receipt["source_config_paths"]["native_operating_point"])
    verify_record("IP replacement operating point", _record(design_owner, point_path), base_dir=design_owner.parent)
    registration = assembly["ion_processor_registration"]
    if (receipt.get("old_oa_removed") is not True or receipt.get("old_oa_field_reuse_allowed") is not False
            or _read(geometry_path) != geometry or assembly["detector"] != geometry["detector"]
            or assembly["ion_processor_electrodes"] != geometry["ion_processor_electrodes"]
            or registration != receipt["assembly_coordinate_transform"]
            or registration.get("to_frame_id") != geometry.get("frame_id")
            or assembly["native_operating_point"] != _read(point_path)):
        raise ValueError("IP replacement geometry, frame or operating point differs from frozen design")
    matching_path = Path(receipt["input_identities"][-1]["path"])
    verify_record("IP frozen voltage projection", receipt["input_identities"][-1])
    expected_values = _read(matching_path)["field_assembly_reference"]["provider_voltage_projection"]["values_v15"]
    if pure_response:
        expected_values = [0.0] * 15
    rows = base["authority"].get("component_voltages_v", [])
    if (len(rows) != 16 or [(row.get("component_namespace"), row.get("component_electrode_id"))
                           for row in rows] != [("ion_processor", i) for i in range(1, 16)] + [("detector", 25)]
            or any(isinstance(row.get("voltage_v"), bool) or not isinstance(row.get("voltage_v"), (int, float))
                   or not math.isfinite(row["voltage_v"]) for row in rows) or rows[-1]["voltage_v"] != 0
            or [row["voltage_v"] for row in rows[:-1]] != expected_values):
        raise ValueError("IP replacement requires complete finite provider15 and grounded detector voltages")
    if "response_level_reuse" in binding:
        if not pure_response:
            raise ValueError("IP response reuse cannot authorize an ordinary Fly field")
        _validate_ip_response_level_reuse(binding, base, windows, instances)
        return
    if "local_domain_update" in binding:
        if pure_response:
            raise ValueError("IP fine extension does not authorize response reuse")
        _validate_ip_fine_extension(binding, base, windows, instances)
        return
    parent_plan = _read(Path(base["numerical_plan_path"]))
    source_path = parent_plan.get("ip_source_binding_path")
    source = None
    if source_path is not None:
        source_path = Path(source_path)
        verify_record("IP unchanged source binding", _record(owner, source_path), base_dir=owner.parent)
        source_descriptor = _read(source_path)
        if Path(source_descriptor["parent"]["manifest"]).resolve() == owner.resolve():
            raise ValueError("IP response source must belong to a distinct sealed owner")
        source = _load_operator_ancestry(source_path, copy_owner=owner)
        if (source.get("accelerator_provider") != provider or source["geometry"] != geometry
                or source["authority"]["assembly"] != assembly
                or [{k: item[k] for k in ("role", "manifest", "pa_path", "origin_mm")} for item in instances[1:]]
                != [{k: item[k] for k in ("role", "manifest", "pa_path", "origin_mm")} for item in source["instances"][1:]]):
            raise ValueError("IP response/compose changes sealed geometry or collision ancestry")
        if (len(windows) != len(source["refinement_windows"])
                or base["grid"] != source["grid"]
                or any(any(current.get(key) != original.get(key) for key in ("name", "grid", "active_box_mm"))
                       for current, original in zip(windows, source["refinement_windows"], strict=True))):
            raise ValueError("IP P/S fields must preserve all actual source grids and active routes")
    if (not windows or windows[0].get("name") != "ion_processor_local"
            or any(Path(level["manifest"]).resolve() != owner.resolve() for level in windows)
            or source is None and any(Path(item["manifest"]).resolve() != owner.resolve() for item in instances)):
        raise ValueError("IP fine-first priority and all assets require this fresh field owner")
    fine = windows[0]
    fine_plan = _read(Path(fine["numerical_plan_path"]))
    if (Path(fine_plan["parent_pa"]).resolve() != Path(base["sources"]["scalar_pa"]).resolve()
            or instances[0]["pa_path"] != base["sources"]["scalar_pa"]
            or instances[0]["origin_mm"] != base["grid"]["origin_mm"]
            or instances[1]["origin_mm"] != base["grid"]["origin_mm"]
            or instances[2]["origin_mm"] != fine["grid"]["origin_mm"]
            or instances[3]["origin_mm"] != receipt["runtime_geometry"]["detector"]["origin_mm"]
            or len({item["pa_path"] for item in instances}) != 4):
        raise ValueError("IP collision occupancy or fine-field source identity/pose differs")


def native_response_operator(binding: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
    """Project a fixed native operator, independent of P/S bias and source locators."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import _native_static_binding_problem
    normalized = copy.deepcopy(binding)
    normalized["authority"] = authority
    values = authority["analyzer_electrode_voltages_v"]
    projection = _native_static_binding_problem(normalized, {
        "analyzer_electrode_voltages_v": values, "stripe_biases_v": [values[10], values[12]],
        "prism_voltages_v": [values[15], values[16]]})
    levels = [binding, *binding["refinement_windows"]]
    identities = [(Path(x["manifest"]).resolve(), Path(x["sources"]["scalar_pa"]).resolve()) for x in levels]
    ancestry, solve_grids = [], []
    for level in levels:
        owner = Path(level["manifest"])
        plan = _read(Path(level["numerical_plan_path"]))
        visited_plans = set()
        while plan.get("refine_performed") is False:
            owner = Path(plan["source_solve_manifest"])
            source_plan = Path(plan["source_solve_plan_path"])
            if source_plan.resolve() in visited_plans:
                raise ValueError("native source solve ancestry contains a cycle")
            visited_plans.add(source_plan.resolve())
            verify_record("source_operator_plan", _record(owner, source_plan), base_dir=owner.parent)
            plan = _read(source_plan)
        if plan.get("full_solve_plan_path"):
            source_plan = Path(plan["full_solve_plan_path"])
            verify_record("full_operator_plan", _record(owner, source_plan), base_dir=owner.parent)
            plan = _read(source_plan)
        solve_grids.append({k: plan.get(k) for k in ("box_mm", "pitch_mm", "dimensions", "mirror_axes", "surface", "boundary_mode")})
    for level in levels[1:]:
        plan = _read(Path(level["numerical_plan_path"]))
        ancestry.append(identities.index((Path(plan["parent_manifest"]).resolve(), Path(plan["parent_pa"]).resolve())))
    return dict(projection=projection, geometry=binding["geometry"], boundary_parent_indices=ancestry,
                full_solve_grids=solve_grids)


@_within_record_lookup
def load_native_response_basis(path: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    """Validate a successful pure response; never authorize it as a Fly workpoint."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_static_field_provider import (
        PS_GROUPS, RESPONSE_NORMALIZATION_V, TE1_AXIS, _response_authority, _te1_basis_metadata,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import candidate_authority
    descriptor = _read(path)
    required = {"schema_version", "role", "parent", "refinement_windows", "instances",
                "fly_authorized", "response_basis", "source_authority_path", "source_binding_path"}
    if descriptor.get("accelerator_provider") == "dual_pressure_rectilinear_ion_processor":
        required |= {"accelerator_provider", "assembly_scope", "replacement_assembly"}
    if "consumer_view" in descriptor:
        required.add("consumer_view")
    if "response_level_reuse" in descriptor:
        required.add("response_level_reuse")
    if descriptor.get("response_basis", {}).get("axis") == TE1_AXIS:
        required.add("direction_reference_path")
    if (set(descriptor) != required
            or descriptor.get("role") != "mrtof_native_static_field_response_basis"
            or descriptor.get("fly_authorized") is not False):
        raise ValueError("sealed native response requires explicit pure basis/no-Fly identity")
    # The first response window is generated by this descriptor's owner. The
    # parent can instead be an already-sealed pure response on mirror extension.
    owner = Path(descriptor["refinement_windows"][0]["manifest"])
    verify_record("response_basis", _record(owner, path), base_dir=owner.parent)
    meta = descriptor["response_basis"]
    if (meta.get("axis") not in set(PS_GROUPS) | {TE1_AXIS} or meta.get("normalization_v") != RESPONSE_NORMALIZATION_V
            or meta.get("axis") != TE1_AXIS and meta.get("physical_electrode_ids") != list(PS_GROUPS[meta["axis"]])):
        raise ValueError("native response axis/normalization differs")
    if meta["axis"] == TE1_AXIS:
        reference = Path(descriptor["direction_reference_path"])
        verify_record("TE1_reference", _record(owner, reference), base_dir=owner.parent)
        if meta != _te1_basis_metadata(reference):
            raise ValueError("native TE1 response differs from its frozen direction authority")
    documents = {}
    for key in ("source_authority_path", "source_binding_path"):
        value = Path(descriptor[key])
        verify_record(key, _record(owner, value), base_dir=owner.parent)
        documents[key] = _read(value)
    source_authority = documents["source_authority_path"]
    original = documents["source_binding_path"]["parent"]
    original_owner = Path(original["manifest"])
    original_authority = Path(original["voltage_authority_path"])
    verify_record("response_original_authority", _record(original_owner, original_authority),
                  base_dir=original_owner.parent)
    if _read(original_authority) != source_authority:
        raise ValueError("response source authority differs from its sealed original binding")
    values = baseline["authority"]["analyzer_electrode_voltages_v"]
    anchor = {axis: values[ids[0]-1] for axis, ids in PS_GROUPS.items()}
    normalized = candidate_authority(source_authority, anchor,
                                     mirror_voltages_v=baseline["authority"]["analyzer_electrode_voltages_v"][:5])
    if normalized != baseline["authority"]:
        raise ValueError("response fixed component/assembly authority differs")
    ordinary = {k: descriptor[k] for k in ("schema_version", "parent", "refinement_windows", "instances")}
    ordinary["role"] = "mrtof_native_static_field_binding"
    if "consumer_view" in descriptor:
        ordinary["consumer_view"] = descriptor["consumer_view"]
    if descriptor.get("accelerator_provider") == "dual_pressure_rectilinear_ion_processor":
        ordinary.update({key: descriptor[key] for key in
                         ("accelerator_provider", "assembly_scope", "replacement_assembly")})
    if "response_level_reuse" in descriptor:
        ordinary["response_level_reuse"] = descriptor["response_level_reuse"]
    result = _load_native_binding(ordinary, pure_response=True)
    if (result["authority"] != _response_authority(source_authority, meta)
            or native_response_operator(result, baseline["authority"]) != native_response_operator(baseline, baseline["authority"])):
        raise ValueError("response pure excitation or geometry/grid/route/operator differs")
    result.update(response_basis=meta, source_authority=source_authority,
                  source_binding_path=descriptor["source_binding_path"], descriptor_path=str(path.resolve()))
    return result


def _load_native_materialized(descriptor: dict[str, Any], path: Path) -> dict[str, Any]:
    """Verify composition lineage/receipts, then reuse the ordinary native loader."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_static_field_provider import compile_response_coefficients, TE1_AXIS
    metadata = descriptor["materialization"]
    ordinary = {k: v for k, v in descriptor.items() if k != "materialization"}
    result = _load_native_binding(ordinary)
    owner = Path(result["manifest"])
    sealed_path = owner.parent / "results/field_binding.json"
    sealed_record = _record(owner, sealed_path)
    verify_record("materialized_binding", sealed_record, base_dir=owner.parent)
    # Trial freezes this descriptor under its own run; only its locator changes.
    # Keep the composition owner's seal authoritative for both original and copy.
    if path.resolve() != sealed_path.resolve():
        verify_record("materialized_binding_copy",
                      dict(sealed_record, path=str(path.resolve())), base_dir=owner.parent)
    plan_path = Path(metadata["plan_path"])
    verify_record("composition_plan", _record(owner, plan_path), base_dir=owner.parent)
    plan = _read(plan_path)
    if plan.get("operation") != "compose" or plan.get("refine_performed") is not False:
        raise ValueError("native materialization must declare composition, not a new Refine")
    if metadata != plan.get("materialization"):
        raise ValueError("native materialization lineage differs from its frozen plan")
    base = _load_operator_ancestry(Path(metadata["base_binding"]), copy_owner=owner,
        frozen_copy=owner.parent / "inputs/combination_base_binding.json")
    bases = {axis: load_native_response_basis(Path(value), base) for axis, value in metadata["response_basis_paths"].items()}
    if any(value["response_basis"]["axis"] != axis for axis, value in bases.items()):
        raise ValueError("materialization response axis differs from its map")
    if (TE1_AXIS in bases) != ("target_mirror_voltages_v" in metadata):
        raise ValueError("materialization TE1 target mirror authority is missing or unexpected")
    expected = compile_response_coefficients(base["authority"], metadata["target_voltages_v"], list(bases),
        mirror_voltages_v=metadata.get("target_mirror_voltages_v"),
        te1_basis=(bases[TE1_AXIS]["response_basis"] if TE1_AXIS in bases else None))
    if (result["authority"] != expected["target_authority"]
            or native_response_operator(result, base["authority"]) != native_response_operator(base, base["authority"])):
        raise ValueError("materialization target or fixed native operator differs")
    outputs = [result, *result["refinement_windows"]]
    sources = [base, *base["refinement_windows"]]
    if len(plan["window_labels"])+1 != len(outputs):
        raise ValueError("materialization level count differs")
    for index, (output, source) in enumerate(zip(outputs, sources, strict=True)):
        label = (["parent", *plan["window_labels"]])[index]
        receipt_path = Path(metadata["receipts"][label])
        verify_record("composition_receipt", _record(owner, receipt_path), base_dir=owner.parent)
        receipt = _read(receipt_path)
        numerical_plan = _read(Path(output["numerical_plan_path"]))
        if (numerical_plan.get("refine_performed") is not False
                or Path(numerical_plan.get("materialization_receipt_path", "")).resolve() != receipt_path.resolve()):
            raise ValueError("native materialization numerical plan lacks its no-Refine receipt")
        responses = []
        for axis, basis in bases.items():
            level = [basis, *basis["refinement_windows"]][index]
            responses.append((str(Path(level["sources"]["scalar_pa"]).resolve()),
                              level["records"]["scalar_pa"]["bytes"], expected["coefficients"][axis]))
        if (receipt.get("status") != "PASS" or receipt.get("refine_performed") is not False
                or receipt.get("baseline_flags_preserved") is not True
                or receipt.get("nonzero_response_flags_verified") is not True
                or receipt.get("header", {}).get("nx") != output["grid"]["dimensions"][0]
                or receipt.get("header", {}).get("ny") != output["grid"]["dimensions"][1]
                or receipt.get("header", {}).get("nz") != output["grid"]["dimensions"][2]
                or [receipt.get("header", {}).get(key) for key in ("dx_mm", "dy_mm", "dz_mm")] != output["grid"]["pitch_mm"]
                or output["records"]["scalar_pa"]["bytes"] != math.prod(output["grid"]["dimensions"])*8+56
                or receipt.get("base") != {"path": source["sources"]["scalar_pa"], "bytes": source["records"]["scalar_pa"]["bytes"]}
                or receipt.get("output") != {"path": output["sources"]["scalar_pa"], "bytes": output["records"]["scalar_pa"]["bytes"]}
                or [(r["path"], r["bytes"], r["coefficient"]) for r in receipt["responses"]] != responses):
            raise ValueError("native composition receipt differs from actual source/output/coefficient")
        for key in ("bytes", "sha256"):
            if output["records"]["surface"][key] != source["records"]["surface"][key]:
                raise ValueError("native composition fractional geometry differs")
    result.update(representation="materialized_native_axis_responses", materialization=metadata,
                  refine_performed=False)
    return result


def _load_collision_overlay(binding: dict[str, Any], path: Path) -> dict[str, Any]:
    """Preserve the source operator seal and independently verify new occupancy."""
    from .native_static_field_provider import collision_overlay_plan, collision_pa_header, COLLISION_NOTREFINABLE_FLAG
    required = {"schema_version", "role", "manifest", "source_binding", "source_binding_copy",
                "patch_plan_path", "patch_pa_path", "patch_surface_path"}
    if set(binding) != required or binding["schema_version"] != 1:
        raise ValueError("unsupported collision overlay binding")
    owner = Path(binding["manifest"]).resolve()
    sealed = _record(owner, owner.parent / "results/field_binding.json")
    verify_record("collision overlay descriptor", dict(sealed, path=str(path.resolve())))
    reference = binding["source_binding"]
    if not isinstance(reference, dict) or set(reference) != {"path", "bytes", "sha256", "manifest"}:
        raise ValueError("collision overlay requires an exact sealed source record and owner")
    source_owner, source_path = Path(reference["manifest"]), Path(reference["path"])
    if source_owner.resolve() == owner:
        raise ValueError("collision overlay source requires an independent owner")
    original = _record(source_owner, source_path)
    if any(reference[k] != original[k] for k in ("path", "bytes", "sha256")):
        raise ValueError("collision overlay source seal differs")
    verify_record("collision overlay original source", original, base_dir=source_owner.parent)
    frozen = Path(binding["source_binding_copy"])
    if frozen.resolve() != (owner.parent / "inputs/source_binding.json").resolve():
        raise ValueError("collision overlay frozen source must belong to its owner")
    frozen_record = _record(owner, frozen)
    if any(frozen_record[k] != original[k] for k in ("bytes", "sha256")):
        raise ValueError("collision overlay source copy changed bytes")
    verify_record("collision overlay source copy", frozen_record, base_dir=owner.parent)
    if _read(frozen).get("role") != "mrtof_native_static_field_binding":
        raise ValueError("collision overlays cannot be recursive or wrap response declarations")
    source = load_binding(frozen)
    if Path(source.get("descriptor_owner", source["manifest"])).resolve() != source_owner.resolve():
        raise ValueError("collision overlay source loader resolved a different descriptor owner")
    plan_path = Path(binding["patch_plan_path"])
    if plan_path.resolve() != (owner.parent / "inputs/analyzer_collision_patch_plan.json").resolve():
        raise ValueError("collision overlay plan belongs to another owner")
    verify_record("collision overlay plan", _record(owner, plan_path), base_dir=owner.parent)
    plan = _read(plan_path)
    geometry_path, contract_path = Path(plan["resolved_geometry"]), Path(plan["numerical_contract_path"])
    for label, item in (("geometry", geometry_path), ("numerics", contract_path)):
        verify_record("collision overlay "+label, _record(owner, item), base_dir=owner.parent)
    if _read(geometry_path) != source["geometry"]:
        raise ValueError("collision overlay changed continuous geometry")
    expected = collision_overlay_plan(source, {k: plan[k] for k in ("box_mm", "pitch_mm", "priority_probes")}, _read(contract_path))
    gem = expected.pop("gem")
    if {k: v for k, v in plan.items() if k not in {"resolved_geometry", "numerical_contract_path"}} != expected:
        raise ValueError("collision overlay plan differs from its source geometry/numerics")
    directory = owner.parent / "simion/analyzer_collision_patch"
    gem_path = directory / "analyzer_collision_patch.gem"
    verify_record("collision overlay GEM", _record(owner, gem_path), base_dir=owner.parent)
    if gem_path.read_text(encoding="utf-8") != gem:
        raise ValueError("collision overlay GEM changed the full analyzer CSG")
    pa_path, surface_path = Path(binding["patch_pa_path"]), Path(binding["patch_surface_path"])
    if (pa_path.resolve() != (directory / "analyzer_collision_patch.pa").resolve()
            or surface_path.resolve() != Path(str(pa_path.resolve())+"-surf")):
        raise ValueError("collision overlay PA and surface must belong to its owner")
    pa_record = _native_payload_record(owner, pa_path)
    surface_record = _native_payload_record(owner, surface_path)
    header = collision_pa_header(pa_path)
    if (header.symmetry != 1 or header.raw_mirror & 7 != 1
            or not header.raw_mirror & COLLISION_NOTREFINABLE_FLAG
            or [header.nx, header.ny, header.nz] != plan["dimensions"]
            or [header.dx_mm, header.dy_mm, header.dz_mm] != plan["pitch_mm"]
            or pa_record["bytes"] != plan["pa_bytes"] or surface_record["bytes"] <= 0):
        raise ValueError("collision overlay PA grid/symmetry/surface differs")
    result = copy.deepcopy(source)
    result["instances"].append(dict(role="analyzer_collision_patch", manifest=str(owner),
        pa_path=str(pa_path.resolve()), origin_mm=plan["origin_mm"], record=pa_record))
    result.update(source_descriptor_path=str(frozen.resolve()), descriptor_owner=str(owner), descriptor_path=str(path.resolve()),
        collision_overlay=dict(schema_version=1, role="mrtof_analyzer_collision_overlay", patch_plan_path=str(plan_path.resolve()),
            **{k: plan[k] for k in ("box_mm", "pitch_mm", "dimensions", "symmetry", "priority_probes",
                                    "refine_performed", "fast_adjust_performed")}))
    return result


@_within_record_lookup
def load_binding(path: Path, *, _allow_responses: bool = True) -> dict[str, Any]:
    """Resolve the base and ordered local scalar fields; unknown support never falls back."""
    binding = _read(path)
    if binding.get("role") == "mrtof_native_collision_overlay_binding":
        return _load_collision_overlay(binding, path)
    if binding.get("role") == "mrtof_native_static_field_binding":
        if "materialization" in binding:
            return _load_native_materialized(binding, path)
        resolved = _load_native_binding(binding)
        if "local_domain_update" in binding:
            # The parent PA keeps its old owner. The new descriptor is published
            # by its independently validated fine-field owner.
            resolved.update(descriptor_owner=resolved["refinement_windows"][0]["manifest"],
                            descriptor_path=str(path.resolve()))
        return resolved
    if not _allow_responses and ("voltage_responses" in binding or "materialization_manifest" in binding):
        raise ValueError("nested voltage response bindings are forbidden")
    if (binding.get("schema_version") not in (1, 2)
            or binding.get("role") != "mrtof_static_comsol_field_binding"
            or binding.get("schema_version") == 2 and "voltage_responses" not in binding):
        raise ValueError("unsupported static COMSOL field binding")
    if "materialization_manifest" in binding:
        return _load_materialized_response(binding)
    if "voltage_responses" in binding:
        if binding["schema_version"] == 2 and set(binding) != {
                "schema_version", "role", "baseline_binding", "voltage_responses", "target_ps_voltages_v"}:
            raise ValueError("version-two response declaration requires only the complete PS target format")
        source = binding.get("baseline_binding")
        if not isinstance(source, str) or not source:
            raise ValueError("voltage responses require an existing ordinary baseline_binding")
        resolved = load_binding(Path(source), _allow_responses=False)
        resolved.update({key: binding[key] for key in (
            "schema_version", "baseline_binding", "voltage_responses",
            "target_stripe_voltages_v", "target_ps_voltages_v") if key in binding})
        return _resolve_voltage_responses(resolved, path)
    export = _load_export(Path(binding["export_manifest"]), binding.get("export_sources"))
    authority, geometry, grid = (export[n] for n in ("authority", "geometry", "grid"))
    if "native_collision_binding" in binding:
        if "assembly_manifest" in binding or "collision_manifest" in binding:
            raise ValueError("native collision reference cannot mix legacy assembly locators")
        reference = binding["native_collision_binding"]
        if (not isinstance(reference, dict) or set(reference) != {"path", "manifest"}
                or any(not isinstance(value, str) or not value for value in reference.values())):
            raise ValueError("native collision reference requires path and manifest")
        source_path, owner = Path(reference["path"]), Path(reference["manifest"])
        verify_record("native_collision_binding", _record(owner, source_path), base_dir=owner.parent)
        if _read(source_path).get("role") != "mrtof_native_static_field_binding":
            raise ValueError("collision reference must be a sealed native binding")
        native = load_binding(source_path, _allow_responses=False)
        if native["geometry"] != geometry or native["authority"] != authority:
            raise ValueError("native collision geometry or full voltage authority differs from COMSOL")
        binding.update(
            instances=copy.deepcopy(native["instances"]),
            collision_geometry=native["sources"]["geometry_authority"],
            collision_binding_kind="sealed_native_instances",
            native_collision_binding_path=str(source_path.resolve()),
            assembly_manifest=str(owner.resolve()),
            collision_manifest=native["instances"][1]["manifest"],
        )
    else:
        _load_legacy_collision_instances(binding)
    instances = binding["instances"]
    if _read(Path(binding["collision_geometry"])) != geometry:
        raise ValueError("collision geometry differs from COMSOL frozen physical model")
    if instances[2]["origin_mm"] != authority["assembly"]["accelerator_iob_origin_mm"]:
        raise ValueError("COMSOL and OA collision instance poses differ")
    detector_box = authority["assembly"]["detector"]["box"]
    if geometry["detector"]["box"] != detector_box:
        raise ValueError("frozen COMSOL and collision detector solids differ")
    oa = authority["assembly"]["accelerator_resolved_electrodes"]
    solids = [oa["grounded_enclosure"]["outer_box_mm"], oa["repeller"]["solid_box_mm"],
              *[e["frame_outer_box_mm"] for e in oa["grid_supports"]],
              *[e["outer_box_mm"] for e in oa["rings"]]]
    binding["accelerator_front_z_mm"] = min(b["z_min_mm"] for b in solids) + oa["local_to_pa_translation_mm"][2] + instances[2]["origin_mm"][2]
    binding.update(export,
                   ideal_sheet_projection=ideal_sheet_projection(authority["assembly"], grid))
    _load_scalar_refinement_windows(binding, authority, geometry)
    return binding


def _load_legacy_collision_instances(binding: dict[str, Any]) -> None:
    """Retain the original frozen assembly/collision asset route."""
    assembly_manifest = Path(binding["assembly_manifest"])
    assembly_root = assembly_manifest.parent
    pose_path = assembly_root / "results" / "resolved_iob_pose.json"
    gui_path = assembly_root / "results" / "gui_workbench_receipt.json"
    _record(assembly_manifest, pose_path)
    _record(assembly_manifest, gui_path)
    pose, gui = _read(pose_path), _read(gui_path)
    collision_manifest = Path(binding["collision_manifest"])
    collision_root = collision_manifest.parent
    collision_plan_path = collision_root / "inputs" / "plan.json"
    collision_geometry = collision_root / "inputs" / "candidate_resolved_geometry.json"
    collision_pa = collision_root / "inputs" / "new_p1_collision.pa0"
    _record(collision_manifest, collision_plan_path)
    _record(collision_manifest, collision_geometry)
    collision_plan = _read(collision_plan_path)
    dependencies = {i["role"]: i for i in gui["pa_dependencies"]}
    instances = []
    for role in ("global_fallback", "native_corridor", "accelerator", "detector"):
        if role == "native_corridor":
            record = _record(collision_manifest, collision_pa)
            instance = dict(role=role, pa_path=str(collision_pa), record=record,
                            manifest=str(collision_manifest), origin_mm=collision_plan["collision_mask"]["origin_mm"])
        else:
            dependency = dependencies[role]
            pa_path = Path(dependency["path"])
            if not pa_path.is_file() or pa_path.stat().st_size != int(dependency["bytes"]):
                raise ValueError(f"sealed assembly PA missing or size changed: {pa_path}")
            record = {"path": str(pa_path), "bytes": dependency["bytes"],
                      "sha256": dependency["source"].get("sha256"), "source": dependency["source"]}
            instance = dict(role=role, pa_path=str(pa_path), record=record, manifest=str(assembly_manifest),
                            origin_mm=pose["origins_mm"]["analyzer" if role == "global_fallback" else role])
        instances.append(instance)
    binding.update(instances=instances, collision_geometry=str(collision_geometry),
                   assembly_pose_path=str(pose_path), assembly_receipt_path=str(gui_path))


def _load_scalar_refinement_windows(binding: dict[str, Any], authority: dict, geometry: dict) -> None:
    if "refinement_windows" in binding:
        windows = binding["refinement_windows"]
        if not isinstance(windows, list):
            raise ValueError("refinement_windows must be an ordered list")
        resolved, names = [], set()
        for window in windows:
            if (not isinstance(window, dict) or not {"name", "export_manifest", "active_box_mm"} <= set(window)
                    or set(window) - {"name", "export_manifest", "active_box_mm", "export_sources"}):
                raise ValueError("refinement window requires name/export_manifest/active_box_mm and optional export_sources")
            name = window["name"]
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ValueError("refinement window names must be nonempty and unique")
            if not isinstance(window["export_manifest"], str) or not window["export_manifest"]:
                raise ValueError("refinement window requires an export_manifest path")
            local = _load_export(Path(window["export_manifest"]), window.get("export_sources"))
            if local["authority"] != authority or local["geometry"] != geometry:
                raise ValueError(f"refinement window {name} voltage authority or geometry differs from base")
            active_box = _validate_active_box_mm(window["active_box_mm"], local["grid"])
            resolved.append(dict(name=name, export_manifest=window["export_manifest"],
                                 active_box_mm=active_box, sources=local["sources"], records=local["records"],
                                 grid=local["grid"], ideal_sheet_projection=ideal_sheet_projection(
                                     authority["assembly"], local["grid"])))
            names.add(name)
        binding["refinement_windows"] = resolved
def _response_scientific_family(family: dict[str, Any]) -> dict[str, Any]:
    """Compare physical/discrete inputs, retaining actual stopping values in sources."""
    compatible = {key: value for key, value in family.items() if key != "geometry_sha256"}
    if isinstance(compatible.get("solver_numerics"), dict):
        compatible["solver_numerics"] = {
            key: value for key, value in compatible["solver_numerics"].items()
            if key not in {"study_stol", "stationary_stol"}
        }
    return compatible


def _resolve_voltage_responses(binding: dict[str, Any], path: Path) -> dict[str, Any]:
    """Resolve PS increments at their declared origins without relabeling saved fields."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import (
        PS_GROUPS, candidate_authority,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
        _static_binding_problem,
    )
    responses = binding["voltage_responses"]
    legacy = binding.get("schema_version", 1) == 1
    if legacy and (not isinstance(binding.get("target_stripe_voltages_v"), list)
                   or len(binding["target_stripe_voltages_v"]) != 2):
        raise ValueError("sealed S response requires two target Stripe voltages")
    target = (dict(zip(("s1", "s2"), binding.get("target_stripe_voltages_v", [])))
              if legacy else binding.get("target_ps_voltages_v"))
    if (not isinstance(responses, dict) or not responses or not set(responses) <= set(PS_GROUPS)
            or legacy and set(responses) != {"s1", "s2"}
            or any(not isinstance(spec, dict) or set(spec) not in ({"binding"}, {"binding", "baseline_binding"})
                   or any(not isinstance(value, str) or not value for value in spec.values())
                   for spec in responses.values())
            or not isinstance(target, dict) or set(target) != ({"s1", "s2"} if legacy else set(PS_GROUPS))
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in target.values())):
        raise ValueError("PS responses require named binding paths and complete finite target voltages")
    base = {k: v for k, v in binding.items() if k not in (
        "baseline_binding", "voltage_responses", "target_stripe_voltages_v", "target_ps_voltages_v")}
    authority = base["authority"]
    anchor = {name: float(authority["analyzer_electrode_voltages_v"][ids[0]-1])
              for name, ids in PS_GROUPS.items()}
    target = {**anchor, **target}
    if any(target[name] != anchor[name] for name in PS_GROUPS if name not in responses):
        raise ValueError("target changes a PS axis without a declared response")
    def family(component: dict[str, Any], source: str) -> dict[str, Any]:
        values = component["authority"]["analyzer_electrode_voltages_v"]
        return _static_binding_problem(component, {
            "stripe_biases_v": [values[10], values[12]],
            "prism_voltages_v": [values[15], values[16]],
            "analyzer_electrode_voltages_v": values,
        }, source)
    common = family(base, binding["baseline_binding"])
    def check_component(component: dict[str, Any], source: str) -> None:
        # Other PS voltages may differ at an old origin, but no fixed input may.
        if candidate_authority(component["authority"], anchor) != authority:
            raise ValueError("response fixed voltages/assembly differ from target baseline")
        if (component["geometry"] != base["geometry"]
                or _response_scientific_family(family(component, source)) != _response_scientific_family(common)):
            raise ValueError("response geometry/mesh/dataset/solver/boundary family differs")
        levels = [base, *base.get("refinement_windows", [])]
        candidates = [component, *component.get("refinement_windows", [])]
        if len(levels) != len(candidates):
            raise ValueError("response window count differs")
        for level, candidate in zip(levels, candidates, strict=True):
            if not isinstance(level["records"]["valid_pa"].get("sha256"), str) or not level["records"]["valid_pa"]["sha256"]:
                raise ValueError("response valid mask lacks a sealed identity")
            if (any(level.get(k) != candidate.get(k) for k in ("name", "active_box_mm", "ideal_sheet_projection"))
                    or any(level["grid"][k] != candidate["grid"][k] for k in ("origin_mm", "pitch_mm", "dimensions"))
                    or any(level["records"]["valid_pa"][k] != candidate["records"]["valid_pa"][k]
                           for k in ("bytes", "sha256"))):
                raise ValueError("response grid/window/sheet/valid-mask identity differs")

    base_path = binding["baseline_binding"]
    cache = {Path(base_path).resolve(): base}
    accumulated = {}

    def add_term(source: str, component: dict[str, Any], weight: float, *, subtract: bool = False) -> None:
        key = Path(source).resolve()
        entry = accumulated.setdefault(key, dict(
            binding_path=source, binding=component, positive=[], negative=[]))
        entry["negative" if subtract else "positive"].append(weight)

    def component_at(source: str) -> dict[str, Any]:
        key = Path(source).resolve()
        if key not in cache:
            component = load_binding(Path(source), _allow_responses=False)
            check_component(component, source)
            cache[key] = component
        return cache[key]

    add_term(base_path, base, 1.)
    for name in (axis for axis in PS_GROUPS if axis in responses):
        spec = responses[name]
        source = spec["binding"]
        origin_path = spec.get("baseline_binding", base_path)
        origin = component_at(origin_path)
        component = component_at(source)
        origin_anchor = {axis: float(origin["authority"]["analyzer_electrode_voltages_v"][ids[0]-1])
                         for axis, ids in PS_GROUPS.items()}
        probe = {**origin_anchor, name: float(component["authority"]["analyzer_electrode_voltages_v"][PS_GROUPS[name][0]-1])}
        step = probe[name] - origin_anchor[name]
        if step == 0 or component["authority"] != candidate_authority(origin["authority"], probe):
            raise ValueError("response must change exactly its named PS axis; fixed voltages/assembly differ")
        weight = (float(target[name]) - anchor[name]) / step
        if not math.isfinite(weight):
            raise ValueError("response coefficient is nonfinite")
        add_term(source, component, weight)
        add_term(origin_path, origin, weight, subtract=True)
    same_anchor = all(Path(spec.get("baseline_binding", base_path)).resolve() == Path(base_path).resolve()
                      for spec in responses.values())
    terms = []
    zero_terms = []
    for entry in accumulated.values():
        coefficient = sum(entry["positive"]) - sum(entry["negative"])
        if not math.isfinite(coefficient):
            raise ValueError("response coefficient is nonfinite")
        term = dict(binding_path=entry["binding_path"], coefficient=coefficient, binding=entry["binding"])
        if coefficient != 0 or same_anchor:
            terms.append(term)
        else:
            zero_terms.append(term)
    # Keep the existing two-to-five-term consumer contract even at a zero increment.
    # This validated zero source is skipped by the adapter, not an extra field query.
    if len(terms) == 1:
        terms.append(zero_terms[0])
    if len(terms) > 5:
        raise ValueError("response requires more than five nonzero consumer terms")
    binding["response_terms"] = terms
    # Diagnostic amplification factor only; not an error bound or acceptance gate.
    binding["response_weight_l1_norm"] = sum(abs(term["coefficient"]) for term in binding["response_terms"])
    binding["response_family"] = common
    binding["authority"] = candidate_authority(authority, target)
    binding["representation"] = ("exploratory_affine_s_responses" if legacy
                                 else "exploratory_affine_ps_responses")
    binding["gui_field_queries_equivalent"] = False
    return binding


def validate_response_candidate(binding: dict[str, Any], request: dict[str, Any]) -> None:
    """Bind an exploratory response to this provider's full authority and field family.

    Reuses sealed records; geometry is compared as parsed content, not JSON formatting.
    No PA payload is scanned or hashed. Raises ValueError for an incompatible basis.
    """
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import derive_candidate_authority
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import _static_binding_problem

    source_path = request["source_binding_path"]
    source = load_binding(Path(source_path), _allow_responses=False)
    authority, _ = derive_candidate_authority(request, source["authority"])
    if binding.get("representation") not in {
            "exploratory_affine_s_responses", "exploratory_affine_ps_responses",
            "exploratory_materialized_affine_s_responses", "exploratory_materialized_affine_ps_responses"}:
        raise ValueError("candidate must consume the declared exploratory S response basis")
    if binding["authority"] != authority:
        raise ValueError("response differs from complete candidate voltage/assembly authority")
    values = source["authority"]["analyzer_electrode_voltages_v"]
    expected = _static_binding_problem(source, {
        "stripe_biases_v": [values[10], values[12]],
        "prism_voltages_v": [values[15], values[16]],
        "analyzer_electrode_voltages_v": values,
    }, source_path)
    # Original SHA remains sealed artifact identity, not semantic geometry identity.
    if (binding["geometry"] != source["geometry"]
            or _response_scientific_family(binding["response_family"]) != _response_scientific_family(expected)):
        raise ValueError("declared response scientific field family differs from provider source")

    def support(level: dict[str, Any]) -> tuple[Any, ...]:
        return (level.get("name"), level.get("active_box_mm"), level.get("ideal_sheet_projection"),
                tuple(level["grid"][k] for k in ("origin_mm", "pitch_mm", "dimensions")),
                tuple(level["records"]["valid_pa"][k] for k in ("bytes", "sha256")))

    actual_levels = [binding, *binding.get("refinement_windows", [])]
    expected_levels = [source, *source.get("refinement_windows", [])]
    if [support(level) for level in actual_levels] != [support(level) for level in expected_levels]:
        raise ValueError("declared response ordered support/window/mask differs from provider source")


def validate_voltages(binding: dict[str, Any], analyzer: list[float], accelerator: list[float],
                      *, pulse_requested: bool) -> None:
    if pulse_requested:
        raise ValueError("static COMSOL binding cannot consume an OA pulse")
    expected = binding["authority"]["analyzer_electrode_voltages_v"]
    if len(analyzer) != 20 or len(expected) != 20 or any(
            not math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9) for a, b in zip(analyzer, expected)):
        raise ValueError("analyzer voltages differ from frozen COMSOL authority")
    if binding.get("accelerator_provider") == "dual_pressure_rectilinear_ion_processor":
        rows = binding["authority"]["component_voltages_v"]
        expected_ip = [row["voltage_v"] for row in rows if row["component_namespace"] == "ion_processor"]
        if (len(accelerator) != 15 or len(expected_ip) != 15
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in accelerator)
                or any(not math.isclose(a, b, rel_tol=0, abs_tol=1e-9) for a, b in zip(accelerator, expected_ip))):
            raise ValueError("IP voltages differ from frozen provider authority")
        return
    oa = binding["authority"]["assembly"]["accelerator_resolved_electrodes"]
    electrodes = [oa["grounded_enclosure"], oa["repeller"], *oa["grid_supports"], *oa["rings"]]
    ids = {int(e["component_electrode_id"]): int(e["local_pa_electrode_id"]) for e in electrodes}
    expected_oa = [None] * len(accelerator)
    for e in binding["authority"]["component_voltages_v"]:
        if e["component_namespace"] == "accelerator":
            expected_oa[ids[int(e["component_electrode_id"])] - 1] = float(e["voltage_v"])
        elif e["component_namespace"] == "detector" and float(e["voltage_v"]) != 0:
            raise ValueError("static consumer requires the grounded detector")
    if any(v is None for v in expected_oa) or any(
            not math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9) for a, b in zip(accelerator, expected_oa)):
        raise ValueError("OA voltages differ from frozen COMSOL authority")


def _lua_vector(values: list[float]) -> str:
    return "{ " + ", ".join(f"{value:.17g}" for value in values) + " }"


def _scalar_field_lua_fields(binding: dict[str, Any]) -> str:
    """Serialize one resolved scalar field without losing its numerical grid."""
    grid = binding["grid"]
    if binding.get("mode") == "native_static_pa":
        return (f"mode = 'native_static_pa', scalar_pa = {json.dumps(binding['sources']['scalar_pa'])}, "
                f"origin_mm = {_lua_vector(grid['origin_mm'])}, pitch_mm = {_lua_vector(grid['pitch_mm'])}, "
                f"dimensions = {_lua_vector(grid['dimensions'])}, symmetry = 'x'"
                + (", consumer_view = 'x_symmetry_plane'" if binding.get("consumer_view") else ""))
    sheets = "{ " + ", ".join(
        "{ " + ", ".join(f"{key} = {sheet[key]}" for key in
                         ("component_electrode_id", "i_min", "i_max", "j_min", "j_max", "k")) + " }"
        for sheet in binding["ideal_sheet_projection"]
    ) + " }"
    fields = (
        f"scalar_pa = {json.dumps(binding['sources']['scalar_pa'], ensure_ascii=False)}, "
        f"valid_pa = {json.dumps(binding['sources']['valid_pa'], ensure_ascii=False)}, "
        f"origin_mm = {_lua_vector(grid['origin_mm'])}, "
        f"pitch_mm = {_lua_vector(grid['pitch_mm'])}, ideal_sheet_projection = {sheets}"
    )
    if "response_terms" in binding:
        fields += ", response_terms = { " + ", ".join(
            "{ coefficient = " + f"{term['coefficient']:.17g}, "
            + _scalar_field_lua_fields(term["binding"]) + ", refinement_windows = "
            + _scalar_refinement_windows_lua(term["binding"].get("refinement_windows", [])) + " }"
            for term in binding["response_terms"]
        ) + " }"
    return fields


def _scalar_refinement_windows_lua(windows: list[dict[str, Any]]) -> str:
    """Preserve ordered takeover boxes and each field's actual assets in Lua."""
    return "{ " + ", ".join(
        "{ " + f"name = {json.dumps(window['name'], ensure_ascii=False)}, "
        + "active_box_mm = { " + ", ".join(_lua_vector(axis) for axis in window["active_box_mm"])
        + " }, " + _scalar_field_lua_fields(window) + " }" for window in windows
    ) + " }"


def compile_sampling_request(binding_a: dict[str, Any], binding_b: dict[str, Any],
                             samples_csv: Path, output_csv: Path) -> str:
    """Compile caller-coordinate samples and two resolved bindings to read-only Lua.

    Samples use the common name,x_mm,y_mm,z_mm protocol; no fields are loaded here.
    The caller owns physical equivalence and acceptance limits for the comparison.
    """
    samples, names = [], set()
    with samples_csv.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["name", "x_mm", "y_mm", "z_mm"]:
            raise ValueError("sample CSV header must be name,x_mm,y_mm,z_mm")
        for row in reader:
            name = row["name"]
            if not name or name in names or any(c in name for c in ',"\r\n') or None in row:
                raise ValueError("sample names must be unique nonempty unquoted CSV identifiers")
            xyz = [float(row[axis]) for axis in ("x_mm", "y_mm", "z_mm")]
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError("sample coordinates must be finite mm values")
            samples.append("{ name = " + json.dumps(name, ensure_ascii=False)
                           + ", position_mm = " + _lua_vector(xyz) + " }")
            names.add(name)
    if not samples:
        raise ValueError("sample CSV contains no samples")
    fields = ["{ " + _scalar_field_lua_fields(binding) + ", refinement_windows = "
              + _scalar_refinement_windows_lua(binding.get("refinement_windows", [])) + " }"
              for binding in (binding_a, binding_b)]
    adapter = Path(__file__).resolve().parents[1] / "simion/scalar_field_adapter.lua"
    return ("return { schema_version = 1, adapter = " + json.dumps(adapter.as_posix())
            + ", output_csv = " + json.dumps(output_csv.resolve().as_posix())
            + ", a = " + fields[0] + ", b = " + fields[1]
            + ", samples = { " + ", ".join(samples) + " } }\n")


def compile_composition_plan(binding: dict[str, Any], source: Path, output_directory: Path,
                             *, _checking_sealed_outputs: bool = False) -> dict[str, Any]:
    """Plan the public standalone composer; never open, copy or hash PA payloads."""
    from common.simion.operating_pa_cache import (
        content_identity_from_verified_record, file_content_identity,
        linear_basis_operating_pa_group_identity,
    )
    terms = binding.get("response_terms")
    if not isinstance(terms, list) or not 2 <= len(terms) <= 5:
        raise ValueError("composition requires baseline and one to four resolved response axes")
    composer = Path(__file__).resolve().parents[3] / "common/simion/compose_standalone_pa.lua"
    groups = [[term["binding"], *term["binding"].get("refinement_windows", [])] for term in terms]
    if len({len(group) for group in groups}) != 1:
        raise ValueError("composition window counts differ")
    members, commands = [], []
    for index, levels in enumerate(zip(*groups, strict=True)):
        name = "field_v.pa" if index == 0 else f"window-{index:03d}_v.pa"
        output = output_directory.resolve() / name
        paths = [Path(level["sources"]["scalar_pa"]).resolve() for level in levels]
        if output in paths or (output.exists() and not _checking_sealed_outputs):
            raise ValueError("composition output must be new and cannot overwrite an input")
        contents = [content_identity_from_verified_record(
            {key: level["records"]["scalar_pa"][key] for key in ("bytes", "sha256")}, path=path)
            for level, path in zip(levels, paths, strict=True)]
        coefficients = [float(term["coefficient"]) for term in terms]
        # Public composer starts with A; these are whole-point scale factors,
        # not unit-voltage electrode responses or linear trajectory predictions.
        coefficients[0] -= 1.0
        responses = [{"coordinate": f"whole_point_{n}_scale", "content": content,
                      "basis_normalization_v": 1.0, "applied_voltage_delta_v": coefficient}
                     for n, content, coefficient in zip(("A_correction", "B", "C", "D", "E")[:len(terms)], contents, coefficients, strict=True)]
        members.append(dict(output_name=name, base_pa=contents[0], responses=responses,
                            target_voltage_vector_v=binding["authority"]["analyzer_electrode_voltages_v"]))
        commands.append(dict(name=levels[0].get("name", "base"), output_name=name,
            expected_bytes=contents[0]["bytes"],
            support=dict(grid={key: levels[0]["grid"][key] for key in ("origin_mm", "pitch_mm", "dimensions")},
                         active_box_mm=levels[0].get("active_box_mm"),
                         ideal_sheet_projection=levels[0]["ideal_sheet_projection"],
                         valid_mask={key: levels[0]["records"]["valid_pa"][key] for key in ("bytes", "sha256")}),
            argv=[str(composer), str(paths[0]), str(output),
                  *[f"{path},{coefficient:.17g}" for path, coefficient in zip(paths, coefficients, strict=True)]]))
    return dict(schema_version=1, role="mrtof_fixed_scalar_composition_plan",
                response_binding=str(source.resolve()), source_identity=file_content_identity(source),
                output_directory=str(output_directory.resolve()), commands=commands,
                operating_pa_identity=linear_basis_operating_pa_group_identity(members, pa_format_version=2020),
                authority=binding["authority"], response_weight_l1_norm=binding["response_weight_l1_norm"],
                qualification="exploratory_materialization_only__no_direct_field_or_gui_qualification")


def _load_materialized_response(descriptor: dict[str, Any]) -> dict[str, Any]:
    from common.simion.operating_pa_cache import canonical_operating_pa_identity
    source = Path(descriptor["response_binding"])
    original = _read(source)
    if "materialization_manifest" in original:
        raise ValueError("nested materialized response bindings are forbidden")
    binding = load_binding(source)
    manifest = Path(descriptor["materialization_manifest"])
    plan_path = manifest.parent / "inputs/composition_plan.json"
    _record(manifest, plan_path)
    plan = _read(plan_path)
    expected = compile_composition_plan(binding, source, Path(plan["output_directory"]),
                                        _checking_sealed_outputs=True)
    for key in ("schema_version", "role", "response_binding", "source_identity",
                "authority", "response_weight_l1_norm", "qualification"):
        if plan.get(key) != expected[key]:
            raise ValueError(f"sealed composition plan source or identity differs: {key}")
    sealed_identity = canonical_operating_pa_identity(plan.get("operating_pa_identity"))
    current_identity = copy.deepcopy(expected["operating_pa_identity"])
    # Generator bytes are immutable provenance, not the scientific validity of
    # an already produced PA.  All members, coefficients and other synthesis
    # settings remain identical to the actual consumption request.
    current_identity["synthesis"]["implementation_sha256"] = sealed_identity["synthesis"]["implementation_sha256"]
    if sealed_identity != current_identity:
        raise ValueError("sealed composition scientific operating identity differs")
    if len(plan.get("commands", [])) != len(expected["commands"]):
        raise ValueError("sealed composition level count differs")
    result = copy.deepcopy(binding)
    levels = [result, *result.get("refinement_windows", [])]
    for level, actual, wanted in zip(levels, plan["commands"], expected["commands"], strict=True):
        output = Path(plan["output_directory"]) / wanted["output_name"]
        if not output.resolve().is_relative_to(manifest.parent.resolve()):
            raise ValueError("composition output must belong to its successful run")
        if any(actual.get(key) != wanted[key] for key in ("name", "output_name", "expected_bytes", "support")):
            raise ValueError("sealed composition output metadata differs")
        argv = list(wanted["argv"]); argv[2] = str(output.resolve())
        if actual.get("argv") != argv:
            raise ValueError("sealed composer command differs")
        record = _record(manifest, output)
        if record["bytes"] != wanted["expected_bytes"]:
            raise ValueError("composition output byte size differs from its scalar grid")
        level["sources"]["scalar_pa"] = str(output.resolve())
        level["records"]["scalar_pa"] = record
    result["composition_sources"] = [{"binding_path": term["binding_path"], "coefficient": term["coefficient"]}
                                     for term in result.pop("response_terms")]
    result.update(materialization_manifest=str(manifest.resolve()),
                  materialization_synthesis=sealed_identity["synthesis"],
                  representation=("exploratory_materialized_affine_ps_responses"
                                  if binding["representation"] == "exploratory_affine_ps_responses"
                                  else "exploratory_materialized_affine_s_responses"),
                  gui_field_queries_equivalent=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--compare-binding", type=Path)
    parser.add_argument("--samples", type=Path)
    parser.add_argument("--sampling-request", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--composition-plan", type=Path)
    parser.add_argument("--composition-output-directory", type=Path)
    args = parser.parse_args()
    composition = (args.composition_plan, args.composition_output_directory)
    if any(composition) and not all(composition):
        parser.error("composition requires --composition-plan and --composition-output-directory")
    sampling = (args.compare_binding, args.samples, args.sampling_request, args.comparison_output)
    if any(sampling) and not all(sampling):
        parser.error("comparison requires --compare-binding, --samples, --sampling-request and --comparison-output")
    binding = load_binding(args.binding)
    if all(composition):
        if any(sampling):
            parser.error("composition planning and sampling are separate operations")
        plan = compile_composition_plan(binding, args.binding, args.composition_output_directory)
        args.composition_plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"composition_plan": str(args.composition_plan.resolve())}))
    elif all(sampling):
        request = compile_sampling_request(binding, load_binding(args.compare_binding),
                                           args.samples, args.comparison_output)
        args.sampling_request.write_text(request, encoding="utf-8", newline="\n")
        print(json.dumps({"sampling_request": str(args.sampling_request.resolve()),
                          "comparison_output": str(args.comparison_output.resolve())}))
    else:
        print(json.dumps(binding))


if __name__ == "__main__":
    main()
