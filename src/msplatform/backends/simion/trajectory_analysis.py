"""Read published SIMION trajectory data and project explicit neutral analysis."""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from typing import Any

from msplatform.analysis.trajectory import analyze_trajectory, _observation_rows
from msplatform.analysis.particle_census import subset_efficiency
from msplatform.assembly.handoff import HandoffMother, _validate_mother
from msplatform.contracts.clock import ClockIdentity, require_same_clock
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.results.artifacts import OpenedArtifact
from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.backends.simion.source import execution_particle_ids


def _read(source, key):
    return json.loads(source.data_path(key).read_text(encoding="utf-8-sig"))


def _clock(source, provenance, collection):
    contract_path = source.data_path("clock_authority")
    epoch_path = source.data_path("instrument_epoch")
    receipt = validate_clock_authority(contract_path, contract_path.parent)
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    if (contract_path.parent / contract["authority"]["path"]).resolve() != epoch_path.resolve():
        raise ValueError("published clock contract does not name the verified epoch member")
    for name in ("clock_authority", "instrument_epoch"):
        recorded, actual = provenance["clock_records"][name], source.data_records[name]
        if recorded["bytes"] != actual["bytes"] or recorded["sha256"].upper() != actual["sha256"].upper():
            raise ValueError("source original clock record differs from published data")
    identity = ClockIdentity(receipt["clock_epoch_id"], receipt["authority_sha256"])
    require_same_clock(identity, ClockIdentity(provenance["clock_epoch_id"], provenance["clock_authority_sha256"]))
    metadata = source.metadata["clock"]
    require_same_clock(identity, ClockIdentity(metadata["clock_epoch_id"], metadata["authority_sha256"]))
    if collection["clock_epoch_id"] != identity.clock_epoch_id:
        raise ValueError("collection clock epoch differs")
    return identity


def _classifications(mother, fates, executed, collection, field):
    if executed:
        if collection.get("native_complete") is not True:
            raise ValueError("nonempty trajectory lacks completed native collection")
        taxonomy = collection["census"]["terminal_taxonomy"]
        if taxonomy.get("classification_is_mutually_exclusive_and_exhaustive") is not True:
            raise ValueError("trajectory terminal taxonomy is not complete")
        terminals = taxonomy["particle_outcomes"]
        ids = [row["particle_id"] for row in terminals]
        if any(type(pid) is not int for pid in ids) or len(ids) != len(set(ids)) or set(ids) != set(executed):
            raise ValueError("terminal taxonomy differs from actual execution cohort")
        labels = {row["particle_id"]: row["category"] for row in terminals}
    else:
        if (collection.get("native_complete") is not None or collection.get("native_calls") != 0
                or collection.get("execution_status") != "not_requested_zero_handoff"):
            raise ValueError("zero handoff must retain its no-native status")
        labels = {}
    if any(not isinstance(label, str) or not label for label in labels.values()):
        raise ValueError("actual terminal category must be an explicit string")
    origins = {pid: "collection.census.terminal_taxonomy.particle_outcomes.category" for pid in labels}
    unresolved = []
    by_id = {row["particle_id"]: row for row in fates}
    for pid in mother:
        if pid in labels:
            continue
        label = by_id[pid].get(field) if field is not None else None
        if not isinstance(label, str) or not label:
            unresolved.append(pid)
            continue
        labels[pid] = label
        origins[pid] = "original_mother.mother_fates." + field
    return labels, origins, unresolved


def _observations(collection, selector):
    if selector is None:
        return [], None, None
    if not isinstance(selector, dict):
        raise ValueError("observation selection must be an explicit object or null")
    if selector.get("kind") == "canonical_event" and set(selector) == {"kind", "event"}:
        if not isinstance(selector["event"], str) or not selector["event"]:
            raise ValueError("canonical event must be explicit")
        rows = [dict(particle_id=row["particle_id"], instrument_time_us=row["instrument_time_us"])
                for row in collection["canonical_events"] if row["event"] == selector["event"]]
        return rows, None, dict(kind="canonical_event", event=selector["event"])
    if selector.get("kind") == "plane_observation" and set(selector) == {"kind", "observation_id", "direction", "occurrence"}:
        plane = collection.get("plane_observations")
        if plane is None:
            return [], {key: selector[key] for key in selector if key != "kind"}, None
        neutral = [{key: row[key] for key in ("particle_id", "instrument_time_us", "observation_id", "direction", "occurrence")}
                   for row in plane["rows"]]
        return neutral, {key: selector[key] for key in selector if key != "kind"}, copy.deepcopy(plane)
    raise ValueError("unknown or ambiguous observation selection")


