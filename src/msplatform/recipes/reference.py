"""Parse an explicit reference study into a validated SI scientific contract.

The reference geometry is a single analytic cell, not a registered instrument
provider. Decimal TOML literals are converted once before float64 computation.
"""
from __future__ import annotations

import copy
import math
import re
from decimal import Decimal
from typing import Any, Mapping

from . import assembly_name
from msplatform.io.file_identity import canonical_json_sha256
from msplatform.physics import CONSTANTS, GasEnvironment, normalize_charge_c
from msplatform.contracts.species import validate_species


def _keys(value: Any, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f"expected fields {sorted(required)}, optional {sorted(optional)}")


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _vector(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must have three components")
    return [_number(v, name) for v in value]


def _identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError(f"{name} must be a lowercase ASCII identifier")
    return value


def _quantity(row: dict, choices: dict[str, str], name: str, vector: bool = False) -> Any:
    present = set(row) & choices.keys()
    if len(present) != 1:
        raise ValueError(f"{name}: select exactly one explicitly unit-tagged field")
    key = present.pop()
    values = row[key] if vector else [row[key]]
    if not isinstance(values, list) or (vector and len(values) != 3):
        raise ValueError(f"{name} must have three components")
    result = []
    for value in values:
        _number(value, name)
        converted = float(Decimal(str(value)) * Decimal(choices[key]))
        if not math.isfinite(converted):
            raise ValueError(f"{name} is not representable")
        result.append(converted)
    return result if vector else result[0]


def _surface(row: dict) -> dict:
    _keys(row, {"surface_id", "component_id", "axis", "position_m", "kind"}, {"electrode_id"})
    surface = {"surface_id": _identity(row["surface_id"], "surface_id"),
               "component_id": _identity(row["component_id"], "component_id"),
               "electrode_id": row.get("electrode_id"), "axis": row["axis"],
               "position_m": _number(row["position_m"], "surface position"), "kind": row["kind"]}
    if surface["electrode_id"] is not None:
        _identity(surface["electrode_id"], "electrode_id")
    if type(surface["axis"]) is not int or surface["axis"] not in (0, 1, 2):
        raise ValueError("surface axis must be 0, 1 or 2")
    if surface["kind"] not in ("detector", "electrode", "observation"):
        raise ValueError("unsupported surface kind")
    if surface["kind"] == "electrode" and surface["electrode_id"] is None:
        raise ValueError("electrode surface requires its electrode identity")
    return surface


def _particle(row: dict, species_by_id: dict[str, dict]) -> dict:
    required = {"particle_id", "species_id", "velocity_m_s", "weight"}
    choices = {"position_m", "position_mm", "time_s", "time_us"}
    _keys(row, required, choices)
    if type(row["particle_id"]) is not int or not 0 < row["particle_id"] <= 2**63 - 1:
        raise ValueError("particle_id must be a positive int64")
    species_id = _identity(row["species_id"], "species_id")
    if species_id not in species_by_id:
        raise ValueError("particle refers to unknown species")
    species = species_by_id[species_id]
    result = {"particle_id": row["particle_id"], "species_id": _identity(row["species_id"], "species_id"),
              "parent_particle_id": None, "lineage_status": "unavailable_initial_snapshot",
              "position_m": _quantity(row, {"position_m": "1", "position_mm": "0.001"}, "position", True),
              "velocity_m_s": _vector(row["velocity_m_s"], "velocity_m_s"),
              "time_s": _quantity(row, {"time_s": "1", "time_us": "0.000001"}, "time"),
              "mass_kg": species["mass_kg"],
              "charge_state": species["charge_state"], "charge_c": species["charge_c"],
              "weight": _number(row["weight"], "weight")}
    if result["mass_kg"] <= 0 or result["weight"] <= 0 or result["time_s"] < 0:
        raise ValueError("mass and weight must be positive; relative time must be nonnegative")
    return result


def _numerics(row: dict, states: list[dict]) -> dict:
    keys = {"end_time_s", "rtol", "position_atol_m", "velocity_atol_m_s", "max_step_s", "sample_count"}
    _keys(row, keys)
    result = {k: _number(row[k], k) for k in keys - {"sample_count"}}
    if any(v <= 0 for v in result.values()) or result["rtol"] >= 1:
        raise ValueError("numeric tolerances and step must be positive, with rtol < 1")
    if type(row["sample_count"]) is not int or row["sample_count"] < 2:
        raise ValueError("sample_count must be an integer >= 2")
    if any(p["time_s"] >= result["end_time_s"] for p in states):
        raise ValueError("end_time_s must follow every particle birth")
    result["sample_count"] = row["sample_count"]
    return result


def resolve_reference(raw: dict) -> dict:
    keys = {"schema_version", "label", "frame_id", "particle_tracer", "assembly", "clock", "gas_environment", "field_source", "species", "initial_states", "numerics", "surfaces", "recording"}
    _keys(raw, keys)
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 3:
        raise ValueError("unsupported recipe schema_version")
    if not isinstance(raw["label"], str) or not raw["label"].strip():
        raise ValueError("label must be nonempty")
    _identity(raw["frame_id"], "frame_id")
    if raw["particle_tracer"] != "scipy_dop853":
        raise ValueError("unsupported particle tracer")
    _keys(raw["assembly"], {"component_ids"})
    components = raw["assembly"]["component_ids"]
    name = assembly_name(components)
    if components != ["reference_cell"]:
        raise ValueError("only the single reference_cell analytic geometry is supported")
    _keys(raw["clock"], {"basis"})
    if raw["clock"]["basis"] != "experiment_relative":
        raise ValueError("only the experiment-relative clock is supported")
    _keys(raw["gas_environment"], {"status"})
    gas = GasEnvironment(raw["gas_environment"]["status"]).to_dict()
    field = raw["field_source"]
    _keys(field, {"kind", "time_dependence", "electric_field_v_m", "magnetic_field_t"})
    if field["kind"] != "uniform" or field["time_dependence"] != "static":
        raise ValueError("reference tracer supports static uniform prescribed fields only")
    field = {**field, "electric_field_v_m": _vector(field["electric_field_v_m"], "electric field"),
             "magnetic_field_t": _vector(field["magnetic_field_t"], "magnetic field")}
    if not isinstance(raw["initial_states"], list) or not raw["initial_states"]:
        raise ValueError("initial_states must be nonempty")
    if not isinstance(raw["species"], list) or not raw["species"]:
        raise ValueError("species must be a nonempty array")
    species = []
    for row in raw["species"]:
        _keys(row, {"species_id", "species_kind", "charge_state"}, {"mass_kg", "mass_u", "charge_c", "mass_data_version", "mass_data_sha256", "atomic_mass_constant_version"})
        charge = row["charge_state"]
        if type(charge) is not int or charge == 0:
            raise ValueError("charge_state must be a nonzero signed integer")
        record = {"species_id": row["species_id"], "species_kind": row["species_kind"],
                  "mass_kg": _quantity(row, {"mass_kg": "1", "mass_u": str(CONSTANTS["atomic_mass_constant_kg"])}, "mass"),
                  "charge_state": charge,
                  "charge_c": row.get("charge_c", charge * CONSTANTS["elementary_charge_c"])}
        for key in ("mass_data_version", "mass_data_sha256", "atomic_mass_constant_version"):
            if key in row:
                record[key] = row[key]
        species.append(validate_species(record))
    species_by_id = {row["species_id"]: row for row in species}
    if len(species_by_id) != len(species):
        raise ValueError("species IDs must be unique")
    states = [_particle(p, species_by_id) for p in raw["initial_states"]]
    if len({p["particle_id"] for p in states}) != len(states):
        raise ValueError("particle IDs must be unique")
    if not isinstance(raw["surfaces"], list):
        raise ValueError("surfaces must be an array")
    surfaces = [_surface(s) for s in raw["surfaces"]]
    if len({s["surface_id"] for s in surfaces}) != len(surfaces):
        raise ValueError("surface IDs must be unique")
    if any(s["component_id"] != "reference_cell" for s in surfaces):
        raise ValueError("surface must belong to reference_cell")
    _keys(raw["recording"], {"trajectory"})
    if raw["recording"]["trajectory"] != "sampled":
        raise ValueError("only sampled trajectories are supported")
    physical = {"schema_version": 1, "frame_id": raw["frame_id"], "component_ids": components,
                "instances": [{"instance_id": "reference_cell", "component_id": "reference_cell",
                               "translation_m": [0.0, 0.0, 0.0],
                               "rotation_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}],
                "connections": [], "surfaces": surfaces}
    assembly = {**physical, "name_version": 1, "name": name, "assembly_id": canonical_json_sha256(physical)}
    result = {"schema_version": 3, "label": raw["label"], "assembly": assembly, "species": species,
              "frame_id": raw["frame_id"], "clock": {"basis": "experiment_relative", "unit": "s"},
              "constants": dict(CONSTANTS), "gas_environment": gas, "field_source": field,
              "particle_tracer": raw["particle_tracer"], "initial_states": states,
              "numerics": _numerics(raw["numerics"], states), "surfaces": surfaces,
              "recording": {"trajectory": "sampled"}}
    result["recipe_id"] = canonical_json_sha256({k: v for k, v in result.items() if k != "label"})
    return result


def validate_reference(resolved: Mapping[str, Any]) -> dict:
    """Validate an SI resolved document, its identities and capability claims."""
    data = copy.deepcopy(dict(resolved))
    _keys(data, {"schema_version", "label", "assembly", "recipe_id", "frame_id", "clock", "constants", "gas_environment", "field_source", "particle_tracer", "species", "initial_states", "numerics", "surfaces", "recording"})
    if data["constants"] != CONSTANTS or data["gas_environment"] != GasEnvironment("vacuum").to_dict() or data["clock"] != {"basis": "experiment_relative", "unit": "s"}:
        raise ValueError("unsupported constants, gas or clock")
    raw = {k: data[k] for k in ("schema_version", "label", "frame_id", "particle_tracer", "field_source", "numerics", "surfaces", "recording")}
    raw.update(assembly={"component_ids": data["assembly"]["component_ids"]}, clock={"basis": "experiment_relative"}, gas_environment={"status": "vacuum"})
    raw["species"] = copy.deepcopy(data["species"])
    raw["initial_states"] = []
    for particle in data["initial_states"]:
        _keys(particle, {"particle_id", "species_id", "position_m", "velocity_m_s", "time_s", "mass_kg", "charge_state", "charge_c", "weight", "parent_particle_id", "lineage_status"})
        p = dict(particle)
        if p.pop("parent_particle_id") is not None or p.pop("lineage_status") != "unavailable_initial_snapshot":
            raise ValueError("initial snapshot lineage is unavailable")
        particle["charge_c"] = normalize_charge_c(p["charge_state"], p.pop("charge_c"))
        p.pop("charge_state")
        p.pop("mass_kg")
        raw["initial_states"].append(p)
    expected = resolve_reference(raw)
    if data != expected:
        raise ValueError("resolved recipe differs from its validated contents or identity")
    return expected
