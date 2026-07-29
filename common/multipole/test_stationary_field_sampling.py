"""Tests for solver-neutral multipole stationary-field sampling."""

from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any

from common.multipole.stationary_field_sampling import (
    FIELD_OUTPUT_COLUMNS,
    StationaryFieldContractError,
    compare_stationary_field_outputs,
    generate_stationary_field_sample_rows,
    load_stationary_field_output_csv,
    main,
)


def _resolved_design() -> dict[str, Any]:
    rods = []
    for index in range(6):
        angle = index * math.pi / 3
        rods.append(
            {
                "center_x_mm": 6.0 * math.cos(angle),
                "center_y_mm": 6.0 * math.sin(angle),
                "radius_mm": 2.0,
            }
        )
    return {
        "schema_version": 2,
        "role": "multipole_resolved_design_do_not_edit",
        "units": {"length": "mm"},
        "coordinate": {
            "coordinate_id": "multipole_canonical_xyz",
            "axial_axis": "+z",
        },
        "geometry_mm": {
            "inscribed_radius_r0": 4.0,
            "rod_z_min": 0.0,
            "rod_z_max": 10.0,
            "rod_array": {"rods": rods},
        },
        "interfaces_mm": {
            "entrance": {
                "release_plane_z_mm": -1.5,
                "aperture_plate_upstream_face_z_mm": -1.0,
                "aperture_plate_downstream_face_z_mm": -0.5,
                "connector_upstream_face_z_mm": -1.0,
                "connector_downstream_face_z_mm": -1.0,
            },
            "exit": {
                "aperture_plate_upstream_face_z_mm": 10.5,
                "aperture_plate_downstream_face_z_mm": 11.0,
                "aperture_crossing_plane_z_mm": 11.0,
                "connector_upstream_face_z_mm": 11.0,
                "connector_downstream_face_z_mm": 11.0,
                "handoff_plane_z_mm": 11.0,
                "census_plane_z_mm": 11.5,
            },
        },
    }


def _sampling_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "role": "multipole_stationary_field_sampling_plan",
        "coordinate_id": "multipole_canonical_xyz",
        "units": {
            "length": "mm",
            "potential": "V",
            "electric_field": "V/m",
        },
        "axial_sampling": {
            "uniform_range": "rod_span",
            "uniform_sample_count": 3,
            "named_plane_ids": [
                "canonical_handoff_plane",
                "source_release_plane",
                "rod_exit",
            ],
        },
        "cross_section_sampling": {
            "rod_inward_clear_radius_fractions": [0.0, 0.5, 0.9],
            "azimuth_count": 4,
        },
    }


