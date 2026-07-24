from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from projects.rf_quadrupole_collision_cooling.analysis import audit_s3_pulse_chain as module
from projects.rf_quadrupole_collision_cooling.analysis import (
    build_s3_local_exit_component_state as adapter,
)


class S3PulseChainAuditTests(unittest.TestCase):
    def test_matlab_emits_only_solver_local_terminal_census(self) -> None:
        script = Path(__file__).parents[1] / "comsol" / "solve_s3_pulse_capture.m"
        text = script.read_text(encoding="utf-8")
        self.assertIn("eventRows = cell(height(ions), 24)", text)
        self.assertIn("localExitCount = nnz(string(terminal.event)", text)
        for forbidden in (
            "exitRows",
            "localExit=cell2table",
            "canonical_parent_particle_id",
            "kinetic_energy_eV",
            "1.602176634e-19",
            "RF_OATOF_S3_LOCAL_EXIT_OUTPUT",
        ):
            self.assertNotIn(forbidden, text)

    def test_runner_validates_and_records_frozen_s3_particle_input(self) -> None:
        runner = Path(__file__).parents[1] / "comsol" / "run_s3_pulse_capture.ps1"
        text = runner.read_text(encoding="utf-8")
        validation = text.index(
            "'-m','common.contracts.component_particle_state',"
        )
        comsol = text.index("& $frozenComsolRunner")
        adapter_call = text.index(
            "$localExitAdapter,'--source',$particleInput"
        )
        audit_call = text.index(
            "$auditAnalysis,'--source',$particleInput"
        )
        snapshot_call = text.index(
            "$snapshotAnalysis,'--capture',$capture"
        )
        self.assertLess(validation, comsol)
        self.assertLess(comsol, adapter_call)
        self.assertLess(adapter_call, audit_call)
        self.assertLess(audit_call, snapshot_call)
        self.assertIn("$manifestToolRoot = $snapshotRoot", text)
        self.assertIn(
            "$frozenManifestVerifier = "
            "$dependencySnapshotPaths['common_verify_run_manifest']",
            text,
        )
        self.assertIn(
            "$frozenComsolRunner = "
            "$dependencySnapshotPaths['common_comsol_runner']",
            text,
        )
        self.assertIn(
            "Write-RfFrozenRunManifest -Python $python "
            "-FrozenRepoRoot $manifestToolRoot",
            text.replace("`\n    ", ""),
        )
        self.assertNotIn("common\\comsol\\run_comsol_r2025b.ps1", text)
        self.assertNotIn("$python $localExitAdapter", text)
        self.assertNotIn("$python $auditAnalysis", text)
        self.assertNotIn("$python $snapshotAnalysis", text)
        self.assertIn(
            "$localExitAdapter = "
            "$dependencySnapshotPaths['rf_s3_local_exit_adapter']",
            text,
        )
        self.assertIn("s3_local_accelerator_exit_validation.json", text)
        self.assertNotIn("RF_OATOF_S3_LOCAL_EXIT_OUTPUT", text)
        self.assertIn("canonical_rf_exit_component_state_validation.json", text)
        self.assertIn("particle_state_validation = $particleValidation", text)
        self.assertIn("particle_validation_sha256", text)

    def test_parent_nan_boundary_and_real_parent_are_explicit(self) -> None:
        velocity = 1000.0
        row = {
            "particle_id": 2, "parent_particle_id": "", "generation": 0,
            "species_id": "ion_100amu_q1", "particle_weight": 1,
            "source_component_id": "s2", "target_component_id": "s3",
            "state_event": "component_handoff", "frame_id": "oatof_global",
            "clock_epoch_id": "epoch", "instrument_time_us": 12,
            "lineage_age_us": 6, "particle_age_us": 6,
            "last_component_elapsed_time_us": 2,
            "lineage_birth_time_us": 6, "particle_birth_time_us": 6,
            "mass_to_charge_Th": 100, "mass_amu": 100, "charge_state": 1,
            "position_x_mm": 0, "position_y_mm": 0, "position_z_mm": 0,
            "velocity_x_m_s": velocity, "velocity_y_m_s": 0, "velocity_z_m_s": 0,
            "kinetic_energy_eV": kinetic_energy_ev(100, velocity, 0, 0),
            "phase_reference_id": "rf_drive.v1", "phase_rad": 0,
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.csv"

            def write(parent: object, generation: int) -> None:
                candidate = {**row, "parent_particle_id": parent, "generation": generation}
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=csv_columns())
                    writer.writeheader()
                    writer.writerow(candidate)

            write("", 0)
            self.assertEqual(validate_component_particle_state_csv(path)["status"], "PASS")
            write(7, 1)
            self.assertEqual(validate_component_particle_state_csv(path)["status"], "PASS")
            write("NaN", 0)
            with self.assertRaisesRegex(ValueError, "parent_particle_id"):
                validate_component_particle_state_csv(path)
            write("", 0)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["species_id"] = ""
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=csv_columns())
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "species_id"):
                validate_component_particle_state_csv(path)

    def test_minimal_chain_preserves_clock_and_exit_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            velocity = 1000.0
            energy = kinetic_energy_ev(100, velocity, 0, 0)
            source = pd.DataFrame([{
                "particle_id": 1, "parent_particle_id": 42, "generation": 1,
                "species_id": "ion_100amu_q1", "particle_weight": 1.0,
                "source_component_id": "s2", "target_component_id": "s3",
                "state_event": "component_handoff", "frame_id": "laboratory_frame",
                "clock_epoch_id": "epoch", "instrument_time_us": 10.0,
                "lineage_age_us": 4.0, "particle_age_us": 4.0,
                "last_component_elapsed_time_us": 0.0,
                "lineage_birth_time_us": 6.0, "particle_birth_time_us": 6.0,
                "mass_to_charge_Th": 100.0, "mass_amu": 100.0,
                "charge_state": 1, "position_x_mm": 0.0, "position_y_mm": 0.0,
                "position_z_mm": 0.0, "velocity_x_m_s": velocity,
                "velocity_y_m_s": 0.0, "velocity_z_m_s": 0.0,
                "kinetic_energy_eV": energy,
                "phase_reference_id": "rf_drive.v1", "phase_rad": 0.0,
            }], columns=csv_columns())
            terminal = pd.DataFrame([{
                "particle_id": 1, "event": "contract_local_exit",
                "status": "transmitted", "frame_id": "laboratory_frame",
                "clock_epoch_id": "epoch", "instrument_time_us": 12.0,
                "lineage_age_us": 6.0, "particle_age_us": 6.0,
                "last_component_elapsed_time_us": 2.0,
                "mass_amu": 100.0, "charge_state": 1,
                "x_mm": 1.0, "y_mm": 2.0, "z_mm": 3.0,
                "vx_m_s": velocity, "vy_m_s": 0.0, "vz_m_s": 0.0,
                "rf_phase_rad": 0.25, "local_accelerator_exit": True,
                "first_forward_oatof_entry": True,
            }])
            capture = pd.DataFrame([{
                "particle_id": 1, "frame_id": "laboratory_frame",
                "clock_epoch_id": "epoch", "instrument_time_us": 11.0,
                "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
                "vx_m_s": velocity, "vy_m_s": 0.0, "vz_m_s": 0.0,
                "inside_oatof_ideal_reference_volume": True, "active_at_pulse": True,
            }])
            for name, frame in (("source", source), ("terminal", terminal),
                                ("capture", capture)):
                frame.to_csv(root/f"{name}.csv", index=False)
            (root/"schedule.json").write_text(json.dumps({
                "stage": "S3", "derived_pulse_time_us": 11.0,
                "pulse_width_us": 1.0,
                "target_species": {"mass_amu": 100.0, "charge_state": 1},
            }), encoding="utf-8")
            contract = {
                "source": {
                    "source_particles": 1, "clock_epoch_id": "epoch",
                    "target_mass_amu": 100.0, "target_charge_state": 1,
                },
                "identity_contract": {"frame_id": "laboratory_frame"},
                "local_exit_adapter": {
                    "terminal_event": "contract_local_exit",
                    "terminal_status": "transmitted",
                    "source_component_id": "rf_quadrupole_to_oatof_s3",
                    "target_component_id": "oatof_analyzer",
                    "state_event": "canonical_contract_local_exit",
                },
                "runtime": {
                    "minimum_active_at_pulse": 1,
                    "minimum_local_accelerator_exit": 1,
                },
            }
            (root/"contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            validation = adapter.build_local_exit_component_state(
                root/"source.csv", root/"terminal.csv", root/"contract.json",
                root/"exit.csv", root/"exit_validation.json",
            )
            self.assertEqual(validation["status"], "PASS")
            with (root/"exit.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, csv_columns())
                exit_rows = list(reader)
            self.assertEqual(exit_rows[0]["species_id"], "ion_100amu_q1")
            self.assertEqual(
                float(exit_rows[0]["kinetic_energy_eV"]),
                kinetic_energy_ev(100.0, velocity, 0.0, 0.0),
            )
            self.assertEqual(exit_rows[0]["position_x_mm"], "1.0")

            continuity_changes = {
                "parent_particle_id": {"parent_particle_id": 43},
                "generation": {"generation": 2},
                "particle_weight": {"particle_weight": 2.0},
                "lineage_birth_time_us": {
                    "lineage_birth_time_us": 5.5,
                    "lineage_age_us": 6.5,
                },
                "particle_birth_time_us": {
                    "particle_birth_time_us": 6.5,
                    "particle_age_us": 5.5,
                },
                "phase_reference_id": {"phase_reference_id": "other_phase.v1"},
                "mass_amu": {
                    "mass_amu": 101.0,
                    "mass_to_charge_Th": mass_to_charge_th(101.0, 1),
                    "kinetic_energy_eV": kinetic_energy_ev(
                        101.0, velocity, 0.0, 0.0
                    ),
                },
                "charge_state": {
                    "charge_state": 2,
                    "mass_to_charge_Th": mass_to_charge_th(100.0, 2),
                },
            }
            for field, changes in continuity_changes.items():
                with self.subTest(identity_field=field):
                    changed_exit = {**exit_rows[0], **changes}
                    changed_exit_path = root / f"exit_bad_{field}.csv"
                    with changed_exit_path.open(
                        "w", encoding="utf-8", newline=""
                    ) as handle:
                        writer = csv.DictWriter(handle, fieldnames=csv_columns())
                        writer.writeheader()
                        writer.writerow(changed_exit)
                    self.assertEqual(
                        validate_component_particle_state_csv(changed_exit_path)[
                            "status"
                        ],
                        "PASS",
                    )
                    with self.assertRaisesRegex(ValueError, field):
                        module.audit(
                            root / "source.csv",
                            root / "terminal.csv",
                            root / "capture.csv",
                            changed_exit_path,
                            root / "schedule.json",
                            root / "contract.json",
                        )

            terminal_equivalence_changes = {
                "event_only": {
                    "event": "other_terminal",
                    "status": "transmitted",
                    "local_accelerator_exit": True,
                },
                "status_only": {
                    "event": "contract_local_exit",
                    "status": "lost",
                    "local_accelerator_exit": True,
                },
                "flag_only": {
                    "event": "contract_local_exit",
                    "status": "transmitted",
                    "local_accelerator_exit": False,
                },
                "non_exit_with_exit_flag": {
                    "event": "other_terminal",
                    "status": "lost",
                    "local_accelerator_exit": True,
                },
            }
            for case, changes in terminal_equivalence_changes.items():
                with self.subTest(terminal_equivalence=case):
                    changed_terminal = terminal.copy()
                    for field, value in changes.items():
                        changed_terminal.loc[0, field] = value
                    changed_terminal_path = root / f"terminal_bad_{case}.csv"
                    changed_terminal.to_csv(changed_terminal_path, index=False)
                    with self.assertRaisesRegex(ValueError, "not equivalent"):
                        adapter.build_local_exit_component_state(
                            root / "source.csv",
                            changed_terminal_path,
                            root / "contract.json",
                            root / f"exit_bad_{case}.csv",
                        )
                    with self.assertRaisesRegex(ValueError, "not equivalent"):
                        module.audit(
                            root / "source.csv",
                            changed_terminal_path,
                            root / "capture.csv",
                            root / "exit.csv",
                            root / "schedule.json",
                            root / "contract.json",
                        )

            changed_terminal = terminal.copy()
            changed_terminal.loc[0, "mass_amu"] = 101.0
            changed_terminal.to_csv(root/"terminal_bad.csv", index=False)
            with self.assertRaisesRegex(ValueError, "species differs"):
                adapter.build_local_exit_component_state(
                    root/"source.csv", root/"terminal_bad.csv",
                    root/"contract.json", root/"exit_bad.csv",
                )
            result = module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                                  root/"exit.csv", root/"schedule.json", root/"contract.json")
            self.assertEqual(result["local_accelerator_exit"], 1)
            self.assertEqual(result["maximum_clock_residual_us"], 0.0)

            string_false_terminal = terminal.copy()
            string_false_terminal["first_forward_oatof_entry"] = (
                string_false_terminal["first_forward_oatof_entry"].astype(object)
            )
            string_false_terminal.loc[0, "first_forward_oatof_entry"] = "false"
            string_false_terminal.to_csv(root / "terminal_string_false.csv", index=False)
            string_false_capture = capture.copy()
            for field in (
                "inside_oatof_ideal_reference_volume",
                "active_at_pulse",
            ):
                string_false_capture[field] = string_false_capture[field].astype(
                    object
                )
            string_false_capture.loc[
                0, "inside_oatof_ideal_reference_volume"
            ] = "false"
            string_false_capture.loc[0, "active_at_pulse"] = "true"
            string_false_capture.to_csv(root / "capture_string_false.csv", index=False)
            false_result = module.audit(
                root / "source.csv",
                root / "terminal_string_false.csv",
                root / "capture_string_false.csv",
                root / "exit.csv",
                root / "schedule.json",
                root / "contract.json",
            )
            self.assertEqual(false_result["oatof_entry_crossings"], 0)
            self.assertEqual(
                false_result["inside_ideal_reference_volume_at_pulse"], 0
            )

            inactive_capture = capture.copy()
            inactive_capture["active_at_pulse"] = inactive_capture[
                "active_at_pulse"
            ].astype(object)
            inactive_capture.loc[0, "active_at_pulse"] = "false"
            inactive_capture.to_csv(root / "capture_inactive.csv", index=False)
            with self.assertRaisesRegex(ValueError, "inactive particle"):
                module.audit(
                    root / "source.csv",
                    root / "terminal.csv",
                    root / "capture_inactive.csv",
                    root / "exit.csv",
                    root / "schedule.json",
                    root / "contract.json",
                )

            changed_capture = capture.copy()
            changed_capture.loc[0, "particle_id"] = 2
            changed_capture.to_csv(root/"capture.csv", index=False)
            with self.assertRaisesRegex(ValueError, "unknown particle ID"):
                module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                             root/"exit.csv", root/"schedule.json", root/"contract.json")

            changed_capture = capture.copy()
            changed_capture.loc[0, "instrument_time_us"] = 11.001
            changed_capture.to_csv(root/"capture.csv", index=False)
            with self.assertRaisesRegex(ValueError, "scheduled pulse time"):
                module.audit(root/"source.csv", root/"terminal.csv", root/"capture.csv",
                             root/"exit.csv", root/"schedule.json", root/"contract.json")


if __name__ == "__main__":
    unittest.main()