def _load_published_trajectory(source: OpenedArtifact) -> dict:
    """Reuse the unique data/source/mother/clock validation for read-only consumers."""
    if not isinstance(source, OpenedArtifact) or source.kind != "trajectory_result":
        raise ValueError("analysis requires an opened trajectory_result")
    collection, provenance = _read(source, "collection"), _read(source, "source_provenance")
    states = _read(source, "canonical_source_states")
    bound = collection["source_provenance_record"]
    actual = source.data_records["source_provenance"]
    if bound["bytes"] != actual["bytes"] or bound["sha256"].upper() != actual["sha256"].upper():
        raise ValueError("collection source provenance content identity differs")
    if collection["model_identity_sha256"] != source.metadata["model_identity_sha256"]:
        raise ValueError("collection model identity differs from published metadata")
    if (type(collection.get("schema_version")) is not int or collection["schema_version"] != 1
            or collection.get("role") != "simion_tracking_collection" or provenance.get("schema_version") != 2):
        raise ValueError("current published tracking/source versions required")
    if states:
        validate_component_particle_state_rows(states)
    executed = execution_particle_ids(provenance, len(states))
    if [row["particle_id"] for row in states] != executed:
        raise ValueError("published actual source rows differ from declared execution IDs")
    original = collection["original_mother"]
    for key in ("mother_particle_ids", "mother_records", "mother_fates", "clock_authority_sha256", "clock_records"):
        if original[key] != provenance[key]:
            raise ValueError("collection original mother/clock differs from source provenance")
    records = original["mother_records"]
    mother = original["mother_particle_ids"]
    _validate_mother(HandoffMother({row["particle_id"]: row for row in records}, original["mother_fates"]))
    weights = {row["particle_id"]: row["particle_weight"] for row in records}
    clock = _clock(source, provenance, collection)
    return dict(collection=collection, provenance=provenance, states=states, executed=executed,
                original=original, records=records, mother=mother, weights=weights, clock=clock)


def analyze_published_trajectory(source: OpenedArtifact, *, selection, method) -> dict:
    """Analyze verified data only; never resolve PA, launch tools or infer losses."""
    if not isinstance(source, OpenedArtifact) or source.kind != "trajectory_result":
        raise ValueError("analysis requires an opened trajectory_result")
    if (not isinstance(selection, dict) or type(selection.get("schema_version")) is not int
            or selection["schema_version"] != 1 or set(selection) !=
            {"schema_version", "particle_ids", "observation", "unexecuted_fate_label_field"}):
        raise ValueError("unknown trajectory selection version or fields")
    field = selection["unexecuted_fate_label_field"]
    if field is not None and (not isinstance(field, str) or not field):
        raise ValueError("unexecuted fate label field must be explicit nonempty string or null")
    if not isinstance(method, dict) or type(method.get("schema_version")) is not int or method["schema_version"] != 1:
        raise ValueError("unknown trajectory method version")
    kind = method.get("kind")
    keys = {"schema_version", "kind"} if kind == "census" else {"schema_version", "kind", "time_reference", "settings"}
    if kind not in {"census", "time_peak"} or set(method) != keys:
        raise ValueError("unknown trajectory method or fields")
    loaded = _load_published_trajectory(source)
    collection = loaded["collection"]
    executed, original = loaded["executed"], loaded["original"]
    mother, weights, clock = loaded["mother"], loaded["weights"], loaded["clock"]
    selected = subset_efficiency(mother, selection["particle_ids"], mother, relative_weights=weights)
    labels, origins, unresolved = _classifications(mother, original["mother_fates"], executed, collection, field)
    observations, observation_selection, observation_evidence = _observations(collection, selection["observation"])
    _observation_rows(observations, set(mother), observation_selection)
    reference, settings = None, None
    if kind == "time_peak":
        if selection["observation"] is None:
            raise ValueError("time peak requires an explicit observed event")
        ref = method["time_reference"]
        if not isinstance(ref, dict) or set(ref) != {"clock_epoch_id", "authority_sha256", "instrument_time_us"}:
            raise ValueError("time peak requires a common original instrument reference")
        require_same_clock(clock, ClockIdentity(ref["clock_epoch_id"], ref["authority_sha256"]))
        reference = ref["instrument_time_us"]
        if type(reference) not in (int, float) or not math.isfinite(reference):
            raise ValueError("common instrument reference must be finite")
        if method["settings"] is not None:
            from msplatform.analysis.peak_metrics import AnalysisSettings
            settings = AnalysisSettings(**method["settings"])
    evidence = dict(original_mother=copy.deepcopy(original), classification_origins=origins,
                    selection_evidence=observation_evidence, selection=copy.deepcopy(selection),
                    method=copy.deepcopy(method), producer=source.producer, trajectory_reference=source.reference,
                    scientific_qualification="not_granted")
    if unresolved:
        return dict(status="insufficient_classification", unresolved_classification_particle_ids=unresolved,
                    selected_population=selected,
                    peak_metrics=None, **evidence)
    result = analyze_trajectory(mother_particle_ids=mother,
        relative_weights=weights,
        classifications=[(pid, labels[pid]) for pid in mother], categories=list(dict.fromkeys(labels[pid] for pid in mother)),
        observations=observations, selected_particle_ids=selection["particle_ids"], clock=clock, method=kind,
        time_reference_instrument_us=reference, observation_selection=observation_selection, settings=settings)
    result.update(evidence)
    return result


def analyze(result: OpenedArtifact | Mapping[str, Any], *,
            selection: Mapping[str, Any], method: Mapping[str, Any]) -> dict[str, Any]:
    """Open and analyze a published SIMION trajectory without native actions.

    Selection and method are explicit version-1 contracts. Missing observations
    or unclassified inherited fates remain unavailable; no tool is started to
    supply them. The common time reference is not a particle birth or age.
    """
    from msplatform.contracts.machine_contracts import ContractError
    from msplatform.results.artifacts import open_artifact

    source = result if isinstance(result, OpenedArtifact) else open_artifact(result, expected_kind="trajectory_result")
    if source.kind != "trajectory_result" or source.metadata.get("backend") != "simion":
        raise ContractError("analysis requires a trajectory result from the supported SIMION data adapter")
    if not isinstance(selection, Mapping) or not isinstance(method, Mapping):
        raise ContractError("analysis requires explicit selection and method contracts")
    return analyze_published_trajectory(source, selection=copy.deepcopy(dict(selection)),
                                        method=copy.deepcopy(dict(method)))
