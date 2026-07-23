from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = load_module(
    "rf_handoff_adapter",
    PROJECT_ROOT / "analysis" / "rf_handoff_adapter.py",
)
PREPARE = load_module(
    "prepare_rf_handoff_projection",
    PROJECT_ROOT / "analysis" / "prepare_rf_handoff_projection.py",
)
ANALYZE = load_module(
    "analyze_rf_handoff_projection",
    PROJECT_ROOT / "analysis" / "analyze_rf_handoff_projection.py",
)
PULSE_ANALYZE = load_module(
    "analyze_rf_handoff_pulse",
    PROJECT_ROOT / "analysis" / "analyze_rf_handoff_pulse.py",
)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class HandoffConsumerModeTests(unittest.TestCase):
    def test_mode_is_candidate_and_forbids_physical_claims(self) -> None:
        validated = PREPARE.validate_mode()
        self.assertFalse(validated["mode"]["claims"]["physical_link_claim_allowed"])

    def test_pulse_mode_requires_one_comsol_source_and_instrument_clock(self) -> None:
        mode_path = PROJECT_ROOT / "config" / "modes" / "rf_handoff_pulse.json"
        validated = PREPARE.validate_mode(mode_path)
        self.assertEqual(validated["mode"]["comparison_kind"], "pulse_functional")
        self.assertEqual(len(validated["mode"]["source_cases"]), 1)
        self.assertEqual(validated["mode"]["clock_policy"]["solver_clock"], "instrument_time")
        self.assertEqual(validated["mode"]["pulse"]["waveform"], "ideal_rectangular")
        self.assertEqual(validated["mode"]["projection"]["target_origin_mm"][0], -62.8)
        self.assertFalse(validated["mode"]["claims"]["physical_link_claim_allowed"])
        self.assertFalse(validated["mode"]["claims"]["resolution_claim_allowed"])
        self.assertFalse(validated["mode"]["claims"]["formal_asset_modification_allowed"])

    def test_hybrid_mesh_pair_mode_is_supported_without_physical_claims(self) -> None:
        mode_path = PROJECT_ROOT / "config" / "modes" / "rf_hybrid_mesh_projection.json"
        validated = PREPARE.validate_mode(mode_path)
        self.assertEqual(validated["mode"]["comparison_kind"], "rf_mesh_pair")
        self.assertEqual(
            {case["mesh_role"] for case in validated["mode"]["source_cases"]},
            {"low_cost_candidate", "reference"},
        )
        self.assertFalse(validated["mode"]["claims"]["physical_link_claim_allowed"])


class HandoffBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.canonical = self.root / "canonical.csv"
        self.row_map = self.root / "row_map.csv"
        self.ion = self.root / "particles.ion"
        self.metadata = self.root / "metadata.json"
        write_csv(self.canonical, [
            "particle_id", "clock_epoch_id", "instrument_time_us", "lineage_age_us",
            "particle_age_us", "mass_amu", "charge_state", "position_x_mm",
            "position_y_mm", "position_z_mm", "velocity_x_m_s", "velocity_y_m_s",
            "velocity_z_m_s", "kinetic_energy_eV",
        ], [{
            "particle_id": 7, "clock_epoch_id": "epoch", "instrument_time_us": 15,
            "lineage_age_us": 5, "particle_age_us": 2, "mass_amu": 100,
            "charge_state": 1, "position_x_mm": -48.8, "position_y_mm": 0.1,
            "position_z_mm": -18.4, "velocity_x_m_s": 1964.5389500506553,
            "velocity_y_m_s": 0, "velocity_z_m_s": 0, "kinetic_energy_eV": 2,
        }])
        write_csv(self.row_map, [
            "solver_row_index", "particle_id", "instrument_time_us", "lineage_age_us",
            "particle_age_us", "solver_birth_time_us", "azimuth_deg", "elevation_deg",
        ], [{
            "solver_row_index": 1, "particle_id": 7, "instrument_time_us": 15,
            "lineage_age_us": 5, "particle_age_us": 2, "solver_birth_time_us": 0,
            "azimuth_deg": 0, "elevation_deg": 0,
        }])
        self.ion.write_text("0,100,1,-48.8,0.1,-18.4,0,0,2,1,3\n", encoding="utf-8")
        contract = PREPARE.repo_path(PREPARE.load_json(PREPARE.DEFAULT_MODE)["handoff_contract"])
        self.metadata.write_text(json.dumps({
            "status": "PASS",
            "package_generation_allowed": False,
            "contract": {"sha256": PREPARE.sha256(contract)},
            "outputs": {
                "canonical_handoff_csv": {"sha256": PREPARE.sha256(self.canonical)},
                "oatof_ion": {"sha256": PREPARE.sha256(self.ion)},
                "row_map_csv": {"sha256": PREPARE.sha256(self.row_map)},
            },
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_bundle_preserves_identity_clocks_and_derived_ion(self) -> None:
        result = PREPARE.validate_bundle(self.canonical, self.ion, self.row_map, self.metadata)
        self.assertEqual(result["particles"], 1)
        self.assertTrue(result["functional_projection_runtime_authorized"])
        self.assertFalse(result["physical_link_claim_allowed"])

    def test_changed_ion_is_rejected(self) -> None:
        self.ion.write_text("0,100,1,-48.8,0.1,-18.4,0,0,3,1,3\n", encoding="utf-8")
        metadata = json.loads(self.metadata.read_text(encoding="utf-8"))
        metadata["outputs"]["oatof_ion"]["sha256"] = PREPARE.sha256(self.ion)
        self.metadata.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from the canonical"):
            PREPARE.validate_bundle(self.canonical, self.ion, self.row_map, self.metadata)

    def test_changed_ion_direction_is_rejected(self) -> None:
        self.ion.write_text("0,100,1,-48.8,0.1,-18.4,90,0,2,1,3\n", encoding="utf-8")
        metadata = json.loads(self.metadata.read_text(encoding="utf-8"))
        metadata["outputs"]["oatof_ion"]["sha256"] = PREPARE.sha256(self.ion)
        self.metadata.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "direction"):
            PREPARE.validate_bundle(self.canonical, self.ion, self.row_map, self.metadata)

    def test_nonfinite_canonical_velocity_is_rejected(self) -> None:
        rows = PREPARE._read_csv(self.canonical)
        rows[0]["velocity_x_m_s"] = "NaN"
        write_csv(self.canonical, list(rows[0]), rows)
        metadata = json.loads(self.metadata.read_text(encoding="utf-8"))
        metadata["outputs"]["canonical_handoff_csv"]["sha256"] = PREPARE.sha256(self.canonical)
        self.metadata.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "finite"):
            PREPARE.validate_bundle(self.canonical, self.ion, self.row_map, self.metadata)


class HandoffAnalysisTests(unittest.TestCase):
    def test_detector_plane_crossing_outside_active_radius_is_not_a_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = root / "canonical.csv"
            row_map = root / "row.csv"
            result_path = root / "result.csv"
            write_csv(canonical, ["particle_id", "clock_epoch_id"], [
                {"particle_id": 1, "clock_epoch_id": "epoch"}
            ])
            write_csv(row_map, [
                "solver_row_index", "particle_id", "instrument_time_us",
                "lineage_age_us", "particle_age_us",
            ], [{
                "solver_row_index": 1, "particle_id": 1, "instrument_time_us": 10,
                "lineage_age_us": 5, "particle_age_us": 2,
            }])
            write_csv(result_path, ["Ion", "TofUs", "XMm", "YMm", "Hit"], [{
                "Ion": 1, "TofUs": 30, "XMm": 90, "YMm": 0, "Hit": True,
            }])
            rows = ANALYZE._normalize_case({
                "case_id": "case", "upstream_solver": "COMSOL",
                "canonical": str(canonical), "row_map": str(row_map),
                "downstream_results": {"COMSOL": str(result_path)},
            }, 48.8, 0.0, 40.0)
            self.assertFalse(rows[0]["hit"])

    def test_global_detector_clocks_and_functional_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for case_index, (case_id, upstream) in enumerate((
                ("rf_comsol_n100", "COMSOL"), ("rf_simion_n100", "SIMION")
            )):
                canonical = root / f"{case_id}_canonical.csv"
                row_map = root / f"{case_id}_row.csv"
                write_csv(canonical, [
                    "particle_id", "clock_epoch_id", "instrument_time_us",
                ], [
                    {"particle_id": index, "clock_epoch_id": "epoch", "instrument_time_us": 10 + index}
                    for index in range(1, 101)
                ])
                write_csv(row_map, [
                    "solver_row_index", "particle_id", "instrument_time_us",
                    "lineage_age_us", "particle_age_us",
                ], [
                    {"solver_row_index": index, "particle_id": index,
                     "instrument_time_us": 10 + index, "lineage_age_us": 5, "particle_age_us": 2}
                    for index in range(1, 101)
                ])
                downstream = {}
                for solver_index, solver in enumerate(("COMSOL", "SIMION")):
                    result_path = root / f"{case_id}_{solver}.csv"
                    write_csv(result_path, ["Ion", "TofUs", "XMm", "YMm", "Hit"], [
                        {"Ion": index, "TofUs": 30 + 0.01 * case_index + 0.001 * solver_index,
                         "XMm": 48.8 + 0.2 + 0.005 * case_index, "YMm": 0.1, "Hit": True}
                        for index in range(1, 101)
                    ])
                    downstream[solver] = str(result_path)
                cases.append({
                    "case_id": case_id, "upstream_solver": upstream,
                    "canonical": str(canonical), "row_map": str(row_map),
                    "downstream_results": downstream,
                })
            manifest = root / "inputs.json"
            manifest.write_text(json.dumps({
                "resolved_geometry": str(PROJECT_ROOT / "config" / "resolved_geometry.json"),
                "cases": cases,
            }), encoding="utf-8")
            result = ANALYZE.analyze(manifest, root / "results")
            self.assertEqual(result["status"], "CONDITIONAL_PASS")
            self.assertEqual(result["clock_reconstruction"], "PASS")
            self.assertEqual(result["physical_link_status"], "BLOCKED")
            self.assertEqual(
                result["cross_ensemble_comparisons"]["COMSOL"]["detector_classification_change_count"],
                0,
            )
            self.assertIsNotNone(result["metrics"]["COMSOL"]["rf_comsol_n100"]["detector_r99_mm"])
            detector_rows = ANALYZE._read_csv(root / "results" / "detector_particles.csv")
            first = detector_rows[0]
            self.assertAlmostEqual(float(first["detector_instrument_time_us"]), 41.0)
            self.assertAlmostEqual(float(first["detector_lineage_age_us"]), 35.0)
            self.assertAlmostEqual(float(first["detector_particle_age_us"]), 32.0)


class HandoffPulseAnalysisTests(unittest.TestCase):
    def test_sparse_events_preserve_entry_and_pulse_velocity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = root / "canonical.csv"
            timed = root / "timed.csv"
            control = root / "control.csv"
            log = root / "timed.log"
            write_csv(canonical, [
                "particle_id", "instrument_time_us", "position_x_mm", "position_y_mm",
                "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
            ], [{
                "particle_id": 1, "instrument_time_us": 45, "position_x_mm": -62.8,
                "position_y_mm": 0.1, "position_z_mm": -18.4, "velocity_x_m_s": 2000,
                "velocity_y_m_s": 20, "velocity_z_m_s": -30,
            }])
            result_fields = ["Ion", "Hit", "TofUs"]
            write_csv(timed, result_fields, [{"Ion": 1, "Hit": "True", "TofUs": 40}])
            write_csv(control, result_fields, [{"Ion": 1, "Hit": "False", "TofUs": "NaN"}])
            log.write_text("\n".join([
                "TRACE: handoff_pulse_contract mode=1 time_us=54 width_us=1 pre_all_v=0 post_repeller_v=2240 grid1_v=1760",
                "TRACE: handoff_pulse_on ion=1 instrument_time_us=54 x_mm=-48.8 y_mm=0.2 z_mm=-18.3 vx_mm_per_us=2 vy_mm_per_us=0.02 vz_mm_per_us=-0.03",
                "TRACE: handoff_terminal_raw ion=1 instance=4 instrument_time_us=85 x_mm=49 y_mm=1 z_mm=19.8 vx_mm_per_us=0.1 vy_mm_per_us=0.2 vz_mm_per_us=-30",
            ]), encoding="utf-8")
            events_path = root / "events.csv"
            events, outcomes = PULSE_ANALYZE.build_events(
                PULSE_ANALYZE.read_csv(canonical), [{
                    "solver_row_index": "1", "particle_id": "1",
                }], PULSE_ANALYZE.read_csv(timed),
                PULSE_ANALYZE.parse_log(log)[2], PULSE_ANALYZE.parse_log(log)[3],
            )
            PULSE_ANALYZE.write_csv(events_path, events)
            saved = PULSE_ANALYZE.read_csv(events_path)
            self.assertEqual([row["event"] for row in saved], ["effective_entry", "pulse_on", "terminal"])
            self.assertEqual(float(saved[1]["vx_m_s"]), 2000.0)
            self.assertEqual(saved[2]["status"], "detector_hit")
            self.assertEqual(outcomes[1], "detector_hit")

    def test_solver_rows_are_mapped_to_nonsequential_particle_ids(self) -> None:
        canonical_rows = [
            {
                "particle_id": "101", "instrument_time_us": "45",
                "position_x_mm": "-62.8", "position_y_mm": "0.1",
                "position_z_mm": "-18.4", "velocity_x_m_s": "2000",
                "velocity_y_m_s": "20", "velocity_z_m_s": "-30",
            },
            {
                "particle_id": "205", "instrument_time_us": "46",
                "position_x_mm": "-62.8", "position_y_mm": "0.2",
                "position_z_mm": "-18.3", "velocity_x_m_s": "1900",
                "velocity_y_m_s": "10", "velocity_z_m_s": "-20",
            },
        ]
        row_map = [
            {"solver_row_index": "1", "particle_id": "101"},
            {"solver_row_index": "2", "particle_id": "205"},
        ]
        timed_rows = [
            {"Ion": "1", "Hit": "True", "TofUs": "40"},
            {"Ion": "2", "Hit": "False", "TofUs": "NaN"},
        ]
        pulse_states = {
            1: {"time": 54, "x": -48.8, "y": 0.2, "z": -18.3,
                "vx": 2, "vy": 0.02, "vz": -0.03},
            2: {"time": 54, "x": -48.7, "y": 0.3, "z": -18.2,
                "vx": 1.9, "vy": 0.01, "vz": -0.02},
        }
        terminal_states = {
            1: {"time": 85, "x": 49, "y": 1, "z": 19.8,
                "vx": 0.1, "vy": 0.2, "vz": -30, "instance": 4},
            2: {"time": 80, "x": 10, "y": 2, "z": 12,
                "vx": 0.1, "vy": 0.1, "vz": -20, "instance": 1},
        }
        events, outcomes = PULSE_ANALYZE.build_events(
            canonical_rows, row_map, timed_rows, pulse_states, terminal_states,
        )
        self.assertEqual(set(outcomes), {101, 205})
        self.assertEqual(outcomes[101], "detector_hit")
        self.assertEqual(outcomes[205], "lost")
        self.assertEqual(
            [(row["particle_id"], row["event"]) for row in events],
            [
                (101, "effective_entry"), (101, "pulse_on"), (101, "terminal"),
                (205, "effective_entry"), (205, "pulse_on"), (205, "terminal"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
