from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[4]
RESOURCES = REPO / "src/msplatform/workflows/resources"
RUNNERS = {
    "run_comsol.ps1": (
        "workflows/resources/run_artifact_workflow.ps1",
        "COMSOL_INSTALLED_RESOURCE_BOUNDARY",
    ),
    "run_simion.ps1": (
        "execution/resources/run_artifact_support.ps1",
        "SIMION_INSTALLED_RESOURCE_BOUNDARY",
    ),
    "build_simion_layout_placeholder.ps1": (
        "execution/resources/require_powershell7.ps1",
        "BUILDER_INSTALLED_RESOURCE_BOUNDARY",
    ),
}


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class InterfaceInstalledBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.venv = cls.root / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(cls.venv)],
            check=True,
            capture_output=True,
            text=True,
            cwd=cls.root,
            timeout=60,
        )
        cls.python = cls.venv / "Scripts/python.exe"
        cls.installed = (
            cls.venv / "Lib/site-packages/msplatform"
        )
        shutil.copytree(
            REPO / "src/msplatform",
            cls.installed,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        cls.callers = cls.root / "unrelated-callers"
        cls.callers.mkdir()
        for name, (resource, sentinel) in RUNNERS.items():
            (cls.installed / resource).write_text(
                f"throw '{sentinel}'\n", encoding="utf-8"
            )
            shutil.copyfile(RESOURCES / name, cls.callers / name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _environment(self, poison: Path) -> dict[str, str]:
        package = poison / "msplatform"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            "raise RuntimeError('same-name package preempted installation')",
            encoding="utf-8",
        )
        return {**os.environ, "PYTHONPATH": str(poison)}

    def test_runners_use_explicit_roots_and_installed_resources(self) -> None:
        workspace = self.root / "explicit-workspace"
        workspace.mkdir()
        for name, (_, sentinel) in RUNNERS.items():
            with self.subTest(runner=name):
                command = [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(self.callers / name),
                    "-WorkspaceRoot",
                    str(workspace),
                    "-PythonExe",
                    str(self.python),
                ]
                if name == "build_simion_layout_placeholder.ps1":
                    command.extend(
                        ["-OutputDir", "unused", "-SourceGemPath", "unused"]
                    )
                else:
                    command.extend(
                        ["-ArtifactRootPath", str(self.root / "artifacts")]
                    )
                    scientific = [
                        "ScientificModePath",
                        "InterfaceContractPath",
                        "ParticleTablePath",
                        "ParticleBundleMetadataPath",
                        "SourceFamilyPath",
                        "ParticleDistributionPath",
                        "SolverNumericsContractPath",
                        "OperatingPoint",
                    ]
                    if name == "run_comsol.ps1":
                        scientific.extend(
                            [
                                "OfficialSolverNumericsContractPath",
                                "SolverNumericsProfileId",
                                "LimitsPath",
                            ]
                        )
                    else:
                        scientific.append("LayoutTemplateRegistryPath")
                    for parameter in scientific:
                        command.extend([f"-{parameter}", "unused"])
                result = subprocess.run(
                    command,
                    cwd=self.callers,
                    env=self._environment(self.root / f"poison-{name}"),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(sentinel, output)
                self.assertNotIn("same-name package preempted installation", output)

    def test_python_selection_is_mandatory(self) -> None:
        for name in RUNNERS:
            with self.subTest(runner=name):
                command = [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(self.callers / name),
                    "-WorkspaceRoot",
                    str(self.root),
                ]
                if name == "build_simion_layout_placeholder.ps1":
                    command.extend(
                        ["-OutputDir", "unused", "-SourceGemPath", "unused"]
                    )
                else:
                    command.extend(["-ArtifactRootPath", "unused"])
                    scientific = [
                        "ScientificModePath",
                        "InterfaceContractPath",
                        "ParticleTablePath",
                        "ParticleBundleMetadataPath",
                        "SourceFamilyPath",
                        "ParticleDistributionPath",
                        "SolverNumericsContractPath",
                        "OperatingPoint",
                    ]
                    if name == "run_comsol.ps1":
                        scientific.extend(
                            [
                                "OfficialSolverNumericsContractPath",
                                "SolverNumericsProfileId",
                                "LimitsPath",
                            ]
                        )
                    else:
                        scientific.append("LayoutTemplateRegistryPath")
                    for parameter in scientific:
                        command.extend([f"-{parameter}", "unused"])
                result = subprocess.run(
                    command,
                    cwd=self.callers,
                    env={key: value for key, value in os.environ.items()
                         if key != "SIMULATION_PYTHON_EXE"},
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "Explicit PythonExe or SIMULATION_PYTHON_EXE is required",
                    result.stdout + result.stderr,
                )


if __name__ == "__main__":
    unittest.main()
