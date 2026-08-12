"""Validate COMSOL retrace arms and freeze SIMION-to-COMSOL receipts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256


ARM_ROLE = "rf_oatof_comsol_retrace_arm"
RECEIPT_ROLE = "simion_winner_to_comsol_handoff_receipt"
CHANGE_PLANS = {
    "source": {"mesh_rebuild": False, "electrostatics": False, "particles": True},
    "field_mask": {"mesh_rebuild": False, "electrostatics": False, "particles": True},
    "voltage": {"mesh_rebuild": False, "electrostatics": True, "particles": True},
}
RELEASE_COLUMNS = (
    "particle_id",
    "mass_amu",
    "charge_state",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_per_s",
    "vy_m_per_s",
    "vz_m_per_s",
    "kinetic_energy_eV",
)
CENSUS_STATUSES = ("hit", "wall", "escape", "timeout", "solver_failure")
FIELD_MASK_PARAMETERS = tuple(
    f"ideal_{region}_{component}"
    for region in ("accel", "drift", "stage1", "stage2")
    for component in ("ex", "ey", "ez")
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"frozen handoff file is missing: {path}")
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _validate_file_record(record: Any, role: str) -> Path:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise ValueError(f"handoff {role} file record is invalid")
    path = Path(record["path"])
    if not path.is_file():
        raise ValueError(f"handoff {role} file is missing")
    if path.stat().st_size != int(record["bytes"]) or file_sha256(path) != record["sha256"]:
        raise ValueError(f"handoff {role} identity changed")
    return path


def _release_identity(path: Path) -> tuple[list[int], float]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RELEASE_COLUMNS:
            raise ValueError("Cartesian release columns or ordering differ from the contract")
        rows = list(reader)
    if not rows:
        raise ValueError("Cartesian release is empty")
    ids = [int(row["particle_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Cartesian release contains duplicate particle_id")
    maximum_speed = 0.0
    for row in rows:
        for name in RELEASE_COLUMNS[1:]:
            value = float(row[name])
            if not math.isfinite(value):
                raise ValueError(f"Cartesian release contains non-finite {name}")
        maximum_speed = max(
            maximum_speed,
            math.sqrt(sum(float(row[f"v{axis}_m_per_s"]) ** 2 for axis in "xyz")),
        )
    return ids, maximum_speed


def build_handoff_receipt(
    *,
    simion_manifest_path: Path,
    geometry_path: Path,
    voltage_path: Path,
    source_model_path: Path,
    source_model_metadata_path: Path,
    release_path: Path,
    source_metadata_path: Path,
    acceptance_window_path: Path,
    output_path: Path,
    field_mode: str,
) -> dict[str, Any]:
    """Freeze the one admissible SIMION-winner input set for COMSOL."""
    if output_path.exists():
        raise ValueError("handoff receipt already exists; receipts are immutable")
    manifest = _load_json(simion_manifest_path)
    if manifest.get("status") != "success" or not manifest.get("run_id"):
        raise ValueError("SIMION winner manifest must be a terminal success run")
    source_metadata = _load_json(source_metadata_path)
    if source_metadata.get("role") != "rf_oatof_comsol_cartesian_retrace_release":
        raise ValueError("source metadata is not a Cartesian retrace release")
    if source_metadata.get("coordinate_frame") != "shared_global_cartesian":
        raise ValueError("source velocity is not in the shared global Cartesian frame")
    velocity_error = float(source_metadata.get("maximum_velocity_serialization_error_m_per_s", math.inf))
    if not math.isfinite(velocity_error) or velocity_error >= 1.0e-6:
        raise ValueError("source velocity error must be <1e-6 m/s")
    acceptance = _load_json(acceptance_window_path)
    if acceptance.get("detector_blind") is not True:
        raise ValueError("acceptance window must be detector-blind")
    if acceptance.get("definition_method") != "field_error_time_budget":
        raise ValueError("acceptance window must be derived from the field-error time budget")
    particle_ids, maximum_speed = _release_identity(release_path)
    model_metadata = _load_json(source_model_metadata_path)
    if model_metadata.get("role") != "rf_oatof_comsol_source_model_identity":
        raise ValueError("source model metadata role is invalid")
    if model_metadata.get("geometry_sha256") != file_sha256(geometry_path):
        raise ValueError("source model metadata geometry identity differs")
    if model_metadata.get("voltages_sha256") != file_sha256(voltage_path):
        raise ValueError("source model metadata voltage identity differs")
    if model_metadata.get("field_mode") != field_mode:
        raise ValueError("source model metadata field mode differs")
    if model_metadata.get("source_model_sha256") != file_sha256(source_model_path):
        raise ValueError("source model metadata MPH identity differs")
    baseline_mask = model_metadata.get("baseline_field_mask")
    baseline_voltages = model_metadata.get("baseline_voltages_V")
    if not isinstance(baseline_mask, dict) or set(baseline_mask) != set(FIELD_MASK_PARAMETERS):
        raise ValueError("source model metadata must freeze all 12 field-mask flags")
    if not isinstance(baseline_voltages, dict) or not baseline_voltages:
        raise ValueError("source model metadata must freeze baseline voltages")
    selection = source_metadata.get("selection", {})
    if int(selection.get("particles", -1)) != len(particle_ids):
        raise ValueError("source metadata particle count differs from release")
    clock = {
        "tof_definition": "t_detector_minus_t_pulse_effective",
        "pulse_effective_time_us": float(selection["pulse_time_us"]),
        "instrument_clock_peak_is_resolution_claim": False,
    }
    receipt = {
        "schema_version": 1,
        "role": RECEIPT_ROLE,
        "status": "frozen",
        "simion_winner": {
            "run_id": manifest["run_id"],
            "run_manifest": _file_record(simion_manifest_path),
        },
        "geometry": _file_record(geometry_path),
        "voltages": _file_record(voltage_path),
        "field_mode": field_mode,
        "source_model": {
            "mph": _file_record(source_model_path),
            "metadata": _file_record(source_model_metadata_path),
        },
        "source": {
            "release": _file_record(release_path),
            "metadata": _file_record(source_metadata_path),
            "coordinate_frame": "shared_global_cartesian",
            "particle_count": len(particle_ids),
            "particle_ids": particle_ids,
            "maximum_speed_m_per_s": maximum_speed,
            "velocity_error_limit_m_per_s": 1.0e-6,
            "maximum_velocity_error_m_per_s": velocity_error,
            "species": source_metadata["species"],
        },
        "clock": clock,
        "acceptance_window": _file_record(acceptance_window_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def validate_retrace_arm(path: Path) -> dict[str, Any]:
    """Validate one declarative retrace arm and return its execution plan."""
    arm = _load_json(path)
    required = {
        "schema_version",
        "role",
        "arm_id",
        "change_class",
        "source_model",
        "source_model_sha256",
        "source_model_metadata",
        "handoff_receipt",
        "cartesian_release",
        "cartesian_release_metadata",
        "output_model",
        "output_root",
        "mass_amu",
        "charge_state",
        "pulse_effective_time_us",
        "source_deviation",
        "baseline_field_mask",
        "baseline_voltages_V",
        "field_mask",
        "voltage_overrides_V",
    }
    missing = required - arm.keys()
    if missing:
        raise ValueError(f"retrace arm is missing fields: {sorted(missing)}")
    unknown = arm.keys() - required
    if unknown:
        raise ValueError(f"retrace arm contains unknown fields: {sorted(unknown)}")
    if arm["schema_version"] != 1 or arm["role"] != ARM_ROLE:
        raise ValueError("retrace arm identity is invalid")
    change_class = arm["change_class"]
    if change_class in {"geometry", "mesh"}:
        raise ValueError(
            f"{change_class} changes require the governed model builder; retrace refuses rebuild"
        )
    if change_class not in CHANGE_PLANS:
        raise ValueError(f"unsupported retrace change_class: {change_class}")
    for name in (
        "source_model",
        "source_model_metadata",
        "handoff_receipt",
        "cartesian_release",
        "cartesian_release_metadata",
    ):
        if not Path(arm[name]).is_absolute():
            raise ValueError(f"retrace arm {name} must be an absolute frozen path")
        if not Path(arm[name]).is_file():
            raise ValueError(f"retrace arm {name} is missing")
    expected_model_sha = str(arm["source_model_sha256"]).upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_model_sha):
        raise ValueError("source_model_sha256 is invalid")
    if file_sha256(Path(arm["source_model"])) != expected_model_sha:
        raise ValueError("source model identity differs from retrace arm")
    for name in ("output_model", "output_root"):
        if not Path(arm[name]).is_absolute():
            raise ValueError(f"retrace arm {name} must be an absolute run-local path")
    receipt = _load_json(Path(arm["handoff_receipt"]))
    if receipt.get("role") != RECEIPT_ROLE or receipt.get("status") != "frozen":
        raise ValueError("handoff receipt is not frozen")
    for name, record in (
        ("SIMION manifest", receipt["simion_winner"]["run_manifest"]),
        ("geometry", receipt["geometry"]),
        ("voltages", receipt["voltages"]),
        ("source metadata", receipt["source"]["metadata"]),
        ("acceptance window", receipt["acceptance_window"]),
        ("source model", receipt["source_model"]["mph"]),
        ("source model metadata", receipt["source_model"]["metadata"]),
    ):
        _validate_file_record(record, name)
    frozen_release = _validate_file_record(receipt["source"]["release"], "release")
    if Path(arm["source_model"]).resolve() != Path(receipt["source_model"]["mph"]["path"]).resolve():
        raise ValueError("retrace source model differs from handoff receipt")
    model_metadata = _load_json(Path(arm["source_model_metadata"]))
    if file_sha256(Path(arm["source_model_metadata"])) != receipt["source_model"]["metadata"]["sha256"]:
        raise ValueError("retrace source model metadata differs from handoff receipt")
    if (
        model_metadata.get("geometry_sha256") != receipt["geometry"]["sha256"]
        or model_metadata.get("voltages_sha256") != receipt["voltages"]["sha256"]
        or model_metadata.get("field_mode") != receipt["field_mode"]
        or model_metadata.get("source_model_sha256") != expected_model_sha
    ):
        raise ValueError("source model physics identity differs from handoff receipt")
    release_path = Path(arm["cartesian_release"])
    release_metadata_path = Path(arm["cartesian_release_metadata"])
    release_metadata = _load_json(release_metadata_path)
    if release_metadata.get("role") != "rf_oatof_comsol_cartesian_retrace_release":
        raise ValueError("Cartesian release metadata role is invalid")
    if release_metadata.get("coordinate_frame") != "shared_global_cartesian":
        raise ValueError("Cartesian release metadata frame is invalid")
    release_error = float(
        release_metadata.get("maximum_velocity_serialization_error_m_per_s", math.inf)
    )
    if not math.isfinite(release_error) or release_error >= 1.0e-6:
        raise ValueError("Cartesian release velocity error must be <1e-6 m/s")
    output_record = release_metadata.get("output", {})
    if output_record.get("sha256") != file_sha256(release_path):
        raise ValueError("Cartesian release differs from its metadata")
    if change_class != "source" and (
        release_path.resolve() != frozen_release.resolve()
        or file_sha256(release_path) != receipt["source"]["release"]["sha256"]
    ):
        raise ValueError("non-source arm release differs from the handoff receipt")
    particle_ids, _ = _release_identity(release_path)
    if particle_ids != receipt["source"]["particle_ids"]:
        raise ValueError("Cartesian release particle identity/order differs from receipt")
    if not math.isclose(float(arm["mass_amu"]), float(receipt["source"]["species"]["mass_amu"]), abs_tol=1e-12):
        raise ValueError("arm mass differs from winner receipt")
    if int(arm["charge_state"]) != int(receipt["source"]["species"]["charge_state"]):
        raise ValueError("arm charge differs from winner receipt")
    if not math.isclose(
        float(arm["pulse_effective_time_us"]),
        float(receipt["clock"]["pulse_effective_time_us"]),
        abs_tol=1e-12,
    ):
        raise ValueError("arm pulse-effective clock differs from winner receipt")
    if float(receipt["source"]["maximum_velocity_error_m_per_s"]) >= 1.0e-6:
        raise ValueError("handoff velocity error does not satisfy <1e-6 m/s")
    mask = arm["field_mask"]
    voltages = arm["voltage_overrides_V"]
    baseline_mask = arm["baseline_field_mask"]
    baseline_voltages = arm["baseline_voltages_V"]
    deviation = arm["source_deviation"]
    if not all(isinstance(value, dict) for value in (mask, voltages, baseline_mask, baseline_voltages, deviation)):
        raise ValueError("mask, voltage, and source-deviation fields must be objects")
    if set(baseline_mask) != set(FIELD_MASK_PARAMETERS):
        raise ValueError("baseline_field_mask must declare all 12 idealization flags")
    if baseline_mask != model_metadata.get("baseline_field_mask"):
        raise ValueError("arm baseline field mask differs from source model metadata")
    if baseline_voltages != model_metadata.get("baseline_voltages_V"):
        raise ValueError("arm baseline voltages differ from source model metadata")
    for name, value in mask.items():
        if not re.fullmatch(r"ideal_(accel|drift|stage1|stage2)_(ex|ey|ez)", name):
            raise ValueError(f"invalid field-mask parameter: {name}")
        if type(value) is not int or value not in (0, 1):
            raise ValueError(f"field-mask parameter must be 0 or 1: {name}")
    for name, value in baseline_mask.items():
        if name not in FIELD_MASK_PARAMETERS or type(value) is not int or value not in (0, 1):
            raise ValueError(f"invalid baseline field-mask parameter: {name}")
    for name, value in voltages.items():
        if not re.fullmatch(r"V_[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid voltage parameter: {name}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"voltage parameter must be finite numeric: {name}")
    for name, value in baseline_voltages.items():
        if not re.fullmatch(r"V_[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid baseline voltage parameter: {name}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"baseline voltage must be finite numeric: {name}")
    if change_class == "field_mask" and not mask:
        raise ValueError("field_mask arm must declare at least one mask parameter")
    if change_class != "field_mask" and mask:
        raise ValueError("field-mask overrides are permitted only for field_mask arms")
    if change_class == "voltage" and not voltages:
        raise ValueError("voltage arm must declare at least one voltage override")
    if change_class != "voltage" and voltages:
        raise ValueError("voltage overrides are permitted only for voltage arms")
    if change_class == "source":
        if set(deviation) != {"deviation_id", "method", "detector_blind", "preserves_particle_ids"}:
            raise ValueError("source arm must declare its exact source_deviation contract")
        if not deviation["deviation_id"] or not deviation["method"]:
            raise ValueError("source deviation identity and method must be non-empty")
        if deviation["detector_blind"] is not True or deviation["preserves_particle_ids"] is not True:
            raise ValueError("source deviation must be detector-blind and preserve winner IDs")
    elif deviation:
        raise ValueError("source_deviation is permitted only for source arms")
    effective_mask = dict(baseline_mask)
    effective_mask.update(mask)
    effective_voltages = dict(baseline_voltages)
    effective_voltages.update(voltages)
    plan = dict(CHANGE_PLANS[change_class])
    plan.update({
        "change_class": change_class,
        "census_statuses": list(CENSUS_STATUSES),
        "effective_field_mask": effective_mask,
        "effective_voltages_V": effective_voltages,
    })
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    receipt = subparsers.add_parser("build-receipt")
    receipt.add_argument("--simion-manifest", type=Path, required=True)
    receipt.add_argument("--geometry", type=Path, required=True)
    receipt.add_argument("--voltages", type=Path, required=True)
    receipt.add_argument("--source-model", type=Path, required=True)
    receipt.add_argument("--source-model-metadata", type=Path, required=True)
    receipt.add_argument("--release", type=Path, required=True)
    receipt.add_argument("--source-metadata", type=Path, required=True)
    receipt.add_argument("--acceptance-window", type=Path, required=True)
    receipt.add_argument("--field-mode", required=True)
    receipt.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate-arm")
    validate.add_argument("--arm", type=Path, required=True)
    validate.add_argument("--plan-output", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "build-receipt":
        value = build_handoff_receipt(
            simion_manifest_path=arguments.simion_manifest,
            geometry_path=arguments.geometry,
            voltage_path=arguments.voltages,
            source_model_path=arguments.source_model,
            source_model_metadata_path=arguments.source_model_metadata,
            release_path=arguments.release,
            source_metadata_path=arguments.source_metadata,
            acceptance_window_path=arguments.acceptance_window,
            output_path=arguments.output,
            field_mode=arguments.field_mode,
        )
        print(f"COMSOL_HANDOFF_RECEIPT=PASS PARTICLES={value['source']['particle_count']}")
    else:
        value = validate_retrace_arm(arguments.arm)
        if arguments.plan_output:
            arguments.plan_output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        print(f"COMSOL_RETRACE_ARM=PASS CHANGE_CLASS={value['change_class']}")


if __name__ == "__main__":
    main()
