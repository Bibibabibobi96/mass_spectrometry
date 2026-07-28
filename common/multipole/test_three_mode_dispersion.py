from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import csv_columns
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.multipole.three_mode_dispersion import (
    MODE_IDS,
    analyze_experiment,
    project_state,
)


class ThreeModeDispersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project_id = "rf_hexapole_ion_optics"
        self.geometry_sha = "A" * 64
        self.n1000_path = self.root / "source_n1000.csv"
        self.n100_path = self.root / "source_n100.csv"
        source_rows = [
            self._row(index, event="source_release", z_mm=0.0)
            for index in range(1, 1001)
        ]
        self._write_csv(self.n1000_path, source_rows)
        self._write_csv(self.n100_path, source_rows[:100])
        self.mode_paths: dict[str, Path] = {}
        self.voltage_paths: dict[str, Path] = {}
        survivor_counts = (100, 90, 80)
        for mode_index, (mode_id, survivors) in enumerate(
            zip(MODE_IDS, survivor_counts, strict=True)
        ):
            state_path = self.root / f"{mode_id}.csv"
            rows = [
                self._row(
                    particle_id,
                    event="canonical_handoff",
                    z_mm=10.0,
                    x_mm=particle_id / 100.0 + mode_index * 0.1,
                    vx_m_s=particle_id + mode_index,
                    energy_shift_eV=mode_index,
                )
                for particle_id in range(1, survivors + 1)
            ]
            self._write_csv(state_path, rows)
            self.mode_paths[mode_id] = state_path
            voltage_path = self.root / f"{mode_id}.json"
            self._write_json(
                voltage_path,
                {
                    "project_id": self.project_id,
                    "mode_id": mode_id,
                    "geometry_invariant_sha256": self.geometry_sha,
                    "voltage_assignment": {"identity_only": mode_index},
                },
            )
            self.voltage_paths[mode_id] = voltage_path
        self.qualification_paths = {}
        for name in (
            "project_acceptance_contract",
            "project_effect_resolution_contract",
            "project_engineering_budget_contract",
        ):
            path = self.root / f"{name}.json"
            self._write_json(
                path,
                {
                    "role": {
                        "project_acceptance_contract": (
                            "multipole_dispersion_acceptance_contract"
                        ),
                        "project_effect_resolution_contract": (
                            "multipole_dispersion_effect_resolution_contract"
                        ),
                        "project_engineering_budget_contract": (
                            "multipole_engineering_budget_contract"
                        ),
                    }[name],
                    "project_id": self.project_id,
                    "contract_id": f"{name}.v1",
                    "preregistered_before_run": True,
                    {
                        "project_acceptance_contract": "acceptance_criteria",
                        "project_effect_resolution_contract": "effect_resolution",
                        "project_engineering_budget_contract": "pilot_authorization",
                    }[name]: {"fixture_metric": 1},
                },
            )
            self.qualification_paths[name] = path
        self.binding_path = self.root / "binding.json"
        self.binding = self._binding()
        self._write_json(self.binding_path, self.binding)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _write_csv(path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=csv_columns(), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _row(
        particle_id: int,
        *,
        event: str,
        z_mm: float,
        x_mm: float = 0.0,
        vx_m_s: float = 0.0,
        energy_shift_eV: float = 0.0,
    ) -> dict:
        mass_amu = 100.0
        vz_m_s = 1000.0
        base_energy = kinetic_energy_ev(mass_amu, vx_m_s, 0.0, vz_m_s)
        if energy_shift_eV:
            target_energy = base_energy + energy_shift_eV
            vz_m_s = (
                max(
                    0.0,
                    2.0 * target_energy * 1.602176634e-19
                    / (mass_amu * 1.66053906892e-27)
                    - vx_m_s * vx_m_s,
                )
            ) ** 0.5
        energy = kinetic_energy_ev(mass_amu, vx_m_s, 0.0, vz_m_s)
        time_us = 0.0 if event == "source_release" else 10.0
        return {
            "particle_id": particle_id,
            "parent_particle_id": "",
            "generation": 0,
            "species_id": "test_ion",
            "particle_weight": 1.0,
            "source_component_id": "rf_multipole",
            "target_component_id": "downstream",
            "state_event": event,
            "frame_id": "multipole_exit_frame",
            "clock_epoch_id": "instrument_trigger",
            "instrument_time_us": time_us,
            "lineage_age_us": time_us,
            "particle_age_us": time_us,
            "last_component_elapsed_time_us": time_us,
            "lineage_birth_time_us": 0.0,
            "particle_birth_time_us": 0.0,
            "mass_to_charge_Th": mass_to_charge_th(mass_amu, 1),
            "mass_amu": mass_amu,
            "charge_state": 1,
            "position_x_mm": x_mm,
            "position_y_mm": 0.0,
            "position_z_mm": z_mm,
            "velocity_x_m_s": vx_m_s,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": vz_m_s,
            "kinetic_energy_eV": energy,
            "phase_reference_id": "",
            "phase_rad": "",
        }

    def _reference(self, path: Path) -> dict:
        return {"path": path.name, "sha256": file_sha256(path)}

    def _binding(self) -> dict:
        return {
            "schema_version": 1,
            "role": "multipole_three_mode_dispersion_binding",
            "project_id": self.project_id,
            "solver_id": "solver_fixture",
            "solver_numerics_sha256": "D" * 64,
            "analysis_plan_preregistered_before_run": True,
            "published_after_real_runs": True,
            "analysis_particle_count": 100,
            "retention_class": "compact",
            "frame_id": "multipole_exit_frame",
            "clock_epoch_id": "instrument_trigger",
            "handoff_state_event": "canonical_handoff",
            "geometry": {
                "geometry_invariant_sha256": self.geometry_sha,
                "rod_z_min_mm": 0.0,
                "rod_z_max_mm": 9.0,
                "handoff_plane_z_mm": 10.0,
                "near_interface_plane_z_mm": 11.5,
            },
            "source_family": {
                "n100": self._reference(self.n100_path),
                "n1000": self._reference(self.n1000_path),
            },
            "modes": [
                {
                    "mode_id": mode_id,
                    "geometry_invariant_sha256": self.geometry_sha,
                    "particle_source_sha256": file_sha256(self.n100_path),
                    "solver_numerics_sha256": "D" * 64,
                    "voltage_contract": self._reference(self.voltage_paths[mode_id]),
                    "handoff_state": self._reference(self.mode_paths[mode_id]),
                }
                for mode_id in MODE_IDS
            ],
            "qualification_bindings": {
                name: self._reference(path)
                for name, path in self.qualification_paths.items()
            },
            "bootstrap": {"seed": 731, "resamples": 20},
        }

    def test_analyzes_all_modes_losses_planes_and_pairs_deterministically(self) -> None:
        first = analyze_experiment(self.binding_path)
        second = analyze_experiment(self.binding_path)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "UNQUALIFIED_ANALYSIS_ONLY")
        self.assertEqual(
            first["mode_results"]["exit_aperture_plate_acceleration"][
                "transmitted_particles"
            ],
            80,
        )
        self.assertEqual(
            first["mode_results"]["exit_aperture_plate_acceleration"][
                "lost_particle_ids"
            ],
            list(range(81, 101)),
        )
        self.assertEqual(len(first["paired_comparisons"]), 3)
        pair = first["paired_comparisons"]["segmented_vs_exit_plate"]
        common = pair["observations"]["field_free_plus_50mm"]["common_survivor_ids"]
        self.assertEqual(common, list(range(1, 81)))
        interval = pair["observations"]["handoff"]["continuous_metrics"][
            "radius_mm"
        ]["paired_bootstrap_95_percent_interval"]
        self.assertEqual(len(interval), 2)
        self.assertLessEqual(interval[0], interval[1])

    def test_ballistic_projection_uses_positive_vz_and_advances_tof(self) -> None:
        row = self._row(1, event="canonical_handoff", z_mm=10.0, x_mm=1.0, vx_m_s=10.0)
        projected = project_state(row, 50.0)
        self.assertAlmostEqual(projected["radius_mm"], 1.5)
        self.assertAlmostEqual(projected["component_tof_us"], 60.0)
        row["velocity_z_m_s"] = 0.0
        with self.assertRaisesRegex(ValueError, "must be positive"):
            project_state(row, 5.0)

    def test_rejects_nonprefix_mother_sample(self) -> None:
        with self.n100_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["position_x_mm"] = "1"
        self._write_csv(self.n100_path, rows)
        self.binding["source_family"]["n100"]["sha256"] = file_sha256(self.n100_path)
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "not the deterministic prefix"):
            analyze_experiment(self.binding_path)

    def test_requires_all_three_project_prerun_bindings(self) -> None:
        del self.binding["qualification_bindings"]["project_effect_resolution_contract"]
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "project_effect_resolution_contract"):
            analyze_experiment(self.binding_path)

    def test_rejects_unknown_binding_field(self) -> None:
        self.binding["unregistered_policy"] = True
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "Additional properties are not allowed"):
            analyze_experiment(self.binding_path)

    def test_rejects_geometry_drift_between_voltage_modes(self) -> None:
        self.binding["modes"][1]["geometry_invariant_sha256"] = "B" * 64
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "one geometry invariant"):
            analyze_experiment(self.binding_path)

    def test_rejects_source_or_solver_numerics_drift_between_modes(self) -> None:
        self.binding["modes"][1]["solver_numerics_sha256"] = "E" * 64
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "source and solver numerics"):
            analyze_experiment(self.binding_path)

    def test_rejects_stale_voltage_contract(self) -> None:
        path = self.voltage_paths[MODE_IDS[1]]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["voltage_assignment"]["identity_only"] = 999
        self._write_json(path, document)
        with self.assertRaisesRegex(ValueError, "voltage contract SHA-256"):
            analyze_experiment(self.binding_path)

    def test_rejects_noncompact_retention(self) -> None:
        self.binding["retention_class"] = "qualification"
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "'compact' was expected"):
            analyze_experiment(self.binding_path)

    def test_disjoint_survivors_preserve_transmission_without_continuous_metrics(self) -> None:
        path = self.mode_paths[MODE_IDS[2]]
        rows = [
            self._row(
                particle_id,
                event="canonical_handoff",
                z_mm=10.0,
                x_mm=particle_id / 100.0,
                vx_m_s=particle_id,
            )
            for particle_id in range(91, 101)
        ]
        self._write_csv(path, rows)
        self.binding["modes"][2]["handoff_state"]["sha256"] = file_sha256(path)
        self._write_json(self.binding_path, self.binding)
        result = analyze_experiment(self.binding_path)
        pair = result["paired_comparisons"]["segmented_vs_exit_plate"]
        observation = pair["observations"]["handoff"]
        self.assertEqual(observation["common_survivor_ids"], [])
        self.assertEqual(
            observation["continuous_metrics_status"],
            "UNAVAILABLE_NO_COMMON_SURVIVORS",
        )
        self.assertEqual(
            result["mode_results"]["exit_aperture_plate_acceleration"][
                "transmitted_particles"
            ],
            10,
        )

    def test_rejects_wrong_project_qualification_role(self) -> None:
        path = self.qualification_paths["project_acceptance_contract"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["role"] = "generic_acceptance"
        self._write_json(path, document)
        self.binding["qualification_bindings"]["project_acceptance_contract"][
            "sha256"
        ] = file_sha256(path)
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "role, project or contract identity"):
            analyze_experiment(self.binding_path)

    def test_rejects_nonforward_handoff_without_dropping_particle(self) -> None:
        path = self.mode_paths[MODE_IDS[0]]
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["velocity_z_m_s"] = "0"
        rows[0]["kinetic_energy_eV"] = str(
            kinetic_energy_ev(100.0, float(rows[0]["velocity_x_m_s"]), 0.0, 0.0)
        )
        self._write_csv(path, rows)
        self.binding["modes"][0]["handoff_state"]["sha256"] = file_sha256(path)
        self._write_json(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, "must be positive"):
            analyze_experiment(self.binding_path)


if __name__ == "__main__":
    unittest.main()
