"""Canonical view of the historical OA ION11 box generator."""
from __future__ import annotations

import math
import csv
import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from .dotnet_gaussian_box_ion11 import generate_particle_source
from .cylinder import CANONICAL_COLUMNS, _serialized_rows, _state_identity, _sha256_text, _canonical_json
from msplatform.io.file_identity import file_sha256
from ._history import receipt_reader
from msplatform.contracts.species import validate_release_species

STRATEGY = "dotnet_gaussian_box_ion11_v1"
CONSTANTS_ID = "repository_particle_physics_v1"


def validate_dotnet_box_spec(spec: Mapping[str, Any]) -> None:
    if not isinstance(spec, dict) or set(spec) != {"schema_version", "role", "frame_id", "particle_count", "mother_particle_count", "common_time_of_birth_s", "geometry", "species", "sampling"}:
        raise ValueError("complete box release specification required")
    identity = (2, "repository_particle_release")
    if type(spec["schema_version"]) is not int or (spec["schema_version"], spec["role"]) != identity or not isinstance(spec["frame_id"], str) or not spec["frame_id"].strip():
        raise ValueError("invalid box release identity")
    count, mother = spec["particle_count"], spec["mother_particle_count"]
    if type(count) is not int or type(mother) is not int or not 0 < count <= mother:
        raise ValueError("box count must be a positive mother prefix")
    if type(spec["common_time_of_birth_s"]) not in (int, float) or spec["common_time_of_birth_s"] != 0:
        raise ValueError("historical ION11 box birth time must be zero")
    g, species, sampling = spec["geometry"], spec["species"], spec["sampling"]
    if not isinstance(g, dict) or set(g) != {"shape", "center_mm", "half_width_mm"} or g["shape"] != "box":
        raise ValueError("box geometry requires center and half widths")
    for key in ("center_mm", "half_width_mm"):
        vector = g[key]
        if not isinstance(vector, list) or len(vector) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError("box vectors must contain three finite values")
    if any(x < 0 for x in g["half_width_mm"]):
        raise ValueError("box half widths must be nonnegative")
    validate_release_species(species)
    if species["species_kind"] == "electron":
        raise ValueError("historical ION11 box precision does not preserve the versioned electron mass")
    if not isinstance(species, dict) or set(species) != {"species_kind", "mass_amu", "charge_state"} or type(species["mass_amu"]) not in (int, float) or not math.isfinite(species["mass_amu"]) or species["mass_amu"] <= 0 or type(species["charge_state"]) is not int or species["charge_state"] == 0:
        raise ValueError("invalid box species")
    if not isinstance(sampling, dict) or set(sampling) != {"strategy", "seed", "energy_mean_ev", "energy_std_ev", "constants_id"} or sampling["strategy"] != STRATEGY or sampling["constants_id"] != CONSTANTS_ID or type(sampling["seed"]) is not int or not -(2**31) <= sampling["seed"] < 2**31:
        raise ValueError("explicit historical box sampling and constants required")
    if any(type(sampling[k]) not in (int, float) or not math.isfinite(sampling[k]) for k in ("energy_mean_ev", "energy_std_ev")) or sampling["energy_mean_ev"] <= 0 or sampling["energy_std_ev"] < 0:
        raise ValueError("invalid Gaussian energy")


def generate_dotnet_box_states(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use emitted ION11 precision; velocity is a declared conversion, not native evidence."""
    validate_dotnet_box_spec(spec)
    g, species, sampling = spec["geometry"], spec["species"], spec["sampling"]
    lines = generate_particle_source(particle_count=spec["particle_count"], mass_amu=species["mass_amu"],
        charge=species["charge_state"], energy_mean_ev=sampling["energy_mean_ev"],
        energy_std_ev=sampling["energy_std_ev"], half_width_xyz_mm=tuple(g["half_width_mm"]),
        center_xyz_mm=tuple(g["center_mm"]), seed=sampling["seed"])
    states = []
    for index, line in enumerate(lines, 1):
        fields = line.split(",")
        mass, energy = float(fields[1]), float(fields[8])
        speed = math.sqrt(2 * energy * ELEMENTARY_CHARGE_C / (mass * AMU_KG))
        states.append(dict(particle_id=index, birth_time_s=0.0, x_mm=float(fields[3]), y_mm=float(fields[4]),
                           z_mm=float(fields[5]), vx_m_s=speed, vy_m_s=0.0, vz_m_s=0.0,
                           mass_amu=mass, charge_state=int(fields[2])))
    return states


def materialize_dotnet_box(spec, state_table: Path, receipt: Path, spec_record=None):
    states = generate_dotnet_box_states(spec)
    state_table.parent.mkdir(parents=True, exist_ok=True)
    with state_table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(_serialized_rows(states))
    result = {"schema_version": 2, "role": "repository_particle_release", "status": "materialized",
              "frame_id": spec["frame_id"], "particle_count": spec["particle_count"],
              "mother_particle_count": spec["mother_particle_count"], "release_spec": dict(spec),
              "release_spec_sha256": _sha256_text(_canonical_json(spec)), "state_identity": _state_identity(states),
              "state_table": {"path": str(state_table.resolve()), "bytes": state_table.stat().st_size,
                              "sha256": file_sha256(state_table), "columns": list(CANONICAL_COLUMNS)},
              "source_spec": spec_record}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


@receipt_reader
def validate_materialized_dotnet_box(receipt: Path):
    data = json.loads(receipt.read_text(encoding="utf-8"))
    identity = (2, "repository_particle_release")
    if (data.get("schema_version"), data.get("role")) != identity or data.get("status") != "materialized":
        raise ValueError("invalid box receipt identity")
    spec = data["release_spec"]
    states = generate_dotnet_box_states(spec)
    if data["release_spec_sha256"] != _sha256_text(_canonical_json(spec)) or data["state_identity"] != _state_identity(states):
        raise ValueError("box receipt identity differs")
    if data["frame_id"] != spec["frame_id"] or data["particle_count"] != spec["particle_count"] or data["mother_particle_count"] != spec["mother_particle_count"]:
        raise ValueError("box receipt metadata differs")
    source = data["source_spec"]
    if source is not None:
        path = Path(source["path"])
        if not path.is_file() or path.stat().st_size != source["bytes"] or file_sha256(path) != source["sha256"]:
            raise ValueError("box source identity differs")
    table = data["state_table"]
    path = Path(table["path"])
    if table["columns"] != list(CANONICAL_COLUMNS) or not path.is_file() or path.stat().st_size != table["bytes"] or file_sha256(path) != table["sha256"]:
        raise ValueError("box table identity differs")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(CANONICAL_COLUMNS) or list(reader) != _serialized_rows(states):
            raise ValueError("box table differs from deterministic source")
    return data
