"""Validate the oa-TOF COMSOL detector-analysis request contract."""
import csv
from pathlib import Path
from typing import Any
import json

ROLE = "oatof_comsol_detector_events_analysis_request"


def load_request(path: Path) -> dict[str, Any]:
    """Read and fail closed on an invalid detector-analysis request."""
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "role", "solver", "label", "nominal_mass_Da", "raw_events_csv",
                "analysis_output_dir", "event_extraction", "aggregate_metrics_owner"}
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


def validate_detector_cohort(events: Path, request: Path) -> None:
    """Accept a complete raw observation cohort without granting detector acceptance."""
    document = load_request(request)
    if Path(document["raw_events_csv"]).resolve() != events.resolve():
        raise ValueError("failed cold export request does not bind its own CSV")
    required = {"Ion", "TofUs", "XMm", "YMm", "Hit", "Status", "Event",
                "DetectorRadiusMm", "X0Mm", "Y0Mm", "Z0Mm"}
    with events.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or ()):
            raise ValueError("failed cold export columns are incomplete")
        rows = list(reader)
    try:
        ids = [int(row["Ion"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("failed cold export IDs are invalid") from error
    if len(ids) != 100 or set(ids) != set(range(1, 101)):
        raise ValueError("failed cold export original cohort is incomplete")
