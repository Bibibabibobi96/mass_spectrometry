"""Versioned detector coverage independently of trajectory integrity."""
from __future__ import annotations


def detector_observation(status, cohort_particle_ids, *, missing_particle_ids=(), reason=None):
    """Build and validate one detector coverage record."""
    record = {"schema_version": 1, "status": status, "cohort_particle_ids": list(cohort_particle_ids),
              "missing_particle_ids": list(missing_particle_ids), "reason": reason}
    validate_detector_observation(record, record["cohort_particle_ids"])
    return record


def validate_detector_observation(record, cohort):
    """Require explicit complete, absent or incomplete collection for the whole cohort."""
    keys = {"schema_version", "status", "cohort_particle_ids", "missing_particle_ids", "reason"}
    if not isinstance(record, dict) or set(record) != keys or type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("invalid detector observation contract")
    ids, missing = record["cohort_particle_ids"], record["missing_particle_ids"]
    if (not isinstance(ids, list) or not isinstance(missing, list)
            or any(type(value) is not int or value <= 0 for value in ids + missing)
            or len(ids) != len(set(ids)) or len(missing) != len(set(missing))
            or set(ids) != set(cohort) or not set(missing) <= set(ids)):
        raise ValueError("detector observation cohort or missing identities differ")
    status, reason = record["status"], record["reason"]
    if status not in {"complete", "unavailable", "not_requested", "incomplete"}:
        raise ValueError("unsupported detector observation status")
    if (status == "complete" and (missing or reason is not None)
            or status == "incomplete" and (not missing or not isinstance(reason, str) or not reason)
            or status in {"unavailable", "not_requested"} and (missing or not isinstance(reason, str) or not reason)):
        raise ValueError("detector observation status and reason differ")
    return record


def merge_detector_observations(batches):
    """Combine explicit batch coverage; missing legacy contracts are unqualified."""
    ids, missing, statuses = [], [], []
    for initial, integrity in batches:
        cohort = [row["particle_id"] for row in initial]
        record = integrity.get("detector_observation")
        if record is None:
            status = "unavailable"
        else:
            validate_detector_observation(record, cohort)
            status = record["status"]
            missing.extend(record["missing_particle_ids"])
        ids.extend(cohort)
        statuses.append(status)
    if len(ids) != len(set(ids)):
        raise ValueError("detector batch cohorts overlap")
    if "incomplete" in statuses:
        status, reason = "incomplete", "detector_observation_incomplete"
    elif all(status == "complete" for status in statuses):
        status, reason = "complete", None
    elif all(status == "not_requested" for status in statuses):
        status, reason = "not_requested", "detector_not_requested"
    else:
        status, reason = "unavailable", "detector_observation_unavailable"
    return detector_observation(status, ids, missing_particle_ids=missing, reason=reason)
