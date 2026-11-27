"""Independent managed dual-cone geometry, unsolved models and spatial fields."""

from pathlib import Path
import json
from collections.abc import Mapping
from msplatform.execution.context import ExecutionContext
from msplatform.results.artifacts import OpenedArtifact

from msplatform.backends.simion.dual_cone_stages import (
    build_geometry, prepare_model, solve_fields, track_fields,
    plan_geometry_stage,
    plan_model_stage,
    require_geometry_product,
    require_model_product,
    require_fields_product,
    require_trajectory_product,
)
from msplatform.io.manifest_records import file_record


_TARGETS = ("geometry", "model", "fields", "trajectory")


def _target_value(value):
    """Snapshot only explicit request data and public artifact references."""
    from collections.abc import Mapping

    if hasattr(value, "reference"):
        return _target_value(value.reference)
    if hasattr(value, "to_contract"):
        return _target_value(value.to_contract())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _target_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_target_value(item) for item in value]
    return value


def _target_arguments(function, arguments, *, reference=False):
    from inspect import signature

    try:
        signature(function).bind(*([None] if reference else []), context=None, **arguments)
    except TypeError as error:
        raise ValueError("target request " + function.__name__ + ": " + str(error)) from error


def _target_plan(*, target, request=None, available=None):
    """Plan this named four-stage workflow without tools, runs or leases.

    Request groups match the existing stage arguments, excluding context and
    predecessor references. Explicit available products never imply repair.
    A complete trajectory is read-only selection, not compatibility with new
    scientific inputs. Source/gas/SDS are considered only for a trajectory.
    """
    from collections.abc import Mapping
    from msplatform.io.file_identity import canonical_json_sha256
    from msplatform.backends.simion.dual_cone_stages import (
        device_placement, plan_saved_fly_inputs, require_field_numerics,
    )

    if target not in _TARGETS:
        raise ValueError("unsupported dual-cone target")
    if ((request is not None and not isinstance(request, Mapping))
            or (available is not None and not isinstance(available, Mapping))):
        raise ValueError("target request and available products must be mappings")
    if set(request or {}) - set(_TARGETS) or set(available or {}) - set(_TARGETS):
        raise ValueError("unknown dual-cone request/product stage")
    selected = _TARGETS[:_TARGETS.index(target) + 1]
    if set(available or {}) - set(selected):
        raise ValueError("available product is beyond the requested target")
    groups = _target_value({key: value for key, value in (request or {}).items() if key in selected})
    if any(not isinstance(value, dict) for value in groups.values()):
        raise ValueError("each target request group must be a mapping")
    references = _target_value(available or {})
    products = {}
    for key, value in references.items():
        if key == "geometry":
            products[key] = require_geometry_product(value)
        elif key == "model":
            products[key] = require_model_product(value)
        elif key == "fields":
            products[key] = require_fields_product(value)[0]
        else:
            products[key] = require_trajectory_product(value)
    stages, pending, authorities = [], [], []
    if "trajectory" in products:
        if any(groups.values()):
            raise ValueError("explicit trajectory cannot claim compatibility with a new scientific request")
    else:
        geometries = []
        if "geometry" in products:
            geometries.append(json.loads(products["geometry"].data_path("compiled_geometry").read_text(encoding="utf-8-sig")))
        documents = {key: json.loads(products[key].data_path("compiled_model").read_text(encoding="utf-8-sig"))
                     for key in ("model", "fields") if key in products}
        geometries.extend(value["geometry"] for value in documents.values())
        if "geometry" in groups:
            _target_arguments(build_geometry, groups["geometry"])
            if ("geometry" in products and "placement" in groups["geometry"]
                    and device_placement(geometries[0]["resolved"], geometries[0]["numerics"],
                                         groups["geometry"]["placement"]).to_contract()
                    != device_placement(geometries[0]["resolved"], geometries[0]["numerics"],
                                        products["geometry"].metadata.get("placement")).to_contract()):
                raise ValueError("explicit geometry placement conflicts with selected geometry product")
            geometries.append(plan_geometry_stage(**groups["geometry"])["projection"])
        if not geometries:
            raise ValueError("target requires explicit geometry request or a suitable saved product")
        geometry = geometries[0]
        if any(value != geometry for value in geometries[1:]):
            raise ValueError("explicit products/request have conflicting geometry")
        placements = ([products["geometry"].metadata.get("placement")] if "geometry" in products else [])
        placements.extend(document.get("placement") for document in documents.values())
        poses = [device_placement(geometry["resolved"], geometry["numerics"], placement).to_contract()
                 for placement in placements]
        if any(value != poses[0] for value in poses[1:]):
            raise ValueError("explicit products have conflicting world placement or frame")
        model = documents.get("model", documents.get("fields"))
        if model is not None and "model" not in groups and "placement" in groups.get("geometry", {}):
            requested_pose = device_placement(geometry["resolved"], geometry["numerics"],
                                              groups["geometry"]["placement"]).to_contract()
            selected_pose = device_placement(geometry["resolved"], geometry["numerics"],
                                             model.get("placement")).to_contract()
            if requested_pose != selected_pose:
                raise ValueError("changed geometry placement requires an explicit model request")
        if target != "geometry":
            if "model" in groups:
                arguments = groups["model"]
                _target_arguments(prepare_model, arguments, reference=True)
                projected = {key: value for key, value in arguments.items() if key != "clock_authority_reference"}
                if "placement" not in projected:
                    projected["placement"] = (products["geometry"].metadata.get("placement") if "geometry" in products
                                              else groups.get("geometry", {}).get("placement"))
                model = plan_model_stage(geometry, **projected)["projection"]
                if ("placement" in groups.get("geometry", {})
                        and device_placement(geometry["resolved"], geometry["numerics"],
                                             groups["geometry"]["placement"]).to_contract()
                        != device_placement(geometry["resolved"], geometry["numerics"],
                                            model.get("placement")).to_contract()):
                    raise ValueError("explicit geometry and model requests have conflicting world placement or frame")
                from msplatform.backends.simion.model_execution import _clock_reference
                _clock_reference(dict(drive=dict(clock=model["clock"])), arguments["clock_authority_reference"])
                authorities.extend(arguments["clock_authority_reference"][key] for key in ("contract", "authority"))
            if model is None:
                raise ValueError("target requires an explicit model request or saved model/fields")
        needs_model = target != "geometry" and model != documents.get("model", documents.get("fields"))
        needs_geometry = "geometry" not in products and (target == "geometry" or needs_model)
        if needs_geometry:
            if "geometry" not in groups:
                raise ValueError("new model needs an explicit geometry product or geometry request")
            stages.append("geometry")
        if needs_model:
            stages.append("model")
        if target in {"fields", "trajectory"}:
            if "fields" in groups:
                arguments = groups["fields"]
                if set(arguments) != {"numerics"}:
                    raise ValueError("fields request requires numerics; select reuse through available fields")
                refinement = require_field_numerics(model, arguments["numerics"])
                if ("fields" in products and
                        refinement != products["fields"].metadata["spatial_identity"]["refinement"]):
                    raise ValueError("explicit saved fields conflict with requested refinement")
            needs_fields = "fields" not in products or model != documents.get("fields")
            if needs_fields:
                if "fields" not in groups:
                    raise ValueError("field solve/rebind requires explicit field numerics")
                stages.append("fields")
                if "fields" in products:
                    pending.append("existing solve_fields validates actual tool/refiner/auditor spatial identity before basis reuse")
        if target == "trajectory":
            if "trajectory" not in groups:
                raise ValueError("trajectory requires explicit gas, source, numerics, interface and SDS inputs")
            arguments = groups["trajectory"]
            _target_arguments(track_fields, arguments, reference=True)
            from msplatform.backends.simion.dual_cone_transport import SDS_FILES
            source = json.loads(Path(arguments["source_spec_path"]).read_text(encoding="utf-8-sig"))
            numerics = json.loads(Path(arguments["numerics_path"]).read_text(encoding="utf-8-sig"))
            current_geometry = plan_geometry_stage(resolved=model["geometry"]["resolved"], numerics=numerics)["projection"]
            if current_geometry != model["geometry"]:
                raise ValueError("tracking numerics redefine selected geometry")
            sds = {name: file_record(Path(arguments["collision_sds_dir"]) / name, "required_evidence") for name in SDS_FILES}
            plan_saved_fly_inputs(model, gas_field_reference=arguments["gas_field_reference"], source_spec=source,
                numerics=numerics, collision_science=arguments["collision_science"], collision_sds_records=sds,
                placement=arguments.get("placement"), source_to_device=arguments.get("source_to_device"))
            authorities.extend(sds.values())
            authorities.extend(file_record(Path(arguments[name]), "required_evidence")
                               for name in ("source_spec_path", "numerics_path", "interface_path"))
            if any(record.get("exists") is not True for record in authorities):
                raise ValueError("explicit trajectory input is missing")
            stages.append("trajectory")
    # These are small request/file identities, not a cache or a new run record.
    reasons = {}
    for stage in stages:
        if stage == "geometry":
            reasons[stage] = "no selected geometry product; build the explicit geometry request"
        elif stage == "model":
            reasons[stage] = "bind the requested drive/clock/physics to explicit geometry"
        elif stage == "fields":
            reasons[stage] = ("rebind the selected basis to the requested model; backend verifies actual compatibility"
                              if "fields" in products else "no fields selected; solve with explicit field numerics")
        else:
            reasons[stage] = "no complete trajectory selected; track explicit source/gas using selected fields"
    plan = dict(target=target, request=groups, available=references, stages=stages, stage_reasons=reasons,
                pending_runtime_checks=pending, request_authorities=authorities)
    plan["request_sha256"] = canonical_json_sha256(plan)
    return plan, products


