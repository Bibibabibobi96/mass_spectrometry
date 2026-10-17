"""Synthetic lifecycle evidence only: never execute a vendor flight."""
from __future__ import annotations

import csv
import unittest

from common.contracts.component_particle_state import write_component_particle_state_csv
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_analysis import analyze_measured_component
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import materialize_measured_source
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_measured_component_source as fixtures


def _terminal(particle: int, code: int, time: float) -> str:
    return (f"MRTOF_EVENT terminal ion={particle} splat={code} t_us={time:.12g} "
            "x_mm=1 y_mm=2 z_mm=3 vx_mm_us=.01 vy_mm_us=.1 vz_mm_us=-30 turns=49 central_crossings=49")


def _detector(particle: int, time: float) -> str:
    return f"MRTOF_EVENT detector ion={particle} t_us={time:.12g} x_mm=1 y_mm=2 z_mm=3"


class MeasuredComponentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = self.root / "prepared_source"
        materialize_measured_source(self.fixture.handoff, self.source)
        self.log = self.root / "flight.log"
        self.output = self.root / "analysis"
        # Same individual downstream duration, different absolute arrivals.
        self.text = "\n".join((_detector(1, 7600.51), _terminal(1, 1, 7600.51),
                                _detector(7, 7600.57), _terminal(7, 1, 7600.57),
                                "status,Fly completed. 2 splats")) + "\n"
        self.log.write_text(self.text, encoding="utf-8")

    def _analyze(self) -> dict:
        return analyze_measured_component(self.log, self.source / "source_receipt.json", self.output)

    def test_noncontiguous_ids_absolute_width_and_upstream_loss_preserved(self) -> None:
        report = self._analyze()
        self.assertEqual(report["counts"], {"mother_source": 3, "upstream_not_transferred": 1,
                                         "downstream_released": 2, "detected": 2,
                                         "downstream_timeout": 0, "downstream_loss": 0})
        self.assertEqual(report["detected_fraction_of_mother"], 2/3)
        self.assertAlmostEqual(report["absolute_arrival"]["population_sigma"], .03)
        self.assertAlmostEqual(report["elapsed_since_handoff"]["population_sigma"], 0)
        self.assertIsNone(report["absolute_arrival"]["fwhm"])
        self.assertIsNone(report["physical_performance_pass"])
        with (self.output / "particle_census.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([int(row["particle_id"]) for row in rows], [1, 7, 9])
        self.assertEqual(rows[2]["downstream_status"], "not_transferred")
        self.assertEqual(rows[2]["upstream_terminal_reason"], "solver_stop")
        self.assertEqual(rows[0]["terminal_velocity_z_m_s"], "-30000.0")

    def test_all_one_hundred_mother_ids_are_denominator(self) -> None:
        fixture = self.fixture.fixture
        ids = [1, 7, *range(1000, 1095)]
        rows = [fixture._row(particle) for particle in ids]
        write_component_particle_state_csv(fixture.source, rows)
        lost = [24, 64, 80]
        lines = ["particle_id,transfer_status,terminal_reason,instrument_time_us,particle_birth_time_us,particle_age_us"]
        lines += [f"{row['particle_id']},transferred,downstream_domain_exit,{row['instrument_time_us']},0,{row['instrument_time_us']}" for row in rows]
        lines += [f"{particle},not_transferred,solver_stop,21,0,21" for particle in lost]
        fixture.census.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fixture.receipt.update(counts={"source": 100, "transferred": 97, "not_transferred": 3},
                               transferred_particle_ids=ids, lost_particle_ids=lost)
        fixture.receipt["outputs"] = {"component_states": fixture._identity(fixture.source),
                                      "mother_census": fixture._identity(fixture.census)}
        fixture._write(fixture.receipt_path, fixture.receipt)
        handoff = self.root / "handoff_100"
        prepare_handoff(fixture.receipt_path, fixture.trajectory, fixture.provider, fixture.request, handoff)
        source = self.root / "source_100"
        materialize_measured_source(handoff / "handoff_receipt.json", source)
        events = []
        for index, row in enumerate(rows):
            particle = row["particle_id"]
            time = row["instrument_time_us"] + 100
            if index < 95:
                events.append(_detector(particle, time))
            events.append(_terminal(particle, 1 if index < 95 else (2 if index == 95 else -1), time))
        events.append("status,Fly completed. 97 splats")
        self.log.write_text("\n".join(events), encoding="utf-8")
        report = analyze_measured_component(self.log, source / "source_receipt.json", self.output)
        self.assertEqual(report["counts"]["mother_source"], 100)
        self.assertEqual(report["counts"]["downstream_released"], 97)
        self.assertEqual(report["counts"]["upstream_not_transferred"], 3)
        self.assertEqual(report["counts"]["downstream_timeout"], 1)
        self.assertEqual(report["counts"]["downstream_loss"], 1)
        self.assertEqual(report["detected_fraction_of_mother"], .95)
        self.assertEqual(report["detected_fraction_of_handoff"], 95/97)
        with (self.output / "particle_census.csv").open(newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 100)

    def test_duplicate_terminal_rejected(self) -> None:
        self.log.write_text(self.text + _terminal(7, 1, 7600.57), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate terminal"):
            self._analyze()
        self.assertFalse(self.output.exists())

    def test_unknown_or_upstream_lost_id_rejected(self) -> None:
        for particle in (9, 200):
            with self.subTest(particle=particle):
                self.log.write_text(self.text + "\n" + _terminal(particle, -1, 7600.57), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unknown downstream particle"):
                    self._analyze()

    def test_missing_terminal_rejected(self) -> None:
        self.log.write_text(self.text.replace(_terminal(7, 1, 7600.57), ""), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Missing downstream terminal"):
            self._analyze()

    def test_relative_solver_time_cannot_masquerade_as_absolute(self) -> None:
        self.log.write_text(self.text.replace("7600.51", "100"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Absolute event clock"):
            self._analyze()

    def test_duplicate_detector_and_detector_terminal_conflict_rejected(self) -> None:
        self.log.write_text(self.text.replace(_terminal(1, 1, 7600.51),
                                             _detector(1, 7600.51) + "\n" + _terminal(1, 1, 7600.51)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate detector"):
            self._analyze()
        self.log.write_text(self.text.replace("splat=1", "splat=2", 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Detector and terminal"):
            self._analyze()

    def test_no_hits_and_single_hit_have_no_width(self) -> None:
        self.log.write_text("\n".join((_terminal(1, 2, 7600.51), _terminal(7, -1, 7600.57),
                                       "status,Fly completed. 2 splats")), encoding="utf-8")
        report = self._analyze()
        self.assertEqual(report["counts"]["detected"], 0)
        self.assertIsNone(report["absolute_arrival"]["mean"])
        self.assertIsNone(report["absolute_arrival"]["population_sigma"])
        one_output = self.root / "single_analysis"
        self.log.write_text("\n".join((_detector(1, 7600.51), _terminal(1, 1, 7600.51),
                                       _terminal(7, -1, 7600.57), "status,Fly completed. 2 splats")), encoding="utf-8")
        report = analyze_measured_component(self.log, self.source / "source_receipt.json", one_output)
        self.assertEqual(report["counts"]["detected"], 1)
        self.assertIsNone(report["absolute_arrival"]["population_sigma"])

    def test_source_byte_tamper_and_incomplete_fly_rejected(self) -> None:
        self.log.write_text(self.text.replace("status,Fly completed. 2 splats", ""), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Fly completion"):
            self._analyze()
        self.log.write_text(self.text, encoding="utf-8")
        path = self.source / "component_particle_state.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises((ValueError, AssertionError)):
            self._analyze()


if __name__ == "__main__":
    unittest.main()
