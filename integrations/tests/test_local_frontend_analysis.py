from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

import matplotlib.pyplot as plt
import pandas as pd

from common.contracts.rigid_transform import RigidTransform
from integrations.tests.frontend_fixtures import (
    canonical_three_zone_frontend_fixture,
    canonical_two_zone_frontend_contract,
    compile_direct_mr_frontend,
)
from integrations.workflows.local_frontend.analyze import (
    _aperture_passages,
    _capture_bounds,
    _source_rows,
    _snapshot_census,
    _select_pulse,
    _validate_lifetimes,
    analyze_local_frontend,
    build_local_shared_time_figure,
    parse_local_logs,
    select_shared_time_display_counts,
)

_TIMES = [0., .5, 1., 2., 3.]


def geometry_frontend(*, three_zone: bool = False) -> dict:
    """Compile real provider geometry without external artifact fixtures."""
    from integrations.runtime.single_flight_frontend import compile_frontend
    if not three_zone:
        return compile_direct_mr_frontend()
    upstream, connection, component = canonical_three_zone_frontend_fixture()
    return compile_frontend(upstream, connection, accelerator_component=component,
                            cell_mm_xyz=dict(x=.1, y=.2, z=.1),
                            target_solver_frame="mrtof_global_cartesian")[1]


class SharedTimeDisplaySelectionTests(unittest.TestCase):
    @staticmethod
    def counts(time, active=1, unsupported=0, not_born=0):
        return dict(instrument_time_us=float(time), mother_count=10, active=active,
                    numerical_unsupported=unsupported, not_born=not_born,
                    already_exit=10-active-unsupported-not_born, already_loss=0)

    def test_empty_and_short_active_census_preserve_available_panels(self):
        self.assertEqual(select_shared_time_display_counts([]), [])
        rows = [self.counts(i) for i in range(3)]
        self.assertEqual(select_shared_time_display_counts(rows), rows)

    def test_only_active_times_cover_first_middle_last_without_fabricated_terminal(self):
        rows = [self.counts(i) for i in range(9)]
        before = copy.deepcopy(rows)
        selected = select_shared_time_display_counts(rows)
        self.assertEqual([r["instrument_time_us"] for r in selected], [0., 2., 4., 6., 8.])
        self.assertEqual(rows, before)

    def test_active_to_terminal_selects_one_first_complete_terminal_not_empty_tail(self):
        rows = [self.counts(i) for i in range(10)] + [self.counts(i, active=0) for i in range(10, 40)]
        selected = select_shared_time_display_counts(rows)
        self.assertEqual([r["instrument_time_us"] for r in selected], [0., 3., 6., 9., 10.])
        self.assertEqual(sum(r["active"] == 0 for r in selected), 1)

    def test_unsupported_and_future_birth_are_not_complete_terminal(self):
        rows = [self.counts(0, active=0, not_born=10), self.counts(1),
                self.counts(2, active=0, unsupported=1), self.counts(3, active=0)]
        self.assertEqual([r["instrument_time_us"] for r in select_shared_time_display_counts(rows)], [1., 3.])
        self.assertEqual(select_shared_time_display_counts(rows[:1]), rows[:1])
        self.assertEqual(select_shared_time_display_counts(rows[-1:]), rows[-1:])

    def test_default_geometry_has_real_rods_repeller_and_zone_specific_supports(self):
        frame = pd.DataFrame([dict(requested_time_us=1., z_mm=32., x_mm=0., y_mm=-50.)])
        for three_zone in (False, True):
            frontend = geometry_frontend(three_zone=three_zone)
            before = copy.deepcopy(frontend)
            figure, axes = build_local_shared_time_figure(
                frame, [self.counts(1)], frame_id="mrtof_global_cartesian", frontend_contract=frontend,
                terminal_rows=pd.DataFrame(),
            )
            try:
                for ax in axes.flat:
                    gids = [p.get_gid() for p in ax.patches]
                    self.assertEqual(sum(str(g).startswith("local_geometry_projected_rod_") for g in gids), 8)
                    for name in ("shield", "repeller", "rings"):
                        self.assertIn("local_geometry_" + name, gids)
                    self.assertEqual("local_geometry_grid_supports" in gids, not three_zone)
                    self.assertTrue(any(str(line.get_gid()).startswith("local_geometry_grid_") for line in ax.lines))
                self.assertEqual(frontend, before)
                self.assertEqual(axes[0, 0].collections[0].get_offsets().tolist(), [[32., 0.]])
            finally:
                plt.close(figure)

    def test_render_groups_valid_actual_clock_by_requested_time_and_excludes_unsupported(self):
        observer = RigidTransform("mrtof_global_cartesian", "mrtof_global_cartesian",
                                  [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0., 0., 0.])
        events = [dict(event="local_shared_time", particle_id=pid, requested_time_us=1.,
                       instrument_time_us=1.+ulps*math.ulp(1.), x_mm=2., y_mm=3., z_mm=4.,
                       vx_mm_per_us=.1, vy_mm_per_us=.2, vz_mm_per_us=-1.)
                  for pid, ulps in ((1, 32), (2, 33))]
        lives = {pid: dict(birth=dict(instrument_time_us=0.), terminal=dict(instrument_time_us=2.), exit=None)
                 for pid in (1, 2)}
        census, active, counts = _snapshot_census(events, {1: {}, 2: {}}, lives, [1.], observer)
        self.assertEqual([r["status"] for r in census], ["active", "numerical_unsupported"])
        self.assertEqual(active[0]["instrument_time_us"], events[0]["instrument_time_us"])
        frame = pd.DataFrame(active)
        frontend = geometry_frontend()
        figure, axes = build_local_shared_time_figure(frame, select_shared_time_display_counts(counts), frame_id=observer.to_frame_id,
                                                     frontend_contract=frontend, terminal_rows=pd.DataFrame())
        try:
            self.assertEqual(axes[0, 0].collections[0].get_offsets().tolist(), [[4., 2.]])
            self.assertIn("active N=1", axes[0, 0].get_title())
            self.assertIn("unsupported 1", axes[0, 0].get_title())
            with self.assertRaisesRegex(ValueError, "differs from the census"):
                build_local_shared_time_figure(frame, [{**counts[0], "active": 2}], frame_id=observer.to_frame_id,
                                               frontend_contract=frontend, terminal_rows=pd.DataFrame())
        finally:
            plt.close("all")

    def test_terminal_markers_are_actual_past_positions_and_not_active_states(self):
        active = pd.DataFrame([dict(requested_time_us=1., z_mm=32., x_mm=0., y_mm=-50.)])
        terminals = pd.DataFrame([
            dict(particle_id=1, instrument_time_us=.5, x_mm=2., y_mm=-60., z_mm=30., terminal_class="native_stop_unresolved"),
            dict(particle_id=2, instrument_time_us=2., x_mm=3., y_mm=-61., z_mm=31., terminal_class="native_stop_unresolved"),
            dict(particle_id=3, instrument_time_us=.7, x_mm=4., y_mm=-62., z_mm=0., terminal_class="exit"),
        ])
        before = terminals.copy(deep=True)
        figure, axes = build_local_shared_time_figure(
            active, [self.counts(1)], frame_id="mrtof_global_cartesian",
            frontend_contract=geometry_frontend(), terminal_rows=terminals,
        )
        try:
            for ax, transverse in zip(axes[:, 0], ("x", "y"), strict=True):
                markers = {artist.get_gid(): artist for artist in ax.collections}
                self.assertEqual(markers["local_terminal_native_stop_unresolved"].get_offsets().tolist(),
                                 [[30., 2. if transverse == "x" else -60.]])
                self.assertEqual(markers["local_terminal_exit"].get_offsets().tolist(),
                                 [[0., 4. if transverse == "x" else -62.]])
                self.assertEqual(len(ax.collections[0].get_offsets()), 1)
            self.assertTrue(any("Splat" in text.get_text() for text in figure.legends[0].texts))
            pd.testing.assert_frame_equal(terminals, before)
        finally:
            plt.close(figure)