def plan_to(*, target: str, request: Mapping | None = None, available: Mapping | None = None) -> dict:
    """Plan only this named workflow; no context, native tools, run or lease."""
    return _target_plan(target=target, request=request, available=available)[0]


def run_to(plan: dict, *, context: ExecutionContext | None = None) -> OpenedArtifact:
    """Revalidate explicit inputs, then call only the existing named stages."""
    from msplatform.io.file_identity import canonical_json_sha256

    if not isinstance(plan, dict) or set(plan) != {
            "target", "request", "available", "stages", "stage_reasons", "pending_runtime_checks", "request_authorities", "request_sha256"}:
        raise ValueError("current dual-cone target plan required")
    identity = canonical_json_sha256({key: value for key, value in plan.items() if key != "request_sha256"})
    if identity != plan["request_sha256"]:
        raise ValueError("target plan request was modified")
    current, products = _target_plan(target=plan["target"], request=plan["request"], available=plan["available"])
    if current != plan:
        raise ValueError("target request authority changed after planning")
    if plan["stages"] and context is None:
        raise ValueError("execution context is required for requested native stages")
    request = plan["request"]
    for stage in plan["stages"]:
        if stage == "geometry":
            products[stage] = build_geometry(context=context, **request[stage])
        elif stage == "model":
            products[stage] = prepare_model(products["geometry"], context=context, **request[stage])
        elif stage == "fields":
            products[stage] = solve_fields(products["model"], context=context,
                reuse_fields_reference=products.get("fields"), **request[stage])
        else:
            products[stage] = track_fields(products["fields"], context=context, **request[stage])
    return products[plan["target"]]
