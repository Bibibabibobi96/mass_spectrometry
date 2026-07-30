import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.multipole.exit_state_plot import (
    load_exit_state,
    export_figure,
    prepare_scales,
    render_exit_state_figure,
)


COLUMNS = [
    "particle_id",
    "event",
    "status",
    "terminal_reason",
    "time_us",
    "elapsed_time_us",
    "rf_phase_rad",
    "axial_z_mm",
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_axial_m_s",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "kinetic_energy_eV",
    "radial_position_mm",
    "divergence_angle_deg",
    "max_rod_radius_mm",
]


def write_fixture(path: Path, *, offset: float = 0.0, bad: bool = False) -> None:
    rows = []
    for particle_id in range(1, 4):
        common = {
            "particle_id": particle_id,
            "terminal_reason": "none",
            "time_us": particle_id,
            "rf_phase_rad": 0.0,
            "axial_z_mm": 0.0,
            "velocity_axial_m_s": 2000.0,
            "velocity_x_m_s": 1.0,
            "velocity_y_m_s": 2.0,
            "max_rod_radius_mm": 0.5,
        }
        rows.append(
            common
            | {
                "event": "source",
                "status": "alive",
                "elapsed_time_us": 0.0,
                "transverse_x_mm": 0.0,
                "transverse_y_mm": 0.0,
                "kinetic_energy_eV": 2.0,
                "radial_position_mm": 0.0,
                "divergence_angle_deg": 0.0,
            }
        )
        rows.append(
            common
            | {
                "event": "handoff",
                "status": "transmitted",
                "elapsed_time_us": 40.0 + particle_id + offset,
                "transverse_x_mm": (
                    float("nan") if bad and particle_id == 1 else 0.1 * particle_id + offset
                ),
                "transverse_y_mm": -0.05 * particle_id,
                "kinetic_energy_eV": 2.0 + 0.1 * particle_id + offset,
                "radial_position_mm": 0.1 * particle_id + offset,
                "divergence_angle_deg": 1.0 * particle_id + offset,
            }
        )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


class ExitStatePlotTests(unittest.TestCase):
    def test_shared_scales_and_fixed_bins_cover_both_series(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path, second_path = root / "a.csv", root / "b.csv"
            write_fixture(first_path)
            write_fixture(second_path, offset=2.0)
            states = [load_exit_state(first_path, "quad"), load_exit_state(second_path, "oct")]
            scales = prepare_scales(states, bin_count=12)
            self.assertEqual(len(scales["histogram_edges"]["kinetic_energy_eV"]), 13)
            self.assertLess(scales["transverse_mm"][0], -2.0)
            self.assertGreater(scales["transverse_mm"][1], 2.0)
            figure, axes = render_exit_state_figure(states, scales, "comparison")
            try:
                self.assertEqual(tuple(axes[0, 0].get_xlim()), scales["transverse_mm"])
                self.assertEqual(tuple(axes[0, 0].get_ylim()), scales["transverse_mm"])
                self.assertIn("(mm)", axes[0, 0].get_xlabel())
                self.assertIn("(deg)", axes[0, 2].get_xlabel())
                self.assertIn("(eV)", axes[1, 0].get_xlabel())
            finally:
                import matplotlib.pyplot as plt

                plt.close(figure)

    def test_headless_export_records_selection_hash_and_bins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "state.csv"
            output = root / "plot.png"
            manifest = root / "plot.json"
            write_fixture(source)
            state = load_exit_state(source, "quadrupole")
            document = export_figure(
                [state],
                output,
                manifest,
                "diagnostic",
                "regular single-run exit-state diagnostic",
            )
            self.assertTrue(output.is_file())
            self.assertEqual(document["series"][0]["selection"]["event"], "handoff")
            self.assertEqual(document["series"][0]["selection"]["selected_particle_count"], 3)
            self.assertEqual(document["figure"]["dpi"], 200)
            self.assertEqual(len(document["shared_scales"]["histogram_edges"]["elapsed_time_us"]), 25)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), document)

    def test_nan_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.csv"
            write_fixture(source, bad=True)
            with self.assertRaisesRegex(ValueError, "NaN/Inf"):
                load_exit_state(source, "bad")

    def test_missing_column_and_empty_table_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.csv"
            missing.write_text("particle_id,event,status\n1,source,alive\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing columns"):
                load_exit_state(missing, "missing")
            empty = root / "empty.csv"
            empty.write_text(",".join(COLUMNS) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                load_exit_state(empty, "empty")

    def test_duplicate_or_unknown_selected_particle_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.csv"
            write_fixture(duplicate)
            with duplicate.open("a", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=COLUMNS)
                writer.writerow(
                    {
                        "particle_id": 1,
                        "event": "handoff",
                        "status": "transmitted",
                        "terminal_reason": "none",
                        "time_us": 1.0,
                        "elapsed_time_us": 41.0,
                        "rf_phase_rad": 0.0,
                        "axial_z_mm": 0.0,
                        "transverse_x_mm": 0.1,
                        "transverse_y_mm": 0.0,
                        "velocity_axial_m_s": 2000.0,
                        "velocity_x_m_s": 1.0,
                        "velocity_y_m_s": 2.0,
                        "kinetic_energy_eV": 2.0,
                        "radial_position_mm": 0.1,
                        "divergence_angle_deg": 1.0,
                        "max_rod_radius_mm": 0.5,
                    }
                )
            with self.assertRaisesRegex(ValueError, "duplicated"):
                load_exit_state(duplicate, "duplicate")

            unknown = root / "unknown.csv"
            write_fixture(unknown)
            with unknown.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                if row["event"] == "handoff" and row["particle_id"] == "1":
                    row["particle_id"] = "999"
                    break
            with unknown.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "do not belong"):
                load_exit_state(unknown, "unknown")


if __name__ == "__main__":
    unittest.main()
