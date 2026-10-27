"""Synthetic lifecycle evidence only: never execute a vendor flight."""
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_analysis import _load_source, analyze_measured_component, _prepare_detector_peak, _save_detector_peak, validate_measured_peak_source_reference
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

    def _peak_contract(self, pulse: float = 7500.0) -> dict:
        timing = self.root / "native_timing.json"
        timing.write_text(json.dumps(dict(schema_version=1, role="native_electrode_timing", pulse_start_us=pulse)))
        source = json.loads((self.source / "source_receipt.json").read_text())
        from common.analysis.peak_metrics import AnalysisSettings
        return dict(method_id="common_gaussian_kde_time_v2", resolution_definition="mean_tof_us/(2*direct_fwhm_tof_us)",
                    time_basis="instrument_arrival_minus_common_extraction_pulse_us",
                    settings={key: value for key, value in vars(AnalysisSettings()).items()},
                    common_time_reference=dict(clock_epoch_id=source["clock_epoch_id"], timing=file_record(timing), field="pulse_start_us"))

    def test_analysis_reads_canonical_source_once(self) -> None:
        canonical = self.source / "component_particle_state.csv"
        open_file, reads = Path.open, []

        def track(path, *args, **kwargs):
            if path == canonical and (not args or args[0] == "r"):
                reads.append(path)
            return open_file(path, *args, **kwargs)

        with patch.object(Path, "open", track):
            _, states, _, _ = _load_source(self.source / "source_receipt.json")
        self.assertEqual(len(reads), 1)
        self.assertIs(type(states[1]["mass_amu"]), float)
        self.assertIs(type(states[1]["charge_state"]), int)

    def test_declared_peak_auto_exports_with_two_hits_unavailable(self) -> None:
        report = analyze_measured_component(self.log, self.source / "source_receipt.json", self.output,
                                            peak_analysis_contract=self._peak_contract())
        peak = report["detector_peak"]
        self.assertEqual(peak["status"], "unavailable_fewer_than_three_hits")
        self.assertIsNone(peak["time_equivalent_resolution"])
        for name in ("detector_peak_samples.csv", "detector_peak.png", "detector_peak.svg", "detector_peak.metadata.json"):
            self.assertTrue((self.output / name).is_file())
        with (self.output / "detector_peak_samples.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertAlmostEqual(float(rows[1]["tof_from_common_pulse_us"])-float(rows[0]["tof_from_common_pulse_us"]), .06)

    def test_common_peak_algorithm_and_time_translation_preserve_exit_spread(self) -> None:
        from common.analysis.peak_metrics import AnalysisSettings, compute_peak_metrics
        source = json.loads((self.source / "source_receipt.json").read_text())
        offsets = [.01, .02, .05, .08, .11]
        states = {i: dict(mass_amu=524.0, charge_state=1, mass_to_charge_Th=524.0, particle_weight=1.0, instrument_time_us=7500+offset)
                  for i, offset in enumerate(offsets, 1)}
        # Every particle flies the same elapsed time; actual exit spread must survive.
        detectors = {i: {"t_us": float(row["instrument_time_us"])+100} for i, row in states.items()}
        contract = self._peak_contract()
        peak, _ = _prepare_detector_peak(contract, self.root, source, states, detectors)
        expected, _ = compute_peak_metrics([100+offset for offset in offsets], 524, AnalysisSettings())
        self.assertEqual(peak["status"], "evaluated")
        self.assertAlmostEqual(peak["fwhm_us"]*1000, expected["direct_fwhm_tof_ns"], places=8)
        self.assertAlmostEqual(peak["time_equivalent_resolution"], expected["time_equivalent_resolution"], places=5)
        peak, spectra = _prepare_detector_peak(contract, self.root, source, states, detectors)
        self.output.mkdir()
        _save_detector_peak(self.output, peak, spectra, states, detectors,
                            dict(counts=dict(detected=5, mother_source=8, downstream_released=6)))
        with (self.output / "detector_peak_spectrum.csv").open(newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 4001)
        metadata = json.loads((self.output / "detector_peak.metadata.json").read_text())
        self.assertEqual(metadata["peak_analysis"]["detected_particle_ids"], [1, 2, 3, 4, 5])
        self.assertTrue((self.output / "detector_peak.png").read_bytes().startswith(b"\x89PNG"))
        shift = 10000
        shifted_states = {i: dict(row, instrument_time_us=float(row["instrument_time_us"])+shift) for i, row in states.items()}
        shifted_detectors = {i: {"t_us": row["t_us"]+shift} for i, row in detectors.items()}
        translated, _ = _prepare_detector_peak(self._peak_contract(7500+shift), self.root, source, shifted_states, shifted_detectors)
        self.assertAlmostEqual(peak["fwhm_us"], translated["fwhm_us"], places=9)
        self.assertAlmostEqual(peak["time_equivalent_resolution"], translated["time_equivalent_resolution"], places=4)

    def test_current_method_keeps_canonical_species_and_explicit_equal_weights(self) -> None:
        source = json.loads((self.source / "source_receipt.json").read_text())
        states = {i: dict(mass_amu=524.0, charge_state=2, mass_to_charge_Th=262.0,
                          particle_weight=3.5, instrument_time_us=7500.1) for i in range(1, 5)}
        detectors = {i: {"t_us": 7600.0 + i*.01} for i in states}
        peak, spectra = _prepare_detector_peak(self._peak_contract(), self.root, source, states, detectors)
        self.assertEqual(peak["species"], dict(mass_amu=524.0, charge_state=2, mass_to_charge_Th=262.0))
        self.assertNotIn("mass_resolution", peak["metrics"])
        self.assertNotIn("mass_grid_Da", spectra)
        self.assertEqual(peak["detected_particle_ids"], [1, 2, 3, 4])
        self.assertEqual(peak["analysis_metadata"]["time_reference"]["clock_qualification"],
                         "validated_epoch_and_frozen_timing")
        # Typed identity propagation is not a multi-charge flight qualification.
        self.assertEqual(peak["qualification"], "detector_survivor_conditioned_time_equivalent_only")
        states[4]["particle_weight"] = 1.0
        with self.assertRaisesRegex(ValueError, "nonuniform weights"):
            _prepare_detector_peak(self._peak_contract(), self.root, source, states, detectors)

    def test_old_or_unknown_method_is_not_an_active_request(self) -> None:
        for method in ("common_gaussian_kde_time_v1", "unknown"):
            contract = self._peak_contract()
            contract["method_id"] = method
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, "Unsupported measured"):
                analyze_measured_component(self.log, self.source / "source_receipt.json", self.output,
                                           peak_analysis_contract=contract)
            self.assertFalse(self.output.exists())

    def test_peak_empty_few_and_zero_variance_are_unavailable(self) -> None:
        source = json.loads((self.source / "source_receipt.json").read_text())
        states = {i: dict(mass_amu=524.0, charge_state=1, mass_to_charge_Th=524.0, particle_weight=3.5, instrument_time_us=7500.1) for i in range(1, 4)}
        for times, status in (([], "unavailable_fewer_than_three_hits"), ([7600], "unavailable_fewer_than_three_hits"),
                              ([7600, 7601], "unavailable_fewer_than_three_hits"), ([7600]*3, "unavailable_zero_variance")):
            with self.subTest(times=times):
                peak, spectra = _prepare_detector_peak(self._peak_contract(), self.root, source, states,
                                                        {i: {"t_us": time} for i, time in enumerate(times, 1)})
                self.assertEqual(peak["status"], status)
                self.assertIsNone(spectra)
                self.assertIsNone(peak["fwhm_us"])
                metadata = peak["analysis_metadata"]
                self.assertEqual(metadata["sample_count"], len(times))
                self.assertEqual(metadata["weight_sum"], 3.5 * len(times))
                self.assertEqual(metadata["effective_sample_count"], float(len(times)))
                self.assertEqual(metadata["sample_sigma_ddof"], 1)
                self.assertEqual(metadata["weight_policy"], "equal_positive_relative_weights")
                self.assertEqual(metadata["status"], status)
                self.assertEqual(metadata["units"]["time_width"], "ns")
                self.assertEqual(metadata["settings"], peak["settings"])
                self.assertEqual(metadata["time_reference"]["reference_time_us"], 7500.)
                self.assertEqual(metadata["time_reference"]["clock_qualification"], "validated_epoch_and_frozen_timing")
                self.assertEqual(metadata["scientific_qualification"], "not_assessed")

    def test_missing_peak_contract_keeps_actual_weights_without_inventing_time_reference(self) -> None:
        source = json.loads((self.source / "source_receipt.json").read_text())
        states = {i: dict(mass_amu=524., charge_state=1, mass_to_charge_Th=524.,
                          particle_weight=weight, instrument_time_us=7500.1)
                  for i, weight in ((7, .125), (19, 8.))}
        detectors = {7: {"t_us": 7600.}, 19: {"t_us": 7601.}}
        peak, spectra = _prepare_detector_peak(None, self.root, source, states, detectors)
        metadata = peak["analysis_metadata"]
        self.assertIsNone(spectra)
        self.assertIsNone(peak["fwhm_us"])
        self.assertIsNone(metadata["method_id"])
        self.assertIsNone(metadata["settings"])
        self.assertEqual(metadata["sample_count"], 2)
        self.assertEqual(metadata["weight_sum"], 8.125)
        self.assertAlmostEqual(metadata["effective_sample_count"], 8.125**2 / (.125**2 + 8.**2))
        self.assertEqual(metadata["weight_policy"], "nonuniform_positive_relative_weights__kde_unsupported")
        self.assertEqual(metadata["time_reference"]["clock_qualification"], "unspecified")
        self.assertEqual(peak["detected_particle_ids"], [7, 19])

    def test_single_centroid_source_can_validate_without_width_analysis(self) -> None:
        source = json.loads((self.source / "source_receipt.json").read_text())
        states = {1: dict(mass_amu=524.0, charge_state=1, mass_to_charge_Th=524.0, particle_weight=1.0, instrument_time_us=7500.1)}
        contract = self._peak_contract()
        self.assertEqual(validate_measured_peak_source_reference(contract, self.root, source, states), 7500)
        peak, _ = _prepare_detector_peak(contract, self.root, source, states, {})
        self.assertEqual(peak["status"], "unavailable_fewer_than_three_hits")

    def test_peak_clock_source_and_invalid_reference_fail_before_output(self) -> None:
        for change in ("epoch", "hash", "field", "late", "nan"):
            with self.subTest(change=change):
                contract = self._peak_contract(7601 if change == "late" else (float("nan") if change == "nan" else 7500))
                if change == "epoch":
                    contract["common_time_reference"]["clock_epoch_id"] = "wrong"
                elif change == "hash":
                    contract["common_time_reference"]["timing"]["sha256"] = "0"*64
                elif change == "field":
                    contract["common_time_reference"]["field"] = "primary_quench_us"
                with self.assertRaises((ValueError, AssertionError)):
                    analyze_measured_component(self.log, self.source / "source_receipt.json", self.output,
                                               peak_analysis_contract=contract)
                self.assertFalse(self.output.exists())

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
        fixture._prepare(handoff)
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
