"""Admit OFF/ON COMSOL world samples for a split OA–TOF model."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping

from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.io.manifest_records import record_path, validate_file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact
from .frontend import split_frontend_instances
from .model import compile_prepared_model, model_geometry, require_prepared_model
from .scalar_sample_binding import _read, _small_product, attach_refinement_windows, verify_scalar_sample


def _workpoints(drive):
    """Return keyed physical OFF and ON voltages, with no invented RF basis."""
    result = {"off": {}, "on": {}}
    for instance, groups in drive["groups"].items():
        for group, item in groups.items():
            if item["kind"] == "static":
                off = on = item["voltage_v"]
            elif item["kind"] == "pulse":
                off, on = item["off_voltage_v"], item["on_voltage_v"]
            else:
                raise ValueError("split scalar OFF/ON supports no RF or other drive")
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in (off, on)):
                raise ValueError("split workpoint voltages must be finite")
            result["off"][(instance, group)] = off
            result["on"][(instance, group)] = on
    return result


def resolve_split_scalar_basis(*, model, geometry_artifact, samples, refinement_windows=None):
    """Bind actual OFF and ON solutions; no sampling coverage or qualification claim.

    Consumers must query both valid supports and compose OFF + active*(ON-OFF).
    The original owners must protect returned references during consumption.
    """
    if not isinstance(samples, Mapping) or set(samples) != {"off", "on"}:
        raise ValueError("exact OFF and ON sample products required")
    document = require_prepared_model(model)
    geometry = model_geometry(model)
    native = geometry.frontend_geometry
    if native.get("role") != "simion_split_oa_tof_geometry":
        raise ValueError("split OA–TOF model required")
    rf, _, _ = split_frontend_instances(native["composition_plan"])
    if rf:
        raise ValueError("two-workpoint binding does not support RF")
    producer, product, manifest = _small_product(geometry_artifact, "geometry_artifact", ("projection",))
    meta = product["metadata"]
    if meta.get("backend") != "comsol" or meta.get("scope") != "geometry_only" or meta.get("native_reopen_verified") is not True:
        raise ValueError("reopened public COMSOL geometry required")
    record = validate_file_record(producer["inputs"]["execution_request"], "geometry execution request")
    verify_record("geometry execution request", record, base_dir=manifest.parent)
    request_path = record_path(record, base_dir=manifest.parent)
    frozen = _read(request_path)
    projection = _read(record_path(product["data"]["projection"], base_dir=manifest.parent))
    if frozen.get("role") != "run_artifact_workflow_request" or frozen["payload"].get("action") != "build_comsol_geometry":
        raise ValueError("COMSOL geometry source action differs")
    snapshot = frozen["payload"]["assembly"]
    from msplatform import assembly as assembly_api
    from msplatform.components.catalog import _from_provider
    from msplatform.components.registry import project_descriptor
    plan = snapshot["composition_plan"]
    if snapshot["composition_plan"] != native["composition_plan"] or snapshot["components_resolved"] != document["components_resolved"]:
        raise ValueError("split model and assembly differ")
    parts = {name: _from_provider(project_descriptor(interface["project_id"]).provider_id,
             snapshot["components_resolved"][name], interface, source_design=snapshot["components_source"][name])
             for name, interface in plan["components"].items()}
    canonical = assembly_api.assemble(plan["recipe"], parts, local_scope=plan.get("local_scope"))
    if canonical.composition_plan != plan:
        raise ValueError("split assembly source or plan differs")
    rebuilt = compile_prepared_model(geometry, snapshot["components_resolved"],
                                     drive=document["drive"], physics=document["physics"])
    if require_prepared_model(rebuilt) != document:
        raise ValueError("split model differs from canonical physical inputs")
    vectors = _workpoints(document["drive"])
    if (frozen["payload"]["projection"] != projection
            or project_assembly_geometry(snapshot, outer_box_mm=projection["outer_box_mm"]) != projection):
        raise ValueError("COMSOL geometry and frozen split assembly differ")
    keys = [(row["instance_id"], row["electrode_group_id"]) for row in projection["electrode_groups"]]
    if len(keys) != len(set(keys)) or any(set(vector) != set(keys) for vector in vectors.values()):
        raise ValueError("split workpoint group coverage differs")

    def admit(level):
        if not isinstance(level, Mapping) or set(level) != {"off", "on"}:
            raise ValueError("exact OFF and ON samples required")
        bindings, common_request, grid = {}, None, None
        for name in ("off", "on"):
            def check(request):
                nonlocal common_request
                rows = request["group_voltages"]
                actual = {(r["instance_id"], r["electrode_group_id"]): r["voltage_v"] for r in rows}
                if len(actual) != len(rows) or actual != vectors[name]:
                    raise ValueError("split sample group workpoint differs: " + name)
                operator = {k: copy.deepcopy(v) for k, v in request.items() if k != "group_voltages"}
                if operator.get("exterior") != {"kind": "potential", "voltage_v": 0.0}:
                    raise ValueError("split scalar basis requires zero exterior potential")
                if common_request is not None and common_request != operator:
                    raise ValueError("split OFF/ON operator or mesh differs")
                common_request = operator
            binding = verify_scalar_sample(level[name], projection, check_workpoint=check,
                                           resolve_reference=True, allow_partial_sheets=True)
            if grid is not None and binding["grid"] != grid:
                raise ValueError("split OFF/ON grids differ")
            grid = binding["grid"]
            if level is samples:
                for axis in range(3):
                    low = grid["origin_mm"][axis]
                    high = low + (grid["dimensions"][axis] - 1) * grid["pitch_mm"][axis]
                    if low > projection["outer_box_mm"]["min"][axis] or high < projection["outer_box_mm"]["max"][axis]:
                        raise ValueError("split scalar grid does not cover the complete world box")
            bindings[name] = binding
        return {"bases": bindings}

    bindings = admit(samples)["bases"]
    attach_refinement_windows(bindings, refinement_windows, admit_level=admit)
    return dict(schema_version=1, role="split_off_on_scalar_binding",
                model_identity_sha256=document["model_identity_sha256"], clock=copy.deepcopy(document["drive"]["clock"]),
                pulse=copy.deepcopy(document["drive"]["pulse"]),
                geometry_reference=(geometry_artifact.reference if isinstance(geometry_artifact, OpenedArtifact)
                                    else copy.deepcopy(dict(geometry_artifact))),
                geometry_execution_request=dict(record, path=str(request_path)), bases=bindings,
                composition="off_plus_pulse_times_on_minus_off", scope="identity_only_not_coverage_or_qualification")