def _field_rows(
    potential_scale: float = 1.0,
    field_scale: float = 1.0,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    points = (
        ("p0", "entrance_aperture_plate_downstream_face", 0.0, 0.0, 0.0),
        ("p1", "rod_span_uniform", 1.0, -1.0, 5.0),
    )
    for field_case in ("differential", "static"):
        case_scale = 1.0 if field_case == "differential" else 2.0
        for index, (point_id, region, x_mm, y_mm, z_mm) in enumerate(
            points, start=1
        ):
            rows.append(
                {
                    "sample_id": point_id,
                    "region": region,
                    "field_case": field_case,
                    "x_mm": str(x_mm),
                    "y_mm": str(y_mm),
                    "z_mm": str(z_mm),
                    "potential_V": str(
                        potential_scale * case_scale * index
                    ),
                    "Ex_V_per_m": str(field_scale * case_scale * index),
                    "Ey_V_per_m": str(
                        field_scale * case_scale * (index + 1)
                    ),
                    "Ez_V_per_m": str(
                        field_scale * case_scale * (index + 2)
                    ),
                }
            )
    return rows


class StationaryFieldSamplingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def _write_rows(
        self,
        name: str,
        rows: list[dict[str, str]],
        columns: tuple[str, ...] = FIELD_OUTPUT_COLUMNS,
    ) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_generation_is_deterministic_and_inside_clear_radius(self) -> None:
        first = generate_stationary_field_sample_rows(
            _resolved_design(), _sampling_plan()
        )
        second = generate_stationary_field_sample_rows(
            _resolved_design(), _sampling_plan()
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 6 * (1 + 4 + 4))
        self.assertEqual(tuple(first[0]), (
            "sample_id", "region", "x_mm", "y_mm", "z_mm"
        ))
        self.assertEqual(
            [row["region"] for row in first][::9],
            [
                "rod_span_uniform",
                "rod_span_uniform",
                "rod_span_uniform",
                "source_release_plane",
                "rod_exit",
                "canonical_handoff_plane",
            ],
        )
        self.assertEqual(len({str(row["sample_id"]) for row in first}), len(first))
        for row in first:
            self.assertLess(
                math.hypot(float(row["x_mm"]), float(row["y_mm"])), 4.0
            )

    def test_plan_rejects_unknown_alias_and_boundary_fraction(self) -> None:
        plan = _sampling_plan()
        plan["cross_section_sampling"]["radius_fractions"] = [0.0]
        with self.assertRaisesRegex(
            StationaryFieldContractError, "fields differ"
        ):
            generate_stationary_field_sample_rows(_resolved_design(), plan)
        plan = _sampling_plan()
        plan["cross_section_sampling"][
            "rod_inward_clear_radius_fractions"
        ] = [0.0, 1.0]
        with self.assertRaisesRegex(StationaryFieldContractError, r"\[0, 1\)"):
            generate_stationary_field_sample_rows(_resolved_design(), plan)

    def test_load_and_compare_valid_outputs(self) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows("reference.csv", _field_rows())
        )
        candidate = load_stationary_field_output_csv(
            self._write_rows(
                "candidate.csv",
                _field_rows(potential_scale=1.5, field_scale=2.0),
            )
        )
        result = compare_stationary_field_outputs(reference, candidate)
        self.assertEqual(result["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertFalse(result["acceptance_thresholds_applied"])
        self.assertEqual(result["total_sample_count"], 4)
        differential = result["field_cases"]["differential"]
        self.assertEqual(differential["sample_count"], 2)
        self.assertEqual(
            tuple(differential["regions"]),
            (
                "entrance_aperture_plate_downstream_face",
                "rod_span_uniform",
            ),
        )
        self.assertEqual(
            differential["regions"]["rod_span_uniform"]["sample_count"], 1
        )
        self.assertGreater(
            differential["potential"]["rms_absolute_difference_V"], 0
        )
        self.assertGreater(
            differential["field_vector"][
                "maximum_difference_norm_V_per_m"
            ],
            0,
        )
        for component in ("Ex", "Ey", "Ez"):
            self.assertGreater(
                differential["field_components"][component][
                    "rms_absolute_difference_V_per_m"
                ],
                0,
            )

    def test_load_rejects_missing_column(self) -> None:
        columns = tuple(
            column
            for column in FIELD_OUTPUT_COLUMNS
            if column != "Ez_V_per_m"
        )
        rows = [
            {key: value for key, value in row.items() if key in columns}
            for row in _field_rows()
        ]
        path = self._write_rows("missing.csv", rows, columns)
        with self.assertRaisesRegex(
            StationaryFieldContractError, "columns or column order"
        ):
            load_stationary_field_output_csv(path)

    def test_load_rejects_duplicate_id(self) -> None:
        rows = _field_rows()
        rows[1]["sample_id"] = rows[0]["sample_id"]
        rows[1]["field_case"] = rows[0]["field_case"]
        path = self._write_rows("duplicate.csv", rows)
        with self.assertRaisesRegex(
            StationaryFieldContractError, "must be unique"
        ):
            load_stationary_field_output_csv(path)

    def test_load_rejects_nan(self) -> None:
        rows = _field_rows()
        rows[0]["Ex_V_per_m"] = "NaN"
        path = self._write_rows("nan.csv", rows)
        with self.assertRaisesRegex(StationaryFieldContractError, "must be finite"):
            load_stationary_field_output_csv(path)

    def test_compare_rejects_coordinate_difference(self) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows("reference.csv", _field_rows())
        )
        rows = _field_rows()
        for row in rows:
            if row["sample_id"] == "p0":
                row["x_mm"] = "0.0000001"
        candidate = load_stationary_field_output_csv(
            self._write_rows("coordinate.csv", rows)
        )
        with self.assertRaisesRegex(
            StationaryFieldContractError, "coordinates differ"
        ):
            compare_stationary_field_outputs(reference, candidate)

    def test_near_zero_reference_normalization_is_null_not_infinite(
        self,
    ) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows(
                "near_zero.csv",
                _field_rows(potential_scale=1e-320, field_scale=1e-320),
            )
        )
        candidate = load_stationary_field_output_csv(
            self._write_rows("finite.csv", _field_rows())
        )
        result = compare_stationary_field_outputs(reference, candidate)
        differential = result["field_cases"]["differential"]
        self.assertIsNone(
            differential["potential"]["reference_normalized_rms"]
        )
        self.assertIsNone(
            differential["field_vector"]["reference_normalized_rms"]
        )
        for component in ("Ex", "Ey", "Ez"):
            self.assertIsNone(
                differential["field_components"][component][
                    "reference_normalized_rms"
                ]
            )

    def test_single_public_utility_boundary_generates_validates_and_compares(
        self,
    ) -> None:
        resolved_path = self.root / "resolved.json"
        plan_path = self.root / "plan.json"
        points_path = self.root / "points.csv"
        resolved_path.write_text(json.dumps(_resolved_design()), encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()), encoding="utf-8")
        self.assertEqual(
            main(
                [
                    "generate",
                    "--resolved-design",
                    str(resolved_path),
                    "--sampling-plan",
                    str(plan_path),
                    "--output",
                    str(points_path),
                ]
            ),
            0,
        )
        with points_path.open(encoding="utf-8", newline="") as handle:
            point_rows = list(csv.DictReader(handle))
        self.assertEqual(
            tuple(point_rows[0]),
            ("sample_id", "region", "x_mm", "y_mm", "z_mm"),
        )

        field_path = self._write_rows("field.csv", _field_rows())
        validation_path = self.root / "validation.json"
        self.assertEqual(
            main(
                [
                    "validate",
                    "--input",
                    str(field_path),
                    "--output",
                    str(validation_path),
                ]
            ),
            0,
        )
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertEqual(validation["point_count"], 2)
        self.assertEqual(validation["row_count"], 4)

        comparison_path = self.root / "comparison.json"
        self.assertEqual(
            main(
                [
                    "compare",
                    "--reference",
                    str(field_path),
                    "--candidate",
                    str(field_path),
                    "--output",
                    str(comparison_path),
                ]
            ),
            0,
        )
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        self.assertEqual(comparison["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")


if __name__ == "__main__":
    unittest.main()
