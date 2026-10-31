from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from common.simion.particle_batching import plan_single_wave_batches
from projects.single_reflection_oa_tof_mass_analyzer.analysis.optimize_reflectron_ring_voltages import render_lua_profile
from projects.single_reflection_oa_tof_mass_analyzer.workflows.reflectron_voltage_compensation import run_compensation as study


FIT = {"schema_version": 1, "stage1_count": 2, "stage2_count": 2,
       "stage1_ring_voltages_V": [100.0, 200.0], "stage2_ring_voltages_V": [300.0, 400.0],
       "fixed_endpoints_V": {}, "fit": {}}
CONTRACT = {"rings": {"stage1_count": 2, "stage2_count": 2}, "geometry_mm": {"L_stage1": 20.0, "L_stage2": 30.0},
            "electrodes_V": {"midgrid": 200.0, "backplate": 500.0}}


class ReflectronVoltageCompensationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, path: Path, value: dict) -> None:
        study._write_json(path, value)

    def terminal(self, run: Path, inputs: list[Path], outputs: list[Path]) -> None:
        self.write(run / "run_config.json", {"run_id": run.name, "mode": "reflectron_voltage_compensation"})
        self.write(run / "run_manifest.json", {"schema_version": 2, "role": "simulation_run_manifest", "project": study.PROJECT,
            "run_id": run.name, "mode": "reflectron_voltage_compensation", "status": "failed",
            "run_config": file_record(run / "run_config.json"), "inputs": {str(i): file_record(p) for i, p in enumerate(inputs)},
            "outputs": [file_record(p) for p in outputs]})

    def fixture(self, name: str) -> Path:
        run = self.root / name
        (run / "inputs").mkdir(parents=True)
        self.write(run / "inputs/candidate_resolved_geometry.json", CONTRACT)
        (run / "inputs/source.ion").write_text("\n".join(str(i) for i in range(1000))+"\n", encoding="ascii")
        builder = run / "inputs/code" / f"projects/{study.PROJECT}/simion/workbench/build_formal_iob.lua"
        builder.parent.mkdir(parents=True)
        builder.write_text("actual-builder", encoding="utf-8")
        assembly = run / "inputs/code/common/simion/assemble_native_fast_adjust_family.lua"
        assembly.parent.mkdir(parents=True)
        assembly.write_text("actual-assembly", encoding="utf-8")
        (run / "results").mkdir()
        (run / "logs").mkdir()
        (run / "results/axis_basis.csv").write_text("fixture", encoding="utf-8")
        source = self.root / "published.pa0"
        if not source.exists():
            source.write_bytes(b"native-source-bytes")
        plan = {"runtime_files": [], "producer": {"component_plan": {"components": [{"role": "reflectron", "identity": {"geometry": "fixture"}, "operating_voltages_v": {"1": 100}}]}},
                "source": file_record(run / "inputs/source.ion"), "simion_executable": {"path": "simion.exe", "sha256": "C"*64},
                "source_manifest": {"path": "source-manifest"},
                "trajectory_quality": 8, "regularization": 1e-4, "particle_count": 1000, "predecessor_manifest": None}
        self.write(run / "inputs/compensation_plan.json", plan)
        return run

    def fit(self, run: Path) -> dict:
        with patch.object(study, "_load_basis", return_value=([], [])), patch.object(study, "optimize", return_value=FIT), \
                patch.object(study, "render_program", return_value="science-program"):
            return study.fit_and_plan(run)

    def parent(self, complete: set[int]) -> Path:
        run = self.fixture("20261030_120000__sim__simion__compensation-parent")
        self.fit(run)
        partition = plan_single_wave_batches(1000, 5)
        outputs = []
        for label in study.LABELS:
            self.write(run / f"results/{label}.batch_plan.json", partition)
            # Materialize from the complete frozen partition, not a new bootstrap.
            dispatch = study._load(run / f"results/{label}.dispatch_plan.json")
            dispatch["waves"][0].update(batches=partition["batches"], batch_count=5, coverage="complete_population")
            self.write(run / f"results/{label}.dispatch_plan.json", dispatch)
            cases = study.materialize_batches(run, label)["batches"]
            outputs.append(run / f"results/{label}.batch_plan.json")
            for case in cases:
                if case["batch"]["index"] not in complete:
                    continue
                Path(case["stdout_path"]).write_text("status,Fly completed. 200 splats, 1 seconds\n", encoding="utf-8")
                study.complete_batch(run, label, case["batch"]["index"], {"completed": True, "exit_code": 0})
                outputs.extend([Path(case["stdout_path"]), run / f"results/native_batch_completion/{case['name']}.json"])
        self.terminal(run, [run / "inputs/flight_identity.json"], outputs)
        return run

    def child(self, parent: Path) -> Path:
        run = self.fixture("20261030_120001__sim__simion__compensation-recovery")
        plan = study._load(run / "inputs/compensation_plan.json")
        plan["predecessor_manifest"] = file_record(parent / "run_manifest.json")
        self.write(run / "inputs/compensation_plan.json", plan)
        return run

    def test_complete_units_reuse_without_native_or_runtime_materialization_and_parent_unchanged(self) -> None:
        parent = self.parent({1, 2, 3, 4, 5})
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        child = self.child(parent)
        with patch.object(study, "producer_specification") as native_prepare:
            result = self.fit(child)
            self.assertFalse(result["native_fly_required"])
            for label in study.LABELS:
                batches = study.materialize_batches(child, label)["batches"]
                self.assertEqual(len(batches), 5)
                self.assertTrue(all(c["reused"] for c in batches))
                self.assertEqual([c["batch"]["count"] for c in batches], [200]*5)
            native_prepare.assert_not_called()
        self.assertFalse((child / "simion").exists())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_partial_failed_parent_keeps_original_larger_units_and_completed_first_batch(self) -> None:
        parent = self.parent({1, 4})
        child = self.child(parent)
        result = self.fit(child)
        self.assertTrue(result["native_fly_required"])
        for mode in result["modes"]:
            self.assertEqual(mode["reused_batch_indices"], [1, 4])
            dispatch = study._load(Path(mode["dispatch_plan"]))
            self.assertTrue(dispatch["estimation"]["recovered_missing_observation"])
            self.assertEqual(dispatch["estimation"]["replay_batch_indices"], [2, 3, 5])
            batches = study.materialize_batches(child, mode["label"])["batches"]
            self.assertEqual([c["batch"]["index"] for c in batches if not c["reused"]], [2, 3, 5])
            self.assertEqual(sum(c["batch"]["count"] for c in batches), 1000)

    def rebind_parent(self, parent: Path) -> None:
        manifest = study._load(parent / "run_manifest.json")
        self.terminal(parent, [Path(r["path"]) for r in manifest["inputs"].values()],
                      [Path(r["path"]) for r in manifest["outputs"] if Path(r["path"]).is_file()])

    def test_recovery_after_first_batch_replan_failure_preserves_completed_prefix(self) -> None:
        parent = self.parent({1})
        path = parent / "results/baseline.batch_plan.json"
        original = study._load(path)
        self.write(path, dict(original, batches=original["batches"][:1], batch_count=1, coverage="formal_observation"))
        self.rebind_parent(parent)
        child = self.child(parent)
        self.fit(child)
        cases = study.materialize_batches(child, "baseline")["batches"]
        self.assertEqual(cases[0]["batch"], original["batches"][0])
        self.assertTrue(cases[0]["reused"])
        self.assertEqual([c["batch"]["index"] for c in cases if not c["reused"]], [2, 3, 4, 5])
        self.assertEqual(sum(c["batch"]["count"] for c in cases), 1000)

    def test_arms_not_started_before_failure_get_fresh_plans_without_losing_other_units(self) -> None:
        parent = self.parent({1})
        (parent / "results/compensated.batch_plan.json").unlink()
        (parent / "results/native_batch_completion/compensated__0001.json").unlink()
        self.rebind_parent(parent)
        child = self.child(parent)
        result = self.fit(child)
        modes = {m["label"]: m for m in result["modes"]}
        self.assertEqual(modes["baseline"]["reused_batch_indices"], [1])
        self.assertEqual(modes["compensated"]["reused_batch_indices"], [])
        self.assertFalse(modes["compensated"]["all_reused"])
        dispatch = study._load(Path(modes["compensated"]["dispatch_plan"]))
        self.assertEqual(dispatch["estimation"]["kind"], "formal_first_batch_observation")

    def test_missing_or_tampered_completion_is_not_silently_reused(self) -> None:
        parent = self.parent({1})
        log = parent / "logs/simion__batch__baseline__0001.stdout.log"
        log.write_text(log.read_text()+"tamper", encoding="utf-8")
        child = self.child(parent)
        with self.assertRaisesRegex(ValueError, "hash differs"):
            self.fit(child)

    def test_changed_actual_fly_input_rejects_reuse_before_native(self) -> None:
        parent = self.parent({1})
        child = self.child(parent)
        plan = study._load(child / "inputs/compensation_plan.json")
        plan["trajectory_quality"] = 9
        self.write(child / "inputs/compensation_plan.json", plan)
        with self.assertRaisesRegex(ValueError, "Fly inputs differ"):
            self.fit(child)
        self.assertFalse((child / "simion").exists())

    def test_completion_requires_observed_exit_and_exact_original_count(self) -> None:
        run = self.fixture("20261030_120002__sim__simion__compensation-completion")
        self.fit(run)
        cases = study.materialize_batches(run, "baseline")["batches"]
        case = cases[0]
        with self.assertRaisesRegex(ValueError, "natural exit"):
            study.complete_batch(run, "baseline", 1, {"completed": False, "exit_code": 0})
        with self.assertRaisesRegex(ValueError, "natural exit"):
            study.complete_batch(run, "baseline", 1, {"completed": True, "exit_code": 3})
        Path(case["stdout_path"]).parent.mkdir(exist_ok=True)
        Path(case["stdout_path"]).write_text("status,Fly completed. 99 splats, 1 seconds\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "whole batch"):
            study.complete_batch(run, "baseline", 1, {"completed": True, "exit_code": 0})

    def published_source(self) -> tuple[Path, Path]:
        case = self.root / "20261030_120004__sim__simion__compensation-source"
        runtime = case / "simion"
        runtime.mkdir(parents=True)
        self.write(case / "contracts/candidate_resolved_geometry.json", CONTRACT)
        source = runtime / "oatof_comsol_524amu_gaussian_N100.ion"
        source.write_text("0,524,1,0,0,0,0,0,5,1,0\n"*100, encoding="ascii")
        names = ("oatof_ideal_grounded.iob", "oatof_ideal_grounded.con", "oatof_ideal_grounded.fly2", "oatof_resolved.lua",
                 "reflectron.pa0", "accelerator.pa0", "flight_tube_ground.pa0", "detector_ground.pa0")
        for name in names:
            (runtime / name).write_bytes(b"software-fixture")
        self.write(runtime / "resolved_geometry.json", CONTRACT)
        self.write(case / "logs/build_completion.json", {"role": "oatof_component_build_completion", "exception": None,
            "operations": [{"observation": {"exit_confirmed": True, "returncode": 0}}]})
        self.write(runtime / "simion_runtime_receipt.json", {"role": "oatof_simion_private_runtime", "status": "verified",
            "canonical_iob_verified": True, "files": [file_record(runtime / name) for name in names if ".pa" in name]})
        # An unrelated report is neither a native input nor an identity dependency.
        (runtime / "unconsumed-report.txt").write_text("report", encoding="utf-8")
        self.terminal(case, [], [p for p in case.rglob("*") if p.is_file()])
        executable = self.root / "simion.exe"
        executable.write_bytes(b"software-fixture-executable")
        return case, executable

    def test_inspect_consumes_only_selected_metadata_and_does_not_hash_published_pa(self) -> None:
        case, executable = self.published_source()
        original = study.verify_record
        calls = []
        def check(name, record, **kwargs):
            path = Path(record["path"])
            self.assertNotIn(".pa", path.name)
            calls.append(path.name)
            return original(name, record, **kwargs)
        with patch.object(study, "verify_record", side_effect=check):
            plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        self.assertEqual(plan["particle_count"], 100)
        self.assertEqual(len([r for r in plan["runtime_files"] if r["pa"]]), 4)
        self.assertNotIn("unconsumed-report.txt", calls)
        self.assertNotIn("unconsumed-report.txt", [r["relative_path"] for r in plan["runtime_files"]])

    def test_explicit_numerics_uses_manifest_mode_independent_of_request_directory(self) -> None:
        case, executable = self.published_source()
        mode = case / "inputs/mode.json"
        self.write(mode, {"science": "original-frozen-mode"})
        self.write(case / "contracts/candidate_baseline.json", {"baseline": "original"})
        contract = {**CONTRACT, "inputs": {"mode_sha256": file_record(mode)["sha256"]}}
        self.write(case / "contracts/candidate_resolved_geometry.json", contract)
        self.write(case / "simion/resolved_geometry.json", contract)
        outputs = [p for p in case.rglob("*") if p.is_file() and p.name not in {"run_manifest.json", "run_config.json"}]
        self.terminal(case, [], outputs)
        manifest = study._load(case / "run_manifest.json")
        manifest["inputs"]["mode"] = file_record(mode)
        self.write(case / "run_manifest.json", manifest)
        for directory in ("request-a", "request-b"):
            numerics = self.root / directory / "numerics.json"
            self.write(numerics, {"numerics": "same-explicit-request"})
            self.write(numerics.with_name("candidate_science_mode.json"), {"science": "unrelated-neighbor"})
            with patch.object(study, "resolve_contract_documents", side_effect=RuntimeError("resolved frozen mode")) as resolve:
                with self.assertRaisesRegex(RuntimeError, "resolved frozen mode"):
                    study.inspect_source(case, executable, 8, 1e-4, particle_count=100, numerics_path=numerics)
            self.assertEqual(resolve.call_args.args[1], {"science": "original-frozen-mode"})
        mode.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, "byte count changed"):
            study.inspect_source(case, executable, 8, 1e-4, particle_count=100, numerics_path=numerics)

    def test_published_native_family_is_rejected_before_native_or_capacity_entry(self) -> None:
        case, executable = self.published_source()
        response = case / "simion/reflectron.pa1"
        response.write_bytes(b"published-native-family")
        receipt_path = case / "simion/simion_runtime_receipt.json"
        receipt = study._load(receipt_path)
        receipt["files"].append(file_record(response))
        self.write(receipt_path, receipt)
        self.terminal(case, [], [p for p in case.rglob("*") if p.is_file() and p.name not in {"run_manifest.json", "run_config.json"}])
        before = {p: p.read_bytes() for p in case.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "standalone provider"):
            study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_frozen_scientific_module_imports_its_real_dependencies_without_native_or_pa_copy(self) -> None:
        case, executable = self.published_source()
        plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        run = self.root / "project/runs/20261030_120006__sim__simion__compensation-frozen"
        (run / "inputs").mkdir(parents=True)
        self.write(run / "inputs/compensation_plan.json", plan)
        result = study.freeze_inputs(run)
        code = Path(result["frozen_code_root"])
        command = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import "+study.MODULE+
                   " as m;assert Path(m.__file__).is_relative_to(Path(sys.argv[1]));"
                   "assert m.export_specification(Path(sys.argv[2]))['name']=='reflectron_axis_basis'")
        subprocess.run([sys.executable, "-B", "-c", command, str(code), str(run)], cwd=code, timeout=60,
                       check=True, capture_output=True, text=True, encoding="utf-8")
        self.assertTrue(result["basis_export_required"])
        self.assertFalse((run / "simion").exists())

    def test_formal_first_batch_source_is_retained_after_adaptive_partition(self) -> None:
        from common.simion.resource_scheduler import plan_adaptive_followup
        run = self.fixture("20261030_120005__sim__simion__compensation-first")
        self.fit(run)
        first = study.materialize_batches(run, "baseline")["batches"][0]
        ion = Path(first["ion"])
        allocation = first["argument_list"][first["argument_list"].index("--default-num-particles") + 1]
        self.assertGreaterEqual(int(allocation), 100)
        self.assertEqual(len(ion.read_text(encoding="ascii").splitlines()), first["batch"]["count"])
        before = (ion.read_bytes(), ion.stat().st_mtime_ns)
        dispatch = study._load(run / "results/baseline.dispatch_plan.json")
        followup = plan_adaptive_followup(dispatch, 20*1024**3, first_batch_completed=True)
        study._write_json(run / "results/baseline.dispatch_plan.json", followup)
        cases = study.materialize_batches(run, "baseline")["batches"]
        self.assertEqual(cases[0]["batch"], first["batch"])
        self.assertEqual((ion.read_bytes(), ion.stat().st_mtime_ns), before)
        self.assertEqual(sum(c["batch"]["count"] for c in cases), 1000)

    def test_predecessor_bytecode_evidence_is_derived_separately_from_current_code(self) -> None:
        import py_compile
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import verify_candidate_source_closure

        case, executable = self.published_source()
        plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        parent = self.root / "parent"
        self.write(parent / "inputs/compensation_plan.json", plan)
        study.freeze_inputs(parent)
        source = parent / "inputs/code/common/contracts/file_identity.py"
        py_compile.compile(str(source), doraise=True)
        self.terminal(parent, [p for p in (parent / "inputs").rglob("*") if p.is_file()], [])
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "extra files"):
            verify_candidate_source_closure(study._load(parent / "inputs/source_closure.json"))
        child = self.root / "child"
        self.write(child / "inputs/compensation_plan.json", {**plan, "predecessor_manifest": file_record(parent / "run_manifest.json")})
        study.freeze_inputs(child)
        evidence = child / "inputs/predecessor_source_closure"
        derived = study._load(evidence / "source_closure.json")
        verify_candidate_source_closure(derived)
        verify_candidate_source_closure(study._load(child / "inputs/source_closure.json"))
        self.assertEqual(len(study._load(evidence / "derivation.json")["validated_bytecode"]), 1)
        self.assertEqual(Path(derived["code_root"]), evidence / "code")
        self.assertFalse(list((evidence / "code").rglob("*.pyc")))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_analysis_failure_leaves_complete_native_units_reusable(self) -> None:
        parent = self.parent({1, 2, 3, 4, 5})
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        with patch.object(study, "analyze_simion_log", side_effect=ValueError("analysis failure")):
            with self.assertRaisesRegex(ValueError, "analysis failure"):
                study.analyze(parent)
        child = self.child(parent)
        result = self.fit(child)
        self.assertFalse(result["native_fly_required"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_n100_first_batch_keeps_ten_source_rows_with_supported_native_capacity(self) -> None:
        run = self.fixture("20261030_120009__sim__simion__compensation-small-first")
        plan = study._plan(run)
        plan["particle_count"] = 100
        self.write(run / "inputs/compensation_plan.json", plan)
        source = run / "inputs/source.ion"
        source.write_text("\n".join(source.read_text(encoding="ascii").splitlines()[:100])+"\n", encoding="ascii")
        self.fit(run)
        first = study.materialize_batches(run, "baseline")["batches"][0]
        self.assertEqual(first["batch"]["count"], 10)
        self.assertEqual(len(Path(first["ion"]).read_text(encoding="ascii").splitlines()), 10)
        arguments = first["argument_list"]
        self.assertEqual(arguments[arguments.index("--default-num-particles")+1], "100")

    def test_missing_case_fails_before_private_execution(self) -> None:
        with patch.object(sys, "argv", ["run_compensation", "--case-dir", str(self.root)]), patch.object(study.subprocess, "run") as native:
            with self.assertRaises(FileNotFoundError):
                study.main()
        native.assert_not_called()

    def test_help_does_not_start_a_process(self) -> None:
        with patch.object(sys, "argv", ["run_compensation", "--help"]), patch.object(study.subprocess, "run") as native:
            with self.assertRaises(SystemExit) as exited:
                study.main()
        self.assertEqual(exited.exception.code, 0)
        native.assert_not_called()

    def test_profile_renderer_preserves_scientific_counts_and_voltages(self) -> None:
        profile = render_lua_profile(FIT)
        self.assertIn("stage1_count = 2", profile)
        self.assertIn("stage1_ring_voltages_V = {100, 200}", profile)
        self.assertIn("stage2_ring_voltages_V = {300, 400}", profile)

    def test_safe_producer_spec_uses_actual_owner_session_original_ion_and_same_host_parameters(self) -> None:
        run = self.fixture("20261030_120007__sim__simion__compensation-producer")
        plan = study._plan(run)
        plan["producer"]["source_gui_seed"] = 17
        plan["protected_cache_keys"] = ["ABC"]
        self.write(run / "inputs/compensation_plan.json", plan)
        session = run / "results/capacity.json"
        self.write(session, {"schema_version": 1, "role": "artifact_workflow_capacity_session", "status": "active",
                             "protected_paths": [str(run)], "protected_cache_keys": ["abc"]})
        with patch.object(study, "prepare_consumers") as prepare:
            specification = study.producer_specification(run, session, "A"*64)
        prepare.assert_called_once_with(run / "inputs/candidate_resolved_geometry.json", run / "inputs/producer_text", particle_source_seed=17)
        self.assertEqual(specification["parameters"]["SourceIonPath"], str(run / "inputs/source.ion"))
        self.assertEqual(specification["parameters"]["CapacitySessionPath"], str(session.resolve()))
        self.assertTrue(specification["parameters"]["DeferRunFinalization"])
        self.assertTrue(specification["script_path"].endswith("build_formal_delivery.ps1"))
        self.write(session, {"role": "artifact_workflow_capacity_session", "status": "active", "protected_paths": [], "protected_cache_keys": ["abc"]})
        with patch.object(study, "prepare_consumers") as prepare, self.assertRaisesRegex(ValueError, "protected capacity"):
            study.producer_specification(run, session, "A"*64)
        prepare.assert_not_called()

    def test_safe_producer_completion_binds_actual_controls_original_source_and_writer(self) -> None:
        run = self.fixture("20261030_120008__sim__simion__compensation-producer-completion")
        self.fit(run)
        plan = study._plan(run)
        plan["producer"]["component_plan"]["components"][0]["cacheable"] = False
        self.write(run / "inputs/compensation_plan.json", plan)
        runtime = run / "simion"
        runtime.mkdir()
        iob = runtime / "oatof_ideal_grounded.iob"
        iob.write_bytes(b"producer-verified-original-template-new-field-bindings")
        iob.with_suffix(".lua").write_bytes((run / "inputs/oatof_ideal_grounded.lua").read_bytes())
        ion = runtime / "oatof_comsol_524amu_gaussian_N1000.ion"
        ion.write_bytes((run / "inputs/source.ion").read_bytes())
        self.write(runtime / "simion_runtime_receipt.json", {"role": "oatof_simion_private_runtime", "status": "verified",
            "run_id": run.name, "context_sha256": "A"*64, "canonical_iob_verified": True,
            "published_native_members_opened": False, "iob": {"path": str(iob)}, "source_ion_reused": True,
            "source_ion": file_record(ion), "components": [{"role": "reflectron", "source": "fresh_frozen_fractional_gem"}]})
        managed = {"schema_version": 1, "role": "repository_managed_python_completion", "exit_code": 0,
            "worker_process_id": 42, "worker_started_at_utc_ticks": 77,
            **{k: True for k in ("ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed", "stdout_drained", "stderr_drained")}}
        self.write(run / "results/field_provider_completion.json", {"schema_version": 1, "role": "oatof_component_build_completion",
            "run_id": run.name, "context_sha256": "A"*64, "exception": None,
            "operations": [{"operation_id": "build", "observation": {"exit_confirmed": True, "returncode": 0}, "managed_process_completion": managed}]})
        result = study.producer_completion(run, "A"*64)
        self.assertIsNone(result["failure_reason"])
        self.assertTrue(result["writers_stopped"])
        self.assertTrue(result["iob_ready"])
        self.assertEqual(result["control_binding"], {"iob_path": str(iob), "program_path": str(iob.with_suffix(".lua")), "source_ion_path": str(run / "inputs/source.ion")})
        self.assertEqual(result["writer_completion"]["operations"][0]["observation"]["process_id"], 42)
        self.assertEqual((runtime / "reflectron_voltage_profile.lua").read_bytes(), (run / "inputs/reflectron_voltage_profile.lua").read_bytes())
        iob.with_suffix(".lua").write_text("wrong-program", encoding="utf-8")
        failed = study.producer_completion(run, "A"*64)
        self.assertTrue(failed["writers_stopped"])
        self.assertFalse(failed["iob_ready"])
        self.assertIn("Program/profile differs", failed["failure_reason"])

    def test_missing_producer_completion_keeps_writer_unknown_without_iob_claim(self) -> None:
        run = self.fixture("20261030_120009__sim__simion__compensation-producer-unknown")
        result = study.producer_completion(run, "A"*64)
        self.assertFalse(result["writers_stopped"])
        self.assertFalse(result["iob_ready"])
        self.assertFalse(result["writer_completion"]["operations"][0]["observation"]["exit_confirmed"])


if __name__ == "__main__":
    unittest.main()
