"""Author a new canonical birth realization through the existing release sampler."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence

from msplatform.contracts.clock import ClockIdentity, instrument_time_us, seconds_to_microseconds
from msplatform.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.ion_release.continuous_axial_volume import ROLE as SNAPSHOT_ROLE
from msplatform.ion_release.release import generate_release_states


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
        birth = instrument_time_us(seconds_to_microseconds(source["birth_time_s"]),
                                   instrument_origin_us=instrument_origin_us, native_origin_us=0.)
        mass, charge = source["mass_amu"], source["charge_state"]
        velocity = [source[f"v{axis}_m_s"] for axis in "xyz"]
        rows.append(dict(particle_id=pid, parent_particle_id=None, generation=0,
            species_id=species_id, particle_weight=weight, source_component_id=source_component_id,
            target_component_id=source_component_id, state_event="source_birth",
            frame_id=original_spec["frame_id"], clock_epoch_id=clock.clock_epoch_id,
            instrument_time_us=birth, lineage_birth_time_us=birth, particle_birth_time_us=birth,
            lineage_age_us=0., particle_age_us=0., last_component_elapsed_time_us=0.,
            mass_amu=mass, charge_state=charge, mass_to_charge_Th=mass_to_charge_th(mass, charge),
            **{f"position_{axis}_mm": source[f"{axis}_mm"] for axis in "xyz"},
            **{f"velocity_{axis}_m_s": value for axis, value in zip("xyz", velocity, strict=True)},
            kinetic_energy_eV=kinetic_energy_ev(mass, *velocity), phase_reference_id=None, phase_rad=None))
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
