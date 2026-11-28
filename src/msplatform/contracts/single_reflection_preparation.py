"""Validate versioned single-reflection preparation requests without executing them."""
from __future__ import annotations

import math
from pathlib import Path

from msplatform.contracts.machine_contracts import validate_schema

SCHEMA = Path(__file__).parent / "schemas/single_reflection_request_v9.schema.json"
SCHEMA_V10 = Path(__file__).parent / "schemas/single_reflection_request_v10.schema.json"
SCHEMA_V11 = Path(__file__).parent / "schemas/single_reflection_request_v11.schema.json"
SCHEMA_V12 = Path(__file__).parent / "schemas/single_reflection_request_v12.schema.json"
SCHEMA_V13 = Path(__file__).parent / "schemas/single_reflection_request_v13.schema.json"


def validate_preparation_request(request: dict) -> int:
    """Validate the declared request version without converting or changing it."""
    if not isinstance(request, dict) or type(request.get("schema_version")) is not int:
        raise ValueError("preparation request requires an explicit integer schema_version")
    version = request["schema_version"]
    if version not in (9, 10, 11, 12, 13):
        raise ValueError("unsupported preparation request schema_version")
    validate_schema(request, {9: SCHEMA, 10: SCHEMA_V10, 11: SCHEMA_V11, 12: SCHEMA_V12, 13: SCHEMA_V13}[version])
    if version in (12, 13):
        origin = request["source"]["instrument_origin_us"]
        if type(origin) not in (int, float) or not math.isfinite(origin):
            raise ValueError("recorded birth instrument_origin_us must be finite")
    if version in (10, 11) and any(type(target) is not int
            for provider in request["providers"]["instances"].values()
            for target in provider["electrode_bindings"].values()):
        raise ValueError(f"version{version} native electrode targets must be strict integers")
    return version
