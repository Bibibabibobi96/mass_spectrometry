from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from msplatform.execution.inputs import enumerate_python_sources, python_import_roots

from projects.rf_multipole_ion_optics.workflows.interface_readiness.particle_source_policy import (
    generate_interface_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
HELPER = PROJECT_ROOT / "runtime" / "frozen_python_package.ps1"
SUPPORT = REPO_ROOT / "common" / "contracts" / "run_artifact_support.ps1"
COMSOL_RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1"
SIMION_RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
SOURCE_FAMILY = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "interface_readiness_particle_source.json"
DISTRIBUTION = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json"
RESOLVED = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_official.json"

RELATIVE_PATHS = (
    "src/msplatform/execution/resources/frozen_python_package.ps1",
    r"projects\rf_multipole_ion_optics\workflows\__init__.py",
    r"projects\rf_multipole_ion_optics\workflows\interface_readiness\__init__.py",
    r"projects\rf_multipole_ion_optics\workflows\interface_readiness\generate_particle_table.py",
    r"projects\rf_multipole_ion_optics\workflows\interface_readiness\particle_source_policy.py",
    r"projects\rf_multipole_ion_optics\analysis\paired_particle_source_bundle.py",
    r"src\msplatform\contracts\particle_count_policy.json",
    r"common\contracts\file_identity.py",
    r"projects\rf_multipole_ion_optics\core\__init__.py",
    r"projects\rf_multipole_ion_optics\core\interface_geometry.py",
)
RELATIVE_PATHS += tuple(enumerate_python_sources(
    REPO_ROOT, package_roots=['src/msplatform'], provider_root='src/msplatform',
    resource_suffixes=('.schema.json',)))
REQUIRED_MODULES = (
    "msplatform",
    "projects.rf_multipole_ion_optics.workflows",
    "projects.rf_multipole_ion_optics.workflows.interface_readiness",
    "projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table",
    "projects.rf_multipole_ion_optics.workflows.interface_readiness.particle_source_policy",
    "projects.rf_multipole_ion_optics.analysis.paired_particle_source_bundle",
    "msplatform.contracts.particle_physics",
    "msplatform.contracts.particle_count_policy",
    "common.contracts.file_identity",
    "msplatform.ion_release",
    "msplatform.ion_release.mt19937_disk_cone_rf_phase",
    "msplatform.ion_release.numpy_box_cone",
    "msplatform.ion_release.numpy_ion11_box",
    "projects.rf_multipole_ion_optics.core",
    "projects.rf_multipole_ion_optics.core.interface_geometry",
    "msplatform.components.rf_multipole.source_validation",
)
GATE_VALIDATOR_RELATIVE_PATH = (
    r"projects\rf_multipole_ion_optics"
    r"\analysis\validate_release_construction_gate.py"
)
GATE_VALIDATOR_MODULE = (
    "projects.rf_multipole_ion_optics"
    ".analysis.validate_release_construction_gate"
)


def _ps(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _mass_analysis_setup(runner: Path) -> str:
    """Exercise each production runner's analysis-only freeze/probe boundary."""
    source = runner.read_text(encoding="utf-8")
    probe_end = "-ForbiddenRoots @($repoRoot,$projectRoot) -ProbeOnly"
    if runner.name == "compare_responses.ps1":
        package_start = source.index("$runtimeRoot =")
        package_end = source.index("$inputs =", package_start)
        probe_start = source.index("$module =", package_end)
        end = source.index(probe_end, probe_start) + len(probe_end)
        return source[package_start:package_end] + source[probe_start:end] + "\n" + "\n".join((
            "$frozenAnalysisPackage = $frozenPythonPackage",
            "$analysisModule = $module",
            "$analysisRequiredModules = $requiredModules",
            "$analysisDistributions = $distributions",
        ))
    start = source.index("$frozenPythonSupport =")
    end = source.index(probe_end, start) + len(probe_end)
    return source[start:end]


class FrozenParticlePolicyPackageTests(unittest.TestCase):
    def test_executor_working_directory_and_pillow_distribution_use_real_selected_provider(self) -> None:
        """Exercise only the shared executor with one tiny frozen test module."""
        import importlib.metadata
        import PIL
        from msplatform.execution.inputs import freeze_python_package

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            source.mkdir()
            module = source / "owned_cwd.py"
            module.write_text(
                "import json,os,sys\nfrom pathlib import Path\nimport PIL\n"
                "Path(sys.argv[1]).write_text(json.dumps(dict(cwd=os.getcwd(),pid=os.getpid(),"
                "module=__file__,pil_origin=PIL.__file__)),encoding='utf-8')\n"
                "print('OWNED_CWD_MODULE_INVOKED')\n", encoding="utf-8")
            original_module = module.read_bytes()
            code_root = root / "frozen"
            package = freeze_python_package(source, code_root, relative_paths=["owned_cwd.py"])
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            explicit = root / "explicit different cwd"
            explicit.mkdir()
            (root / "relative-cwd").mkdir()
            receipt = root / "receipt.json"
            script = root / "exercise.ps1"
            script.write_text(f"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. {_ps(REPO_ROOT / 'src/msplatform/execution/resources/frozen_python_package.ps1')}
$package=Get-Content -LiteralPath {_ps(package_path)} -Raw -Encoding UTF8|ConvertFrom-Json
$startingDirectory=(Get-Location).Path
$positive=@()
foreach($label in @('default','explicit')){{
 $marker=Join-Path {_ps(root)} ($label+'-invoked.json')
 $stdout=Join-Path {_ps(root)} ($label+'-stdout.log')
 $options=@{{}}
 if($label-ceq'explicit'){{$options.WorkingDirectory={_ps(explicit)}}}
 $execution=Invoke-IsolatedFrozenPythonModule -Python {_ps(sys.executable)} -Package $package `
  -Module 'owned_cwd' -Arguments @($marker) -DistributionNames @('Pillow') `
  -RequiredModuleNames @('owned_cwd') -ForbiddenRoots @({_ps(source)},{_ps(REPO_ROOT)}) `
  -StdoutPath $stdout @options
 $positive+=@{{label=$label;execution=$execution;marker=(Get-Content -LiteralPath $marker -Raw|ConvertFrom-Json);
  stdout=[IO.File]::ReadAllText($stdout);restored=((Get-Location).Path-ceq$startingDirectory)}}
}}
$negative=@()
foreach($label in @('relative','missing')){{
 $marker=Join-Path {_ps(root)} ($label+'-invoked.json')
 $stdout=Join-Path {_ps(root)} ($label+'-stdout.log')
 $cwd=if($label-ceq'relative'){{'relative-cwd'}}else{{{_ps(root / 'missing-cwd')}}}
 $message=$null
 try{{
  Invoke-IsolatedFrozenPythonModule -Python {_ps(sys.executable)} -Package $package `
   -Module 'owned_cwd' -Arguments @($marker) -DistributionNames @('Pillow') `
   -RequiredModuleNames @('owned_cwd') -WorkingDirectory $cwd -StdoutPath $stdout|Out-Null
 }}catch{{$message=$_.Exception.Message}}
 $negative+=@{{label=$label;requested=$cwd;message=$message;
  marker_exists=[IO.File]::Exists($marker);stdout_exists=[IO.File]::Exists($stdout);
  restored=((Get-Location).Path-ceq$startingDirectory)}}
}}
@{{positive=$positive;negative=$negative}}|ConvertTo-Json -Depth 16|
 Set-Content -LiteralPath {_ps(receipt)} -Encoding utf8NoBOM
""", encoding="utf-8")
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual([row["label"] for row in result["positive"]], ["default", "explicit"])
            for row in result["positive"]:
                with self.subTest(cwd=row["label"]):
                    expected = code_root if row["label"] == "default" else explicit
                    execution = row["execution"]
                    self.assertEqual(execution["schema_version"], 1)
                    self.assertTrue(execution["module_invoked"])
                    self.assertEqual(execution["module"], "owned_cwd")
                    self.assertEqual(Path(execution["working_directory"]), expected)
                    self.assertEqual(Path(row["marker"]["cwd"]), expected)
                    self.assertGreater(row["marker"]["pid"], 0)
                    self.assertEqual(Path(row["marker"]["module"]), code_root / "owned_cwd.py")
                    self.assertTrue(row["restored"])
                    self.assertIn("OWNED_CWD_MODULE_INVOKED", row["stdout"])
                    self.assertEqual(execution["module_stdout"], "OWNED_CWD_MODULE_INVOKED")
                    self.assertEqual(execution["package_roots"], package["package_roots"])
                    self.assertEqual(execution["frozen_modules"], [dict(name="owned_cwd", origin=str(code_root / "owned_cwd.py"))])
                    self.assertEqual(len(execution["third_party"]), 1)
                    pillow = execution["third_party"][0]
                    self.assertEqual(pillow["name"], "Pillow")
                    self.assertEqual(pillow["version"], importlib.metadata.version("Pillow"))
                    self.assertEqual(Path(pillow["module_path"]), Path(PIL.__file__).resolve())
                    self.assertEqual(Path(row["marker"]["pil_origin"]), Path(pillow["module_path"]))
                    self.assertTrue(Path(pillow["module_path"]).is_relative_to(Path(pillow["distribution_root"])))
            self.assertEqual([row["label"] for row in result["negative"]], ["relative", "missing"])
            for row in result["negative"]:
                with self.subTest(invalid_cwd=row["label"]):
                    self.assertIsInstance(row["message"], str)
                    self.assertTrue(row["message"].startswith("Explicit frozen Python working directory must be absolute and existing:"), row)
                    self.assertIn(row["requested"], row["message"])
                    self.assertFalse(row["marker_exists"])
                    self.assertFalse(row["stdout_exists"])
                    self.assertTrue(row["restored"])
            self.assertEqual(module.read_bytes(), original_module)
            self.assertEqual((code_root / "owned_cwd.py").read_bytes(), original_module)

    def test_same_solver_and_mass_filter_select_real_rf_adapter_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, (relative, variable) in enumerate((
                    ('workflows/same_solver_convergence/run_comparison.ps1', '$runtimeFiles'),
                    ('workflows/mass_filter_reference/run_simion.ps1', '$analysisFiles'))):
                with self.subTest(runner=relative):
                    script = f"""
$ErrorActionPreference='Stop'
$repoRoot={_ps(REPO_ROOT)};$python={_ps(sys.executable)}
. {_ps(SUPPORT)}
. {_ps(HELPER)} -ExecutionResourcePath {_ps(REPO_ROOT / 'src/msplatform/execution/resources/frozen_python_package.ps1')}
$t=$null;$e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({_ps(PROJECT_ROOT / relative)},[ref]$t,[ref]$e)
if($e.Count){{throw 'Actual runner did not parse'}}
$node=$ast.Find({{param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq{_ps(variable)}}},$true)
Invoke-Expression $node.Extent.Text
$paths={variable}
$package=New-FrozenPythonPackage -Python $python -SourceRoot $repoRoot -CodeRoot {_ps(Path(directory) / str(index))} -RelativePaths $paths
$execution=Invoke-IsolatedFrozenPythonModule -Python $python -Package $package `
 -Module 'projects.rf_multipole_ion_optics.analysis.rf_event_table_validation' -Arguments @('--help') `
 -RequiredModuleNames @('projects.rf_multipole_ion_optics.analysis.rf_event_table_validation',
 'projects.rf_multipole_ion_optics.simion.ion11_source_adapter','msplatform.contracts.particle_physics') `
 -ForbiddenRoots @($repoRoot)
@{{files=@($package.files.relative_path);executed=$execution.module_invoked}}|ConvertTo-Json -Depth 8 -Compress
"""
                    result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=directory,
                                            capture_output=True, text=True, encoding='utf-8', timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    document = json.loads(result.stdout[result.stdout.index('{'):])
                    self.assertTrue(document['executed'])
                    self.assertIn('projects/rf_multipole_ion_optics/simion/ion11_source_adapter.py', document['files'])

    def test_comsol_canonical_state_to_response_uses_one_frozen_analysis_package(self) -> None:
        runner = PROJECT_ROOT / "workflows/mass_filter_reference/run_comsol.ps1"
        source = runner.read_text(encoding="utf-8")
        start = source.index("  foreach($case in $cases){", source.index("Restore-RunEnvironment"))
        analysis = source[start:source.index("  $metricDocument=", start)]
        setup = _mass_analysis_setup(runner)
        files = re.findall(r"^\s*'((?:projects|common)[/\\][^']+)'[,]?$", setup, re.MULTILINE)
        package_roots = [relative for relative in files if (REPO_ROOT / relative).is_dir()]
        self.assertTrue(package_roots)
        files = (set(files) - set(package_roots)) | set(
            enumerate_python_sources(REPO_ROOT, package_roots=package_roots)
        )
        files.update(enumerate_python_sources(REPO_ROOT, package_roots=['src/msplatform'],
                                              provider_root='src/msplatform', resource_suffixes=('.schema.json',)))
        files.add('src/msplatform/execution/resources/frozen_python_package.ps1')
        state_relative = "projects/rf_multipole_ion_optics/analysis/analyze_comsol_particle_state_metrics.py"
        helper_relative = "projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1"
        mode_path = PROJECT_ROOT / "config/modes/quadrupole_mass_filter_reference.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        masses = mode["mass_scan_spec"]["paired_source_masses_Th"]
        center = mode["mass_scan_spec"]["calibration_mass_Th"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active_source"
            for relative in {*files, state_relative, helper_relative}:
                destination = active / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO_ROOT / relative, destination)
            inputs, results = root / "inputs", root / "results"
            inputs.mkdir()
            results.mkdir()
            frozen_mode = inputs / "mode.json"
            shutil.copy2(mode_path, frozen_mode)
            cases = []
            for index, mass in enumerate(masses):
                state, raw, summary = (results / f"case_{index}_{name}" for name in ("state.csv", "raw.json", "summary.json"))
                raw.write_text(json.dumps(dict(role="rf_quadrupole_comsol_raw_solver_metadata",
                                               mode="mass_filter_reference", mass_Th=mass)), encoding="utf-8")
                with state.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=("particle_id", "event", "status", "radial_position_mm", "kinetic_energy_eV"))
                    writer.writeheader()
                    writer.writerows(dict(particle_id=pid, event=event,
                                          status="alive" if event == "source" else (
                                              "transmitted" if mass == center else "lost"),
                                          radial_position_mm=.1, kinetic_energy_eV=2.)
                                     for pid in range(1, 5) for event in ("source", "terminal"))
                cases.append(dict(mass_Th=mass, raw_metadata=str(raw), particle_state=str(state), solver_summary=str(summary)))
            scan = inputs / "scan.json"
            scan.write_text(json.dumps(dict(cases=cases)), encoding="utf-8")
            receipt = root / "receipt.json"
            script = root / "exercise.ps1"
            script.write_text(f"""
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. {_ps(SUPPORT)}
$python = {_ps(Path(sys.executable).resolve())}
$package = @{{python=$python}}
$repoRoot = {_ps(active)}
$projectRoot = Join-Path $repoRoot 'projects/rf_multipole_ion_optics'
$inputDir = {_ps(inputs)}
$resultDir = {_ps(results)}
$scanConfig = {_ps(scan)}
$sources = @{{mode={_ps(frozen_mode)}}}
$cases = (Get-Content -LiteralPath $scanConfig -Raw | ConvertFrom-Json).cases
{setup}
$analysisBlock = [ScriptBlock]::Create(@'
{analysis}
{chr(39)}@)
Set-Location -LiteralPath $repoRoot
. $analysisBlock
$before = [IO.File]::ReadAllText($metrics)
$beforeResponse = [IO.File]::ReadAllText($response)
$beforeStates = @($cases | ForEach-Object {{ [IO.File]::ReadAllText($_.solver_summary) }})
[IO.File]::WriteAllText((Join-Path $repoRoot '{state_relative}'), "raise RuntimeError('LIVE_STATE_METRICS_USED')")
. $analysisBlock
$unchanged = $before -ceq [IO.File]::ReadAllText($metrics) -and $beforeResponse -ceq [IO.File]::ReadAllText($response)
for ($index=0; $index -lt $cases.Count; $index++) {{
    $unchanged = $unchanged -and $beforeStates[$index] -ceq [IO.File]::ReadAllText($cases[$index].solver_summary)
}}
$statePath = Get-FrozenPythonPackageFile -Package $frozenAnalysisPackage -RelativePath '{state_relative}'
Remove-Item -LiteralPath $statePath
$missing = $null
try {{ . $analysisBlock }} catch {{ $missing=$_.Exception.Message }}
@{{unchanged=$unchanged;missing=$missing;metrics=(Get-Content -LiteralPath $metrics -Raw | ConvertFrom-Json);
   source_state=(Get-Content -LiteralPath $cases[3].solver_summary -Raw | ConvertFrom-Json)}} |
    ConvertTo-Json -Depth 20 | Set-Content -LiteralPath {_ps(receipt)} -Encoding UTF8
""", encoding="utf-8")
            completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script)],
                                       cwd=root, capture_output=True, text=True, errors="replace", timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(receipt.read_text(encoding="utf-8-sig"))
            self.assertTrue(result["unchanged"])
            self.assertIn("missing or outside", result["missing"])
            self.assertEqual(result["source_state"]["metrics_authority"], "python_canonical_particle_state")
            self.assertEqual(result["source_state"]["hits"], 4)
            self.assertEqual(result["metrics"]["status"], "PASS")
            self.assertEqual(result["metrics"]["sampled_response_analysis"]["interpolated_main_peak_fwhm_Th"], 1.75)

    def test_interface_comsol_worker_imports_actual_frozen_core(self) -> None:
        """Run the production worker import boundary in isolated Python."""
        source = COMSOL_RUNNER.read_text(encoding="utf-8")
        start = source.index("import importlib,json,pathlib,runpy,sys")
        code = source[start:source.index("raw=json.loads", start)]
        code += "\nfrom msplatform.contracts.particle_physics import kinetic_energy_ev, AMU_KG, ELEMENTARY_CHARGE_C\n"
        code += "assert kinetic_energy_ev(1.,1.,0.,0.) == .5*AMU_KG/ELEMENTARY_CHARGE_C\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = enumerate_python_sources(REPO_ROOT, package_roots=(
                'common/contracts', 'projects/rf_multipole_ion_optics/analysis', 'src/msplatform'),
                module_paths=('projects/rf_multipole_ion_optics/simion/ion11_source_adapter.py',),
                resource_suffixes=('.schema.json',))
            for relative in paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO_ROOT / relative, target)
            command = [sys.executable, '-I', '-B', '-c', code, str(root), *(['unused'] * 9)]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                    encoding='utf-8', timeout=60, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            origins = json.loads((root / 'unused').read_text(encoding='utf-8'))
            self.assertTrue(all(Path(path).is_relative_to(root) for path in origins.values()))
            self.assertTrue(Path(origins['msplatform.contracts.particle_physics']).is_relative_to(root / 'src'))
            adapter = root / 'projects/rf_multipole_ion_optics/simion/ion11_source_adapter.py'
            self.assertEqual(Path(origins['projects.rf_multipole_ion_optics.simion.ion11_source_adapter']), adapter)
            adapter_bytes = adapter.read_bytes()
            adapter.unlink()
            missing_adapter = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                             encoding='utf-8', timeout=60, check=False)
            self.assertNotEqual(missing_adapter.returncode, 0)
            self.assertIn('ion11_source_adapter', missing_adapter.stderr)
            adapter.write_bytes(adapter_bytes)
            shutil.rmtree(root / 'src')
            missing = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                     encoding='utf-8', timeout=60, check=False)
            self.assertNotEqual(missing.returncode, 0)
            self.assertTrue('analysis escaped frozen source' in missing.stderr or
                            "No module named 'msplatform'" in missing.stderr, missing.stderr)

    def test_both_runners_use_the_isolated_frozen_package_contract(self) -> None:
        """Generate real source bundles from both actual runner package declarations."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = f"""
$ErrorActionPreference='Stop'
$repoRoot={_ps(REPO_ROOT)};$python={_ps(sys.executable)}
. {_ps(SUPPORT)}
. {_ps(HELPER)} -ExecutionResourcePath {_ps(REPO_ROOT / 'src/msplatform/execution/resources/frozen_python_package.ps1')}
$results=@()
"""
            for index, runner in enumerate((COMSOL_RUNNER, SIMION_RUNNER)):
                script += f"""
$t=$null;$e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({_ps(runner)},[ref]$t,[ref]$e)
if($e.Count){{throw 'Actual runner did not parse'}}
$declaration=$ast.Find({{param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$frozenPythonRelativePaths'}},$true)
Invoke-Expression $declaration.Extent.Text
$paths=Get-FrozenPythonPackageExecutionPaths -RelativePaths $frozenPythonRelativePaths
$package=New-FrozenPythonPackage -Python $python -SourceRoot $repoRoot -CodeRoot {_ps(root / str(index))} -RelativePaths $frozenPythonRelativePaths
$execution=Invoke-IsolatedFrozenPythonModule -Python $python -Package $package `
 -Module 'projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table' `
 -Arguments @('--source-family',{_ps(SOURCE_FAMILY)},'--distribution',{_ps(DISTRIBUTION)},
 '--resolved-design',{_ps(RESOLVED)},'--particle-count','4','--bundle-output-dir',{_ps(root / ('bundle-' + str(index)))}) `
 -DistributionNames @('numpy') `
 -RequiredModuleNames @('projects.rf_multipole_ion_optics.workflows.interface_readiness.particle_source_policy') `
 -ForbiddenRoots @($repoRoot)
$results+=@{{files=@($package.files.relative_path);paths=$paths;executed=$execution.module_invoked;
 bundle=(Get-Content -Raw -LiteralPath {_ps(root / ('bundle-' + str(index)) / 'paired_particle_bundle.json')}|ConvertFrom-Json)}}
"""
            script += '$results|ConvertTo-Json -Depth 8 -Compress'
            completed = subprocess.run(
                ['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                cwd=root, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            results = json.loads(completed.stdout[completed.stdout.index('[{'):])
            self.assertEqual(results[0]['bundle']['sample_family_sha256'], results[1]['bundle']['sample_family_sha256'])
            for result in results:
                files = result['files']
                self.assertTrue(result['executed'])
                self.assertEqual(result['paths'], ['inputs/code/' + path for path in files])
                self.assertIn('projects/rf_multipole_ion_optics/analysis/paired_particle_source_bundle.py', files)
                self.assertIn('projects/rf_multipole_ion_optics/analysis/rf_event_table_validation.py', files)
                self.assertIn('projects/rf_multipole_ion_optics/simion/ion11_source_adapter.py', files)
                self.assertNotIn('projects/rf_multipole_ion_optics/analysis/__init__.py', files)
                self.assertFalse(any('/tests/' in path or Path(path).name.startswith('test_') for path in files))

    def test_package_selector_uses_utf8_for_unicode_source_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            junction = root / "源码根"
            created = subprocess.run(
                ['cmd', '/d', '/c', 'mklink', '/J', str(junction), str(REPO_ROOT)],
                cwd=root, capture_output=True, text=True, errors='replace', timeout=20,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            try:
                self.assertEqual(junction.resolve(), REPO_ROOT.resolve())
                script = f"""
$ErrorActionPreference='Stop'
. {_ps(HELPER)} -ExecutionResourcePath {_ps(REPO_ROOT / 'src/msplatform/execution/resources/frozen_python_package.ps1')}
$OutputEncoding=[Text.ASCIIEncoding]::new()
$before=$OutputEncoding
$one=Get-FrozenPythonPackageRelativePaths -SourceRoot {_ps(junction)} `
 -Python {_ps(sys.executable)} -PythonPackages @('common/contracts')
$two=Get-FrozenPythonPackageRelativePaths -SourceRoot {_ps(REPO_ROOT)} `
 -Python {_ps(sys.executable)} -PythonPackages @('common/contracts')
@{{one=@($one);two=@($two);restored=[object]::ReferenceEquals($before,$OutputEncoding)}}|ConvertTo-Json -Compress
"""
                completed = subprocess.run(
                    ['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                    cwd=root, capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result['one'], result['two'])
                self.assertIn('common/contracts/file_identity.py', result['one'])
                self.assertTrue(result['restored'])
            finally:
                # Remove only this verified directory junction, never its source target.
                os.rmdir(junction)

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

    def test_package_aggregate_uses_selected_builder_and_refuses_host_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / 'selected/src/msplatform'
            shutil.copytree(REPO_ROOT / 'src/msplatform', selected, ignore=shutil.ignore_patterns('__pycache__'))
            source = root / 'data'
            source.mkdir()
            (source / 'owned.py').write_bytes(b'value = 1\r\n')
            command = f"""
$ErrorActionPreference='Stop'
. {_ps(HELPER)} -ExecutionResourcePath {_ps(selected / 'execution/resources/frozen_python_package.ps1')}
$package=New-FrozenPythonPackage -Python {_ps(sys.executable)} -SourceRoot {_ps(source)} `
 -CodeRoot {_ps(root / 'copy')} -RelativePaths @('owned.py')
if($package.files.Count-ne1-or$package.files[0].relative_path-cne'owned.py'){{throw 'Selected builder lost its inventory'}}
if($package.files[0].sha256-cne(Get-FileHash -LiteralPath {_ps(source / 'owned.py')} -Algorithm SHA256).Hash){{throw 'Selected builder changed its identity convention'}}
Remove-Item -LiteralPath {_ps(selected / 'execution/inputs.py')}
try{{
 New-FrozenPythonPackage -Python {_ps(sys.executable)} -SourceRoot {_ps(source)} `
  -CodeRoot {_ps(root / 'refused')} -RelativePaths @('owned.py')
 throw 'Missing selected builder accepted'
}}catch{{if($_.Exception.Message-notlike'Selected Python inputs implementation is missing:*'){{throw}}}}
Write-Output 'SELECTED_BUILDER_MISSING_REJECTED'
exit 0
"""
            completed = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', command],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn('SELECTED_BUILDER_MISSING_REJECTED', completed.stdout)
            self.assertEqual((root / 'copy/owned.py').read_bytes(), (source / 'owned.py').read_bytes())
            self.assertFalse((root / 'refused').exists())
            self.assertTrue((REPO_ROOT / 'src/msplatform/execution/inputs.py').is_file())

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
                "projects.rf_multipole_ion_optics.analysis",
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
                / "rf_multipole_ion_optics"
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
. {_ps(HELPER)} -ExecutionResourcePath {_ps(REPO_ROOT / 'src/msplatform/execution/resources/frozen_python_package.ps1')}
$package = New-FrozenPythonPackage -Python {_ps(sys.executable)} -SourceRoot {_ps(source_snapshot)} `
    -CodeRoot {_ps(code_root)} -RelativePaths @(
        {relative_paths}
    )
Remove-Item -LiteralPath {_ps(source_snapshot)} -Recurse
$module = 'projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table'
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
$originalFiles = @($package.files)
try {{
foreach ($entry in $originalFiles) {{
    $package.files = @($entry) + @($originalFiles | Where-Object {{ $_.path -cne $entry.path }})
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
}} finally {{ $package.files = $originalFiles }}
$generator = Get-FrozenPythonPackageFile -Package $package -RelativePath `
    'projects/rf_multipole_ion_optics/workflows/interface_readiness/generate_particle_table.py'
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
                errors="replace",
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
            self.assertEqual(package["package_roots"], python_import_roots(code_root))
            self.assertEqual(len(package["files"]), len(frozen_relative_paths))
            self.assertEqual(
                execution["python_path"],
                os.pathsep.join(python_import_roots(code_root)),
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


    def test_mass_filter_analysis_packages_and_failure_boundaries(self) -> None:
        workflow = PROJECT_ROOT / "workflows" / "mass_filter_reference"
        mode_path = PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json"
        baseline_path = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        masses = mode["mass_scan_spec"]["paired_source_masses_Th"]
        center = min(masses, key=lambda mass: abs(mass - mode["mass_scan_spec"]["calibration_mass_Th"]))
        simion_source = (workflow / "run_simion.ps1").read_text(encoding="utf-8")
        analysis_start = simion_source.index("$analysisExitCode = 0\n")
        decision = "$physicalDecision = [string]$massMetrics.status"
        analysis_end = simion_source.index(decision, analysis_start) + len(decision)
        analysis_block = simion_source[analysis_start:analysis_end]
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            particles = root / "particles.ion"
            with particles.open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerows(
                    (0, mass, 1, 0, 0, 0, 0, 0, 2, 1, 0) for mass in masses
                )
            for status in ("PASS", "FAIL"):
                with (root / f"{status}.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=("particle_id", "event", "status"))
                    writer.writeheader()
                    writer.writerows(
                        {"particle_id": index, "event": "terminal", "status":
                         "transmitted" if status == "PASS" and mass == center else "lost"}
                        for index, mass in enumerate(masses, 1)
                    )
            poison_root = root / "poison"
            poison = poison_root / "common" / "analysis" / "peak_metrics.py"
            poison.parent.mkdir(parents=True)
            poison.write_text("raise RuntimeError('LIVE_ANALYSIS_FALLBACK_USED')\n", encoding="utf-8")
            result_path = root / "result.json"
            script = [f"""
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. {_ps(SUPPORT)}
. {_ps(HELPER)} -ExecutionResourcePath {_ps(REPO_ROOT / 'src/msplatform/execution/resources/frozen_python_package.ps1')}
$repoRoot = {_ps(REPO_ROOT)}
$projectRoot = {_ps(PROJECT_ROOT)}
$python = {_ps(Path(sys.executable).resolve())}
$fixtureRoot = {_ps(root)}
$env:PYTHONPATH = {_ps(poison_root)}
$env:PYTHONNOUSERSITE = 'restore-site'
$env:PYTHONDONTWRITEBYTECODE = 'restore-bytecode'
$packages = [ordered]@{{}}
$decisions = [ordered]@{{}}
$rejections = [ordered]@{{}}
$startingDirectory = (Get-Location).Path
"""]
            for runner_name in ("run_simion.ps1", "run_comsol.ps1", "compare_responses.ps1"):
                input_directory = root / Path(runner_name).stem
                input_directory.mkdir()
                script.extend((
                    "$inputDir = " + _ps(input_directory),
                    "$frozenInterface = Join-Path $inputDir 'interface_contract.json'",
                    "$frozenNumericalContract = Join-Path $inputDir 'simion_solver_numerics.json'",
                    "$SolverNumericsContractPath = " + _ps(PROJECT_ROOT / 'variants/quadrupole/config/simion_solver_numerics.json'),
                    _mass_analysis_setup(workflow / runner_name),
                    """
$execution = Invoke-IsolatedFrozenPythonModule `
    -Python $python -Package $frozenAnalysisPackage -Module $analysisModule `
    -Arguments @('--help') -DistributionNames $analysisDistributions `
    -RequiredModuleNames $analysisRequiredModules -ForbiddenRoots @($repoRoot,$projectRoot)
""",
                    "$packages[" + _ps(runner_name) + "] = [ordered]@{package=$frozenAnalysisPackage;execution=$execution}",
                ))
                if runner_name != "run_simion.ps1":
                    continue
                script.append(f"""
$particlePath = {_ps(particles)}
$frozenBaseline = {_ps(baseline_path)}
$frozenMode = {_ps(mode_path)}
$moduleFailure = $null
try {{
    Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenAnalysisPackage `
        -Module $analysisModule -Arguments @('--invalid-frozen-test-option') `
        -DistributionNames $analysisDistributions -RequiredModuleNames $analysisRequiredModules `
        -ForbiddenRoots @($repoRoot,$projectRoot) | Out-Null
}} catch {{
    $moduleFailure = [ordered]@{{message=$_.Exception.Message;exit_code=$_.Exception.Data['exit_code']}}
}}
$analysisBlock = [ScriptBlock]::Create(@'
{analysis_block}
{chr(39)}@)
foreach ($status in @('PASS','FAIL')) {{
    $particleStateCsv = Join-Path $fixtureRoot "$status.csv"
    $massResponseCsv = Join-Path $fixtureRoot "$status-response.csv"
    $massMetricsJson = Join-Path $fixtureRoot "$status-metrics.json"
    $massResponseFigure = Join-Path $fixtureRoot "$status-figure.png"
    . $analysisBlock
    $decisions[$status] = [ordered]@{{decision=$physicalDecision;exit_code=$analysisExitCode}}
}}
# Keep the complete FAIL outputs in place: they must not mask isolation failures.
$peakPath = Get-FrozenPythonPackageFile -Package $frozenAnalysisPackage `
    -RelativePath src/msplatform/analysis/peak_metrics.py
$peakPath = [IO.Path]::GetFullPath($peakPath)
if (-not $peakPath.StartsWith($fixtureRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {{ throw 'Fixture path escaped temporary root.' }}
$originalPeak = [IO.File]::ReadAllBytes($peakPath)
foreach ($scenario in @('probe','hash','missing')) {{
    $savedModules = $analysisRequiredModules
    if ($scenario -eq 'probe') {{ $analysisRequiredModules += 'common.analysis.missing_test_dependency' }}
    if ($scenario -eq 'hash') {{ [IO.File]::AppendAllText($peakPath,'# changed') }}
    if ($scenario -eq 'missing') {{ Remove-Item -LiteralPath $peakPath }}
    $rejections[$scenario] = $null
    try {{ . $analysisBlock }} catch {{ $rejections[$scenario] = $_.Exception.Message }} finally {{
        $analysisRequiredModules = $savedModules
        [IO.File]::WriteAllBytes($peakPath,$originalPeak)
    }}
}}
# A matching legacy message alone must not turn an infrastructure error into physical FAIL.
$invokeBody = (Get-Command Invoke-IsolatedFrozenPythonModule).ScriptBlock
try {{
    function Invoke-IsolatedFrozenPythonModule {{ throw 'Frozen Python module failed with exit code 1.' }}
    $rejections['message_only'] = $null
    try {{ . $analysisBlock }} catch {{ $rejections['message_only'] = $_.Exception.Message }}
}} finally {{
    Set-Item Function:Invoke-IsolatedFrozenPythonModule -Value $invokeBody
}}
""")
            script.append(f"""
$result = [ordered]@{{
    packages=$packages
    decisions=$decisions
    rejections=$rejections
    module_failure=$moduleFailure
    environment_restored=(
        $env:PYTHONPATH -ceq {_ps(poison_root)} -and
        $env:PYTHONNOUSERSITE -ceq 'restore-site' -and
        $env:PYTHONDONTWRITEBYTECODE -ceq 'restore-bytecode' -and
        (Get-Location).Path -ceq $startingDirectory
    )
}}
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath {_ps(result_path)} -Encoding UTF8
""")
            script_path = root / "exercise.ps1"
            script_path.write_text("\n".join(script), encoding="utf-8")
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
                cwd=root, env=os.environ.copy(), capture_output=True, text=True,
                errors="replace", timeout=120, check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(result["decisions"], {
                "PASS": {"decision": "PASS", "exit_code": 0},
                "FAIL": {"decision": "FAIL", "exit_code": 1},
            })
            self.assertIn("dependency probe failed", result["rejections"]["probe"])
            self.assertIn("hash differs", result["rejections"]["hash"])
            self.assertIn("missing or outside", result["rejections"]["missing"])
            self.assertEqual(result["rejections"]["message_only"], "Frozen Python module failed with exit code 1.")
            self.assertEqual(result["module_failure"], {
                "message": "Frozen Python module failed with exit code 2.", "exit_code": 2,
            })
            self.assertTrue(result["environment_restored"])
            self.assertNotIn("LIVE_ANALYSIS_FALLBACK_USED", completed.stderr)
            for runner_name, record in result["packages"].items():
                with self.subTest(runner=runner_name):
                    code_root = Path(record["package"]["code_root"]).resolve()
                    origins = {item["name"]: Path(item["origin"]).resolve()
                               for item in record["execution"]["frozen_modules"]}
                    for module in (
                        "msplatform.analysis.mass_response",
                        "msplatform.ion_release.paired_mass_scan",
                        "msplatform.io.file_identity",
                        "msplatform.analysis.peak_metrics",
                    ):
                        self.assertIn(module, origins)
                    if runner_name != "compare_responses.ps1":
                        frozen_python = {Path(entry["path"]).resolve() for entry in record["package"]["files"]
                                         if entry["relative_path"].endswith(".py")}
                        self.assertLessEqual(set(origins.values()), frozen_python)
                    self.assertTrue(all(origin.is_relative_to(code_root) for origin in origins.values()))
                    self.assertEqual(record["execution"]["python_path"], os.pathsep.join(python_import_roots(code_root)))
                    self.assertTrue(record["execution"]["module_invoked"])
                    self.assertTrue(record["execution"]["python_no_user_site"])
                    self.assertTrue(record["execution"]["python_no_bytecode"])


if __name__ == "__main__":
    unittest.main()
