"""Pure inert boundary of the historical COMSOL cold-export action."""
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.comsol.historical_detector_extraction import (
    _extract_action, _validate_legacy_save_completion, extract_historical_detector, validate_stopped_cold_launcher,
)
from msplatform.io.manifest_records import file_record
from msplatform.results.historical_comsol_request import validate_detector_cohort


class ColdActionTests(unittest.TestCase):
    def test_read_only_output_and_rejected_solve(self):
        for solve_count in (0, 1, False):
            with self.subTest(solve_count=solve_count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source"
                source.mkdir()
                model = source / "model.mph"
                model.write_bytes(b"INERT_MODEL_NOT_COMSOL")
                context = source / "context.json"
                context.write_text("{}", encoding="utf-8")
                geometry = source / "geometry.json"
                geometry.write_text("{}", encoding="utf-8")
                contract = source / "analysis.json"
                contract.write_text("{}", encoding="utf-8")
                manifest = source / "run_manifest.json"
                manifest.write_text("{}", encoding="utf-8")
                run = root / "run"
                inp, result, logs = (run / name for name in ("inputs", "results", "logs"))
                for path in (inp, result, logs):
                    path.mkdir(parents=True)
                launcher = inp / "native_sources/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1"
                launcher.parent.mkdir(parents=True)
                launcher.write_text("", encoding="utf-8")
                class Session:
                    run_dir, input_dir, result_dir, log_dir = run, inp, result, logs
                    run_id = "fixture"
                    context = SimpleNamespace(workspace=root, python_executable=Path("python"), host_state_path=root / "host",
                        policy_path=root / "policy", powershell_executable=Path("powershell"),
                        tools={"comsol_launcher": "comsol", "matlab_root": "matlab"})
                    def declare_file(self, path, role):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        return path
                    def add_input(self, name, record):
                        pass
                    def run_process(self, *args, **kwargs):
                        events = result / "comsol_detector_events_test.csv"
                        request = result / "comsol_detector_events_test.analysis_request.json"
                        events.write_text("Ion,TofUs\n" + "".join(f"{i},70\n" for i in range(1,101)), encoding="utf-8")
                        request.write_text(json.dumps(dict(schema_version=1, role="oatof_comsol_detector_events_analysis_request",
                            solver="COMSOL", label="test", nominal_mass_Da=524, raw_events_csv=str(events),
                            analysis_output_dir=str(result / "analysis"), event_extraction={},
                            aggregate_metrics_owner="python_reference_analysis")), encoding="utf-8")
                        (result / "ms_oaTOF_ringstack_reflectron_test.png").write_bytes(b"inert")
                        (result / "cold_extraction.json").write_text(json.dumps(dict(native_particle_solve_count=solve_count,
                            native_field_solve_count=0, parent_model_saved=False, candidate_model_validation="passed",
                            nP=100, nDet=100, model_path=str(model), raw_detector_events_path=str(events),
                            analysis_request_path=str(request))), encoding="utf-8")
                        (logs / "cold_extraction.bootstrap.log").write_text("STATUS=PASS", encoding="utf-8")
                arguments = dict(model=file_record(model), saved_context=file_record(context), geometry=file_record(geometry),
                    analysis_contract=file_record(contract), manifest_record=file_record(manifest),
                    source_root=source, source_status="success", label="test", limits={})
                with (patch("msplatform.backends.comsol.historical_detector_extraction.freeze_native_sources", return_value=(launcher, [])),
                      patch("msplatform.backends.comsol.historical_detector_extraction.require_launcher_completion"),
                      patch("msplatform.backends.comsol.historical_detector_extraction.declare_runtime_files")):
                    if solve_count or type(solve_count) is bool:
                        with self.assertRaisesRegex(ValueError, "evidence differs"):
                            _extract_action(Session(), **arguments)
                    else:
                        value = _extract_action(Session(), **arguments)
                        self.assertEqual(value["summary"]["solve_calls"], 0)
                        self.assertEqual(value["manifest_extra_fields"]["products"]["detector_export"]["kind"],
                                         "historical_detector_export")

    def test_stopped_launcher_requires_actual_exit_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "launcher.json"
            receipt = dict(schema_version=1, role="comsol_launcher_completion", run_id="fixture",
                operations=[dict(operation_id="attempt", observation=dict(exit_confirmed=True, returncode=7,
                    process_id=111, process_started_at_utc_ticks=222))],
                host_release=dict(inherited=False, token="fixture-token",
                    result=dict(status="released", token="fixture-token"), error=None))
            path.write_text(json.dumps(receipt), encoding="utf-8")
            validate_stopped_cold_launcher(path, "fixture")
            receipt["operations"][0]["observation"]["exit_confirmed"] = False
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_stopped_cold_launcher(path, "fixture")
            receipt["operations"][0]["observation"]["exit_confirmed"] = True
            receipt["host_release"]["error"] = "unknown"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_stopped_cold_launcher(path, "fixture")

    def test_failed_detector_cohort_is_evidence_not_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / "events.csv"
            names = ["Ion", "TofUs", "XMm", "YMm", "Hit", "Status", "Event", "DetectorRadiusMm", "X0Mm", "Y0Mm", "Z0Mm"]
            with events.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=names)
                writer.writeheader()
                for index in range(1,101):
                    writer.writerow(dict.fromkeys(names, "") | {"Ion": index, "Hit": index < 74})
            request = root / "request.json"
            document = dict(schema_version=1, role="oatof_comsol_detector_events_analysis_request",
                solver="COMSOL", label="partial", nominal_mass_Da=524, raw_events_csv=str(events),
                analysis_output_dir=str(root / "analysis"), event_extraction={},
                aggregate_metrics_owner="python_reference_analysis")
            request.write_text(json.dumps(document), encoding="utf-8")
            validate_detector_cohort(events, request)
            document["raw_events_csv"] = str(root / "other.csv")
            request.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not bind"):
                validate_detector_cohort(events, request)
            document["raw_events_csv"] = str(events)
            request.write_text(json.dumps(document), encoding="utf-8")
            lines = events.read_text(encoding="utf-8").splitlines()
            events.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cohort is incomplete"):
                validate_detector_cohort(events, request)

    def test_boolean_model_size_is_rejected_before_owner(self):
        from contextlib import contextmanager
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.mph"
            model.write_bytes(b"x")
            saved = root / "saved.json"
            saved.write_text(json.dumps(dict(schema_version=1, role="oatof_saved_particle_solution",
                particle_count=100, solution_tag="sol2", dataset_tag="pdset1", saved_model_bytes=True,
                model_save_state="raw_complete", label="test")), encoding="utf-8")
            class Source:
                manifest = {"mode": "design_candidate"}
                def output(self, name):
                    return file_record(model if name == "model" else saved)
                def input(self, name):
                    return file_record(saved)
            @contextmanager
            def guard(*args, **kwargs):
                yield Source()
            with (patch("msplatform.backends.comsol.historical_detector_extraction.read_stage_policy",
                        return_value=({}, {})),
                  patch("msplatform.backends.comsol.historical_detector_extraction.guard_historical_run", guard),
                  patch("msplatform.backends.comsol.historical_detector_extraction.run_managed_stage") as owner):
                with self.assertRaisesRegex(ValueError, "not explicitly complete"):
                    extract_historical_detector({}, model_output="model", context_output="context",
                        geometry_input="geometry", analysis_contract_input="analysis", context=None, store=None)
                owner.assert_not_called()

    def test_detector_product_requires_exact_metadata_and_data(self):
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.results.artifacts import open_artifact
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = {}
            for name in ("events", "request", "report", "geometry", "analysis_contract", "saved_context"):
                path = root / (name + ".json")
                path.write_text("{}", encoding="utf-8")
                data[name] = file_record(path)
            source = file_record(root / "events.json")
            metadata = dict(backend="comsol", scope="saved_solution_read_only",
                native_particle_solve_count=0, native_field_solve_count=0,
                source_manifest=source, source_model=source, source_execution_status="success")
            product = dict(schema_version=1, kind="historical_detector_export", status="complete",
                           metadata=metadata, data=data)
            manifest = dict(schema_version=2, role="simulation_run_manifest", run_id="fixture",
                project="single_reflection_oa_tof_mass_analyzer", mode="saved_detector_extraction",
                status="success", inputs={"source_manifest": source, "source_model": source},
                outputs=list(data.values()), products={"detector_export": product})
            publish_terminal_state(root, {"status": "success"}, manifest)
            path = root / "run_manifest.json"
            reference = {"manifest": file_record(path), "product_id": "detector_export"}
            self.assertEqual(open_artifact(reference, expected_kind="historical_detector_export").kind,
                             "historical_detector_export")
            metadata["native_particle_solve_count"] = 1
            path.write_text(json.dumps(manifest), encoding="utf-8")
            reference["manifest"] = file_record(path)
            with self.assertRaisesRegex(ValueError, "metadata or data"):
                open_artifact(reference, expected_kind="historical_detector_export")
            metadata["native_particle_solve_count"] = 0
            manifest["status"] = "failed"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            reference["manifest"] = file_record(path)
            with self.assertRaisesRegex(ValueError, "metadata or data"):
                open_artifact(reference, expected_kind="historical_detector_export")

    def test_legacy_save_requires_bound_stopped_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {}
            for relative, contents in (("logs/comsol_build.txt", "STATUS=PASS\n"),
                                       ("logs/comsol_build_completion.json", "{}"),
                                       ("inputs/request.json", "{}")):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
                paths[relative] = file_record(path)
            request_path = root / "inputs/request.json"
            request_path.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_request",
                package=dict(run_id=root.name, project="single_reflection_oa_tof_mass_analyzer", mode="design_candidate"))), encoding="utf-8")
            paths["inputs/request.json"] = file_record(request_path)
            completion_path = root / "execution_completion.json"
            completion = dict(schema_version=1, role="run_artifact_workflow_completion", run_id=root.name,
                project="single_reflection_oa_tof_mass_analyzer", status="success",
                run_config={"sha256": "abc"}, execution_request=paths["inputs/request.json"],
                writer_completion={"operations": [{"operation_id": "x", "observation": {"returncode": 0, "exit_confirmed": True}}],
                                   "resource_releases": []})
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            paths["execution_completion.json"] = file_record(completion_path)
            class Source:
                manifest = {"status": "success", "mode": "design_candidate", "run_config": {"sha256": "abc"},
                            "outputs": [paths["execution_completion.json"]]}
                def __init__(self):
                    self.root = root
                def output(self, name):
                    return paths[name]
                def input(self, name):
                    return paths["inputs/request.json"]
            def append(writer, *args, **kwargs):
                writer["operations"].append({"operation_id": "x", "observation": {"returncode": 0, "exit_confirmed": True}})
            with (patch("msplatform.backends.simion.native_stage_completion.append_native_stage_completion", side_effect=append),
                  patch("msplatform.execution.owner.validate_writer_completion")):
                _validate_legacy_save_completion(Source())
                completion["execution_request"] = dict(completion["execution_request"], sha256="0" * 64)
                completion_path.write_text(json.dumps(completion), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "request identity"):
                    _validate_legacy_save_completion(Source())


if __name__ == "__main__":
    unittest.main()
