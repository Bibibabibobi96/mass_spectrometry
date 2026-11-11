from __future__ import annotations

import ast
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
PARTICLE_COUNT_POLICY = (
    REPO_ROOT / "src" / "msplatform" / "contracts" / "particle_count_policy.json"
)
ANALYSIS = PROJECT_ROOT / "analysis"
EVALUATOR = REPO_ROOT / "src/msplatform/workflows/rf_transport_comparison.py"
INTERFACE = "transport_interface_readiness"
NO_COLLISION = "transport_no_collision"
ANALYZER_MODULE = "msplatform.workflows.rf_transport_comparison"
CORE = REPO_ROOT / "src/msplatform/analysis/particle_state_comparison.py"
STATE_FIELDS = [
    "particle_id",
    "event",
    "elapsed_time_us",
    "radial_position_mm",
    "divergence_angle_deg",
    "kinetic_energy_eV",
    "max_rod_radius_mm",
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_axial_m_s",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "rf_phase_rad",
]


class SplitParticleStateComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.resolved = self.root / "resolved.json"
        self.resolved.write_text(
            json.dumps(
                {
                    "role": "multipole_resolved_design_do_not_edit",
                    "geometry_mm": {"inscribed_radius_r0": 3.5},
                }
            ),
            encoding="utf-8",
        )
        self.no_collision_mode = self.root / "no_collision.json"
        self.no_collision_mode.write_text(
            json.dumps(
                {
                    "mode": "transport_no_collision",
                    "numerics": {
                        "minimum_expected_transmission": 0.8,
                        "cross_solver_transmission_absolute_tolerance": 0.1,
                        "cross_solver_relative_mean_tof_tolerance": 0.1,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.interface_mode = self.root / "interface.json"
        self.interface_mode.write_text(
            json.dumps(
                {
                    "mode": "transport_interface_readiness",
                    "status": "candidate_only",
                    "numerics": {"minimum_diagnostic_particles": 100},
                    "candidate_acceptance_targets": {
                        "policy": "diagnostic_only",
                        "minimum_transmission": 0.8,
                        "cross_solver_transmission_absolute_difference": 0.05,
                        "cross_solver_relative_mean_tof_difference": 0.05,
                        "cross_solver_relative_rms_output_radius_difference": 0.1,
                        "cross_solver_relative_rms_divergence_difference": 0.15,
                        "cross_solver_relative_mean_energy_difference": 0.02,
                    },
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def write_state(
        path: Path,
        particle_count: int,
        handoff_ids: set[int],
        source_ids: set[int] | None = None,
        duplicate_source: bool = False,
    ) -> None:
        if source_ids is None:
            source_ids = set(range(1, particle_count + 1))
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
            writer.writeheader()
            for particle_id in sorted(source_ids):
                writer.writerow({"particle_id": particle_id, "event": "source"})
            if duplicate_source:
                writer.writerow({"particle_id": 1, "event": "source"})
            for particle_id in range(1, particle_count + 1):
                if particle_id in handoff_ids:
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "event": "handoff",
                            "elapsed_time_us": 10 + particle_id / 1000,
                            "radial_position_mm": 0.1,
                            "divergence_angle_deg": 0.1,
                            "kinetic_energy_eV": 2,
                            "transverse_x_mm": 0.1,
                            "transverse_y_mm": 0,
                            "velocity_axial_m_s": 1000,
                            "velocity_x_m_s": 0,
                            "velocity_y_m_s": 0,
                            "rf_phase_rad": 0,
                        }
                    )
                writer.writerow(
                    {
                        "particle_id": particle_id,
                        "event": "terminal",
                        "max_rod_radius_mm": 0.1,
                    }
                )

    def run_analyzer(
        self,
        analyzer: str,
        particle_count: int,
        comsol_handoffs: set[int],
        simion_handoffs: set[int],
        *,
        source_ids: set[int] | None = None,
        duplicate_source: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], dict | None, list[dict[str, str]]]:
        case = self.root / f"case_{len(list(self.root.glob('case_*')))}"
        case.mkdir()
        comsol = case / "comsol.csv"
        simion = case / "simion.csv"
        particles = case / "particles.dat"
        output = case / "result.json"
        census = case / "census.csv"
        self.write_state(
            comsol,
            particle_count,
            comsol_handoffs,
            source_ids,
            duplicate_source,
        )
        self.write_state(simion, particle_count, simion_handoffs, source_ids)
        particles.write_text("particle\n" * particle_count, encoding="ascii")
        arguments = [
            sys.executable,
            "-m",
            ANALYZER_MODULE,
            "--comsol",
            str(comsol),
            "--simion",
            str(simion),
        ]
        if analyzer == NO_COLLISION:
            arguments += [
                "--resolved",
                str(self.resolved),
                "--mode-contract",
                str(self.no_collision_mode),
                "--particle-count-policy",
                str(PARTICLE_COUNT_POLICY),
            ]
        else:
            arguments += [
                "--mode-contract",
                str(self.interface_mode),
            ]
        arguments += [
            "--particles",
            str(particles),
            "--particle-count",
            str(particle_count),
            "--output",
            str(output),
            "--census-output",
            str(census),
        ]
        completed = subprocess.run(
            arguments,
            cwd=REPO_ROOT,
            timeout=60,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        report = (
            json.loads(output.read_text(encoding="utf-8"))
            if output.is_file()
            else None
        )
        rows: list[dict[str, str]] = []
        if census.is_file():
            with census.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        return completed, report, rows

    def test_interface_identical_eighty_percent_survivors_can_pass(self) -> None:
        survivors = set(range(1, 81))
        result, report, census = self.run_analyzer(
            INTERFACE, 100, survivors, survivors
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(report["gates"].values()))
        self.assertEqual(report["paired_handoff_particles"], 80)
        self.assertEqual(len(census), 100)

    def test_no_collision_requires_full_handoff_pairing(self) -> None:
        survivors = set(range(1, 81))
        result, report, _ = self.run_analyzer(
            NO_COLLISION, 100, survivors, survivors
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["gates"]["full_handoff_pairing"])

    def test_interface_below_minimum_is_not_evaluated(self) -> None:
        survivors = set(range(1, 100))
        result, report, _ = self.run_analyzer(
            INTERFACE, 99, survivors, survivors
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "NOT_EVALUATED")
        self.assertFalse(report["sample_size_eligible"])
        self.assertEqual(report["gates"], {})

    def test_invalid_source_identity_is_not_a_physical_fail(self) -> None:
        source_ids = set(range(1, 100))
        result, report, _ = self.run_analyzer(
            INTERFACE,
            100,
            set(range(1, 81)),
            set(range(1, 81)),
            source_ids=source_ids,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "NOT_EVALUATED")
        self.assertFalse(report["source_evidence"]["valid"])
        self.assertEqual(report["gates"], {})

    def test_no_collision_claim_does_not_switch_with_sample_size(self) -> None:
        statuses = []
        reports = []
        for count in (5, 100):
            all_ids = set(range(1, count + 1))
            result, report, _ = self.run_analyzer(
                NO_COLLISION, count, all_ids, all_ids
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            assert report is not None
            reports.append(report)
            statuses.append((report["workflow"], report["status"]))
        self.assertEqual(
            statuses,
            [
                ("transport_no_collision", "NOT_EVALUATED"),
                ("transport_no_collision", "PASS"),
            ],
        )
        self.assertFalse(reports[0]["sample_size_eligible"])
        self.assertEqual(reports[0]["gates"], {})
        self.assertTrue(reports[1]["sample_size_eligible"])

    def test_duplicate_event_is_an_execution_error(self) -> None:
        result, report, _ = self.run_analyzer(
            INTERFACE,
            100,
            set(range(1, 81)),
            set(range(1, 81)),
            duplicate_source=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(report)
        self.assertIn("duplicate particle event", result.stderr)

    def test_actual_cross_solver_frozen_path_requires_canonical_core(self) -> None:
        self.run_analyzer(INTERFACE, 100, set(range(1, 81)), set(range(1, 81)))
        case = self.root / "case_0"
        arguments = ["--comsol", str(case / "comsol.csv"), "--simion", str(case / "simion.csv"),
                     "--mode-contract", str(self.interface_mode), "--particles", str(case / "particles.dat"),
                     "--particle-count", "100", "--output", str(case / "cold.json"),
                     "--census-output", str(case / "cold.csv")]
        args_path = self.root / "arguments.json"
        args_path.write_text(json.dumps(arguments), encoding="utf-8")
        selected = self.root / "selected-source"
        shutil.copytree(REPO_ROOT / "src/msplatform", selected / "src/msplatform",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(REPO_ROOT / "common/contracts", selected / "common/contracts",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        selected_workflow = selected / "src/msplatform/workflows/rf_transport_comparison.py"
        selected_workflow.write_bytes(selected_workflow.read_bytes() + b"\n# selected source witness\n")
        self.assertNotEqual(selected_workflow.read_bytes(), EVALUATOR.read_bytes())
        literal = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = f"""
$ErrorActionPreference='Stop'
$repoRoot={literal(REPO_ROOT)};$selectedRoot={literal(selected)};$python={literal(sys.executable)}
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1') -ExecutionResourcePath (Join-Path $selectedRoot 'src/msplatform/execution/resources/frozen_python_package.ps1')
. (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/cross_solver_analysis_lifecycle.ps1')
$t=$null;$e=$null
$entry=Join-Path $repoRoot 'projects/rf_multipole_ion_optics/workflows/cross_solver/compare_cross_solver.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($entry,[ref]$t,[ref]$e)
if($e.Count){{throw 'Actual cross-solver entry did not parse'}}
$frozen=New-CrossSolverFrozenPathSet -InputDir {literal(self.root / 'frozen-inputs')} `
 -AnalyzerRelativePath 'src/msplatform/workflows/rf_transport_comparison.py' -ModeFilename 'mode.json'
$selection=$ast.Find({{param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$frozenPackage'}},$true)
$liveRoot=$repoRoot;$repoRoot=$selectedRoot
Invoke-Expression $selection.Extent.Text
Assert-FrozenPythonPackage -Package $frozenPackage
. (Get-FrozenPythonPackageFile -Package $frozenPackage -RelativePath 'src/msplatform/execution/resources/frozen_python_package.ps1')
$arguments=@(Get-Content -Raw -LiteralPath {literal(args_path)}|ConvertFrom-Json)
$parameters=@{{Python=$python;AnalyzerModule='{ANALYZER_MODULE}';
 Package=$frozenPackage;ForbiddenRoots=@($repoRoot,$liveRoot);Arguments=$arguments;
 Stdout={literal(self.root / 'stdout.txt')};Stderr={literal(self.root / 'stderr.txt')};
 RequiredOutputs=@({literal(case / 'cold.json')},{literal(case / 'cold.csv')})}}
Invoke-CrossSolverAnalyzer @parameters
$probe=Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenPackage -Module '{ANALYZER_MODULE}' `
 -Arguments $arguments -RequiredModuleNames @('{ANALYZER_MODULE}','msplatform.io.file_identity','msplatform.analysis.particle_state_comparison') `
 -ForbiddenRoots @($repoRoot,$liveRoot) -ProbeOnly
foreach($row in $probe.frozen_modules){{
 if(-not ([IO.Path]::GetFullPath([string]$row.origin)).StartsWith([IO.Path]::GetFullPath($frozen.module_root)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){{throw 'Probed module escaped frozen source'}}
}}
if((Get-RunFileSha256 $frozen.analyzer)-ne(Get-RunFileSha256 (Join-Path $selectedRoot 'src/msplatform/workflows/rf_transport_comparison.py'))){{throw 'Frozen analyzer differs from selected source'}}
foreach($relative in @('src/msplatform/analysis/particle_state_comparison.py','src/msplatform/workflows/rf_transport_comparison.py','src/msplatform/io/file_identity.py')){{
 $path=Join-Path $frozen.module_root $relative; $bytes=[IO.File]::ReadAllBytes($path)
 Remove-Item -LiteralPath $path
 try{{Invoke-CrossSolverAnalyzer @parameters;throw 'Missing canonical dependency was accepted'}}
 catch{{if($_.Exception.Message-notlike'Frozen Python dependency is missing*'){{throw}}}}
 [IO.File]::WriteAllBytes($path,$bytes)
 [IO.File]::WriteAllBytes($path,($bytes + [byte[]](10)))
 try{{Invoke-CrossSolverAnalyzer @parameters;throw 'Tampered canonical dependency was accepted'}}
 catch{{if($_.Exception.Message-notlike'Frozen Python dependency hash differs:*'){{throw}}}}
 [IO.File]::WriteAllBytes($path,$bytes)
}}
Write-Output 'CANONICAL_CORE_MISSING_REJECTED'
exit 0
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                cwd=self.root, timeout=120, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout + (self.root / "stderr.txt").read_text(encoding="utf-8"))
        self.assertIn("CANONICAL_CORE_MISSING_REJECTED", result.stdout)
        expected = json.loads((case / "result.json").read_text(encoding="utf-8"))
        actual = json.loads((case / "cold.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)
        self.assertEqual((case / "cold.csv").read_bytes(), (case / "census.csv").read_bytes())

    def test_cross_solver_failure_stdout_bytes_survive_isolated_exit(self) -> None:
        source = self.root / "source"
        for relative in ("src/msplatform/__init__.py", "src/msplatform/analysis/__init__.py",
                         "src/msplatform/analysis/particle_state_comparison.py",
                         "src/msplatform/execution/resources/frozen_python_package.ps1"):
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO_ROOT / relative).read_bytes())
        expected = "OWNED_STDOUT_MARKER\n\n\u4e2d\u6587 trailing  \n\n".encode("utf-8")
        (source / "owned_analyzer.py").write_text(
            "import pathlib, sys\n"
            f"sys.stdout.buffer.write(bytes.fromhex('{expected.hex()}'))\n"
            "sys.stdout.flush()\n"
            "print('OWNED_STDERR_MARKER', file=sys.stderr, flush=True)\n"
            "pathlib.Path(sys.argv[2]).write_text(str(pathlib.Path(__file__).resolve()), encoding='utf-8')\n"
            "raise SystemExit(int(sys.argv[1]))\n", encoding="utf-8")
        literal = lambda value: "'" + str(value).replace("'", "''") + "'"
        report = self.root / "stdout-proof.json"
        script = f"""
$ErrorActionPreference='Stop'
$repoRoot={literal(REPO_ROOT)};$python={literal(sys.executable)};$root={literal(self.root)}
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1') -ExecutionResourcePath (Join-Path $repoRoot 'src/msplatform/execution/resources/frozen_python_package.ps1')
. (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/cross_solver_analysis_lifecycle.ps1')
$package=New-FrozenPythonPackage -Python $python -SourceRoot {literal(source)} -CodeRoot (Join-Path $root 'frozen') `
 -RelativePaths @('owned_analyzer.py','src/msplatform/__init__.py','src/msplatform/analysis/__init__.py','src/msplatform/analysis/particle_state_comparison.py','src/msplatform/execution/resources/frozen_python_package.ps1')
Assert-FrozenPythonPackage -Package $package
. (Get-FrozenPythonPackageFile -Package $package -RelativePath 'src/msplatform/execution/resources/frozen_python_package.ps1')
$before=@($package.files|ForEach-Object{{Get-RunFileSha256 -Path $_.path}})
$rows=@()
foreach($code in @(0,7)){{
 $stdout=Join-Path $root "$code.stdout";$stderr=Join-Path $root "$code.stderr";$origin=Join-Path $root "$code.origin"
 $threw=$false;$errorCode=$null;$message=''
 try{{Invoke-CrossSolverAnalyzer -Python $python -AnalyzerModule owned_analyzer `
   -Package $package -ForbiddenRoots @($repoRoot,{literal(source)}) -Arguments @([string]$code,$origin) `
   -Stdout $stdout -Stderr $stderr -RequiredOutputs @($origin)}}
 catch{{$threw=$true;$errorCode=$_.Exception.Data['exit_code'];$message=$_.Exception.Message}}
 Assert-FrozenPythonPackage -Package $package
 $rows+=@{{code=$code;threw=$threw;exit_code=$errorCode;message=$message;origin=[IO.File]::ReadAllText($origin);
 stdout_hex=[Convert]::ToHexString([IO.File]::ReadAllBytes($stdout));stderr=[IO.File]::ReadAllText($stderr)}}
}}
$after=@($package.files|ForEach-Object{{Get-RunFileSha256 -Path $_.path}})
@{{before=$before;after=$after;rows=$rows;code_root=$package.code_root}}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath {literal(report)} -Encoding utf8NoBOM
exit 0
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                cwd=self.root, timeout=120, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        proof = json.loads(report.read_text(encoding="utf-8-sig"))
        self.assertEqual(proof["before"], proof["after"])
        for row in proof["rows"]:
            with self.subTest(exit_code=row["code"]):
                self.assertEqual(bytes.fromhex(row["stdout_hex"]), expected)
                self.assertIn("OWNED_STDERR_MARKER", row["stderr"])
                self.assertEqual(Path(row["origin"]), Path(proof["code_root"]) / "owned_analyzer.py")
                self.assertEqual(row["threw"], row["code"] != 0)
                if row["code"]:
                    self.assertEqual(row["exit_code"], 7)
                    self.assertIn("exit code 7", row["message"])

    def test_missing_selected_execution_resource_does_not_use_host_resource(self) -> None:
        selected = self.root / "selected_execution_resource.ps1"
        selected.write_bytes((REPO_ROOT / "src/msplatform/execution/resources/frozen_python_package.ps1").read_bytes())
        literal = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = f"""
$ErrorActionPreference='Stop'
$helper={literal(REPO_ROOT / 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1')}
$selected={literal(selected)}
. $helper -ExecutionResourcePath $selected
if((Get-Command Invoke-IsolatedFrozenPythonModule).ScriptBlock.File-cne$selected){{throw 'Executor did not originate from selected resource'}}
Remove-Item -LiteralPath $selected
try{{. $helper -ExecutionResourcePath $selected;throw 'Missing selected resource accepted'}}
catch{{if($_.Exception.Message-notlike'Selected frozen Python execution resource is missing:*'){{throw}}}}
Write-Output 'MISSING_SELECTED_RESOURCE_REJECTED'
exit 0
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                cwd=self.root, timeout=120, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MISSING_SELECTED_RESOURCE_REJECTED", result.stdout)
        self.assertTrue((REPO_ROOT / "src/msplatform/execution/resources/frozen_python_package.ps1").is_file())

    def test_hash_source_is_the_existing_canonical_implementation(self) -> None:
        from common.contracts.file_identity import file_sha256 as prior_alias
        from msplatform.io.file_identity import file_sha256
        from msplatform.workflows import rf_transport_comparison

        self.assertIs(prior_alias, file_sha256)
        self.assertIs(rf_transport_comparison._sha256, file_sha256)
        self.assertEqual(file_sha256.__module__, "msplatform.io.file_identity")
        sample = self.root / "identity.bin"
        sample.write_bytes(b"\x00identity\xff\n")
        self.assertEqual(prior_alias(sample), file_sha256(sample))

    def test_shared_core_has_no_claim_vocabulary(self) -> None:
        source = CORE.read_text(encoding="utf-8").lower()
        for forbidden in (
            "solver",
            "comsol",
            "simion",
            "mode",
            "role",
            "threshold",
            "decision",
        ):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        arguments = {
            argument.arg
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in (*node.args.args, *node.args.kwonlyargs)
        }
        self.assertTrue(
            names.isdisjoint({"within", "acceptance", "threshold", "limit"})
        )
        self.assertTrue(
            arguments.isdisjoint(
                {"maximum", "limit", "acceptance", "threshold"}
            )
        )


if __name__ == "__main__":
    unittest.main()
