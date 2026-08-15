"""Publish one family RF-handoff source bundle for the oaTOF consumer."""

from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
    write_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import validate_schema
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import (
    FramedPosition,
    FramedVector,
    RigidTransform,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.rf_handoff_adapter import (
    encode_simion_accelerator_velocity,
    ordered_solver_identity_map,
    validate_ion_velocity_adapter,
)


EXPECTED_INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
EXPECTED_DOWNSTREAM_PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
EXPECTED_DOWNSTREAM_FRAME_ID = "oatof_global"
ROW_MAP_COLUMNS = [
    "solver_row_index",
    "particle_id",
    "instrument_time_us",
    "lineage_age_us",
    "particle_age_us",
    "solver_birth_time_us",
    "azimuth_deg",
    "elevation_deg",
]


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _reference(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def _read_exact_csv(
    path: Path,
    columns: Sequence[str],
    label: str,
) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(columns):
            raise ValueError(f"{label} columns differ from the required schema")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{label} must contain at least one row")
    return rows


def _resolved_transform(resolved: dict[str, Any]) -> RigidTransform:
    validate_schema(resolved, "resolved_connection.schema.json")
    if resolved["integration_id"] != EXPECTED_INTEGRATION_ID:
        raise ValueError("resolved connection belongs to a different integration")
    selection = resolved["selection"]
    if selection["downstream_project_id"] != EXPECTED_DOWNSTREAM_PROJECT_ID:
        raise ValueError("resolved connection targets a different downstream project")
    if resolved["coupling_mode"] != "monolithic_joint_solve":
        raise ValueError(
            "family source publication requires monolithic_joint_solve coupling"
        )

    ports = resolved["port_geometry"]
    upstream_frame = ports["upstream"]["coordinate_frame"]["frame_id"]
    downstream_frame = ports["downstream"]["coordinate_frame"]["frame_id"]
    if downstream_frame != EXPECTED_DOWNSTREAM_FRAME_ID:
        raise ValueError("resolved downstream frame must be oatof_global")
    registration = resolved["spatial_registration"]
    return RigidTransform(
        from_frame_id=upstream_frame,
        to_frame_id=downstream_frame,
        rotation=registration["rotation_upstream_to_downstream"],
        translation_mm=registration["translation_mm"],
    )


def _transform_canonical_rows(
    upstream_rows: Sequence[Mapping[str, str]],
    transform: RigidTransform,
) -> list[dict[str, object]]:
    transformed_rows: list[dict[str, object]] = []
    for row in upstream_rows:
        particle_id = row["particle_id"]
        if row["frame_id"] != transform.from_frame_id:
            raise ValueError(
                f"particle {particle_id} frame differs from resolved upstream frame"
            )
        position = transform.transform_position(
            FramedPosition(
                transform.from_frame_id,
                tuple(float(row[f"position_{axis}_mm"]) for axis in "xyz"),
            )
        )
        velocity = transform.transform_vector(
            FramedVector(
                transform.from_frame_id,
                tuple(float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"),
                "polar",
            )
        )
        mass_amu = float(row["mass_amu"])
        output: dict[str, object] = dict(row)
        output["frame_id"] = transform.to_frame_id
        for axis, value in zip("xyz", position.coordinates_mm):
            output[f"position_{axis}_mm"] = value
        for axis, value in zip("xyz", velocity.components):
            output[f"velocity_{axis}_m_s"] = value
        transformed_energy = kinetic_energy_ev(
            mass_amu, *velocity.components
        )
        if not math.isclose(
            transformed_energy,
            float(row["kinetic_energy_eV"]),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"particle {particle_id} kinetic energy changed under rigid rotation"
            )
        output["kinetic_energy_eV"] = transformed_energy
        transformed_rows.append(output)
    return transformed_rows


def _derived_solver_rows(
    canonical_rows: Sequence[Mapping[str, str]],
) -> tuple[list[list[str]], list[dict[str, object]]]:
    ion_rows: list[list[str]] = []
    row_map_rows: list[dict[str, object]] = []
    for solver_row, state in enumerate(canonical_rows, start=1):
        velocity = tuple(float(state[f"velocity_{axis}_m_s"]) for axis in "xyz")
        azimuth_deg, elevation_deg = encode_simion_accelerator_velocity(velocity)
        values = (
            float(state["instrument_time_us"]),
            float(state["mass_amu"]),
            int(state["charge_state"]),
            float(state["position_x_mm"]),
            float(state["position_y_mm"]),
            float(state["position_z_mm"]),
            azimuth_deg,
            elevation_deg,
            float(state["kinetic_energy_eV"]),
            1,
            3,
        )
        ion_rows.append(
            [
                str(value) if isinstance(value, int) else format(value, ".17g")
                for value in values
            ]
        )
        row_map_rows.append(
            {
                "solver_row_index": solver_row,
                "particle_id": int(state["particle_id"]),
                "instrument_time_us": state["instrument_time_us"],
                "lineage_age_us": state["lineage_age_us"],
                "particle_age_us": state["particle_age_us"],
                "solver_birth_time_us": state["instrument_time_us"],
                "azimuth_deg": format(azimuth_deg, ".17g"),
                "elevation_deg": format(elevation_deg, ".17g"),
            }
        )
    return ion_rows, row_map_rows


def _write_row_map(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=ROW_MAP_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_ion11(path: Path, rows: Sequence[Sequence[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)


def _validate_solver_projection(
    canonical_path: Path,
    ion_path: Path,
    row_map_path: Path,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    report = validate_component_particle_state_csv(canonical_path)
    canonical_rows = _read_exact_csv(
        canonical_path, csv_columns(), "canonical component state"
    )
    if {row["frame_id"] for row in canonical_rows} != {
        EXPECTED_DOWNSTREAM_FRAME_ID
    }:
        raise ValueError("canonical source frame must be oatof_global")
    row_map_rows = _read_exact_csv(row_map_path, ROW_MAP_COLUMNS, "row map")
    with ion_path.open("r", encoding="utf-8-sig", newline="") as handle:
        ion_rows = list(csv.reader(handle))
    if len(ion_rows) != len(canonical_rows):
        raise ValueError("canonical and ION particle counts differ")
    if any(len(row) != 11 for row in ion_rows):
        raise ValueError("every ION row must contain exactly 11 columns")

    ordered_solver_identity_map(canonical_rows, row_map_rows)
    for state, mapping, ion in zip(canonical_rows, row_map_rows, ion_rows):
        for field in (
            "instrument_time_us",
            "lineage_age_us",
            "particle_age_us",
        ):
            if not math.isclose(
                float(mapping[field]),
                float(state[field]),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(f"row-map clock differs from canonical {field}")
        if not math.isclose(
            float(mapping["solver_birth_time_us"]),
            float(state["instrument_time_us"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "row-map solver birth time differs from shared instrument time"
            )
        if not math.isclose(
            float(ion[0]),
            float(state["instrument_time_us"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("ION birth time differs from shared instrument time")
        expected_fields = (
            state["mass_amu"],
            state["charge_state"],
            state["position_x_mm"],
            state["position_y_mm"],
            state["position_z_mm"],
            state["kinetic_energy_eV"],
        )
        ion_fields = (ion[1], ion[2], ion[3], ion[4], ion[5], ion[8])
        if any(
            not math.isclose(
                float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12
            )
            for actual, expected in zip(ion_fields, expected_fields)
        ):
            raise ValueError("ION physical state differs from canonical state")
        if ion[9:] != ["1", "3"]:
            raise ValueError("ION row uses an unexpected CWF or instance")
        validate_ion_velocity_adapter(state, mapping, ion)
    return report, canonical_rows


def _require_distinct_paths(inputs: Sequence[Path], outputs: Sequence[Path]) -> None:
    input_paths = {path.resolve() for path in inputs}
    output_paths = [path.resolve() for path in outputs]
    if len(output_paths) != len(set(output_paths)):
        raise ValueError("bundle output paths must be distinct")
    if input_paths.intersection(output_paths):
        raise ValueError("bundle outputs must not overwrite bundle inputs")


def render_oatof_simion_inputs(
    source_path: Path,
    canonical_output_path: Path,
    ion_output_path: Path,
    row_map_output_path: Path,
    metadata_output_path: Path,
) -> dict[str, Any]:
    """Render and validate canonical oatof_global state as ION11 and row-map."""
    outputs = [
        canonical_output_path,
        ion_output_path,
        row_map_output_path,
        metadata_output_path,
    ]
    _require_distinct_paths([source_path], outputs)
    if not source_path.is_file():
        raise ValueError("canonical oaTOF source must be an existing file")
    validate_component_particle_state_csv(source_path)
    source_rows = _read_exact_csv(
        source_path, csv_columns(), "canonical oaTOF source"
    )
    if {row["frame_id"] for row in source_rows} != {
        EXPECTED_DOWNSTREAM_FRAME_ID
    }:
        raise ValueError("canonical source frame must be oatof_global")

    with tempfile.TemporaryDirectory(prefix="oatof-simion-input-") as temporary:
        staging = Path(temporary)
        canonical_path = staging / "canonical_component_state.csv"
        ion_path = staging / "particles.ion"
        row_map_path = staging / "row_map.csv"

        canonical_path.write_bytes(source_path.read_bytes())
        ion_rows, row_map_rows = _derived_solver_rows(source_rows)
        _write_ion11(ion_path, ion_rows)
        _write_row_map(row_map_path, row_map_rows)
        validation, canonical_rows = _validate_solver_projection(
            canonical_path, ion_path, row_map_path
        )

        for staged, destination in (
            (canonical_path, canonical_output_path),
            (ion_path, ion_output_path),
            (row_map_path, row_map_output_path),
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(staged.read_bytes())

    metadata = {
        "schema_version": 1,
        "role": "oatof_simion_input_bundle",
        "status": "PASS",
        "particles": len(canonical_rows),
        "source": _reference(source_path),
        "coordinate_frame_id": EXPECTED_DOWNSTREAM_FRAME_ID,
        "clock": {"solver_clock": "instrument_time"},
        "outputs": {
            "canonical_handoff_csv": _reference(canonical_output_path),
            "oatof_ion": _reference(ion_output_path),
            "row_map_csv": _reference(row_map_output_path),
        },
        "validation": {
            "canonical_state": validation,
            "one_to_one_particle_identity": "PASS",
            "kinetic_energy_consistency": "PASS",
            "simion_velocity_decode_round_trip": "PASS",
        },
    }
    metadata_output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_output_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def publish_family_source_bundle(
    handoff_contract_path: Path,
    resolved_connection_path: Path,
    state_path: Path,
    source_path: Path,
    canonical_output_path: Path,
    ion_output_path: Path,
    row_map_output_path: Path,
    metadata_output_path: Path,
) -> dict[str, Any]:
    """Publish and validate the canonical, ION11, row-map, and metadata bundle."""
    from common.multipole.publish_three_mode_binding import publish_handoff

    inputs = [
        handoff_contract_path,
        resolved_connection_path,
        state_path,
        source_path,
    ]
    outputs = [
        canonical_output_path,
        ion_output_path,
        row_map_output_path,
        metadata_output_path,
    ]
    _require_distinct_paths(inputs, outputs)
    if any(not path.is_file() for path in inputs):
        raise ValueError("every family source bundle input must be an existing file")

    handoff_contract = _load_json_object(
        handoff_contract_path, "handoff contract"
    )
    resolved = _load_json_object(resolved_connection_path, "resolved connection")
    transform = _resolved_transform(resolved)

    with tempfile.TemporaryDirectory(prefix="family-source-bundle-") as temporary:
        staging = Path(temporary)
        upstream_path = staging / "upstream_component_state.csv"
        transformed_source_path = staging / "transformed_component_state.csv"
        canonical_path = staging / "canonical_component_state.csv"
        ion_path = staging / "particles.ion"
        row_map_path = staging / "row_map.csv"
        adapter_metadata_path = staging / "adapter_metadata.json"

        publish_handoff(
            state_path,
            source_path,
            upstream_path,
            contract=handoff_contract,
        )
        upstream_rows = _read_exact_csv(
            upstream_path, csv_columns(), "upstream component state"
        )
        transformed_rows = _transform_canonical_rows(upstream_rows, transform)
        write_component_particle_state_csv(
            transformed_source_path, transformed_rows
        )
        adapter_metadata = render_oatof_simion_inputs(
            transformed_source_path,
            canonical_path,
            ion_path,
            row_map_path,
            adapter_metadata_path,
        )
        canonical_rows = _read_exact_csv(
            canonical_path, csv_columns(), "canonical component state"
        )

        staged_outputs = (
            (canonical_path, canonical_output_path),
            (ion_path, ion_output_path),
            (row_map_path, row_map_output_path),
        )
        for staged, destination in staged_outputs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(staged.read_bytes())

    metadata = {
        "schema_version": 1,
        "role": "rf_multipole_oatof_family_source_bundle",
        "status": "PASS",
        "particles": len(canonical_rows),
        "inputs": {
            "handoff_contract": _reference(handoff_contract_path),
            "resolved_connection": _reference(resolved_connection_path),
            "solver_state": _reference(state_path),
            "canonical_mother_source": _reference(source_path),
        },
        "transform": transform.to_contract(),
        "clock": {"solver_clock": "instrument_time"},
        "outputs": {
            "canonical_handoff_csv": _reference(canonical_output_path),
            "oatof_ion": _reference(ion_output_path),
            "row_map_csv": _reference(row_map_output_path),
        },
        "validation": {
            **adapter_metadata["validation"],
            "rendered_by": (
                "integrations.rf_multipole_ion_optics_to_single_reflection_"
                "oa_tof_mass_analyzer.analysis.publish_family_source_bundle"
            ),
        },
    }
    metadata_output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_output_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-contract", type=Path)
    parser.add_argument("--resolved-connection", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--canonical-output", required=True, type=Path)
    parser.add_argument("--ion-output", required=True, type=Path)
    parser.add_argument("--row-map-output", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path)
    args = parser.parse_args()
    family_inputs = (
        args.handoff_contract,
        args.resolved_connection,
        args.state,
    )
    if any(family_inputs) and not all(family_inputs):
        parser.error(
            "--handoff-contract, --resolved-connection, and --state must be "
            "provided together"
        )
    if all(family_inputs):
        metadata = publish_family_source_bundle(
            args.handoff_contract,
            args.resolved_connection,
            args.state,
            args.source,
            args.canonical_output,
            args.ion_output,
            args.row_map_output,
            args.metadata_output,
        )
        print(
            "FAMILY_SOURCE_BUNDLE=PASS "
            f"PARTICLES={metadata['particles']} "
            f"FRAME={EXPECTED_DOWNSTREAM_FRAME_ID}"
        )
    else:
        metadata = render_oatof_simion_inputs(
            args.source,
            args.canonical_output,
            args.ion_output,
            args.row_map_output,
            args.metadata_output,
        )
        print(
            "OATOF_SIMION_INPUT=PASS "
            f"PARTICLES={metadata['particles']} "
            f"FRAME={EXPECTED_DOWNSTREAM_FRAME_ID}"
        )


if __name__ == "__main__":
    main()
