"""Pure local diagnostics fixtures; no solver or external artifact dependency."""
from __future__ import annotations

import csv
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as diagnostics


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _state(pid: int, time: float, event: str, reason: str, z: float) -> dict:
    return dict(event=event, particle_id=pid, reason=reason, t_us=time, x_mm=pid * .1,
                y_mm=-55 + pid * .2, z_mm=z, vx_mm_us=pid * .01,
                vy_mm_us=-pid * .02, vz_mm_us=-40., potential_v=0.)


class LocalPrismDiagnosticsTests(unittest.TestCase):
    def test_figure_export_preserves_names_dpi_and_closes(self) -> None:
        from matplotlib import pyplot as plt
        from PIL import Image
        from xml.etree import ElementTree

        figure, axis = plt.subplots(figsize=(2, 1))
        self.addCleanup(plt.close, figure)
        axis.plot([0, 1], [1, 0])
        diagnostics._save_figure(figure, self.run / "local.v1")
        with Image.open(self.run / "local.png") as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (400, 200))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255, 255))
        svg = ElementTree.parse(self.run / "local.svg").getroot()
        self.assertEqual((svg.attrib["width"], svg.attrib["height"]), ("144pt", "72pt"))
        self.assertFalse(plt.fignum_exists(figure.number))

    def test_figure_export_failure_preserves_existing_files_and_closes(self) -> None:
        from matplotlib import pyplot as plt

        for collision in (True, False):
            with self.subTest(collision=collision):
                directory = self.run / str(collision)
                directory.mkdir()
                target = directory / "figure"
                figure, _ = plt.subplots(figsize=(2, 1))
                self.addCleanup(plt.close, figure)
                if collision:
                    protected = target.with_suffix(".svg")
                    protected.write_bytes(b"existing figure")
                    with self.assertRaises(FileExistsError):
                        diagnostics._save_figure(figure, target)
                    self.assertEqual(protected.read_bytes(), b"existing figure")
                    self.assertFalse(target.with_suffix(".png").exists())
                else:
                    original = figure.savefig

                    def fail_svg(stream, **kwargs):
                        if kwargs["format"] == "svg":
                            raise OSError("render failure")
                        return original(stream, **kwargs)

                    with patch.object(figure, "savefig", side_effect=fail_svg), \
                         self.assertRaisesRegex(OSError, "render failure"):
                        diagnostics._save_figure(figure, target)
                    self.assertEqual(list(directory.iterdir()), [])
                self.assertFalse(plt.fignum_exists(figure.number))

    def test_table_snapshot_reads_once_and_preserves_raw_byte_provenance(self) -> None:
        import hashlib

        fields = ["particle_id", *diagnostics.STATE_FIELDS]
        values = ["7", "7500.125", "1", "2", "3", "4", "5", "-6", "0"]
        read_bytes = Path.read_bytes
        for ending in (b"\n", b"\r\n"):
            for bom in (b"", b"\xef\xbb\xbf"):
                with self.subTest(ending=ending, bom=bom):
                    raw_line = ",".join(values).encode() + ending
                    payload = bom + ",".join(fields).encode() + ending + raw_line
                    path = self.run / "snapshot.csv"
                    path.write_bytes(payload)
                    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes) as read, \
                         patch.object(Path, "read_text", side_effect=AssertionError("table reread")), \
                         patch.object(diagnostics, "file_sha256", side_effect=AssertionError("table rehashed from disk")):
                        rows = diagnostics._load_rows(path, states=True)
                    read.assert_called_once_with(path)
                    self.assertEqual(len(rows), 1)
                    row = rows[0]
                    self.assertEqual(row["particle_id"], 7)
                    self.assertEqual([row[key] for key in diagnostics.STATE_FIELDS], list(map(float, values[1:])))
                    self.assertEqual(row["raw_sha256"], hashlib.sha256(payload).hexdigest().upper())
                    self.assertEqual(row["raw_line_sha256"], hashlib.sha256(raw_line).hexdigest())
                    self.assertEqual(row["raw_line_number"], 2)
                    self.assertEqual(row["raw_line"], ",".join(values))
                    self.assertEqual(row["raw_path"], str(path.resolve()))

    def test_zero_field_projection_preserves_individual_birth_clock_and_noncommon_z(self) -> None:
        rows = [_state(1, 7.5, "birth", "measured_exit", 2.), _state(2, 8., "birth", "measured_exit", 0.)]
        rows[0].update(x_mm=3., y_mm=4., vx_mm_us=1., vy_mm_us=2., vz_mm_us=-2., potential_v=12.)
        rows[1].update(x_mm=3., y_mm=4., vx_mm_us=-2., vy_mm_us=.5, vz_mm_us=-1.)
        original = copy.deepcopy(rows)
        result = diagnostics.project_field_free_births(rows, -2.)
        self.assertEqual(rows, original)
        self.assertEqual(result["missing_ids"], [])
        first, second = result["crossings"]
        self.assertEqual((first["t_us"], first["x_mm"], first["y_mm"], first["z_mm"]), (9.5, 5., 8., -2.))
        self.assertEqual((second["t_us"], second["x_mm"], second["y_mm"]), (10., -1., 5.))
        self.assertEqual(first["birth_z_mm"], 2.)
        self.assertEqual(first["birth_t_us"], 7.5)
        self.assertEqual(first["potential_v"], 0.)
        self.assertEqual(first["birth_potential_v"], 12.)
        self.assertAlmostEqual(diagnostics.compute_plane_statistics(result["crossings"], 524.)["time_sigma_ns"], 250.)

    def test_zero_field_unreachable_and_invalid_sources_remain_explicit(self) -> None:
        rows = [_state(i, 7., "birth", "measured_exit", 0.) for i in range(1, 6)]
        rows[0]["vz_mm_us"] = 0.
        rows[1]["vz_mm_us"] = 1.
        rows[2]["z_mm"] = -3.
        rows[3]["z_mm"] = -2.
        del rows[4]["t_us"]
        result = diagnostics.project_field_free_births(rows, -2.)
        self.assertEqual(result["missing_ids"], [1, 2, 3, 4, 5])
        self.assertEqual(result["source_count"], 5)
        self.assertEqual(len(result["particle_decisions"]), 5)
        self.assertIn("not physical losses", result["scope"])
        rows[4]["t_us"] = float("nan")
        self.assertEqual(diagnostics.project_field_free_births(rows, -2.)["particle_decisions"][-1]["reason"], "missing_or_nonfinite_birth_state")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            diagnostics.project_field_free_births([rows[0], rows[0]], -2.)
        with self.assertRaises(ValueError):
            diagnostics.project_field_free_births([], float("nan"))
        self.assertEqual(diagnostics.project_field_free_births([], -2.)["crossing_count"], 0)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        (self.run / "inputs").mkdir()
        self.contract = dict(schema_version=1, mass_u=524., mother_particle_count=3, source_count=2,
                             source_epoch_us=7500., pulse_time_us=7500., contract={"numerics": {"maximum_step_us": .004}},
                             cases=[dict(case_id="current", distance_mm=52.828, directory="case_current", exit_z_mm=0.),
                                    dict(case_id="short", distance_mm=10., directory="case_short", exit_z_mm=-42.828)])
        self._write_contract()
        _write_csv(self.run / "inputs/source_census.csv", [dict(particle_id=i, transfer_status="transferred" if i < 3 else "not_transferred") for i in (1, 2, 3)])
        source = []
        for pid in (1, 2):
            row = _state(pid, 7500 + pid * .002, "birth", "release", 0.)
            source.append(dict(particle_id=pid, mass_amu=524., charge_state=1,
                               instrument_time_us=row["t_us"], position_x_mm=row["x_mm"],
                               position_y_mm=row["y_mm"], position_z_mm=0.,
                               velocity_x_m_s=row["vx_mm_us"] * 1000,
                               velocity_y_m_s=row["vy_mm_us"] * 1000, velocity_z_m_s=-40000.))
        _write_csv(self.run / "inputs/component_particle_state.csv", source)
        self._write_case(0)
        self._write_case(1)

    def _write_contract(self) -> None:
        (self.run / "inputs/resolved_study.json").write_text(json.dumps(self.contract), encoding="utf-8")

    def _write_case(self, index: int, *, empty_exit: bool = False, nonfinite: bool = False, duplicate: bool = False) -> None:
        case = self.contract["cases"][index]
        events, samples = [], []
        for pid in (1, 2):
            birth_time = 7500 + pid * .002
            birth = _state(pid, birth_time, "birth", "release", case["exit_z_mm"])
            if nonfinite:
                birth["vx_mm_us"] = float("nan")
            events.append(birth)
            if duplicate:
                events.append(birth.copy())
            for offset, plane, z in ((.5, "p1_near", -52.828), (.8, "p1_far", -82.), (1., "p1_exit", -98.)):
                if not empty_exit:
                    events.append(_state(pid, birth_time + offset, "plane", plane, z))
            events.append(_state(pid, birth_time + 1.1, "terminal", "solver_stop" if empty_exit else "reached_exit", -99.))
            samples.extend([_state(pid, birth_time + offset, "sample", "cadence", -offset * 40 + case["exit_z_mm"])
                            for offset in (.2, .4, .6, .8, 1.)])
        _write_csv(self.run / case["directory"] / "events.csv", events)
        _write_csv(self.run / case["directory"] / "samples.csv", samples)

    def test_population_time_width_keeps_source_clock(self) -> None:
        rows = [_state(1, 7500., "plane", "p1_exit", -98.), _state(2, 7500.004, "plane", "p1_exit", -98.)]
        stats = diagnostics.compute_plane_statistics(rows, 524.)
        self.assertAlmostEqual(stats["time_sigma_ns"], 2., places=6)
        self.assertAlmostEqual(stats["time_range_ns"], 4., places=6)
        self.assertGreater(stats["sigma_theta_x_deg"], 0.)
        cancellation_bound = np.sqrt(np.finfo(float).eps) * stats["sigma_x_mm"] * np.radians(stats["sigma_theta_x_deg"]) * 1000
        self.assertLessEqual(stats["emittance_x_mm_mrad"], cancellation_bound)

    def test_empty_statistics_do_not_invent_fwhm(self) -> None:
        stats = diagnostics.compute_plane_statistics([], 524.)
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["time_sigma_ns"])
        self.assertIsNone(stats["emittance_y_mm_mrad"])

    def test_complete_census_losses_and_common_time_support(self) -> None:
        with patch.object(diagnostics, "_save_figure") as save:
            result = diagnostics.analyze_study(self.run)
        self.assertEqual(result["common_plane_counts"]["p1_exit"], 2)
        self.assertEqual(save.call_count, 5)
        root = self.run / "results/local_diagnostics"
        with (root / "mother_census.csv").open() as stream:
            census = list(csv.DictReader(stream))
        self.assertEqual(len(census), 6)
        with (root / "all_losses.csv").open() as stream:
            losses = list(csv.DictReader(stream))
        self.assertEqual(len(losses), 2)
        self.assertTrue(all(row["outcome"] == "upstream_not_handed_off" for row in losses))
        with (root / "simultaneous_positions.csv").open() as stream:
            snapshots = list(csv.DictReader(stream))
        self.assertEqual(len(snapshots), 20)
        self.assertGreaterEqual(min(float(row["t_us"]) for row in snapshots), 7500.004)
        self.assertEqual(result["maximum_observed_hamiltonian_drift_ev"], 0.)
        from matplotlib import pyplot as plt
        plt.close("all")

    def test_no_arrivals_is_explicit_and_terminal_raw_evidence_is_preserved(self) -> None:
        self._write_case(1, empty_exit=True)
        with patch.object(diagnostics, "_save_figure"):
            result = diagnostics.analyze_study(self.run)
        self.assertEqual(result["status"], "no_arrival_in_one_or_more_cases")
        self.assertEqual(result["common_plane_counts"]["p1_exit"], 0)
        with (self.run / "results/local_diagnostics/all_losses.csv").open() as stream:
            losses = list(csv.DictReader(stream))
        local = [row for row in losses if row["outcome"] == "solver_stop"]
        self.assertEqual(len(local), 2)
        self.assertEqual(len(local[0]["terminal_raw_line_sha256"]), 64)
        self.assertIn("terminal,", local[0]["terminal_raw_line"])
        from matplotlib import pyplot as plt
        plt.close("all")

    def test_nonfinite_state_and_duplicate_birth_fail_closed(self) -> None:
        for kwargs in (dict(nonfinite=True), dict(duplicate=True)):
            self._write_case(0, **kwargs)
            with self.assertRaises(ValueError):
                diagnostics.analyze_study(self.run)

    def test_source_time_correlation_cannot_be_erased(self) -> None:
        events = self.run / "case_current/events.csv"
        rows = list(csv.DictReader(events.read_text().splitlines()))
        rows[0]["t_us"] = "7500.0"
        _write_csv(events, rows)
        with self.assertRaisesRegex(ValueError, "Changed source t_us"):
            diagnostics.analyze_study(self.run)

    def test_snapshot_interpolation_is_bounded_and_uses_common_instrument_time(self) -> None:
        cases = [diagnostics._load_case(self.run, case, 2, .004) for case in self.contract["cases"]]
        snapshots = diagnostics.prepare_common_time_snapshots(cases)
        first = snapshots[0]
        self.assertAlmostEqual(first["t_us"], 7500.004)
        track = cases[0]["tracks"][1]
        self.assertGreaterEqual(first["z_mm"], min(row["z_mm"] for row in track))
        self.assertLessEqual(first["z_mm"], max(row["z_mm"] for row in track))
        self.assertTrue(np.isfinite(first["z_mm"]))

    def _append_exit_halo(self, *, delta_us: float = .002, reason: str = "reached_exit", reverse: bool = False,
                          count: int = 1) -> None:
        directory = self.run / "case_current"
        events = list(csv.DictReader((directory / "events.csv").read_text().splitlines()))
        for row in events:
            if row["particle_id"] == "1" and row["event"] == "terminal":
                row.update(t_us=7501.002, z_mm=-98., reason=reason)
        if reason != "reached_exit":
            events = [row for row in events if not (row["particle_id"] == "1" and row["reason"] == "p1_exit")]
        _write_csv(directory / "events.csv", events)
        samples = list(csv.DictReader((directory / "samples.csv").read_text().splitlines()))
        for index in range(count):
            row = _state(1, 7501.002 + delta_us + index * .0001, "sample", "cadence", -98. - .08)
            if reverse:
                row["vz_mm_us"] = 40.
            samples.append(row)
        _write_csv(directory / "samples.csv", samples)

    def test_last_actual_step_halo_is_preserved_but_not_extrapolated_into_packet(self) -> None:
        self._append_exit_halo()
        case = diagnostics._load_case(self.run, self.contract["cases"][0], 2, .004)
        self.assertEqual(len(case["overshoots"]), 1)
        self.assertAlmostEqual(case["overshoots"][0]["delta_after_terminal_us"], .002, places=9)
        self.assertEqual(len(case["overshoots"][0]["raw_line_sha256"]), 64)
        self.assertTrue(all(row["t_us"] <= case["terminals"][1]["t_us"] for row in case["tracks"][1]))
        self.assertGreater(case["raw_tracks"][1][-1]["t_us"], case["terminals"][1]["t_us"])
        with patch.object(diagnostics, "_save_figure"):
            result = diagnostics.analyze_study(self.run)
        self.assertEqual(result["event_interpolation_halo_count"], 1)
        path = self.run / "results/local_diagnostics/observation_overshoot.csv"
        self.assertIn("last_actual_step_after_interpolated_exit", path.read_text())
        from matplotlib import pyplot as plt
        plt.close("all")

    def test_event_halo_rejects_overlong_multiple_wrong_direction_or_nonexit(self) -> None:
        for kwargs in (dict(delta_us=.005), dict(count=2), dict(reverse=True), dict(reason="solver_stop")):
            self._write_case(0)
            self._append_exit_halo(**kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "halo"):
                diagnostics._load_case(self.run, self.contract["cases"][0], 2, .004)

    def test_simultaneous_linear_chirp_gives_spatial_waist_sign_and_units(self) -> None:
        rows = [_state(pid, 7500., "sample", "cadence", -s)
                for pid, s in enumerate((9., 10., 11.), 1)]
        for row, u in zip(rows, (41., 40., 39.)):
            row["vz_mm_us"] = -u
        chirp = diagnostics.compute_longitudinal_chirp(rows)
        self.assertEqual(chirp["ballistic_tau_star_us"], 1.)
        self.assertEqual(chirp["regression_u_on_s_per_us"], -1.)
        self.assertEqual(chirp["correlation_s_u"], -1.)
        self.assertEqual(chirp["ballistic_waist_mean_z_mm"], -50.)
        self.assertEqual(chirp["ballistic_minimum_sigma_s_mm"], 0.)
        for row in rows:
            row["vz_mm_us"] = -(80 + row["z_mm"] * -1)
        self.assertEqual(diagnostics.compute_longitudinal_chirp(rows)["ballistic_tau_star_us"], -1.)

    def test_arrival_ballistic_length_preserves_clock_and_negative_length_is_mathematical(self) -> None:
        # t = 7500 - 20/u reaches a common time after +20 mm free drift.
        rows = [_state(pid, 7500 - 20 / u, "plane", "p1_exit", -98.)
                for pid, u in enumerate((39., 40., 41.), 1)]
        for row, u in zip(rows, (39., 40., 41.)):
            row["vz_mm_us"] = -u
        before = [dict(row) for row in rows]
        result = diagnostics.compute_arrival_time_energy_correlations(rows, 524.)
        # Absolute-time subtraction loses at most ulp(t)/span(1/u).
        bound_mm = 8 * np.spacing(7500.) / np.ptp(1 / np.array([39., 40., 41.]))
        self.assertLessEqual(abs(result["ballistic_best_length_mm"] - 20), bound_mm)
        self.assertEqual(rows, before)
        self.assertIn("mathematical_upstream_only", result["interpretation"])
        for row, u in zip(rows, (39., 40., 41.)):
            row["t_us"] = 7500 + 20 / u
        result = diagnostics.compute_arrival_time_energy_correlations(rows, 524.)
        self.assertLessEqual(abs(result["ballistic_best_length_mm"] + 20), bound_mm)

    def test_centered_time_display_keeps_raw_times_and_resolves_width(self) -> None:
        cases = [diagnostics._load_case(self.run, case, 2, .004) for case in self.contract["cases"]]
        before = [row["t_us"] for case in cases for row in case["planes"]["p1_exit"].values()]
        figure = diagnostics.build_time_energy_figure(cases, 524., 7500.)
        self.assertIn("display only", figure.axes[2].get_xlabel())
        after = [row["t_us"] for case in cases for row in case["planes"]["p1_exit"].values()]
        self.assertEqual(before, after)
        from matplotlib import pyplot as plt
        plt.close(figure)


