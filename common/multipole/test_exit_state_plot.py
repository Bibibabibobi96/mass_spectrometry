import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.multipole.exit_state_plot import (
    HISTOGRAMS,
    export_four_domain_figure,
    load_exit_state,
    export_figure,
    prepare_scales,
    prepare_shared_scale_contract,
    render_four_domain_comparison,
    render_exit_state_figure,
    validate_comparison_states,
    validate_shared_scale_contract,
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


def write_fixture(
    path: Path,
    *,
    offset: float = 0.0,
    bad: bool = False,
    source_count: int = 3,
    selected_count: int | None = None,
    plane_mm: float = 0.0,
) -> None:
    rows = []
    selected_count = source_count if selected_count is None else selected_count
    for particle_id in range(1, source_count + 1):
        common = {
            "particle_id": particle_id,
            "terminal_reason": "none",
            "time_us": particle_id,
            "rf_phase_rad": 0.0,
            "axial_z_mm": plane_mm,
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
        if particle_id <= selected_count:
            rows.append(
                common
                | {
                    "event": "handoff",
                    "status": "transmitted",
                    "elapsed_time_us": 40.0 + particle_id + offset,
                    "transverse_x_mm": (
                        float("nan")
                        if bad and particle_id == 1
                        else 0.1 * particle_id + offset
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
            self.assertEqual(scales["histogram_edges"]["radial_position_mm"][0], 0.0)
            self.assertEqual(scales["histogram_edges"]["divergence_angle_deg"][0], 0.0)
            self.assertEqual(scales["radial_vs_divergence"]["x"][0], 0.0)
            self.assertEqual(scales["radial_vs_divergence"]["y"][0], 0.0)
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

    def test_shared_scale_contract_roundtrip_and_subset_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path, second_path = root / "a.csv", root / "b.csv"
            write_fixture(first_path)
            write_fixture(second_path, offset=2.0)
            first = load_exit_state(first_path, "baseline")
            second = load_exit_state(second_path, "refined")
            contract = prepare_shared_scale_contract(
                [first, second], bin_count=12, require_paired_ids=True
            )
            loaded = json.loads(json.dumps(contract))
            self.assertEqual(loaded, contract)
            validate_shared_scale_contract(loaded, [second])
            figure, axes = render_four_domain_comparison(
                [second], loaded, "subset"
            )
            try:
                expected = tuple(
                    loaded["shared_scales"]["histogram_edges"][
                        "radial_position_mm"
                    ][::12]
                )
                self.assertEqual(tuple(axes[0, 0].get_xlim()), expected)
                self.assertEqual(len(figure.legends), 1)
                self.assertEqual(
                    figure.legends[0].get_texts()[0].get_text(),
                    "refined (N=3/3)",
                )
            finally:
                import matplotlib.pyplot as plt

                plt.close(figure)

    def test_four_domain_export_records_contract_and_semantic_styles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path, second_path = root / "a.csv", root / "b.csv"
            output, manifest = root / "comparison.png", root / "comparison.json"
            write_fixture(first_path)
            write_fixture(second_path, offset=0.2)
            states = [
                load_exit_state(first_path, "baseline"),
                load_exit_state(second_path, "refined"),
            ]
            contract = prepare_shared_scale_contract(states, bin_count=8)
            reversed_contract = prepare_shared_scale_contract(
                list(reversed(states)), bin_count=8
            )
            self.assertEqual(contract["style_map"], reversed_contract["style_map"])
            six_states = [
                replace(states[index % 2], label=f"series-{index}")
                for index in range(6)
            ]
            six_styles = prepare_shared_scale_contract(six_states)["style_map"]
            self.assertEqual(
                len(
                    {
                        (style["color"], style["linestyle"])
                        for style in six_styles.values()
                    }
                ),
                6,
            )
            document = export_four_domain_figure(
                list(reversed(states)),
                output,
                manifest,
                "comparison",
                "four-domain comparison",
                scale_contract=contract,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(
                document["layout"], "four_domain_fixed_bin_comparison"
            )
            self.assertEqual(
                document["shared_scales"], contract["shared_scales"]
            )
            self.assertEqual(document["comparison"], contract["comparison"])
            self.assertEqual(document["style_map"], contract["style_map"])
            self.assertNotEqual(
                contract["style_map"]["baseline"]["color"],
                contract["style_map"]["refined"]["color"],
            )
            self.assertNotEqual(
                (
                    contract["style_map"]["baseline"]["color"],
                    contract["style_map"]["baseline"]["linestyle"],
                ),
                (
                    contract["style_map"]["refined"]["color"],
                    contract["style_map"]["refined"]["linestyle"],
                ),
            )
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8")), document
            )

    def test_comparison_semantics_and_paired_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "state.csv"
            write_fixture(source)
            baseline = load_exit_state(source, "baseline")
            cases = (
                (
                    replace(baseline, label="event", event="rod_exit"),
                    False,
                    "events",
                ),
                (
                    replace(baseline, label="status", statuses=("alive",)),
                    False,
                    "statuses",
                ),
                (
                    replace(
                        baseline,
                        label="cohort",
                        source_particle_ids=("1", "2"),
                    ),
                    False,
                    "cohorts",
                ),
                (
                    replace(
                        baseline,
                        label="paired",
                        selected_particle_ids=("1", "2"),
                    ),
                    True,
                    "selected particle IDs",
                ),
            )
            for changed, paired, message in cases:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        validate_comparison_states(
                            [baseline, changed],
                            require_paired_ids=paired,
                        )

    def test_comparison_requires_one_shared_finite_axial_plane(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path, second_path = root / "a.csv", root / "b.csv"
            write_fixture(first_path, plane_mm=0.0)
            write_fixture(second_path, plane_mm=1.0)
            first = load_exit_state(first_path, "first")
            second = load_exit_state(second_path, "second")
            with self.assertRaisesRegex(ValueError, "different axial planes"):
                validate_comparison_states([first, second])
            mixed_values = dict(first.values)
            mixed_values["axial_z_mm"] = np.array([0.0, 0.0, 1.0])
            mixed = replace(first, label="mixed", values=mixed_values)
            with self.assertRaisesRegex(ValueError, "multiple axial planes"):
                validate_comparison_states([first, mixed])

    def test_contract_rejects_invalid_or_duplicate_active_styles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path, second_path = root / "a.csv", root / "b.csv"
            write_fixture(first_path)
            write_fixture(second_path, offset=0.2)
            states = [
                load_exit_state(first_path, "baseline"),
                load_exit_state(second_path, "refined"),
            ]
            contract = prepare_shared_scale_contract(states)
            invalid = json.loads(json.dumps(contract))
            invalid["style_map"]["baseline"]["color"] = "not-a-color"
            with self.assertRaisesRegex(ValueError, "style is invalid"):
                validate_shared_scale_contract(invalid, states)
            duplicate = json.loads(json.dumps(contract))
            duplicate["style_map"]["refined"] = duplicate["style_map"]["baseline"]
            with self.assertRaisesRegex(ValueError, "unique styles"):
                validate_shared_scale_contract(duplicate, states)

    def test_selected_cohort_probability_and_boundary_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cohort_path, single_path = root / "cohort.csv", root / "single.csv"
            write_fixture(cohort_path, source_count=100, selected_count=21)
            cohort = load_exit_state(cohort_path, "cohort")
            contract = prepare_shared_scale_contract([cohort], bin_count=8)
            figure, axes = render_four_domain_comparison(
                [cohort], contract, "cohort"
            )
            try:
                self.assertEqual(
                    figure.legends[0].get_texts()[0].get_text(),
                    "cohort (N=21/100)",
                )
                self.assertEqual(
                    axes[0, 0].get_ylabel(),
                    "Selected-cohort probability per fixed bin",
                )
            finally:
                import matplotlib.pyplot as plt

                plt.close(figure)
            for column, _ in HISTOGRAMS:
                edges = contract["shared_scales"]["histogram_edges"][column]
                weights = np.full(cohort.selected_count, 1.0 / cohort.selected_count)
                self.assertAlmostEqual(
                    np.histogram(cohort.values[column], bins=edges, weights=weights)[
                        0
                    ].sum(),
                    1.0,
                )

            write_fixture(single_path, source_count=1, selected_count=1)
            single = load_exit_state(single_path, "single")
            boundary = prepare_shared_scale_contract([single], bin_count=8)
            for column, _ in HISTOGRAMS:
                edges = boundary["shared_scales"]["histogram_edges"][column]
                value = float(single.values[column][0])
                edges[:] = np.linspace(0.0, value, len(edges))
                self.assertTrue(np.all(np.diff(edges) > 0))
                self.assertEqual(
                    np.histogram(single.values[column], bins=edges)[0].sum(), 1
                )
            validate_shared_scale_contract(boundary, [single])

    def test_transactional_export_rolls_back_and_rejects_same_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "state.csv"
            output, manifest = root / "plot.png", root / "plot.json"
            write_fixture(source)
            state = load_exit_state(source, "series")
            contract = prepare_shared_scale_contract([state])
            output.write_bytes(b"old-png")
            manifest.write_text("old-manifest", encoding="utf-8")
            resolved_manifest = manifest.resolve()
            real_replace = __import__("os").replace

            def fail_manifest_install(source_path, destination_path):
                source_path, destination_path = Path(source_path), Path(destination_path)
                if (
                    destination_path == resolved_manifest
                    and source_path.name.endswith(".tmp")
                ):
                    raise OSError("simulated manifest commit failure")
                return real_replace(source_path, destination_path)

            with patch(
                "common.multipole.exit_state_plot._replace_path",
                side_effect=fail_manifest_install,
            ):
                with self.assertRaisesRegex(OSError, "manifest commit"):
                    export_four_domain_figure(
                        [state],
                        output,
                        manifest,
                        "comparison",
                        "transaction test",
                        scale_contract=contract,
                    )
            self.assertEqual(output.read_bytes(), b"old-png")
            self.assertEqual(manifest.read_text(encoding="utf-8"), "old-manifest")
            self.assertFalse(any(".tmp" in path.name for path in root.iterdir()))
            with self.assertRaisesRegex(ValueError, "paths must differ"):
                export_four_domain_figure(
                    [state],
                    output,
                    output,
                    "comparison",
                    "same path",
                    scale_contract=contract,
                )
            self.assertEqual(output.read_bytes(), b"old-png")

    def test_shared_scale_contract_rejects_values_outside_frozen_edges(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path, shifted_path = root / "a.csv", root / "b.csv"
            write_fixture(baseline_path)
            write_fixture(shifted_path, offset=2.0)
            baseline = load_exit_state(baseline_path, "series")
            shifted = load_exit_state(shifted_path, "series")
            contract = prepare_shared_scale_contract([baseline])
            with self.assertRaisesRegex(ValueError, "exceeds shared edges"):
                validate_shared_scale_contract(contract, [shifted])

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
