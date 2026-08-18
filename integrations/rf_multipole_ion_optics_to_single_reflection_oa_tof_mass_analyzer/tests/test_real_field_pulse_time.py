from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.select_real_field_pulse_time import (
    SELECTION_ORDER,
    select_and_write,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    select_detector_blind_real_field_pulse_time,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    _publish_detector_blind_pulse_selection,
    _publish_pulse_timing_transition,
    _publish_verified_pulse_receipt,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _profile() -> dict[str, object]:
    return {
        "profile_id": "layout_resolved_axial_provisional_xy2_v1",
        "event": "pre_pulse_state",
        "axes": {
            "x": {
                "center_binding": "particle_source.center_x_mm",
                "full_width_mm": 2.0,
            },
            "y": {
                "center_binding": "particle_source.center_y_mm",
                "full_width_mm": 2.0,
            },
            "z": {
                "center_binding": "particle_source.center_z_mm",
                "full_width_binding": "particle_source.size_z_mm",
            },
        },
        "selection_uses_detector_outcome": False,
    }


def _geometry() -> dict[str, object]:
    return {
        "role": "oa_tof_resolved_contract_do_not_edit",
        "particle_source": {
            "center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": 0.0,
            "size_z_mm": 2.2,
        },
        "coordinate_convention": {
            "accelerator_axis_x": 0.0, "accelerator_axis_y": 0.0,
        },
        "geometry_mm": {
            "accelerator_repeller_z": -1.0,
            "accelerator_grid1_z": 1.0,
            "accelerator_bore_half": 1.0,
        },
    }


def _rows() -> list[dict[str, str]]:
    result = []
    for sample_index, (time_us, coordinates) in enumerate((
        (10.0, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 2.0))),
        (11.0, ((0.4, 0.0, 0.0), (0.4, 0.0, 0.0), (0.4, 0.0, 0.0))),
        (12.0, ((0.4, 0.0, 0.0), (0.4, 0.0, 0.0), (0.4, 0.0, 0.0))),
    ), start=1):
        result.extend({
            "particle_id": str(particle_id),
            "event": "pre_pulse_time_series_state",
            "sample_index": str(sample_index),
            "instrument_time_us": str(time_us),
            "actual_instrument_time_us": str(time_us),
            "x_mm": str(x), "y_mm": str(y), "z_mm": str(z),
            "survival_status": "alive",
        } for particle_id, (x, y, z) in enumerate(coordinates, start=1))
    return result


