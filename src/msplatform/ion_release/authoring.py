"""Author generated births or read an explicitly bound recorded birth source."""
from __future__ import annotations

import copy
import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from msplatform.contracts.clock import ClockIdentity, instrument_time_us, seconds_to_microseconds
from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.ion_release.continuous_axial_volume import ROLE as SNAPSHOT_ROLE
from msplatform.ion_release.release import generate_release_states
from msplatform.ion_release.cylinder import CANONICAL_COLUMNS
from msplatform.io.manifest_records import validate_file_record, verify_record


def _canonical_birth_row(source: Mapping[str, Any], *, pid: int, weight: float,
                         clock: ClockIdentity, instrument_origin_us: float,
                         species_id: str, source_component_id: str, frame_id: str) -> dict[str, Any]:
    birth = instrument_time_us(seconds_to_microseconds(source["birth_time_s"]),
                               instrument_origin_us=instrument_origin_us, native_origin_us=0.)
    mass, charge = source["mass_amu"], source["charge_state"]
    velocity = [source[f"v{axis}_m_s"] for axis in "xyz"]
    return dict(particle_id=pid, parent_particle_id=None, generation=0,
        species_id=species_id, particle_weight=weight, source_component_id=source_component_id,
        target_component_id=source_component_id, state_event="source_birth",
        frame_id=frame_id, clock_epoch_id=clock.clock_epoch_id,
        instrument_time_us=birth, lineage_birth_time_us=birth, particle_birth_time_us=birth,
        lineage_age_us=0., particle_age_us=0., last_component_elapsed_time_us=0.,
        mass_amu=mass, charge_state=charge, mass_to_charge_Th=mass_to_charge_th(mass, charge),
        **{f"position_{axis}_mm": source[f"{axis}_mm"] for axis in "xyz"},
        **{f"velocity_{axis}_m_s": value for axis, value in zip("xyz", velocity, strict=True)},
        kinetic_energy_eV=kinetic_energy_ev(mass, *velocity), phase_reference_id=None, phase_rad=None)


@dataclass(frozen=True, init=False)
class ReleaseRealization:
    """Canonical birth rows and their complete, independently copied authoring facts."""

    _document: dict[str, Any]

    def __init__(self, request: Mapping[str, Any]):
        required = {"schema_version", "role", "release_spec", "clock", "instrument_origin_us",
                    "species_id", "source_component_id", "relative_weights"}
        if (not isinstance(request, Mapping) or not required <= request.keys()
                or set(request) - required - {"particle_ids"}
                or type(request["schema_version"]) is not int or request["schema_version"] != 1
                or request["role"] != "canonical_birth_source_request"):
            raise ContractError("release requires a version-1 canonical_birth_source_request")
        document = copy.deepcopy(dict(request))
        if not isinstance(document["clock"], dict) or set(document["clock"]) != {"clock_epoch_id", "authority_sha256"}:
            raise ContractError("release clock requires an explicit epoch and authority identity")
        clock = ClockIdentity(**document["clock"])
        weights = document["relative_weights"]
        if isinstance(weights, Mapping):
            converted = {}
            for key, value in weights.items():
                if isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key:
                    key = int(key)
                if type(key) is not int or key in converted:
                    raise ContractError("release weight keys must be unique canonical particle IDs")
                converted[key] = value
            weights = converted
        result = author_release(document["release_spec"], clock=clock,
            instrument_origin_us=document["instrument_origin_us"], species_id=document["species_id"],
            source_component_id=document["source_component_id"], relative_weights=weights,
            particle_ids=document.get("particle_ids"))
        object.__setattr__(self, "_document", result)

    @property
    def rows(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._document["rows"])

    @property
    def mother(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["mother"])

    @property
    def clock(self) -> ClockIdentity:
        return ClockIdentity(**self._document["clock"])

    def to_dict(self) -> dict[str, Any]:
        """Expand the exact sampler inputs, actual rows, ID mapping and clock mapping."""
        return copy.deepcopy(self._document)


def sample_release(spec: Mapping[str, Any]) -> ReleaseRealization:
    """Author canonical births without fields, materialized source files or native actions.

    The request supplies the existing release spec, clock, birth origin, species,
    component and explicit weight policy. Existing low-level sampler contracts
    remain available from msplatform.ion_release.release unchanged.
    """
    return ReleaseRealization(spec)


