from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import resolve_runtime_profile

REPO_ROOT = Path(__file__).resolve().parents[2]
QUAD = "rf_quadrupole_ion_optics"
HEX = "rf_hexapole_ion_optics"
OCT = "rf_octupole_ion_optics"


class ResourceBudgetTests(unittest.TestCase):
    def validate(
        self,
        project_id: str = QUAD,
        runtime_profile_id: str = "exit_aperture_plate_acceleration",
        retention_class: str = "compact",
    ) -> dict:
        runtime = resolve_runtime_profile(REPO_ROOT, project_id, runtime_profile_id)
        return validate_pilot_budget(
            repo_root=REPO_ROOT,
            budget_path=Path(runtime["engineering_budget"]["path"]),
            project_id=project_id,
            solver="comsol",
            runtime_profile_id=runtime_profile_id,
            design_profile_id=runtime["design_profile_id"],
            particle_source_path=Path(runtime["particle_source"]["path"]),
            retention_class=retention_class,
        )

    def test_only_quadrupole_exit_plate_acceleration_baseline_is_authorized(self) -> None:
        validated = self.validate()
        self.assertEqual(
            validated["runtime_profile_id"],
            "exit_aperture_plate_acceleration",
        )
        for project_id in (HEX, OCT):
            with self.assertRaisesRegex(ValueError, "not authorized"):
                self.validate(
                    project_id,
                    "no_acceleration_full_length_n100_temporal_refined",
                )
        with self.assertRaisesRegex(ValueError, "differs from authorized scope"):
            self.validate(
                QUAD,
                "segmented_rod_axial_acceleration_n100_spatial_refined",
            )

    def test_high_cost_runners_validate_before_creating_run_package(self) -> None:
        for name in ("run_finite_3d_transport.ps1", "run_simion_finite_3d_transport.ps1"):
            source = (REPO_ROOT / "common/multipole" / name).read_text(encoding="utf-8")
            self.assertLess(
                source.index("common.multipole.resource_budget"),
                source.index("New-RunPackage"),
            )
            for token in (
                "[Parameter(Mandatory=$true)][string]$RuntimeProfileId",
                "[Parameter(Mandatory=$true)][string]$EngineeringBudgetPath",
                "resource_budget_exceeded",
                "Complete-ResourceUsage",
            ):
                self.assertIn(token, source)
        comsol = (REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("'-StartupAttempts','1'", comsol)

    def test_watchdog_interrupts_only_its_child_on_wall_clock_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            usage = root / "usage.json"
            budget.write_text(
                json.dumps(
                    {
                        "limits": {
                            "wall_clock_seconds": 1,
                            "transient_run_directory_bytes": 1024**3,
                            "process_tree_working_set_bytes": 1024**3,
                            "minimum_system_available_memory_bytes": 1,
                            "compact_final_retained_bytes": 1024**2,
                            "automatic_retry_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                f"$r=Invoke-ResourceBudgetedProcess -ResolvedBudgetPath '{budget}' "
                f"-RunDir '{root}' -UsagePath '{usage}' -FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 5');"
                "if(-not$r.resource_budget_exceeded-or$r.exit_code-ne124){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertEqual(measured["status"], "resource_budget_exceeded")
            self.assertEqual(measured["limit_name"], "wall_clock_seconds")

    def test_common_runners_reject_free_numerics_before_run_package(self) -> None:
        project = REPO_ROOT / "projects" / QUAD
        source = REPO_ROOT / (
            "common/multipole/sources/rf_multipole_family_mother_sample_v1_100.csv"
        )
        budget = project / "config/family_experiment/engineering_budget.json"
        cases = (
            (
                "run_finite_3d_transport.ps1",
                [
                    "-WorkingRegionMaximumElementSizeMm",
                    "0.4",
                    "-MeshAutoLevel",
                    "6",
                    "-RfStepsPerPeriod",
                    "80",
                    "-MaximumTimeUs",
                    "80",
                ],
            ),
            (
                "run_simion_finite_3d_transport.ps1",
                [
                    "-CellMm",
                    "0.15",
                    "-TrajectoryQuality",
                    "10",
                    "-RfStepsPerPeriod",
                    "40",
                    "-MaximumTimeUs",
                    "80",
                    "-SimionExe",
                    str(Path(shutil.which("pwsh") or "pwsh.exe").resolve()),
                ],
            ),
        )
        for index, (name, extra) in enumerate(cases, start=1):
            run_id = f"20260728_23590{index}__test__cross__budget-reject__n100"
            command = [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(REPO_ROOT / "common/multipole" / name),
                "-ProjectId",
                QUAD,
                "-RuntimeProfileId",
                "no_acceleration_full_length_n100_temporal_refined",
                "-DesignProfileId",
                "no_acceleration_full_length",
                "-ParticleSourcePath",
                str(source),
                "-EngineeringBudgetPath",
                str(budget),
                "-RunId",
                run_id,
                "-PythonExe",
                str(REPO_ROOT / ".venv/Scripts/python.exe"),
                *extra,
            ]
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "differs from authorized scope",
                completed.stdout + completed.stderr,
            )
            run_dir = (
                REPO_ROOT.parent
                / "artifacts/projects"
                / QUAD
                / "runs"
                / run_id
            )
            self.assertFalse(run_dir.exists(), "rejected numerics created a run package")


if __name__ == "__main__":
    unittest.main()
