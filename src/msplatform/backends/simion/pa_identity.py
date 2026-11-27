"""Pure, versioned PA physical identity validation and canonical key."""
from __future__ import annotations
from typing import Any, Mapping
from msplatform.io.file_identity import canonical_json_sha256


class PAFamilyCacheError(ValueError):
    """Invalid PA physical identity or historical PA evidence."""


CACHE_KEY_FIELDS = (
    "geometry",
    "gem",
    "basis_namespace",
    "mesh",
    "grid_phase",
    "surface",
    "simion_identity",
    "refine_policy",
    "builder_identity",
)
WORKING_FIELD_CACHE_KEY_FIELDS = (
    "geometry",
    "gem",
    "working_points",
    "mesh",
    "grid_phase",
    "surface",
    "boundary_policy",
    "rf_reference_voltage_v",
    "simion_identity",
    "builder_identity",
)
NON_RF_WORKING_FIELD_CACHE_KEY_FIELDS = tuple(
    field for field in WORKING_FIELD_CACHE_KEY_FIELDS if field != "rf_reference_voltage_v"
)


def _canonical_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    fields = next((candidate for candidate in (CACHE_KEY_FIELDS, WORKING_FIELD_CACHE_KEY_FIELDS, NON_RF_WORKING_FIELD_CACHE_KEY_FIELDS)
                   if isinstance(identity, Mapping) and set(identity) == set(candidate)), None)
    if fields is None:
        raise PAFamilyCacheError(
            "PA cache identity fields must be exactly the basis set (" + ", ".join(CACHE_KEY_FIELDS)
            + ") or the working-field set (" + ", ".join(WORKING_FIELD_CACHE_KEY_FIELDS)
            + ") with RF reference present only for an RF working field"
        )
    document = {field: identity[field] for field in fields}
    if fields in (WORKING_FIELD_CACHE_KEY_FIELDS, NON_RF_WORKING_FIELD_CACHE_KEY_FIELDS):
        points = document["working_points"]
        has_rf = isinstance(points, list) and any(isinstance(point, dict) and point.get("kind") == "rf_reference"
                                                  for point in points)
        if has_rf != ("rf_reference_voltage_v" in document):
            raise PAFamilyCacheError("PA cache identity fields must declare RF reference exactly when RF is consumed")
    # canonical_json_sha256 supplies the finite-JSON, stable-serialization gate.
    try:
        canonical_json_sha256(document)
    except ValueError as exc:
        raise PAFamilyCacheError("PA cache identity is not canonical finite JSON") from exc
    return document


def canonical_pa_family_cache_key(identity: Mapping[str, Any]) -> str:
    """Return the content key for all numerical and builder inputs to one PA family."""

    return canonical_json_sha256(_canonical_identity(identity))
