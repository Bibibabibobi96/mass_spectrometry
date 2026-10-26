"""Canonical finite-pulse export fixtures; no native solver qualification."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.analysis.compare_paired_accelerator_pulse import (
    COMSOL_COLUMNS, FIELDS, SIMION_COLUMNS, SOURCE_COLUMNS, compare_paired_accelerator_pulse,
)
from integrations.workflows.paired_accelerator_pulse.runtime import COLUMNS


class PairedPulseComparisonTests(unittest.TestCase):
    def write_csv(self, path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def fixture(self, root: Path) -> tuple[Path, dict, list[dict], list[dict]]:
        source = []
        comsol = []
        simion = []
        for native, pid in enumerate((9, 2), 1):
            state = dict(zip(FIELDS, (pid, 1, 2, 3, 4, 5)))
            source.append(dict(particle_id=pid, mass_amu=100, charge_state=1, **state, kinetic_energy_eV=1))
            for time in (50, 51, 52, 53):
                row = dict(particle_id=pid, native_particle_index=native, instrument_time_us=time,
                           **state, state_present=1, solver_raw_status=0)
                comsol.append(dict(**row, solver_stop_time_us="NaN"))
                simion.append(dict(**row, event="observation", requested_time_us=time,
                                   original_birth_time_us=pid / 100, terminal_reason=""))
            simion.append(dict(simion[-4], event="source_state"))
            simion.append(dict(simion[-2], event="terminal", requested_time_us="", terminal_reason="observation_window_complete"))
        plan = dict(schema_version=1, role="paired_accelerator_pulse_plan", source_csv=dict(path="source.csv"),
                    selected_particle_ids=[9, 2], particle_count=2, mass_amu=100, charge_state=1,
                    source_time_us=50, observation_times_us=[50, 51, 52, 53],
                    clock_epoch_id="original_unique_clock", instrument_epoch_us=0, frame_id="oatof_global",
                    original_mother_particle_ids=[2, 9, 22], original_birth_times_us={"2": .02, "9": .09, "22": .22},
                    uncontinued_mother_particle_ids=[22])
        self.write_csv(root / "source.csv", SOURCE_COLUMNS, source)
        path = root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path, plan, comsol, simion

    def compare(self, root: Path, plan: Path, comsol: list[dict], simion: list[dict]) -> dict:
        self.write_csv(root / "comsol.csv", COMSOL_COLUMNS, comsol)
        self.write_csv(root / "simion.csv", SIMION_COLUMNS, simion)
        return compare_paired_accelerator_pulse(plan, root / "comsol.csv", root / "simion.csv", root / "out")

    def test_original_ids_outer_pair_known_differences_order_and_read_once(self):
        self.assertEqual(tuple(COLUMNS), SIMION_COLUMNS)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, original, comsol, simion = self.fixture(root)
            for row in simion:
                if row["event"] == "observation" and row["requested_time_us"] == 51:
                    row["x_mm"] += 3 if row["particle_id"] == 9 else 4
            comsol.reverse()
            simion.reverse()
            opened = []
            native_open = Path.open

            def counted(path, *args, **kwargs):
                if path.name in ("comsol.csv", "simion.csv") and (not args or args[0] == "r"):
                    opened.append(path.name)
                return native_open(path, *args, **kwargs)

            with patch.object(Path, "open", counted):
                report = self.compare(root, plan, comsol, simion)
            self.assertCountEqual(opened, ["comsol.csv", "simion.csv"])
            self.assertEqual(report["qualification"], "diagnostic_only")
            self.assertEqual(report["fields"]["x_mm"]["finite_pair_count"], 8)
            self.assertEqual(report["fields"]["x_mm"]["max_abs"], 4)
            self.assertAlmostEqual(report["fields"]["x_mm"]["rms"], math.sqrt(25 / 8))
            self.assertEqual(report["fields"]["vy_m_per_s"]["max_abs"], 0)
            for key in ("original_mother_particle_ids", "original_birth_times_us", "uncontinued_mother_particle_ids"):
                self.assertEqual(report[key], original[key])
            with Path(report["differences_csv"]).open(newline="") as handle:
                diffs = list(csv.DictReader(handle))
            self.assertEqual(len(diffs), 48)
            self.assertEqual({int(row["particle_id"]) for row in diffs}, {9, 2})
            self.assertEqual(json.loads((root / "out/paired_pulse_comparison.json").read_text()), report)

    def test_late_early_stop_nan_and_missed_time_are_not_inner_joined_away(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, _, comsol, simion = self.fixture(root)
            comsol[:] = [row for row in comsol if not (row["particle_id"] == 9 and row["instrument_time_us"] == 53)]
            for row in simion:
                if row["event"] != "observation":
                    continue
                if row["particle_id"] == 2 and row["requested_time_us"] == 52:
                    row.update(state_present=0, x_mm="NaN")
                if row["particle_id"] == 9 and row["requested_time_us"] == 52:
                    row["instrument_time_us"] += .01
                if row["particle_id"] == 2 and row["requested_time_us"] == 53:
                    row["vz_m_per_s"] = "Inf"
            report = self.compare(root, plan, comsol, simion)
            self.assertEqual(report["expected_observation_pairs"], 8)
            self.assertEqual(report["availability"]["comsol"]["missing_record"], 1)
            self.assertEqual(report["availability"]["simion"]["missing_state"], 1)
            self.assertEqual(report["availability"]["simion"]["missed_time"], 1)
            self.assertEqual(report["availability"]["simion"]["nonfinite_state"], 1)
            self.assertEqual(report["fields"]["x_mm"]["finite_pair_count"], 5)
            self.assertEqual(report["fields"]["vz_m_per_s"]["finite_pair_count"], 4)
            with Path(report["differences_csv"]).open(newline="") as handle:
                differences = list(csv.DictReader(handle))
            self.assertEqual(len(differences), 48)
            missed = [row for row in differences if row["simion_availability"] == "missed_time"]
            self.assertEqual(len(missed), 6)
            self.assertTrue(all(row["simion_minus_comsol"] == "" for row in missed))
            self.assertTrue(all(row["simion_terminal_reason"] == "unknown" for row in differences))

    def test_initial_identity_clock_birth_duplicates_and_units_rejected(self):
        scenarios = ("missing_initial", "initial_6d", "initial_nan", "source_state", "clock", "birth", "duplicate", "foreign", "units")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                plan, _, comsol, simion = self.fixture(root)
                if scenario == "missing_initial":
                    comsol.pop(0)
                elif scenario == "initial_6d":
                    comsol[0]["x_mm"] += 1
                elif scenario == "initial_nan":
                    comsol[0]["x_mm"] = "NaN"
                elif scenario == "source_state":
                    simion[:] = [row for row in simion if row["event"] != "source_state"]
                elif scenario == "clock":
                    simion[0]["instrument_time_us"] += 1
                elif scenario == "birth":
                    simion[1]["original_birth_time_us"] += 1
                elif scenario == "duplicate":
                    simion.append(dict(simion[1]))
                elif scenario == "foreign":
                    comsol[-1]["particle_id"] = 22
                else:
                    self.write_csv(root / "comsol.csv", tuple("x_m" if key == "x_mm" else key for key in COMSOL_COLUMNS),
                                   [dict(("x_m" if key == "x_mm" else key, value) for key, value in row.items()) for row in comsol])
                    self.write_csv(root / "simion.csv", SIMION_COLUMNS, simion)
                    with self.assertRaisesRegex(ValueError, "columns/units"):
                        compare_paired_accelerator_pulse(plan, root / "comsol.csv", root / "simion.csv", root / "out")
                    continue
                with self.assertRaises(ValueError):
                    self.compare(root, plan, comsol, simion)

    def test_both_backends_missing_late_still_has_every_expected_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, _, comsol, simion = self.fixture(root)
            comsol[:] = [row for row in comsol if row["instrument_time_us"] != 53]
            simion[:] = [row for row in simion if row["event"] != "observation" or row["requested_time_us"] != 53]
            report = self.compare(root, plan, comsol, simion)
            self.assertEqual(report["availability"]["comsol"]["missing_record"], 2)
            self.assertEqual(report["availability"]["simion"]["missing_record"], 2)
            self.assertEqual(report["fields"]["x_mm"]["finite_pair_count"], 6)
            with Path(report["differences_csv"]).open(newline="") as handle:
                missing = [row for row in csv.DictReader(handle) if row["requested_time_us"] == "53.0"]
            self.assertEqual(len(missing), 12)
            self.assertTrue(all(row["simion_value"] == row["comsol_value"] == row["simion_minus_comsol"] == ""
                                for row in missing))


if __name__ == "__main__":
    unittest.main()
