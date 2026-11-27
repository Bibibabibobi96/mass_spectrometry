"""Read explicitly versioned historical flight requests without starting work."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from msplatform.contracts.machine_contracts import validate_schema


def decode_flight_request(data: bytes) -> dict[str, Any]:
    """Validate and return original v9–v12 data without inventing particle kinds."""
    if not isinstance(data, bytes):
        raise ValueError("historical request must be explicit bytes")
    request = json.loads(data.decode("utf-8-sig"))
    if not isinstance(request, dict) or type(request.get("schema_version")) is not int:
        raise ValueError("historical request needs an explicit integer version")
    version = request["schema_version"]
    if version not in (9, 10, 11, 12):
        raise ValueError("unsupported historical flight request version")
    schema = Path(__file__).with_name("historical_schemas") / f"flight_request_v{version}.schema.json"
    validate_schema(request, schema)
    if version == 12:
        origin = request["source"]["instrument_origin_us"]
        if type(origin) not in (int, float) or not math.isfinite(origin):
            raise ValueError("historical recorded birth origin must be finite")
    if version in (10, 11) and any(type(target) is not int
            for provider in request["providers"]["instances"].values()
            for target in provider["electrode_bindings"].values()):
        raise ValueError(f"version{version} native electrode targets must be strict integers")
    return copy.deepcopy(request)
