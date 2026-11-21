"""Validate the oa-TOF COMSOL detector-analysis request contract."""
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
