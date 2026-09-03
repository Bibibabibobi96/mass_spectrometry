"""Bind a completed three-PA geometry review to one SIMION flight receipt.

This writer does not interpret trajectory metrics.  It only proves that the
raw log and event receipt consumed one frozen source and a byte-verified,
no-flight geometry-review assembly.  Numerical conclusions remain solely in
the event-analysis receipt and are deliberately not copied here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    SOURCE_COUNT_KEYS,
    load_particle_source,
)


PROJECT_ID = "parallel_mirror_dual_stripe_mr_tof"
GEOMETRY_REVIEW_STATUS = "prototype_geometry_review_only"
REQUIRED_WORKBENCH_ARTIFACTS = (
    "iob",
    "program",
    "operating_point",
    "voltage_map",
    "structure_report",
)
REQUIRED_GEOMETRY_REVIEW_FLAGS = {
    "STATUS": "pass",
    "PHYSICAL_MODEL": "false",
    "PARTICLE_FLY_EXECUTED": "false",
}


class FlightReceiptError(ValueError):
    """Raised when a purported flight evidence chain is incomplete or altered."""


def _record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FlightReceiptError(f"required flight artifact is missing: {path}")
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _verify_record(root: Path, record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise FlightReceiptError(f"{label} must be an artifact identity record")
    name = record.get("name")
    expected_bytes = record.get("bytes")
    expected_sha256 = record.get("sha256")
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
        or not isinstance(expected_sha256, str)
    ):
        raise FlightReceiptError(f"{label} is not a valid local artifact identity")
    path = root / name
    actual = _record(path)
    if actual["bytes"] != expected_bytes or actual["sha256"].lower() != expected_sha256.lower():
        raise FlightReceiptError(f"{label} bytes do not match the geometry-review manifest")
    return path


def _parse_required_flags(report_path: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in report_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            flags[key.strip()] = value.strip().lower()
    for key, expected in REQUIRED_GEOMETRY_REVIEW_FLAGS.items():
        if flags.get(key) != expected:
            raise FlightReceiptError(
                f"geometry-review structure report requires {key}={expected}"
            )
    return {key: flags[key] for key in REQUIRED_GEOMETRY_REVIEW_FLAGS}


def _load_geometry_review(manifest_path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FlightReceiptError("geometry-review manifest is unreadable JSON") from error
    if not isinstance(manifest, dict):
        raise FlightReceiptError("geometry-review manifest must be a JSON object")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("project_id") != PROJECT_ID
        or manifest.get("status") != GEOMETRY_REVIEW_STATUS
    ):
        raise FlightReceiptError("completed three-component geometry-review manifest is required")
    workbench = manifest.get("workbench")
    if not isinstance(workbench, dict) or workbench.get("instance_count") != 3:
        raise FlightReceiptError("geometry-review manifest must bind the three-component IOB")
    root = manifest_path.parent
    companions = {
        key: _record(_verify_record(root, workbench.get(key), f"workbench.{key}"))
        for key in REQUIRED_WORKBENCH_ARTIFACTS
    }
    report_path = root / str(companions["structure_report"]["name"])
    return {
        "manifest": _record(manifest_path),
        "workbench": companions,
        "structure_review_flags": _parse_required_flags(report_path),
    }


def _load_event_analysis(
    event_analysis_path: Path,
    raw_log_path: Path,
    source_manifest_path: Path,
    source: dict[str, object],
) -> dict[str, object]:
    try:
        event = json.loads(event_analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FlightReceiptError("event-analysis receipt is unreadable JSON") from error
    if not isinstance(event, dict) or event.get("schema_version") != 2:
        raise FlightReceiptError("current event-analysis receipt schema is required")
    if event.get("event_integrity_passed") is not True:
        raise FlightReceiptError("event-analysis receipt did not pass event integrity")
    raw_log = _record(raw_log_path)
    if str(event.get("log_sha256", "")).lower() != str(raw_log["sha256"]).lower():
        raise FlightReceiptError("event-analysis receipt does not bind the supplied raw SIMION log")
    provenance = source.get("provenance")
    if not isinstance(provenance, dict) or event.get("source") != provenance:
        raise FlightReceiptError("event-analysis receipt does not bind the selected frozen source")
    source_manifest = _record(source_manifest_path)
    if str(provenance.get("input_manifest_sha256", "")).lower() != str(source_manifest["sha256"]).lower():
        raise FlightReceiptError("selected source provenance does not bind its input manifest")
    return {
        "raw_simion_log": raw_log,
        "event_analysis": _record(event_analysis_path),
        "selected_source": provenance,
        "source_input_manifest": source_manifest,
    }


def _verify_consumed_fly2(
    source_input_manifest_path: Path, source: dict[str, object], consumed_fly2_path: Path
) -> dict[str, object]:
    """Prove that Workbench consumed the exact frozen source selected by key.

    The IOB convention renames its companion Fly2 to the IOB basename.  The
    source manifest deliberately preserves the materializer's descriptive
    filename, so a filename comparison is insufficient; both byte identities
    must be retained and equal.
    """
    provenance = source.get("provenance")
    if not isinstance(provenance, dict):
        raise FlightReceiptError("selected source has no frozen provenance")
    source_name = provenance.get("fly2_filename")
    if not isinstance(source_name, str) or Path(source_name).name != source_name:
        raise FlightReceiptError("selected source has an invalid Fly2 filename")
    selected_source = source_input_manifest_path.parent / source_name
    selected_record = _record(selected_source)
    consumed_record = _record(consumed_fly2_path)
    if selected_record["sha256"].lower() != consumed_record["sha256"].lower():
        raise FlightReceiptError("Workbench-consumed Fly2 differs from selected frozen source")
    return {"selected_source_fly2": selected_record, "workbench_consumed_fly2": consumed_record}


def build_flight_receipt(
    geometry_review_manifest_path: Path,
    source_input_manifest_path: Path,
    source_key: str,
    raw_log_path: Path,
    event_analysis_path: Path,
    consumed_fly2_path: Path,
) -> dict[str, object]:
    """Return a Candidate-only receipt after checking all frozen evidence links."""
    if source_key not in SOURCE_COUNT_KEYS:
        raise FlightReceiptError("an explicit current frozen-source key is required")
    geometry_review = _load_geometry_review(geometry_review_manifest_path)
    try:
        source = load_particle_source(source_input_manifest_path, source_key)
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise FlightReceiptError(f"selected frozen source is invalid: {error}") from error
    flight = _load_event_analysis(
        event_analysis_path, raw_log_path, source_input_manifest_path, source
    )
    consumed_fly2 = _verify_consumed_fly2(
        source_input_manifest_path, source, consumed_fly2_path
    )
    return {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "status": "candidate_prototype_flight_receipt",
        "formal_eligible": False,
        "geometry_review": geometry_review,
        "flight_inputs": {
            "source_key": source_key,
            "expected_particle_ids": list(source["expected_particle_ids"]),
            "target_oscillation_count": source["target_k"],
            "source_input_manifest": flight["source_input_manifest"],
            "selected_source": flight["selected_source"],
            **consumed_fly2,
        },
        "flight_evidence": {
            "raw_simion_log": flight["raw_simion_log"],
            "event_analysis": flight["event_analysis"],
            "event_integrity_passed": True,
        },
        "limitations": [
            "This receipt binds provenance and event integrity only; it contains no copied or inferred flight metrics.",
            "Candidate/prototype evidence is not Formal evidence.",
        ],
    }


def write_flight_receipt(output_path: Path, **arguments: object) -> dict[str, object]:
    """Write a deterministic UTF-8/LF Candidate-only flight receipt."""
    receipt = build_flight_receipt(**arguments)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind MR-TOF SIMION flight evidence without creating metrics.")
    parser.add_argument("--geometry-review-manifest", type=Path, required=True)
    parser.add_argument("--source-input-manifest", type=Path, required=True)
    parser.add_argument("--source-key", choices=tuple(SOURCE_COUNT_KEYS), required=True)
    parser.add_argument("--raw-log", type=Path, required=True)
    parser.add_argument("--event-analysis", type=Path, required=True)
    parser.add_argument("--consumed-fly2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = vars(parser.parse_args())
    output = arguments.pop("output")
    # argparse derives this key from the public CLI spelling, whereas the
    # callable API deliberately makes the Path nature explicit.  Normalize
    # here so CLI and library callers exercise the same implementation.
    arguments["geometry_review_manifest_path"] = arguments.pop(
        "geometry_review_manifest"
    )
    arguments["source_input_manifest_path"] = arguments.pop(
        "source_input_manifest"
    )
    arguments["raw_log_path"] = arguments.pop("raw_log")
    arguments["event_analysis_path"] = arguments.pop("event_analysis")
    arguments["consumed_fly2_path"] = arguments.pop("consumed_fly2")
    try:
        write_flight_receipt(output, **arguments)
    except FlightReceiptError as error:
        print(f"MRTOF_THREE_COMPONENT_FLIGHT_RECEIPT=FAIL ERROR={error}")
        return 1
    print("MRTOF_THREE_COMPONENT_FLIGHT_RECEIPT=PASS STATUS=candidate_prototype")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
