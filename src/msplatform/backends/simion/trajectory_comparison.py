"""Read-only same-field comparison of published actual canonical event data."""
from __future__ import annotations

import copy
import json

from msplatform.analysis.propagation_comparison import compare_observed_events, _observed_event_rows, _require_lineage_identity
from msplatform.analysis.particle_census import subset_efficiency
from msplatform.assembly.handoff import HandoffMother
from msplatform.contracts.clock import require_same_clock
from msplatform.io.manifest_records import validate_file_record
from .trajectory_analysis import _load_published_trajectory, _classifications


def _field_reference(source, loaded):
    declared = json.loads(source.data_path("field_reference").read_text(encoding="utf-8-sig"))
    if declared != loaded["collection"]["field_reference"] or set(declared) != {"manifest", "product_id"}:
        raise ValueError("collection field reference differs from its verified published data")
    record = validate_file_record(declared["manifest"], "original field manifest")
    if not isinstance(declared["product_id"], str) or not declared["product_id"]:
        raise ValueError("original field product ID is missing")
    return declared, (record["bytes"], record["sha256"].upper(), declared["product_id"])


def _frame(loaded):
    frames = {row["frame_id"] for row in loaded["states"]}
    declared = loaded["provenance"]["target_frame_id"]
    if len(frames) > 1 or (frames and frames != {declared}) or (not frames and declared is not None):
        raise ValueError("trajectory frame differs from its actual source states and provenance")
    return next(iter(frames)) if frames else None


def compare_published_trajectories(left, right, *, selection, method) -> dict:
    """Compare actual t/xyz under one field, model, mother and original clock.

    No PA, tool, source checkout or raw-wire parser is invoked. Missing data
    remain visible; comparison completion never implies numerical equivalence.
    """
    if (not isinstance(selection, dict) or type(selection.get("schema_version")) is not int
            or selection["schema_version"] != 1 or set(selection) !=
            {"schema_version", "particle_ids", "observation", "unexecuted_fate_label_field"}):
        raise ValueError("current exact trajectory selection required")
    selector = selection["observation"]
    if (not isinstance(selector, dict) or set(selector) != {"kind", "event"}
            or selector["kind"] != "canonical_event" or not isinstance(selector["event"], str) or not selector["event"]):
        raise ValueError("comparison requires one explicit actual canonical event")
    field = selection["unexecuted_fate_label_field"]
    if field is not None and (not isinstance(field, str) or not field):
        raise ValueError("explicit unexecuted fate label field or null required")
    if (not isinstance(method, dict) or set(method) != {"schema_version", "kind"}
            or type(method["schema_version"]) is not int or method["schema_version"] != 1
            or method["kind"] != "event_time_position"):
        raise ValueError("unsupported published comparison method")
    loaded = [_load_published_trajectory(source) for source in (left, right)]
    if any(source.metadata.get("backend") != "simion" for source in (left, right)):
        raise ValueError("published comparison requires actual SIMION trajectory products")
    require_same_clock(loaded[0]["clock"], loaded[1]["clock"])
    if (any(loaded[0]["original"][key] != loaded[1]["original"][key]
            for key in ("mother_particle_ids", "mother_records", "mother_fates"))
            or loaded[0]["collection"]["model_identity_sha256"] != loaded[1]["collection"]["model_identity_sha256"]):
        raise ValueError("comparison requires the same complete original mother/lineage and model")
    fields = [_field_reference(source, facts) for source, facts in zip((left, right), loaded)]
    if fields[0][1] != fields[1][1]:
        raise ValueError("comparison requires the same original field manifest content and product")
    population = subset_efficiency(loaded[0]["mother"], selection["particle_ids"], loaded[0]["mother"],
                                   relative_weights=loaded[0]["weights"])
    mother = HandoffMother({row["particle_id"]: row for row in loaded[0]["records"]},
                           loaded[0]["original"]["mother_fates"])
    _require_lineage_identity(mother)
    labels, origins, unresolved = [], [], []
    frames = [_frame(facts) for facts in loaded]
    for facts in loaded:
        _observed_event_rows(facts["collection"]["canonical_events"], set(facts["mother"]), selector["event"])
        category, origin, missing = _classifications(facts["mother"], facts["original"]["mother_fates"],
                                                    facts["executed"], facts["collection"], field)
        labels.append(category); origins.append(origin); unresolved.append(missing)
        if any(type(row["particle_id"]) is not int or row["particle_id"] not in facts["executed"]
               for row in facts["collection"]["canonical_events"]):
            raise ValueError("canonical event escaped its actual execution cohort")
    evidence = dict(producers=dict(left=left.producer, right=right.producer),
                    trajectory_references=dict(left=left.reference, right=right.reference),
                    field_references=dict(left=fields[0][0], right=fields[1][0]),
                    model_identity_sha256=loaded[0]["collection"]["model_identity_sha256"],
                    selection=copy.deepcopy(selection), method=copy.deepcopy(method),
                    original_mother=copy.deepcopy(loaded[0]["original"]),
                    original_clock_records=dict(left=copy.deepcopy(loaded[0]["original"]["clock_records"]),
                                                right=copy.deepcopy(loaded[1]["original"]["clock_records"])),
                    classification_origins=dict(left=origins[0], right=origins[1]),
                    scientific_qualification="not_granted")
    if any(unresolved):
        return dict(status="insufficient_classification", selected_population=population,
                    unresolved_classification_particle_ids=dict(left=unresolved[0], right=unresolved[1]), **evidence)
    result = compare_observed_events(loaded[0]["collection"]["canonical_events"],
        loaded[1]["collection"]["canonical_events"], mother=mother,
        left_clock=loaded[0]["clock"], right_clock=loaded[1]["clock"],
        left_fates=labels[0], right_fates=labels[1], selected_particle_ids=selection["particle_ids"],
        event=selector["event"], left_frame_id=frames[0], right_frame_id=frames[1])
    result.update(evidence)
    return result
