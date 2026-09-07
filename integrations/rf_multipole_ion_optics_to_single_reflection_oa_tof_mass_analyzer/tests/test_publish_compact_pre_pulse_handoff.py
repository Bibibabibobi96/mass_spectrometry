from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure import (
    publish_compact_pre_pulse_handoff as subject,
)


class PublishCompactPrePulseHandoffTests(unittest.TestCase):
    def test_v2_receipt_requires_the_frozen_winning_ranking(self) -> None:
        """v1 stays readable; v2 must carry the new selector's score evidence."""

        receipt = {
            "schema_version": 1,
            "role": "rf_oatof_compact_pre_pulse_trace_handoff_receipt",
            "status": "success",
            "method": "native_trace_detector_blind_pulse_selection_v2",
            "selection": {
                "mother_population_count": 1,
                "pulse_eligible_count": 1,
                "pulse_eligible_particle_ids": [1],
                "postselection_prohibited": True,
                "ranking": {
                    "selection_order": [
                        "maximize_pulse_eligible_count",
                        "minimize_normalized_xyz_spread_norm",
                        "minimize_normalized_xyz_centroid_distance",
                        "select_earlier_time",
                    ],
                    "metric_population_basis": "pulse_eligible",
                    "normalization_bounds": {
                        axis: {
                            "center_mm": 0.0, "full_width_mm": 2.0,
                            "minimum_mm": -1.0, "maximum_mm": 1.0,
                        }
                        for axis in "xyz"
                    },
                    "normalized_xyz_spread": {axis: 0.0 for axis in "xyz"},
                    "normalized_xyz_spread_norm": 0.0,
                    "normalized_xyz_centroid": {axis: 0.0 for axis in "xyz"},
                    "normalized_xyz_centroid_distance": 0.0,
                },
            },
            "pulse_target_state": {
                "path": "handoff.csv", "sha256": "A" * 64,
                "particle_count": 1, "ordered_particle_id_sha256": "B" * 64,
                "source_state_epoch": "pulse_effective_time",
                "coordinate_frame": "oatof_global_cartesian",
                "clock_basis": "canonical_instrument_time_us",
                "clock_authority": "detector_blind_native_trace_selection",
                "pulse_effective_time_us": 1.0,
            },
        }
        validate_schema(receipt, subject.HANDOFF_RECEIPT_SCHEMA_PATH)
        del receipt["selection"]["ranking"]
        with self.assertRaises(ContractError):
            validate_schema(receipt, subject.HANDOFF_RECEIPT_SCHEMA_PATH)

    def test_legacy_receipt_recovers_terminal_census_without_reselecting_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, results, inputs = root / "source", root / "source" / "results", root / "source" / "inputs"
            results.mkdir(parents=True); inputs.mkdir()
            handoff = results / "pre_pulse_compact_handoff.csv"
            handoff.write_text("particle_id\n1\n", encoding="utf-8")
            contract = inputs / "pre_pulse_time_series_screening_contract.json"
            contract.write_text("{}\n", encoding="utf-8")
            row_map = inputs / "single_flight_particle_row_map.csv"
            row_map.write_text("source_particle_id\n1\n2\n", encoding="utf-8")
            selection = {"pulse_effective_time_us": 1.5, "pulse_eligible_particle_ids": [1],
                         "mother_population_count": 2, "alive_count": 2, "pulse_eligible_count": 1,
                         "postselection_prohibited": True}
            (results / "pre_pulse_compact_handoff_selection.json").write_text(json.dumps(selection), encoding="utf-8")
            receipt = {
                "schema_version": 1, "role": "rf_oatof_compact_pre_pulse_trace_handoff_receipt", "status": "success",
                "method": "native_trace_detector_blind_pulse_selection_v1",
                "producer": {"screening_contract": {"bytes": contract.stat().st_size, "sha256": file_sha256(contract)}}, "selection": selection,
                "pulse_target_state": {"sha256": file_sha256(handoff), "particle_count": 1,
                    "ordered_particle_id_sha256": hashlib.sha256(json.dumps([1], separators=(",", ":")).encode("utf-8")).hexdigest().upper(),
                    "source_state_epoch": "pulse_effective_time", "coordinate_frame": "oatof_global_cartesian",
                    "clock_basis": "canonical_instrument_time_us", "clock_authority": "detector_blind_native_trace_selection", "pulse_effective_time_us": 1.5},
            }
            receipt_path = results / "pre_pulse_compact_handoff_receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            retention = source / "retention_actions.json"
            retention.write_text(json.dumps({"removed": [{"path": "logs/simion__batch01.trace.log", "bytes": 0}]}), encoding="utf-8")
            manifest = {
                "role": "simulation_run_manifest", "status": "success",
                "inputs": {"particle_row_map": {"exists": True, "bytes": row_map.stat().st_size, "sha256": file_sha256(row_map)}},
                "outputs": [{"path": str(path.resolve()), "exists": True, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
                            for path in (handoff, receipt_path, results / "pre_pulse_compact_handoff_selection.json", retention)],
            }
            (source / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            trace = root / "simion__batch01.trace.log"
            trace.write_text("retained task copy", encoding="utf-8")
            retention.write_text(json.dumps({"removed": [{"path": "logs/simion__batch01.trace.log", "bytes": trace.stat().st_size}]}), encoding="utf-8")
            manifest["outputs"][-1].update(bytes=retention.stat().st_size, sha256=file_sha256(retention))
            (source / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "20260904_140500__analysis__python__compact-terminal-recovery__n2"

            def extract(*, trace_paths: list[Path], frozen_particle_ids: list[int], output_path: Path) -> dict[str, object]:
                self.assertEqual(trace_paths, [trace.resolve()]); self.assertEqual(frozen_particle_ids, [1, 2])
                output_path.write_text("particle_id,terminal_reason\n1,splat\n2,geometry_collision\n", encoding="utf-8")
                return {"mother_population_count": 2, "terminal_particle_count": 1, "unknown_terminal_count": 1,
                        "accounted_particle_count": 2, "complete": False,
                        "by_reason": {"geometry_collision": 1, "splat": 1},
                        "terminal_state": {"path": str(output_path), "bytes": output_path.stat().st_size, "sha256": file_sha256(output_path)}}

            with patch.object(subject, "extract_natural_terminal_states", side_effect=extract):
                subject.publish(repo_root=Path.cwd(), source_run_dir=source, output_run_dir=output, terminal_trace_logs=[trace])
            published = json.loads((output / "results" / "pre_pulse_compact_handoff_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(published["selection"]["pulse_eligible_particle_ids"], selection["pulse_eligible_particle_ids"])
            self.assertEqual(published["selection"]["pulse_population_partition"], {
                "not_observed_alive": 0, "alive_not_eligible": 1, "eligible": 1,
            })
            self.assertFalse(published["natural_terminal_census"]["complete"])
            self.assertEqual(published["natural_terminal_census"]["unknown_terminal_count"], 1)
            self.assertEqual(published["producer"]["terminal_trace_recovery"]["verification_limit"], "source retention actions record original names and bytes only; no source TRACE sha256 exists")
            self.assertTrue((output / "results" / subject.TERMINAL_STATE_NAME).is_file())
