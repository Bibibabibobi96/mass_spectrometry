"""Versioned experimental gas environments and their typed frozen view."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from importlib.resources import files
import json
from types import MappingProxyType
from msplatform.contracts.gas import (
    AxisymmetricGasRegion, AxisymmetricGasValues, BoxDomain, CylindricalDomain,
    GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState, UnboundedDomain,
)

FROZEN_PACKAGE_RESOURCES = ("physics/data/reference.json",)


def _load_data() -> dict:
    data = json.loads(files("msplatform").joinpath("physics/data/reference.json").read_text(encoding="utf-8"))
    if data["schema_version"] != 1 or data["dataset_id"] != "repository_reference_physics_v1":
        raise ValueError("unsupported reference physics dataset")
    return data


_DATA = _load_data()
@dataclass(frozen=True)
class GasEnvironment:
    """One experimental gas environment, retaining the vacuum v1 view."""

    status: str
    fields: tuple[GasFieldSpec, ...] = ()
    collision_model_refs: tuple[Mapping, ...] = ()

    def __post_init__(self) -> None:
        from .gas_species import HS1_EXAMPLE_ASSUMPTION, NITROGEN, SDS_MODEL

        object.__setattr__(self, "fields", tuple(self.fields))
        refs = tuple(self.collision_model_refs)
        if self.status == "vacuum":
            if self.fields or refs:
                raise ValueError("vacuum cannot contain gas fields or collision models")
            return
        if self.status != "gas" or not self.fields or not refs:
            raise ValueError("gas requires explicit fields and collision model references")
        if any(not isinstance(field, GasFieldSpec) for field in self.fields):
            raise ValueError("gas fields must be typed GasFieldSpec values")
        ids = [field.field_id for field in self.fields]
        if len(set(ids)) != len(ids):
            raise ValueError("gas field identities must be unique")
        for field in self.fields:
            if len(field.composition) != 1 or field.composition[0].species_id != NITROGEN["species_id"] or field.composition[0].mass_amu != NITROGEN["mass_amu"] or field.composition[0].mole_fraction != 1:
                raise ValueError("gas field must use the current N2 species authority")
        known = {(model["model_id"], model["version"]) for model in (HS1_EXAMPLE_ASSUMPTION, SDS_MODEL)}
        frozen = []
        for ref in refs:
            if not isinstance(ref, Mapping) or set(ref) != {"gas_field_id", "model_id", "version"}:
                raise ValueError("collision reference requires field, model and version")
            if any(not isinstance(ref[key], str) or not ref[key] for key in ("gas_field_id", "model_id", "version")):
                raise ValueError("collision reference identities must be nonempty strings")
            if ref["gas_field_id"] not in ids or (ref["model_id"], ref["version"]) not in known:
                raise ValueError("collision reference does not bind a current gas field and model")
            frozen.append(MappingProxyType(dict(ref)))
        if len({ref["gas_field_id"] for ref in frozen}) != len(frozen) or {ref["gas_field_id"] for ref in frozen} != set(ids):
            raise ValueError("each gas field requires exactly one collision model reference")
        object.__setattr__(self, "collision_model_refs", tuple(frozen))

    def to_dict(self) -> dict:
        if self.status == "gas":
            from .gas_species import HS1_EXAMPLE_ASSUMPTION, NITROGEN, SDS_MODEL

            models = {(model["model_id"], model["version"]): model for model in (HS1_EXAMPLE_ASSUMPTION, SDS_MODEL)}
            return {"status": "gas", "environment_version": "gas_environment_v1",
                    "fields": [_plain(field) for field in self.fields],
                    "species_data": [dict(NITROGEN)],
                    "collision_models": [dict(ref, data=dict(models[(ref["model_id"], ref["version"])]))
                                         for ref in self.collision_model_refs]}
        return {"status": _DATA["gas"]["vacuum"]["status"],
                "pressure_pa": _DATA["gas"]["vacuum"]["pressure_pa"],
                "collision_model": _DATA["collision_models"]["none"]["model"],
                "data_version": _DATA["dataset_id"], "collision_model_ref": "none"}

    @classmethod
    def from_dict(cls, document: dict) -> "GasEnvironment":
        """Validate an exact frozen environment and reconstruct its typed fields."""
        if not isinstance(document, dict):
            raise ValueError("gas environment must be an object")
        if document == cls("vacuum").to_dict():
            return cls("vacuum")
        if (set(document) != {"status", "environment_version", "fields", "species_data", "collision_models"}
                or document["status"] != "gas" or document["environment_version"] != "gas_environment_v1"
                or not isinstance(document["fields"], list) or not isinstance(document["collision_models"], list)):
            raise ValueError("unsupported frozen gas environment")
        gas_fields = tuple(_typed(value) for value in document["fields"])
        refs = []
        for model in document["collision_models"]:
            if not isinstance(model, dict) or set(model) != {"gas_field_id", "model_id", "version", "data"}:
                raise ValueError("malformed frozen collision model")
            refs.append({key: model[key] for key in ("gas_field_id", "model_id", "version")})
        result = cls("gas", gas_fields, tuple(refs))
        if result.to_dict() != document:
            raise ValueError("frozen gas environment differs from current data or typed values")
        return result


def _plain(value):
    """Convert typed immutable fields to JSON values without touching sources."""
    if is_dataclass(value) and not isinstance(value, type):
        return {"_type": type(value).__name__,
                **{field.name: _plain(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


_FIELD_TYPES = {item.__name__: item for item in (
    AxisymmetricGasRegion, AxisymmetricGasValues, BoxDomain, CylindricalDomain,
    GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState, UnboundedDomain,
)}


def _typed(value):
    if isinstance(value, list):
        return tuple(_typed(item) for item in value)
    if not isinstance(value, dict):
        return value
    if "_type" not in value:
        return {key: _typed(item) for key, item in value.items()}
    name = value["_type"]
    if not isinstance(name, str):
        raise ValueError("invalid typed gas field member identity")
    kind = _FIELD_TYPES.get(name)
    if kind is None or set(value) != {"_type", *(field.name for field in fields(kind))}:
        raise ValueError("unsupported or malformed typed gas field member")
    try:
        return kind(**{key: _typed(item) for key, item in value.items() if key != "_type"})
    except (TypeError, KeyError) as error:
        raise ValueError("invalid typed gas field member") from error
