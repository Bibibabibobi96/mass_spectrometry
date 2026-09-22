"""Thin OA-TOF adapter for native-family operating-PA cache operations.

All field-state calculations stay in Python.  SIMION execution remains owned
by the PowerShell runner so the repository resource scheduler and host lease
continue to govern every solver process.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.simion.native_fast_adjust_operating_pa_cache import (
    EXPORT_RECEIPT_SUFFIX,
    build_native_operating_pa_export_plan,
    canonical_native_operating_pa_cache_key,
    canonical_native_operating_pa_identity,
    ensure_native_operating_pa_cache,
    materialize_native_operating_pa_cache,
    native_operating_pa_group_identity,
    native_operating_pa_member_identity,
    probe_native_operating_pa_cache,
    publish_native_operating_pa_cache,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.standalone_field_bank import (
    MODE_IDS,
    resolve_mode_states,
)


STATE_OUTPUT_SUFFIXES = {
    "carrier_off": "carrier_off.pa",
    "pulse_delta": "pulse_delta.pa",
    "rf_differential_unit": "rf_differential.pa",
}
BOUNDARY_MASK_POLICY_ID = "physical_geometry_boundary_flags_v1"
_EXPORT_RECEIPT_FIELDS = {
    "schema_version",
    "role",
    "policy_id",
    "status",
    "potential_operation",
    "source_controller_basename",
    "physical_template_basename",
    "output_basename",
    "adjustable_electrode_count",
    "boundary_points",
    "physical_boundary_flags",
    "cleared_synthetic_boundary_flags",
    "copy_mode",
}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_object(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def export_receipt_path(output: Path) -> Path:
    """Return the direct receipt paired with one detached operating PA."""

    return output.with_name(output.name + EXPORT_RECEIPT_SUFFIX)


def verify_export_receipts(
    identity: Mapping[str, object], source_directory: Path
) -> dict[str, object]:
    """Bind mask restoration evidence to an operating-cache identity."""

    canonical = canonical_native_operating_pa_identity(identity)
    source_family = canonical["source_family"]
    controller_name = str(source_family["controller_basename"])
    template_name = controller_name[:-1] + "#"
    solution_count = len(source_family["solution_ids"])
    records: list[dict[str, object]] = []
    for member in canonical["members"]:
        output = source_directory / str(member["output_name"])
        receipt_path = export_receipt_path(output)
        if not output.is_file() or output.stat().st_size < 1:
            raise ValueError(f"operating PA output is missing or empty: {output}")
        receipt = _load_object(receipt_path)
        if set(receipt) != _EXPORT_RECEIPT_FIELDS:
            raise ValueError(f"operating PA export receipt fields differ: {receipt_path}")
        expected = {
            "schema_version": 1,
            "role": "simion_fast_adjusted_standalone_pa_export",
            "policy_id": BOUNDARY_MASK_POLICY_ID,
            "status": "pass",
            "potential_operation": "unchanged_official_electrode_setter",
            "source_controller_basename": controller_name,
            "physical_template_basename": template_name,
            "output_basename": output.name,
            "adjustable_electrode_count": solution_count,
        }
        for field, value in expected.items():
            if receipt[field] != value:
                raise ValueError(
                    f"operating PA export receipt {field} differs: {receipt_path}"
                )
        for field in (
            "boundary_points",
            "physical_boundary_flags",
            "cleared_synthetic_boundary_flags",
        ):
            value = receipt[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"operating PA export receipt {field} is invalid: {receipt_path}"
                )
        if receipt["boundary_points"] < 1:
            raise ValueError(f"operating PA export receipt boundary is empty: {receipt_path}")
        if receipt["copy_mode"] not in {"native_copy", "point_fallback"}:
            raise ValueError(f"operating PA export receipt copy mode differs: {receipt_path}")
        records.append(
            {
                "output_basename": output.name,
                "output_bytes": output.stat().st_size,
                "output_sha256": file_sha256(output),
                "receipt_basename": receipt_path.name,
                "receipt_bytes": receipt_path.stat().st_size,
                "receipt_sha256": file_sha256(receipt_path),
                "boundary_points": receipt["boundary_points"],
                "physical_boundary_flags": receipt["physical_boundary_flags"],
                "cleared_synthetic_boundary_flags": receipt[
                    "cleared_synthetic_boundary_flags"
                ],
            }
        )
    return {
        "schema_version": 1,
        "role": "rf_oatof_native_operating_pa_export_verification",
        "cache_key": canonical_native_operating_pa_cache_key(canonical),
        "boundary_mask_policy_id": BOUNDARY_MASK_POLICY_ID,
        "records": records,
    }


def operating_members(
    role: str, mode_states: Mapping[str, Mapping[int, float]]
) -> list[dict[str, object]]:
    """Return the three complete, deterministically named operating states."""

    if not role or Path(role).name != role or "." in role:
        raise ValueError("operating role must be one extension-free direct name")
    if set(mode_states) != set(STATE_OUTPUT_SUFFIXES):
        raise ValueError("operating mode states must contain exactly three states")
    members: list[dict[str, object]] = []
    for state, suffix in STATE_OUTPUT_SUFFIXES.items():
        voltages = mode_states[state]
        if set(voltages) != set(MODE_IDS):
            raise ValueError(f"operating state {state} must contain modes 36 through 43")
        members.append(
            native_operating_pa_member_identity(
                f"{role}.{suffix}",
                {mode_id: float(voltages[mode_id]) for mode_id in MODE_IDS},
            )
        )
    return members


def resolve_identity(
    *,
    role: str,
    source_family_role: str,
    source_family_cache_key: str,
    controller_basename: str,
    mode_states: Mapping[str, Mapping[int, float]],
    exporter: Path,
) -> dict[str, object]:
    return native_operating_pa_group_identity(
        source_family_role=source_family_role,
        source_family_cache_key=source_family_cache_key,
        controller_basename=controller_basename,
        solution_ids=MODE_IDS,
        members=operating_members(role, mode_states),
        exporter_path=exporter,
    )


def _state_documents(args: argparse.Namespace) -> tuple[dict[str, dict[int, float]], dict[str, object]]:
    accelerator = _load_object(args.accelerator_main)
    states = resolve_mode_states(
        _load_object(args.upstream),
        _load_object(args.frontend),
        _load_object(args.oatof),
        _load_object(args.region_field),
        accelerator["pa_plus_solution_model"],
    )
    identity = resolve_identity(
        role=args.role,
        source_family_role=args.source_family_role,
        source_family_cache_key=args.source_family_cache_key,
        controller_basename=args.controller_basename,
        mode_states=states,
        exporter=args.exporter,
    )
    return states, identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "identity",
            "export-plan",
            "verify-exports",
            "probe",
            "ensure",
            "publish",
            "materialize",
        ),
    )
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--generation", type=Path)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--destination-directory", type=Path)
    parser.add_argument("--staging-directory", type=Path)
    parser.add_argument("--operating-directory", type=Path)
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--role")
    parser.add_argument("--source-family-role")
    parser.add_argument("--source-family-cache-key")
    parser.add_argument("--controller-basename")
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--oatof", type=Path)
    parser.add_argument("--region-field", type=Path)
    parser.add_argument("--accelerator-main", type=Path)
    args = parser.parse_args()

    if args.action == "identity":
        required = (
            args.exporter,
            args.role,
            args.source_family_role,
            args.source_family_cache_key,
            args.controller_basename,
            args.upstream,
            args.frontend,
            args.oatof,
            args.region_field,
            args.accelerator_main,
        )
        if any(value is None for value in required):
            raise ValueError("identity action lacks a required source or family argument")
        states, identity = _state_documents(args)
        _write_object(
            args.output,
            {
                "schema_version": 1,
                "role": "rf_oatof_native_operating_pa_identity",
                "cache_key": canonical_native_operating_pa_cache_key(identity),
                "boundary_mask_policy_id": BOUNDARY_MASK_POLICY_ID,
                "identity": identity,
                "mode_states_v": {
                    name: {str(mode_id): values[mode_id] for mode_id in MODE_IDS}
                    for name, values in states.items()
                },
            },
        )
        return 0

    if args.identity is None:
        raise ValueError(f"{args.action} action requires --identity")
    document = _load_object(args.identity)
    if document.get("boundary_mask_policy_id") != BOUNDARY_MASK_POLICY_ID:
        raise ValueError("native operating PA boundary-mask policy differs")
    identity = canonical_native_operating_pa_identity(document["identity"])

    if args.action == "export-plan":
        if args.staging_directory is None or args.operating_directory is None or args.exporter is None:
            raise ValueError("export-plan requires staging, operating directory, and exporter")
        plan = build_native_operating_pa_export_plan(
            identity,
            args.staging_directory,
            args.operating_directory,
            exporter_path=args.exporter,
        )
        _write_object(
            args.output,
            {
                "schema_version": 1,
                "role": "rf_oatof_native_operating_pa_export_plan",
                "cache_key": canonical_native_operating_pa_cache_key(identity),
                "exports": [
                    {
                        "exporter": str(item.exporter_path.resolve()),
                        "source_controller": str(item.source_controller.resolve()),
                        "output": str(item.output_path.resolve()),
                        "receipt": str(item.receipt_path.resolve()),
                        "voltage_arguments": list(item.voltage_arguments),
                    }
                    for item in plan
                ],
            },
        )
        return 0

    if args.action == "verify-exports":
        if args.source_directory is None:
            raise ValueError("verify-exports action requires --source-directory")
        _write_object(args.output, verify_export_receipts(identity, args.source_directory))
        return 0

    if args.cache_root is None:
        raise ValueError(f"{args.action} action requires --cache-root")
    if args.action in {"probe", "ensure"}:
        probe = (
            probe_native_operating_pa_cache(args.cache_root, identity)
            if args.action == "probe"
            else ensure_native_operating_pa_cache(args.cache_root, identity)
        )
        _write_object(
            args.output,
            {
                "schema_version": 1,
                "role": "rf_oatof_native_operating_pa_cache_probe",
                "cache_key": probe.cache_key,
                "disposition": probe.disposition.value,
                "generation_directory": (
                    str(probe.generation_directory.resolve())
                    if probe.generation_directory is not None
                    else None
                ),
                "detail": probe.detail,
            },
        )
        return 0
    if args.action == "publish":
        if args.source_directory is None:
            raise ValueError("publish action requires --source-directory")
        verify_export_receipts(identity, args.source_directory)
        publication = publish_native_operating_pa_cache(
            args.cache_root, identity, args.source_directory
        )
        _write_object(
            args.output,
            {
                "schema_version": 1,
                "role": "rf_oatof_native_operating_pa_cache_publication",
                "cache_key": publication.cache_key,
                "disposition": publication.disposition.value,
                "generation_sha256": publication.generation_sha256,
                "generation_directory": str(publication.generation_directory.resolve()),
            },
        )
        return 0
    if args.action == "materialize":
        if args.generation is None or args.destination_directory is None:
            raise ValueError("materialize action requires generation and destination directory")
        result = materialize_native_operating_pa_cache(
            args.generation,
            args.destination_directory,
            expected_identity=identity,
        )
        _write_object(
            args.output,
            {
                "schema_version": 1,
                "role": "rf_oatof_native_operating_pa_materialization",
                "cache_key": canonical_native_operating_pa_cache_key(identity),
                "generation_directory": str(result.source_generation_directory.resolve()),
                "predecessor_generation_directory": (
                    str(result.predecessor_generation_directory.resolve())
                    if result.predecessor_generation_directory is not None else None
                ),
                "repair_receipt_path": (
                    str(result.repair_receipt_path.resolve())
                    if result.repair_receipt_path is not None else None
                ),
                "destination_directory": str(result.destination_directory.resolve()),
                "files": list(result.files),
            },
        )
        return 0
    raise AssertionError(args.action)


if __name__ == "__main__":
    raise SystemExit(main())
