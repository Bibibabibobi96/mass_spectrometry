from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation import (
    REQUIRED_INPUT_ROLES,
    build_continuation_plan,
    build_prepared_joint_whole_unit_plan,
    continuation_protection_projection,
)
from common.contracts.write_run_manifest import file_record


class MrtofBatchContinuationTests(unittest.TestCase):
    def test_protection_projection_covers_multigeneration_and_rejects_unbound_source(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory) / "artifacts/projects/instrument_assembly/runs"
            original, second, third = (runs / name for name in ("old", "middle", "new"))
            for path in (original, second, third):
                path.mkdir(parents=True)
            log = original / "joint_flight_batch_001.log"
            exit_fact = original / "owner_exit.json"
            log.write_text("sealed native output")
            exit_fact.write_text('{"role":"simion_batch_owner_exit"}')
            def seal(run, inputs, outputs):
                config = run / "run_config.json"
                config.write_text(json.dumps({"run_id": run.name, "project": "instrument_assembly",
                    "mode": "prepared_joint", "inputs": {key: str(path) for key, path in inputs.items()}}))
                (run / "run_manifest.json").write_text(json.dumps({"role": "simulation_run_manifest", "status": "failed",
                    "run_id": run.name, "project": "instrument_assembly", "mode": "prepared_joint",
                    "run_config": file_record(config), "inputs": {key: file_record(path) for key, path in inputs.items()},
                    "outputs": [file_record(path) for path in outputs]}))
            seal(original, {}, [log, exit_fact])
            seal(second, {"reused_batch_001_log": log, "reused_batch_001_owner_exit": exit_fact,
                          "continuation_parent_manifest": original / "run_manifest.json"}, [])
            seal(third, {"reused_batch_001_log": log, "reused_batch_001_owner_exit": exit_fact,
                         "continuation_parent_manifest": second / "run_manifest.json"}, [])
            projection = continuation_protection_projection(third)
            self.assertCountEqual(projection["run_directories"], [str(original), str(second), str(third)])
            self.assertIn(str(log), projection["files"])
            self.assertIn(str(exit_fact), projection["files"])
            self.assertEqual(len(projection["manifests"]), 3)
            cli = subprocess.run([sys.executable, "-m",
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation",
                "--predecessor-run-dir", str(third), "--protection-projection"],
                cwd=Path(__file__).resolve().parents[4], capture_output=True, text=True, timeout=30)
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertEqual(json.loads(cli.stdout), projection)
            source_manifest_path = original / "run_manifest.json"
            source = json.loads(source_manifest_path.read_text())
            source["outputs"][0]["sha256"] = "0" * 64
            source_manifest_path.write_text(json.dumps(source))
            with self.assertRaises((ValueError, AssertionError, ContractError)):
                continuation_protection_projection(third)

    def _exit(self, root: Path, index: int, code: int = 0) -> Path:
        path = root / f"results/batches/batch_{index:03d}/owner_exit.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "role": "simion_batch_owner_exit",
                                    "batch_index": index, "completed": True, "exit_code": code}))
        return path

    def _prepared_joint_fixture(self, root: Path, *, second_complete: bool) -> tuple[Path, Path]:
        """Create an interrupted two-unit predecessor and its new frozen preparation."""
        parent = root / "parent"
        current = root / "current"
        for directory in (parent / "results", parent / "logs", current / "results"):
            directory.mkdir(parents=True, exist_ok=True)
        preparation = {
            "expected_particle_ids": [1, 7],
            "mother_particle_count": 100,
            "launched_particle_count": 2,
            "solver_epoch_instrument_time_us": 7500.5,
            "numerics": {"maximum_step_us": 0.001},
            "parent_preparation": {"path": "/parent/preparation.json", "sha256": "a" * 64},
            "field_binding": {"path": "/parent/binding.json", "sha256": "b" * 64},
            "trajectory_contract": {"path": "/parent/contract.json", "sha256": "c" * 64},
            "flight_program": {"path": "/parent/joint.lua", "sha256": "d" * 64},
            "source_runtime": {"path": "/parent/joint.source_runtime.lua", "sha256": "e" * 64},
            "voltage_waveforms": {"path": "/parent/joint.voltage_waveforms.lua", "sha256": "f" * 64},
            "source_mode": "measured_population",
            "prism_voltages_v": [1.0, 2.0],
            "stripe_biases_v": [3.0, 4.0],
        }
        parent_preparation = parent / "results" / "prepared_joint_trial.json"
        current_preparation = current / "results" / "prepared_joint_trial.json"
        parent_preparation.write_text(json.dumps(preparation) + "\n", encoding="utf-8")
        current_value = json.loads(json.dumps(preparation))
        for key in ("parent_preparation", "field_binding", "trajectory_contract",
                    "flight_program", "source_runtime", "voltage_waveforms"):
            current_value[key]["path"] = current_value[key]["path"].replace("/parent/", "/current/")
        current_preparation.write_text(json.dumps(current_value) + "\n", encoding="utf-8")
        batch_plan = parent / "results" / "simion_execution_batch_plan.json"
        batch_plan.write_text(
            json.dumps(
                {
                    "role": "simion_single_wave_particle_batch_plan",
                    "batches": [
                        {"index": 1, "particle_id_min": 1, "particle_id_max": 1, "count": 1},
                        {"index": 2, "particle_id_min": 2, "particle_id_max": 2, "count": 1},
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        dispatch_request = parent / "results" / "simion_dispatch_request.json"
        resource_profiles = parent / "results" / "simion_resource_profiles.json"
        dispatch_plan = parent / "results" / "simion_repository_dispatch_plan.json"
        dispatch_request.write_text("{}\n", encoding="utf-8")
        resource_profiles.write_text("{}\n", encoding="utf-8")
        dispatch_plan.write_text('{"estimation":{"kind":"observed"}}\n', encoding="utf-8")
        outputs = [parent_preparation, batch_plan, dispatch_request, resource_profiles, dispatch_plan]
        for index, original_id in enumerate(preparation["expected_particle_ids"], start=1):
            batch_dir = parent / "results" / "batches" / f"batch_{index:03d}"
            batch_dir.mkdir(parents=True)
            fly = batch_dir / "joint.fly2"
            fly.write_text(f"frozen batch {index}\n", encoding="utf-8")
            receipt = batch_dir / "batch_receipt.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "mrtof_measured_source_batch",
                        "original_particle_ids": [original_id],
                        "count": 1,
                        "solver_epoch_instrument_time_us": preparation["solver_epoch_instrument_time_us"],
                        "outputs": {"source": file_record(fly)},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            log = parent / "logs" / f"joint_flight_batch_{index:03d}.log"
            complete = index == 1 or second_complete
            log.write_text(
                (
                    f"MRTOF_EVENT terminal ion={original_id} t_us=1\n"
                    "status,Fly completed. 1 splats\n"
                    "IOB_FLIGHT: PASS iob=joint.iob\n"
                )
                if complete
                else f"MRTOF_EVENT terminal ion={original_id} t_us=1\n",
                encoding="utf-8",
            )
            outputs.extend((fly, receipt, log))
            outputs.append(self._exit(parent, index))
        config = parent / "run_config.json"
        config.write_text(
            json.dumps(
                {
                    "run_id": "parent",
                    "inputs": {
                        "simion_execution_batch_plan": str(batch_plan.resolve()),
                        "prepared_joint_trial": str(parent_preparation.resolve()),
                        "simion_dispatch_request": str(dispatch_request.resolve()),
                        "simion_resource_profiles": str(resource_profiles.resolve()),
                        "simion_repository_dispatch_plan": str(dispatch_plan.resolve()),
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (parent / "run_manifest.json").write_text(
            json.dumps(
                {
                    "role": "simulation_run_manifest",
                    "run_id": "parent",
                    "status": "interrupted",
                    "run_config": {"sha256": file_sha256(config)},
                    "inputs": {key: file_record(Path(value)) for key, value in json.loads(config.read_text(encoding="utf-8"))["inputs"].items()},
                    "outputs": [file_record(path) for path in outputs],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return parent, current_preparation

    def test_prepared_joint_reuses_complete_units_and_replays_an_incomplete_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=False)
            plan = build_prepared_joint_whole_unit_plan(
                predecessor_run_dir=parent,
                current_preparation=current,
                output_dir=root / "recovery",
            )
        self.assertEqual([batch["action"] for batch in plan["batches"]], ["reuse", "replay"])
        self.assertEqual((plan["reusable_unit_count"], plan["replay_unit_count"]), (1, 1))
        self.assertEqual(len(plan["units"][0]["terminal_outputs"]), 4)
        self.assertEqual(plan["units"][1]["terminal_outputs"], [])
        self.assertTrue(plan["dispatch_plan"]["path"].endswith("simion_repository_dispatch_plan.json"))

    def test_prepared_rejects_incomplete_or_gapped_population_plan(self) -> None:
        for kind in ("formal_only", "truncated", "gap"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._prepared_joint_fixture(root, second_complete=True)
                plan_path = parent / "results/simion_execution_batch_plan.json"
                plan = json.loads(plan_path.read_text())
                if kind == "formal_only":
                    plan["coverage"] = "initial_formal_batch_only"
                    plan["batches"] = plan["batches"][:1]
                elif kind == "truncated":
                    plan["batches"] = plan["batches"][:1]
                else:
                    plan["batches"][1]["particle_id_min"] = 3
                plan_path.write_text(json.dumps(plan))
                manifest_path = parent / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["inputs"]["simion_execution_batch_plan"] = file_record(plan_path)
                manifest["outputs"] = [file_record(plan_path) if record["path"] == str(plan_path.resolve()) else record
                                       for record in manifest["outputs"]]
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ContractError, "(formal recovery|formal provisional|batch plan does not cover|batch interval differs)"):
                    build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current,
                                                        output_dir=root / "recovery")

    def test_prepared_replans_formal_batch_from_sealed_observation(self) -> None:
        from common.simion.particle_batching import batch_plan_from_dispatch
        from common.simion.resource_scheduler import plan_simion_dispatch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=False)
            request = {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
                       "particle_count": 2, "independent_particles": True, "trajectory_quality": 8}
            dispatch = plan_simion_dispatch(request, [], available_memory_bytes=10*1024**3,
                                           total_physical_memory_bytes=20*1024**3, logical_processors=8)
            dispatch_path = parent / "results/simion_repository_dispatch_plan.json"
            plan_path = parent / "results/simion_execution_batch_plan.json"
            dispatch_path.write_text(json.dumps(dispatch))
            plan_path.write_text(json.dumps(batch_plan_from_dispatch(dispatch)))
            usage = parent / "logs/simion_batch_resource_usage.json"
            usage.write_text(json.dumps({"first_formal_observation": {"peak_managed_memory_bytes": 1024**3,
                "process_cpu_percent": 8.0, "background_cpu_percent": 0.0}}))
            manifest_path = parent / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for role, path in (("simion_execution_batch_plan", plan_path), ("simion_repository_dispatch_plan", dispatch_path)):
                manifest["inputs"][role] = file_record(path)
                manifest["outputs"] = [file_record(path) if record["path"] == str(path.resolve()) else record
                                       for record in manifest["outputs"]]
            manifest["outputs"].append(file_record(usage))
            manifest_path.write_text(json.dumps(manifest))
            recovered = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current,
                                                            output_dir=root / "recovery")
            self.assertEqual([item["action"] for item in recovered["batches"]], ["reuse", "replay"])
            self.assertEqual(recovered["batches"][0]["particle_id_max"], 1)
            self.assertEqual(recovered["batches"][1]["particle_id_min"], 2)
            self.assertTrue(Path(recovered["dispatch_plan"]["path"]).is_file())
            self.assertEqual(recovered["recovered_formal_provenance"]["resource_usage"]["path"], str(usage.resolve()))
            usage.write_text(json.dumps({"first_formal_observation": {"peak_working_set_bytes": 2048,
                "process_cpu_percent": 8.0, "background_cpu_percent": 0.0}}))
            manifest["outputs"] = [file_record(usage) if entry["path"] == str(usage.resolve()) else entry
                                   for entry in manifest["outputs"]]
            manifest_path.write_text(json.dumps(manifest))
            recovered = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current,
                                                            output_dir=root / "legacy_observation")
            legacy = json.loads(Path(recovered["dispatch_plan"]["path"]).read_text())
            self.assertTrue(legacy["estimation"]["recovered_missing_observation"])
            usage.unlink()
            manifest["outputs"] = [entry for entry in manifest["outputs"] if entry["path"] != str(usage.resolve())]
            manifest_path.write_text(json.dumps(manifest))
            recovered = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current,
                                                            output_dir=root / "no_observation")
            self.assertEqual([item["action"] for item in recovered["batches"]], ["reuse", "replay"])
            fallback = json.loads(Path(recovered["dispatch_plan"]["path"]).read_text())
            self.assertTrue(fallback["estimation"]["recovered_missing_observation"])
            self.assertEqual(fallback["limits"]["maximum_concurrency"], 1)
            self.assertIsNone(recovered["recovered_formal_provenance"]["resource_usage"])

    def test_prepared_recovers_committed_dispatch_when_batch_plan_write_failed(self) -> None:
        from common.simion.particle_batching import batch_plan_from_dispatch
        from common.simion.resource_scheduler import plan_adaptive_followup, plan_simion_dispatch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            parent,current=self._prepared_joint_fixture(root,second_complete=False)
            request={"solver":"SIMION","field_kind":"rf","rf_steps_per_period":40,
                     "particle_count":2,"independent_particles":True,"trajectory_quality":8}
            initial=plan_simion_dispatch(request,[],available_memory_bytes=10*1024**3,
                                         total_physical_memory_bytes=20*1024**3,logical_processors=8)
            committed=plan_adaptive_followup(initial,1024**3,observed_cpu_percent=8,
                background_cpu_percent=0,first_batch_completed=True)
            dispatch_path=parent/'results/simion_repository_dispatch_plan.json'
            plan_path=parent/'results/simion_execution_batch_plan.json'
            dispatch_path.write_text(json.dumps(committed))
            plan_path.write_text(json.dumps(batch_plan_from_dispatch(initial)))
            manifest_path=parent/'run_manifest.json';manifest=json.loads(manifest_path.read_text())
            for role,path in (("simion_execution_batch_plan",plan_path),("simion_repository_dispatch_plan",dispatch_path)):
                manifest['inputs'][role]=file_record(path)
                manifest['outputs']=[file_record(path) if record['path']==str(path.resolve()) else record
                                     for record in manifest['outputs']]
            manifest_path.write_text(json.dumps(manifest))
            recovered=build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent,current_preparation=current,
                                                           output_dir=root/'recovery')
            self.assertEqual([unit['action'] for unit in recovered['batches']],['reuse','replay'])
            self.assertEqual(json.loads(Path(recovered['dispatch_plan']['path']).read_text()),committed)
            committed['waves'][0]['batches'][0]['particle_id_max']=2
            dispatch_path.write_text(json.dumps(committed));manifest['inputs']['simion_repository_dispatch_plan']=file_record(dispatch_path)
            manifest['outputs']=[file_record(dispatch_path) if record['path']==str(dispatch_path.resolve()) else record
                                 for record in manifest['outputs']]
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError,'provisional dispatch'):
                build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent,current_preparation=current,
                                                     output_dir=root/'rejected')

    def test_owner_exit_missing_or_nonzero_replays_only_that_complete_batch(self) -> None:
        for kind in ("oa", "prepared"):
            for state in ("missing", "nonzero"):
                with self.subTest(kind=kind, state=state), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    if kind == "oa":
                        parent, current = self._fixture(root)
                    else:
                        parent, current = self._prepared_joint_fixture(root, second_complete=True)
                    evidence = parent / "results/batches/batch_001/owner_exit.json"
                    if state == "missing":
                        evidence.unlink()
                    else:
                        self._exit(parent, 1, code=7)
                    plan = (build_continuation_plan(predecessor_run_dir=parent, current_run_config=current,
                                                    output_dir=root / "recovery") if kind == "oa" else
                            build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current,
                                                                 output_dir=root / "recovery"))
                    self.assertEqual(plan["batches"][0]["action"], "replay")
                    if kind == "prepared":
                        self.assertEqual(plan["batches"][1]["action"], "reuse")

    def test_legacy_prepared_success_uses_bound_owner_and_aggregate_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=True)
            for index in (1, 2):
                (parent / f"results/batches/batch_{index:03d}/owner_exit.json").unlink()
            owner = parent / "owner.ps1"
            owner.write_bytes(subprocess.check_output(["git", "show", "af158d22c53e5ff85a32e9984f4d9b2bb009777b:integrations/workflows/prepared_joint/execute.ps1"], cwd=Path(__file__).resolve().parents[4], timeout=30))
            usage = parent / "logs/simion_batch_resource_usage.json"
            usage.write_text(json.dumps({"status": "completed", "execution_wave": {"process_count": 2}}))
            config_path = parent / "run_config.json"
            config = json.loads(config_path.read_text())
            config.update(project="instrument_assembly", mode="prepared_joint")
            config["inputs"]["prepared_joint_integrations_workflows_prepared_joint_execute_ps1"] = str(owner)
            config_path.write_text(json.dumps(config))
            manifest_path = parent / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["status"] = "success"
            manifest["run_config"] = file_record(config_path)
            manifest["inputs"]["prepared_joint_integrations_workflows_prepared_joint_execute_ps1"] = file_record(owner)
            manifest["outputs"] = [record for record in manifest["outputs"] if not record["path"].endswith("owner_exit.json")]
            manifest["outputs"].append(file_record(usage))
            manifest_path.write_text(json.dumps(manifest))
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis import mrtof_batch_continuation
            frozen_module = root / "snapshot/projects/parallel_mirror_dual_stripe_mr_tof/analysis/mrtof_batch_continuation.py"
            frozen_module.parent.mkdir(parents=True)
            frozen_module.write_bytes(Path(mrtof_batch_continuation.__file__).read_bytes())
            spec = importlib.util.spec_from_file_location("frozen_batch_continuation", frozen_module)
            assert spec is not None and spec.loader is not None
            snapshot = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(snapshot)
            self.assertIsNone(snapshot._legacy_prepared_success(manifest_path, 2))
            self.assertEqual(snapshot._legacy_prepared_success(manifest_path, 2,
                trusted_repo_root=Path(mrtof_batch_continuation.__file__).resolve().parents[3]), usage)
            self.assertIsNone(snapshot._legacy_prepared_success(manifest_path, 2, trusted_repo_root=root))
            plan = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "legacy")
            self.assertEqual(plan["replay_unit_count"], 0)
            self.assertEqual(plan["batches"][0]["exit_evidence_kind"], "legacy_aggregate_success")
            self.assertEqual(plan["batches"][0]["exit_evidence_manifest"], str(manifest_path.resolve()))
            owner.write_bytes(owner.read_bytes() + b"\n# different version\n")
            manifest["inputs"]["prepared_joint_integrations_workflows_prepared_joint_execute_ps1"] = file_record(owner)
            manifest_path.write_text(json.dumps(manifest))
            plan = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "unknown_owner")
            self.assertEqual(plan["replay_unit_count"], 2)
            manifest["status"] = "failed"
            manifest_path.write_text(json.dumps(manifest))
            plan = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "failed")
            self.assertEqual(plan["replay_unit_count"], 2)

    def test_continuation_waveform_is_resolved_through_sealed_trial_and_rejects_damage(self) -> None:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import _continuation_waveforms
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            waveform = root / "waveforms.lua"
            waveform.write_text("return {}\n")
            trial = root / "trial.json"
            trial.write_text(json.dumps({"voltage_waveforms": file_record(waveform)}))
            config = root / "run_config.json"
            config.write_text(json.dumps({"project": "instrument_assembly", "mode": "prepared_joint",
                                          "inputs": {"prepared_joint_trial": str(trial)}}))
            manifest = root / "run_manifest.json"
            manifest.write_text(json.dumps({"run_config": file_record(config),
                                            "inputs": {"prepared_joint_trial": file_record(trial)}}))
            resolved, provenance = _continuation_waveforms(manifest)
            self.assertEqual(resolved, waveform.resolve())
            self.assertEqual(provenance["manifest"], str(manifest.resolve()))
            waveform.write_text("changed\n")
            with self.assertRaises((ValueError, AssertionError)):
                _continuation_waveforms(manifest)

    def test_peak_upgrade_reuses_fly_only_with_verified_contracts_and_unchanged_flight(self) -> None:
        from common.analysis.peak_metrics import AnalysisSettings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=True)
            timing = root / "timing.json"
            timing.write_text(json.dumps({"schema_version": 1, "role": "native_electrode_timing", "pulse_start_us": 1.0}))
            peak = {"method_id": "common_gaussian_kde_time_v2",
                    "resolution_definition": "mean_tof_us/(2*direct_fwhm_tof_us)",
                    "time_basis": "instrument_arrival_minus_common_extraction_pulse_us",
                    "settings": vars(AnalysisSettings()), "common_time_reference": {
                        "clock_epoch_id": "epoch", "field": "pulse_start_us", "timing": file_record(timing)}}
            parent_contract, current_contract = root / "old.json", root / "new.json"
            parent_contract.write_text(json.dumps({"peak_analysis": {**peak, "method_id": "common_gaussian_kde_time_v1"}, "flight": {"step": 1}}))
            current_contract.write_text(json.dumps({"peak_analysis": peak, "flight": {"step": 1}}))
            parent_trial = parent / "results/prepared_joint_trial.json"
            for trial, contract in ((parent_trial, parent_contract), (current, current_contract)):
                value = json.loads(trial.read_text())
                value["trajectory_contract"] = file_record(contract)
                trial.write_text(json.dumps(value))
            manifest_path = parent / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["inputs"]["prepared_joint_trial"] = file_record(parent_trial)
            manifest["outputs"] = [file_record(parent_trial) if entry["path"] == str(parent_trial.resolve()) else entry
                                   for entry in manifest["outputs"]]
            manifest_path.write_text(json.dumps(manifest))
            plan = build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "ok")
            self.assertEqual(plan["replay_unit_count"], 0)
            self.assertEqual(plan["analysis_contract_change"]["excluded_analysis_field"], "peak_analysis")
            invalid_peak = dict(peak)
            invalid_peak.pop("common_time_reference")
            current_contract.write_text(json.dumps({"peak_analysis": invalid_peak, "flight": {"step": 1}}))
            value = json.loads(current.read_text())
            value["trajectory_contract"] = file_record(current_contract)
            current.write_text(json.dumps(value))
            with self.assertRaisesRegex(ContractError, "peak analysis contract is invalid"):
                build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "clock")
            current_contract.write_text(json.dumps({"peak_analysis": peak, "flight": {"step": 2}}))
            value = json.loads(current.read_text())
            value["trajectory_contract"] = file_record(current_contract)
            current.write_text(json.dumps(value))
            with self.assertRaisesRegex(ContractError, "scientific identity differs"):
                build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "bad")
            current_contract.write_text('{}')
            with self.assertRaisesRegex(ContractError, "trajectory contract is invalid"):
                build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent, current_preparation=current, output_dir=root / "tampered")

    def test_prepared_joint_rejects_scientific_input_drift_before_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=True)
            changed = json.loads(current.read_text(encoding="utf-8"))
            changed["field_binding"] = {"sha256": "d" * 64}
            current.write_text(json.dumps(changed) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "frozen scientific identity differs"):
                build_prepared_joint_whole_unit_plan(
                    predecessor_run_dir=parent,
                    current_preparation=current,
                    output_dir=root / "recovery",
                )

    def test_prepared_joint_requires_manifest_bound_predecessor_dispatch_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=True)
            config_path = parent / "run_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            del config["inputs"]["simion_repository_dispatch_plan"]
            config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "lacks frozen input: simion_repository_dispatch_plan"):
                build_prepared_joint_whole_unit_plan(
                    predecessor_run_dir=parent,
                    current_preparation=current,
                    output_dir=root / "recovery",
                )

    def test_prepared_joint_rejects_program_source_and_waveform_drift_with_same_operating_point(self) -> None:
        for role in ("flight_program", "source_runtime", "voltage_waveforms"):
            for missing in (False, True):
                with self.subTest(role=role, missing=missing), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    parent, current = self._prepared_joint_fixture(root, second_complete=True)
                    value = json.loads(current.read_text())
                    if missing:
                        del value[role]
                    else:
                        value[role]["sha256"] = "0" * 64
                    current.write_text(json.dumps(value))
                    with self.assertRaisesRegex(ContractError, "scientific identity"):
                        build_prepared_joint_whole_unit_plan(predecessor_run_dir=parent,
                            current_preparation=current, output_dir=root / "recovery")

    def test_prepared_joint_recovery_carries_manifest_bound_reuse_into_the_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._prepared_joint_fixture(root, second_complete=False)
            first_plan = build_prepared_joint_whole_unit_plan(
                predecessor_run_dir=parent,
                current_preparation=current,
                output_dir=root / "b_inputs",
            )
            recovered = root / "recovered"
            (recovered / "results/batches/batch_002").mkdir(parents=True)
            (recovered / "logs").mkdir()
            replay_fly = recovered / "results/batches/batch_002/joint.fly2"
            replay_fly.write_text("replayed second batch\n", encoding="utf-8")
            replay_receipt = recovered / "results/batches/batch_002/batch_receipt.json"
            replay_receipt.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "mrtof_measured_source_batch",
                        "original_particle_ids": [7],
                        "count": 1,
                        "solver_epoch_instrument_time_us": 7500.5,
                        "outputs": {"source": file_record(replay_fly)},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            replay_log = recovered / "logs/joint_flight_batch_002.log"
            replay_log.write_text(
                "MRTOF_EVENT terminal ion=7 t_us=1\n"
                "status,Fly completed. 1 splats\n"
                "IOB_FLIGHT: PASS iob=joint.iob\n",
                encoding="utf-8",
            )
            recovered_preparation = current
            first_outputs = first_plan["units"][0]["terminal_outputs"]
            recovered_config = recovered / "run_config.json"
            parent_inputs = json.loads((parent / "run_config.json").read_text(encoding="utf-8"))["inputs"]
            recovered_inputs = {
                "prepared_joint_trial": str(recovered_preparation.resolve()),
                "simion_execution_batch_plan": str((parent / "results/simion_execution_batch_plan.json").resolve()),
                "simion_dispatch_request": parent_inputs["simion_dispatch_request"],
                "simion_resource_profiles": parent_inputs["simion_resource_profiles"],
                "simion_repository_dispatch_plan": parent_inputs["simion_repository_dispatch_plan"],
                "simion_whole_unit_replay_plan": str((root / "b_inputs/simion_whole_unit_replay_plan.json").resolve()),
                "reused_batch_001_log": first_outputs[0]["path"],
                "reused_batch_001_receipt": first_outputs[1]["path"],
                "reused_batch_001_fly2": first_outputs[2]["path"],
                "reused_batch_001_owner_exit": first_outputs[3]["path"],
            }
            recovered_config.write_text(
                json.dumps({"run_id": "recovered", "inputs": recovered_inputs}) + "\n",
                encoding="utf-8",
            )
            (recovered / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "role": "simulation_run_manifest",
                        "run_id": "recovered",
                        "status": "interrupted",
                        "run_config": {"sha256": file_sha256(recovered_config)},
                        "inputs": {key: file_record(Path(value)) for key, value in recovered_inputs.items()},
                        "outputs": [file_record(path) for path in (replay_fly, replay_receipt, replay_log, self._exit(recovered, 2))],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            next_preparation = root / "next/prepared_joint_trial.json"
            next_preparation.parent.mkdir(parents=True)
            next_preparation.write_bytes(current.read_bytes())
            next_plan = build_prepared_joint_whole_unit_plan(
                predecessor_run_dir=recovered,
                current_preparation=next_preparation,
                output_dir=root / "c_inputs",
            )
        self.assertEqual([batch["action"] for batch in next_plan["batches"]], ["reuse", "reuse"])
        self.assertEqual((next_plan["reusable_unit_count"], next_plan["replay_unit_count"]), (2, 0))

    def _fixture(self, root: Path, *, static_mode: str | None = None) -> tuple[Path, Path]:
        parent = root / "parent"
        current = root / "current"
        for run in (parent, current):
            (run / "inputs").mkdir(parents=True)
            (run / "logs").mkdir()

        def materialize(run: Path) -> dict[str, str]:
            inputs: dict[str, str] = {}
            roles = REQUIRED_INPUT_ROLES
            if static_mode is not None:
                roles = roles[:-2] + ("static_field_binding", "scalar_field_adapter")
            for role in roles:
                path = run / "inputs" / f"{role}.json"
                value = {"role": role}
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")
                inputs[role] = str(path.resolve())
            trial = run / "inputs" / "trial_materialization.json"
            priority = Path(inputs["native_corridor_priority_contract"])
            trial_value = dict(schema_version=1, role="mrtof_finite_3d_two_prism_voltage_trial", status="materialized",
                source_particle_count=3, source_expected_particle_ids=[1, 2, 3], source_time_of_birth_us=0.,
                source_clock_basis="instrument_global_us", source_cohort=dict(mother_particle_count=100,
                    particle_states_sha256="a"*64, expected_particle_ids_sha256="b"*64),
                resolved_iob_pose=dict(frame_id="mrtof_global_cartesian", origins_mm=[[0, 0, 0]]),
                trajectory_profile=dict(profile_id="fixed", trajectory_quality=3),
                native_corridor_priority_contract=file_record(priority),
                inputs=dict(geometry_contract_sha256="c"*64, bunch_source_receipt_sha256="d"*64),
                analyzer_electrode_voltages_v=[0., 10.],
                field_binding=(dict(mode=static_mode, path=inputs["static_field_binding"],
                    grid=dict(pitch_mm=[1., 1., 1.]), records=dict(scalar_pa=dict(sha256="e"*64)),
                    sources=dict(scalar_pa=str(root / "unavailable_field.pa"))) if static_mode is not None else None))
            if static_mode is None:
                trial_value["inputs"]["native_corridor_cache_manifest"] = file_record(Path(inputs["native_corridor_bank_cache_manifest"]))
            trial.write_text(json.dumps(trial_value)+"\n", encoding="utf-8")
            inputs["trial_materialization"] = str(trial.resolve())
            return inputs

        parent_inputs = materialize(parent)
        current_inputs = materialize(current)
        plan = {
            "role": "simion_single_wave_particle_batch_plan",
            "batches": [
                {"index": 1, "particle_id_min": 1, "particle_id_max": 1, "count": 1},
                {"index": 2, "particle_id_min": 2, "particle_id_max": 3, "count": 2},
            ],
        }
        plan_path = parent / "inputs" / "simion_execution_batch_plan.json"
        plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        parent_inputs["simion_execution_batch_plan"] = str(plan_path.resolve())
        parameters = {
            "execution_mode": "mrtof_native_corridor_bunch",
            "particle_count": 3,
            "launched_particle_count": 3,
        }
        parent_config = parent / "run_config.json"
        parent_config.write_text(
            json.dumps({"parameters": parameters, "inputs": parent_inputs}) + "\n",
            encoding="utf-8",
        )
        current_config = current / "run_config.json"
        current_config.write_text(
            json.dumps({"parameters": parameters, "inputs": current_inputs}) + "\n",
            encoding="utf-8",
        )
        complete = parent / "logs" / "native_two_prism_flight__batch01.log"
        complete.write_text(
            "MRTOF_EVENT terminal ion=1 splat=1 t_us=1\n"
            "status,Fly completed. 1 splats, 1.0 seconds\n"
            "IOB_FLIGHT: PASS iob=fixture.iob\n",
            encoding="utf-8",
        )
        partial = parent / "logs" / "native_two_prism_flight__batch02.log"
        partial.write_text("MRTOF_EVENT terminal ion=1 splat=1 t_us=2\n", encoding="utf-8")
        exits = [self._exit(parent, i) for i in (1, 2)]
        manifest_inputs = {role: file_record(Path(path)) for role, path in parent_inputs.items()}
        (parent / "run_manifest.json").write_text(
            json.dumps(
                {
                    "role": "simulation_run_manifest",
                    "run_id": "parent",
                    "status": "interrupted",
                    "run_config": {"sha256": file_sha256(parent_config)},
                    "inputs": manifest_inputs,
                    "outputs": [
                        {"path": str(complete), "sha256": file_sha256(complete)},
                        {"path": str(partial), "sha256": file_sha256(partial)},
                        *[file_record(path) for path in exits],
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return parent, current_config

    def test_reuses_complete_whole_mrtof_batches_with_new_run_transport_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root)
            plan = build_continuation_plan(
                predecessor_run_dir=parent,
                current_run_config=current,
                output_dir=root / "recovery",
            )
        self.assertEqual(plan["completed_particle_count"], 1)
        self.assertEqual(plan["replay_particle_count"], 2)
        self.assertEqual(
            [batch["action"] for batch in plan["batches"]],
            ["reuse", "replay"],
        )

    def test_published_batch_role_survives_retired_config_transport_locator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root)
            config_path, manifest_path = parent / "run_config.json", parent / "run_manifest.json"
            config = json.loads(config_path.read_text())
            config["inputs"]["simion_execution_batch_plan"] = str(root / "retired_alias/results/plan.json")
            config_path.write_text(json.dumps(config))
            manifest = json.loads(manifest_path.read_text())
            manifest["run_config"] = {"sha256": file_sha256(config_path)}
            manifest_path.write_text(json.dumps(manifest))
            plan = build_continuation_plan(predecessor_run_dir=parent,
                current_run_config=current, output_dir=root / "recovery")
            self.assertEqual(plan["batch_plan"]["path"],
                manifest["inputs"]["simion_execution_batch_plan"]["path"])
            self.assertEqual(plan["completed_particle_count"], 1)

    def test_published_batch_role_rejects_missing_or_damaged_record(self) -> None:
        for damage in ("missing_record", "missing_file", "bytes", "sha256"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root)
                manifest_path = parent / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text())
                record = manifest["inputs"]["simion_execution_batch_plan"]
                if damage == "missing_record":
                    del manifest["inputs"]["simion_execution_batch_plan"]
                elif damage == "missing_file":
                    Path(record["path"]).unlink()
                elif damage == "bytes":
                    record["bytes"] += 1
                else:
                    record["sha256"] = "0" * 64
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ContractError, "predecessor.*input"):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")

    def test_rejects_changed_frozen_physics_input(self) -> None:
        for role in ("operating_point_lua", "flight_program", "voltage_waveforms"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root)
                config = json.loads(current.read_text(encoding="utf-8"))
                Path(config["inputs"][role]).write_text('{"changed":true}\n', encoding="utf-8")
                with self.assertRaisesRegex(ContractError, "frozen cohort identity"):
                    build_continuation_plan(
                        predecessor_run_dir=parent,
                        current_run_config=current,
                        output_dir=root / "recovery",
                    )

    def test_static_reuses_complete_batches_without_native_assets(self) -> None:
        for mode in ("comsol_static_scalar_v", "native_static_pa"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root, static_mode=mode)
                plan = build_continuation_plan(predecessor_run_dir=parent,
                    current_run_config=current, output_dir=root / "recovery")
                self.assertEqual(plan["completed_particle_count"], 1)
                self.assertEqual(plan["replay_particle_count"], 2)

    def test_static_binding_change_rejects_old_traces(self) -> None:
        for mode in ("comsol_static_scalar_v", "native_static_pa"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root, static_mode=mode)
                config = json.loads(current.read_text(encoding="utf-8"))
                Path(config["inputs"]["static_field_binding"]).write_text(
                    '{"role":"static_field_binding","changed_voltage_identity":true}\n')
                with self.assertRaisesRegex(ContractError, "frozen cohort identity"):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")

    def _seal_oa_parent(self, parent: Path) -> None:
        config = parent / "run_config.json"
        manifest_path = parent / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["run_config"] = {"sha256": file_sha256(config)}
        manifest["inputs"] = {key: file_record(Path(value))
            for key, value in json.loads(config.read_text())["inputs"].items()}
        manifest["outputs"] = [file_record(path) for path in sorted((parent / "logs").glob("*.log"))]
        manifest["outputs"] += [file_record(path) for path in sorted((parent / "results/batches").glob("*/owner_exit.json"))]
        manifest_path.write_text(json.dumps(manifest)+"\n")

    def test_oa_zero_replay_retains_original_batch_plan_offsets_and_logs_without_pa(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root, static_mode="native_static_pa")
            (parent / "logs/native_two_prism_flight__batch02.log").write_text(
                "MRTOF_EVENT terminal ion=2 splat=1 t_us=1\n"
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=1\n"
                "status,Fly completed. 2 splats\nIOB_FLIGHT: PASS iob=source.iob\n")
            self._seal_oa_parent(parent)
            plan = build_continuation_plan(predecessor_run_dir=parent,
                current_run_config=current, output_dir=root / "recovery")
            self.assertEqual((plan["completed_particle_count"], plan["replay_particle_count"]), (3, 0))
            self.assertEqual([item["offset"] for item in plan["batches"]], [0, 1])
            self.assertEqual([Path(item["terminal_outputs"][0]["path"]).parent for item in plan["batches"]],
                             [parent / "logs", parent / "logs"])
            self.assertEqual(Path(plan["batch_plan"]["path"]), parent / "inputs/simion_execution_batch_plan.json")
            self.assertFalse((root / "unavailable_field.pa").exists())
            self.assertNotEqual(plan["frozen_trial_authority"]["sha256"], plan["current_materialization"]["sha256"])

    def test_oa_formal_recovery_keeps_first_and_replans_remaining(self):
        from common.simion.particle_batching import batch_plan_from_dispatch
        from common.simion.resource_scheduler import plan_simion_dispatch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root)
            request = {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
                       "particle_count": 3, "independent_particles": True, "trajectory_quality": 8}
            dispatch = plan_simion_dispatch(request, [], available_memory_bytes=10*1024**3,
                                           total_physical_memory_bytes=20*1024**3, logical_processors=8)
            dispatch_path = parent / "inputs/simion_repository_dispatch_plan.json"
            plan_path = parent / "inputs/simion_execution_batch_plan.json"
            dispatch_path.write_text(json.dumps(dispatch))
            plan_path.write_text(json.dumps(batch_plan_from_dispatch(dispatch)))
            config = json.loads((parent / "run_config.json").read_text())
            config["inputs"]["simion_repository_dispatch_plan"] = str(dispatch_path)
            (parent / "run_config.json").write_text(json.dumps(config))
            self._seal_oa_parent(parent)
            result = build_continuation_plan(predecessor_run_dir=parent, current_run_config=current,
                                             output_dir=root / "recovery")
            self.assertEqual([item["action"] for item in result["batches"]], ["reuse", "replay", "replay"])
            self.assertEqual((result["completed_particle_count"], result["replay_particle_count"]), (1, 2))
            recovered = json.loads(Path(result["recovered_formal_dispatch"]["path"]).read_text())
            self.assertTrue(recovered["estimation"]["recovered_missing_observation"])

    def test_oa_later_complete_batch_does_not_require_a_completed_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root)
            (parent / "logs/native_two_prism_flight__batch01.log").write_text("unfinished\n")
            (parent / "logs/native_two_prism_flight__batch02.log").write_text(
                "MRTOF_EVENT terminal ion=2 splat=1 t_us=1\n"
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=1\n"
                "status,Fly completed. 2 splats\nIOB_FLIGHT: PASS iob=source.iob\n")
            self._seal_oa_parent(parent)
            plan = build_continuation_plan(predecessor_run_dir=parent,
                current_run_config=current, output_dir=root / "recovery")
            self.assertEqual([item["action"] for item in plan["batches"]], ["replay", "reuse"])
            self.assertEqual((plan["completed_particle_count"], plan["replay_particle_count"]), (2, 1))

    def test_oa_scientific_drift_is_not_hidden_by_run_local_path_normalization(self):
        mutations = (
            lambda value: value.update(source_time_of_birth_us=1.),
            lambda value: value.update(source_clock_basis="another_epoch"),
            lambda value: value.update(source_expected_particle_ids=[1, 2, 4]),
            lambda value: value["source_cohort"].update(mother_particle_count=101),
            lambda value: value["source_cohort"].update(particle_states_sha256="0"*64),
            lambda value: value["inputs"].update(geometry_contract_sha256="0"*64),
            lambda value: value["resolved_iob_pose"].update(origins_mm=[[1, 0, 0]]),
            lambda value: value["trajectory_profile"].update(trajectory_quality=4),
            lambda value: value["field_binding"]["grid"].update(pitch_mm=[2., 1., 1.]),
            lambda value: value["field_binding"]["records"]["scalar_pa"].update(sha256="0"*64),
            lambda value: value.update(analyzer_electrode_voltages_v=[0., 11.]),
            lambda value: value.update(new_science_field="unknown changes cannot disappear"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root, static_mode="native_static_pa")
                config = json.loads(current.read_text())
                path = Path(config["inputs"]["trial_materialization"])
                value = json.loads(path.read_text())
                mutate(value)
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ContractError, "scientific identity"):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")

    def test_oa_all_direct_execution_input_changes_reject_old_batches(self):
        for role in REQUIRED_INPUT_ROLES:
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root)
                config = json.loads(current.read_text())
                Path(config["inputs"][role]).write_text("changed actual execution input\n")
                with self.assertRaisesRegex(ContractError, "frozen cohort identity"):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")

    def test_oa_complete_unsealed_or_tampered_log_cannot_be_reused(self):
        for change in ("unsealed", "tampered", "bad_native_terminal"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root)
                manifest_path = parent / "run_manifest.json"
                if change == "unsealed":
                    manifest = json.loads(manifest_path.read_text())
                    manifest["outputs"] = manifest["outputs"][1:]
                    manifest_path.write_text(json.dumps(manifest))
                else:
                    log = parent / "logs/native_two_prism_flight__batch01.log"
                    text = log.read_text()
                    log.write_text(text.replace("t_us=1", "t_us=9") if change == "tampered" else
                                   text.replace("terminal ion=1", "terminal ion=2"))
                with self.assertRaises(ContractError):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")

    def test_oa_next_recovery_reuses_only_its_direct_predecessors_bound_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, second_config = self._fixture(root)
            first = build_continuation_plan(predecessor_run_dir=original,
                current_run_config=second_config, output_dir=root / "first_plan")
            second = second_config.parent
            config = json.loads(second_config.read_text())
            config["inputs"]["simion_execution_batch_plan"] = first["batch_plan"]["path"]
            config["inputs"]["reused_batch_001_log"] = first["batches"][0]["terminal_outputs"][0]["path"]
            config["inputs"]["reused_batch_001_owner_exit"] = first["batches"][0]["terminal_outputs"][1]["path"]
            second_config.write_text(json.dumps(config))
            (second / "logs/native_two_prism_flight__batch02.log").write_text(
                "MRTOF_EVENT terminal ion=2 splat=1 t_us=1\n"
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=1\n"
                "status,Fly completed. 2 splats\nIOB_FLIGHT: PASS iob=replayed.iob\n")
            self._exit(second, 2)
            (second / "run_manifest.json").write_text(json.dumps(dict(
                role="simulation_run_manifest", run_id="second", status="failed",
                run_config=dict(sha256=file_sha256(second_config)),
                inputs={key: file_record(Path(value)) for key, value in config["inputs"].items()}, outputs=[])))
            self._seal_oa_parent(second)
            _, third_config = self._fixture(root / "third")
            # Only the second run's explicit inherited input seal is consumed.
            (original / "run_manifest.json").write_text("not an ancestor search source\n")
            next_plan = build_continuation_plan(predecessor_run_dir=second,
                current_run_config=third_config, output_dir=root / "next_plan")
            self.assertEqual((next_plan["completed_particle_count"], next_plan["replay_particle_count"]), (3, 0))
            self.assertEqual([Path(batch["terminal_outputs"][0]["path"]).parent for batch in next_plan["batches"]],
                             [original / "logs", second / "logs"])

    def test_oa_static_scalar_adapter_code_change_rejects_reuse(self):
        for mode in ("native_static_pa", "comsol_static_scalar_v"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root, static_mode=mode)
                config = json.loads(current.read_text())
                Path(config["inputs"]["scalar_field_adapter"]).write_text("changed field evaluator\n")
                with self.assertRaisesRegex(ContractError, "frozen cohort identity"):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")

    def test_oa_transport_record_must_point_to_its_actual_configured_input(self):
        for locator in ("priority_path", "priority_sha", "field_path", "cache_bytes"):
            mode = "native_static_pa" if locator == "field_path" else None
            with self.subTest(locator=locator), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, current = self._fixture(root, static_mode=mode)
                config = json.loads(current.read_text())
                path = Path(config["inputs"]["trial_materialization"])
                value = json.loads(path.read_text())
                if locator == "priority_path":
                    value["native_corridor_priority_contract"]["path"] = str(root / "different.json")
                elif locator == "priority_sha":
                    value["native_corridor_priority_contract"]["sha256"] = "0"*64
                elif locator == "field_path":
                    value["field_binding"]["path"] = str(root / "different.json")
                else:
                    value["inputs"]["native_corridor_cache_manifest"]["bytes"] += 1
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ContractError, "transport binding"):
                    build_continuation_plan(predecessor_run_dir=parent,
                        current_run_config=current, output_dir=root / "recovery")


if __name__ == "__main__":
    unittest.main()
