"""Pure admission of the current single dual-cone SDS study.

This does not admit a native execution or validate a published gas payload.
Those checks belong to the consuming backend and its artifact owner.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
from decimal import Decimal
import hashlib
import math
from pathlib import Path, PureWindowsPath

from msplatform import components
from msplatform.components.dual_cone_tandem_quadrupole.gas_environment import (
    require_sds_positive_ion,
    resolve_dual_cone_conditions,
)
from .native_assets import _document, _freeze_reference, _validate_reference
from msplatform.particle_release.release import validate_release_spec


def project_sds_numerics(study: Mapping, recording: Mapping) -> dict:
    """Project one authored numerical policy into the existing native document."""
    import copy

    numerics = study.get("numerics") if isinstance(study, Mapping) else None
    if not isinstance(numerics, Mapping) or set(numerics) != {"geometry", "fields", "tracing"}:
        raise ValueError("SDS study requires explicit geometry, fields and tracing numerics")
    geometry, fields, tracing = (numerics[key] for key in ("geometry", "fields", "tracing"))
    if (not isinstance(geometry, Mapping) or set(geometry) != {"schema_version", "role", "project_id", "solver", "qualification_status", "pa", "workbench"}
            or geometry["schema_version"] != 1 or geometry["role"] != "dual_cone_simion_solver_numerics"
            or geometry["project_id"] != "dual_cone_tandem_quadrupole"):
        raise ValueError("SDS geometry numerics require their explicit native document identity")
    pa = geometry["pa"]
    if not isinstance(pa, Mapping) or set(pa) != {"grid_points_xyz", "cell_mm_xyz", "surface_enhancement", "symmetry", "basis_namespace"}:
        raise ValueError("SDS geometry PA settings differ or duplicate refinement")
    if not isinstance(fields, Mapping) or set(fields) not in ({"refine_policy"}, {"refine_policy", "convergence_v"}):
        raise ValueError("SDS field numerics require one explicit refinement policy")
    if not isinstance(tracing, Mapping) or set(tracing) != {"end_policy", "simion"}:
        raise ValueError("SDS tracing numerics differ")
    end, simion = tracing["end_policy"], tracing["simion"]
    if (not isinstance(end, Mapping) or set(end) != {"maximum_particle_age_us"}
            or not isinstance(simion, Mapping) or set(simion) != {"maximum_step_us", "trajectory_quality", "rf_steps_per_period", "random_seed"}):
        raise ValueError("SDS tracing requires explicit age, step, quality, RF steps and seed")
    if (not isinstance(recording, Mapping) or set(recording) != {"mode", "sample_interval_us", "end_time_us"}
            or recording["mode"] != "actual_callback_samples"):
        raise ValueError("SDS records actual callback samples, not exact observation times")
    for name, value in (("maximum_particle_age_us", end["maximum_particle_age_us"]),
                        ("maximum_step_us", simion["maximum_step_us"]),
                        ("sample_interval_us", recording["sample_interval_us"]), ("end_time_us", recording["end_time_us"])):
        if type(value) not in (int, float, Decimal) or not math.isfinite(value) or value <= 0:
            raise ValueError("SDS numerical value must be finite and positive: " + name)
    if float(recording["end_time_us"]) != float(end["maximum_particle_age_us"]):
        raise ValueError("SDS recording horizon differs from its native end policy")
    if (type(simion["trajectory_quality"]) is not int or not -500 <= simion["trajectory_quality"] <= 500
            or type(simion["rf_steps_per_period"]) is not int or simion["rf_steps_per_period"] <= 0
            or type(simion["random_seed"]) is not int or simion["random_seed"] < 0):
        raise ValueError("SDS quality, RF steps or random seed differs")
    policy = fields["refine_policy"]
    if (policy == "simion_refine_without_convergence_argument" and set(fields) != {"refine_policy"}
            or policy == "explicit_convergence" and (set(fields) != {"refine_policy", "convergence_v"}
                or type(fields["convergence_v"]) not in (int, float)
                or not math.isfinite(fields["convergence_v"]) or fields["convergence_v"] <= 0)
            or policy not in {"simion_refine_without_convergence_argument", "explicit_convergence"}):
        raise ValueError("SDS refinement policy differs")
    result = copy.deepcopy(dict(geometry))
    result["pa"].update(copy.deepcopy(dict(fields)))
    result["trajectory"] = dict(rf_steps_per_period=simion["rf_steps_per_period"],
        sample_interval_us=float(recording["sample_interval_us"]), trajectory_quality=simion["trajectory_quality"],
        maximum_time_us=float(end["maximum_particle_age_us"]), maximum_step_us=float(simion["maximum_step_us"]),
        random_seed=simion["random_seed"])
    return result


def validate_sds_physics(study: Mapping) -> tuple[dict, dict]:
    """Require the explicitly authored interface and model-only collision view."""
    import copy

    physics = study.get("physics") if isinstance(study, Mapping) else None
    if not isinstance(physics, Mapping):
        raise ValueError("SDS physics must be explicit")
    interface, collision = physics.get("gas_field_interface"), physics.get("sds_collision_science")
    if (not isinstance(interface, dict) or interface.get("schema_version") != 2
            or interface.get("role") != "dual_cone_simion_gas_field_interface"
            or interface.get("project_id") != "dual_cone_tandem_quadrupole"):
        raise ValueError("SDS requires its actual gas-field interface")
    if (not isinstance(collision, dict) or set(collision) != {"diffusion_enabled", "field_authority"}
            or type(collision["diffusion_enabled"]) is not bool
            or collision["field_authority"] != "config/gas_field_interface.json"):
        raise ValueError("SDS collision science must be model-only and bind the actual interface")
    return copy.deepcopy(interface), copy.deepcopy(collision)


def validate_sds_release(release: Mapping) -> dict:
    """Select the exact canonical cylinder request supported by the native leaf."""
    import copy

    if not isinstance(release, Mapping) or release.get("role") != "canonical_birth_source_request":
        raise ValueError("SDS requires an explicit canonical generated birth request")
    spec = release.get("release_spec")
    validate_release_spec(spec)
    if (spec["geometry"]["shape"] != "cylinder" or release.get("instrument_origin_us") != 0
            or spec["common_time_of_birth_s"] != 0):
        raise ValueError("SDS requires an explicit zero-time cylinder source")
    require_sds_positive_ion(spec)
    ids = release.get("particle_ids")
    count = spec["particle_count"]
    if ids is not None and ids != list(range(1, count + 1)):
        raise ValueError("SDS source supports the generator's original particle IDs only")
    weights = release.get("relative_weights")
    if weights is not None and (not isinstance(weights, Mapping)
            or set(weights) != {str(i) for i in range(1, count + 1)}
            or any(type(value) not in (int, float) or value != 1 for value in weights.values())):
        raise ValueError("SDS source supports only explicitly unit particle weights")
    return copy.deepcopy(dict(spec))


def _check_gas_manifest(document: dict) -> None:
    products = document.get("products")
    product = products.get("gas_field") if isinstance(products, dict) else None
    if (type(document.get("schema_version")) is not int or document["schema_version"] not in (1, 2)
            or document.get("role") != "simulation_run_manifest" or document.get("status") != "success"
            or document.get("lifecycle_state") == "provisional"
            or not isinstance(product, dict) or type(product.get("schema_version")) is not int or product["schema_version"] != 1
            or product.get("kind") != "gas_field" or product.get("status") != "complete"
            or not isinstance(product.get("metadata"), dict) or product["metadata"].get("backend") != "comsol"
            or not isinstance(product.get("data"), dict)):
        raise ValueError("SDS requires a complete published COMSOL gas_field")
    inputs, outputs = document.get("inputs"), document.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ValueError("gas_field manifest requires owner records")
    records = [*inputs.values(), *outputs]
    for name in ("science", "science_author", "numerics", "geometry", "environment", "species_data",
                 "constants_data", "transport_data", "field_csv", "field_metadata"):
        if not isinstance(product["data"].get(name), dict) or product["data"][name] not in records:
            raise ValueError("gas_field record is absent or not owner-bound: " + name)


def _snapshot(payload: bytes) -> dict:
    return {"sha256": hashlib.sha256(payload).hexdigest().upper(),
            "bytes_base64": base64.b64encode(payload).decode("ascii")}


def _decode(snapshot: Mapping) -> bytes:
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"sha256", "bytes_base64"}:
        raise ValueError("invalid SDS resource snapshot")
    try:
        payload = base64.b64decode(snapshot["bytes_base64"], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid SDS resource encoding") from error
    if _snapshot(payload) != dict(snapshot):
        raise ValueError("SDS resource snapshot identity differs")
    return payload


def _relative(record: Mapping, base: Path) -> Path:
    if not isinstance(record, Mapping) or set(record) != {"path", "bytes", "sha256"}:
        raise ValueError("SDS resource requires a path, byte count and SHA-256")
    path = record["path"]
    if (not isinstance(path, str) or not path or Path(path).is_absolute()
            or PureWindowsPath(path).is_absolute() or PureWindowsPath(path).drive
            or ".." in PureWindowsPath(path).parts or ".." in Path(path).parts):
        raise ValueError("SDS resource path must be relative")
    return base / path


def _check_request(request: dict) -> None:
    if (set(request) != {"environment_instance_id", "environment_record", "gas_field_reference", "sds_records"}
            or request["environment_instance_id"] != "dual_cone"
            or not isinstance(request["sds_records"], dict)
            or not request["sds_records"]
            or len({name.casefold() for name in request["sds_records"] if isinstance(name, str)}) != len(request["sds_records"])
            or any(not isinstance(name, str) or not name or Path(name).name != name
                   or PureWindowsPath(name).name != name or name.casefold() in {"sds_request.json", "sds_environment.json", "sds_gas_field"}
                   for name in request["sds_records"])):
        raise ValueError("SDS request differs from the supported single-instance closure")


def freeze_sds_resources(request_path: Path, expected_sha256: str) -> dict:
    """Freeze only the small explicit request, sources and producer manifest once."""
    path = Path(request_path).absolute()
    payload = path.read_bytes()
    if _snapshot(payload)["sha256"] != str(expected_sha256).upper():
        raise ValueError("SDS request SHA-256 mismatch")
    request = _document(payload)
    _check_request(request)
    result = {"sds_request.json": _snapshot(payload)}
    for name, record in [("sds_environment.json", request["environment_record"]),
                         *request["sds_records"].items()]:
        data = _relative(record, path.parent).read_bytes()
        if type(record["bytes"]) is not int or len(data) != record["bytes"] or _snapshot(data)["sha256"] != str(record["sha256"]).upper():
            raise ValueError("SDS source differs from its declared identity: " + name)
        result[name] = _snapshot(data)
    result["sds_gas_field"] = _freeze_reference(request["gas_field_reference"], path,
                                                  product_id="gas_field", check=_check_gas_manifest)
    validate_sds_resources(result, expected_sha256)
    return result


def validate_sds_resources(resources: Mapping, expected_sha256: str) -> dict:
    """Validate frozen bytes without rereading author paths or native payloads."""
    if not isinstance(resources, Mapping):
        raise ValueError("SDS resource closure differs")
    request = _document(_decode(resources["sds_request.json"]))
    if resources["sds_request.json"]["sha256"] != str(expected_sha256).upper():
        raise ValueError("frozen SDS request differs from author identity")
    _check_request(request)
    if set(resources) != {"sds_request.json", "sds_environment.json", "sds_gas_field", *request["sds_records"]}:
        raise ValueError("SDS resource closure differs")
    for name, record in [("sds_environment.json", request["environment_record"]),
                         *request["sds_records"].items()]:
        _relative(record, Path("."))
        payload = _decode(resources[name])
        if type(record["bytes"]) is not int or len(payload) != record["bytes"] or resources[name]["sha256"] != str(record["sha256"]).upper():
            raise ValueError("frozen SDS source differs: " + name)
    frozen = _validate_reference(resources["sds_gas_field"], product_id="gas_field", check=_check_gas_manifest)
    selected = request["gas_field_reference"]
    if (not isinstance(selected, Mapping) or set(selected) != {"path", "sha256", "product_id"}
            or selected["product_id"] != "gas_field"
            or frozen["reference"]["manifest"]["sha256"] != str(selected["sha256"]).upper()):
        raise ValueError("frozen gas_field manifest differs from request")
    return request


def sds_resource_identities(resources: Mapping, expected_sha256: str) -> dict:
    """Path-independent identities for the frozen five-file native closure."""
    request = validate_sds_resources(resources, expected_sha256)
    return {name: {"bytes": len(_decode(resources[name])), "sha256": resources[name]["sha256"]}
            for name in request["sds_records"]}


def sds_environment_bytes(resources: Mapping, expected_sha256: str) -> bytes:
    """Return the authenticated original author bytes without rereading paths."""
    validate_sds_resources(resources, expected_sha256)
    return _decode(resources["sds_environment.json"])


def resolve_sds_conditions(study: Mapping, environment_author: dict, species: Sequence[Mapping]) -> dict:
    """Bind the sole supported instance and explicitly positive species to gas authority.

    The existing native stage currently names this domain ``dual_cone``.  Keep
    that limitation explicit until the stage can project arbitrary instance IDs.
    Assembly validation and source/snapshot verification remain caller duties.
    """
    requests = study.get("component_requests")
    if not isinstance(requests, Mapping) or set(requests) != {"dual_cone"}:
        raise ValueError("SDS requires the single supported dual_cone instance")
    component = components.resolve_component(requests["dual_cone"])
    if component.provider_id != "dual_cone_tandem_quadrupole":
        raise ValueError("SDS requires the dual-cone provider")
    recipe = study.get("recipe")
    instances = recipe.get("instances") if isinstance(recipe, Mapping) else None
    if (not isinstance(instances, list) or len(instances) != 1
            or instances[0].get("instance_id") != "dual_cone"):
        raise ValueError("SDS Assembly must select the dual_cone instance")
    if not isinstance(species, Sequence) or isinstance(species, (str, bytes)) or not species:
        raise ValueError("SDS requires explicit species")
    for value in species:
        require_sds_positive_ion({"species": value})
    return resolve_dual_cone_conditions(environment_author, component.resolved_design)
