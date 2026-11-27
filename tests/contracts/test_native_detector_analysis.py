"""Actual Store trajectory product and SI detector-analysis consumer; no native solver."""
import json
import shutil
from pathlib import Path
import tempfile
import unittest

import numpy as np

from msplatform.analysis.peak_metrics import AnalysisSettings
from msplatform.contracts.species import validate_species
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.physics import CONSTANTS
from msplatform.results.detector_observation import detector_observation
from msplatform.results.artifacts import open_artifact
from msplatform.results.model import TraceResult
from msplatform.results.particle_data import write_particle_data
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.native_detector_analysis import (
    publish_native_detector_peak, publish_public_run_detector_peak,
)


def source(store, *, hits, observed, native_detector=True, plan_epoch="fixture"):
    species = validate_species(dict(species_id="ion", species_kind="ion", mass_kg=524 * CONSTANTS["atomic_mass_constant_kg"],
                                    charge_state=1, charge_c=CONSTANTS["elementary_charge_c"]))
    with store.inplace_asset("native_stage", "trajectory-" + observed + str(hits)) as (identity, asset, _, seal):
        run = asset / "runs/20261127_180000__sim__comsol__inert-detector"
        output = run / "results"
        output.mkdir(parents=True)
        initial, terminal, events = [], [], []
        for i in range(1, 5):
            start = i * 1e-7
            end = start + (10 + i) * 1e-6
            initial.append(dict(particle_id=i, species_id="ion", position_m=[0.,0.,0.], velocity_m_s=[1.,0.,0.],
                time_s=start, mass_kg=species["mass_kg"], charge_state=1, charge_c=species["charge_c"],
                weight=1., parent_particle_id=None, lineage_status="primary_birth"))
            found = i <= hits
            row = dict(particle_id=i, species_id="ion", position_m=[0.,0.,0.], velocity_m_s=[1.,0.,0.], time_s=end,
                physical_outcome="detected" if found else "unknown", stop_reason="normal",
                component_id="detector" if found else None, electrode_id="disk" if found else None,
                surface_id="detector_active_face" if found else None,
                attribution_method="native_detector_wall_auxiliary" if found else "unavailable",
                attribution_status="known" if found else "unavailable", started=True, backend_version="inert-fixture",
                native_termination_code="2", native_entity_id=None, detail=None)
            terminal.append(row)
            if found:
                events.append(dict(row, event_kind="detector", event_sequence=1, crossing_direction=1))
        arrays = dict(particle_id=np.empty(0,dtype="int64"), time_s=np.empty(0),
                      position_m=np.empty((0,3)), velocity_m_s=np.empty((0,3)))
        reason = None if observed == "complete" else "detector_observation_unsupported"
        result = TraceResult(initial, terminal, events, arrays, "succeeded", dict(status="complete",
            detector_observation=detector_observation(observed, [1,2,3,4], reason=reason)))
        write_particle_data(output, result, metadata=dict(schema_version=2, initial_state_basis="native_birth_verified",
            frame_id="inert-frame", clock={"basis":"experiment_relative", "unit":"s",
                "clock_epoch_id":"fixture", "authority_sha256":"0" * 64}, species=[species]))
        plan = run / "plan.json"
        plan.write_text(json.dumps({"detector_active_face":{"surface_id":"detector_active_face"},
            "observation_times_us":[0.0, 20.0], "background":{"projection":{"assembly_frame_id":"inert-frame"}},
            "source":{"clock":{"clock_epoch_id":plan_epoch, "authority_sha256":"0" * 64}}}), encoding="utf-8")
        facts = run / "native_facts.json"
        facts.write_text(json.dumps({"comsol_version":"6.4", "study_completed":True, "particle_count":4,
            "stored_times_us":[0.0, 20.0], "boundary_policy":"metal_and_outer_freeze_ideal_pass",
            "detector_faces":[1], "detector_observation_native":native_detector}), encoding="utf-8")
        config = run / "run_config.json"
        config.write_text("{}", encoding="utf-8")
        records = {"plan": file_record(plan), "native_facts": file_record(facts)}
        for name in ("initial_states.parquet", "terminal_states.parquet", "events.parquet", "trajectories.h5", "execution.json"):
            records["particle_data_" + name.replace(".", "_")] = file_record(output / name)
        manifest = dict(schema_version=2, role="simulation_run_manifest", run_id=run.name,
            project="instrument_assembly", mode="particle_trace", status="success", run_config=file_record(config),
            inputs={}, outputs=list(records.values()), products={"trajectory": dict(schema_version=1,
                kind="trajectory_result", status="complete", metadata={"backend":"comsol"}, data=records)})
        publish_terminal_state(run, {"status":"success"}, manifest)
        reference = {"manifest": file_record(run / "run_manifest.json"), "product_id":"trajectory"}
        seal()
    return reference, identity


