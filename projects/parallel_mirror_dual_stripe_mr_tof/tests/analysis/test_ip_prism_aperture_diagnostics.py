"""Recorded aperture comparison fixtures: no native solver or external assets."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_aperture_diagnostics as d
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_distance_study as study


def write_rows(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def rows(path: Path) -> list:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def state(pid: int, index: int, z: float, event: str, reason: str) -> dict:
    return dict(event=event, reason=reason, particle_id=pid, t_us=20.+pid*.001+index*.01,
                x_mm=pid*.1, y_mm=0., z_mm=z, vx_mm_us=.01*pid,
                vy_mm_us=.02*pid, vz_mm_us=-50., potential_v=0.)


def producer(root: Path, physical: bool, shape: str = "circle", extra_z: bool = True) -> Path:
    root.mkdir(parents=True)
    folder = root/"simion/case_01"
    folder.mkdir(parents=True)
    inputs = root/"inputs"
    inputs.mkdir()
    aperture = dict(frame_id="test", shape=shape, center_mm=[0., 0., -1.], normal=[0, 0, -1], thickness_mm=1.,
                    outer_half_widths_mm=[2., 2.], voltage_v=0., connection="isolated")
    aperture.update(dict(radius_mm=.25) if shape == "circle" else dict(half_widths_mm=[.25, .25]))
    geometry = dict(frame_id="test", ion_processor_electrodes=[])
    if physical:
        geometry["aperture_electrodes"] = [dict(specification=aperture, grid_representation={"pitch_mm": .1})]
    (folder/"geometry.json").write_text(json.dumps(dict(geometry=geometry)))
    events, samples = [], []
    for pid in (1, 2, 3):
        trajectory = [state(pid, i, z, "sample", "cadence") for i, z in enumerate((0., -.5, -1., -1.5, -2.))]
        trajectory[0].update(event="birth", reason="release")
        # ID 1 is selected at the hole then moves outside its projected shadow;
        # ID 3 is outside at the selector but inside at the report plane.
        trajectory[-1]["x_mm"] = .9 if pid == 1 else .01
        if physical and pid == 2:
            trajectory = trajectory[:2]
            terminal = dict(trajectory[-1], event="terminal", reason="solver_stop")
        else:
            terminal = dict(trajectory[-1], event="terminal", reason="reached_exit")
        events.append(trajectory[0])
        for index, raw in enumerate(trajectory[1:], 1):
            if index == 4 or extra_z:
                events.append(dict(raw, event="plane", reason=("front", "center", "back", "p1_exit")[index-1]))
        events.append(terminal)
        samples.extend(trajectory[1:])
    write_rows(folder/"events.csv", events)
    write_rows(folder/"samples.csv", samples)
    source = []
    for pid in (1, 2, 3):
        s = state(pid, 0, 0., "birth", "release")
        source.append(dict(particle_id=pid, instrument_time_us=s["t_us"], mass_amu=524., charge_state=1,
            **{f"position_{a}_mm": s[f"{a}_mm"] for a in "xyz"},
            **{f"velocity_{a}_m_s": s[f"v{a}_mm_us"]*1000 for a in "xyz"}))
    write_rows(inputs/"source.csv", source)
    write_rows(inputs/"census.csv", [dict(particle_id=i, transfer_status="transferred" if i < 4 else "not_transferred",
        reason="none" if i < 4 else "upstream_loss") for i in range(1, 101)])
    projection = inputs/"native_sources/source_01/provider_voltage_projection.json"
    projection.parent.mkdir(parents=True)
    projection.write_text(json.dumps(dict(values_v15=[0.]*15, evaluation_time_us=10., basis="fixture_held")))
    spec = dict(case_id="case", label="synthetic", source_run="same-original-IP", directory=str(folder),
        source_csv=str(inputs/"source.csv"), source_census_csv=str(inputs/"census.csv"),
        physical_aperture=aperture if physical else None, distance_mm=10., exit_z_mm=0., delta_z_mm=0., gap_mm=1.,
        source_epoch_us=20.001, pulse_time_us=20., mass_u=524., charge_state=1, source_count=3, mother_count=100,
        pitch_mm=[.1, .1, .1], maximum_step_us=.02, sample_interval_us=.01)
    planes = [dict(name=name, z_mm=z) for name, z in (("front", -.5), ("center", -1.), ("back", -1.5), ("p1_exit", -2.))]
    if not extra_z:
        planes = planes[-1:]
    resolved = dict(role="resolved_ip_prism_contour_focus_study", cases=[spec], prism_voltage_v=100.,
        numerics=dict(convergence_v=1e-5), contract=dict(observation_planes=planes,
            source_registration=dict(translation_mm=[0., 0., 0.], from_frame_id="IP", to_frame_id="test")))
    (inputs/"resolved_study.json").write_text(json.dumps(resolved))
    reseal(root)
    return root


def reseal(root: Path) -> None:
    config = root/"run_config.json"
    config.write_text(json.dumps(dict(inputs={})))
    outputs = [file_record(p) for p in root.rglob("*") if p.is_file() and p.name not in {"run_manifest.json", "run_config.json"}]
    (root/"run_manifest.json").write_text(json.dumps(dict(project="parallel_mirror_dual_stripe_mr_tof", status="success",
        run_config=file_record(config), inputs={}, outputs=outputs)))


class ApertureDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline = producer(self.root/"baseline", False)
        self.physical = producer(self.root/"physical", True)
        self.run = self.root/"analysis"
        (self.run/"inputs").mkdir(parents=True)
        (self.run/"run_config.json").write_text(json.dumps(dict(inputs={}, parameters={})))
        self.contract = dict(schema_version=1, role=d.ROLE, committed_new_bytes=100_000_000, claim="Synthetic comparison",
            comparisons=[dict(comparison_id="circle", baseline_case=dict(producer_run=str(self.baseline), case_id="case"),
                physical_case=dict(producer_run=str(self.physical), case_id="case"), virtual_thin_plane="center", downstream_plane_name="p1_exit")])
        self.author = self.root/"author.json"
        self.author.write_text(json.dumps(self.contract))

    def test_study_prepare_and_analyze_cli_freeze_and_full_mother_comparison(self) -> None:
        original = {str(p): p.read_bytes() for owner in (self.baseline, self.physical) for p in owner.rglob("*") if p.is_file()}
        study.prepare(self.run, self.author)
        config = json.loads((self.run/"run_config.json").read_text())
        self.assertEqual(config["parameters"]["workflow"], d.ROLE)
        self.assertTrue(any(p.endswith("ip_prism_aperture_diagnostics.py") for p in config["inputs"]))
        frozen = json.loads((self.run/"inputs/resolved_study.json").read_text())
        self.assertEqual(frozen["role"], "resolved_"+d.ROLE)
        self.assertTrue(all(Path(r["frozen"]["path"]).is_relative_to(self.run/"inputs")
            for case in frozen["comparisons"] for key in ("baseline", "physical") for r in case[key]["records"]))
        # No producer observation is needed after preparation.
        (self.baseline/"simion/case_01/events.csv").write_text("changed externally")
        with patch.object(sys, "argv", ["study", "analyze", "--run", str(self.run)]):
            study.main()
        output = self.run/"results/aperture_comparison"
        report = json.loads((self.run/"summary.json").read_text())
        self.assertEqual(report["status"], "success")
        self.assertFalse(report["new_solver_execution"])
        self.assertEqual(report["mother_decision_count"], 100)
        final = {r["channel"]: r for r in report["downstream_statistics"]}
        self.assertEqual(final["baseline_virtual"]["available_ids"], [1, 2])
        self.assertEqual(final["physical_actual"]["available_ids"], [1, 3])
        self.assertEqual(final["baseline_virtual"]["transmission_mother"], .02)
        self.assertEqual(final["baseline_virtual"]["transmission_exit"], 2/3)
        self.assertAlmostEqual(final["baseline_virtual"]["time_sigma_ns"], .5)
        self.assertGreater(final["baseline_virtual"]["sigma_x_mm"], .4)
        for key in ("central68_ns", "central90_ns", "sigma_theta_x_deg", "sigma_theta_y_deg", "sigma_kinetic_energy_ev", "sigma_ky_ev"):
            self.assertIsNotNone(final["baseline_virtual"][key])
        decisions = rows(output/"mother_decisions.csv")
        self.assertEqual(len(decisions), 100)
        self.assertEqual(decisions[1]["physical_outcome"], "solver_stop")
        self.assertEqual(decisions[2]["virtual_decision"], "aperture_rejected")
        self.assertEqual(decisions[-1]["physical_outcome"], "upstream_not_handed_off")
        self.assertIn("physical_terminal_raw_line_sha256", decisions[1])
        paired = rows(output/"paired_statistics.csv")
        self.assertTrue(all(r["paired_downstream_ids"] == "[1]" for r in paired))
        self.assertTrue(all(r["time_sigma_ns"] == "" for r in paired))
        deltas = rows(output/"paired_particle_deltas.csv")
        self.assertEqual({int(r["particle_id"]) for r in deltas}, {1})
        self.assertEqual(len(report["figure_names"]), 2)
        self.assertTrue(all((output/name).is_file() for name in report["figure_names"]))
        for path, content in original.items():
            if path != str(self.baseline/"simion/case_01/events.csv"):
                self.assertEqual(Path(path).read_bytes(), content)

    def test_source_or_numerical_or_nonaperture_geometry_changes_rejected(self) -> None:
        for field, value in (("pulse_time_us", 19.), ("maximum_step_us", .01), ("pitch_mm", [.2, .1, .1])):
            with self.subTest(field=field):
                path = self.physical/"inputs/resolved_study.json"
                original = path.read_text()
                data = json.loads(original)
                data["cases"][0][field] = value
                path.write_text(json.dumps(data))
                reseal(self.physical)
                with self.assertRaisesRegex(ValueError, "differ beyond aperture"):
                    d.prepare_aperture_comparison(self.run, self.author)
                path.write_text(original)
                reseal(self.physical)
        path = self.physical/"simion/case_01/geometry.json"
        geometry = json.loads(path.read_text())
        geometry["geometry"]["unrelated_electrode"] = {"voltage_v": 1}
        path.write_text(json.dumps(geometry))
        reseal(self.physical)
        with self.assertRaisesRegex(ValueError, "differ beyond aperture"):
            d.prepare_aperture_comparison(self.run, self.author)

    def test_manifest_tamper_and_private_tamper_fail_closed(self) -> None:
        path = self.physical/"simion/case_01/events.csv"
        original = path.read_bytes()
        path.write_bytes(original+b"changed")
        with self.assertRaises(AssertionError):
            d.prepare_aperture_comparison(self.run, self.author)
        path.write_bytes(original)
        d.prepare_aperture_comparison(self.run, self.author)
        private = self.run/"inputs/sources/source_02/events.csv"
        private.write_bytes(original+b"changed")
        with self.assertRaises(AssertionError):
            d.analyze_aperture_comparison(self.run)

    def test_y_slit_boundary_and_empty_singleton_widths(self) -> None:
        aperture = dict(shape="y_slit", center_mm=[0, 0, -1], half_widths_mm=[.2, .1])
        states = {1:dict(x_mm=.2, y_mm=.1), 2:dict(x_mm=.2000001, y_mm=0), 3:dict(x_mm=0, y_mm=-.1)}
        self.assertEqual(d._selected_ids(states, aperture), {1, 3})
        aperture.update(shape="circle", radius_mm=.2)
        self.assertEqual(d._selected_ids({1:dict(x_mm=.2, y_mm=0)}, aperture), {1})
        self.assertIsNone(d._stats([], 524.)["time_sigma_ns"])
        self.assertIsNone(d._stats([state(1, 0, 0, "birth", "release")], 524.)["central90_ns"])

    def test_baseline_copy_deduplicated_across_circle_and_y_slit(self) -> None:
        slit = producer(self.root/"slit", True, shape="y_slit")
        comparison = copy.deepcopy(self.contract["comparisons"][0])
        comparison.update(comparison_id="slit", physical_case=dict(producer_run=str(slit), case_id="case"))
        self.contract["comparisons"].append(comparison)
        self.author.write_text(json.dumps(self.contract))
        resolved = d.prepare_aperture_comparison(self.run, self.author)
        self.assertEqual(len(list((self.run/"inputs/sources").iterdir())), 3)
        self.assertEqual(resolved["comparisons"][0]["baseline"]["spec"]["directory"],
                         resolved["comparisons"][1]["baseline"]["spec"]["directory"])
        tables = d._comparison_tables(resolved["comparisons"][1], self.run)
        self.assertEqual(tables["population_statistics"][0]["aperture_shape"], "y_slit")

    def test_copy_budget_fails_before_copy_and_hook_accounts_for_code_closure(self) -> None:
        self.contract["committed_new_bytes"] = 1
        self.author.write_text(json.dumps(self.contract))
        with self.assertRaisesRegex(ValueError, "before copying"):
            d.prepare_aperture_comparison(self.run, self.author)
        self.assertEqual(list((self.run/"inputs").iterdir()), [])
        self.contract["committed_new_bytes"] = 1_000_000
        self.author.write_text(json.dumps(self.contract))
        def oversized_code(repo, inputs):
            (inputs/"synthetic_code_closure.py").write_bytes(b" "*1_000_001)
        with patch.object(study, "freeze_code", side_effect=oversized_code):
            with self.assertRaisesRegex(ValueError, "committed_new_bytes|commitment|capacity"):
                study.prepare(self.run, self.author)

    def test_missing_internal_events_use_bounded_track_support_without_extrapolation(self) -> None:
        base = producer(self.root/"sample_baseline", False, extra_z=False)
        physical = producer(self.root/"sample_physical", True, extra_z=False)
        self.contract["comparisons"][0]["baseline_case"]["producer_run"] = str(base)
        self.contract["comparisons"][0]["physical_case"]["producer_run"] = str(physical)
        self.author.write_text(json.dumps(self.contract))
        frozen = d.prepare_aperture_comparison(self.run, self.author)
        tables = d._comparison_tables(frozen["comparisons"][0], self.run)
        decision = next(r for r in tables["mother_decisions"] if r["particle_id"] == 2)
        self.assertTrue(decision["physical_front_reached"])
        self.assertFalse(decision["physical_center_reached"])
        self.assertFalse(decision["physical_back_reached"])
        self.assertEqual(len([r for r in tables["plane_particles"] if r["side"] == "baseline" and r["plane"] == "center"]), 3)

    def test_paired_statistics_use_shared_ids_when_only_one_middle_track_is_missing(self) -> None:
        physical = producer(self.root/"sparse_physical", True, extra_z=False)
        samples = physical/"simion/case_01/samples.csv"
        write_rows(samples, [r for r in rows(samples) if int(r["particle_id"]) != 1 or float(r["z_mm"]) == -2.])
        reseal(physical)
        self.contract["comparisons"][0]["physical_case"]["producer_run"] = str(physical)
        self.author.write_text(json.dumps(self.contract))
        prepared = d.prepare_aperture_comparison(self.run, self.author)
        paired = d._comparison_tables(prepared["comparisons"][0], self.run)["paired_statistics"]
        middle = [r for r in paired if r["plane"] == "center"]
        self.assertTrue(all(r["paired_downstream_ids"] == [1] and r["available_ids"] == [] and r["count"] == 0 for r in middle))
        self.assertEqual(middle[0]["side_available_ids"], [1])
        self.assertEqual(middle[1]["side_missing_ids"], [1])

    def test_author_unknown_fields_duplicate_and_invalid_selection_rejected(self) -> None:
        for mutate in (lambda c:c.update(extra=True), lambda c:c.update(committed_new_bytes=True),
                       lambda c:c["comparisons"].append(copy.deepcopy(c["comparisons"][0])),
                       lambda c:c["comparisons"][0].update(virtual_thin_plane="downstream"),
                       lambda c:c["comparisons"][0]["physical_case"].update(case_id="../unsafe")):
            changed = copy.deepcopy(self.contract)
            mutate(changed)
            with self.assertRaises(ValueError):
                d.validate_aperture_contract(changed)

    def test_figure_uses_prepared_metrics_with_distinct_markers_and_units(self) -> None:
        prepared = d.prepare_aperture_comparison(self.run, self.author)
        table = d._comparison_tables(prepared["comparisons"][0], self.run)["population_statistics"]
        original = copy.deepcopy(table)
        figure, axes = d.build_aperture_comparison_figure(table, "circle")
        figure.canvas.draw()
        self.assertEqual(table, original)
        self.assertEqual(axes.shape, (3, 3))
        self.assertEqual([line.get_marker() for line in axes[0, 0].lines], ["D", "o", "s"])
        self.assertIn("(ns)", axes[0, 2].get_ylabel())
        self.assertEqual(len(axes[0, 0].lines[0].get_ydata()), 4)
        figure.clear()


if __name__ == "__main__":
    unittest.main()
