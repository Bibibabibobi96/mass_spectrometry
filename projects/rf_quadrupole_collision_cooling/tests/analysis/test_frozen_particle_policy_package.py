from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.particle_source_policy import (
    generate_interface_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
HELPER = PROJECT_ROOT / "runtime" / "frozen_python_package.ps1"
SUPPORT = REPO_ROOT / "common" / "contracts" / "run_artifact_support.ps1"
COMSOL_RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1"
SIMION_RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
SOURCE_FAMILY = PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
DISTRIBUTION = PROJECT_ROOT / "config" / "official_particle_source.json"
RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"

RELATIVE_PATHS = (
    r"projects\rf_quadrupole_collision_cooling\workflows\__init__.py",
    r"projects\rf_quadrupole_collision_cooling\workflows\interface_readiness\__init__.py",
    r"projects\rf_quadrupole_collision_cooling\workflows\interface_readiness\generate_particle_table.py",
    r"projects\rf_quadrupole_collision_cooling\workflows\interface_readiness\particle_source_policy.py",
    r"projects\rf_quadrupole_collision_cooling\analysis\paired_particle_source_bundle.py",
    r"common\contracts\particle_physics.py",
    r"common\contracts\particle_count_policy.py",
    r"common\contracts\particle_count_policy.json",
    r"common\multipole\__init__.py",
    r"common\multipole\particle_source_preflight.py",
)
REQUIRED_MODULES = (
    "projects.rf_quadrupole_collision_cooling.workflows",
    "projects.rf_quadrupole_collision_cooling.workflows.interface_readiness",
    "projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.generate_particle_table",
    "projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.particle_source_policy",
    "projects.rf_quadrupole_collision_cooling.analysis.paired_particle_source_bundle",
    "common.contracts.particle_physics",
    "common.contracts.particle_count_policy",
    "common.multipole",
    "common.multipole.particle_source_preflight",
)
GATE_VALIDATOR_RELATIVE_PATH = (
    r"projects\rf_quadrupole_collision_cooling"
    r"\analysis\validate_release_construction_gate.py"
)
GATE_VALIDATOR_MODULE = (
    "projects.rf_quadrupole_collision_cooling"
    ".analysis.validate_release_construction_gate"
)


def _ps(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class FrozenParticlePolicyPackageTests(unittest.TestCase):
    def test_both_runners_use_the_isolated_frozen_package_contract(self) -> None:
        forbidden_live_path = (
            '$env:PYTHONPATH = "$frozenCodeRoot'
            '$([IO.Path]::PathSeparator)$repoRoot"'
        )
        for runner in (COMSOL_RUNNER, SIMION_RUNNER):
            source = runner.read_text(encoding="utf-8")
            with self.subTest(runner=runner.name):
                self.assertIn("runtime\\frozen_python_package.ps1", source)
                self.assertIn("New-FrozenPythonPackage", source)
                self.assertIn("Invoke-IsolatedFrozenPythonModule", source)
                self.assertIn("-ForbiddenRoots @($repoRoot,$projectRoot)", source)
                self.assertIn("-RequiredModuleNames @(", source)
                self.assertIn("frozen_python_code_", source)
                self.assertIn("frozen_python_package_support", source)
                self.assertIn("frozen_python", source)
                self.assertNotIn(forbidden_live_path, source)
                freeze_index = source.index("$frozenBundleMetadata")
                invoke_index = source.index(
                    "$frozenPythonExecution = Invoke-IsolatedFrozenPythonModule"
                )
                self.assertLess(freeze_index, invoke_index)
                invocation = source[invoke_index : source.index(
                    "$frozenParticlePolicy", invoke_index
                )]
                self.assertIn(
                    "'--validate-bundle',$frozenBundleMetadata",
                    invocation,
                )
                self.assertNotIn("$liveBundleMetadata", invocation)
                self.assertNotIn("$bundleMetadataInput", invocation)
                for relative_path in RELATIVE_PATHS:
                    self.assertIn(f"'{relative_path}'", source)

    def test_runtime_helper_is_policy_neutral(self) -> None:
        source = HELPER.read_text(encoding="utf-8").lower()
        for forbidden in (
            "interface_readiness",
            "operating_point",
            "particle_source_policy",
            "threshold",
            "1000",
        ):
            self.assertNotIn(forbidden, source)

    def test_comsol_runner_freezes_analysis_namespace_modules_without_init(
        self,
    ) -> None:
        source = COMSOL_RUNNER.read_text(encoding="utf-8")
        self.assertFalse((PROJECT_ROOT / "analysis" / "__init__.py").exists())
        self.assertNotIn(
            r"projects\rf_quadrupole_collision_cooling\analysis\__init__.py",
            source,
        )
        for relative_path in (
            RELATIVE_PATHS[4],
            GATE_VALIDATOR_RELATIVE_PATH,
        ):
            self.assertIn(f"'{relative_path}'", source)

    def test_frozen_closure_runs_without_live_pythonpath_and_is_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            bundle = root / "bundle"
            generate_interface_bundle(SOURCE_FAMILY, DISTRIBUTION, RESOLVED, bundle)
            source_snapshot = root / "source_snapshot"
            frozen_relative_paths = RELATIVE_PATHS + (
                GATE_VALIDATOR_RELATIVE_PATH,
            )
            frozen_required_modules = REQUIRED_MODULES + (
                GATE_VALIDATOR_MODULE,
            )
            self.assertNotIn(
                "projects.rf_quadrupole_collision_cooling.analysis",
                frozen_required_modules,
            )
            for relative_path in frozen_relative_paths:
                source = REPO_ROOT / relative_path
                destination = source_snapshot / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            code_root = root / "code"
            poison_root = root / "poison"
            poison_module = (
                poison_root
                / "projects"
                / "rf_quadrupole_collision_cooling"
                / "workflows"
                / "interface_readiness"
                / "generate_particle_table.py"
            )
            poison_module.parent.mkdir(parents=True)
            poison_module.write_text(
                "raise RuntimeError('LIVE_OR_USER_FALLBACK_USED')\n",
                encoding="utf-8",
            )
            result_path = root / "result.json"
            script_path = root / "exercise.ps1"
            relative_paths = ",\n        ".join(
                _ps(value) for value in frozen_relative_paths
            )
            required_modules = ",\n        ".join(
                _ps(value) for value in frozen_required_modules
            )
            arguments = ",\n        ".join(
                _ps(value)
                for value in (
                    "--source-family",
                    SOURCE_FAMILY,
                    "--distribution",
                    DISTRIBUTION,
                    "--resolved-design",
                    RESOLVED,
                    "--validate-bundle",
                    bundle / "paired_particle_bundle.json",
                )
            )
            script_path.write_text(
                f"""
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. {_ps(SUPPORT)}
. {_ps(HELPER)}
$package = New-FrozenPythonPackage -SourceRoot {_ps(source_snapshot)} `
    -CodeRoot {_ps(code_root)} -RelativePaths @(
        {relative_paths}
    )
Remove-Item -LiteralPath {_ps(source_snapshot)} -Recurse
$module = 'projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.generate_particle_table'
$arguments = @(
        {arguments}
    )
$requiredModules = @(
        {required_modules}
    )
$env:PYTHONPATH = {_ps(poison_root)}
$env:PYTHONNOUSERSITE = 'restore-me'
$env:PYTHONDONTWRITEBYTECODE = 'restore-bytecode'
$startingDirectory = (Get-Location).Path
$execution = Invoke-IsolatedFrozenPythonModule `
    -Python {_ps(Path(sys.executable).resolve())} -Package $package `
    -Module $module -Arguments $arguments -DistributionNames @('numpy') `
    -RequiredModuleNames $requiredModules `
    -ForbiddenRoots @({_ps(REPO_ROOT)},{_ps(PROJECT_ROOT)})
$restoredAfterSuccess = (
    $env:PYTHONPATH -ceq {_ps(poison_root)} -and
    $env:PYTHONNOUSERSITE -ceq 'restore-me' -and
    $env:PYTHONDONTWRITEBYTECODE -ceq 'restore-bytecode' -and
    (Get-Location).Path -ceq $startingDirectory
)
$mutationRejectCount = 0
foreach ($entry in @($package.files)) {{
    $bytes = [IO.File]::ReadAllBytes([string]$entry.path)
    Remove-Item -LiteralPath ([string]$entry.path)
    try {{ Assert-FrozenPythonPackage -Package $package }}
    catch {{ $mutationRejectCount += 1 }}
    [IO.File]::WriteAllBytes([string]$entry.path,$bytes)
    [IO.File]::AppendAllText([string]$entry.path,"`n# tamper")
    try {{ Assert-FrozenPythonPackage -Package $package }}
    catch {{ $mutationRejectCount += 1 }}
    [IO.File]::WriteAllBytes([string]$entry.path,$bytes)
}}
$generator = Get-FrozenPythonPackageFile -Package $package -RelativePath `
    'projects/rf_quadrupole_collision_cooling/workflows/interface_readiness/generate_particle_table.py'
[IO.File]::WriteAllText($generator,"raise RuntimeError('FROZEN_POISON_EXECUTED')`n")
$generatorEntry = @($package.files | Where-Object {{ $_.path -ceq $generator }})[0]
$generatorEntry.sha256 = Get-RunFileSha256 -Path $generator
$failedClosed = $false
try {{
    Invoke-IsolatedFrozenPythonModule `
        -Python {_ps(Path(sys.executable).resolve())} -Package $package `
        -Module $module -Arguments $arguments -DistributionNames @('numpy') `
        -RequiredModuleNames $requiredModules `
        -ForbiddenRoots @({_ps(REPO_ROOT)},{_ps(PROJECT_ROOT)}) | Out-Null
}} catch {{
    $failedClosed = $_.Exception.Message -match 'Frozen Python module failed'
}}
$restoredAfterFailure = (
    $env:PYTHONPATH -ceq {_ps(poison_root)} -and
    $env:PYTHONNOUSERSITE -ceq 'restore-me' -and
    $env:PYTHONDONTWRITEBYTECODE -ceq 'restore-bytecode' -and
    (Get-Location).Path -ceq $startingDirectory
)
$result = [ordered]@{{
    package = $package
    execution = $execution
    restored_after_success = $restoredAfterSuccess
    restored_after_failure = $restoredAfterFailure
    mutation_reject_count = $mutationRejectCount
    failed_closed = $failedClosed
}}
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath {_ps(result_path)} -Encoding UTF8
""".strip()
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            self.assertTrue(result["restored_after_success"])
            self.assertTrue(result["restored_after_failure"])
            self.assertTrue(result["failed_closed"])
            self.assertEqual(
                result["mutation_reject_count"],
                2 * len(frozen_relative_paths),
            )
            package = result["package"]
            execution = result["execution"]
            self.assertEqual(package["package_roots"], [str(code_root.resolve())])
            self.assertEqual(len(package["files"]), len(frozen_relative_paths))
            self.assertEqual(
                execution["python_path"],
                str(code_root.resolve()),
            )
            self.assertTrue(execution["python_no_user_site"])
            self.assertTrue(execution["python_no_bytecode"])
            self.assertEqual(
                len([path for path in code_root.rglob("*") if path.is_file()]),
                len(frozen_relative_paths),
            )
            self.assertEqual(
                {entry["name"] for entry in execution["frozen_modules"]},
                set(frozen_required_modules),
            )
            for entry in execution["frozen_modules"]:
                self.assertTrue(
                    Path(entry["origin"]).resolve().is_relative_to(code_root.resolve())
                )
            numpy_record = execution["third_party"][0]
            self.assertEqual(numpy_record["name"], "numpy")
            self.assertTrue(numpy_record["version"])
            self.assertIn("site-packages", numpy_record["distribution_root"].lower())
            self.assertNotIn("LIVE_OR_USER_FALLBACK_USED", completed.stderr)


if __name__ == "__main__":
    unittest.main()