class RealFieldPulseCoreTests(unittest.TestCase):
    def test_rank_prioritizes_eligibility_and_uses_earlier_final_tie(self) -> None:
        result = select_detector_blind_real_field_pulse_time(
            _rows(), _geometry(), _profile(),
            candidate_times_us=[10.0, 11.0, 12.0],
            frozen_particle_ids=[1, 2, 3],
            ballistic_seed_time_us=11.5,
        )
        self.assertEqual(result["selected_time_us"], 11.0)
        self.assertEqual(
            [row["candidate_time_us"] for row in result["candidates_ranked"]],
            [11.0, 12.0, 10.0],
        )
        self.assertEqual(result["candidates_ranked"][0]["pulse_eligible_ids"], [1, 2, 3])
        self.assertFalse(result["detector_results_used"])

    def test_source_box_boundaries_are_inclusive(self) -> None:
        rows = [
            {"particle_id": "1", "event": "pre_pulse_time_series_state", "sample_index": "1", "instrument_time_us": "1", "actual_instrument_time_us": "1", "x_mm": "-0.5", "y_mm": "0.5", "z_mm": "0.5", "survival_status": "alive"},
            {"particle_id": "2", "event": "pre_pulse_time_series_state", "sample_index": "1", "instrument_time_us": "1", "actual_instrument_time_us": "1", "x_mm": "1.0000001", "y_mm": "0", "z_mm": "0", "survival_status": "alive"},
        ]
        result = select_detector_blind_real_field_pulse_time(
            rows, _geometry(), _profile(), candidate_times_us=[1.0],
            frozen_particle_ids=[1, 2], ballistic_seed_time_us=1.0,
        )
        self.assertEqual(result["candidates_ranked"][0]["source_region_ids"], [1])
        self.assertEqual(result["source_region_bounds"]["x"]["full_width_mm"], 2.0)
        self.assertEqual(result["source_region_bounds"]["z"]["full_width_mm"], 2.2)

    def test_allows_physical_loss_with_complete_frozen_denominator(self) -> None:
        rows = [
            row for row in _rows()
            if not (row["particle_id"] == "3" and int(row["sample_index"]) >= 2)
        ]
        result = select_detector_blind_real_field_pulse_time(
            rows, _geometry(), _profile(),
            candidate_times_us=[10.0, 11.0, 12.0],
            frozen_particle_ids=[1, 2, 3], ballistic_seed_time_us=11.5,
        )
        by_sample = {
            row["sample_index"]: row for row in result["candidates_ranked"]
        }
        self.assertEqual(by_sample[2]["alive_particle_ids"], [1, 2])
        self.assertEqual(by_sample[2]["missing_particle_ids"], [3])
        self.assertEqual(by_sample[2]["population_count"], 3)
        self.assertEqual(by_sample[2]["alive_count"], 2)
        self.assertIn(3, by_sample[2]["pulse_noneligible_ids"])
        self.assertIn(3, by_sample[2]["transverse_nonbore_ids"])

    def test_rejects_particle_resurrection_after_missing_sample(self) -> None:
        rows = [
            row for row in _rows()
            if not (row["particle_id"] == "3" and row["sample_index"] == "2")
        ]
        with self.assertRaisesRegex(ContractError, "alive prefix"):
            select_detector_blind_real_field_pulse_time(
                rows, _geometry(), _profile(),
                candidate_times_us=[10.0, 11.0, 12.0],
                frozen_particle_ids=[1, 2, 3], ballistic_seed_time_us=11.5,
            )

    def test_rejects_candidate_with_no_alive_states(self) -> None:
        rows = [row for row in _rows() if row["sample_index"] != "3"]
        with self.assertRaisesRegex(ContractError, "no alive states"):
            select_detector_blind_real_field_pulse_time(
                rows, _geometry(), _profile(),
                candidate_times_us=[10.0, 11.0, 12.0],
                frozen_particle_ids=[1, 2, 3], ballistic_seed_time_us=11.5,
            )

    def test_rejects_actual_time_outside_candidate_tolerance(self) -> None:
        rows = _rows()
        rows[0]["actual_instrument_time_us"] = "10.000001"
        with self.assertRaisesRegex(ContractError, "time landing differs"):
            select_detector_blind_real_field_pulse_time(
                rows, _geometry(), _profile(),
                candidate_times_us=[10.0, 11.0, 12.0],
                frozen_particle_ids=[1, 2, 3], ballistic_seed_time_us=11.5,
            )


