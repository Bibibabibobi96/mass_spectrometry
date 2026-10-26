from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation import (
    REQUIRED_INPUT_ROLES,
    build_continuation_plan,
    build_prepared_joint_whole_unit_plan,
)
from common.contracts.write_run_manifest import file_record


class MrtofBatchContinuationTests(unittest.TestCase):
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
        self.assertEqual(len(plan["units"][0]["terminal_outputs"]), 3)
        self.assertEqual(plan["units"][1]["terminal_outputs"], [])
        self.assertTrue(plan["dispatch_plan"]["path"].endswith("simion_repository_dispatch_plan.json"))

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
                        "outputs": [file_record(path) for path in (replay_fly, replay_receipt, replay_log)],
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
            second_config.write_text(json.dumps(config))
            (second / "logs/native_two_prism_flight__batch02.log").write_text(
                "MRTOF_EVENT terminal ion=2 splat=1 t_us=1\n"
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=1\n"
                "status,Fly completed. 2 splats\nIOB_FLIGHT: PASS iob=replayed.iob\n")
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