def aperture_triplet(crossing: dict, before: dict | None = None, after: dict | None = None) -> list[dict]:
    """Synthetic native endpoints; omitted endpoints model a zero-step confirmation."""
    return [dict(before or crossing, event=crossing["event"] + "_step_before"),
            dict(after or crossing, event=crossing["event"] + "_step_after"), crossing]


class ActualFirstGapTests(unittest.TestCase):
    def test_sectioned_provider_capture_uses_world_bounds_without_fabricated_frames(self):
        from integrations.runtime.single_flight_frontend import compile_frontend
        upstream, connection, component = canonical_three_zone_frontend_fixture()
        _, frontend = compile_frontend(upstream, connection, accelerator_component=component,
                                       cell_mm_xyz=dict(x=.1, y=.2, z=.1), target_solver_frame="mrtof_global_cartesian")
        self.assertNotIn("grid_supports", frontend["accelerator_local_region"]["canonical_electrodes"])
        result = _capture_bounds(frontend)
        actual = frontend["accelerator_local_region"]["first_gap_bounds_mm"]
        for axis in "xyz":
            self.assertEqual(result[axis]["minimum_mm"], actual[axis+"_min"])
            self.assertEqual(result[axis]["maximum_mm"], actual[axis+"_max"])


def fixture(root: Path) -> tuple[Path, list[dict]]:
    inputs = root / "inputs"
    inputs.mkdir()
    frontend = canonical_two_zone_frontend_contract()
    local = frontend["accelerator_local_region"]
    # The statistics fixture below uses synthetic clocks and capture bounds;
    # retain complete provider geometry so default rendering cannot omit it.
    geometry = geometry_frontend()
    frontend.update({key: geometry[key] for key in ("guide_contract", "guide_registration")})
    local["accelerator_component"]["transform"]["rotation"] = [[0, 1, 0], [1, 0, 0], [0, 0, -1]]
    local["canonical_electrodes"] = copy.deepcopy(geometry["accelerator_local_region"]["canonical_electrodes"])
    local["canonical_electrodes"]["grid_supports"][0]["aperture_box_mm"] = {
        "x_min_mm": -2., "x_max_mm": 2., "y_min_mm": -5., "y_max_mm": 5., "z_min_mm": 35., "z_max_mm": 37.,
    }
    frontend.update(native_frame_id="mrtof_global_cartesian", frame_id="mrtof_global_cartesian", slow_axis="y", acceleration_direction=-1)
    local["planes"] = {k: -v - 6. for k, v in local["planes"].items()}
    local["port"] = dict(normal_axis="y", flange_min_mm=.2, flange_max_mm=.4)
    local["accelerator_component"]["transform"] = {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation_mm": [0., 0., -6.]}
    frontend.update(cell_mm_xyz=dict(x=.1, y=.2, z=.1),
                    instance_origin_mm=dict(x=-5.1, y=-5.2, z=-.1))
    (inputs / "frontend_contract.json").write_text(json.dumps(frontend), encoding="utf-8")
    (inputs / "numerics.json").write_text(json.dumps({
        "trajectory_sample_interval_us": .5, "maximum_step_us": .01,
    }), encoding="utf-8")
    identity = RigidTransform("mrtof_global_cartesian", "mrtof_global_cartesian", [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0., 0., 0.])
    (inputs / "registration.json").write_text(json.dumps({"observer_to_mr": identity.to_contract()}), encoding="utf-8")
    source, events = [], []

    def event(pid: int, kind: str, time: float, **updates) -> None:
        events.append(dict(event=kind, particle_id=pid, ion=pid, source_instance=1,
                           instrument_time_us=time, requested_time_us=time,
                           x_mm=10., y_mm=2., z_mm=-38.,
                           vx_mm_per_us=1., vy_mm_per_us=.1, vz_mm_per_us=10., **updates))

    for pid, birth in ((3, 0.), (11, .2), (67, 1.5)):
        source.append(dict(particle_id=pid, instrument_time_us=birth, mass_amu=524., charge_state=1.,
                           position_x_mm=10., position_y_mm=2., position_z_mm=-38.,
                           velocity_x_m_s=1000., velocity_y_m_s=100., velocity_z_m_s=10000.,
                           kinetic_energy_eV=1.))
        event(pid, "source_release", birth)
    for pid, times in ((3, [0., .5, 1., 2.]), (11, [.5]), (67, [2.])):
        for time in times:
            event(pid, "local_shared_time", time)
    # Actual rectangular x span is 10 mm, y span 4 mm: a square of y width would reject ID11.
    next(r for r in events if r["event"] == "local_shared_time" and r["particle_id"] == 11)["x_mm"] = 14.
    next(r for r in events if r["event"] == "local_shared_time" and r["particle_id"] == 3 and r["instrument_time_us"] == 2.)["z_mm"] = -20.
    event(3, "accelerator_grid1_forward", 1.8)
    events[-1]["z_mm"] = -36.
    event(3, "local_accelerator_exit", 2.1)
    events[-1]["z_mm"] = -6.
    event(3, "accelerator_exit_stop", 2.2)
    events[-1]["z_mm"] = -5.
    event(11, "local_native_stop", .7)
    events[-1]["source_instance"] = 0
    event(67, "local_timeout", 2.5)
    # Bake the native geometry/source/records; analysis must apply no observer rotation.
    for row in events:
        x, y, z = row["x_mm"], row["y_mm"], row["z_mm"]
        row.update(x_mm=y-2., y_mm=x-10., z_mm=-z-6., vx_mm_per_us=row["vy_mm_per_us"], vy_mm_per_us=row["vx_mm_per_us"], vz_mm_per_us=-row["vz_mm_per_us"])
    for row in source:
        row.update(position_x_mm=0., position_y_mm=0., position_z_mm=32., velocity_x_m_s=100., velocity_y_m_s=1000., velocity_z_m_s=-10000.)
    # Native +y physical face records: ID3 passes, ID11 reaches only pre,
    # ID67 has no forward face passage. These are synthetic test records.
    for pid, name, time, y in ((3, "local_aperture_pre", .3, .2),
                               (3, "local_aperture_post", .4, .4),
                               (11, "local_aperture_pre", .3, .2)):
        row = copy.deepcopy(next(r for r in events if r["particle_id"] == pid))
        row.update(event=name, instrument_time_us=time, requested_time_us=time, y_mm=y)
        events.extend(aperture_triplet(row))
    with (inputs / "release_global.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(source[0]))
        writer.writeheader()
        writer.writerows(source)
    path = root / "native.log"
    write_log(path, events)
    return path, events


def write_log(path: Path, events: list[dict]) -> None:
    lines = []
    # Preserve emitted triplets: the after endpoint's time exceeds the interpolated time.
    for row in events:
        fields = " ".join(f"{k}={format(v, '.17g')}" for k, v in row.items() if k != "event")
        lines.append(f"TRACE: {row['event']} {fields}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class LocalFrontendAnalysisTests(unittest.TestCase):
    def test_extracted_occupancy_preserves_legacy_checkpoint_moments_exactly(self):
        from integrations.analysis.plot_single_flight_spatial_six_panel import _checkpoint_distribution_summary
        from integrations.runtime.pulse_selection import SELECTION_ORDER, pulse_candidate_concentration

        bounds = dict(x_min=99e6,x_max=101e6,y_min=-101e6,y_max=-99e6,z_min=20.,z_max=40.)
        frontend = dict(native_frame_id="mrtof_global_cartesian",
                        accelerator_local_region=dict(first_gap_bounds_mm=bounds))
        rows = [dict(particle_id=i+1,event="local_shared_time",requested_time_us=.5,instrument_time_us=.5,
                     x_mm=1e8+(i%11)*.1,y_mm=-1e8+(i%5)*.07,z_mm=30.+(i%7)*.03,
                     vx_mm_per_us=.1+i*.001,vy_mm_per_us=1.,vz_mm_per_us=.02)
                for i in range(37)]
        census = [dict(particle_id=row["particle_id"],instrument_time_us=.5,status="active") for row in rows]
        actual_bounds = _capture_bounds(frontend)
        legacy = _checkpoint_distribution_summary(pd.DataFrame(rows),"pre_pulse_state",
                                                   frame_id=frontend["native_frame_id"],propagation_axis="y")
        candidate = dict(candidate_time_us=.5,pulse_eligible_count=37,
                         eligible_ids=list(range(1,38)),unsupported_ids=[],rankable=True)
        candidate.update(pulse_candidate_concentration(
            {a:legacy["space_mm"][a]["mean"]-actual_bounds[a]["center_mm"] for a in "xyz"},
            legacy["integration_frame_components"]["space_population_sigma_mm"],actual_bounds))
        expected = dict(status="selected",selected_time_us=.5,selection_order=SELECTION_ORDER,
                        selected=candidate,candidates=[candidate],capture_bounds_native_mm=actual_bounds,
                        native_frame_id=frontend["native_frame_id"],selection_uses_future_terminal_outcome=False)
        self.assertEqual(_select_pulse(rows,census,[.5],frontend),expected)

    def test_real_timeout_callback_after_native_terminal_remains_rejected(self):
        # Original batch_0001 stdout, N100 run 20261023_004408. Retain its
        # line numbers and raw states; the historical invalid snapshot stays invalid.
        raw = {
            9: "TRACE: source_release ion=1 particle_id=1 instrument_time_us=0 x_mm=0 y_mm=-96 z_mm=32 vx_mm_per_us=0 vy_mm_per_us=1.3569536221848404 vz_mm_per_us=0 requested_time_us=0 source_instance=1",
            3615: "TRACE: local_trajectory ion=1 particle_id=1 instrument_time_us=1699.9918918904266 x_mm=-0.011782018478642317 y_mm=26.901329364966092 z_mm=32.008557092438011 vx_mm_per_us=0.020912470906066464 vy_mm_per_us=1.8020387683178705 vz_mm_per_us=-0.00060219225409962425 requested_time_us=1699.9918918904266 source_instance=1",
            3616: "TRACE: local_shared_time ion=1 particle_id=1 instrument_time_us=1700 x_mm=-0.011626880324695766 y_mm=26.915759956019318 z_mm=32.008541828157199 vx_mm_per_us=0.017354255645305138 vy_mm_per_us=1.7574591614703639 vz_mm_per_us=-0.0031688677307731106 requested_time_us=1700 source_instance=1",
            11476: "TRACE: local_timeout ion=1 particle_id=1 instrument_time_us=1699.9998918904264 x_mm=-0.011628759044884656 y_mm=26.915569925720085 z_mm=32.00854216888537 vx_mm_per_us=0.017401598325002449 vy_mm_per_us=1.7580537334432187 vz_mm_per_us=-0.0031345175466008959 requested_time_us=1699.9998918904264 source_instance=1",
        }
        source = {1: dict(instrument_time_us=0., position_x_mm=0., position_y_mm=-96.,
                          position_z_mm=32., velocity_x_m_s=0.,
                          velocity_y_m_s=1356.9536221848404, velocity_z_m_s=0., mass_amu=524.)}
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "batch_0001__ids_000001_000010.stdout.log"
            log.write_text("\n".join(raw.get(n, "") for n in range(1, 11477)) + "\n", encoding="utf-8")
            events, _ = parse_local_logs([log], source)
            original = copy.deepcopy(events)
            with self.assertRaisesRegex(ValueError, "particle 1 native state follows terminal") as caught:
                _validate_lifetimes(events, source)
            message = str(caught.exception)
            self.assertIn(f"local_shared_time at {log}:3616 time_us=1700", message)
            self.assertIn(f"local_timeout at {log}:11476 time_us=1699.9998918904264", message)
            self.assertEqual(events, original)

    def test_all_local_acceleration_planes_use_native_mr_z_angle_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = fixture(root)
            intermediate = copy.deepcopy(next(r for r in events if r["event"] == "accelerator_grid1_forward"))
            intermediate.update(event="accelerator_intermediate2_forward", instrument_time_us=2., requested_time_us=2.)
            events.append(intermediate)
            write_log(log, events)
            analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)
            output = root / "results/local_frontend/discovery"
            evolution = json.loads((output / "checkpoint_evolution_metadata.json").read_text())
            checkpoints = {row["event"]: row for row in evolution["checkpoints"]}
            for name in ("source_release", "local_aperture_pre", "local_aperture_post"):
                self.assertEqual(checkpoints[name]["local_propagation_axis"], "y")
            for name in ("accelerator_grid1_forward", "accelerator_intermediate2_forward", "local_accelerator_exit"):
                self.assertEqual(checkpoints[name]["local_propagation_axis"], "z")
                components = checkpoints[name]["integration_frame_components"]
                self.assertAlmostEqual(components["theta_x_deg"]["signed_mean"], math.degrees(math.atan2(.1, 10.)))
                self.assertAlmostEqual(components["theta_y_deg"]["signed_mean"], math.degrees(math.atan2(1., 10.)))

    def test_complete_native_census_actual_snapshots_and_native_mr_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = fixture(root)
            recrossing = copy.deepcopy(next(r for r in events if r["event"] == "accelerator_grid1_forward"))
            recrossing.update(instrument_time_us=1.9, requested_time_us=1.9)
            events.append(recrossing)
            write_log(log, events)
            result = analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)
            output = root / "results/local_frontend/discovery"
            self.assertEqual((result["mother_count"], result["exit_count"], result["loss_count"]), (3, 1, 2))
            checkpoints = pd.read_csv(output / "checkpoints.csv")
            self.assertEqual((checkpoints.event == "accelerator_grid1_forward").sum(), 1)
            self.assertEqual(result["selected_pulse_time_us"], .5)
            pulse = json.loads((output / "pulse_selection.json").read_text())
            self.assertEqual(pulse["selected"]["eligible_ids"], [3, 11])
            self.assertEqual(pulse["capture_bounds_native_mm"]["y"]["full_width_mm"], 10.)
            census = pd.read_csv(output / "all_shared_time_census.csv")
            self.assertEqual(len(census), 3 * len(_TIMES))
            self.assertEqual(census.loc[(census.particle_id == 67) & (census.instrument_time_us == 1.), "status"].item(), "not_born")
            counts = pd.read_csv(output / "all_shared_time_status_counts.csv")
            self.assertTrue((counts[["not_born", "active", "already_exit", "already_loss", "numerical_unsupported"]].sum(axis=1) == 3).all())
            self.assertEqual(counts.iloc[-1]["active"], 0)
            active = pd.read_csv(output / "active_shared_states_mr.csv")
            self.assertFalse(((active.particle_id == 11) & (active.instrument_time_us > .7)).any())
            losses = pd.read_csv(output / "all_losses.csv")
            self.assertEqual(set(losses.particle_id), {11, 67})
            native = losses.loc[losses.particle_id == 11].iloc[0]
            self.assertEqual(native.source_instance, 0)
            self.assertIn("TRACE: local_native_stop", native.raw_line)
            self.assertEqual(result["mr_exit_statistics"]["observer_frame_components"]["frame"], "mrtof_global_cartesian")
            exits = pd.read_csv(output / "exit_states_mr.csv")
            self.assertEqual(exits.z_mm.item(), 0.)
            self.assertEqual(exits.vz_mm_per_us.item(), -10.)
            self.assertEqual(exits.vx_mm_per_us.item(), .1)
            self.assertTrue((output / "shared_time_distributions.png").is_file())
            evolution = json.loads((output / "checkpoint_evolution_metadata.json").read_text())
            self.assertEqual(evolution["checkpoints"][0]["local_propagation_axis"], "y")
            self.assertEqual(evolution["exit_phase_portrait"]["frame"], "mrtof_global_cartesian")
            self.assertEqual(exits.z_mm.item(), next(r["z_mm"] for r in events if r["event"] == "local_accelerator_exit"))
            with self.assertRaises(ValueError):
                analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)

    def test_aperture_first_pass_cohorts_preserve_recrossings_and_unresolved_losses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = fixture(root)
            duplicate = copy.deepcopy(next(r for r in events if r["event"] == "local_aperture_pre" and r["particle_id"] == 3))
            duplicate.update(instrument_time_us=.6, requested_time_us=.6)
            events.extend(aperture_triplet(duplicate))
            write_log(log, events)
            result = analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)
            aperture = result["aperture_passages"]
            self.assertEqual(aperture["recorded_passage_stage_counts"], dict(before_pre=1, between_faces=1, after_post=1))
            self.assertEqual((aperture["mother_count"], aperture["pre_count"], aperture["post_count"]), (3, 2, 1))
            self.assertEqual(aperture["paired_ids"], [3])
            self.assertEqual(aperture["cohorts"]["pre_own"]["particle_ids"], [3, 11])
            for name in ("paired_pre", "paired_post"):
                cohort = aperture["cohorts"][name]
                self.assertEqual(cohort["particle_ids"], [3])
                metrics = cohort["statistics"]["integration_frame_components"]
                self.assertEqual(set(metrics["local_transverse_angles_deg"]), {"theta_x_y", "theta_z_y"})
                self.assertIsNone(metrics["theta_x_deg"])
            output = root / "results/local_frontend/discovery"
            raw = pd.read_csv(output / "all_native_events.csv")
            self.assertEqual((raw.event == "local_aperture_pre").sum(), 3)
            checkpoints = pd.read_csv(output / "checkpoints.csv")
            self.assertEqual((checkpoints.event == "local_aperture_pre").sum(), 2)
            evolution = pd.read_csv(output / "checkpoint_evolution.csv")
            self.assertIn("theta_x_y_population_std_deg", evolution)
            self.assertTrue((evolution.loc[evolution.event.str.startswith("local_aperture"), "local_propagation_axis"] == "y").all())
            losses = pd.read_csv(output / "all_losses.csv")
            self.assertEqual(losses.loc[losses.particle_id == 11, "terminal_class"].item(), "native_stop_unresolved")

    def test_aperture_linear_6d_checkpoint_preserves_overshooting_native_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = fixture(root)
            index = next(i for i, r in enumerate(events) if r["event"] == "local_aperture_pre" and r["particle_id"] == 3)
            before, after, crossing = events[index - 2:index + 1]
            before.update(instrument_time_us=.299, requested_time_us=.299, y_mm=.199,
                          x_mm=.1, z_mm=32., vx_mm_per_us=.2, vy_mm_per_us=.9, vz_mm_per_us=-.3)
            after.update(instrument_time_us=.301, requested_time_us=.301, y_mm=.20000004341033844,
                         x_mm=.11, z_mm=31.9, vx_mm_per_us=.4, vy_mm_per_us=1.1, vz_mm_per_us=-.1)
            fraction = (.2 - before["y_mm"]) / (after["y_mm"] - before["y_mm"])
            for key in ("instrument_time_us", "x_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us"):
                crossing[key] = before[key] + fraction * (after[key] - before[key])
            crossing["requested_time_us"] = crossing["instrument_time_us"]
            write_log(log, events)
            # Vendor progress text is permitted between consecutive TRACE events.
            log.write_text(log.read_text().replace("\n", "\nstatus,progress\n"), encoding="utf-8")
            result = analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)
            self.assertEqual(result["aperture_passages"]["pre_count"], 2)
            output = root / "results/local_frontend/discovery"
            raw = pd.read_csv(output / "all_native_events.csv")
            endpoint = raw.loc[(raw.event == "local_aperture_pre_step_after") & (raw.particle_id == 3)].iloc[0]
            self.assertGreater(endpoint.y_mm, .2)
            checkpoints = pd.read_csv(output / "checkpoints.csv")
            row = checkpoints.loc[(checkpoints.event == "local_aperture_pre") & (checkpoints.particle_id == 3)].iloc[0]
            self.assertEqual(row.y_mm, .2)
            self.assertAlmostEqual(row.interpolation_fraction, fraction)
            self.assertEqual(row.plane_landing_basis, "same_native_step_linear_6d_plane_interpolation")
            self.assertEqual(row.step_after_raw_line_number, endpoint.raw_line_number)
            self.assertLess(row.instrument_time_us, endpoint.instrument_time_us)
            self.assertAlmostEqual(row.vx_mm_per_us, crossing["vx_mm_per_us"])

    def test_aperture_endpoint_contract_rejects_unsupported_or_fabricated_crossings(self) -> None:
        for mutation in ("missing_before", "order", "pid", "instance", "clock", "reverse_time",
                         "nonzero_without_bracket", "zero_off_plane", "zero_changed_velocity", "state", "direction"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log, events = fixture(root)
                index = next(i for i, r in enumerate(events) if r["event"] == "local_aperture_pre")
                before, after, crossing = events[index - 2:index + 1]
                if mutation == "missing_before":
                    events.remove(before)
                elif mutation == "order":
                    events[index - 2], events[index - 1] = after, before
                elif mutation == "pid":
                    before["particle_id"] = 11
                elif mutation == "instance":
                    before["source_instance"] = 0
                elif mutation == "clock":
                    crossing["requested_time_us"] += .001
                elif mutation == "reverse_time":
                    before["instrument_time_us"] += .001
                    before["requested_time_us"] = before["instrument_time_us"]
                elif mutation == "nonzero_without_bracket":
                    before.update(instrument_time_us=.299, requested_time_us=.299)
                elif mutation == "zero_off_plane":
                    for row in (before, after, crossing):
                        row["y_mm"] += 4.3410338435e-8
                elif mutation == "zero_changed_velocity":
                    after["vx_mm_per_us"] += .01
                elif mutation == "state":
                    crossing["vx_mm_per_us"] += .01
                else:
                    crossing["vy_mm_per_us"] = -1.
                write_log(log, events)
                source = _source_rows(root / "inputs/release_global.csv")
                parsed, _ = parse_local_logs([log], source)
                lives = _validate_lifetimes(parsed, source)
                frontend = json.loads((root / "inputs/frontend_contract.json").read_text())
                with self.assertRaises(ValueError):
                    _aperture_passages(parsed, source, lives, frontend)

    def test_aperture_wrong_face_direction_or_missing_pre_fails_closed(self) -> None:
        for mutation in ("position", "direction", "missing_pre"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log, events = fixture(root)
                if mutation == "missing_pre":
                    events = [r for r in events if not (r["event"] == "local_aperture_pre" and r["particle_id"] == 3)]
                else:
                    row = next(r for r in events if r["event"] == "local_aperture_post")
                    row["y_mm" if mutation == "position" else "vy_mm_per_us"] = 10. if mutation == "position" else -1.
                write_log(log, events)
                with self.assertRaises(ValueError):
                    analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)

    def test_missing_active_snapshot_is_unsupported_not_interpolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = fixture(root)
            events = [r for r in events if not (r["event"] == "local_shared_time" and r["particle_id"] == 3 and r["instrument_time_us"] == 1.)]
            write_log(log, events)
            result = analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)
            self.assertEqual(result["shared_unsupported_count"], 1)
            candidates = json.loads((root / "results/local_frontend/discovery/pulse_selection.json").read_text())["candidates"]
            self.assertFalse(next(c for c in candidates if c["candidate_time_us"] == 1.)["rankable"])

    def test_missing_duplicate_terminal_bad_clock_and_after_death_fail_closed(self) -> None:
        for mutation in ("missing", "duplicate", "clock", "after_death"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log, events = fixture(root)
                if mutation == "missing":
                    events = [r for r in events if r["event"] != "local_timeout"]
                elif mutation == "duplicate":
                    events.append(copy.deepcopy(next(r for r in events if r["event"] == "local_timeout")))
                elif mutation == "clock":
                    next(r for r in events if r["particle_id"] == 3 and r["event"] == "source_release")["instrument_time_us"] = .1
                else:
                    row = copy.deepcopy(next(r for r in events if r["event"] == "local_native_stop"))
                    row.update(event="local_trajectory", instrument_time_us=3., requested_time_us=3.)
                    events.append(row)
                write_log(log, events)
                with self.assertRaises(ValueError):
                    analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)

    def test_post_flight_rotation_is_rejected_for_native_mr_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, _ = fixture(root)
            path = root / "inputs/registration.json"
            observer = RigidTransform("mrtof_global_cartesian", "mrtof_global_cartesian", [[0, 1, 0], [1, 0, 0], [0, 0, -1]], [0., 0., 0.])
            path.write_text(json.dumps({"observer_to_mr": observer.to_contract()}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity observer"):
                analyze_local_frontend(root, [log], phase="discovery", shared_times_us=_TIMES)

    def test_zero_exits_remain_negative_results_with_all_losses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events = fixture(root)
            events = [r for r in events if r["event"] != "local_accelerator_exit"]
            next(r for r in events if r["event"] == "accelerator_exit_stop")["event"] = "local_timeout"
            write_log(log, events)
            result = analyze_local_frontend(root, [log], phase="extraction", shared_times_us=_TIMES, pulse_time_us=.5)
            self.assertEqual(result["exit_count"], 0)
            self.assertIsNone(result["mr_exit_statistics"])
            self.assertEqual(len(pd.read_csv(root / "results/local_frontend/extraction/all_losses.csv")), 3)


if __name__ == "__main__":
    unittest.main()
