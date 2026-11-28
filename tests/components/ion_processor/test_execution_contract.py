"""Keep public planning scope bound to the existing functional inputs and runner."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.repository.build_project_registry import validate_descriptor


PROJECT = Path(__file__).resolve().parents[3] / "src/msplatform/components/ion_processor"


def read(relative: str) -> dict:
    return json.loads((PROJECT / relative).read_text(encoding="utf-8-sig"))


class ExecutionContractTests(unittest.TestCase):
    def test_registered_mode_matches_actual_source_and_retains_prototype_scope(self) -> None:
        descriptor = read("config/project.json")
        validate_descriptor(descriptor, PROJECT / "config/project.json", PROJECT.parents[3])
        self.assertNotIn("lifecycle_status", descriptor)
        profile, = read(descriptor["contracts"]["execution"])["profiles"]
        mode = read(f"config/modes/{profile['mode']}.json")
        source = read(mode["inputs"]["source"])
        self.assertEqual(profile["action"], "run")
        self.assertNotIn("qualification_support", profile)
        self.assertEqual(profile["supported_operating_points"], [{
            "mass": {"value": source["species"]["mass_amu"], "unit": "Da"},
            "charge_state": source["species"]["charge_state"],
        }])
        self.assertEqual(mode["source_profile"], "functional")
        self.assertEqual(profile["supported_design_variables"], [])
        self.assertEqual(profile["required_bindings"],
                         ["workspace", "execution_environment", "environment_profile", "artifact_root"])
        step = profile["steps"][0]
        self.assertEqual(step["shell"], "python")
        self.assertEqual(step["entrypoint"], "src/msplatform/cli.py")
        self.assertEqual(step["arguments"][:2], ["ion-processor-native-functional", "run"])
        budgets = read(mode["runtime_profiles"])
        self.assertEqual(budgets["role"], "ion_processor_runtime_profiles")
        budget, = [row for row in budgets["profiles"] if row["profile_id"] == mode["runtime_profile_id"]]
        self.assertEqual(budget["retention_class"], "solver_review")
        for key in ("baseline", "numerics", "source", "acceptance", "native_operating_point"):
            self.assertTrue((PROJECT / mode["inputs"][key]).is_file())

    def test_store_run_and_recovery_share_the_existing_public_cli(self) -> None:
        from msplatform import cli
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = ["--artifact-root", str(root / "store")]
            with patch("msplatform.execution.context.load_environment", return_value="context"), \
                 patch("msplatform.workflows.ion_processor.native_functional.run_native_functional",
                       return_value={"status": "success"}) as run, \
                 patch.object(sys, "argv", ["msplatform", "ion-processor-native-functional", "run",
                     "--run-id", "run-1", "--source-profile", "functional",
                     "--execution-environment", str(root / "environment.json"),
                     "--environment-profile", "fixture", "--workspace", str(root), *common]):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(run.call_args.kwargs["run_id"], "run-1")
            self.assertEqual(run.call_args.kwargs["context"], "context")
            self.assertEqual(run.call_args.kwargs["artifact_store"].root, root / "store")
            with patch("msplatform.execution.context.load_environment", return_value="context"), \
                 patch("msplatform.workflows.ion_processor.native_functional.recover_native_stage",
                       return_value={"recovered": False}) as recover, \
                 patch.object(sys, "argv", ["msplatform", "ion-processor-native-functional", "recover-stage",
                     "--native-stage-asset-id", "asset-1", "--execution-environment", str(root / "environment.json"),
                     "--environment-profile", "fixture", "--workspace", str(root), *common]):
                self.assertEqual(cli.main(), 0)
            recover.assert_called_once()
            with patch("msplatform.workflows.ion_processor.native_functional.recover_native_publication",
                       return_value={"recovered": False}) as recover_publication, \
                 patch.object(sys, "argv", ["msplatform", "ion-processor-native-functional", "recover-publication",
                     "--store-run-id", "store-1", *common]):
                self.assertEqual(cli.main(), 0)
            recover_publication.assert_called_once()
            with patch.object(sys, "argv", ["msplatform", "ion-processor-native-functional",
                    "recover-stage", *common]), self.assertRaises(SystemExit):
                cli.main()
            from contextlib import redirect_stderr
            from io import StringIO
            failure = RuntimeError("inert native failure")
            failure.add_note("IP Store run_id: store-1")
            failure.add_note("IP native stage asset_id: asset-1")
            errors = StringIO()
            with patch("msplatform.execution.context.load_environment", return_value="context"), \
                 patch("msplatform.workflows.ion_processor.native_functional.run_native_functional",
                       side_effect=failure), \
                 patch.object(sys, "argv", ["msplatform", "ion-processor-native-functional", "run",
                     "--run-id", "run-1", "--execution-environment", str(root / "environment.json"),
                     "--environment-profile", "fixture", "--workspace", str(root), *common]), \
                 redirect_stderr(errors), self.assertRaises(SystemExit):
                cli.main()
            self.assertIn("store-1", errors.getvalue())
            self.assertIn("asset-1", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