def load_recorded_release(record: Mapping[str, Any], *, clock: ClockIdentity, frame_id: str,
                          source_component_id: str, species_id: str,
                          relative_weights: Mapping[int | str, float] | None,
                          instrument_origin_us: float, expected_particle_ids: Sequence[int]) -> dict[str, Any]:
    """Read explicitly bound birth rows without sampling or changing particle identities."""
    if not isinstance(clock, ClockIdentity):
        raise ValueError("recorded birth requires an explicit clock identity")
    selected = validate_file_record(dict(record), "recorded birth source")
    if not Path(selected["path"]).is_absolute():
        raise ValueError("recorded birth source path must be absolute")
    ids = list(expected_particle_ids)
    if not ids or any(type(pid) is not int or pid <= 0 for pid in ids) or len(set(ids)) != len(ids):
        raise ValueError("expected recorded birth IDs must be unique positive integers")
    if any(not isinstance(value, str) or not value.strip() for value in (frame_id, source_component_id, species_id)):
        raise ValueError("recorded birth frame, source component and species must be explicit")
    weights = None
    if relative_weights is not None:
        if not isinstance(relative_weights, Mapping):
            raise ValueError("recorded birth weights must be an explicit mapping or None")
        weights = {}
        for key, value in relative_weights.items():
            if isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key:
                key = int(key)
            if type(key) is not int or key in weights or type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("recorded birth weights must have unique IDs and finite positive values")
            weights[key] = value
        if set(weights) != set(ids):
            raise ValueError("recorded birth weights must cover the complete expected mother")
    verify_record("recorded birth source", selected)
    with Path(selected["path"]).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
            raise ValueError("recorded birth CSV columns differ from canonical release")
        generated = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("recorded birth CSV row has missing or extra columns")
            try:
                pid, charge = int(row["particle_id"]), int(row["charge_state"])
                if str(pid) != row["particle_id"] or str(charge) != row["charge_state"]:
                    raise ValueError("noncanonical integer")
                source = {key: float(row[key]) for key in CANONICAL_COLUMNS if key not in {"particle_id", "charge_state"}}
                source.update(particle_id=pid, charge_state=charge)
            except (ValueError, TypeError) as exc:
                raise ValueError("recorded birth CSV has an invalid numeric value") from exc
            generated.append(source)
    verify_record("recorded birth source", selected)
    if [row["particle_id"] for row in generated] != ids:
        raise ValueError("recorded birth rows differ from the explicit ordered mother IDs")
    rows = validate_component_particle_state_rows([
        _canonical_birth_row(row, pid=row["particle_id"], weight=1. if weights is None else weights[row["particle_id"]],
            clock=clock, instrument_origin_us=instrument_origin_us, species_id=species_id,
            source_component_id=source_component_id, frame_id=frame_id) for row in generated]).rows
    return dict(schema_version=1, role="canonical_recorded_birth_realization", state_kind="source_birth",
        rows=rows, mother=dict(records={row["particle_id"]: dict(copy.deepcopy(row),
            source_component_entry_time_us=row["particle_birth_time_us"]) for row in rows},
            fates=[dict(particle_id=pid, status="not_propagated") for pid in ids]),
        clock=dict(clock_epoch_id=clock.clock_epoch_id, authority_sha256=clock.authority_sha256),
        recorded_source=dict(record=selected, frame_id=frame_id, source_component_id=source_component_id,
            species_id=species_id, relative_weights=None if weights is None else {str(k): v for k, v in weights.items()},
            instrument_origin_us=instrument_origin_us, expected_particle_ids=ids))


def author_release(spec: Mapping, *, clock: ClockIdentity, instrument_origin_us: float,
                   species_id: str, source_component_id: str,
                   relative_weights: Mapping[int, float] | None,
                   particle_ids: Sequence[int] | None = None) -> dict:
    """Generate one new birth cohort, returning CSV1 rows and copied source facts.

    Position is mm, velocity m/s and instrument times us. The explicit origin
    maps sampler birth seconds once. None weights declares unit weights; a map
    covers actual authored IDs exactly. Optional IDs assign identity only to
    this first realization, never to an existing handoff. The sampler's family
    prefix size is retained in spec, not invented as ungenerated mother rows.
    Snapshot samplers are not birth sources. No files, host or native programs
    are accessed; CSV1 validation reads only its installed schema resource.
    """
    if not isinstance(clock, ClockIdentity):
        raise ValueError("clock must be a ClockIdentity")
    if not isinstance(spec, Mapping):
        raise ValueError("release spec must be an object")
    if spec.get("role") == SNAPSHOT_ROLE:
        raise ValueError("snapshot source cannot be authored as source_birth")
    instrument_time_us(0., instrument_origin_us=instrument_origin_us, native_origin_us=0.)
    original_spec = copy.deepcopy(dict(spec))
    generated = generate_release_states(copy.deepcopy(original_spec))
    if not generated or len(generated) != original_spec["particle_count"]:
        raise ValueError("release generator must return the full nonempty requested cohort")
    ids = list(particle_ids) if particle_ids is not None else [row["particle_id"] for row in generated]
    if (len(ids) != len(generated) or any(type(pid) is not int or pid <= 0 for pid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("authored particle IDs must be positive unique integers covering all rows")
    if relative_weights is not None and (not isinstance(relative_weights, Mapping)
            or any(type(pid) is not int for pid in relative_weights) or set(relative_weights) != set(ids)):
        raise ValueError("relative_weights must cover actual authored IDs exactly or be None")
    rows, mapping = [], []
    for ordinal, (pid, source) in enumerate(zip(ids, generated, strict=True), start=1):
        weight = 1. if relative_weights is None else relative_weights[pid]
        if type(weight) not in (int, float) or not math.isfinite(weight) or weight <= 0:
            raise ValueError("relative weights must be finite and positive")
        rows.append(_canonical_birth_row(source, pid=pid, weight=weight, clock=clock,
            instrument_origin_us=instrument_origin_us, species_id=species_id,
            source_component_id=source_component_id, frame_id=original_spec["frame_id"]))
        mapping.append(dict(ordinal=ordinal, generator_particle_id=source["particle_id"], particle_id=pid))
    validated = validate_component_particle_state_rows(rows).rows
    return dict(schema_version=1, role="canonical_release_realization", state_kind="source_birth",
        rows=validated,
        mother=dict(records={row["particle_id"]: dict(copy.deepcopy(row),
                    source_component_entry_time_us=row["particle_birth_time_us"]) for row in validated},
                    fates=[dict(particle_id=pid, status="not_propagated") for pid in ids]),
        clock=dict(clock_epoch_id=clock.clock_epoch_id, authority_sha256=clock.authority_sha256),
        realization=dict(spec=original_spec, generator_rows=copy.deepcopy(generated), source_id_map=mapping,
                         time_mapping=dict(instrument_origin_us=instrument_origin_us, native_origin_us=0.,
                                           sampler_time_unit="s", instrument_time_unit="us")))
