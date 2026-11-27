"""Installed versioned species data and derived SI views."""

from importlib.resources import files
from hashlib import sha256
import json
from types import MappingProxyType

from .particle_physics import CONSTANTS

FROZEN_PACKAGE_RESOURCES = (
    "physics/data/nitrogen.json", "physics/data/hs1_example_assumption.json", "physics/data/sds_model.json",
)


_nitrogen_bytes = files("msplatform").joinpath("physics/data/nitrogen.json").read_bytes()
_source = json.loads(_nitrogen_bytes)
if _source["schema_version"] != 1 or _source["dataset_id"] != "nitrogen_effective_hard_sphere_v1":
    raise ValueError("unsupported nitrogen dataset")
_mass_u = float(_source["relative_molecular_mass"])
_diameter_m = float(_source["effective_hard_sphere_diameter_m"])
NITROGEN = MappingProxyType({
    "version": _source["dataset_id"],
    "dataset_sha256": sha256(_nitrogen_bytes).hexdigest(),
    "species_id": _source["species_id"],
    "mass_amu": _mass_u,
    "avogadro_constant_per_mol": float(_source["avogadro_constant_per_mol"]),
    "molar_mass_kg_per_mol": _mass_u * CONSTANTS["atomic_mass_constant_kg"]
    * float(_source["avogadro_constant_per_mol"]),
    "effective_hard_sphere_diameter_m": _diameter_m,
    "effective_hard_sphere_diameter_nm": _diameter_m * 1e9,
    "atomic_mass_constant_version": CONSTANTS["version"],
})

_hs1_bytes = files("msplatform").joinpath("physics/data/hs1_example_assumption.json").read_bytes()
_hs1 = json.loads(_hs1_bytes)
if (_hs1["schema_version"] != 1
        or _hs1["version"] != "simion_hs1_helium_example_uncalibrated_assumption_v1"):
    raise ValueError("unsupported HS1 assumption dataset")
HS1_EXAMPLE_ASSUMPTION = MappingProxyType({
    "model_id": _hs1["model_id"],
    "version": _hs1["version"],
    "dataset_sha256": sha256(_hs1_bytes).hexdigest(),
    "cross_section_m2": float(_hs1["cross_section_m2"]),
    "original_example": _hs1["original_example"],
    "qualification": _hs1["qualification"],
    "limitation": _hs1["limitation"],
})

_sds_bytes = files("msplatform").joinpath("physics/data/sds_model.json").read_bytes()
_sds = json.loads(_sds_bytes)
if _sds["schema_version"] != 1 or _sds["version"] != "simion_official_collision_sds_v1":
    raise ValueError("unsupported SDS dataset")
SDS_MODEL = MappingProxyType({
    "model_id": _sds["model_id"],
    "version": _sds["version"],
    "dataset_sha256": sha256(_sds_bytes).hexdigest(),
    "qualification": _sds["qualification"],
    "limitation": _sds["limitation"],
})


def resolve_nitrogen(reference: dict) -> dict:
    """Resolve the sole current N2 data version into a native-neutral view."""
    if reference != {"species_id": NITROGEN["species_id"], "version": NITROGEN["version"]}:
        raise ValueError("unsupported nitrogen species identity or data version")
    return dict(NITROGEN)


def resolve_hs1_example_assumption(reference: dict) -> dict:
    """Resolve the historical HS1 example only as an uncalibrated assumption."""
    if reference != {"model_id": HS1_EXAMPLE_ASSUMPTION["model_id"],
                     "version": HS1_EXAMPLE_ASSUMPTION["version"]}:
        raise ValueError("unsupported HS1 assumption identity or data version")
    return dict(HS1_EXAMPLE_ASSUMPTION)


def resolve_sds_model(reference: dict) -> dict:
    """Resolve the single current documented SDS model identity."""
    if reference != {"model_id": SDS_MODEL["model_id"], "version": SDS_MODEL["version"]}:
        raise ValueError("unsupported SDS model identity or data version")
    return dict(SDS_MODEL)


def project_nitrogen_hs1_assumption(species_ref: dict, model_ref: dict) -> dict:
    """Project a declared N2 bath and historical, uncalibrated HS1 assumption.

    The pair remains explicitly unqualified; the cross section is not an N2
    material property.  The result is a view for an actual backend consumer,
    not evidence that any trajectory or collision model has been validated.
    """
    species = resolve_nitrogen(species_ref)
    model = resolve_hs1_example_assumption(model_ref)
    return {
        "gas_mass_amu": species["mass_amu"],
        "cross_section_m2": model["cross_section_m2"],
        "gas_species": species,
        "collision_assumption": model,
    }