class RealFieldPulseAnalysisTests(unittest.TestCase):
    def _write_inputs(
        self, root: Path, *, detector_column: bool = False, physical_loss: bool = False,
    ) -> dict[str, Path]:
        paths = {name: root / filename for name, filename in (
            ("states", "states.csv"), ("geometry", "geometry.json"),
            ("configuration", "configuration.json"), ("schedule", "schedule.json"),
            ("contract", "screening_contract.json"),
            ("screening_receipt", "screening_receipt.json"),
            ("population", "population.json"),
            ("population_table", "population.csv"),
            ("source", "source.json"), ("connection", "connection.json"),
            ("manifest", "run_manifest.json"), ("table", "candidates.csv"),
            ("receipt", "candidate_receipt.json"),
        )}
        columns = [
            "particle_id", "event", "sample_index", "instrument_time_us",
            "actual_instrument_time_us", "x_mm", "y_mm", "z_mm",
            "survival_status",
        ]
        if detector_column:
            columns.append("detector_hit")
        state_rows = [
            row for row in _rows()
            if not (
                physical_loss
                and row["particle_id"] == "3"
                and int(row["sample_index"]) >= 2
            )
        ]
        with paths["states"].open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for row in state_rows:
                writer.writerow({**row, **({"detector_hit": "false"} if detector_column else {})})
        paths["geometry"].write_text(json.dumps(_geometry()), encoding="utf-8")
        paths["configuration"].write_text(json.dumps({
            "schema_version": 5,
            "role": "rf_oatof_simion_single_flight_configuration",
            "source_region_diagnostic_profiles": [_profile()],
        }), encoding="utf-8")
        paths["schedule"].write_text(json.dumps({
            "schema_version": 1,
            "role": "rf_oatof_resolved_single_flight_pulse_schedule",
            "pulse_effective_time_us": 11.5,
        }), encoding="utf-8")
        contract = {
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "pulse_disabled": True,
            "resolution_claim_allowed": False,
            "sample_times_us": [10.0, 11.0, 12.0],
            "rf_time_grid": {"sample_count": 3},
            "selection_order": SELECTION_ORDER,
            "identities": {
                "campaign_id": "campaign", "experiment_id": "experiment",
                "connection_profile_id": "profile",
                "ordered_particle_id_sha256": "",
                "layout_profile_id": "layout", "field_profile_id": "field",
                "time_integration_profile_id": "dt",
                "spatial_window_profile_id": (
                    "layout_resolved_axial_provisional_xy2_v1"
                ),
            },
        }
        population_ids = [1, 2, 3]
        from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
            _observed_id_set,
        )
        ordered_sha = _observed_id_set(population_ids)["ordered_particle_id_sha256"]
        contract["identities"]["ordered_particle_id_sha256"] = ordered_sha
        paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
        with paths["population_table"].open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=["particle_id"], lineterminator="\n")
            writer.writeheader()
            writer.writerows({"particle_id": value} for value in population_ids)
        paths["population"].write_text(json.dumps({
            "role": "rf_oatof_resolved_population_contract",
            "source_authority": {
                "table_binding": "prepared_deterministic_prefix",
                "table": {"sha256": file_sha256(paths["population_table"])},
            },
            "execution_population": {
                "particle_count": 3,
                "ordered_particle_id_sha256": ordered_sha,
            },
        }), encoding="utf-8")
        paths["source"].write_text(json.dumps({
            "role": "rf_multipole_oatof_source_contract",
        }), encoding="utf-8")
        paths["connection"].write_text(json.dumps({
            "role": "resolved_connection_do_not_edit",
            "selection": {"connection_profile_id": "profile"},
            "spatial_registration": {}, "connector": {}, "port_geometry": {},
            "transition_aperture": {}, "effective_clear_radius_mm": 1.0,
            "potential_alignment": {}, "clock_alignment": {},
            "field_ownership_segments": [],
        }), encoding="utf-8")
        receipt_identities = {
            key: contract["identities"][key]
            for key in (
                "campaign_id", "experiment_id", "connection_profile_id",
                "ordered_particle_id_sha256", "layout_profile_id",
                "field_profile_id", "time_integration_profile_id",
            )
        }
        paths["screening_receipt"].write_text(json.dumps({
            "role": "rf_oatof_pre_pulse_time_series_screening_receipt",
            "status": "success",
            "execution_mode": "real_pa_rf_pre_pulse_time_series",
            "pulse_disabled": True,
            "resolution_claim_allowed": False,
            "contract_sha256": file_sha256(paths["contract"]),
            "rf_time_grid": contract["rf_time_grid"],
            "state_row_count": len(state_rows),
            "outputs": {
                "states": {
                    "sha256": file_sha256(paths["states"]),
                    "row_count": len(state_rows),
                }
            },
            "identities": receipt_identities,
        }), encoding="utf-8")
        paths["manifest"].write_text(json.dumps({
            "role": "simulation_run_manifest", "status": "success",
        }), encoding="utf-8")
        return paths

    def _select(self, paths: dict[str, Path]) -> dict[str, object]:
        selector_source = (
            Path(__file__).parents[1] / "analysis" / "select_real_field_pulse_time.py"
        )
        return select_and_write(
            state_table_path=paths["states"],
            screening_contract_path=paths["contract"],
            screening_receipt_path=paths["screening_receipt"],
            resolved_population_path=paths["population"],
            population_table_path=paths["population_table"],
            resolved_source_path=paths["source"],
            resolved_connection_path=paths["connection"],
            screening_manifest_path=paths["manifest"],
            selector_source_path=selector_source,
            geometry_path=paths["geometry"],
            single_flight_configuration_path=paths["configuration"],
            ballistic_schedule_path=paths["schedule"],
            candidate_table_path=paths["table"],
            receipt_path=paths["receipt"],
        )

    def _write_publisher_child(
        self, workspace: Path,
    ) -> tuple[dict[str, Path], Path, Path, dict[str, object]]:
        child = (
            workspace / "artifacts" / "projects" / INTEGRATION_ID
            / "runs" / "20260818_000000__sim__simion__pulse-screen__n3"
        )
        child.mkdir(parents=True)
        paths = self._write_inputs(child)
        states = child / "pre_pulse_time_series_states.csv"
        screening_receipt = child / "pre_pulse_time_series_screening_receipt.json"
        paths["states"].rename(states)
        paths["screening_receipt"].rename(screening_receipt)
        paths["states"] = states
        paths["screening_receipt"] = screening_receipt
        manifest = {
            "inputs": {
                "configuration": _record(paths["configuration"]),
                "resolved_connection": _record(paths["connection"]),
                "resolved_source_contract": _record(paths["source"]),
                "resolved_population_contract": _record(paths["population"]),
                "oatof_resolved_geometry": _record(paths["geometry"]),
                "pulse_schedule": _record(paths["schedule"]),
                "mother_particle_source": _record(paths["population_table"]),
                "pre_pulse_time_series_contract": _record(paths["contract"]),
            },
            "outputs": [_record(states), _record(screening_receipt)],
        }
        paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
        parent = workspace / "parent"
        parent.mkdir()
        stage = {
            "path": child.relative_to(workspace).as_posix(),
            "manifest_sha256": file_sha256(paths["manifest"]),
        }
        return paths, child, parent, stage

    def test_writes_manifest_ready_full_candidates_and_id_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._write_inputs(Path(directory))
            receipt = self._select(paths)
            self.assertEqual(receipt["selected_time_us"], 11.0)
            self.assertEqual(len(receipt["candidates_ranked"]), 3)
            self.assertEqual(
                receipt["candidates_ranked"][0]["population_identity"]["ordered_particle_ids"],
                [1, 2, 3],
            )
            self.assertRegex(
                receipt["candidate_table"]["sha256"], r"^[0-9A-F]{64}$"
            )
            self.assertFalse(receipt["detector_results_used"])
            self.assertEqual(receipt["schema_version"], 2)
            self.assertIn("source_region_bounds", receipt)
            self.assertTrue(paths["receipt"].is_file())

    def test_receipt_publishes_alive_and_missing_sample_census(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._write_inputs(Path(directory), physical_loss=True)
            receipt = self._select(paths)
            sample_two = receipt["sample_census"][1]
            self.assertEqual(sample_two["population_count"], 3)
            self.assertEqual(sample_two["alive"]["ordered_particle_ids"], [1, 2])
            self.assertEqual(sample_two["missing"]["ordered_particle_ids"], [3])
            self.assertRegex(
                sample_two["missing"]["ordered_particle_id_sha256"],
                r"^[0-9A-F]{64}$",
            )

    def test_rejects_any_detector_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._write_inputs(Path(directory), detector_column=True)
            with self.assertRaisesRegex(ContractError, "forbidden columns"):
                self._select(paths)

    def test_rejects_detector_outcome_hidden_in_allowed_status_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._write_inputs(Path(directory))
            text = paths["states"].read_text(encoding="utf-8")
            lines = text.splitlines()
            lines[0] += ",status"
            lines[1:] = [f"{line},detector_crossing" for line in lines[1:]]
            paths["states"].write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "detector outcomes"):
                self._select(paths)

    def test_parent_publisher_runs_selector_from_verified_child_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            paths, _child, parent, stage = self._write_publisher_child(workspace)
            table, receipt_path, receipt = _publish_detector_blind_pulse_selection(
                repo_root=REPO_ROOT,
                workspace_root=workspace,
                parent_run_dir=parent,
                stage=stage,
                resolved_connection_path=paths["connection"],
                resolved_source_path=paths["source"],
                resolved_population_path=paths["population"],
            )
            self.assertTrue(table.is_file())
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(receipt["selected_time_us"], 11.0)
            self.assertFalse(receipt["reusable_verified_pulse"])

    def test_discovery_publisher_emits_manifest_ready_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            paths, child, parent, stage = self._write_publisher_child(workspace)
            parent_run = parent.with_name(
                "20260819_000000__sim__cross__pulse-timing-discovery__n100"
            )
            parent.rename(parent_run)
            _table, receipt_path, receipt = _publish_detector_blind_pulse_selection(
                repo_root=REPO_ROOT,
                workspace_root=workspace,
                parent_run_dir=parent_run,
                stage=stage,
                resolved_connection_path=paths["connection"],
                resolved_source_path=paths["source"],
                resolved_population_path=paths["population"],
            )
            transition_path = _publish_pulse_timing_transition(
                workspace_root=workspace,
                parent_run_dir=parent_run,
                stage=stage,
                candidate_receipt_path=receipt_path,
                candidate_receipt=receipt,
            )
            transition = json.loads(transition_path.read_text(encoding="utf-8"))
            validate_schema(transition, "rf_oatof_pulse_timing_transition.schema.json")
            self.assertEqual(transition["content_key"], receipt["content_key"])
            self.assertEqual(
                transition["screening_child_manifest"]["sha256"],
                file_sha256(child / "run_manifest.json"),
            )

    def test_parent_publisher_rejects_child_parent_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            paths, _child, parent, stage = self._write_publisher_child(workspace)
            other_connection = workspace / "other_connection.json"
            other_connection.write_text('{"role":"different"}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "child and parent identities"):
                _publish_detector_blind_pulse_selection(
                    repo_root=REPO_ROOT,
                    workspace_root=workspace,
                    parent_run_dir=parent,
                    stage=stage,
                    resolved_connection_path=other_connection,
                    resolved_source_path=paths["source"],
                    resolved_population_path=paths["population"],
                )

    def test_confirmed_child_publishes_identical_identity_reuse_receipt(self) -> None:
        workspace = REPO_ROOT.parent
        child = workspace / (
            "artifacts/projects/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runs/20260818_232300__sim__simion__rf-oatof-single-flight-gap3p2__n100"
        )
        manifest = child / "run_manifest.json"
        if not manifest.is_file():
            self.skipTest("canonical pulse confirmation child is not available")
        with tempfile.TemporaryDirectory() as directory:
            for precreate_results in (False, True):
                with self.subTest(precreate_results=precreate_results):
                    parent = Path(directory) / str(precreate_results).lower()
                    parent.mkdir()
                    if precreate_results:
                        (parent / "results").mkdir()
                    result = _publish_verified_pulse_receipt(
                        workspace_root=workspace,
                        parent_run_dir=parent,
                        stage={
                            "path": child.relative_to(workspace).as_posix(),
                            "manifest_sha256": file_sha256(manifest),
                        },
                    )
                    self.assertIsNotNone(result)
                    assert result is not None
                    receipt_path, receipt = result
                    self.assertTrue(receipt_path.is_file())
                    self.assertEqual(
                        receipt["decision"], "PASS_FOR_IDENTICAL_IDENTITY_REUSE"
                    )
                    self.assertEqual(receipt["census"]["detector_crossing"], 69)
                    self.assertTrue(receipt["reusable_verified_pulse"])


if __name__ == "__main__":
    unittest.main()
