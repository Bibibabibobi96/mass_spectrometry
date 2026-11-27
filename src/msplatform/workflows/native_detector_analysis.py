"""Analyze an existing COMSOL trajectory product using its verified native detector events."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from msplatform.analysis.native_detector_peak import analyze_native_detector_peak
from msplatform.analysis.peak_metrics import AnalysisSettings
from msplatform.analysis.single_reflection_plotting import plot_single
from msplatform.backends.comsol.detector_facts import validate_comsol_particle_facts
from msplatform.execution.native_source_guard import guard_native_source
from msplatform.results.particle_data import read_particle_data


def publish_native_detector_peak(reference, *, source_artifact_root: Path, store, species_id: str,
                                 surface_id: str, nominal_mass_da: float, settings: AnalysisSettings,
                                 reserve_bytes: int):
    """Publish peak evidence from a guarded trajectory product and preserve its source identity."""
    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("reserve_bytes must be a positive integer")
    if not isinstance(settings, AnalysisSettings):
        raise ValueError("explicit peak analysis settings are required")
    asset_ids: set[str] = set()
    with guard_native_source(reference, expected_kind="trajectory_result",
            expected_artifact_root=Path(source_artifact_root), artifact_store=store, asset_ids=asset_ids) as source:
        if source.metadata.get("backend") != "comsol" or source.producer.get("status") != "success":
            raise ValueError("a successful COMSOL trajectory product is required")
        plan = json.loads(source.data_path("plan").read_text(encoding="utf-8-sig"))
        detector = plan.get("detector_active_face")
        if not isinstance(detector, dict) or detector.get("surface_id") != surface_id:
            raise ValueError("frozen COMSOL producer did not declare this detector surface")
        names = ("initial_states.parquet", "terminal_states.parquet", "events.parquet",
                 "trajectories.h5", "execution.json")
        paths = [source.data_path("particle_data_" + name.replace(".", "_")) for name in names]
        if any(path.name != name for path, name in zip(paths, names, strict=True)) or len({path.parent for path in paths}) != 1:
            raise ValueError("trajectory particle product is not one complete SI data directory")
        data = read_particle_data(paths[0].parent)
        native_facts = json.loads(source.data_path("native_facts").read_text(encoding="utf-8-sig"))
        _validate_native_source(data, plan, native_facts)
        result = analyze_native_detector_peak(data, species_id=species_id, surface_id=surface_id,
            nominal_mass_da=nominal_mass_da, settings=settings, declared_surface_ids=(detector["surface_id"],))
        return _publish_analysis(store, reference, data, result, species_id=species_id, surface_id=surface_id,
            nominal_mass_da=nominal_mass_da, settings=settings, reserve_bytes=reserve_bytes,
            asset_ids=asset_ids, source_retention="required_store_assets" if asset_ids else "external_source_not_owned")


def _validate_native_source(data, plan, facts):
    validate_comsol_particle_facts(facts, plan, particle_count=len(data["initial_states"]))
    try:
        frame = plan["background"]["projection"]["assembly_frame_id"]
        clock = plan["source"]["clock"]
    except (KeyError, TypeError) as error:
        raise ValueError("COMSOL native plan lacks its assembly frame or source clock") from error
    if (not isinstance(clock, dict) or set(clock) != {"clock_epoch_id", "authority_sha256"}
            or {"basis": "experiment_relative", "unit": "s", **clock} != data["metadata"]["clock"]):
        raise ValueError("COMSOL native plan and particle clock differ")
    if frame != data["metadata"]["frame_id"]:
        raise ValueError("COMSOL native plan and particle frame differ")


def _publish_analysis(store, reference, data, result, *, species_id, surface_id, nominal_mass_da, settings,
                      reserve_bytes, asset_ids, source_retention):
    run_id, work = store.begin_run()
    with store.run_writer(run_id):
        try:
            with store.reserve(reserve_bytes):
                store.mark_running(run_id)
                inputs = work / "inputs"
                inputs.mkdir()
                (inputs / "source_reference.json").write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (inputs / "analysis_request.json").write_text(json.dumps({
                    "schema_version": 1, "species_id": species_id, "surface_id": surface_id,
                    "nominal_mass_da": nominal_mass_da, "settings": settings.to_dict(),
                    "time_basis": "flight_time_from_verified_birth",
                    "source_retention": source_retention,
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output = work / "results"
                output.mkdir()
                report = {key: value for key, value in result.items() if key != "spectra"}
                report.update(schema_version=1, frame_id=data["metadata"]["frame_id"],
                              clock=data["metadata"]["clock"], source_execution_status=data["execution_status"])
                def convert(value):
                    if isinstance(value, np.generic):
                        return value.item()
                    if isinstance(value, np.ndarray):
                        return value.tolist()
                    raise TypeError(f"Cannot serialize {type(value)!r}")
                (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                    sort_keys=True, default=convert) + "\n", encoding="utf-8")
                spectra = result["spectra"]
                if spectra is not None:
                    pd.DataFrame({"tof_grid_us": spectra["time_grid_us"], "tof_density": spectra["time_density"],
                        "tof_intensity_normalized": spectra["time_density_normalized"],
                        "mass_grid_Da": spectra["mass_grid_Da"], "mass_density": spectra["mass_density"],
                        "mass_intensity_normalized": spectra["mass_density_normalized"]}).to_csv(output / "spectra.csv", index=False)
                    plot_single(pd.DataFrame({"tof_us": spectra["tof_us"]}), result["metrics"], spectra,
                                species_id, output / "peak_overview.png", result_schema_version=4)
                store.publish_run(work, run_id=run_id, required_assets=tuple(sorted(asset_ids)))
        except Exception as error:
            status = store.run_status(run_id)["execution_status"]
            if status == "queued":
                store.set_queued_reason(run_id, str(error))
            elif status == "running":
                store.finish_run(run_id, "failed", reason=str(error))
            raise
    return run_id, store.inspect_run(run_id)


def publish_public_run_detector_peak(source_run_id: str, *, store, species_id: str, surface_id: str,
                                     nominal_mass_da: float, settings: AnalysisSettings, reserve_bytes: int):
    """Analyze one published SCI run without relying on its evictable native cache."""
    from contextlib import ExitStack
    from msplatform.io.file_identity import guarded_file_identity
    from msplatform.io.manifest_records import file_record
    from msplatform.results.public_detector_contract import read_public_detector_contract

    if type(reserve_bytes) is not int or reserve_bytes <= 0 or not isinstance(settings, AnalysisSettings):
        raise ValueError("explicit positive reservation and peak settings are required")
    state = store.run_status(source_run_id)
    if state["publication_status"] != "ready" or state["execution_status"] != "succeeded":
        raise ValueError("detector analysis requires a published successful source run")
    root = (store.root / str(state["run_path"])).resolve(strict=True)
    if not root.is_relative_to(store.root / "runs"):
        raise ValueError("public SCI source run path escapes the Store")
    manifest_path = root / "run_manifest.json"
    manifest_record = file_record(manifest_path)
    with ExitStack() as stack:
        stack.enter_context(guarded_file_identity(manifest_path, expected_bytes=manifest_record["bytes"],
                                                  expected_sha256=manifest_record["sha256"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_id") != source_run_id:
            raise ValueError("public SCI run identity differs")
        names = ("detector_contract.json", "detector_plan.json", "detector_native_facts.json", "initial_states.parquet",
                 "terminal_states.parquet", "events.parquet", "trajectories.h5", "execution.json")
        for name in names:
            record = manifest.get("files", {}).get(name)
            if not isinstance(record, dict) or set(record) != {"bytes", "sha256"}:
                raise ValueError("public SCI run lacks a manifest-bound detector input")
            stack.enter_context(guarded_file_identity(root / name, expected_bytes=record["bytes"],
                                                      expected_sha256=record["sha256"]))
        if store.inspect_run(source_run_id) != root:
            raise ValueError("public SCI source Store identity differs")
        contract = read_public_detector_contract(root, manifest)
        detector = contract["detector_active_face"]
        if not isinstance(detector, dict) or detector.get("surface_id") != surface_id:
            raise ValueError("public SCI run did not declare this detector surface")
        data = read_particle_data(root)
        _validate_native_source(data, contract["plan"], contract["native_facts"])
        result = analyze_native_detector_peak(data, species_id=species_id, surface_id=surface_id,
            nominal_mass_da=nominal_mass_da, settings=settings, declared_surface_ids=(surface_id,))
        reference = {"kind": "published_store_run", "run_id": source_run_id,
                     "run_manifest_sha256": manifest_record["sha256"],
                     "native_producer_reference": contract["source_reference"]}
        return _publish_analysis(store, reference, data, result, species_id=species_id, surface_id=surface_id,
            nominal_mass_da=nominal_mass_da, settings=settings, reserve_bytes=reserve_bytes,
            asset_ids=set(), source_retention="published_store_run")
