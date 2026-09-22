import csv
import math
import tempfile
import unittest
from pathlib import Path

from common.simion.field_comparison import (
    FieldComparisonError,
    compute_delta_field_rms,
    compute_field_residual_metrics,
    read_field_comparison_csv,
)


class FieldComparisonTests(unittest.TestCase):
    def _write(self, path: Path, rows: list[tuple[object, ...]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow((
                "name", "z_mm", "delta_potential_V", "delta_ex_V_per_mm",
                "delta_ey_V_per_mm", "delta_ez_V_per_mm",
            ))
            writer.writerows(rows)

    def test_reads_finite_rows_and_computes_complete_residual_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "comparison.csv"
            self._write(path, [("a", 1, 3, 4, 0, 0), ("b", 2, -1, 0, 0, 0)])
            rows = read_field_comparison_csv(
                path,
                required_columns=(column for column in ("name",)),
                finite_columns=(column for column in ("z_mm",)),
            )
            metrics = compute_field_residual_metrics(rows)
            self.assertEqual([row.numeric["z_mm"] for row in rows], [1.0, 2.0])
            self.assertEqual(metrics["sample_count"], 2)
            self.assertEqual(metrics["delta_potential_max_abs_V"], 3.0)
            self.assertEqual(metrics["delta_field_max_V_per_mm"], 4.0)
            self.assertAlmostEqual(metrics["delta_potential_rms_V"], math.sqrt(5.0))
            self.assertAlmostEqual(metrics["delta_field_rms_V_per_mm"], math.sqrt(8.0))
            self.assertEqual(
                compute_delta_field_rms(rows),
                math.sqrt((4.0 ** 2 + 0.0 ** 2 + 0.0 ** 2 + 0.0 ** 2 + 0.0 ** 2 + 0.0 ** 2) / 2),
            )

    def test_rejects_missing_columns_nonfinite_values_and_empty_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = root / "missing.csv"
            missing.write_text("name,delta_potential_V\na,1\n", encoding="utf-8")
            with self.assertRaisesRegex(FieldComparisonError, "columns differ"):
                read_field_comparison_csv(missing)

            nonfinite = root / "nonfinite.csv"
            self._write(nonfinite, [("a", 1, "nan", 0, 0, 0)])
            with self.assertRaisesRegex(FieldComparisonError, "must be finite"):
                read_field_comparison_csv(nonfinite)
            with self.assertRaisesRegex(FieldComparisonError, "empty"):
                compute_field_residual_metrics([])


if __name__ == "__main__":
    unittest.main()
