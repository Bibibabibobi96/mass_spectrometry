"""Analyze a solver-native OA-TOF COMSOL detector-event handoff in Python."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis import (
    analyze_single,
)


ROLE = "oatof_comsol_detector_events_analysis_request"


def _load_request(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "role",
        "solver",
        "label",
        "nominal_mass_Da",
        "raw_events_csv",
        "analysis_output_dir",
        "event_extraction",
        "aggregate_metrics_owner",
    }
    if set(document) != required:
        raise ValueError("COMSOL analysis request has unexpected or missing fields")
    if document["schema_version"] != 1 or document["role"] != ROLE:
        raise ValueError("unsupported COMSOL analysis request identity")
    if document["solver"] != "COMSOL":
        raise ValueError("COMSOL analysis request declares a different solver")
    if document["aggregate_metrics_owner"] != "python_reference_analysis":
        raise ValueError("COMSOL analysis request does not delegate metrics to Python")
    if not isinstance(document["nominal_mass_Da"], (int, float)) or document["nominal_mass_Da"] <= 0:
        raise ValueError("nominal_mass_Da must be positive")
    return document


def analyze_request(request_path: Path) -> dict[str, Any]:
    """Run the canonical Python analysis for one immutable COMSOL event export."""

    request_path = request_path.resolve(strict=True)
    request = _load_request(request_path)
    events = Path(str(request["raw_events_csv"])).resolve(strict=True)
    output = Path(str(request["analysis_output_dir"])).resolve()
    result = analyze_single(
        events,
        output,
        float(request["nominal_mass_Da"]),
        label=str(request["label"]),
    )
    receipt = {
        "schema_version": 1,
        "role": "oatof_comsol_detector_events_analysis_receipt",
        "status": result["status"],
        "request": {"path": str(request_path), "sha256": file_sha256(request_path)},
        "raw_events": {"path": str(events), "sha256": file_sha256(events)},
        "metrics": {"path": str(output / "metrics.json"), "sha256": file_sha256(output / "metrics.json")},
        "aggregate_metrics_owner": "python_reference_analysis",
    }
    (output / "analysis_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        receipt = analyze_request(arguments.request)
    except Exception as error:
        print(f"STATUS=FAIL\nERROR={type(error).__name__}: {error}")
        return 1
    print(f"STATUS={receipt['status']} RECEIPT={Path(receipt['metrics']['path']).parent / 'analysis_receipt.json'}")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
