"""Resolve manifest-bound compact pre-pulse producer evidence.

Both an ordinary successful family parent and a successful analysis recovery
can publish the same detector-blind compact handoff contract.  This module
normalizes those two current lifecycle paths to one verified evidence leaf so
campaign authoring and later preparation cannot interpret their lineage
differently.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import record_path, verify_record


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
FAMILY_PARENT_MODE = "multipole_family_source_closure"
SINGLE_FLIGHT_MODE = "rf_to_oatof_simion_single_flight"
RECOVERY_MODE = "rf_oatof_pre_pulse_time_series_analysis_recovery"
RECOVERY_RECEIPT_NAME = "pre_pulse_time_series_analysis_recovery_receipt.json"
RECOVERABLE_SOURCE_STATUSES = frozenset({"failed", "interrupted", "checkpoint"})


@dataclass(frozen=True)
class CompactPrePulseProducer:
    """Verified compact producer and the leaf records carrying its evidence."""

    producer_manifest_path: Path
    producer_manifest: dict[str, Any]
    leaf_manifest_path: Path
    leaf_manifest: dict[str, Any]
    population_path: Path
    population_record: dict[str, Any]
    mother_source_path: Path
    mother_source_record: dict[str, Any]
    compact_receipt_path: Path
    compact_receipt_record: dict[str, Any]
    handoff_path: Path
    handoff_record: dict[str, Any]


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _verified_record(
    manifest: dict[str, Any], *, run_dir: Path, role: str, record: object
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(record, dict):
        raise ContractError(f"{role} is missing")
    try:
        verify_record(role, record, base_dir=run_dir)
        path = record_path(record, base_dir=run_dir).resolve()
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(f"{role} identity differs") from exc
    return path, record


def _named_record(
    manifest: dict[str, Any], *, run_dir: Path, name: str
) -> tuple[Path, dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in manifest.get("inputs", {}).values():
        if isinstance(record, dict) and record_path(record, base_dir=run_dir).name == name:
            matches.append(record)
    for record in manifest.get("outputs", []):
        if isinstance(record, dict) and record_path(record, base_dir=run_dir).name == name:
            matches.append(record)
    if len(matches) != 1:
        raise ContractError(f"compact pre-pulse producer lacks unique {name}")
    return _verified_record(
        manifest, run_dir=run_dir, role=f"compact pre-pulse producer {name}",
        record=matches[0],
    )


def _require_manifest_identity(
    manifest: dict[str, Any], *, run_dir: Path, mode: str, status: str
) -> None:
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != status
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("run_id") != run_dir.name
        or manifest.get("mode") != mode
    ):
        raise ContractError("compact pre-pulse producer manifest identity differs")


def _verified_run_config(
    manifest: dict[str, Any], *, run_dir: Path, expected_mode: str,
    expected_experiment_id: str | None,
) -> tuple[Path, dict[str, Any]]:
    path, _ = _verified_record(
        manifest, run_dir=run_dir, role="compact pre-pulse producer run_config",
        record=manifest.get("run_config"),
    )
    config = _load_object(path, "compact pre-pulse producer run config")
    if expected_experiment_id is not None and config.get("experiment_id") != expected_experiment_id:
        raise ContractError("pre-pulse parent experiment mapping differs")
    # Recovery configs are current run contracts and must close their complete
    # identity.  Older ordinary family parents did not always repeat every
    # identity field, so their established experiment check remains unchanged.
    if expected_mode == RECOVERY_MODE and (
        config.get("mode") != RECOVERY_MODE
        or config.get("project") != INTEGRATION_ID
        or config.get("run_id") != run_dir.name
    ):
        raise ContractError("pre-pulse recovery run configuration identity differs")
    return path, config


def _ordinary_leaf(
    *, producer_manifest: dict[str, Any], producer_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    child_path, _ = _verified_record(
        producer_manifest, run_dir=producer_dir,
        role="pre-pulse producer single-flight child",
        record=producer_manifest.get("inputs", {}).get("single_flight_transport_manifest"),
    )
    child = _load_object(child_path, "pre-pulse single-flight child manifest")
    _require_manifest_identity(
        child, run_dir=child_path.parent, mode=SINGLE_FLIGHT_MODE, status="success"
    )
    return child_path, child


def _recovery_leaf(
    *, producer_manifest: dict[str, Any], producer_dir: Path,
    producer_config: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if producer_manifest.get("formal_eligible") is not False:
        raise ContractError("pre-pulse recovery must be non-Formal evidence")
    failed_child_path, failed_child_record = _verified_record(
        producer_manifest, run_dir=producer_dir,
        role="pre-pulse recovery failed child manifest",
        record=producer_manifest.get("inputs", {}).get("failed_child_manifest"),
    )
    failed_config_path, failed_config_record = _verified_record(
        producer_manifest, run_dir=producer_dir,
        role="pre-pulse recovery failed child run_config",
        record=producer_manifest.get("inputs", {}).get("failed_run_config"),
    )
    failed_child = _load_object(failed_child_path, "pre-pulse recovery source child manifest")
    if (
        failed_child.get("role") != "simulation_run_manifest"
        or failed_child.get("project") != INTEGRATION_ID
        or failed_child.get("run_id") != failed_child_path.parent.name
        or failed_child.get("mode") != SINGLE_FLIGHT_MODE
        or failed_child.get("status") not in RECOVERABLE_SOURCE_STATUSES
    ):
        raise ContractError("pre-pulse recovery source child identity differs")
    config_inputs = producer_config.get("inputs")
    if not isinstance(config_inputs, dict) or (
        Path(str(config_inputs.get("failed_child_manifest", ""))).resolve()
        != failed_child_path
        or Path(str(config_inputs.get("failed_run_config", ""))).resolve()
        != failed_config_path
    ):
        raise ContractError("pre-pulse recovery source paths differ")

    recovery_receipt_path, _ = _named_record(
        producer_manifest, run_dir=producer_dir, name=RECOVERY_RECEIPT_NAME
    )
    recovery_receipt = _load_object(
        recovery_receipt_path, "pre-pulse analysis recovery receipt"
    )
    failed_run = recovery_receipt.get("failed_run")
    materialized = recovery_receipt.get("materialized_outputs")
    if (
        recovery_receipt.get("role")
        != "rf_oatof_pre_pulse_time_series_analysis_recovery_receipt"
        or recovery_receipt.get("status") != "success"
        or recovery_receipt.get("solver_reexecuted") is not False
        or not isinstance(failed_run, dict)
        or Path(str(failed_run.get("manifest", ""))).resolve() != failed_child_path
        or failed_run.get("manifest_sha256") != failed_child_record.get("sha256")
        or Path(str(failed_run.get("run_config", ""))).resolve() != failed_config_path
        or failed_run.get("run_config_sha256") != failed_config_record.get("sha256")
        or not isinstance(materialized, dict)
        or materialized.get("mode") != "selected_pulse_handoff_only_v1"
    ):
        raise ContractError("pre-pulse analysis recovery receipt identity differs")
    return producer_dir / "run_manifest.json", producer_manifest


def resolve_compact_pre_pulse_producer(
    manifest_path: Path, *, expected_experiment_id: str | None = None,
) -> CompactPrePulseProducer:
    """Resolve either current successful producer topology to one compact leaf."""

    producer_manifest_path = manifest_path.resolve()
    producer_dir = producer_manifest_path.parent
    producer_manifest = _load_object(
        producer_manifest_path, "compact pre-pulse producer manifest"
    )
    mode = producer_manifest.get("mode")
    if mode not in {FAMILY_PARENT_MODE, RECOVERY_MODE}:
        raise ContractError("compact pre-pulse producer mode is unsupported")
    _require_manifest_identity(
        producer_manifest, run_dir=producer_dir, mode=mode, status="success"
    )
    _, producer_config = _verified_run_config(
        producer_manifest, run_dir=producer_dir, expected_mode=mode,
        expected_experiment_id=expected_experiment_id,
    )
    if mode == FAMILY_PARENT_MODE:
        leaf_manifest_path, leaf_manifest = _ordinary_leaf(
            producer_manifest=producer_manifest, producer_dir=producer_dir
        )
    else:
        leaf_manifest_path, leaf_manifest = _recovery_leaf(
            producer_manifest=producer_manifest, producer_dir=producer_dir,
            producer_config=producer_config,
        )
    leaf_dir = leaf_manifest_path.parent
    population_path, population_record = _named_record(
        leaf_manifest, run_dir=leaf_dir, name="resolved_population_contract.json"
    )
    mother_source_path, mother_source_record = _named_record(
        leaf_manifest, run_dir=leaf_dir, name="mother_particle_source.csv"
    )
    compact_receipt_path, compact_receipt_record = _named_record(
        leaf_manifest, run_dir=leaf_dir, name="pre_pulse_compact_handoff_receipt.json"
    )
    handoff_path, handoff_record = _named_record(
        leaf_manifest, run_dir=leaf_dir, name="pre_pulse_compact_handoff.csv"
    )
    if mode == RECOVERY_MODE:
        recovery_receipt_path, _ = _named_record(
            producer_manifest, run_dir=producer_dir, name=RECOVERY_RECEIPT_NAME
        )
        recovery_receipt = _load_object(
            recovery_receipt_path, "pre-pulse analysis recovery receipt"
        )
        materialized = recovery_receipt["materialized_outputs"]
        handoff = materialized.get("handoff")
        compact = materialized.get("handoff_receipt")
        if (
            not isinstance(handoff, dict)
            or Path(str(handoff.get("path", ""))).resolve() != handoff_path
            or handoff.get("sha256") != handoff_record.get("sha256")
            or not isinstance(compact, dict)
            or Path(str(compact.get("path", ""))).resolve() != compact_receipt_path
            or compact.get("sha256") != compact_receipt_record.get("sha256")
            or file_sha256(handoff_path) != handoff_record.get("sha256")
            or file_sha256(compact_receipt_path) != compact_receipt_record.get("sha256")
        ):
            raise ContractError("pre-pulse recovery compact output identity differs")
        config_inputs = producer_config["inputs"]
        if (
            Path(str(config_inputs.get("resolved_population_contract", ""))).resolve()
            != population_path
            or Path(str(config_inputs.get("mother_particle_source", ""))).resolve()
            != mother_source_path
        ):
            raise ContractError("pre-pulse recovery cohort input paths differ")
    return CompactPrePulseProducer(
        producer_manifest_path=producer_manifest_path,
        producer_manifest=producer_manifest,
        leaf_manifest_path=leaf_manifest_path,
        leaf_manifest=leaf_manifest,
        population_path=population_path,
        population_record=population_record,
        mother_source_path=mother_source_path,
        mother_source_record=mother_source_record,
        compact_receipt_path=compact_receipt_path,
        compact_receipt_record=compact_receipt_record,
        handoff_path=handoff_path,
        handoff_record=handoff_record,
    )
