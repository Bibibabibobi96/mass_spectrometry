from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common.contracts.particle_physics import kinetic_energy_ev

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from projects.rf_quadrupole_collision_cooling.analysis import (
    analyze_rf_oatof_checkpoints as module,
)


class RfOatofCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.baseline = REPO_ROOT / "projects" / "oa_tof" / "config" / "baseline.json"
        self.s2 = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"
        self.joint = PROJECT_ROOT / "config" / "rf_to_oatof_shared_physical_port_joint_geometry.json"
        self.contract = PROJECT_ROOT / "config" / "rf_to_oatof_checkpoint_diagnostic.json"
        baseline = json.loads(self.baseline.read_text(encoding="utf-8"))
        center = baseline["particle_source"]
        self.center = np.array([center[f"center_{axis}_mm"] for axis in "xyz"], dtype=float)
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        rows = []
        for particle_id in range(1, 6):
            rows.append({
                "particle_id": particle_id,
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch.v1",
                "instrument_time_us": 1.0,
                "mass_amu": 100.0,
                "charge_state": 1,
                "position_x_mm": self.center[0] - 1.0,
                "position_y_mm": 0.05 * particle_id,
                "position_z_mm": self.center[2] + 0.02 * particle_id,
                "velocity_x_m_s": 1000.0,
                "velocity_y_m_s": 5.0 * particle_id,
                "velocity_z_m_s": -2.0 * particle_id,
            })
        self.exit_path = self.root / "exit.csv"
        pd.DataFrame(rows).to_csv(self.exit_path, index=False)

        capture_rows = []
        for particle_id, residual_x in ((1, 0.0), (2, 0.2), (3, 0.4)):
            source = rows[particle_id - 1]
            capture_rows.append({
                "particle_id": particle_id,
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch.v1",
                "instrument_time_us": 2.0,
                "x_mm": self.center[0] + residual_x,
                "y_mm": source["position_y_mm"] + source["velocity_y_m_s"] / 1000,
                "z_mm": source["position_z_mm"] + source["velocity_z_m_s"] / 1000,
                "vx_m_s": source["velocity_x_m_s"] + 10 * particle_id,
                "vy_m_s": source["velocity_y_m_s"],
                "vz_m_s": source["velocity_z_m_s"],
                "inside_oatof_ideal_reference_volume": True,
                "active_at_pulse": True,
            })
        self.capture_path = self.root / "capture.csv"
        pd.DataFrame(capture_rows).to_csv(self.capture_path, index=False)

        terminal_rows = []
        for particle_id in range(1, 6):
            active = particle_id <= 3
            terminal_rows.append({
                "particle_id": particle_id,
                "frame_id": "oatof_global",
                "clock_epoch_id": "instrument_clock_epoch.v1",
                "event": "local_accelerator_exit" if active else (
                    "terminal" if particle_id == 3 else "downstream_entry_wall"),
                "status": "transmitted" if active else "lost",
                "terminal_reason": "none" if active else (
                    "accelerator_electrode_or_boundary" if particle_id == 3
                    else "outside_rectangular_oatof_entry"),
                "x_mm": self.center[0] if active else self.center[0] - 0.8,
                "y_mm": 0.05 * particle_id,
                "z_mm": self.center[2] + 0.02 * particle_id,
            })
        self.terminal_path = self.root / "terminal.csv"
        pd.DataFrame(terminal_rows).to_csv(self.terminal_path, index=False)
        self.schedule_path = self.root / "schedule.json"
        self.schedule_path.write_text(json.dumps({
            "derived_pulse_time_us": 2.0,
            "selected_cohort": {"particle_ids": [1, 2, 4]},
        }), encoding="utf-8")

        self.s2_entry_path = self.root / "s2_entry.csv"
        pd.DataFrame([{
            "particle_id": particle_id,
            "frame_id": "oatof_global",
            "clock_epoch_id": "instrument_clock_epoch.v1",
            "first_forward_oatof_entry": particle_id <= 4,
            "position_x_mm": -67.8,
            "position_y_mm": 0.0,
            "position_z_mm": -18.42918680341103,
            "velocity_x_m_s": 1000.0,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 0.0,
        } for particle_id in range(1, 6)]).to_csv(self.s2_entry_path, index=False)

        self.local_exit_path = self.root / "local_exit.csv"
        pd.DataFrame([{
            "particle_id": particle_id,
            "frame_id": "oatof_global",
            "clock_epoch_id": "instrument_clock_epoch.v1",
            "position_x_mm": -47.0,
            "position_y_mm": 0.1 * particle_id,
            "position_z_mm": 4.8,
            "velocity_x_m_s": 4000.0,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 58000.0,
        } for particle_id in (1, 2)]).to_csv(self.local_exit_path, index=False)

        self.row_map_path = self.root / "row_map.csv"
        pd.DataFrame([
            {"solver_row_index": 1, "particle_id": 2},
            {"solver_row_index": 2, "particle_id": 1},
        ]).to_csv(self.row_map_path, index=False)
        baseline = json.loads(self.baseline.read_text(encoding="utf-8"))
        detector_x = baseline["coordinate_convention"]["detector_x"]
        detector_y = baseline["coordinate_convention"].get("detector_y", 0.0)
        self.downstream_path = self.root / "downstream.csv"
        pd.DataFrame([
            {"Ion": 2, "InstrumentTimeUs": 12.0, "XMm": detector_x,
             "YMm": detector_y, "Hit": True},
            {"Ion": 1, "InstrumentTimeUs": 12.5, "XMm": detector_x + 1.0,
             "YMm": detector_y, "Hit": False},
        ]).to_csv(self.downstream_path, index=False)

    def _analyze(self):
        return module.analyze_checkpoints(
            self.exit_path, self.capture_path, self.terminal_path,
            self.s2_entry_path, self.local_exit_path, self.row_map_path,
            self.downstream_path, self.schedule_path, self.baseline, self.s2,
            self.joint, self.contract,
        )

    def test_energy_uses_common_particle_physics_for_each_state(self) -> None:
        states = pd.DataFrame({
            "mass_amu": [40.0, 100.0],
            "local_vx_m_s": [1000.0, -250.0],
            "local_vy_m_s": [0.0, 500.0],
            "local_vz_m_s": [0.0, 750.0],
        })
        expected = np.array([
            kinetic_energy_ev(40.0, 1000.0, 0.0, 0.0),
            kinetic_energy_ev(100.0, -250.0, 500.0, 750.0),
        ])
        np.testing.assert_allclose(module._energy_eV(states), expected, rtol=1e-15)

    def test_same_id_metrics_preserve_full_population_and_residual(self) -> None:
        metrics, table, _ = self._analyze()
        counts = metrics["population_counts"]
        self.assertEqual(counts["source_exit_all"], 5)
        self.assertEqual(counts["scheduler_cohort"], 3)
        self.assertEqual(counts["capture_all_active"], 3)
        self.assertEqual(counts["scheduler_cohort_lost_before_pulse"], 1)
        self.assertEqual(counts["all_exit_lost_before_pulse"], 2)
        self.assertEqual(metrics["scientific_scope"]["particles_removed_from_metrics"], 0)
        self.assertEqual(set(table["particle_id"]), {1, 2, 3, 4, 5})
        residual = metrics["capture_minus_ballistic_same_id_residual"]["position"]["x"]
        self.assertAlmostEqual(residual["mean"], 0.2)
        self.assertAlmostEqual(residual["rms"], np.sqrt(0.2 / 3))
        capture = metrics["checkpoint_metrics"]["capture_all_active"]
        covariance = capture["covariance_r_v_mm_m_per_s"]
        self.assertEqual(covariance["row_frame_id"], metrics["analysis_frame"])
        self.assertEqual(covariance["column_frame_id"], metrics["analysis_frame"])
        self.assertEqual(covariance["row_unit"], "mm")
        self.assertEqual(covariance["column_unit"], "m/s")
        self.assertEqual(np.asarray(covariance["values"]).shape, (3, 3))
        self.assertIn("projected_emittance", capture)
        self.assertEqual(capture["ideal_reference_volume"]["denominator"], 3)
        stages = metrics["stage_membership"]
        self.assertEqual(stages["denominator"], 5)
        self.assertTrue(stages["sets_are_nested_not_additive"])
        self.assertEqual(
            [stages[key] for key in (
                "rf_exit", "s2_oatof_entry", "pulse_active",
                "local_accelerator_exit", "detector_hit",
            )],
            [5, 4, 3, 2, 1],
        )
        outcomes = metrics["exclusive_particle_outcomes"]
        self.assertEqual(outcomes["denominator"], 5)
        self.assertTrue(outcomes["classes_are_mutually_exclusive_and_exhaustive"])
        self.assertEqual(
            outcomes["counts"],
            {
                "physical_port_wall_loss": 1,
                "pre_pulse_loss": 1,
                "active_local_exit_loss": 1,
                "local_exit_without_detector_hit": 1,
                "detector_hit": 1,
            },
        )
        self.assertEqual(
            dict(zip(table["particle_id"], table["particle_outcome"], strict=True)),
            {
                1: "detector_hit",
                2: "local_exit_without_detector_hit",
                3: "active_local_exit_loss",
                4: "pre_pulse_loss",
                5: "physical_port_wall_loss",
            },
        )

    def test_registered_transform_applies_translation_to_position_only(self) -> None:
        rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        local_position = np.array([2.0, 3.0, 4.0])
        local_velocity = np.array([5.0, 6.0, 7.0])
        translation = np.array([10.0, 20.0, 30.0])
        instrument_position = local_position @ rotation.T + translation
        instrument_velocity = local_velocity @ rotation.T
        state = pd.DataFrame([{
            "particle_id": 1, "frame_id": "instrument",
            **{f"{axis}_mm": instrument_position[index] for index, axis in enumerate("xyz")},
            **{f"v{axis}_m_s": instrument_velocity[index] for index, axis in enumerate("xyz")},
        }])
        registration = {
            "instrument_frame_id": "instrument",
            "component_poses": {
                "oatof_global": {
                    "schema_version": 1,
                    "role": "rigid_transform",
                    "from_frame_id": "oatof_global",
                    "to_frame_id": "instrument",
                    "rotation": rotation.tolist(),
                    "translation_mm": translation.tolist(),
                },
            },
        }
        transformed = module._registered_local_state(state, registration, "", "v")
        np.testing.assert_allclose(
            transformed[[f"local_{axis}_mm" for axis in "xyz"]], [local_position])
        np.testing.assert_allclose(
            transformed[[f"local_v{axis}_m_s" for axis in "xyz"]], [local_velocity])

    def test_render_smoke_has_required_planes_and_units(self) -> None:
        metrics, table, geometry = self._analyze()
        with mock.patch.object(plt, "show") as show, mock.patch(
            "matplotlib.figure.Figure.savefig"
        ) as save:
            figure, axes = module.build_checkpoint_figure(metrics, table, geometry)
            show.assert_not_called()
            save.assert_not_called()
        try:
            self.assertEqual(set(axes), {
                "chain_xz", "aperture_yz", "detector", "ballistic_residual",
                "exclusive_outcomes", "stage_membership",
            })
            self.assertIn("x–z", axes["chain_xz"].get_title())
            self.assertIn("y–z", axes["aperture_yz"].get_title())
            self.assertIn("(mm)", axes["chain_xz"].get_xlabel())
            self.assertIn("(mm)", axes["detector"].get_xlabel())
            self.assertIn(metrics["analysis_frame"], figure._suptitle.get_text())
            self.assertIn(metrics["clock_epoch_id"], figure._suptitle.get_text())
            figure_labels = [
                text.get_text() for legend in figure.legends
                for text in legend.get_texts()
            ]
            self.assertIn("RF exit (N=5)", figure_labels)
            self.assertNotIn("RF exit (N=100)", figure_labels)
            self.assertEqual(axes["chain_xz"].get_aspect(), 1.0)
            self.assertEqual(axes["aperture_yz"].get_aspect(), 1.0)
            self.assertEqual(axes["detector"].get_aspect(), 1.0)
            for axis_name in ("chain_xz", "aperture_yz"):
                axis = axes[axis_name]
                geometry_artists = [
                    artist for artist in [*axis.patches, *axis.lines]
                    if artist.get_gid()
                ]
                semantic_ids = [artist.get_gid() for artist in geometry_artists]
                self.assertEqual(len(semantic_ids), len(set(semantic_ids)))
                self.assertEqual(
                    sum(":ring:" in semantic_id for semantic_id in semantic_ids),
                    2 * len(geometry["ring_centers_z"]),
                )
                self.assertEqual(
                    sum(semantic_id.endswith(":physical_port")
                        for semantic_id in semantic_ids),
                    1,
                )
                self.assertTrue(all(artist.get_zorder() < 6
                                    for artist in geometry_artists))
            self.assertEqual(
                sum((patch.get_gid() or "").startswith("rf:xz:rod:")
                    for patch in axes["chain_xz"].patches),
                geometry["rf_chain"]["rod_count"],
            )
            self.assertEqual(
                sum((patch.get_gid() or "").startswith("rf:yz:rod:")
                    for patch in axes["aperture_yz"].patches),
                geometry["rf_chain"]["rod_count"],
            )
            self.assertEqual(
                sum((patch.get_gid() or "") == "rf:yz:clear_aperture"
                    for patch in axes["aperture_yz"].patches),
                1,
            )
            residual_axis = axes["ballistic_residual"]
            residual_legend = residual_axis.get_legend()
            self.assertIsNotNone(residual_legend)
            self.assertEqual(
                [text.get_text() for text in residual_legend.get_texts()],
                ["x residual (Δx)", "y residual (Δy)", "z residual (Δz)"],
            )
            residual_lines = [
                line for line in residual_axis.lines
                if line.get_label().endswith(")")
            ]
            self.assertEqual(
                [line.get_marker() for line in residual_lines],
                ["o", "s", "^"],
            )
            for line in residual_lines:
                np.testing.assert_array_equal(line.get_xdata(), [1, 2, 3])
            self.assertTrue(all(
                line.get_linestyle() == "None" for line in residual_lines
            ))
            output = self.root / "checkpoint.png"
            module.export_checkpoint_figure(figure, output)
            self.assertGreater(output.stat().st_size, 1000)
        finally:
            plt.close(figure)

    def test_unknown_capture_id_and_mixed_time_fail_closed(self) -> None:
        capture = pd.read_csv(self.capture_path)
        capture.loc[0, "particle_id"] = 99
        capture.to_csv(self.capture_path, index=False)
        with self.assertRaisesRegex(ValueError, "unknown particle ID"):
            self._analyze()
        self._write_fixture()
        capture = pd.read_csv(self.capture_path)
        capture.loc[0, "instrument_time_us"] = 1.9
        capture.to_csv(self.capture_path, index=False)
        with self.assertRaisesRegex(ValueError, "scheduled global time"):
            self._analyze()

    def test_capture_and_terminal_frame_epoch_fail_closed(self) -> None:
        capture = pd.read_csv(self.capture_path)
        capture.loc[0, "frame_id"] = "wrong_frame"
        capture.to_csv(self.capture_path, index=False)
        with self.assertRaisesRegex(ValueError, "checkpoint frame_id differs"):
            self._analyze()
        self._write_fixture()
        terminal = pd.read_csv(self.terminal_path)
        terminal.loc[0, "clock_epoch_id"] = "wrong_epoch"
        terminal.to_csv(self.terminal_path, index=False)
        with self.assertRaisesRegex(ValueError, "terminal census clock epoch changed"):
            self._analyze()

    def test_chain_states_reject_nonfinite_values_and_identity_drift(self) -> None:
        s2_entry = pd.read_csv(self.s2_entry_path)
        s2_entry.loc[0, "position_y_mm"] = np.nan
        s2_entry.to_csv(self.s2_entry_path, index=False)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            self._analyze()

        self._write_fixture()
        local_exit = pd.read_csv(self.local_exit_path)
        local_exit.loc[0, "frame_id"] = "solver_local"
        local_exit.to_csv(self.local_exit_path, index=False)
        with self.assertRaisesRegex(ValueError, "frame or clock epoch"):
            self._analyze()

        self._write_fixture()
        downstream = pd.read_csv(self.downstream_path)
        downstream.loc[0, "InstrumentTimeUs"] = np.nan
        downstream.loc[0, "Hit"] = True
        downstream.to_csv(self.downstream_path, index=False)
        with self.assertRaisesRegex(ValueError, "hit lacks a finite detector crossing"):
            self._analyze()


if __name__ == "__main__":
    unittest.main()
