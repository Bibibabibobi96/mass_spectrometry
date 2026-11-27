"""Controlled historical COMSOL CSV source and actual Store publication."""
import json
import os
from pathlib import Path
import tempfile
import sys
from unittest.mock import patch
import unittest

from msplatform.backends.simion.native_completion import retention_api
from msplatform.execution.manifest_publication import publish_run_manifest
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.historical_comsol_detector import (
    publish_failed_historical_comsol_report, publish_historical_comsol_report,
)
from tests.contracts.test_support.historical_mass_fixture import PROJECT


class HistoricalComsolReportTests(unittest.TestCase):
    def make_source(self, root):
        source = root / "20261101_100000__sim__comsol__fixture"
        (source / "inputs").mkdir(parents=True)
        (source / "results").mkdir()
        geometry = source / "inputs/geometry.json"
        contract = source / "inputs/analysis.json"
        geometry.write_bytes((PROJECT / "config/resolved_geometry.json").read_bytes())
        contract.write_bytes((PROJECT / "config/analysis_contract.json").read_bytes())
        events = source / "results/events.csv"
        events.write_text("Ion,TofUs\n" + "".join(f"{i},{70 + i * 0.00001}\n" for i in range(1,101)), encoding="utf-8")
        request = source / "results/request.json"
        request.write_text(json.dumps(dict(schema_version=1, role="oatof_comsol_detector_events_analysis_request",
            solver="COMSOL", label="sealed fixture", nominal_mass_Da=524, raw_events_csv=str(events),
            analysis_output_dir=str(source / "results/old"), event_extraction={},
            aggregate_metrics_owner="python_reference_analysis")), encoding="utf-8")
        config = dict(schema_version=2, role="fixture", run_id=source.name,
            project="single_reflection_oa_tof_mass_analyzer", mode="design_candidate",
            inputs=dict(geometry=str(geometry), analysis_contract=str(contract)),
            artifact_retention=dict(policy_version=1, **{"class":"compact"}, reason=None))
        (source / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        publish_run_manifest(source / "run_config.json", "success", output_paths=[request, events], retention_api=retention_api)
        return source

    def test_retired_candidate_postprocess_cli_is_not_available(self):
        from msplatform.workflows.oa_candidate.run_candidate import main
        with patch.object(sys, "argv", ["run_candidate", "--postprocess-from", "old", "--run-id", "new"]):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)

    def test_published_report_and_source_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_source(root)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000,
                                  low_water_bytes=80_000_000, safety_bytes=0)
            kwargs = dict(mode="design_candidate", request_output="results/request.json",
                events_output="results/events.csv", analysis_contract_input="analysis_contract",
                geometry_input="geometry", store=store, reserve_bytes=20_000_000)
            run, published = publish_historical_comsol_report(file_record(source / "run_manifest.json"), **kwargs)
            self.assertEqual(published, store.inspect_run(run))
            metrics = json.loads((published / "results/metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["metrics"]["particles"], 100)
            self.assertTrue((published / "results/peak_overview.png").is_file())
            from msplatform.workflows.oa_candidate.reference_analysis_core import analyze_single
            original = analyze_single(source / "results/events.csv", root / "baseline", 524,
                                      label="sealed fixture", result_schema_version=4)
            self.assertEqual(metrics["metrics"], original["metrics"])
            self.assertEqual(metrics["input"], original["input"])
            self.assertEqual(metrics["runtime"]["analysis_contract_sha256"],
                             original["runtime"]["analysis_contract_sha256"])
            self.assertEqual(metrics["runtime"]["numpy_version"], original["runtime"]["numpy_version"])
            self.assertEqual((published / "results/spectra.csv").read_bytes(),
                             (root / "baseline/spectra.csv").read_bytes())
            (source / "results/events.csv").write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                publish_historical_comsol_report(file_record(source / "run_manifest.json"), **kwargs)

    @unittest.skipUnless(os.name == "nt", "Windows file identity guard")
    def test_source_remains_protected_during_report(self):
        from msplatform.analysis.single_reflection_plotting import plot_single
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_source(root)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            def checked_plot(*args, **kwargs):
                with self.assertRaises(PermissionError):
                    (source / "results/events.csv").write_text("changed", encoding="utf-8")
                return plot_single(*args, **kwargs)
            with patch("msplatform.workflows.historical_comsol_detector.plot_single", side_effect=checked_plot):
                publish_historical_comsol_report(file_record(source / "run_manifest.json"), mode="design_candidate",
                    request_output="results/request.json", events_output="results/events.csv",
                    analysis_contract_input="analysis_contract", geometry_input="geometry",
                    store=store, reserve_bytes=20_000_000)

    def test_fewer_than_three_detected_rows_publish_unavailable_not_failure(self):
        from msplatform.results.single_reflection_particle_table import read_particle_table
        for hit_count in (0, 1, 2):
            with self.subTest(hit_count=hit_count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.make_source(root)
                events = source / "results/events.csv"
                events.write_text("Ion,TofUs,Hit,Status\n" + "".join(
                    f"{i},{70+i*.001},{1 if i <= hit_count else 0},{'detector_hit' if i <= hit_count else 'unknown'}\n"
                    for i in range(1, 101)), encoding="utf-8")
                (source / "run_manifest.json").unlink()
                publish_run_manifest(source / "run_config.json", "success",
                    output_paths=[source / "results/request.json", events], retention_api=retention_api)
                with self.assertRaisesRegex(ValueError, "Fewer than three"):
                    read_particle_table(events, 0.0, 0.0)
                store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
                run, path = publish_historical_comsol_report(file_record(source / "run_manifest.json"),
                    mode="design_candidate", request_output="results/request.json", events_output="results/events.csv",
                    analysis_contract_input="analysis_contract", geometry_input="geometry", store=store, reserve_bytes=20_000_000)
                result = json.loads((store.inspect_run(run) / "results/metrics.json").read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["reason"], "fewer_than_three_detector_events")
                self.assertIsNone(result["metrics"])
                self.assertEqual(result["detector_observation"]["detector_observed_count"], hit_count)
                self.assertEqual(result["detector_observation"]["unobserved_count"], 100 - hit_count)
                self.assertEqual((path / "inputs/events.csv").read_bytes(), events.read_bytes())
                self.assertFalse((path / "results/peak_overview.png").exists())

    def test_failed_original_csv_is_available_without_inventing_mother_count(self):
        from tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_candidate_workflow import postprocess_source_fixture
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, source, config_path, outputs = postprocess_source_fixture(root)
            contract = source / "inputs/analysis_contract.json"
            contract.write_bytes((PROJECT / "config/analysis_contract.json").read_bytes())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["inputs"]["analysis_contract"] = str(contract)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            from msplatform.backends.simion.native_stage_completion import append_native_stage_completion
            native = source / "logs/comsol_build_completion.json"
            native_document = json.loads(native.read_text(encoding="utf-8"))
            native_document["operations"][0]["observation"].update(process_id=111, process_started_at_utc_ticks=222)
            native.write_text(json.dumps(native_document), encoding="utf-8")
            writer = {"operations": [], "resource_releases": []}
            append_native_stage_completion(writer, native, role="comsol_launcher_completion", run_id=source.name)
            completion = source / "results/execution_completion.json"
            document = json.loads(completion.read_text(encoding="utf-8"))
            document["writer_completion"] = writer
            document["run_config"] = file_record(config_path)
            completion.write_text(json.dumps(document), encoding="utf-8")
            (source / "run_manifest.json").unlink()
            publish_run_manifest(config_path, "failed", output_paths=outputs, retention_api=retention_api)
            manifest = file_record(source / "run_manifest.json")
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000,
                                  low_water_bytes=80_000_000, safety_bytes=0)
            run, path = publish_failed_historical_comsol_report(manifest, manifest,
                events_output="results/comsol_detector_events_Fixture.csv",
                request_output="results/comsol_detector_events_Fixture.analysis_request.json",
                analysis_contract_input="analysis_contract", geometry_input="candidate_resolved_geometry.json",
                store=store, reserve_bytes=20_000_000)
            result = json.loads((store.inspect_run(run) / "results/metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(result["source_execution_status"], "failed")
            self.assertIsNone(result["detector_observation"]["expected_mother_count"])
            self.assertEqual(result["detector_observation"]["raw_cohort_rows"], 100)
            self.assertEqual(path, store.inspect_run(run))

    def test_failed_csv_child_without_model_context_does_not_invent_mother_count(self):
        from msplatform.backends.simion.native_stage_completion import append_native_stage_completion
        from tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_candidate_workflow import cold_export_failed_child_fixture
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, producer, child, events = cold_export_failed_child_fixture(root)
            def update_native_and_completion(run, native_name, config, output_paths):
                native = run / "logs" / native_name
                native_doc = json.loads(native.read_text(encoding="utf-8"))
                native_doc["operations"][0]["observation"].update(process_id=111, process_started_at_utc_ticks=222)
                native.write_text(json.dumps(native_doc), encoding="utf-8")
                writer = {"operations": [], "resource_releases": []}
                append_native_stage_completion(writer, native, role="comsol_launcher_completion", run_id=run.name)
                config_path = run / "run_config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                completion = run / "results/execution_completion.json"
                complete = json.loads(completion.read_text(encoding="utf-8"))
                complete["run_config"] = file_record(config_path)
                complete["writer_completion"] = writer
                completion.write_text(json.dumps(complete), encoding="utf-8")
                (run / "run_manifest.json").unlink()
                publish_run_manifest(config_path, "failed", output_paths=output_paths, retention_api=retention_api)
                return file_record(run / "run_manifest.json")
            producer_config = json.loads((producer / "run_config.json").read_text(encoding="utf-8"))
            contract = producer / "inputs/analysis_contract.json"
            contract.write_bytes((PROJECT / "config/analysis_contract.json").read_bytes())
            producer_config["inputs"]["analysis_contract"] = str(contract)
            producer_manifest = update_native_and_completion(producer, "comsol_build_completion.json", producer_config,
                [producer / "results/comsol_detector_events_Fixture.csv",
                 producer / "results/comsol_detector_events_Fixture.analysis_request.json",
                 producer / "logs/comsol_build_completion.json", producer / "results/execution_completion.json"])
            selection_path = child / "inputs/postprocess_source_selection.json"
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertIsNone(selection["context_record"])
            selection["manifest_record"] = producer_manifest
            for key in ("source_reference", "science_reference", "export_source_reference"):
                selection[key] = {"manifest_record": producer_manifest}
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            child_config = json.loads((child / "run_config.json").read_text(encoding="utf-8"))
            child_config["provenance"]["science_reference"] = {"manifest_record": producer_manifest}
            request = child / "results/comsol_detector_events_Fixture.analysis_request.json"
            child_manifest = update_native_and_completion(child, "cold_postprocess_completion.json", child_config,
                [events, request, child / "logs/cold_postprocess_completion.json", child / "results/execution_completion.json"])
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            run, path = publish_failed_historical_comsol_report(child_manifest, producer_manifest,
                events_output="results/comsol_detector_events_Fixture.csv",
                request_output="results/comsol_detector_events_Fixture.analysis_request.json",
                analysis_contract_input="analysis_contract", geometry_input="candidate_resolved_geometry.json",
                store=store, reserve_bytes=20_000_000)
            result = json.loads((store.inspect_run(run) / "results/metrics.json").read_text(encoding="utf-8"))
            self.assertIsNone(result["detector_observation"]["expected_mother_count"])
            self.assertEqual(result["detector_observation"]["raw_cohort_rows"], 100)
            self.assertFalse((path / "inputs/original_saved_context.json").exists())

    def test_incomplete_population_and_mismatched_request_refused(self):
        for case in ("incomplete", "wrong_request"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self.make_source(root)
                (source / "run_manifest.json").unlink()
                events = source / "results/events.csv"
                request = source / "results/request.json"
                if case == "incomplete":
                    events.write_text("Ion,TofUs\n1,70\n", encoding="utf-8")
                else:
                    data = json.loads(request.read_text(encoding="utf-8"))
                    data["raw_events_csv"] = str(source / "results/other.csv")
                    request.write_text(json.dumps(data), encoding="utf-8")
                publish_run_manifest(source / "run_config.json", "success", output_paths=[request, events], retention_api=retention_api)
                store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
                with self.assertRaises(ValueError):
                    publish_historical_comsol_report(file_record(source / "run_manifest.json"), mode="design_candidate",
                        request_output="results/request.json", events_output="results/events.csv",
                        analysis_contract_input="analysis_contract", geometry_input="geometry",
                        store=store, reserve_bytes=20_000_000)


if __name__ == "__main__":
    unittest.main()
