"""Project capability binding; full registry freshness belongs to its common owner."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from msplatform.contracts.machine_contracts import sha256
from msplatform.contracts.particle_physics import ELECTRON_MASS_U
from tools.repository.build_project_registry import validate_descriptor
from tools.repository.compile_execution_plan import compile_execution

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT / "src/msplatform/components/transverse_helical_filament_wehnelt_electron_gun"


class RegistryProfileTests(unittest.TestCase):
    def test_shared_registry_accepts_and_exposes_profile(self) -> None:
        path = PROJECT_ROOT / "config/project.json"
        project = json.loads(path.read_text(encoding="utf-8"))
        validate_descriptor(project, path, REPO_ROOT)
        execution = json.loads((PROJECT_ROOT / project["contracts"]["execution"]).read_text(encoding="utf-8"))
        profile = execution["profiles"][0]
        self.assertEqual(profile["mode"], "build_only_smoke")
        self.assertEqual(profile["action"], "build")
        self.assertNotIn("qualification_support", profile)
        self.assertEqual([step["step_id"] for step in profile["steps"]], ["commercial_build_only"])
        step = profile["steps"][0]
        self.assertEqual(step["shell"], "python")
        self.assertEqual(step["entrypoint"], "src/msplatform/cli.py")
        self.assertIsNone(step["run_id_template"])
        self.assertEqual(profile["supported_operating_points"][0]["mass"], {"value": ELECTRON_MASS_U, "unit": "Da"})
        self.assertIn("does not run either solver", " ".join(profile["limitations"]))
        self.assertFalse((REPO_ROOT / "src/msplatform/workflows/resources/wehnelt_build_only.ps1").exists())
        self.assertFalse((REPO_ROOT / "src/msplatform/backends/comsol/matlab/build_wehnelt_build_only_task.m").exists())
        self.assertFalse((REPO_ROOT / "src/msplatform/backends/comsol/matlab/write_wehnelt_build_only_report.m").exists())

    def test_registered_profile_compiles_to_public_store_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text("{}", encoding="utf-8")
            registry = REPO_ROOT / "config/project_registry.json"
            plan = dict(
                schema_version=2,
                role="solver_neutral_design_plan",
                request_status="approved",
                project_id=PROJECT_ROOT.name,
                capability_id="wehnelt_thermal_electron_transport",
                mode="build_only_smoke",
                run_id="20261128_000000__build__comsol__wehnelt-registry",
                operating_points=[{"mass": {"value": ELECTRON_MASS_U, "unit": "Da"}, "charge_state": -1}],
                objectives=[],
                design_variables=[],
                constraints=[],
                required_outputs=[],
                provenance=dict(
                    request=dict(path=str(request), sha256=sha256(request)),
                    project_registry=dict(sha256=sha256(registry)),
                ),
            )
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            workspace = root / "workspace"
            artifact_root = root / "store"
            workspace.mkdir()
            artifact_root.mkdir()
            environment = root / "environment.json"
            environment.write_text("{}", encoding="utf-8")
            bindings = {
                "workspace": str(workspace),
                "execution_environment": str(environment),
                "environment_profile": "local",
                "artifact_root": str(artifact_root),
            }
            incomplete = dict(bindings)
            del incomplete["artifact_root"]
            blocked = compile_execution(plan_path, registry, incomplete)
            self.assertEqual(blocked["status"], "NEEDS_RUNTIME_INPUTS")
            self.assertFalse(blocked["safe_to_execute"])
            self.assertIn("artifact_root", " ".join(blocked["blockers"]))
            compiled = compile_execution(plan_path, registry, bindings)
            self.assertEqual(compiled["status"], "EXECUTION_READY", compiled["blockers"])
            command = compiled["commands"][0]
            self.assertEqual(command["argv"][1:4], ["-m", "msplatform.cli", "wehnelt-build-only"])
            self.assertEqual(Path(command["entrypoint"]), REPO_ROOT / "src/msplatform/cli.py")
            self.assertIsNone(command["run_id"])
            self.assertEqual(command["arguments"][command["arguments"].index("--artifact-root") + 1],
                             str(artifact_root))


if __name__ == "__main__":
    unittest.main()
