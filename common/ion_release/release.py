"""Generic, shape-extensible entry point for repository ion releases.

Only registered shape/strategy pairs are executable.  A future shape is added
by supplying one closed validator and one deterministic materializer, then
registering the pair here; project field or geometry logic never enters this
registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from common.contracts.file_identity import file_sha256
from common.ion_release.cylinder import (
    GAUSSIAN_STRATEGY,
    HALTON_STRATEGY,
    ROLE,
    generate_cylinder_release_states,
    materialize_cylinder_release,
    validate_cylinder_release_spec,
    validate_materialized_cylinder_release,
)
from common.ion_release.continuous_axial_volume import (
    CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY,
    ROLE as CONTINUOUS_AXIAL_VOLUME_ROLE,
    generate_continuous_axial_volume_states,
    materialize_continuous_axial_volume_release,
    validate_continuous_axial_volume_spec,
    validate_materialized_continuous_axial_volume_release,
)
from common.ion_release.mt19937_disk_cone_rf_phase import (
    IDEAL_TRANSPORT_STRATEGY,
    STRATEGY as MT19937_DISK_CONE_RF_PHASE_STRATEGY,
    generate_mt19937_disk_cone_rf_phase_states,
    generate_mt19937_disk_sqrt_cone_rf_phase_states,
    materialize_mt19937_disk_cone_rf_phase_release,
    materialize_mt19937_disk_sqrt_cone_rf_phase_release,
    validate_materialized_mt19937_disk_cone_rf_phase_release,
    validate_materialized_mt19937_disk_sqrt_cone_rf_phase_release,
    validate_mt19937_disk_cone_rf_phase_release_spec,
    validate_mt19937_disk_sqrt_cone_rf_phase_release_spec,
)


ReleaseGenerator = Callable[[Mapping[str, Any]], list[dict[str, Any]]]
ReleaseValidator = Callable[[Mapping[str, Any]], None]
ReleaseMaterializer = Callable[[Mapping[str, Any], Path, Path, Mapping[str, Any] | None], dict[str, Any]]
ReceiptValidator = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class ReleaseHandler:
    """One closed implementation for a supported shape/strategy pair."""

    validate: ReleaseValidator
    generate: ReleaseGenerator
    materialize: ReleaseMaterializer
    validate_receipt: ReceiptValidator


def _materialize_cylinder(spec: Mapping[str, Any], state_table: Path, receipt: Path, spec_record: Mapping[str, Any] | None) -> dict[str, Any]:
    return materialize_cylinder_release(spec, state_table, receipt, spec_record=spec_record)

# This is deliberately data, not plugin discovery: unknown code cannot become
# executable just by appearing on sys.path or in a project configuration.
RELEASE_HANDLER_REGISTRY: dict[tuple[str, str], ReleaseHandler] = {
    ("cylinder", HALTON_STRATEGY): ReleaseHandler(
        validate_cylinder_release_spec, generate_cylinder_release_states,
        _materialize_cylinder, validate_materialized_cylinder_release,
    ),
    ("cylinder", GAUSSIAN_STRATEGY): ReleaseHandler(
        validate_cylinder_release_spec, generate_cylinder_release_states,
        _materialize_cylinder, validate_materialized_cylinder_release,
    ),
    CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY: ReleaseHandler(
        validate_continuous_axial_volume_spec,
        generate_continuous_axial_volume_states,
        materialize_continuous_axial_volume_release,
        validate_materialized_continuous_axial_volume_release,
    ),
    ("disk", MT19937_DISK_CONE_RF_PHASE_STRATEGY): ReleaseHandler(
        validate_mt19937_disk_cone_rf_phase_release_spec,
        generate_mt19937_disk_cone_rf_phase_states,
        materialize_mt19937_disk_cone_rf_phase_release,
        validate_materialized_mt19937_disk_cone_rf_phase_release,
    ),
    ("disk", IDEAL_TRANSPORT_STRATEGY): ReleaseHandler(
        validate_mt19937_disk_sqrt_cone_rf_phase_release_spec,
        generate_mt19937_disk_sqrt_cone_rf_phase_states,
        materialize_mt19937_disk_sqrt_cone_rf_phase_release,
        validate_materialized_mt19937_disk_sqrt_cone_rf_phase_release,
    ),
}
# Kept as the compact public sampler view for consumers that only need states.
SAMPLER_REGISTRY: Mapping[tuple[str, str], ReleaseGenerator] = {
    key: handler.generate for key, handler in RELEASE_HANDLER_REGISTRY.items()
}


def _release_key(spec: Mapping[str, Any]) -> tuple[str, str]:
    if spec.get("role") == CONTINUOUS_AXIAL_VOLUME_ROLE:
        return CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY
    geometry = spec.get("geometry")
    sampling = spec.get("sampling")
    if not isinstance(geometry, dict) or not isinstance(sampling, dict):
        raise ValueError("release geometry and sampling must be objects")
    shape = geometry.get("shape")
    strategy = sampling.get("strategy")
    if not isinstance(shape, str) or not isinstance(strategy, str):
        raise ValueError("release geometry.shape and sampling.strategy are required")
    return shape, strategy


def validate_release_spec(spec: Mapping[str, Any]) -> None:
    """Validate a generic release request against its registered handler."""
    key = _release_key(spec)
    handler = RELEASE_HANDLER_REGISTRY.get(key)
    if handler is None:
        raise ValueError(f"unsupported release shape/strategy: {key[0]}/{key[1]}")
    handler.validate(spec)


def generate_release_states(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate canonical states through the closed shape/strategy registry."""
    validate_release_spec(spec)
    return RELEASE_HANDLER_REGISTRY[_release_key(spec)].generate(spec)


def materialize_release(spec: Mapping[str, Any], state_table_path: Path, receipt_path: Path, *, spec_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Materialize a registered release and its immutable identity receipt."""
    validate_release_spec(spec)
    return RELEASE_HANDLER_REGISTRY[_release_key(spec)].materialize(
        spec, state_table_path, receipt_path, spec_record,
    )


def materialize_release_from_file(spec_path: Path, state_table_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Materialize a registered release from its frozen JSON request."""
    spec_path = spec_path.resolve(strict=True)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release specification is unreadable") from error
    if not isinstance(spec, dict):
        raise ValueError("release specification must be an object")
    return materialize_release(
        spec,
        state_table_path,
        receipt_path,
        spec_record={"path": str(spec_path), "bytes": spec_path.stat().st_size, "sha256": file_sha256(spec_path)},
    )


def validate_materialized_release(receipt_path: Path) -> dict[str, Any]:
    """Validate a registered release receipt and regenerate its exact table."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release receipt is unreadable") from error
    if not isinstance(receipt, dict) or not isinstance(receipt.get("release_spec"), dict):
        raise ValueError("release receipt lacks its release specification")
    validate_release_spec(receipt["release_spec"])
    return RELEASE_HANDLER_REGISTRY[_release_key(receipt["release_spec"])].validate_receipt(receipt_path)


__all__ = [
    "ROLE", "RELEASE_HANDLER_REGISTRY", "SAMPLER_REGISTRY", "generate_release_states", "materialize_release",
    "materialize_release_from_file", "validate_materialized_release", "validate_release_spec",
]