class NativeDetectorAnalysisTests(unittest.TestCase):
    def test_guarded_si_products_publish_and_pin_required_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            reference, identity = source(store, hits=4, observed="complete")
            run, path = publish_native_detector_peak(reference, source_artifact_root=root, store=store, species_id="ion",
                surface_id="detector_active_face", nominal_mass_da=524, settings=AnalysisSettings(), reserve_bytes=20_000_000)
            result = json.loads((path / "results/metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["summary"]["detector_observed_count"], 4)
            self.assertEqual(result["summary"]["time_basis"], "flight_time_from_verified_birth")
            self.assertEqual(path, store.inspect_run(run))
            store.collect(100_000_000)
            self.assertIsNotNone(store.find_asset("trajectory-complete4"))
            self.assertTrue((store.inspect_run(run) / "results/peak_overview.png").is_file())
            self.assertTrue(identity)

    def test_public_science_run_remains_analyzable_after_native_cache_gc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            reference, _ = source(store, hits=4, observed="complete")
            artifact = open_artifact(reference, expected_kind="trajectory_result")
            run, work = store.begin_run()
            with store.run_writer(run), store.reserve(20_000_000):
                store.mark_running(run)
                for name in ("initial_states.parquet", "terminal_states.parquet", "events.parquet", "trajectories.h5", "execution.json"):
                    shutil.copyfile(artifact.data_path("particle_data_" + name.replace(".", "_")), work / name)
                from msplatform.execution.native_source_guard import guard_native_source
                from msplatform.workflows.native_tracing import _archive_comsol_detector_contract
                with guard_native_source(reference, expected_kind="trajectory_result",
                                         expected_artifact_root=root, artifact_store=store) as protected:
                    _archive_comsol_detector_contract(protected, work)
                store.publish_run(work, run_id=run)
            store.collect(100_000_000)
            self.assertIsNone(store.find_asset("trajectory-complete4"))
            analysis_run, path = publish_public_run_detector_peak(run, store=store, species_id="ion",
                surface_id="detector_active_face", nominal_mass_da=524, settings=AnalysisSettings(), reserve_bytes=20_000_000)
            result = json.loads((path / "results/metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["summary"]["detector_observed_count"], 4)
            self.assertEqual(store.inspect_run(analysis_run), path)

    def test_plan_without_native_detector_fact_does_not_certify_hits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            reference, _ = source(store, hits=4, observed="complete", native_detector=False)
            with self.assertRaisesRegex(ValueError, "native detector boundary evidence is missing"):
                publish_native_detector_peak(reference, source_artifact_root=root, store=store, species_id="ion",
                    surface_id="detector_active_face", nominal_mass_da=524, settings=AnalysisSettings(), reserve_bytes=20_000_000)

    def test_mismatched_native_clock_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            reference, _ = source(store, hits=4, observed="complete", plan_epoch="different")
            with self.assertRaisesRegex(ValueError, "particle clock differ"):
                publish_native_detector_peak(reference, source_artifact_root=root, store=store, species_id="ion",
                    surface_id="detector_active_face", nominal_mass_da=524, settings=AnalysisSettings(), reserve_bytes=20_000_000)

    def test_zero_hit_is_available_but_unknown_observation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
            reference, _ = source(store, hits=0, observed="complete")
            _, path = publish_native_detector_peak(reference, source_artifact_root=root, store=store, species_id="ion",
                surface_id="detector_active_face", nominal_mass_da=524, settings=AnalysisSettings(), reserve_bytes=20_000_000)
            result = json.loads((path / "results/metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["summary"]["detector_observed_count"], 0)
            self.assertIsNone(result["metrics"])
            self.assertFalse((path / "results/peak_overview.png").exists())
            unknown, _ = source(store, hits=0, observed="unavailable")
            with self.assertRaisesRegex(ValueError, "complete detector observation"):
                publish_native_detector_peak(unknown, source_artifact_root=root, store=store, species_id="ion",
                    surface_id="detector_active_face", nominal_mass_da=524, settings=AnalysisSettings(), reserve_bytes=20_000_000)


if __name__ == "__main__":
    unittest.main()