class LensContactWitnessTests(unittest.TestCase):
    def test_witness_preserves_component_native_flag_and_bracket(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            terminal = _state(3, 10.5, "terminal", "lens_contact", -.6)
            row = {key: value for key, value in terminal.items() if key in diagnostics.STATE_FIELDS[:-1]}
            row.update(particle_id=3, electrode_id=1007, component_name="Q2_y_positive",
                       face="cap_end", fraction=.5, native_splat_before=0)
            for key in diagnostics.STATE_FIELDS[:-1]:
                stem, unit = key.split("_", 1)
                row[f"{stem}0_{unit}"] = row[key] - .5
                row[f"{stem}1_{unit}"] = row[key] + .5
            (root/"geometry.json").write_text(json.dumps(dict(geometry=dict(lens_electrodes=[
                dict(electrode_id=1007, name="Q2_y_positive")]))))
            path = root/"lens_contacts.csv"
            _write_csv(path, [row])
            self.assertEqual(len(diagnostics._validate_lens_contacts(root, {3: terminal})), 1)
            for changes in (dict(native_splat_before=-4), dict(component_name="wrong"),
                            dict(fraction=2), dict(t0_us=11), dict(x1_mm=99)):
                with self.subTest(changes=changes):
                    _write_csv(path, [dict(row, **changes)])
                    with self.assertRaises(ValueError):
                        diagnostics._validate_lens_contacts(root, {3: terminal})
            path.unlink()
            with self.assertRaises(ValueError):
                diagnostics._validate_lens_contacts(root, {3: terminal})
            self.assertEqual(diagnostics._validate_lens_contacts(root, {}), [])


if __name__ == "__main__":
    unittest.main()
