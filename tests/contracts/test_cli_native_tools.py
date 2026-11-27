"""Exercise unified CLI injection and failure reporting without a solver."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.cli import main
from msplatform.storage import ArtifactStore
from msplatform.workflows import rf_stationary
from msplatform.workflows.rf_mass_filter import research


class NativeToolsCliTests(unittest.TestCase):
    def test_stationary_stage_receives_actual_store_and_failure_stays_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = ["rf-stationary", "simion-sample", "--request", "request.json",
                    "--budget", "budget.json", "--run-id", "run", "--source-id", "source",
                    "--artifact-root", str(root / "store"), "--workspace", str(root),
                    "--python", "python", "--powershell", "pwsh", "--host-state", "host",
                    "--policy", "policy", "--simion", "simion"]
            context = object()
            output = io.StringIO()
            with patch.object(rf_stationary, "_context", return_value=context), \
                 patch.object(rf_stationary, "simion_samples", return_value={
                     "status": "failed", "reason": "original scientific failure"}) as stage, \
                 redirect_stdout(output):
                self.assertEqual(main(args), 1)
            self.assertIs(stage.call_args.kwargs["context"], context)
            store = stage.call_args.kwargs["artifact_store"]
            self.assertIsInstance(store, ArtifactStore)
            self.assertEqual(store.root, (root / "store").resolve())
            self.assertEqual(json.loads(output.getvalue())["reason"], "original scientific failure")
            self.assertFalse(list(store.root.glob("runs/**/*")))

    def test_missing_store_rejects_before_producer_and_old_cli_surfaces_are_absent(self):
        errors = io.StringIO()
        args = ["rf-stationary", "simion-sample", "--request", "request.json",
                "--budget", "budget.json", "--run-id", "run", "--source-id", "source",
                "--workspace", "workspace", "--python", "python", "--powershell", "pwsh",
                "--host-state", "host", "--policy", "policy", "--simion", "simion"]
        with redirect_stderr(errors), patch.object(rf_stationary, "simion_samples") as stage:
            with self.assertRaises(SystemExit) as rejected:
                main(args)
        self.assertEqual(rejected.exception.code, 2)
        self.assertIn("required: --artifact-root", errors.getvalue())
        stage.assert_not_called()
        for module in (rf_stationary, research):
            self.assertFalse(hasattr(module, "main"))
            self.assertFalse(hasattr(module, "_build_parser"))

    def test_tracking_controls_use_strict_json_and_reach_public_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracking.json"
            controls = {"unit_size": 1, "dispatch_profiles": ["small_native"]}
            path.write_text(json.dumps(controls), encoding="utf-8")
            args = ["run", "recipe.toml", "--artifact-root", str(Path(directory) / "store"),
                    "--tracking-execution", str(path)]
            with patch("msplatform.workflows.tracing.run_recipe", return_value={}) as run, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            self.assertEqual(run.call_args.kwargs["tracking_execution"], controls)
            for invalid in ('{"unit_size":1,"unit_size":2}', '[1]', '{"unit_size":NaN}'):
                with self.subTest(invalid=invalid):
                    path.write_text(invalid, encoding="utf-8")
                    with patch("msplatform.workflows.tracing.run_recipe") as run, \
                         redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as rejected:
                            main(args)
                    self.assertEqual(rejected.exception.code, 2)
                    run.assert_not_called()

    def test_public_run_keeps_interrupted_execution_unsuccessful(self):
        with patch("msplatform.workflows.tracing.run_recipe", return_value={
                "summary": {"execution_status": "interrupted"}}), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["run", "recipe.toml", "--artifact-root", "store"]), 1)

    def test_research_finalization_does_not_turn_original_failure_green(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["rf-filter-research", "--resume-finalization", "--run-id", "original",
                    "--asset-id", "asset", "--workspace", directory, "--artifact-root", directory,
                    "--execution-environment", "environment.json", "--engineering-profile", "small"]
            for state, expected in (("failed", 1), ("ready", 0)):
                with self.subTest(state=state), patch("msplatform.execution.context.load_environment"), \
                     patch.object(research, "resume", return_value={
                         "status": state, "run_directory": str(Path(directory) / "original")}), \
                     redirect_stdout(io.StringIO()):
                    self.assertEqual(main(args), expected)


if __name__ == "__main__":
    unittest.main()
