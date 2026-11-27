"""Explicit species identity for charged particles in the public SI contract."""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from msplatform.contracts.particle_physics import ELECTRON_CONSTANTS, normalize_charge_c


def validate_species(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one species without inferring its kind from charge or mass."""
    required = {"species_id", "species_kind", "mass_kg", "charge_state", "charge_c"}
    optional = {"mass_data_version", "mass_data_sha256", "atomic_mass_constant_version"}
    if not isinstance(record, Mapping) or not required <= set(record) or set(record) - required - optional:
        raise ValueError("species requires explicit identity, kind, mass and charge")
    name = record["species_id"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("species_id must be a lowercase ASCII identifier")
    kind, mass, charge = record["species_kind"], record["mass_kg"], record["charge_state"]
    if not isinstance(kind, str) or kind not in {"ion", "electron"}:
        raise ValueError("unsupported species_kind")
    if isinstance(mass, bool) or not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0:
        raise ValueError("species mass_kg must be finite and positive")
    charge_c = normalize_charge_c(charge, record["charge_c"])
    if kind == "electron" and (charge != -1 or float(mass) != ELECTRON_CONSTANTS["mass_kg"]):
        raise ValueError("electron requires charge_state=-1 and the versioned electron mass")
    mass_data_version = ELECTRON_CONSTANTS["version"] if kind == "electron" else "author_supplied"
    if record.get("mass_data_version", mass_data_version) != mass_data_version:
        raise ValueError("species mass data version disagrees with its declared kind")
    mass_data_sha256 = ELECTRON_CONSTANTS["dataset_sha256"] if kind == "electron" else None
    atomic_version = ELECTRON_CONSTANTS["atomic_mass_constant_version"] if kind == "electron" else None
    if (record.get("mass_data_sha256", mass_data_sha256) != mass_data_sha256
            or record.get("atomic_mass_constant_version", atomic_version) != atomic_version):
        raise ValueError("species mass source identity disagrees with its declared kind")
    return {"species_id": name, "species_kind": kind, "mass_kg": float(mass),
            "charge_state": charge, "charge_c": charge_c, "mass_data_version": mass_data_version,
            "mass_data_sha256": mass_data_sha256, "atomic_mass_constant_version": atomic_version}


def validate_release_species(record: Mapping[str, Any]) -> None:
    """Validate the sampler's explicitly typed mass in unified atomic mass units."""
    if not isinstance(record, Mapping) or set(record) != {"species_kind", "mass_amu", "charge_state"}:
        raise ValueError("release species requires explicit kind, mass_amu and charge_state")
    mass, charge, kind = record["mass_amu"], record["charge_state"], record["species_kind"]
    if isinstance(mass, bool) or not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0:
        raise ValueError("release species mass must be positive and finite")
    if type(charge) is not int or charge == 0 or not -(2**63) <= charge < 2**63:
        raise ValueError("release charge_state must be a nonzero signed int64")
    if not isinstance(kind, str) or kind not in {"ion", "electron"}:
        raise ValueError("unsupported release species_kind")
    if kind == "electron" and (charge != -1 or float(mass) != ELECTRON_CONSTANTS["mass_u"]):
        raise ValueError("electron requires charge_state=-1 and the versioned electron mass")
