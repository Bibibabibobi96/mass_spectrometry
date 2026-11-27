"""Publish a report from explicitly sealed historical COMSOL detector CSV."""
from __future__ import annotations

import csv
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

import matplotlib
import numpy as np
import scipy
import pandas as pd

from msplatform.analysis.peak_metrics import AnalysisSettings
from msplatform.analysis.single_reflection_peak_analysis import analyze_peak_frame
from msplatform.analysis.single_reflection_plotting import plot_single, plot_source_mapping
from msplatform.execution.context import python_runtime_version
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.io.manifest_records import record_path
from msplatform.results.single_reflection_particle_table import read_particle_table
from msplatform.results.historical_comsol_request import load_request

PROJECT = "single_reflection_oa_tof_mass_analyzer"


def publish_historical_comsol_report(manifest_record, *, mode, request_output, events_output,
                                     analysis_contract_input, geometry_input, store,
                                     reserve_bytes: int):
    """Read protected sealed files, publish scientific results, then verify Store cold read.

    The caller supplies an existing ArtifactStore. The named inputs and outputs
    must belong to one successful historical run.
    This routine never opens a saved native model or invokes a solver.
    """
    if mode not in {"design_candidate", "candidate_comsol_postprocess"}:
        raise ValueError("unsupported historical COMSOL producer mode")
    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("reserve_bytes must be a positive integer")
    with guard_historical_run(manifest_record, expected_project=PROJECT, expected_mode=mode) as source:
        return _publish_source(source, manifest_record, request_output=request_output,
            events_output=events_output, analysis_contract_input=analysis_contract_input,
            geometry_input=geometry_input, store=store, reserve_bytes=reserve_bytes)


