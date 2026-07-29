"""Solver-neutral stationary-field sampling and diagnostic comparison.

The module defines one narrow CSV boundary shared by multipole field solvers.
It neither launches a solver nor applies project acceptance thresholds.
Coordinates use the resolved design's canonical frame and millimetres; field
outputs use volts and volts per metre.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


FIELD_CASES = ("differential", "static")
SAMPLE_COLUMNS = (
    "sample_id",
    "region",
    "x_mm",
    "y_mm",
    "z_mm",
)
FIELD_OUTPUT_COLUMNS = (
    "sample_id",
    "region",
    "field_case",
    "x_mm",
    "y_mm",
    "z_mm",
    "potential_V",
    "Ex_V_per_m",
    "Ey_V_per_m",
    "Ez_V_per_m",
)

_PLAN_KEYS = {
    "schema_version", "role", "coordinate_id", "units",
    "axial_sampling", "cross_section_sampling",
}
_PLAN_UNITS = {
    "length": "mm",
    "potential": "V",
    "electric_field": "V/m",
}
_AXIAL_KEYS = {"uniform_range", "uniform_sample_count", "named_plane_ids"}
_CROSS_SECTION_KEYS = {
    "rod_inward_clear_radius_fractions", "azimuth_count",
}
_NAMED_PLANE_PATHS = {
    "source_release_plane": "interfaces_mm.entrance.release_plane_z_mm",
    "entrance_aperture_plate_upstream_face":
        "interfaces_mm.entrance.aperture_plate_upstream_face_z_mm",
    "entrance_aperture_plate_downstream_face":
        "interfaces_mm.entrance.aperture_plate_downstream_face_z_mm",
    "entrance_connector_upstream_face":
        "interfaces_mm.entrance.connector_upstream_face_z_mm",
    "entrance_connector_downstream_face":
        "interfaces_mm.entrance.connector_downstream_face_z_mm",
    "rod_entrance": "geometry_mm.rod_z_min",
    "rod_exit": "geometry_mm.rod_z_max",
    "exit_aperture_plate_upstream_face":
        "interfaces_mm.exit.aperture_plate_upstream_face_z_mm",
    "exit_aperture_plate_downstream_face":
        "interfaces_mm.exit.aperture_plate_downstream_face_z_mm",
    "exit_aperture_crossing_plane":
        "interfaces_mm.exit.aperture_crossing_plane_z_mm",
    "exit_connector_upstream_face":
        "interfaces_mm.exit.connector_upstream_face_z_mm",
    "exit_connector_downstream_face":
        "interfaces_mm.exit.connector_downstream_face_z_mm",
    "canonical_handoff_plane": "interfaces_mm.exit.handoff_plane_z_mm",
    "near_interface_census_plane": "interfaces_mm.exit.census_plane_z_mm",
}


class StationaryFieldContractError(ValueError):
    """Raised when a sampling plan or field CSV violates the public contract."""


@dataclass(frozen=True)
class StationaryFieldRecord:
    """One finite stationary-field observation in canonical multipole units."""

    sample_id: str
    region: str
    field_case: str
    x_mm: float
    y_mm: float
    z_mm: float
    potential_V: float
    Ex_V_per_m: float
    Ey_V_per_m: float
    Ez_V_per_m: float


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StationaryFieldContractError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise StationaryFieldContractError(
            f"{label} fields differ; missing={missing}, unknown={unknown}"
        )


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise StationaryFieldContractError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise StationaryFieldContractError(
            f"{label} must be a finite number"
        ) from error
    if not math.isfinite(number):
        raise StationaryFieldContractError(f"{label} must be finite")
    return number


def _positive_integer(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StationaryFieldContractError(
            f"{label} must be an integer greater than or equal to {minimum}"
        )
    return value


def _nested_number(
    document: Mapping[str, Any], path: str, label: str
) -> float:
    value: Any = document
    for component in path.split("."):
        value = _require_mapping(value, label).get(component)
    return _finite_number(value, label)


def _validate_resolved_design(
    resolved_design: Mapping[str, Any],
) -> tuple[Mapping[str, Any], float]:
    if resolved_design.get("schema_version") != 2:
        raise StationaryFieldContractError(
            "resolved design schema_version must be 2"
        )
    if resolved_design.get("role") != "multipole_resolved_design_do_not_edit":
        raise StationaryFieldContractError(
            "resolved design role is not canonical multipole resolved design"
        )
    units = _require_mapping(resolved_design.get("units"), "resolved units")
    if units.get("length") != "mm":
        raise StationaryFieldContractError(
            "resolved design length unit must be mm"
        )
    coordinate = _require_mapping(
        resolved_design.get("coordinate"), "resolved coordinate"
    )
    if (
        not isinstance(coordinate.get("coordinate_id"), str)
        or not coordinate["coordinate_id"]
        or coordinate.get("axial_axis") != "+z"
    ):
        raise StationaryFieldContractError(
            "resolved coordinate must provide coordinate_id and +z axial_axis"
        )
    geometry = _require_mapping(
        resolved_design.get("geometry_mm"), "resolved geometry_mm"
    )
    rod_array = _require_mapping(
        geometry.get("rod_array"), "resolved geometry_mm.rod_array"
    )
    rods = rod_array.get("rods")
    if not isinstance(rods, list) or not rods:
        raise StationaryFieldContractError(
            "resolved geometry must contain a nonempty round-rod array"
        )
    inward_radii: list[float] = []
    for index, rod_value in enumerate(rods):
        rod = _require_mapping(rod_value, f"rod {index}")
        center_x = _finite_number(rod.get("center_x_mm"), "rod center_x_mm")
        center_y = _finite_number(rod.get("center_y_mm"), "rod center_y_mm")
        radius = _finite_number(rod.get("radius_mm"), "rod radius_mm")
        inward_radius = math.hypot(center_x, center_y) - radius
        if radius <= 0 or inward_radius <= 0:
            raise StationaryFieldContractError(
                "each rod must have positive radius and inward clear radius"
            )
        inward_radii.append(inward_radius)
    clear_radius = min(inward_radii)
    r0 = _finite_number(
        geometry.get("inscribed_radius_r0"),
        "geometry_mm.inscribed_radius_r0",
    )
    if not math.isclose(clear_radius, r0, rel_tol=1e-12, abs_tol=1e-12):
        raise StationaryFieldContractError(
            "rod inward clear radius differs from inscribed_radius_r0"
        )
    return coordinate, clear_radius


def _validate_sampling_plan(
    sampling_plan: Mapping[str, Any],
    coordinate_id: str,
) -> tuple[int, tuple[str, ...], tuple[float, ...], int]:
    _require_exact_keys(sampling_plan, _PLAN_KEYS, "sampling plan")
    if (
        sampling_plan.get("schema_version") != 1
        or sampling_plan.get("role")
        != "multipole_stationary_field_sampling_plan"
    ):
        raise StationaryFieldContractError(
            "sampling plan schema_version or role differs"
        )
    if sampling_plan.get("coordinate_id") != coordinate_id:
        raise StationaryFieldContractError(
            "sampling plan coordinate_id differs from resolved design"
        )
    units = _require_mapping(sampling_plan.get("units"), "sampling plan units")
    _require_exact_keys(units, set(_PLAN_UNITS), "sampling plan units")
    if dict(units) != _PLAN_UNITS:
        raise StationaryFieldContractError(
            "sampling plan units must be mm, V, and V/m"
        )
    axial = _require_mapping(
        sampling_plan.get("axial_sampling"), "axial_sampling"
    )
    _require_exact_keys(axial, _AXIAL_KEYS, "axial_sampling")
    if axial.get("uniform_range") != "rod_span":
        raise StationaryFieldContractError(
            "axial_sampling.uniform_range must be rod_span"
        )
    uniform_count = _positive_integer(
        axial.get("uniform_sample_count"),
        "axial_sampling.uniform_sample_count",
        2,
    )
    plane_values = axial.get("named_plane_ids")
    if not isinstance(plane_values, list) or not plane_values:
        raise StationaryFieldContractError(
            "axial_sampling.named_plane_ids must be a nonempty list"
        )
    if any(not isinstance(value, str) for value in plane_values):
        raise StationaryFieldContractError(
            "each named_plane_ids value must be a string"
        )
    plane_ids = tuple(plane_values)
    if len(set(plane_ids)) != len(plane_ids):
        raise StationaryFieldContractError(
            "axial_sampling.named_plane_ids contains duplicates"
        )
    unknown_planes = sorted(set(plane_ids) - set(_NAMED_PLANE_PATHS))
    if unknown_planes:
        raise StationaryFieldContractError(
            f"unknown named_plane_ids values: {unknown_planes}"
        )
    cross_section = _require_mapping(
        sampling_plan.get("cross_section_sampling"),
        "cross_section_sampling",
    )
    _require_exact_keys(
        cross_section, _CROSS_SECTION_KEYS, "cross_section_sampling"
    )
    fraction_values = cross_section.get(
        "rod_inward_clear_radius_fractions"
    )
    if not isinstance(fraction_values, list) or not fraction_values:
        raise StationaryFieldContractError(
            "rod_inward_clear_radius_fractions must be a nonempty list"
        )
    fractions = tuple(
        _finite_number(value, "rod inward clear radius fraction")
        for value in fraction_values
    )
    if any(value < 0 or value >= 1 for value in fractions):
        raise StationaryFieldContractError(
            "rod inward clear radius fractions must be in [0, 1)"
        )
    if any(
        right <= left for left, right in zip(fractions, fractions[1:])
    ):
        raise StationaryFieldContractError(
            "rod inward clear radius fractions must be strictly increasing"
        )
    azimuth_count = _positive_integer(
        cross_section.get("azimuth_count"),
        "cross_section_sampling.azimuth_count",
        1,
    )
    ordered_planes = tuple(
        plane_id
        for plane_id in _NAMED_PLANE_PATHS
        if plane_id in set(plane_ids)
    )
    return uniform_count, ordered_planes, fractions, azimuth_count


def _axial_samples(
    resolved_design: Mapping[str, Any],
    uniform_count: int,
    plane_ids: Sequence[str],
) -> list[tuple[str, int, float]]:
    geometry = _require_mapping(
        resolved_design.get("geometry_mm"), "resolved geometry_mm"
    )
    z_min = _finite_number(geometry.get("rod_z_min"), "rod_z_min")
    z_max = _finite_number(geometry.get("rod_z_max"), "rod_z_max")
    if z_max <= z_min:
        raise StationaryFieldContractError("rod_z_max must exceed rod_z_min")
    values = [
        (
            "rod_span_uniform",
            index,
            z_min + (z_max - z_min) * index / (uniform_count - 1),
        )
        for index in range(uniform_count)
    ]
    for index, plane_id in enumerate(plane_ids):
        values.append(
            (
                plane_id,
                index,
                _nested_number(
                    resolved_design,
                    _NAMED_PLANE_PATHS[plane_id],
                    plane_id,
                ),
            )
        )
    return values


def generate_stationary_field_sample_rows(
    resolved_design: Mapping[str, Any],
    sampling_plan: Mapping[str, Any],
) -> list[dict[str, str | float]]:
    """Generate deterministic field-case sampling rows in the canonical frame.

    The returned five-column rows contain globally unique spatial
    ``sample_id`` values, positions in mm, and no solver settings.  A solver
    exporter evaluates both field cases at these same points.  Every
    transverse point is checked to lie strictly inside the minimum inward
    surface radius of the resolved round-rod array.
    """

    resolved = _require_mapping(resolved_design, "resolved design")
    plan = _require_mapping(sampling_plan, "sampling plan")
    coordinate, clear_radius = _validate_resolved_design(resolved)
    (
        uniform_count,
        plane_ids,
        fractions,
        azimuth_count,
    ) = _validate_sampling_plan(plan, str(coordinate["coordinate_id"]))
    axial_samples = _axial_samples(resolved, uniform_count, plane_ids)
    rows: list[dict[str, str | float]] = []
    for region, axial_index, z_mm in axial_samples:
        for radial_index, fraction in enumerate(fractions):
            count = 1 if fraction == 0 else azimuth_count
            for azimuth_index in range(count):
                angle = 2 * math.pi * azimuth_index / count
                radius = clear_radius * fraction
                x_mm = radius * math.cos(angle)
                y_mm = radius * math.sin(angle)
                if not math.hypot(x_mm, y_mm) < clear_radius:
                    raise StationaryFieldContractError(
                        "generated point is not strictly inside the rod "
                        "inward clear radius"
                    )
                sample_id = (
                    f"{region}__z{axial_index:04d}"
                    f"__r{radial_index:03d}__a{azimuth_index:03d}"
                )
                rows.append(
                    {
                        "sample_id": sample_id,
                        "region": region,
                        "x_mm": x_mm,
                        "y_mm": y_mm,
                        "z_mm": z_mm,
                    }
                )
    return rows


def write_stationary_field_sample_csv(
    rows: Sequence[Mapping[str, str | float]], path: Path
) -> None:
    """Write generated sampling rows with the canonical column order."""

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_COLUMNS)
        writer.writeheader()
        for row in rows:
            if set(row) != set(SAMPLE_COLUMNS):
                raise StationaryFieldContractError(
                    "sample row fields differ from the canonical columns"
                )
            writer.writerow(row)


def _record_from_row(
    row: Mapping[str, str], row_number: int
) -> StationaryFieldRecord:
    sample_id = row["sample_id"]
    region = row["region"]
    field_case = row["field_case"]
    if not sample_id or sample_id.strip() != sample_id:
        raise StationaryFieldContractError(
            f"row {row_number} sample_id must be nonempty and trimmed"
        )
    if not region or region.strip() != region:
        raise StationaryFieldContractError(
            f"row {row_number} region must be nonempty and trimmed"
        )
    if field_case not in FIELD_CASES:
        raise StationaryFieldContractError(
            f"row {row_number} field_case must be differential or static"
        )
    values = {
        name: _finite_number(row[name], f"row {row_number} {name}")
        for name in FIELD_OUTPUT_COLUMNS[3:]
    }
    return StationaryFieldRecord(
        sample_id=sample_id,
        region=region,
        field_case=field_case,
        **values,
    )


def _validate_paired_field_cases(
    records: Sequence[StationaryFieldRecord],
) -> None:
    by_case: dict[str, dict[str, StationaryFieldRecord]] = {
        field_case: {} for field_case in FIELD_CASES
    }
    for record in records:
        if record.sample_id in by_case[record.field_case]:
            raise StationaryFieldContractError(
                "each field_case must contain unique sample_id values"
            )
        by_case[record.field_case][record.sample_id] = record
    point_sets = [set(by_case[field_case]) for field_case in FIELD_CASES]
    if not point_sets[0] or point_sets[0] != point_sets[1]:
        raise StationaryFieldContractError(
            "differential and static cases must contain the same sample points"
        )
    for sample_id in sorted(point_sets[0]):
        differential = by_case["differential"][sample_id]
        static = by_case["static"][sample_id]
        if differential.region != static.region or (
            differential.x_mm,
            differential.y_mm,
            differential.z_mm,
        ) != (static.x_mm, static.y_mm, static.z_mm):
            raise StationaryFieldContractError(
                "field cases differ in region or coordinates for "
                f"sample point {sample_id}"
            )


def load_stationary_field_output_csv(
    path: Path,
) -> tuple[StationaryFieldRecord, ...]:
    """Load and strictly validate a complete two-case field-output CSV.

    Required columns are exact.  ``(field_case, sample_id)`` is the unique
    output key; both cases must contain the same spatial IDs, regions, and
    coordinates.  All potential and electric-field values must be finite.
    """

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELD_OUTPUT_COLUMNS:
            raise StationaryFieldContractError(
                "field output columns or column order differ from the "
                "canonical contract"
            )
        records = tuple(
            _record_from_row(row, row_number)
            for row_number, row in enumerate(reader, start=2)
        )
    if not records:
        raise StationaryFieldContractError("field output CSV is empty")
    keys = [(record.field_case, record.sample_id) for record in records]
    if len(set(keys)) != len(keys):
        raise StationaryFieldContractError(
            "field output (field_case, sample_id) keys must be unique"
        )
    _validate_paired_field_cases(records)
    return records


def _safe_normalized_rms(
    difference_rms: float, reference_rms: float
) -> float | None:
    if reference_rms <= 0:
        return None
    ratio = difference_rms / reference_rms
    return ratio if math.isfinite(ratio) else None


def _scalar_metrics(
    reference: Sequence[float],
    candidate: Sequence[float],
    unit_suffix: str,
) -> dict[str, float | None]:
    differences = [
        candidate_value - reference_value
        for reference_value, candidate_value in zip(reference, candidate)
    ]
    difference_rms = math.sqrt(
        math.fsum(value * value for value in differences) / len(differences)
    )
    reference_rms = math.sqrt(
        math.fsum(value * value for value in reference) / len(reference)
    )
    return {
        f"rms_absolute_difference_{unit_suffix}": difference_rms,
        f"maximum_absolute_difference_{unit_suffix}": max(
            abs(value) for value in differences
        ),
        f"reference_rms_{unit_suffix}": reference_rms,
        "reference_normalized_rms": _safe_normalized_rms(
            difference_rms, reference_rms
        ),
    }


def _vector_metrics(
    reference: Sequence[tuple[float, float, float]],
    candidate: Sequence[tuple[float, float, float]],
) -> dict[str, float | None]:
    difference_norms = [
        math.sqrt(
            math.fsum(
                (candidate_component - reference_component) ** 2
                for reference_component, candidate_component in zip(
                    reference_vector, candidate_vector
                )
            )
        )
        for reference_vector, candidate_vector in zip(reference, candidate)
    ]
    reference_norms = [
        math.sqrt(math.fsum(component * component for component in vector))
        for vector in reference
    ]
    difference_rms = math.sqrt(
        math.fsum(value * value for value in difference_norms)
        / len(difference_norms)
    )
    reference_rms = math.sqrt(
        math.fsum(value * value for value in reference_norms)
        / len(reference_norms)
    )
    return {
        "rms_difference_norm_V_per_m": difference_rms,
        "maximum_difference_norm_V_per_m": max(difference_norms),
        "reference_rms_norm_V_per_m": reference_rms,
        "reference_normalized_rms": _safe_normalized_rms(
            difference_rms, reference_rms
        ),
    }


def _field_case_metrics(
    reference_case: Sequence[StationaryFieldRecord],
    candidate_case: Sequence[StationaryFieldRecord],
) -> dict[str, Any]:
    """Calculate one field case without applying an acceptance threshold."""

    reference_vectors = [
        (record.Ex_V_per_m, record.Ey_V_per_m, record.Ez_V_per_m)
        for record in reference_case
    ]
    candidate_vectors = [
        (record.Ex_V_per_m, record.Ey_V_per_m, record.Ez_V_per_m)
        for record in candidate_case
    ]
    components: dict[str, Any] = {}
    for name in ("Ex", "Ey", "Ez"):
        attribute = f"{name}_V_per_m"
        components[name] = _scalar_metrics(
            [getattr(record, attribute) for record in reference_case],
            [getattr(record, attribute) for record in candidate_case],
            "V_per_m",
        )
    return {
        "sample_count": len(reference_case),
        "potential": _scalar_metrics(
            [record.potential_V for record in reference_case],
            [record.potential_V for record in candidate_case],
            "V",
        ),
        "field_vector": _vector_metrics(reference_vectors, candidate_vectors),
        "field_components": components,
    }


def compare_stationary_field_outputs(
    reference: Sequence[StationaryFieldRecord],
    candidate: Sequence[StationaryFieldRecord],
) -> dict[str, Any]:
    """Compare two outputs at exactly matching identities and coordinates.

    Metrics are reported independently for differential and static cases.
    The result is always diagnostic-only and applies no PASS threshold.
    """

    reference_by_id = {
        (record.field_case, record.sample_id): record for record in reference
    }
    candidate_by_id = {
        (record.field_case, record.sample_id): record for record in candidate
    }
    if len(reference_by_id) != len(reference) or len(candidate_by_id) != len(
        candidate
    ):
        raise StationaryFieldContractError(
            "comparison inputs contain duplicate (field_case, sample_id) keys"
        )
    if set(reference_by_id) != set(candidate_by_id):
        raise StationaryFieldContractError(
            "comparison inputs contain different (field_case, sample_id) sets"
        )
    for key in sorted(reference_by_id):
        reference_record = reference_by_id[key]
        candidate_record = candidate_by_id[key]
        if (
            reference_record.field_case != candidate_record.field_case
            or reference_record.region != candidate_record.region
        ):
            raise StationaryFieldContractError(
                f"comparison identity differs for {key}"
            )
        reference_coordinates = (
            reference_record.x_mm,
            reference_record.y_mm,
            reference_record.z_mm,
        )
        candidate_coordinates = (
            candidate_record.x_mm,
            candidate_record.y_mm,
            candidate_record.z_mm,
        )
        if reference_coordinates != candidate_coordinates:
            raise StationaryFieldContractError(
                f"comparison coordinates differ for {key}"
            )
    field_cases: dict[str, Any] = {}
    for field_case in FIELD_CASES:
        ids = sorted(
            key for key in reference_by_id if key[0] == field_case
        )
        if not ids:
            raise StationaryFieldContractError(
                f"comparison input has no {field_case} records"
            )
        reference_case = [reference_by_id[key] for key in ids]
        candidate_case = [candidate_by_id[key] for key in ids]
        regions = sorted({record.region for record in reference_case})
        region_metrics = {}
        for region in regions:
            reference_region = [
                record for record in reference_case if record.region == region
            ]
            candidate_region = [
                record for record in candidate_case if record.region == region
            ]
            region_metrics[region] = _field_case_metrics(
                reference_region, candidate_region
            )
        field_cases[field_case] = {
            **_field_case_metrics(reference_case, candidate_case),
            "regions": region_metrics,
        }
    return {
        "schema_version": 1,
        "role": "multipole_stationary_field_comparison",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "acceptance_thresholds_applied": False,
        "total_sample_count": len(reference),
        "field_cases": field_cases,
    }


def _write_json(document: Mapping[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise StationaryFieldContractError(
            f"{label} is not readable JSON: {path}"
        ) from error
    return _require_mapping(document, label)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, validate, or compare governed multipole field samples."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--resolved-design", type=Path, required=True)
    generate.add_argument("--sampling-plan", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Expose one solver-neutral utility boundary; this does not launch transport."""

    arguments = _build_parser().parse_args(argv)
    if arguments.command == "generate":
        rows = generate_stationary_field_sample_rows(
            _load_json_object(arguments.resolved_design, "resolved design"),
            _load_json_object(arguments.sampling_plan, "sampling plan"),
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        write_stationary_field_sample_csv(rows, arguments.output)
        return 0
    if arguments.command == "validate":
        records = load_stationary_field_output_csv(arguments.input)
        point_count = len({record.sample_id for record in records})
        _write_json(
            {
                "schema_version": 1,
                "role": "multipole_stationary_field_sample_validation",
                "status": "PASS",
                "field_cases": list(FIELD_CASES),
                "point_count": point_count,
                "row_count": len(records),
            },
            arguments.output,
        )
        return 0
    if arguments.command == "compare":
        comparison = compare_stationary_field_outputs(
            load_stationary_field_output_csv(arguments.reference),
            load_stationary_field_output_csv(arguments.candidate),
        )
        _write_json(comparison, arguments.output)
        return 0
    raise AssertionError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
