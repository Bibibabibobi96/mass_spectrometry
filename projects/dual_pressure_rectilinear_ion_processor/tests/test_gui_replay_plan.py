"""Synthetic replay planning/identity tests; no PA solve or physical evidence."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis.gui_replay import prepare_replay, finalize_replay
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import (
    to_local_position, to_local_vector, to_project_position, to_project_vector,
    transform_from_config,
)


class CoordinateTests(unittest.TestCase):
    """Exact frame contracts; these tests do not provide native field evidence."""

    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config/coordinate_transform.json"
        self.config = {"coordinate_transform": json.loads(path.read_text())}

    def test_legacy_identity(self) -> None:
        self.assertEqual(to_project_position({}, (1, 2, 3)), (1, 2, 3))
        self.assertEqual(to_local_vector({}, (1, 2, 3)), (1, 2, 3))

    def test_native_origin(self) -> None:
        self.assertEqual(to_project_position(self.config, (-1, -4, -4)), (4, -1, 13.8))

    def test_exit_plane(self) -> None:
        self.assertEqual(to_project_position(self.config, (170, 9.8, 0)), (0, 170, 0))

    def test_slow_axis(self) -> None:
        self.assertEqual(to_project_vector(self.config, (1, 0, 0)), (0, 1, 0))

    def test_acceleration_axis(self) -> None:
        self.assertEqual(to_project_vector(self.config, (0, 1, 0)), (0, 0, -1))

    def test_transverse_axis(self) -> None:
        self.assertEqual(to_project_vector(self.config, (0, 0, 1)), (-1, 0, 0))

    def test_position_inverse(self) -> None:
        original = (123.5, 2.25, -0.4)
        for left, right in zip(to_local_position(self.config, to_project_position(self.config, original)), original):
            self.assertAlmostEqual(left, right)

    def test_vector_inverse_without_translation(self) -> None:
        self.assertEqual(to_local_vector(self.config, to_project_vector(self.config, (2, 3, 4))), (2, 3, 4))
        self.assertEqual(to_project_vector(self.config, (0, 0, 0)), (0, 0, 0))

    def test_source_frame_rejected(self) -> None:
        self.config["baseline"] = {"clock": {"frame_id": "other"}}
        with self.assertRaisesRegex(ValueError, "source frame"):
            transform_from_config(self.config)

    def test_improper_rotation_rejected(self) -> None:
        self.config["coordinate_transform"]["rotation"] = [[1, 0, 0], [0, 1, 0], [0, 0, -1]]
        with self.assertRaisesRegex(ValueError, "right handed"):
            transform_from_config(self.config)


class GuiReplayPlanTests(unittest.TestCase):
    """Use tiny fake PA bytes exclusively to test frozen file identity mechanics."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ion_processor_replay_plan_")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.baseline, self.run = root / "baseline", root / "replay"
        for base in (self.baseline, self.run):
            for sub in ("inputs", "simion", "logs", "results"):
                (base / sub).mkdir(parents=True, exist_ok=True)
            (base / "run_config.json").write_text('{"inputs":{}}', encoding="utf-8")
        for suffix in ["#", *map(str, range(16)), "-surf"]:
            (self.baseline / "simion" / ("processor.pa" + suffix)).write_bytes(b"synthetic-test-not-a-real-pa")
        for name in ("frozen_config.lua", "collision_hs1.lua", "source_states.lua", "native_drive.lua", "simion_rf_drive.lua", "processor.fly2", "processor.lua"):
            (self.baseline / "simion" / name).write_text("-- synthetic frozen input", encoding="utf-8")
        config = {"source_profile": "functional", "native_projection": {"origin_mm": [-1, -4, -4]}, "numerics": {"seed": 42, "trajectory_quality": 0}}
        (self.baseline / "inputs/resolved_model.json").write_text(json.dumps(config), encoding="utf-8")
        (self.baseline / "summary.json").write_text(json.dumps({"role": "ion_processor_functional_summary", "status": "functional_incomplete", "source_profile": "functional"}), encoding="utf-8")
        (self.baseline / "logs/flight.log").write_text("ION_PROCESSOR_END\n", encoding="utf-8")
        table = "particle_id,event,t_us,x_mm\n1,source,0,1\n1,terminal,1,2\n"
        for relative in ("simion/events.csv", "simion/samples.csv", "results/particle_state.csv"):
            (self.baseline / relative).write_text(table, encoding="utf-8")
        (self.baseline / "simion/samples.csv").write_text("particle_id,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n1,0,1,0,0,1,0,0\n1,1,2,0,0,1,0,0\n", encoding="utf-8")
        self.publish_manifest()

    def publish_manifest(self) -> None:
        records = [file_record(p) for p in self.baseline.rglob("*") if p.is_file() and p.name != "run_manifest.json"]
        (self.baseline / "run_manifest.json").write_text(json.dumps({"project": "dual_pressure_rectilinear_ion_processor", "status": "failed", "inputs": {}, "outputs": records}), encoding="utf-8")

    def test_prepare_isolated_inputs_and_pa_references(self) -> None:
        original = (self.baseline / "simion/processor.pa0").read_bytes()
        plan = prepare_replay(self.run, self.baseline)
        self.assertEqual(len(plan["native_pa_records"]), 18)
        self.assertFalse(plan["gui_manual_fly_completed"])
        self.assertEqual((self.run / "simion/processor.pa0").read_bytes(), original)
        builder = (self.run / "simion/build_gui_workbench.lua").read_text(encoding="utf-8")
        self.assertNotIn("pa:save", builder)
        self.assertIn("load_particles", builder)
        self.assertIn("debug.getinfo", builder)
        self.assertNotIn("pa:fast_adjust", builder)
        self.assertEqual(len(plan["local_native_pa_records"]), 17)
        resolved = json.loads((self.run / "inputs/resolved_model.json").read_text())
        self.assertEqual(Path(resolved["native_field"]["directory"]), self.run / "simion")
        self.assertIn(str(self.run / "simion").replace("\\", "\\\\"), (self.run / "simion/frozen_config.lua").read_text())
        self.assertNotIn("wb:save('processor.iob')", builder)
        self.assertIn("wb:save(directory..'processor.iob')", builder)
        self.assertIn("wb:load_particles(directory..'processor.fly2')", builder)
        self.assertEqual((self.run / "simion/source_states.lua").read_bytes(), (self.baseline / "simion/source_states.lua").read_bytes())
        self.assertEqual((self.baseline / "simion/processor.pa0").read_bytes(), original)
        self.assertEqual((self.run / "simion/processor.lua").read_bytes(), (self.baseline / "simion/processor.lua").read_bytes())

    def test_modified_baseline_or_missing_completion_rejected(self) -> None:
        pa = self.baseline / "simion/processor.pa0"
        pa.write_bytes(b"tampered")
        with self.assertRaises(AssertionError):
            prepare_replay(self.run, self.baseline)
        self.publish_manifest()
        (self.baseline / "logs/flight.log").write_text("not complete", encoding="utf-8")
        self.publish_manifest()
        with self.assertRaisesRegex(ValueError, "sentinel"):
            prepare_replay(self.run, self.baseline)

    def test_local_basis_mutation_rejected_before_analysis(self) -> None:
        prepare_replay(self.run, self.baseline)
        (self.run / "simion/processor.pa7").write_bytes(b"changed GUI basis")
        with self.assertRaises(AssertionError):
            finalize_replay(self.run)

    def test_source_mutation_rejected_after_prepare(self) -> None:
        prepare_replay(self.run, self.baseline)
        (self.baseline / "simion/processor.pa0").write_bytes(b"changed source")
        with self.assertRaises(AssertionError):
            finalize_replay(self.run)

    def test_local_pa0_mutation_is_explicit_and_source_stays_intact(self) -> None:
        source = (self.baseline / "simion/processor.pa0").read_bytes()
        prepare_replay(self.run, self.baseline)
        (self.run / "simion/processor.pa0").write_bytes(b"GUI saved adjusted initial state")
        for relative in ("simion/events.csv", "simion/samples.csv", "results/particle_state.csv"):
            (self.run / relative).write_bytes((self.baseline / relative).read_bytes())
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.functional.analyze", return_value={"status": "functional_incomplete", "source_profile": "functional"}):
            result = finalize_replay(self.run)
        self.assertTrue(result["gui_pa0_changed"])
        self.assertTrue(result["local_immutable_basis_verified"])
        self.assertEqual((self.baseline / "simion/processor.pa0").read_bytes(), source)
        registered = json.loads((self.run / "run_config.json").read_text())["inputs"]
        self.assertNotIn(str(self.run / "simion/processor.pa0"), registered.values())

    def test_finalize_compares_every_table_and_does_not_claim_manual_gui(self) -> None:
        prepare_replay(self.run, self.baseline)
        for relative in ("simion/events.csv", "simion/samples.csv", "results/particle_state.csv"):
            (self.run / relative).write_bytes((self.baseline / relative).read_bytes())
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.functional.analyze", return_value={"status": "functional_incomplete", "source_profile": "functional"}):
            result = finalize_replay(self.run)
            self.assertTrue(result["numerical_equivalence"])
            self.assertFalse(result["gui_visual_review"])
            self.assertEqual(result["comparison_scope"], "headless_replay_vs_baseline")
            (self.run / "simion/events.csv").write_text("particle_id,event,t_us,x_mm\n1,source,0,1\n1,terminal,1,2.1\n", encoding="utf-8")
            result = finalize_replay(self.run)
            self.assertFalse(result["numerical_equivalence"])
            self.assertAlmostEqual(result["raw_events"]["max_absolute_difference"]["x_mm"], 0.1)
            self.assertTrue(result["canonical_particle_state"]["passed"])

    def test_exploration_identity_preserved_without_functional_promotion(self) -> None:
        config_path = self.baseline / "inputs/resolved_model.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["source_profile"] = "exploration"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        summary_path = self.baseline / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.update(source_profile="exploration", status="exploration_incomplete")
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        self.publish_manifest()
        plan = prepare_replay(self.run, self.baseline)
        self.assertEqual(plan["baseline_evidence_scope"], "exploration_baseline")
        self.assertEqual(plan["source_profile"], "exploration")
        for relative in ("simion/events.csv", "simion/samples.csv", "results/particle_state.csv"):
            (self.run / relative).write_bytes((self.baseline / relative).read_bytes())
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.functional.analyze", return_value={"status": "exploration_pass", "source_profile": "exploration"}):
            result = finalize_replay(self.run)
        self.assertEqual(result["qualification"], "unqualified_exploration_replay_no_Candidate_or_Formal")
        self.assertEqual(result["measured_functional_status"], "exploration_pass")
        self.assertFalse(result["gui_visual_review"])
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.functional.analyze", return_value={"status": "functional_pass", "source_profile": "exploration"}):
            with self.assertRaisesRegex(ValueError, "upgrade"):
                finalize_replay(self.run)

    def test_recorded_samples_change_breaks_replay_equivalence(self) -> None:
        prepare_replay(self.run, self.baseline)
        for relative in ("simion/events.csv", "simion/samples.csv", "results/particle_state.csv"):
            (self.run / relative).write_bytes((self.baseline / relative).read_bytes())
        (self.run / "simion/samples.csv").write_text("particle_id,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n1,0,1,0,0,1,0,0\n1,1,2.25,0,0,1,0,0\n", encoding="utf-8")
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.functional.analyze", return_value={"status": "functional_incomplete", "source_profile": "functional"}):
            result = finalize_replay(self.run)
        self.assertFalse(result["numerical_equivalence"])
        self.assertFalse(result["sampled_trajectory"]["passed"])
        self.assertTrue(result["raw_events"]["passed"])
        self.assertTrue(result["canonical_particle_state"]["passed"])
        self.assertEqual(result["sampled_trajectory"]["max_absolute_difference"]["x_mm"], 0.25)
        self.assertIn("not_every_integration_step", result["comparison_coverage"])

    def test_wrapper_identity_uses_final_runtime_bytes(self) -> None:
        current_runtime = Path(__file__).resolve().parents[1] / "simion/runtime.lua"
        (self.baseline / "simion/processor.lua").write_bytes(current_runtime.read_bytes())
        self.publish_manifest()
        plan = prepare_replay(self.run, self.baseline)
        self.assertFalse(plan["runtime_wrapper_changed"])
        self.assertIn("identical", plan["wrapper_difference"])
        config = json.loads((self.run / "run_config.json").read_text(encoding="utf-8"))
        self.assertFalse(config["parameters"]["runtime_wrapper_changed"])
        plan = prepare_replay(self.run, self.baseline, 2)
        self.assertTrue(plan["runtime_wrapper_changed"])
        self.assertNotEqual(plan["baseline_runtime_record"]["sha256"], plan["replay_runtime_record"]["sha256"])
        config = json.loads((self.run / "run_config.json").read_text(encoding="utf-8"))
        self.assertTrue(config["parameters"]["runtime_wrapper_changed"])
        self.assertIn("repeat-Fly orchestration only", plan["wrapper_difference"])

    def test_workspace_runtime_change_cannot_affect_frozen_replay(self) -> None:
        # No worktree mutation is needed: interpose the file copy boundary and
        # prove that the workspace runtime is never requested as an input.
        import shutil as copy_module
        original_copy = copy_module.copyfile
        workspace_runtime = Path(__file__).resolve().parents[1] / "simion/runtime.lua"
        def reject_worktree_runtime(source, target, **kwargs):
            if Path(source).resolve() == workspace_runtime.resolve():
                raise AssertionError("working-tree runtime must not affect replay")
            return original_copy(source, target, **kwargs)
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.gui_replay.shutil.copyfile", side_effect=reject_worktree_runtime):
            plan = prepare_replay(self.run, self.baseline)
        self.assertFalse(plan["runtime_wrapper_changed"])
        self.assertEqual(plan["runtime_source_policy"], "baseline_exact_copy")
        self.assertEqual(plan["baseline_runtime_record"]["sha256"], plan["replay_runtime_record"]["sha256"])
        self.assertEqual((self.run / "simion/processor.lua").read_bytes(), b"-- synthetic frozen input")

    def test_optional_frozen_field_diagnostics_copied_without_new_solve(self) -> None:
        (self.baseline/"inputs/field_diagnostics.json").write_text('{"synthetic_test":true}',encoding="utf-8")
        for name in ("native_field_samples.csv","native_potential_audit.csv"):
            (self.baseline/"simion"/name).write_text("test_value\n1\n",encoding="utf-8")
        self.publish_manifest()
        plan=prepare_replay(self.run,self.baseline)
        self.assertEqual(len(plan["field_diagnostics_source_records"]),2)
        for name in ("native_field_samples.csv","native_potential_audit.csv"):
            self.assertEqual((self.run/"simion"/name).read_bytes(),(self.baseline/"simion"/name).read_bytes())
        config=json.loads((self.run/"run_config.json").read_text(encoding="utf-8"))
        self.assertIn(str(self.run/"simion/native_field_samples.csv"),config["inputs"].values())
        manifest_path=self.baseline/"run_manifest.json"
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["outputs"]=[record for record in manifest["outputs"] if not record["path"].endswith("native_potential_audit.csv")]
        manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"manifest-bound output"):
            prepare_replay(self.run,self.baseline)

    def test_invalid_repeat_count_rejected(self) -> None:
        for count in (0, 3, True, 1.0):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "repeat_fly_count"):
                    prepare_replay(self.run, self.baseline, count)

    def test_repeat_orchestration_snapshots_each_complete_stub_fly(self) -> None:
        lua = shutil.which("lua") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe")
        if not Path(lua).is_file():
            self.skipTest("ordinary Lua interpreter unavailable")
        plan = prepare_replay(self.run, self.baseline, 2)
        self.assertEqual(plan["repeat_fly_count"], 2)
        runtime = (self.run / "simion/processor.lua").read_text(encoding="utf-8")
        appended = runtime[runtime.index("-- BEGIN_REPEAT_FLY_ORCHESTRATION"):]
        directory = json.dumps(str((self.run / "simion").resolve()).replace("\\", "/") + "/")
        stub = "segment={};local count=0;local d=" + directory + ";function run() count=count+1;for _,name in ipairs({'events.csv','samples.csv'}) do local f=assert(io.open(d..name,'w'));f:write(tostring(count));f:close() end end\n"
        script = self.run / "stub_repeat.lua"
        script.write_text(stub + appended + "\nsegment.flym();assert(count==2)\n", encoding="utf-8")
        result = subprocess.run([lua, str(script)], cwd=self.run, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for index in (1, 2):
            for kind in ("events", "samples"):
                self.assertEqual((self.run / f"simion/repeat_{index}_{kind}.csv").read_text(encoding="utf-8"), str(index))

    def test_repeat_drift_fails_even_when_final_tables_match(self) -> None:
        prepare_replay(self.run, self.baseline, 2)
        for relative in ("simion/events.csv", "simion/samples.csv", "results/particle_state.csv"):
            (self.run / relative).write_bytes((self.baseline / relative).read_bytes())
        for index in (1, 2):
            for kind in ("events", "samples"):
                (self.run / f"simion/repeat_{index}_{kind}.csv").write_bytes((self.baseline / f"simion/{kind}.csv").read_bytes())
        path = self.run / "simion/repeat_1_samples.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("1,1,2,0,0", "1,1,2.5,0,0"), encoding="utf-8")
        with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.functional.analyze", return_value={"status": "functional_incomplete", "source_profile": "functional"}):
            result = finalize_replay(self.run)
        self.assertFalse(result["numerical_equivalence"])
        self.assertEqual(len(result["repeated_fly_comparisons"]), 2)
        self.assertTrue(result["raw_events"]["passed"])
        self.assertFalse(result["repeated_fly_comparisons"][0]["sampled_trajectory"]["passed"])
        self.assertTrue(result["repeated_fly_comparisons"][1]["sampled_trajectory"]["passed"])
        self.assertFalse(result["gui_visual_review"])

    def test_overlap_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nonoverlapping"):
            prepare_replay(self.baseline, self.baseline)


if __name__ == "__main__":
    unittest.main()