def _publish_source(source, manifest_record, *, request_output, events_output, analysis_contract_input,
                    geometry_input, store, reserve_bytes, extra_inputs=None, provenance=None):
    request_record = source.output(request_output)
    event_record = source.output(events_output)
    contract_record = source.input(analysis_contract_input)
    geometry_record = source.input(geometry_input)
    request_path = Path(request_record["path"])
    event_path = Path(event_record["path"])
    request = load_request(request_path)
    if Path(request["raw_events_csv"]).resolve() != event_path:
        raise ValueError("analysis request and sealed detector CSV differ")
    with event_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    try:
        ids = [int(row["Ion"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("historical detector IDs are invalid") from error
    if len(ids) != 100 or set(ids) != set(range(1, 101)):
        raise ValueError("historical detector export requires exactly 100 original IDs")
    contract = json.loads(Path(contract_record["path"]).read_text(encoding="utf-8-sig"))
    geometry = json.loads(Path(geometry_record["path"]).read_text(encoding="utf-8-sig"))
    kde = contract["kde"]
    settings = AnalysisSettings(grid_points=int(kde["grid_points"]),
        bandwidth_multiplier=float(kde["bandwidth_multiplier"]),
        mode_threshold_fraction=float(kde["significant_mode_threshold_fraction"]))
    frame, metadata = read_particle_table(event_path,
        float(geometry["coordinate_convention"]["detector_x"]), 0.0, minimum_detected=0)
    if len(frame) < 3:
        metrics, spectra, source_arrays = None, None, None
    else:
        metrics, spectra, source_arrays = analyze_peak_frame(
            frame, float(request["nominal_mass_Da"]), settings, result_schema_version=4)
    run_id, work = store.begin_run()
    with store.run_writer(run_id):
        try:
            with store.reserve(reserve_bytes):
                store.mark_running(run_id)
                inputs = work / "inputs"
                inputs.mkdir()
                for name, record in (("request.json", request_record), ("events.csv", event_record),
                                     ("analysis_contract.json", contract_record), ("geometry.json", geometry_record)):
                    shutil.copyfile(record["path"], inputs / name)
                (inputs / "source_manifest.json").write_bytes(Path(record_path(manifest_record)).read_bytes())
                for name, path in (extra_inputs or {}).items():
                    shutil.copyfile(path, inputs / name)
                if provenance is not None:
                    (inputs / "native_product_provenance.json").write_text(
                        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output = work / "results"
                output.mkdir()
                result = {"schema_version": 4, "status": "PASS" if spectra is not None else "unavailable",
                    "reason": None if spectra is not None else "fewer_than_three_detector_events",
                    "label": request["label"],
                    "analysis_contract_schema_version": int(contract["schema_version"]),
                    "input": {"path": str(event_path), "bytes": event_record["bytes"],
                              "sha256": event_record["sha256"], **metadata},
                    "settings": settings.to_dict(),
                    "runtime": {"python_version": python_runtime_version(), "python_executable": sys.executable,
                                "numpy_version": np.__version__, "scipy_version": scipy.__version__,
                                "pandas_version": pd.__version__, "matplotlib_version": matplotlib.__version__,
                                "analysis_contract": contract_record["path"],
                                "analysis_contract_sha256": contract_record["sha256"]},
                    "metrics": metrics}
                result["detector_observation"] = {
                    "expected_mother_count": None if provenance is None else provenance.get("expected_mother_count"),
                    "raw_cohort_rows": len(rows), "detector_observed_count": len(frame),
                    "unobserved_count": len(rows) - len(frame),
                    "unobserved_semantics": "not confirmed as detector observations; no physical-loss inference",
                    "recorded_status_counts": dict(Counter(row.get("Status", "") for row in rows)),
                }
                if provenance is not None and provenance.get("source_execution_status") in ("success", "failed"):
                    result["source_execution_status"] = provenance["source_execution_status"]
                    result["analysis_scope"] = "historical_detector_observations_only"
                if provenance is not None and "extraction_execution_status" in provenance:
                    result["extraction_execution_status"] = provenance["extraction_execution_status"]
                def convert(value):
                    if isinstance(value, np.generic):
                        return value.item()
                    if isinstance(value, np.ndarray):
                        return value.tolist()
                    raise TypeError(f"Cannot serialize {type(value)!r}")
                (output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2,
                    sort_keys=True, default=convert) + "\n", encoding="utf-8")
                frame.to_csv(output / "particles_normalized.csv", index=False)
                if spectra is not None:
                    pd.DataFrame({"tof_grid_us": spectra["time_grid_us"], "tof_density": spectra["time_density"],
                        "tof_intensity_normalized": spectra["time_density_normalized"],
                        "mass_grid_Da": spectra["mass_grid_Da"], "mass_density": spectra["mass_density"],
                        "mass_intensity_normalized": spectra["mass_density_normalized"]}).to_csv(output / "spectra.csv", index=False)
                    plot_single(frame, metrics, spectra, request["label"], output / "peak_overview.png", result_schema_version=4)
                if source_arrays is not None:
                    pd.DataFrame({"initial_z_bin_center_mm": source_arrays["z_bin_center_mm"],
                        "particle_count": source_arrays["z_bin_particle_count"],
                        "mean_tof_us": source_arrays["z_bin_mean_tof_us"],
                        "std_tof_ns": source_arrays["z_bin_std_tof_ns"]}).to_csv(
                            output / "source_mapping_bins.csv", index=False)
                    plot_source_mapping(frame, source_arrays, metrics["source_mapping"], output / "initial_z_tof_mapping.png")
                store.publish_run(work, run_id=run_id)
        except Exception as error:
            status = store.run_status(run_id)["execution_status"]
            if status == "queued":
                store.set_queued_reason(run_id, str(error))
            elif status == "running":
                store.finish_run(run_id, "failed", reason=str(error))
            raise

    return run_id, store.inspect_run(run_id)


def publish_extracted_comsol_report(reference, *, store, reserve_bytes: int):
    """Publish a report from a guarded Store-native historical detector export."""
    from msplatform.execution.native_source_guard import guard_native_source
    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("reserve_bytes must be a positive integer")
    with guard_native_source(reference, expected_kind="historical_detector_export",
                             expected_artifact_root=store.root, artifact_store=store) as artifact:
        if (artifact.metadata.get("scope") != "saved_solution_read_only"
                or artifact.metadata.get("native_particle_solve_count") != 0
                or artifact.metadata.get("native_field_solve_count") != 0
                or set(artifact.data_records) != {"events", "request", "report", "geometry", "analysis_contract", "saved_context"}):
            raise ValueError("historical detector export product differs")
        report = json.loads(artifact.data_path("report").read_text(encoding="utf-8-sig"))
        if (report.get("candidate_model_validation") != "passed"
                or any(type(report.get(name)) is not int or report[name] != 100 for name in ("nP", "nDet"))
                or report.get("parent_model_saved") is not False
                or any(type(report.get(name)) is not int or report[name] != 0
                       for name in ("native_particle_solve_count", "native_field_solve_count"))
                or Path(str(report.get("model_path", ""))).resolve() != Path(artifact.metadata["source_model"]["path"]).resolve()
                or Path(str(report.get("raw_detector_events_path", ""))).resolve() != artifact.data_path("events")
                or Path(str(report.get("analysis_request_path", ""))).resolve() != artifact.data_path("request")):
            raise ValueError("historical detector export report differs")
        context = json.loads(artifact.data_path("saved_context").read_text(encoding="utf-8-sig"))
        if (context.get("schema_version") != 1 or context.get("role") != "oatof_saved_particle_solution"
                or type(context.get("particle_count")) is not int or context["particle_count"] != 100):
            raise ValueError("saved detector context does not establish the original cohort")
        class Source:
            def output(self, name):
                return dict(artifact.data_records[name], path=str(artifact.data_path(name)))
            def input(self, name):
                return dict(artifact.data_records[name], path=str(artifact.data_path(name)))
        return _publish_source(Source(), reference["manifest"], request_output="request",
            events_output="events", analysis_contract_input="analysis_contract",
            geometry_input="geometry", store=store, reserve_bytes=reserve_bytes,
            extra_inputs={"native_validation_report.json": artifact.data_path("report"),
                          "original_saved_context.json": artifact.data_path("saved_context")},
            provenance={"reference": reference, "metadata": artifact.metadata,
                        "source_execution_status": artifact.metadata["source_execution_status"],
                        "extraction_execution_status": "succeeded", "expected_mother_count": context["particle_count"]})


def publish_failed_extracted_comsol_report(manifest_record, *, events_record, request_record, store, reserve_bytes: int):
    """Analyze a sealed stopped failed cold export without upgrading its producer status."""
    from msplatform.execution.native_source_guard import guard_stopped_store_evidence
    from msplatform.io.manifest_records import validate_file_record
    from msplatform.results.historical_comsol_request import validate_detector_cohort

    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("reserve_bytes must be a positive integer")
    with guard_stopped_store_evidence(store, manifest_record) as (manifest, hold):
        if (manifest.get("status") != "failed" or manifest.get("project") != PROJECT
                or manifest.get("mode") != "saved_detector_extraction"):
            raise ValueError("failed detector evidence is not a failed cold extraction")
        hold([events_record, request_record])
        launchers = [row for row in manifest["outputs"] if Path(row["path"]).name == "cold_extraction.launcher.json"]
        if len(launchers) != 1:
            raise ValueError("failed cold launcher completion is missing or ambiguous")
        hold(launchers)
        from msplatform.backends.comsol.historical_detector_extraction import validate_stopped_cold_launcher
        validate_stopped_cold_launcher(record_path(launchers[0]), manifest["run_id"])
        events = record_path(events_record)
        request_path = record_path(request_record)
        validate_detector_cohort(events, request_path)
        inputs = manifest.get("inputs", {})
        required = ("execution_request", "source_manifest", "source_model", "saved_context",
                    "geometry", "analysis_contract")
        if any(name not in inputs for name in required):
            raise ValueError("failed cold extraction source identity is incomplete")
        saved_context = json.loads(record_path(inputs["saved_context"]).read_text(encoding="utf-8-sig"))
        if (saved_context.get("schema_version") != 1 or saved_context.get("role") != "oatof_saved_particle_solution"
                or type(saved_context.get("particle_count")) is not int or saved_context["particle_count"] != 100):
            raise ValueError("failed cold source does not establish the original cohort")
        execution_record = validate_file_record(inputs["execution_request"], "cold execution request")
        execution = json.loads(record_path(execution_record).read_text(encoding="utf-8-sig"))
        package = execution.get("package", {})
        if (execution.get("schema_version") != 1 or execution.get("role") != "run_artifact_workflow_request"
                or package.get("project") != PROJECT or package.get("mode") != "saved_detector_extraction"
                or package.get("run_id") != manifest.get("run_id")
                or execution.get("payload", {}).get("action") != "reextract_oatof_saved_solution"
                or execution.get("expected_operation_ids") != ["reextract_saved_detector"]):
            raise ValueError("failed cold execution request differs")
        entrypoint = execution.get("prepared", {}).get("entrypoint")
        original = execution.get("prepared", {}).get("source_entrypoint")
        entrypoint = validate_file_record(entrypoint, "frozen cold action")
        original = validate_file_record(original, "original cold action")
        if (Path(original["path"]).name != "historical_detector_extraction.py"
                or entrypoint["bytes"] != original["bytes"]
                or entrypoint["sha256"].lower() != original["sha256"].lower()):
            raise ValueError("failed cold action source identity differs")
        # The stopped-stage guard holds all local manifest-bound inputs; explicitly
        # require the frozen action itself to be a member rather than an arbitrary path.
        hold([entrypoint])
        completions = [row for row in manifest["outputs"] if Path(row["path"]).name == "execution_completion.json"]
        if len(completions) != 1:
            raise ValueError("failed cold completion is missing or ambiguous")
        hold(completions)
        completion = json.loads(record_path(completions[0]).read_text(encoding="utf-8-sig"))
        if completion.get("status") != "failed" or not completion.get("exception"):
            raise ValueError("failed cold completion does not retain its error")
        class Source:
            def output(self, name):
                return {"events": events_record, "request": request_record}[name]
            def input(self, name):
                return inputs[name]
        return _publish_source(Source(), manifest_record, request_output="request", events_output="events",
            analysis_contract_input="analysis_contract", geometry_input="geometry", store=store,
            reserve_bytes=reserve_bytes, extra_inputs={"failed_execution_completion.json": record_path(completions[0]),
                                                       "cold_launcher_completion.json": record_path(launchers[0])},
            provenance={"source_execution_status": "failed", "source_manifest": manifest_record,
                        "expected_mother_count": saved_context["particle_count"],
                        "source_model": inputs["source_model"], "failure": completion["exception"]})


def publish_failed_historical_comsol_report(child_manifest, producer_manifest, *, events_output, request_output,
                                            analysis_contract_input, geometry_input, store, reserve_bytes: int):
    """Analyze a stopped failed historical child and its exact original science owner."""
    from msplatform.execution.native_source_guard import guard_oa_failed_historical_run
    from msplatform.io.manifest_records import validate_file_record
    from msplatform.results.historical_comsol_request import validate_detector_cohort

    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("reserve_bytes must be a positive integer")
    expected = validate_file_record(producer_manifest, "original producer manifest")
    with guard_oa_failed_historical_run(child_manifest) as child:
        if child.manifest.get("mode") == "design_candidate":
            actual = validate_file_record(child_manifest, "failed original producer manifest")
            if (record_path(actual) != record_path(expected) or actual["bytes"] != expected["bytes"]
                    or actual["sha256"].lower() != expected["sha256"].lower()):
                raise ValueError("direct historical CSV requires its own producer manifest")
            direct_events = child.output(events_output)
            direct_request = child.output(request_output)
            validate_detector_cohort(Path(direct_events["path"]), Path(direct_request["path"]))
            completion_record = child.output("results/execution_completion.json")
            completion = json.loads(Path(completion_record["path"]).read_text(encoding="utf-8-sig"))
            return _publish_source(child, child_manifest, request_output=request_output, events_output=events_output,
                analysis_contract_input=analysis_contract_input, geometry_input=geometry_input,
                store=store, reserve_bytes=reserve_bytes,
                extra_inputs={"failed_execution_completion.json": Path(completion_record["path"])},
                provenance={"source_execution_status": "failed", "source_manifest": child_manifest,
                            "failure": completion.get("exception")})
        if child.manifest.get("mode") != "candidate_comsol_postprocess":
            raise ValueError("historical CSV must be from its stopped postprocess child")
        selection_record = child.input("postprocess_source_selection")
        selection = json.loads(Path(selection_record["path"]).read_text(encoding="utf-8-sig"))
        def same_manifest(value):
            identity = validate_file_record(value, "selected original producer manifest")
            return (record_path(identity) == record_path(expected) and identity["bytes"] == expected["bytes"]
                    and identity["sha256"].lower() == expected["sha256"].lower())
        if not same_manifest(selection.get("manifest_record")):
            raise ValueError("historical child does not bind the explicit original producer")
        for name in ("science_reference", "source_reference", "export_source_reference"):
            reference = selection.get(name)
            if not isinstance(reference, dict) or not same_manifest(reference.get("manifest_record")):
                raise ValueError("historical child source references disagree")
        events_record = child.output(events_output)
        request_record = child.output(request_output)
        validate_detector_cohort(Path(events_record["path"]), Path(request_record["path"]))
        completion_record = child.output("results/execution_completion.json")
        completion = json.loads(Path(completion_record["path"]).read_text(encoding="utf-8-sig"))
        with guard_oa_failed_historical_run(producer_manifest) as producer:
            if producer.manifest.get("mode") != "design_candidate":
                raise ValueError("historical science owner is not its original design producer")
            selected_geometry = validate_file_record(selection.get("inputs", {}).get("contract_path"),
                                                     "selected historical geometry")
            original_geometry = producer.input(geometry_input)
            if (record_path(selected_geometry) != record_path(original_geometry)
                    or selected_geometry["bytes"] != original_geometry["bytes"]
                    or selected_geometry["sha256"].lower() != original_geometry["sha256"].lower()):
                raise ValueError("historical child geometry differs from its producer")
            context_count = None
            extra_context = {}
            if selection.get("context_record") is not None:
                selected_context = validate_file_record(selection["context_record"], "selected saved context")
                context_path = record_path(selected_context)
                if not context_path.is_relative_to(producer.root):
                    raise ValueError("historical saved context escapes its producer")
                original_context = producer.output(context_path.relative_to(producer.root).as_posix())
                if (record_path(selected_context) != record_path(original_context)
                        or selected_context["bytes"] != original_context["bytes"]
                        or selected_context["sha256"].lower() != original_context["sha256"].lower()):
                    raise ValueError("historical child saved context differs from its producer")
                context = json.loads(Path(original_context["path"]).read_text(encoding="utf-8-sig"))
                if (context.get("schema_version") != 1 or context.get("role") != "oatof_saved_particle_solution"
                        or type(context.get("particle_count")) is not int or context["particle_count"] != 100):
                    raise ValueError("historical saved context does not establish the original cohort")
                context_count = context["particle_count"]
                extra_context["original_saved_context.json"] = Path(original_context["path"])
            class Source:
                def output(self, name):
                    return {"events": events_record, "request": request_record}[name]
                def input(self, name):
                    return producer.input(name)
            return _publish_source(Source(), child_manifest, request_output="request", events_output="events",
                analysis_contract_input=analysis_contract_input, geometry_input=geometry_input,
                store=store, reserve_bytes=reserve_bytes,
                extra_inputs={"postprocess_source_selection.json": Path(selection_record["path"]),
                              "original_producer_manifest.json": record_path(producer_manifest),
                              "failed_execution_completion.json": Path(completion_record["path"]),
                              **extra_context},
                provenance={"source_execution_status": "failed", "source_manifest": child_manifest,
                            "expected_mother_count": context_count,
                            "original_producer_manifest": producer_manifest, "source_model": selection.get("model_record"),
                            "failure": completion.get("exception")})
