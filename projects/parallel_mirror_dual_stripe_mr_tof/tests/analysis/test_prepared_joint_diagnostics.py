"""Synthetic measured-source diagnostics: complete evidence and headless figures."""
from __future__ import annotations

import csv
import json
import math
import re
import shutil
import sys
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import (
    materialize_measured_source, materialize_measured_source_slice,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import main, merge_measured_event_logs
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_diagnostics import (
    _design_reference, _prism_rows, _prism_statistics, _snapshot_rows, analyze_prepared_joint_flight,
    _trajectory_lifetimes, _validate_birth_clock_projection, build_prism_figure,
)
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_measured_component_source as fixtures


class PreparedJointDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        producer = self.fixture.fixture
        (self.root / "simion").mkdir()
        for name in ("events.csv", "samples.csv"):
            (self.root / "simion" / name).write_text(
                "particle_id,t_us,x_mm\n9,0,1\n9,21,2\n1,22,3\n", encoding="utf-8")
        self.manifest = self.root / "run_manifest.json"
        producer._write(self.manifest, {"inputs": {}, "outputs": [file_record(p) for p in (self.root / "simion").iterdir()]})
        producer.receipt["inputs"]["run_manifest.json"] = file_record(self.manifest)
        producer._write(producer.receipt_path, producer.receipt)
        handoff = self.root / "diagnostic_handoff"
        prepare_handoff(producer.receipt_path, producer.trajectory, producer.provider, producer.request, handoff)
        self.source = self.root / "measured_source"
        materialize_measured_source(handoff / "handoff_receipt.json", self.source)
        policy = dict(schema_version=1, mode="fixed_interval", interval_us=.1,
                      retention_class="solver_review", reason="synthetic evidence test", output_budget_bytes=2000000)
        contract = self.root / "contract.json"
        producer._write(contract, {"coordinate_system": {"frame_id": "mr_frame.v2"}, "simion": {"trajectory_recording": policy}})
        point = self.root / "operating_point.lua"
        point.write_text("return {}\n", encoding="utf-8")
        reference = self.root / "reference_materialization.json"
        producer._write(reference, {"target_low_field_tangent_ratio_vy_over_vz": .035,
                                    "target_nominal_injection_angle_degrees": math.degrees(math.atan(.035)),
                                    "target_positive_mirror_turn_y_mm": 0,
                                    "p2_low_field_reference_section": {"reference_plane_project_z_mm": 33,
                                         "transit_aperture_project_mm": {"x_mm": [-2, 2], "y_mm": [-32, 3]}}})
        self.preparation = self.root / "prepared_joint_trial.json"
        source = json.loads((self.source / "source_receipt.json").read_text())
        self.prepared = dict(schema_version=1, role="mrtof_prepared_joint_trial", measured_source_directory=str(self.source),
                             source_receipt=file_record(self.source / "source_receipt.json"),
                             trajectory_contract=file_record(contract), operating_point=file_record(point),
                             reference_materialization=file_record(reference), trajectory_recording=policy,
                             expected_particle_ids=[1, 7], mother_particle_count=3,
                             solver_epoch_instrument_time_us=source["solver_epoch_instrument_time_us"])
        binding_path = self.root / "field_binding.json"
        producer._write(binding_path, {"fixture": "native geometry is mocked; no PA is read"})
        self.prepared["field_binding"] = file_record(binding_path)
        geometry = {key: [] for key in ("mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot",
                    "mirror_ground_shields", "mirror_e_closures", "stripe_electrodes", "stripe_slot",
                    "central_ground_electrodes", "central_ground_slots", "prism_electrodes", "prism_ground_shields")}
        geometry["frame_id"] = "mr_frame.v2"
        binding_mock = patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_diagnostics.load_binding",
                             return_value=dict(geometry=geometry, refinement_windows=[]))
        binding_mock.start()
        self.addCleanup(binding_mock.stop)
        producer._write(self.preparation, self.prepared)
        self.log = self.root / "merged.log"
        self.original_lines = []
        for row in producer.rows:
            particle, birth = row["particle_id"], row["instrument_time_us"]
            for phase, t in (("birth", birth), ("step", birth+1), ("terminal", birth+2)):
                position = (row["position_x_mm"], row["position_y_mm"]-225, row["position_z_mm"])
                velocity = tuple(row[f"velocity_{axis}_m_s"]/1000 for axis in "xyz")
                if phase == "terminal":
                    position, velocity = (.1, -10, 33), (.05, .1, 37.8)
                self.original_lines.append(f"MRTOF_TRAJECTORY ion={particle} phase={phase} t_us={t:.17g} " +
                    " ".join(f"{key}={value:.17g}" for key, value in zip(("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"), (*position, *velocity))))
            self.original_lines.extend((
                f"MRTOF_EVENT prism_pass ion={particle} n=1 t_us={birth+.5:.12g} x_mm=.1 y_mm=-50 z_mm=-101 vx_mm_us=.05 vy_mm_us=.1 vz_mm_us=-37.8",
                f"MRTOF_EVENT p2_low_field_crossing ion={particle} t_us={birth+1:.12g} x_mm=.1 y_mm=-10 z_mm=33 vx_mm_us=.05 vy_mm_us={.1 if particle==1 else -.1} vz_mm_us=37.8 inside_aperture={1 if particle==1 else 0} direction_ok={1 if particle==1 else 0}"))
            if particle == 1:
                self.original_lines.append(f"MRTOF_EVENT detector ion=1 t_us={birth+2:.12g} x_mm=.1 y_mm=-10 z_mm=33")
            self.original_lines.append(f"MRTOF_EVENT terminal ion={particle} splat={1 if particle==1 else -1} t_us={birth+2:.12g} x_mm=.1 y_mm=-10 z_mm=33 vx_mm_us=.05 vy_mm_us=.1 vz_mm_us=37.8 turns=49 central_crossings=49")
        self.original_lines.append("status,Fly completed. 2 splats")
        self.log.write_text("\n".join(self.original_lines)+"\n", encoding="utf-8")
        self.output = self.root / "diagnostics"

    def test_full_pipeline_preserves_mother_raw_branches_losses_and_figures(self) -> None:
        before = self.log.read_bytes()
        result = analyze_prepared_joint_flight(self.preparation, self.log, self.output)
        self.assertEqual(result["counts"]["mother_source"], 3)
        self.assertEqual(result["counts"]["detected"], 1)
        self.assertEqual(result["counts"]["downstream_loss"], 1)
        self.assertEqual(result["counts"]["upstream_not_transferred"], 1)
        self.assertEqual(result["prism_statistics"]["p2_fixed_plane"]["outside_aperture_ids"], [7])
        self.assertEqual(result["prism_statistics"]["p2_fixed_plane"]["missing_mother_particle_ids"], [9])
        self.assertEqual(len(list(self.output.glob("*.png"))), 4)
        self.assertEqual(len(list(self.output.glob("*.svg"))), 4)
        self.assertEqual(len(list(self.output.glob("*.metadata.json"))), 4)
        with (self.output / "loss_acceptance.csv").open(newline="") as stream:
            loss_rows = list(csv.DictReader(stream))
        self.assertEqual({int(r["particle_id"]) for r in loss_rows}, {1, 7, 9})
        self.assertEqual(loss_rows[2]["source_position_x_mm"], "")
        self.assertEqual(result["loss_acceptance"]["group_counts"],
                         {"detected": 1, "early_contact": 1, "not_transferred": 1})
        with (self.output / "prism_phase_space.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({int(r["particle_id"]) for r in rows}, {1, 7})
        p2 = [r for r in rows if r["stage"] == "p2_fixed_plane"]
        self.assertEqual(len(p2), 2)
        self.assertTrue(any(r["inside_aperture"] == "0.0" for r in p2))
        self.assertLess(float(p2[1]["signed_yz_angle_deg"]), 0)
        losses = self.output / "loss_evidence"
        down = [json.loads(line) for line in (losses / "particle_00007.jsonl").read_text().splitlines()]
        expected = [(i, line+"\n") for i, line in enumerate(self.original_lines, 1) if "ion=7 " in line]
        self.assertEqual([(r["line_number"], r["raw_line"]) for r in down], expected)
        self.assertEqual(len((losses / "particle_00009.jsonl").read_text().splitlines()), 4)
        with (self.output / "timed_spatial_clouds.csv").open(newline="") as stream:
            snapshots = list(csv.DictReader(stream))
        self.assertEqual(len(snapshots), result["snapshot_count"]*3)
        self.assertTrue(all(r["x_mm"] == "" for r in snapshots if r["particle_id"] == "9"))
        self.assertTrue(any(r["state"] == "not_yet_handed_off" for r in snapshots))
        self.assertEqual(before, self.log.read_bytes())

    def test_missing_or_changed_native_binding_fails_before_output(self) -> None:
        binding = self.prepared["field_binding"]
        for mode in ("missing", "changed"):
            with self.subTest(mode=mode):
                value = dict(self.prepared)
                if mode == "missing":
                    del value["field_binding"]
                else:
                    value["field_binding"] = dict(binding, sha256="0"*64)
                self.preparation.write_text(json.dumps(value))
                output = self.root / ("rejected_binding_"+mode)
                with self.assertRaises((KeyError, ValueError, AssertionError)):
                    analyze_prepared_joint_flight(self.preparation, self.log, output)
                self.assertFalse(output.exists())

    def test_default_cli_transports_real_batches_without_mutating_preparation(self) -> None:
        epoch = self.prepared["solver_epoch_instrument_time_us"]
        pairs = []
        for ordinal, particle in enumerate((1, 7), 1):
            directory = self.root / f"batch_{ordinal}"
            directory.mkdir()
            receipt = materialize_measured_source_slice(self.source, directory / "measured_source", ordinal, ordinal)
            shutil.copyfile(directory / "measured_source/source.fly2", directory / "joint.fly2")
            receipt_path, log = directory / "batch_receipt.json", directory / "flight.log"
            receipt_path.write_text(json.dumps(receipt))
            lines = [re.sub(r"t_us=[^ ]+", f"t_us={epoch:.17g}", line)
                     if "phase=birth" in line else line
                     for line in self.original_lines if f"ion={particle} " in line]
            log.write_text("\n".join(lines)+"\nstatus,Fly completed. 1 splats\n")
            pairs.append((log, receipt_path))
        before = self.preparation.read_bytes()
        merge_path = self.root / "batch_log_merge_receipt.json"
        merged = merge_measured_event_logs(batches=pairs, preparation_path=self.preparation,
                                          output_path=self.log, receipt_path=merge_path)
        # The normal CLI must consume the merge role without a second entrypoint.
        with patch.object(sys, "argv", ["mrtof_batch_flight", "analyze-joint", "--preparation", str(self.preparation),
                                        "--log", str(self.log), "--output", str(self.output)]):
            self.assertEqual(main(), 0)
        self.assertEqual(self.preparation.read_bytes(), before)
        result = json.loads((self.output / "diagnostics_receipt.json").read_text())
        self.assertEqual(result["counts"]["mother_source"], 3)
        self.assertEqual(result["birth_clock_projection"]["projected_particle_ids"], [7])
        self.assertEqual(result["inputs"]["batch_log_merge_receipt"], file_record(merge_path))
        for path in self.output.glob("*.metadata.json"):
            metadata = json.loads(path.read_text())
            self.assertEqual(metadata["inputs"]["batch_log_merge_receipt"], file_record(merge_path))
        self.assertEqual(len(list(self.output.glob("*.png"))), 4)
        evidence = result["birth_clock_projection"]["authority"]["actual_launch_evidence"]
        self.assertEqual(evidence["verified_particle_count"], 2)
        self.assertEqual([row["verified_particle_ids"] for row in evidence["batches"]], [[1], [7]])
        # Independently reject changed prep/log, missing records, and duplicate IDs.
        for name in ("preparation", "merged_log", "missing_source", "bad_source", "missing_log", "empty", "duplicate", "wrong_mother", "conflict"):
            with self.subTest(name=name):
                value = json.loads(json.dumps(merged))
                if name in ("preparation", "merged_log"):
                    value[name]["sha256"] = "0" * 64
                elif name == "missing_source":
                    del value["batches"][0]["fly2"]
                elif name == "bad_source":
                    value["batches"][0]["fly2"]["sha256"] = "0" * 64
                elif name == "missing_log":
                    del value["batches"][0]["log"]
                elif name == "empty":
                    value["batches"] = []
                elif name == "duplicate":
                    value["batches"][1] = value["batches"][0]
                elif name == "wrong_mother":
                    value["mother_particle_count"] += 1
                else:
                    self.prepared["completed_source_batches"] = list(reversed(value["batches"]))
                    self.preparation.write_text(json.dumps(self.prepared))
                    value["preparation"] = file_record(self.preparation)
                merge_path.write_text(json.dumps(value))
                with self.assertRaises((ValueError, AssertionError, KeyError)):
                    analyze_prepared_joint_flight(self.preparation, self.log, self.root / f"reject_{name}",
                                                 merge_receipt=merge_path)

    def test_signed_angle_uses_full_quadrant_and_preserves_raw_repeats(self) -> None:
        source = self.fixture.fixture.rows[0]
        states = {1: source}
        base = dict(kind="p2_low_field_crossing", ion=1, t_us=7501, x_mm=0, y_mm=0, z_mm=33,
                    vx_mm_us=0, vy_mm_us=1, vz_mm_us=-1, inside_aperture=0, direction_ok=0)
        rows = _prism_rows([base, dict(base, t_us=7502)], states)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["signed_yz_angle_deg"], 135)
        self.assertEqual([r["first_recorded_crossing"] for r in rows], [1, 0])
        self.assertAlmostEqual(rows[0]["K_per_charge_eV"], sum(rows[0][key+"_per_charge_eV"] for key in ("Ex", "Ey", "Ez")))

    def test_snapshot_no_extrapolation_and_lost_last_position_is_not_alive(self) -> None:
        path = self.root / "sample.csv"
        path.write_text("ion,phase,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n1,birth,9,0,0,0,1,0,0\n1,terminal,12,2,0,0,1,0,0\n", encoding="utf-8")
        lifetime = {1: {"birth": 10., "terminal": 12., "terminal_state": {key: float(key=="x_mm")*2 for key in ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")}}}
        times = [{"label": str(t), "instrument_time_us": t} for t in (9., 11., 13.)]
        rows, gap = _snapshot_rows(path, lifetime, [{"particle_id": "1"}], {1: "loss"}, times)
        self.assertEqual([r["state"] for r in rows], ["not_yet_handed_off", "alive", "loss"])
        self.assertEqual([r["x_mm"] for r in rows], ["", 1., 2.])
        self.assertEqual(gap, 2)
        self.assertIn("1,birth,9,", path.read_text())  # Raw initialize clock is retained.

    def test_angle_statistics_do_not_average_reverse_beams_to_zero(self) -> None:
        source = self.fixture.fixture.rows[0]
        base = dict(kind="p2_low_field_crossing", ion=1, t_us=7501, x_mm=0, y_mm=0, z_mm=33,
                    vx_mm_us=0, vy_mm_us=.01, vz_mm_us=-1, inside_aperture=1, direction_ok=0)
        rows = _prism_rows([base, dict(base, ion=7, vy_mm_us=-.01)], {1: source, 7: source})
        for row in rows:
            row.update(raw_signed_angle_difference_to_reference_deg="", positive_turn_y_difference_to_reference_mm="")
        result = _prism_statistics(rows, {1, 7, 9})["p2_fixed_plane"]
        self.assertAlmostEqual(abs(result["signed_yz_circular_mean_deg"]), 180)
        self.assertEqual(result["nonpositive_vz_ids"], [1, 7])
        self.assertEqual(result["missing_mother_particle_ids"], [9])

    def test_missing_bound_target_is_explicit_and_figure_labels_are_english(self) -> None:
        self.assertIn("unavailable", _design_reference({}, self.root)["status"])
        design = _design_reference(self.prepared, self.root)
        figure, axes = build_prism_figure([], 3, design)
        self.addCleanup(lambda: __import__("matplotlib.pyplot", fromlist=["close"]).close(figure))
        self.assertEqual(axes.shape, (4, 2))
        self.assertIn("atan2", axes[1, 1].get_ylabel())
        self.assertTrue(axes[0, 1].patches)
        self.assertTrue(axes[1, 1].lines)

    def test_unknown_identity_and_tampered_preparation_rejected_before_output(self) -> None:
        value = dict(self.prepared, expected_particle_ids=[1, 99])
        self.fixture.fixture._write(self.preparation, value)
        with self.assertRaisesRegex(ValueError, "ID/clock/mother"):
            analyze_prepared_joint_flight(self.preparation, self.log, self.output)
        self.assertFalse(self.output.exists())

    def test_trajectory_terminal_must_match_actual_terminal_event(self) -> None:
        path = self.root / "terminal_mismatch.csv"
        path.write_text("ion,phase,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n1,birth,10,0,0,0,1,0,0\n1,terminal,11,2,0,0,1,0,0\n", encoding="utf-8")
        source = {1: {"instrument_time_us": "10", "position_x_mm": "0", "position_y_mm": "0", "position_z_mm": "0",
                      "velocity_x_m_s": "1000", "velocity_y_m_s": "0", "velocity_z_m_s": "0"}}
        terminal = {1: {"t_us": 11., "x_mm": 3., "y_mm": 0., "z_mm": 0., "vx_mm_us": 1., "vy_mm_us": 0., "vz_mm_us": 0.}}
        with self.assertRaisesRegex(ValueError, "terminal differs"):
            _trajectory_lifetimes(path, source, terminal)

    def test_initialize_zero_clock_projects_only_birth_in_full_pipeline(self) -> None:
        epoch = self.prepared["solver_epoch_instrument_time_us"]
        lines = []
        for line in self.log.read_text().splitlines():
            if line.startswith("MRTOF_TRAJECTORY") and "phase=birth" in line:
                import re
                line = re.sub(r"t_us=[^ ]+", f"t_us={epoch:.17g}", line)
            lines.append(line)
        self.log.write_text("\n".join(lines)+"\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "actual launched batch FLY2"):
            analyze_prepared_joint_flight(self.preparation, self.log, self.root / "rejected_without_launch_evidence")
        batch_receipt = self.root / "actual_batch_receipt.json"
        self.fixture.fixture._write(batch_receipt, dict(schema_version=1, role="mrtof_measured_source_batch",
            original_particle_ids=[1, 7], count=2, solver_epoch_instrument_time_us=epoch,
            outputs={"source": file_record(self.source / "source.fly2")}))
        self.prepared["completed_source_batches"] = [dict(batch_receipt=file_record(batch_receipt),
            fly2=file_record(self.source / "source.fly2"), log=file_record(self.log))]
        self.fixture.fixture._write(self.preparation, self.prepared)
        result = analyze_prepared_joint_flight(self.preparation, self.log, self.output)
        self.assertEqual(result["birth_clock_projection"]["projected_particle_ids"], [7])
        self.assertFalse(result["birth_clock_projection"]["raw_trajectory_csv_modified"])
        with (self.output / "trajectory_samples.csv").open(newline="") as handle:
            births = [r for r in csv.DictReader(handle) if r["phase"] == "birth"]
        self.assertEqual([float(row["t_us"]) for row in births], [epoch, epoch])
        with (self.output / "birth_clock_projection.csv").open(newline="") as handle:
            projected = list(csv.DictReader(handle))
        self.assertGreater(float(projected[1]["canonical_birth_time_us"]), epoch)

    def test_real_r05_initialize_clock_fixture_preserves_exact_6D_and_rejects_wrong_data(self) -> None:
        # Literal r05 ID1 rows, 20261016_200610 joint run; this regression is
        # self-contained and does not require historical artifacts in checkout.
        path = self.root / "r05_id1.csv"
        text = ("ion,phase,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n"
                "1,birth,7500.6336496307204,-0.046005478801127903,-54.356897566724996,0,0.213750156364789,0.18279108857989901,-40.130961605510699\n"
                "1,step,7500.7029782765412,-0.031982482087465354,-54.344887411366336,-2.636184518095293,0.21340927437750681,0.18279111858948449,-40.121508700683691\n"
                "1,terminal,7512.7064065971335,-2.5103975573863693,-33.898256896807105,-107.00000007015036,-0.011795142005426945,1.9079793421804718,40.077272571627141\n")
        path.write_text(text, encoding="utf-8")
        source = {1: dict(instrument_time_us="7500.63727401505", position_x_mm="-0.0460054788011279",
                         position_y_mm="-54.356897566724996", position_z_mm="0.0", velocity_x_m_s="213.750156364789",
                         velocity_y_m_s="182.791088579899", velocity_z_m_s="-40130.961605510696")}
        raw_terminal = list(csv.DictReader(text.splitlines()))[-1]
        terminal = {1: {key: float(f"{float(raw_terminal[key]):.12g}") for key in ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")}}
        result = _trajectory_lifetimes(path, source, terminal, initialization_epoch_us=7500.63364963072)
        self.assertEqual(result[1]["birth"], 7500.63727401505)
        self.assertEqual(result[1]["raw_birth_time_us"], 7500.63364963072)
        self.assertTrue(result[1]["six_dimensional_state_exact"])
        self.assertEqual(result[1]["first_subsequent_time_us"], 7500.7029782765412)
        self.assertEqual(path.read_text(), text)
        for changed, message in ((text.replace("-0.046005478801127903", "-0.046006"), "canonical 6D"),
                                 (text.replace("7500.6336496307204", "7500.6336506307204"), "neither canonical TOB"),
                                 (text.replace("7500.7029782765412", "7500.634"), "precedes canonical")):
            path.write_text(changed, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                _trajectory_lifetimes(path, source, terminal, initialization_epoch_us=7500.63364963072)

    def test_fly2_must_keep_real_non_simultaneous_birth_offsets(self) -> None:
        source_path = self.source / "source_receipt.json"
        source = json.loads(source_path.read_text())
        with (self.source / "component_particle_state.csv").open(newline="") as handle:
            states = {int(r["particle_id"]): r for r in csv.DictReader(handle)}
        result = _validate_birth_clock_projection(source, states, self.source)
        self.assertEqual(result["verified_particle_count"], 2)
        fly_path = self.source / "source.fly2"
        import re
        fly_path.write_text(re.sub(r"\btob = [^,]+,", "tob = 0,", fly_path.read_text()), encoding="utf-8")
        source["outputs"]["source"] = file_record(fly_path)
        with self.assertRaisesRegex(ValueError, "birth offset differs"):
            _validate_birth_clock_projection(source, states, self.source)


if __name__ == "__main__":
    unittest.main()
