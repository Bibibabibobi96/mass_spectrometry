"""Pure canonical transfer selection and spatial mapping, without propagation."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from msplatform.contracts.clock import ClockIdentity, require_same_clock
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.contracts.rigid_transform import PhaseSpaceState, RigidTransform


@dataclass(frozen=True)
class HandoffClock:
    """Source and receiving authority identities, verified by the outer owner."""

    source: ClockIdentity
    target: ClockIdentity


@dataclass(frozen=True)
class HandoffSelection:
    """Declared transfer IDs/order and kind; event localization stays with its producer."""

    state_kind: str
    particle_ids: tuple[int, ...]
    snapshot_time_us: float | None = None


@dataclass(frozen=True)
class HandoffMother:
    """Full original metadata and opaque fate records, independent of survivors.

    Records are keyed by particle ID and retain species_id, mass_amu,
    charge_state, particle_weight and particle_birth_time_us. Extra original
    source metadata is retained. Fate categories, including unknown, are never
    interpreted or inferred by this boundary.
    """

    records: Mapping[int, Mapping[str, Any]]
    fates: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class HandoffResult:
    """Copied transfer rows and complete mother metadata; zero rows is legitimate."""

    rows: tuple[dict[str, Any], ...]
    selected_particle_ids: tuple[int, ...]
    untransferred_particle_ids: tuple[int, ...]
    mother: HandoffMother
    clock: HandoffClock
    state_kind: str


def select_state_rows(rows: Sequence[Mapping[str, Any]], *, particle_ids: Sequence[int],
                      mother_particle_ids: Sequence[int]) -> list[dict[str, Any]]:
    """Select already-observed rows by explicit IDs/order, without future-outcome filtering.

    This helper validates identity only. Source adapters own event occurrence,
    native completion and their domain columns; canonical transfer validation
    is applied by prepare_handoff_states.
    """
    selected, mother = tuple(particle_ids), tuple(mother_particle_ids)
    for ids in (selected, mother):
        if any(type(pid) is not int or pid <= 0 for pid in ids) or len(set(ids)) != len(ids):
            raise ValueError("handoff particle IDs must be positive and unique")
    if not mother or not set(selected) <= set(mother):
        raise ValueError("handoff selection is outside the original mother cohort")
    by_id = {}
    for row in rows:
        pid = row["particle_id"]
        if type(pid) is not int or pid <= 0:
            raise ValueError("handoff state particle ID is invalid")
        if pid not in selected:
            continue
        if pid in by_id:
            raise ValueError("handoff repeats a selected particle state")
        by_id[pid] = row
    if set(by_id) != set(selected):
        raise ValueError("handoff lacks a selected particle state")
    return [copy.deepcopy(dict(by_id[pid])) for pid in selected]


def _validate_mother(mother: HandoffMother) -> None:
    if not mother.records:
        raise ValueError("handoff requires the full original mother cohort")
    for pid, record in mother.records.items():
        if type(pid) is not int or pid <= 0:
            raise ValueError("mother particle ID must be positive")
        for field in ("mass_amu", "particle_weight", "particle_birth_time_us"):
            value = record[field]
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("mother metadata must be finite")
        if record["mass_amu"] <= 0 or record["particle_weight"] <= 0:
            raise ValueError("mother mass and statistical weight must be positive")
        if type(record["charge_state"]) is not int or record["charge_state"] == 0:
            raise ValueError("mother charge state must be a nonzero integer")
        if not isinstance(record["species_id"], str) or not record["species_id"].strip():
            raise ValueError("mother species identity is missing")
    fate_ids = [row["particle_id"] for row in mother.fates]
    if (any(type(pid) is not int for pid in fate_ids) or len(set(fate_ids)) != len(fate_ids)
            or set(fate_ids) != set(mother.records)):
        raise ValueError("mother fate records must cover the full original cohort once")


def prepare_handoff_states(states: Sequence[Mapping[str, Any]], *, transform: RigidTransform,
                           clock: HandoffClock, selection: HandoffSelection,
                           mother: HandoffMother) -> HandoffResult:
    """Validate/select/map CSV1 states, preserving lineage, birth, elapsed and mother.

    No I/O other than read-only packaged schema validation, no flight, clipping,
    resampling, native restart or event localization occurs. Zero transfer is
    represented in memory, never by a fabricated nonempty CSV or particle.
    """
    require_same_clock(clock.source, clock.target)
    _validate_mother(mother)
    if selection.state_kind not in ("plane_crossing", "time_snapshot"):
        raise ValueError("unsupported handoff state kind")
    if selection.state_kind == "time_snapshot":
        if type(selection.snapshot_time_us) not in (float, int) or not math.isfinite(selection.snapshot_time_us):
            raise ValueError("snapshot requires a finite explicit instrument time")
    elif selection.snapshot_time_us is not None:
        raise ValueError("plane crossing must not declare a snapshot time")
    validated = validate_component_particle_state_rows(states).rows if states else []
    rows = select_state_rows(validated, particle_ids=selection.particle_ids,
                             mother_particle_ids=tuple(mother.records))
    for row in rows:
        original = mother.records[row["particle_id"]]
        for field in ("species_id", "mass_amu", "charge_state", "particle_weight", "particle_birth_time_us"):
            if row[field] != original[field]:
                raise ValueError("handoff reshapes original mother identity, birth, species or weight")
        if row["clock_epoch_id"] != clock.source.clock_epoch_id:
            raise ValueError("handoff row clock differs from its authority")
        if selection.state_kind == "time_snapshot" and row["instrument_time_us"] != selection.snapshot_time_us:
            raise ValueError("handoff snapshot row time differs from declared time")
        state = transform.transform_state(PhaseSpaceState(row["frame_id"],
            tuple(row[f"position_{a}_mm"] for a in "xyz"),
            tuple(row[f"velocity_{a}_m_s"] for a in "xyz"), row["instrument_time_us"]))
        row["frame_id"] = state.frame_id
        row.update({f"position_{a}_mm": value for a, value in zip("xyz", state.position_mm, strict=True)})
        row.update({f"velocity_{a}_m_s": value for a, value in zip("xyz", state.velocity_m_s, strict=True)})
        row["kinetic_energy_eV"] = kinetic_energy_ev(row["mass_amu"], *state.velocity_m_s)
    if rows:
        validate_component_particle_state_rows(rows)
    return HandoffResult(tuple(rows), tuple(selection.particle_ids),
        tuple(sorted(set(mother.records) - set(selection.particle_ids))),
        copy.deepcopy(mother), clock, selection.state_kind)
