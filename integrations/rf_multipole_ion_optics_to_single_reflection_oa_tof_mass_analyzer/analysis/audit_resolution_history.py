"""Audit historical oaTOF resolution evidence and emit three claim-scoped boards.

The inventory is explicit: every row points to one immutable JSON evidence file
and supplies the source, field, architecture, geometry, and grid identities that
the historical run actually recorded.  This module never searches artifacts or
infers a missing identity from a filename.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError


REQUEST_ROLE = "rf_oatof_resolution_history_audit_request"
RESULT_ROLE = "rf_oatof_resolution_history_audit"
PULSE_EFFECTIVE_BASIS = "detector_time_minus_pulse_effective_time"
DIRECT_FWHM_METHOD = "canonical_direct_kde_fwhm"
IDENTITY_AXES = ("source", "field", "architecture", "geometry", "grid")
LEADERBOARD_IDS = (
    "real_beam_pulse_effective",
    "finite_ideal_source",
    "numerical_oracle",
)
SOURCE_CLASS_BY_BOARD = {
    "real_beam_pulse_effective": {"real_multipole_beam"},
    "finite_ideal_source": {"finite_ideal_source"},
    "numerical_oracle": {"finite_ideal_source", "axial_ideal_source"},
}
METRIC_ROLES_BY_BOARD = {
    "real_beam_pulse_effective": {"pulse_effective_peak"},
    "finite_ideal_source": {"pulse_effective_peak"},
    "numerical_oracle": {
        "pulse_effective_peak",
        "analytic_pulse_effective_peak",
    },
}


def _require_exact_keys(
    value: Mapping[str, Any], required: set[str], optional: set[str], label: str
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing or unknown:
        raise ContractError(
            f"{label} keys differ: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value)


def _validate_identity(value: object, label: str) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} identity must be an object")
    _require_exact_keys(value, {"id", "sha256"}, set(), f"{label} identity")
    identity_id = value["id"]
    identity_sha = value["sha256"]
    if identity_id is not None and (
        not isinstance(identity_id, str) or not identity_id.strip()
    ):
        raise ContractError(f"{label} identity id must be null or a non-empty string")
    if identity_sha is not None and not _is_sha256(identity_sha):
        raise ContractError(f"{label} identity sha256 is invalid")
    return {
        "id": identity_id.strip() if isinstance(identity_id, str) else None,
        "sha256": identity_sha.upper() if isinstance(identity_sha, str) else None,
    }


def _validate_claim(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} claim must be an object")
    _require_exact_keys(
        value,
        {
            "resolution_time_basis",
            "metric_role",
            "fwhm_method",
            "population_basis",
            "nominal_mass_da",
            "charge_state",
            "comparison_contract_id",
            "allowed_variation_axes",
        },
        set(),
        f"{label} claim",
    )
    if not isinstance(value["resolution_time_basis"], str):
        raise ContractError(f"{label} resolution_time_basis must be a string")
    for field in ("metric_role", "fwhm_method", "population_basis"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ContractError(f"{label} {field} must be a non-empty string")
    mass = value["nominal_mass_da"]
    charge = value["charge_state"]
    if not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0:
        raise ContractError(f"{label} nominal_mass_da must be finite and positive")
    if not isinstance(charge, int) or charge == 0:
        raise ContractError(f"{label} charge_state must be a nonzero integer")
    contract_id = value["comparison_contract_id"]
    if contract_id is not None and (
        not isinstance(contract_id, str) or not contract_id.strip()
    ):
        raise ContractError(
            f"{label} comparison_contract_id must be null or a non-empty string"
        )
    axes = value["allowed_variation_axes"]
    if not isinstance(axes, list) or any(axis not in IDENTITY_AXES for axis in axes):
        raise ContractError(f"{label} allowed_variation_axes are invalid")
    if len(axes) != len(set(axes)):
        raise ContractError(f"{label} allowed_variation_axes contain duplicates")
    return {
        **value,
        "nominal_mass_da": float(mass),
        "comparison_contract_id": contract_id.strip() if contract_id else None,
        "allowed_variation_axes": sorted(axes),
    }


def validate_inventory(value: object) -> dict[str, Any]:
    """Validate and normalize one explicit history-audit inventory."""
    if not isinstance(value, Mapping):
        raise ContractError("history audit inventory must be an object")
    _require_exact_keys(
        value,
        {"schema_version", "role", "records"},
        set(),
        "history audit inventory",
    )
    if value["schema_version"] != 1 or value["role"] != REQUEST_ROLE:
        raise ContractError("history audit inventory identity differs")
    if not isinstance(value["records"], list) or not value["records"]:
        raise ContractError("history audit inventory requires at least one record")
    records = [_validate_record(record, index) for index, record in enumerate(value["records"])]
    record_ids = [record["record_id"] for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ContractError("history audit record_id values must be unique")
    return {"schema_version": 1, "role": REQUEST_ROLE, "records": records}


def _validate_record(value: object, index: int) -> dict[str, Any]:
    label = f"records[{index}]"
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    _require_exact_keys(
        value,
        {
            "record_id",
            "label",
            "run_id",
            "leaderboard",
            "source_class",
            "evidence_path",
            "evidence_sha256",
            "metric_json_pointer",
            "identities",
            "claim",
        },
        set(),
        label,
    )
    for field in ("record_id", "label", "run_id", "evidence_path"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ContractError(f"{label} {field} must be a non-empty string")
    board = value["leaderboard"]
    if board not in LEADERBOARD_IDS:
        raise ContractError(f"{label} leaderboard is unknown")
    if value["source_class"] not in SOURCE_CLASS_BY_BOARD[board]:
        raise ContractError(f"{label} source_class is incompatible with leaderboard")
    if not _is_sha256(value["evidence_sha256"]):
        raise ContractError(f"{label} evidence_sha256 is invalid")
    pointer = value["metric_json_pointer"]
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ContractError(f"{label} metric_json_pointer must be empty or start with /")
    identities = value["identities"]
    if not isinstance(identities, Mapping):
        raise ContractError(f"{label} identities must be an object")
    _require_exact_keys(identities, set(IDENTITY_AXES), set(), f"{label} identities")
    normalized_identities = {
        axis: _validate_identity(identities[axis], f"{label} {axis}")
        for axis in IDENTITY_AXES
    }
    return {
        **value,
        "record_id": value["record_id"].strip(),
        "label": value["label"].strip(),
        "run_id": value["run_id"].strip(),
        "evidence_path": value["evidence_path"].strip(),
        "evidence_sha256": value["evidence_sha256"].upper(),
        "identities": normalized_identities,
        "claim": _validate_claim(value["claim"], label),
    }


def _json_pointer(value: object, pointer: str) -> object:
    current = value
    if not pointer:
        return current
    for encoded in pointer.split("/")[1:]:
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ContractError(f"metric_json_pointer does not resolve: {pointer}")
    return current


def _contains_true_flag(value: object, key: str) -> bool:
    if isinstance(value, Mapping):
        if value.get(key) is True:
            return True
        return any(_contains_true_flag(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_true_flag(child, key) for child in value)
    return False


def _positive_metric(value: Mapping[str, Any], field: str) -> float | None:
    candidate = value.get(field)
    if not isinstance(candidate, (int, float)):
        return None
    number = float(candidate)
    return number if math.isfinite(number) and number > 0 else None


def _audit_record(record: Mapping[str, Any], inventory_dir: Path) -> dict[str, Any]:
    evidence_path = Path(record["evidence_path"])
    if not evidence_path.is_absolute():
        evidence_path = (inventory_dir / evidence_path).resolve()
    if not evidence_path.is_file():
        raise ContractError(f"evidence file is missing: {evidence_path}")
    observed_sha = file_sha256(evidence_path)
    if observed_sha != record["evidence_sha256"]:
        raise ContractError(f"evidence SHA differs for record {record['record_id']}")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"evidence JSON cannot be read: {evidence_path}") from error
    metric = _json_pointer(evidence, record["metric_json_pointer"])
    if not isinstance(metric, Mapping):
        raise ContractError(f"metric object is not a mapping: {record['record_id']}")
    reasons = _claim_exclusion_reasons(record, evidence, metric)
    identity_reasons = [
        f"missing_{axis}_identity"
        for axis, identity in record["identities"].items()
        if identity["id"] is None or identity["sha256"] is None
    ]
    resolution = _positive_metric(metric, "mass_resolution")
    direct_fwhm = _positive_metric(metric, "direct_fwhm_tof_ns")
    particles = metric.get("particles")
    return {
        "record_id": record["record_id"],
        "label": record["label"],
        "run_id": record["run_id"],
        "leaderboard": record["leaderboard"],
        "source_class": record["source_class"],
        "evidence": {
            "path": str(evidence_path),
            "sha256": observed_sha,
            "role": evidence.get("role") if isinstance(evidence, Mapping) else None,
            "status": evidence.get("status") if isinstance(evidence, Mapping) else None,
            "metric_json_pointer": record["metric_json_pointer"],
        },
        "claim": record["claim"],
        "identities": record["identities"],
        "metrics": {
            "mass_resolution": resolution,
            "direct_fwhm_tof_ns": direct_fwhm,
            "mean_tof_us": _positive_metric(metric, "mean_tof_us"),
            "particles": particles if isinstance(particles, int) and particles > 0 else None,
            "significant_kde_modes": metric.get("significant_kde_modes"),
        },
        "leaderboard_eligible": not reasons,
        "claim_exclusion_reasons": reasons,
        "strict_comparability_ready": not identity_reasons
        and record["claim"]["comparison_contract_id"] is not None,
        "comparability_limitations": identity_reasons
        + (
            []
            if record["claim"]["comparison_contract_id"] is not None
            else ["comparison_contract_not_recorded"]
        ),
    }


def _claim_exclusion_reasons(
    record: Mapping[str, Any], evidence: object, metric: Mapping[str, Any]
) -> list[str]:
    claim = record["claim"]
    reasons: list[str] = []
    basis = claim["resolution_time_basis"]
    if "absolute_birth_time" in basis.lower():
        reasons.append("absolute_birth_time_resolution_claim_excluded")
    elif basis != PULSE_EFFECTIVE_BASIS:
        reasons.append("resolution_time_basis_not_pulse_effective")
    if (
        "instrument_clock" in claim["metric_role"].lower()
        or "instrument_clock" in record["metric_json_pointer"].lower()
        or "absolute_birth" in record["metric_json_pointer"].lower()
    ):
        reasons.append("absolute_instrument_clock_metric_excluded")
    if _contains_true_flag(evidence, "instrument_clock_peak_is_resolution_claim"):
        reasons.append("instrument_clock_resolution_claim_forbidden")
    if claim["metric_role"] not in METRIC_ROLES_BY_BOARD[record["leaderboard"]]:
        reasons.append("metric_role_incompatible_with_leaderboard")
    if claim["fwhm_method"] != DIRECT_FWHM_METHOD:
        reasons.append("noncanonical_or_proxy_fwhm_excluded")
    status = evidence.get("status") if isinstance(evidence, Mapping) else None
    if status not in {"success", "pass"}:
        reasons.append("evidence_status_not_success")
    if _positive_metric(metric, "mass_resolution") is None:
        reasons.append("valid_mass_resolution_missing")
    if _positive_metric(metric, "direct_fwhm_tof_ns") is None:
        reasons.append("valid_direct_fwhm_tof_missing")
    modes = metric.get("significant_kde_modes")
    if not isinstance(modes, int):
        reasons.append("peak_modality_not_recorded")
    elif modes != 1:
        reasons.append("peak_not_unimodal")
    return list(dict.fromkeys(reasons))


def _compare_records(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    left_claim = left["claim"]
    right_claim = right["claim"]
    if not left["leaderboard_eligible"] or not right["leaderboard_eligible"]:
        reasons.append("one_or_both_resolution_claims_excluded")
    if left["leaderboard"] != right["leaderboard"]:
        reasons.append("leaderboard_scope_differs")
    contract = left_claim["comparison_contract_id"]
    if contract is None or right_claim["comparison_contract_id"] is None:
        reasons.append("comparison_contract_not_recorded")
    elif contract != right_claim["comparison_contract_id"]:
        reasons.append("comparison_contract_differs")
    if left_claim["allowed_variation_axes"] != right_claim["allowed_variation_axes"]:
        reasons.append("allowed_variation_axes_differ")
    for field in (
        "resolution_time_basis",
        "metric_role",
        "fwhm_method",
        "population_basis",
        "nominal_mass_da",
        "charge_state",
    ):
        if left_claim[field] != right_claim[field]:
            reasons.append(f"{field}_differs")
    allowed = set(left_claim["allowed_variation_axes"])
    differing_axes: list[str] = []
    for axis in IDENTITY_AXES:
        left_identity = left["identities"][axis]
        right_identity = right["identities"][axis]
        if None in left_identity.values() or None in right_identity.values():
            reasons.append(f"{axis}_identity_incomplete")
        elif left_identity != right_identity:
            differing_axes.append(axis)
            if axis not in allowed:
                reasons.append(f"uncontrolled_{axis}_identity_difference")
    return {
        "leaderboard": left["leaderboard"] if left["leaderboard"] == right["leaderboard"] else None,
        "left_record_id": left["record_id"],
        "right_record_id": right["record_id"],
        "strictly_comparable": not reasons,
        "controlled_differing_axes": sorted(axis for axis in differing_axes if axis in allowed),
        "incomparability_reasons": list(dict.fromkeys(reasons)),
    }


def audit_history(inventory: object, *, inventory_dir: Path) -> dict[str, Any]:
    """Audit immutable evidence and return claim eligibility plus three boards."""
    normalized = validate_inventory(inventory)
    records = [_audit_record(record, inventory_dir.resolve()) for record in normalized["records"]]
    leaderboards: dict[str, list[dict[str, Any]]] = {}
    for board_id in LEADERBOARD_IDS:
        board_records = sorted(
            (
                record
                for record in records
                if record["leaderboard"] == board_id and record["leaderboard_eligible"]
            ),
            key=lambda record: (-record["metrics"]["mass_resolution"], record["record_id"]),
        )
        leaderboards[board_id] = [
            {"rank_by_reported_mass_resolution": rank, **record}
            for rank, record in enumerate(board_records, start=1)
        ]
    eligible = [record for record in records if record["leaderboard_eligible"]]
    pairs = [
        _compare_records(left, right)
        for index, left in enumerate(records)
        for right in records[index + 1 :]
    ]
    return {
        "schema_version": 1,
        "role": RESULT_ROLE,
        "status": "success",
        "ranking_scope": (
            "reported maxima within each claim class; rank is not a causal or "
            "strict comparability claim"
        ),
        "resolution_time_basis_required": PULSE_EFFECTIVE_BASIS,
        "absolute_birth_time_resolution_claims_allowed": False,
        "record_count": len(records),
        "eligible_record_count": len(eligible),
        "excluded_record_count": len(records) - len(eligible),
        "excluded_absolute_birth_time_claim_count": sum(
            "absolute_birth_time_resolution_claim_excluded"
            in record["claim_exclusion_reasons"]
            for record in records
        ),
        "records": records,
        "leaderboards": leaderboards,
        "pairwise_comparability": pairs,
    }


def render_markdown(result: Mapping[str, Any]) -> str:
    """Render the three reported-maxima boards and exclusions for human review."""
    titles = {
        "real_beam_pulse_effective": "Real multipole beam — legal pulse-effective resolution",
        "finite_ideal_source": "Finite ideal source",
        "numerical_oracle": "Numerical / analytic oracle",
    }
    lines = [
        "# oaTOF historical resolution evidence audit",
        "",
        "> Ranks are reported maxima inside separate claim classes. They are not causal comparisons unless the pairwise audit explicitly marks two rows strictly comparable. Absolute-birth-time and absolute-instrument-clock resolution claims are excluded.",
        "",
    ]
    for board_id in LEADERBOARD_IDS:
        lines.extend(
            [
                f"## {titles[board_id]}",
                "",
                "| Rank | Record | R | Direct FWHM (ns) | Source | Field | Architecture | Geometry | Grid |",
                "|---:|---|---:|---:|---|---|---|---|---|",
            ]
        )
        rows = result["leaderboards"][board_id]
        if not rows:
            lines.append("| — | No eligible evidence | — | — | — | — | — | — | — |")
        for row in rows:
            identities = row["identities"]
            lines.append(
                "| {rank} | `{record}` | {resolution:.6g} | {fwhm:.6g} | {source} | {field} | {architecture} | {geometry} | {grid} |".format(
                    rank=row["rank_by_reported_mass_resolution"],
                    record=row["record_id"],
                    resolution=row["metrics"]["mass_resolution"],
                    fwhm=row["metrics"]["direct_fwhm_tof_ns"],
                    **{
                        axis: identities[axis]["id"] or "UNKNOWN"
                        for axis in IDENTITY_AXES
                    },
                )
            )
        lines.append("")
    lines.extend(["## Excluded claims", ""])
    excluded = [record for record in result["records"] if not record["leaderboard_eligible"]]
    if not excluded:
        lines.append("None.")
    else:
        for record in excluded:
            lines.append(
                f"- `{record['record_id']}`: {', '.join(record['claim_exclusion_reasons'])}"
            )
    lines.append("")
    return "\n".join(lines)


def _write_text_atomic(path: Path, text: str) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(text, encoding="utf-8", newline="\n")
    os.replace(pending, path)


def write_audit_outputs(
    inventory_path: Path, output_path: Path, report_path: Path
) -> dict[str, Any]:
    """Load an inventory, audit its evidence, and atomically publish JSON/Markdown."""
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"history audit inventory cannot be read: {inventory_path}") from error
    result = audit_history(inventory, inventory_dir=inventory_path.resolve().parent)
    _write_text_atomic(output_path, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    _write_text_atomic(report_path, render_markdown(result))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    result = write_audit_outputs(args.inventory, args.output, args.report)
    print(
        "RF_OATOF_RESOLUTION_HISTORY_AUDIT=PASS "
        f"ELIGIBLE={result['eligible_record_count']} "
        f"EXCLUDED={result['excluded_record_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
