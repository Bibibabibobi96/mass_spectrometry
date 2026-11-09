from __future__ import annotations

import ast
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from msplatform.execution.inputs import python_import_roots

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = REPO_ROOT / "integrations"
INVENTORY = INTEGRATION_ROOT / "config/runtime_dependencies.json"
DEPENDENCIES = INTEGRATION_ROOT / "runtime/dependencies.ps1"


def snapshot_environment(snapshot: Path) -> dict[str, str]:
    return dict(os.environ, PYTHONPATH=os.pathsep.join(python_import_roots(snapshot)), PYTHONNOUSERSITE="1")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class DependencyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_single_reflection_field_plan_uses_only_frozen_module_and_lua_resources(self) -> None:
        from integrations.tests.test_single_reflection_field_stage import prepared
        from msplatform.workflows.single_reflection_flight.field_plan import build_field_plan

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "study").mkdir()
            run, _ = prepared(root / "study", entrance_refinement=True)
            expected = build_field_plan(run / "inputs", Path(sys.executable))
            destination = root / "snapshot_inputs"
            script = root / "freeze.ps1"
            script.write_text("""param($Repo,$Destination,$Python)
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
$null=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') -InputDir $Destination -OwnerId instrument_assembly -ConsumerId single_reflection_flight
""", encoding="utf-8")
            frozen = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                                    str(REPO_ROOT), str(destination), sys.executable], cwd=root,
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = destination / "runtime_snapshot"
            module = "src/msplatform/workflows/single_reflection_flight/field_plan.py"
            resources = ["src/msplatform/backends/simion/resources/" + name for name in
                         ("build_dirichlet_patch_operating_pa.lua", "export_detached_standalone_pa.lua")]
            self.assertFalse((snapshot / "integrations/workflows/single_reflection_flight/field_plan.py").exists())
            selected = load(destination / "code_inventory.json")["dependencies"]
            for relative in [module, *resources]:
                self.assertEqual(sum(row["source_repo_path"] == relative for row in selected), 1)
            for relative in [module, *resources]:
                self.assertEqual((snapshot / relative).read_bytes(), (REPO_ROOT / relative).read_bytes())
            code = """import sys,json
from pathlib import Path
sys.path[:0]=json.loads(sys.argv[1])
from msplatform.workflows.single_reflection_flight import field_plan
from msplatform.backends.simion import resources
root=Path.cwd().resolve()
assert Path(field_plan.__file__).resolve().is_relative_to(root)
assert Path(resources.__file__).resolve().is_relative_to(root)
print(json.dumps(field_plan.build_field_plan(Path(sys.argv[2]),Path(sys.argv[3]))))
"""
            command = [sys.executable, "-I", "-B", "-c", code,
                       json.dumps(python_import_roots(snapshot)), str(run / "inputs"), sys.executable]
            def cold():
                return subprocess.run(command, cwd=snapshot, capture_output=True, text=True,
                                      encoding="utf-8", timeout=60)
            result = cold()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), expected)
            self.assertEqual([d["domain_id"] for d in expected["domains"]], ["parent", "entrance_refinement"])
            for relative in [module, *resources]:
                with self.subTest(missing=relative):
                    target = snapshot / relative
                    original = target.read_bytes()
                    target.unlink()
                    try:
                        missing = cold()
                        self.assertNotEqual(missing.returncode, 0, missing.stdout)
                        self.assertIn(target.stem, missing.stderr)
                    finally:
                        target.write_bytes(original)

    def test_dependency_enumerator_single_package_resources_preserve_exact_inventory(self) -> None:
        from msplatform.execution.inputs import enumerate_python_sources

        body = DEPENDENCIES.read_text(encoding="utf-8").split("  $enumerator = @'\n", 1)[1].split("\n'@", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("__init__.py", "a/__init__.py", "a/code.py", "a/model.schema.json",
                         "a/not_selected.txt", "b/__init__.py", "b/code.py", "b/not_selected.schema.json",
                         "b/selected.txt"):
                target = root / "src/pkg" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("{}", encoding="utf-8")
            selections = [dict(source_repo_path="src/pkg/a", consumers=["first"], resource_suffixes=[".schema.json"]),
                          dict(source_repo_path="src/pkg/b", consumers=["second"], resource_suffixes=[".txt"])]
            for packages, expected_calls in ((selections[:1], 1), (selections, 3)):
                with self.subTest(package_count=len(packages)):
                    group = dict(provider_scope="repository_core", provider_project="pkg", provider_repo_path="src/pkg",
                                 python_packages=packages, python_modules=[])
                    request = dict(source_root=str(root), providers=[group])
                    expected_paths = set(enumerate_python_sources(root,
                        package_roots=[row["source_repo_path"] for row in packages], provider_root="src/pkg"))
                    for row in packages:
                        expected_paths.update(enumerate_python_sources(root, package_roots=[row["source_repo_path"]],
                            provider_root="src/pkg", resource_suffixes=row["resource_suffixes"]))
                    expected = []
                    for path in sorted(expected_paths):
                        source = Path(path)
                        consumers = set()
                        for row in packages:
                            selected = Path(row["source_repo_path"])
                            if (source == selected or selected in source.parents
                                    or (source.name == "__init__.py" and source.parent in (selected, *selected.parents))):
                                consumers.update(row["consumers"])
                        expected.append({key: group[key] for key in ("provider_scope", "provider_project", "provider_repo_path")}
                            | dict(id=("python:" if path.endswith(".py") else "resource:") + path,
                                   source_repo_path=path, consumers=sorted(consumers)))
                    output = io.StringIO()
                    with mock.patch.object(sys, "argv", ["enumerator", str(REPO_ROOT)]), \
                         mock.patch.object(sys, "stdin", io.StringIO(json.dumps(request))), \
                         contextlib.redirect_stdout(output), \
                         mock.patch("msplatform.execution.inputs.enumerate_python_sources", wraps=enumerate_python_sources) as enumerate_sources:
                        exec(compile(body, "dependency-enumerator", "exec"), {})
                    self.assertEqual(json.loads(output.getvalue()), expected)
                    self.assertEqual(enumerate_sources.call_count, expected_calls)
                    self.assertNotIn("src/pkg/a/not_selected.txt", expected_paths)
                    self.assertNotIn("src/pkg/b/not_selected.schema.json", expected_paths)

    def test_dependency_enumerator_optimized_route_keeps_missing_overlap_and_containment_errors(self) -> None:
        body = DEPENDENCIES.read_text(encoding="utf-8").split("  $enumerator = @'\n", 1)[1].split("\n'@", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/pkg/a").mkdir(parents=True)
            (root / "src/pkg/a/code.py").write_text("VALUE = 1\n", encoding="utf-8")
            cases = [(["src/pkg/missing"], [], FileNotFoundError),
                     (["src/pkg/a"], ["src/pkg/missing.py"], FileNotFoundError),
                     (["src/pkg/a"], ["src/pkg/a/code.py"], ValueError),
                     (["src/pkg"], [], ValueError)]
            for package_paths, module_paths, error in cases:
                with self.subTest(packages=package_paths, modules=module_paths):
                    group = dict(provider_scope="repository_core", provider_project="pkg", provider_repo_path="src/pkg/a",
                        python_packages=[dict(source_repo_path=value, consumers=["first"], resource_suffixes=[".schema.json"])
                                         for value in package_paths],
                        python_modules=[dict(source_repo_path=value, consumers=["first"]) for value in module_paths])
                    request = dict(source_root=str(root), providers=[group])
                    with mock.patch.object(sys, "argv", ["enumerator", str(REPO_ROOT)]), \
                         mock.patch.object(sys, "stdin", io.StringIO(json.dumps(request))), \
                         contextlib.redirect_stdout(io.StringIO()), self.assertRaises(error):
                        exec(compile(body, "dependency-enumerator", "exec"), {})

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_frozen_legacy_process_loader_requires_its_canonical_dispatch_body(self) -> None:
        with tempfile.TemporaryDirectory(prefix="frozen PS dispatch 工作 ") as directory:
            root = Path(directory)
            inputs = root / "inputs"
            freeze_script = root / "freeze.ps1"
            freeze_script.write_text("""param($Repo,$Destination,$Python)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
$null=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') -InputDir $Destination -OwnerId instrument_assembly -ConsumerId local_frontend
""", encoding="utf-8", newline="\n")
            environment = dict(os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1",
                               SIMULATION_PYTHON_EXE=sys.executable,
                               MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root / "host.sqlite3"))
            frozen = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(freeze_script),
                str(REPO_ROOT), str(inputs), sys.executable], cwd=root, env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = inputs / "runtime_snapshot"
            relative = "src/msplatform/execution/resources/simion_dispatch_support.ps1"
            dispatch = snapshot / relative
            self.assertEqual(dispatch.read_bytes(), (REPO_ROOT / relative).read_bytes())
            loader = root / "load.ps1"
            loader.write_text("""param($Snapshot)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$ErrorActionPreference='Stop'
. (Join-Path $Snapshot 'common/resource_budget_support.ps1')
$expected=[IO.Path]::GetFullPath((Join-Path $Snapshot 'src/msplatform/execution/resources/simion_dispatch_support.ps1'))
foreach($name in @('Start-ObservedFormalProcess','Invoke-SimionBatchPhase','Invoke-ResourceBudgetedProcesses')){
 $command=Get-Command -Name $name -CommandType Function -ErrorAction Stop
 $actual=[IO.Path]::GetFullPath([string]$command.ScriptBlock.File)
 if(-not $actual.Equals($expected,[StringComparison]::OrdinalIgnoreCase)){throw "Dispatch function escaped frozen source: $name"}
}
'FROZEN_DISPATCH_BODY=PASS'
""", encoding="utf-8", newline="\n")
            command = [shutil.which("pwsh"), "-NoProfile", "-File", str(loader), str(snapshot)]
            loaded = subprocess.run(command, cwd=snapshot, env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="backslashreplace", timeout=30)
            self.assertEqual(loaded.returncode, 0, loaded.stdout + loaded.stderr)
            self.assertIn("FROZEN_DISPATCH_BODY=PASS", loaded.stdout)
            # A new process cannot retain the previously loaded function or
            # fall back to the author checkout/installed resource after deletion.
            dispatch.unlink()
            missing = subprocess.run(command, cwd=snapshot, env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="backslashreplace", timeout=30)
            self.assertNotEqual(missing.returncode, 0, missing.stdout + missing.stderr)
            self.assertIn("simion_dispatch_support.ps1", missing.stdout + missing.stderr)
            self.assertNotIn("FROZEN_DISPATCH_BODY=PASS", missing.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_scientific_core_provider_freezes_src_resources_without_installed_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix='src dependency 工作 ') as directory:
            root = Path(directory)
            output = root / 'inputs'
            script = f"""
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
. '{DEPENDENCIES}'
$f=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend
$f.import_roots|ConvertTo-Json -Compress
"""
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-Command', script], cwd=root,
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='backslashreplace', timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            snapshot = output / 'runtime_snapshot'
            roots = json.loads(result.stdout)
            self.assertEqual(roots, python_import_roots(snapshot))
            entries = load(output / 'code_inventory.json')['dependencies']
            policy_relative = "src/msplatform/contracts/particle_count_policy.json"
            policy_entries = [row for row in entries if row["source_repo_path"] == policy_relative]
            self.assertEqual(len(policy_entries), 1)
            self.assertEqual(policy_entries[0]["provider_scope"], "repository_core")
            self.assertEqual(policy_entries[0]["provider_project"], "msplatform")
            self.assertEqual(policy_entries[0]["id"], "msplatform_contracts_particle_count_policy_json")
            self.assertEqual(policy_entries[0]["consumers"],
                ["local_frontend", "prepared_joint", "accelerator_interface", "cooled_frontend", "oa_mr"])
            self.assertEqual((snapshot/policy_relative).read_bytes(), (REPO_ROOT/policy_relative).read_bytes())
            resources = [row for row in entries if row['source_repo_path'].endswith('.schema.json')
                         and row['provider_scope'] == 'repository_core']
            expected = sorted(path.name for path in (REPO_ROOT/'src/msplatform').rglob('*.schema.json'))
            self.assertEqual(sorted(Path(row['source_repo_path']).name for row in resources), expected)
            self.assertTrue(all(row['id'] == 'resource:' + row['source_repo_path'] for row in resources))
            code = '''import json,sys
from pathlib import Path
sys.path[:0]=json.loads(sys.argv[1])
from msplatform.assembly import resolve_assembly
from msplatform.contracts import machine_contracts, particle_count_policy
root=Path(sys.argv[2]).resolve()
assert Path(resolve_assembly.__file__).resolve().is_relative_to(root/'src')
assert Path(machine_contracts.__file__).resolve().is_relative_to(root/'src')
assert particle_count_policy.POLICY_PATH.resolve()==root/'src/msplatform/contracts/particle_count_policy.json'
assert particle_count_policy.load_particle_count_policy()['standard_particle_counts']==[100,1000,5000]
try: machine_contracts.validate_schema({}, 'assembly_recipe.schema.json')
except machine_contracts.ContractError: pass
else: raise AssertionError('invalid recipe accepted')
print('FROZEN_SRC_CORE=PASS')
'''
            command = [sys.executable, '-X', 'utf8', '-I', '-B', '-c', code, json.dumps(roots), str(snapshot)]
            complete = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
            for relative in ('src/msplatform/assembly/resolve_assembly.py',
                             'src/msplatform/contracts/schemas/assembly_recipe.schema.json',
                             'src/msplatform/contracts/particle_count_policy.json'):
                target = snapshot / relative
                payload = target.read_bytes()
                target.unlink()
                try:
                    missing = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
                    self.assertNotEqual(missing.returncode, 0, missing.stdout + missing.stderr)
                    self.assertNotIn('FROZEN_SRC_CORE=PASS', missing.stdout)
                finally:
                    target.write_bytes(payload)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_accelerator_interface_imports_ip_validator_from_frozen_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "inputs"
            freeze = f". '{DEPENDENCIES}'; $null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId accelerator_interface"
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", freeze],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            snapshot = inputs / "runtime_snapshot"
            code = '''
from pathlib import Path
from integrations.workflows.accelerator_interface import prepare
from msplatform.workflows.multipole_ip import prepare as handoff
from msplatform.contracts.machine_contracts import ContractError
from projects.dual_pressure_rectilinear_ion_processor.analysis import functional
import tempfile
root = Path.cwd().resolve()
for module in (prepare, functional, handoff):
    Path(module.__file__).resolve().relative_to(root)
handoff.SCHEMA.resolve().relative_to(root)
assert callable(functional.validate_configs)
with tempfile.TemporaryDirectory() as request_directory:
    invalid = Path(request_directory) / "request.json"
    invalid.write_text("{}", encoding="utf-8")
    try:
        handoff.load_request(invalid)
    except ContractError as error:
        assert "required" in str(error), str(error)
    else:
        raise AssertionError("frozen request schema must reject missing fields")
'''
            result = subprocess.run([sys.executable, "-B", "-s", "-c", code], cwd=snapshot,
                env=snapshot_environment(snapshot),
                capture_output=True, text=True, encoding="utf-8", errors="backslashreplace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_expanded_package_report_module_preserves_frozen_fly_reuse(self) -> None:
        from integrations.tests.test_single_reflection_continuation import SingleReflectionContinuationTests
        from msplatform.workflows.single_reflection_flight.continuation import prepare_phase_continuation

        fixture = SingleReflectionContinuationTests("run")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author = root / "author"
            # The isolated author is the actual provider closure, not a stub
            # enumerator or an import fallback to the checkout.
            from msplatform.execution.inputs import enumerate_python_sources
            contract = load(INVENTORY)
            paths = {row["source_repo_path"] for group in contract["providers"] for row in group["files"]}
            for group in contract["providers"]:
                if group["python_packages"] or group["python_modules"]:
                    package_roots = [row["source_repo_path"] for row in group["python_packages"]]
                    # Consumer-specific declarations may name a singleton that
                    # another consumer obtains through the whole package.
                    # The union author closure copies that module only once.
                    module_paths = [row["source_repo_path"] for row in group["python_modules"]
                                    if not any(Path(row["source_repo_path"]).is_relative_to(package)
                                               for package in package_roots)]
                    paths.update(enumerate_python_sources(REPO_ROOT,
                        package_roots=package_roots, module_paths=module_paths))
                    for row in group["python_packages"]:
                        if row.get("resource_suffixes"):
                            paths.update(enumerate_python_sources(REPO_ROOT,
                                package_roots=[row["source_repo_path"]], resource_suffixes=row["resource_suffixes"]))
            paths.update({"integrations/registry.json", "integrations/config/runtime_dependencies.json",
                          "integrations/runtime/dependencies.ps1"})
            for relative in paths:
                destination = author / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if relative.endswith(".pa0") and "iob_seed_placeholder_" in relative:
                    destination.write_bytes(b"INERT_TEST_SEED_NOT_A_PA\n")
                else:
                    shutil.copyfile(REPO_ROOT / relative, destination)

            def freeze(name):
                output = root / name
                script = f". '{DEPENDENCIES}'; $null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{author}' -ContractPath '{author / 'integrations/config/runtime_dependencies.json'}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId single_reflection_flight"
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                    cwd=author, capture_output=True, text=True, encoding="utf-8", timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return output / "runtime_snapshot"

            fixture.snapshot = freeze("first")
            event_module = "projects/rf_multipole_ion_optics/analysis/rf_event_table_validation.py"
            self.assertEqual(sum(row["source_repo_path"] == event_module
                                 for row in load(root / "first/code_inventory.json")["dependencies"]), 1)
            current = fixture._current_workbench()
            parent = fixture._parent(current)
            parent_before = {path.relative_to(parent): path.read_bytes()
                             for path in parent.rglob("*") if path.is_file()}
            report = author / "integrations/workflows/single_reflection_flight/package_report_only.py"
            report.write_text("TITLE = 'shipment provenance only'\n", encoding="utf-8")
            fixture.snapshot = freeze("report")
            inventory = load(root / "report/code_inventory.json")["dependencies"]
            self.assertIn("python:" + report.relative_to(author).as_posix(), {row["id"] for row in inventory})
            # Rebuild only small inert preparation records, never a native IOB.
            shutil.rmtree(fixture.run / "simion/full_instrument")
            current = fixture._current_workbench()
            result = prepare_phase_continuation(fixture.preparation, current, fixture.run, "baseline")
            self.assertEqual([row["action"] for row in result["plan"]["units"]], ["reuse", "reuse"])
            self.assertEqual({path.relative_to(parent): path.read_bytes()
                              for path in parent.rglob("*") if path.is_file()}, parent_before)
            shutil.rmtree(fixture.run / "inputs/continuation")
            # An actual numerical Program source change is still a dependency.
            generator = fixture.snapshot / "src/msplatform/backends/simion/resources/single_flight_pulse_hook.lua"
            self.assertTrue(generator.is_file())
            generator.write_text(generator.read_text() + "\n-- changed numerical Program implementation\n", encoding="utf-8")
            shutil.rmtree(fixture.run / "simion/full_instrument")
            current = fixture._current_workbench()
            with self.assertRaisesRegex(ValueError, "Program"):
                prepare_phase_continuation(fixture.preparation, current, fixture.run, "baseline")
            self.assertEqual({path.relative_to(parent): path.read_bytes()
                              for path in parent.rglob("*") if path.is_file()}, parent_before)

    def test_shared_single_reflection_fixture_expands_packages_without_large_seeds(self) -> None:
        from integrations.tests.test_support.single_reflection_execute_fixture import SingleReflectionExecuteFixture
        fixture = SingleReflectionExecuteFixture("run")
        with tempfile.TemporaryDirectory() as directory:
            author = fixture._prepare_source_template(Path(directory), load(INVENTORY), lightweight_seeds=True)
            self.assertTrue((author / "src/msplatform/workflows/single_reflection_flight/prepare.py").is_file())
            self.assertTrue((author / "src/msplatform/execution/inputs.py").is_file())
            self.assertTrue((author / "projects/orthogonal_accelerator/analysis/sectioned_geometry.py").is_file())
            resources = Path('src/msplatform/contracts/schemas')
            originals = sorted((REPO_ROOT / resources).glob('*.schema.json'))
            self.assertTrue(originals)
            self.assertEqual(sorted(path.name for path in (author / resources).glob('*.schema.json')),
                             [path.name for path in originals])
            for original in originals:
                self.assertEqual((author / resources / original.name).read_bytes(), original.read_bytes())
            seeds = list((author / "common/simion/assets/iob_instance_seeds").glob("iob_seed_placeholder_*.pa0"))
            self.assertEqual(len(seeds), 5)
            self.assertTrue(all(path.read_bytes() == b"INERT_TEST_SEED_NOT_A_PA\n" for path in seeds))

    def test_joint_finalization_owners_freeze_the_existing_public_adapter(self) -> None:
        entries = {item["source_repo_path"]: set(item["consumers"])
                   for group in load(INVENTORY)["providers"] for item in group["files"]}
        self.assertEqual(entries["common/contracts/run_artifact_workflow.ps1"],
                         {"prepared_joint", "oa_mr", "paired_accelerator_static_field",
                          "paired_accelerator_pulse", "local_frontend", "cooled_frontend",
                          "single_reflection_flight"})
        self.assertLessEqual(entries["common/contracts/run_artifact_workflow.ps1"],
                             entries["common/resource_budget_support.ps1"])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_prepared_joint_loads_shared_mr_continuation_guard_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory)/"inputs"
            freeze = f". '{DEPENDENCIES}'; $null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId prepared_joint"
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",freeze],cwd=REPO_ROOT,
                                    capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            snapshot = inputs/"runtime_snapshot"
            runtime = snapshot/"projects/parallel_mirror_dual_stripe_mr_tof/simion/native_corridor_runtime_support.ps1"
            load_runtime = f". '{runtime}'; if(-not (Get-Command Protect-MrtofContinuationEvidence -ErrorAction SilentlyContinue)){{throw 'missing frozen guard'}}"
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",load_runtime],cwd=snapshot,
                                    capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            environment = snapshot_environment(snapshot)
            result = subprocess.run([sys.executable,"-B","-s","-m",
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation","--help"],
                cwd=snapshot,env=environment,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_single_reflection_workflow_imports_form_a_dag(self) -> None:
        """Include deferred imports; they must not hide a reverse ownership edge."""
        prefix = "integrations.workflows.single_reflection_flight."
        paths = {prefix+name:INTEGRATION_ROOT/"workflows/single_reflection_flight"/f"{name}.py"
                 for name in ("runtime", "downstream_fields")}
        paths["msplatform.workflows.single_reflection_flight.pulse"] = REPO_ROOT/"src/msplatform/workflows/single_reflection_flight/pulse.py"
        paths["msplatform.workflows.single_reflection_flight.prepare"] = REPO_ROOT/"src/msplatform/workflows/single_reflection_flight/prepare.py"
        paths["msplatform.workflows.single_reflection_flight.collect"] = REPO_ROOT/"src/msplatform/workflows/single_reflection_flight/collect.py"
        paths["msplatform.workflows.single_reflection_flight.field_evidence"] = REPO_ROOT/"src/msplatform/workflows/single_reflection_flight/field_evidence.py"
        paths["msplatform.backends.simion.tracking_collection"] = REPO_ROOT/"src/msplatform/backends/simion/tracking_collection.py"
        paths["msplatform.results.single_reflection_continuation"] = REPO_ROOT/"src/msplatform/results/single_reflection_continuation.py"
        paths["msplatform.workflows.single_reflection_flight.continuation"] = REPO_ROOT/"src/msplatform/workflows/single_reflection_flight/continuation.py"
        graph = {}
        for name, source in paths.items():
            graph[name] = {
                node.module for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                if isinstance(node, ast.ImportFrom) and node.module in paths
            }

        def visit(name: str, chain: tuple[str, ...]) -> None:
            self.assertNotIn(name, chain, " -> ".join((*chain, name)))
            for dependency in graph[name]:
                visit(dependency, (*chain, name))

        for name in graph:
            visit(name, ())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_shared_capacity_contracts_import_from_actual_frozen_snapshot(self) -> None:
        """Import the real consumers with cwd and search path detached from live code."""
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "inputs"
            script = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId prepared_joint
"""
            freeze = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(freeze.returncode, 0, freeze.stdout + freeze.stderr)
            detached = inputs / "runtime_snapshot"
            code = '''
import sys
from pathlib import Path
from common.contracts import capacity_ledger, verify_artifact_layout
from common.contracts import gui_source_protection
from msplatform.execution import artifact_cache_contract, solver_review_retirement
root=Path(sys.argv[1]).resolve()
for module in (capacity_ledger,solver_review_retirement,verify_artifact_layout,artifact_cache_contract,gui_source_protection):
    Path(module.__file__).resolve().relative_to(root)
solver_review_retirement._assert_runtime_retirement_unprotected(root/'absent_artifacts',root/'absent_artifacts/projects/p/runs/source')
'''
            probe = subprocess.run([sys.executable, "-B", "-c", code, str(detached)], cwd=detached,
                env=snapshot_environment(detached), capture_output=True, text=True,
                encoding="utf-8", timeout=30)
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_prepared_snapshot_can_freeze_dependency_without_live_repository(self) -> None:
        """The PS freezer resolves its shared implementation from the snapshot."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            detached = inputs / "runtime_snapshot"
            script = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId prepared_joint
"""
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            destination = root / "second_inputs"
            # New process, no live-repository import. The source is an existing
            # frozen contract; the copy and receipt must bind its actual bytes.
            script = f"""
. '{detached / 'integrations/runtime/dependencies.ps1'}'
$dependency=[pscustomobject]@{{
 id='fixture';provider_scope='repository_common';provider_project='common';provider_repo_path='common'
 source_repo_path='common/contracts/run_artifact_support.ps1';frozen_filename='copied.ps1'
 run_input_name='fixture';consumers=@('prepared_joint')
}}
Copy-FrozenDependency -RepoRoot '{detached}' -InputDir '{destination}' -Dependency $dependency | ConvertTo-Json -Depth 5
"""
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=root,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(result.stdout)
            source = detached / "common/contracts/run_artifact_support.ps1"
            self.assertEqual((destination / "copied.ps1").read_bytes(), source.read_bytes())
            self.assertEqual(record["sha256"], hashlib.sha256(source.read_bytes()).hexdigest().upper())
            self.assertEqual(Path(record["snapshot_path"]), destination / "copied.ps1")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_prepared_joint_derives_scope_from_its_complete_frozen_assembly_closure(self) -> None:
        """Run the actual parent compiler detached, including non-Python schemas."""
        required = (
            "src/msplatform/assembly/resolve_assembly.py",
            "src/msplatform/contracts/machine_contracts.py",
            "src/msplatform/contracts/rigid_transform.py",
            "src/msplatform/contracts/schemas/assembly_recipe.schema.json",
            "src/msplatform/contracts/schemas/component_geometry_interface.schema.json",
            "src/msplatform/contracts/schemas/composition_plan.schema.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            parent = output / "parent.json"
            shutil.copyfile(INTEGRATION_ROOT / "config/recipes/multipole_ip_mr_y_minus55_plan.json", parent)
            freeze = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId prepared_joint
"""
            frozen = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", freeze],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            selected = {row["source_repo_path"] for row in load(output / "code_inventory.json")["dependencies"]}
            self.assertTrue(set(required) <= selected)
            snapshot = output / "runtime_snapshot"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
            statement = """
import json,sys
from pathlib import Path
from msplatform.assembly import resolve_assembly
assert Path(resolve_assembly.__file__).is_relative_to(Path.cwd())
parent=json.loads(Path(sys.argv[1]).read_text())
local=resolve_assembly.derive_assembly_scope(parent,local_scope=dict(
    instance_ids=['ion_processor','mrtof'],research_scope='frozen IP/MR segment',
    boundary_assumptions='upstream multipole metal excluded from this numerical domain'))
assert len(parent['recipe']['instances'])==3
assert local['recipe']==parent['recipe']
assert local['scope']==dict(kind='local',instance_ids=['ion_processor','mrtof'],
    connection_ids=['ip_to_mr'],boundary_connection_ids=['multipole_to_ip'])
print('FROZEN_PREPARED_JOINT_ASSEMBLY_SCOPE=PASS')
"""
            command = [sys.executable, "-B", "-s", "-c", statement, str(parent)]
            complete = subprocess.run(command, cwd=snapshot, env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
            self.assertIn("FROZEN_PREPARED_JOINT_ASSEMBLY_SCOPE=PASS", complete.stdout)
            for relative in required:
                with self.subTest(missing=relative):
                    resource = snapshot / relative
                    contents = resource.read_bytes()
                    resource.unlink()
                    try:
                        refused = subprocess.run(command, cwd=snapshot, env=environment,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
                        self.assertNotIn("FROZEN_PREPARED_JOINT_ASSEMBLY_SCOPE=PASS", refused.stdout)
                        self.assertIn(Path(relative).stem.split('.')[0], refused.stderr)
                    finally:
                        resource.write_bytes(contents)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_native_completion_provider_imports_in_each_frozen_consumer(self) -> None:
        consumers = load(INVENTORY)["consumer_ids"]
        for consumer in consumers:
            with self.subTest(consumer=consumer), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                script = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId {consumer}
"""
                frozen = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                    capture_output=True, text=True, encoding='utf-8', timeout=120)
                self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
                selected = load(output / "code_inventory.json")["dependencies"]
                paths = {row["source_repo_path"] for row in selected}
                self.assertIn("src/msplatform/execution/manifest_publication.py", paths)
                self.assertIn("common/contracts/capacity_protection.py", paths)
                self.assertIn("src/msplatform/execution/retention.py", paths)
                self.assertNotIn("common/contracts/artifact_retention.py", paths)
                self.assertEqual(len({row["id"] for row in selected}), len(selected))
                self.assertTrue(all(row["id"] == "python:" + row["source_repo_path"]
                                    for row in selected if row["source_repo_path"].endswith(".py")))
                snapshot = output / 'runtime_snapshot'
                environment = dict(os.environ, PYTHONNOUSERSITE="1")
                environment['PYTHONPATH'] = os.pathsep.join(python_import_roots(snapshot))
                statement = """
from pathlib import Path
from msplatform.backends.simion import native_completion
from msplatform.execution import retention as write_run_manifest
from common.contracts import capacity_protection
assert Path(native_completion.__file__).is_relative_to(Path.cwd())
assert Path(write_run_manifest.__file__).is_relative_to(Path.cwd())
assert Path(capacity_protection.__file__).is_relative_to(Path.cwd())
"""
                if consumer in ('accelerator_interface', 'cooled_frontend'):
                    statement += "\nfrom projects.dual_pressure_rectilinear_ion_processor.analysis import batching\n"
                    statement += "assert Path(batching.__file__).is_relative_to(Path.cwd())\n"
                if consumer == 'accelerator_interface':
                    statement += "\nfrom projects.parallel_mirror_dual_stripe_mr_tof.analysis import bunch_source_and_schedule\n"
                command = [sys.executable, '-B', '-s', '-c', statement]
                completed = subprocess.run(command, cwd=snapshot, env=environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                for module in (False, True):
                    with self.subTest(module=module, adapter_present=True):
                        self._assert_frozen_retention(snapshot, module=module, adapter_present=True)
                (snapshot / 'src/msplatform/backends/simion/native_completion.py').unlink()
                missing = subprocess.run(command, cwd=snapshot, env=environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn('native_completion', missing.stderr)
                for module in (False, True):
                    with self.subTest(module=module, adapter_present=False):
                        self._assert_frozen_retention(snapshot, module=module, adapter_present=False)

    def _assert_frozen_retention(self, snapshot: Path, *, module: bool, adapter_present: bool) -> None:
        """Exercise public retention entrypoints with no live-checkout import path."""
        run = snapshot.parent / "runs" / f"retention_{module}_{adapter_present}"
        logs = run / "logs"
        logs.mkdir(parents=True)
        config = run / "run_config.json"
        config.write_text(json.dumps({
            "schema_version": 2,
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        }), encoding="utf-8")
        original_logs = {
            logs / "simion__batch01.trace.log": b"status,Fly completed.\n",
            logs / "simion__batch02.stdout.log": b"status,Fly completed. 2 splats, 0.1 seconds\n",
        }
        for path, contents in original_logs.items():
            path.write_bytes(contents)
        payload = run / "field.pa0"
        payload.write_bytes(b"rebuildable fixture")
        native_cli = (
            "from msplatform.execution.artifact_retention import main; "
            "from msplatform.backends.simion import native_completion; "
            "from msplatform.execution.retention import classify_file; "
            "main(classifier=classify_file,completion_api=lambda:native_completion)"
        )
        entry = ["-c", native_cli] if module else ["-c", native_cli.replace(
            "from msplatform.execution.artifact_retention import main;",
            "import msplatform.execution.artifact_retention as engine; main=engine.main;"
        )]
        command = [sys.executable, "-B", "-s", *entry, "apply", "--run-config", str(config), "--failed-run"]
        for path in original_logs:
            command.extend(("--preserve-path", str(path)))
        environment = dict(os.environ, PYTHONNOUSERSITE="1")
        environment["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
        completed = subprocess.run(command, cwd=snapshot if module else snapshot.parent,
            env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        receipt = run / "retention_actions.json"
        if adapter_present:
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertFalse(payload.exists())
            action = load(receipt)
            self.assertEqual(action["status"], "complete")
            self.assertEqual({row["path"] for row in action["preserved"]},
                             {path.relative_to(run).as_posix() for path in original_logs})
        else:
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("native_completion", completed.stderr)
            self.assertEqual(payload.read_bytes(), b"rebuildable fixture")
            self.assertFalse(receipt.exists())
        for path, contents in original_logs.items():
            self.assertEqual(path.read_bytes(), contents)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_single_reflection_snapshot_plans_downstream_without_live_checkout(self) -> None:
        """Native command planning must consume the complete frozen provider."""
        from integrations.tests.test_single_reflection_preparation import fixture

        with tempfile.TemporaryDirectory() as directory:
            request, run, _ = fixture(Path(directory))
            (run / "run_config.json").write_text(json.dumps(dict(
                project="instrument_assembly", run_id="20261023_120000__test__python__frozen-downstream")),
                encoding="utf-8")
            freeze = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{run / 'inputs'}' -OwnerId instrument_assembly -ConsumerId single_reflection_flight
"""
            frozen = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", freeze],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            selected = load(run / "inputs/code_inventory.json")["dependencies"]
            self.assertIn("common/contracts/reconcile_artifact_capacity.py",
                          {row["source_repo_path"] for row in selected})
            snapshot = run / "inputs/runtime_snapshot"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
            artifact_root = Path(directory) / "artifacts"
            protected = artifact_root / "projects/instrument_assembly/runs/test"
            protected.mkdir(parents=True)
            command = [sys.executable, "-B", "-s", "-m",
                       "common.contracts.reconcile_artifact_capacity",
                       "--artifact-root", str(artifact_root)]
            created = subprocess.run(command + ["--create-protection-lease", "frozen-test",
                "--lease-owner", "instrument_assembly", "--lease-ttl-seconds", "60",
                "--protect-path", str(protected), "--committed-new-bytes", "1024"],
                cwd=snapshot, env=environment, capture_output=True, text=True,
                encoding="utf-8", timeout=60)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            lease = json.loads(created.stdout)
            self.assertEqual(lease["committed_new_bytes"], 1024)
            self.assertTrue(Path(lease["path"]).is_file())
            released = subprocess.run(command + ["--delete-protection-lease", "frozen-test"],
                cwd=snapshot, env=environment, capture_output=True, text=True,
                encoding="utf-8", timeout=60)
            self.assertEqual(released.returncode, 0, released.stdout + released.stderr)
            self.assertFalse(Path(lease["path"]).exists())
            statement = """
import json,sys
from pathlib import Path
class NoOrchestrationImport:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('integrations.workflows.single_reflection_flight.runtime',
                        'msplatform.workflows.single_reflection_flight.collect'):
            raise ImportError('pure evidence/continuation cannot import orchestration: '+fullname)
guard=NoOrchestrationImport()
sys.meta_path.insert(0,guard)
from integrations.workflows.single_reflection_flight import downstream_fields
from msplatform.workflows.single_reflection_flight import continuation
from msplatform.backends.simion import tracking_collection as census
from msplatform.workflows.single_reflection_flight import pulse
sys.meta_path.remove(guard)
from msplatform.workflows.single_reflection_flight import prepare
from integrations.workflows.single_reflection_flight import runtime
from msplatform.workflows.single_reflection_flight import collect
assert all(Path(m.__file__).is_relative_to(Path.cwd()) for m in (prepare,downstream_fields,runtime,collect,census,continuation,pulse))
assert not any('rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' in name for name in sys.modules)
assert not (Path.cwd()/'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer').exists()
request,run=map(Path,sys.argv[1:])
# TEST_ONLY schema branch copied from the fixture, never used as scientific input.
from msplatform.contracts.machine_contracts import validate_schema
from msplatform.io.manifest_records import record_path
request_value=json.loads(request.read_text())
provider=next(v for v in request_value['providers']['instances'].values() if 'geometry' not in v)
enclosure_fixture=json.loads(record_path(provider['resolved_design'],base_dir=request.parent).read_text())
enclosure_fixture['governance']={key:'A'*64 for key in ('design_variables_sha256','optimization_envelope_sha256','design_request_file_sha256')}
validate_schema(enclosure_fixture,Path.cwd()/'src/msplatform/contracts/schemas/multipole_resolved_design.schema.json')
preparation=prepare.prepare(request,run)
assert 'composition_plan' not in preparation['outputs']
assert (run/'inputs/composition_plan.json').exists()
assert json.loads(Path(preparation['outputs']['frontend_geometry']['path']).read_text())['composition_plan']['scope']['kind']=='full'
(run/'preparation_for_dependency_test.json').write_text(json.dumps(preparation),encoding='utf-8')
result=downstream_fields.plan_downstream_fields(preparation,run,snapshot_root=Path.cwd())
assert len(result['steps'])==5
assert all(Path(step['argv'][3]).is_relative_to(Path.cwd()) for step in result['steps'])
print(json.dumps(dict(status='FROZEN_DOWNSTREAM_PLAN_PASS',native_executed=False)))
"""
            planned = subprocess.run([sys.executable, "-B", "-s", "-c", statement, str(request), str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["status"], "FROZEN_DOWNSTREAM_PLAN_PASS")
            # Remove a non-Python provider resource. A new detached process
            # must fail before execution instead of searching the live tree.
            resource = snapshot / "src/msplatform/backends/simion/resources/oatof_reflectron_ideal_10_5.gem"
            resource.unlink()
            refused = subprocess.run([sys.executable, "-B", "-s", "-c",
                "import json,sys; from pathlib import Path; "
                "from integrations.workflows.single_reflection_flight.downstream_fields import plan_downstream_fields; "
                "plan_downstream_fields(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]),snapshot_root=Path.cwd())",
                str(run / "preparation_for_dependency_test.json"), str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("FileNotFoundError: frozen SIMION GEM resource is missing: "
                          "oatof_reflectron_ideal_10_5.gem", refused.stderr)

    def test_cooled_prepare_imports_shared_assembly_from_declared_snapshot(self) -> None:
        # Exercise the actual freeze and the runtime-only reference imports;
        # these are not discoverable from prepare.py's ordinary Python imports.
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            freeze = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId cooled_frontend
"""
            result = subprocess.run([pwsh, "-NoProfile", "-Command", freeze], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            snapshot = output / "runtime_snapshot"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
            environment["PYTHONNOUSERSITE"] = "1"
            helper = snapshot / "integrations/workflows/cooled_frontend/reference_support.ps1"
            stage = f"""
$ErrorActionPreference='Stop'
. './integrations/runtime/frontend_flight_support.ps1'
. './integrations/workflows/cooled_frontend/reference_support.ps1'
$command=Get-Command Invoke-CooledReferenceCalibration
if($command.ScriptBlock.File -cne '{helper}'){{throw 'Reference helper came from outside the frozen snapshot'}}
if(-not(Get-Command Invoke-FrontendFlightPhase)){{throw 'Frozen reference flight support is missing'}}
'FROZEN_REFERENCE_HELPER=PASS'
"""
            result = subprocess.run([pwsh, "-NoProfile", "-Command", stage], cwd=snapshot,
                                    env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            statement = (
                "from pathlib import Path; "
                "from integrations.workflows.cooled_frontend import prepare; "
                "from integrations.workflows.cooled_frontend import reference, pulse, mesh_check; "
                "from msplatform.assembly import resolve_assembly; "
                "from projects.orthogonal_accelerator.analysis import assembly_interface; "
                "assert all(Path(module.__file__).is_relative_to(Path.cwd()) "
                "for module in (prepare,reference,pulse,mesh_check,resolve_assembly,assembly_interface)); "
                "print('COOLED_SHARED_ASSEMBLY_IMPORT=PASS')"
            )
            result = subprocess.run([sys.executable, "-B", "-s", "-c", statement],
                                    cwd=snapshot, env=environment, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("COOLED_SHARED_ASSEMBLY_IMPORT=PASS", result.stdout)
            result = subprocess.run([sys.executable, "-B", "-s", "-m",
                "integrations.workflows.cooled_frontend.reference", "prepare-reference", "--help"],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--run", result.stdout)
            from integrations.tests.test_cooled_frontend import cooled_request_fixture
            request_path, _ = cooled_request_fixture(Path(directory) / "scientific-input")
            command = [sys.executable, "-B", "-s", "-m", "integrations.workflows.cooled_frontend.prepare",
                       "--request", str(request_path), "--repo-root", str(snapshot),
                       "--workspace-root", str(Path(directory) / "scientific-input"), "--output-directory", str(Path(directory) / "prepared"),
                       "--run-id", "20261101_000000__build__python__frozen-cooled"]
            prepared = subprocess.run(command, cwd=snapshot, env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            self.assertEqual(json.loads(prepared.stdout)["particle_count"], 100)
            self.assertTrue((Path(directory) / "prepared/inputs/frontend_contract.json").is_file())
            # Missing snapshot modules must fail instead of falling back to the
            # checkout from which this test was launched.
            (snapshot / "integrations/workflows/cooled_frontend/reference.py").unlink()
            result = subprocess.run([sys.executable, "-B", "-s", "-c", statement], cwd=snapshot,
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reference", result.stderr)



    def test_local_freezer_imports_without_repository_and_requires_provider(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            script = f"""
. '{DEPENDENCIES}'
$f=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend
if(@($f.identities).Count-lt1){{throw 'empty selected closure'}}
Write-Output $f.execution_root
"""
            result = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            selected = load(output / "code_inventory.json")["dependencies"]
            paths = {row["source_repo_path"] for row in selected}
            required_ip = {"src/msplatform/components/dual_pressure_rectilinear_ion_processor/guide_interface.py"}
            required_ip.update("src/msplatform/components/dual_pressure_rectilinear_ion_processor/" + name + ".py"
                               for name in ("native_geometry", "electrode_contours", "convex_geometry"))
            self.assertTrue(required_ip <= paths)
            self.assertNotIn("oatof_analyzer_component", {row["id"] for row in selected})
            snapshot = output/"runtime_snapshot"
            detached_script = """
. './integrations/runtime/dependencies.ps1'
Assert-DependencyProviderIdentity -RepoRoot (Get-Location).Path -DependencyId test `
  -Scope integration -Provider instrument_assembly -ProviderRelative integrations
Write-Output 'FROZEN_DEPENDENCIES=PASS'
"""
            detached = subprocess.run([pwsh, "-NoProfile", "-Command", detached_script],
                                      cwd=snapshot, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(detached.returncode, 0, detached.stdout + detached.stderr)
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
            statement = ("from msplatform.workflows.local_frontend import prepare,runtime; "
                         "from integrations.workflows.local_frontend import analyze; from integrations.runtime "
                         "import standalone_pa_family; from msplatform.execution import run_capacity_lifecycle;"
                         "assert prepare.ROLE=='instrument_assembly_local_frontend_request'; print('LOCAL_SNAPSHOT_IMPORT=PASS')")
            completed = subprocess.run([sys.executable, "-s", "-c", statement], cwd=snapshot, env=env,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            # Exercise the real local OA adapter inside the detached snapshot,
            # then remove its new public kernel and prove imports fail closed.
            crossing_statement = """
from pathlib import Path
from integrations.workflows.local_frontend.focus import _local_crossings
from msplatform.analysis import plane_crossings
assert Path(plane_crossings.__file__).is_relative_to(Path.cwd())
rows = _local_crossings(
    [(4, dict(particle_id=7,t_us=1.,x_mm=1.,y_mm=2.,z_mm=2.,vx_mm_us=0.,vy_mm_us=0.,vz_mm_us=-1.)),
     (8, dict(particle_id=7,t_us=2.,x_mm=3.,y_mm=2.,z_mm=0.,vx_mm_us=0.,vy_mm_us=0.,vz_mm_us=-1.))],
    {7: {}}, {}, {7: dict(reason='not_extracted')}, [1.,0.],
    frame='mrtof_global_cartesian',pulse=0.,limit=1.,mass=524.)
assert rows[0]['t_us']==1.5 and rows[0]['lower_sample_line']==4 and rows[0]['upper_sample_line']==8
assert rows[1]['status']=='unknown'
print('LOCAL_SNAPSHOT_CROSSING=PASS')
"""
            crossing_command = [sys.executable, "-B", "-s", "-c", crossing_statement]
            crossed = subprocess.run(crossing_command, cwd=snapshot, env=env,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(crossed.returncode, 0, crossed.stdout+crossed.stderr)
            self.assertIn("LOCAL_SNAPSHOT_CROSSING=PASS", crossed.stdout)
            kernel = snapshot/"src/msplatform/analysis/plane_crossings.py"
            contents = kernel.read_bytes()
            kernel.unlink()
            try:
                absent = subprocess.run(crossing_command, cwd=snapshot, env=env,
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertNotEqual(absent.returncode, 0)
                self.assertIn("plane_crossings", absent.stderr)
            finally:
                kernel.write_bytes(contents)
            # Removing one declared provider proves the clean snapshot cannot
            # silently recover an undeclared cross-project import from the repo.
            (snapshot/"src/msplatform/components/dual_pressure_rectilinear_ion_processor/guide_interface.py").unlink()
            missing = subprocess.run([sys.executable, "-B", "-s", "-c", statement], cwd=snapshot, env=env,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("guide_interface", missing.stderr)

    def test_local_snapshot_prepares_both_variants_and_requires_runtime_resources(self) -> None:
        from integrations.tests.test_local_frontend_workflow import fixture, write_fixture_plan
        from integrations.tests.frontend_fixtures import canonical_three_zone_frontend_fixture

        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fixture_root = workspace / "frozen"
            request_path, request = fixture(fixture_root)
            freeze = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{workspace / 'frozen'}' -OwnerId instrument_assembly -ConsumerId local_frontend
"""
            frozen = subprocess.run([pwsh, "-NoProfile", "-Command", freeze], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout+frozen.stderr)
            snapshot = workspace / "frozen/runtime_snapshot"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
            module = "msplatform.workflows.local_frontend.prepare"
            command = [sys.executable, "-B", "-s", "-m", module, "--request", str(request_path),
                       "--workspace-root", str(fixture_root), "--validate-only"]

            def run_prepare():
                return subprocess.run(command, cwd=snapshot, env=environment, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=60)

            for variant in ("two_zone", "three_zone"):
                with self.subTest(variant=variant):
                    if variant == "three_zone":
                        _, connection, component = canonical_three_zone_frontend_fixture()
                        placement = component.pop("transform")
                        request["accelerator_component"] = component
                        parent = json.loads(Path(request['composition_plan']['path']).read_text())
                        recipe = parent['recipe']
                        instances = {item["instance_id"]: item for item in recipe["instances"]}
                        instances["guide"]["transform"].update(
                            rotation=connection["spatial_registration"]["rotation_upstream_to_downstream"],
                            translation_mm=connection["spatial_registration"]["translation_mm"])
                        instances["accelerator"]["transform"].update(
                            from_frame_id="sectioned_accelerator_cartesian", **placement)
                        recipe["connections"][0]["gap_mm"] = connection["connector"]["length_mm"]
                        write_fixture_plan(fixture_root, request, recipe)
                    request_path.write_text(json.dumps(request), encoding="utf-8")
                    completed = run_prepare()
                    self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
                    output = workspace / variant
                    output.mkdir()
                    config = output / "run_config.json"
                    run_id = "20261022_120000__test__python__frozen-prepare"
                    public = [pwsh, "-NoProfile", "-File", str(INTEGRATION_ROOT / "workflows/local_frontend/execute.ps1"),
                              "-Request", str(request_path), "-RepoRoot", str(snapshot), "-Python", sys.executable,
                              "-PrepareOnly", "-OutputDirectory", str(output)]
                    config.write_text(json.dumps(dict(project="wrong_owner", run_id=run_id)))
                    refused = subprocess.run(public, cwd=snapshot, env=environment, capture_output=True, text=True,
                                             encoding="utf-8", errors="replace", timeout=60)
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertIn("managed run owner", refused.stderr)
                    self.assertFalse((output / "inputs").exists())
                    config.write_text(json.dumps(dict(project="instrument_assembly", run_id=run_id)))
                    prepared = subprocess.run(public, cwd=snapshot, env=environment, capture_output=True, text=True,
                                              encoding="utf-8", errors="replace", timeout=60)
                    self.assertEqual(prepared.returncode, 0, prepared.stdout+prepared.stderr)
                    self.assertEqual(load(workspace / variant / "inputs/integration_identity.json")["integration_id"],
                                     "instrument_assembly")
                    from msplatform.execution.clock_authority import validate_clock_authority
                    self.assertEqual(validate_clock_authority(output / "inputs/clock_authority.json", output)["clock_epoch_id"],
                                     load(output / "inputs/source_identity.json")["clock_epoch_id"])
                    self.assertFalse((output / "inputs/source_clock.json").exists())
                    result = json.loads(completed.stdout)
                    self.assertEqual((result["status"], result["particle_count"]), ("validated", 100))

            # Each omitted resource failed in a real frozen run. Fresh processes
            # and -B prevent an already imported module/pyc masking the omission.
            for relative in ("src/msplatform/contracts/schemas/simion_rectangular_aperture_discretization.schema.json",
                             "src/msplatform/execution/clock_authority.py",
                             "src/msplatform/contracts/schemas/canonical_clock_authority.schema.json",
                             "src/msplatform/contracts/schemas/assembly_recipe.schema.json",
                             "src/msplatform/contracts/schemas/component_geometry_interface.schema.json",
                             "src/msplatform/contracts/schemas/composition_plan.schema.json",
                             "src/msplatform/assembly/resolve_assembly.py",
                             "src/msplatform/components/orthogonal_accelerator/assembly_interface.py",
                             "src/msplatform/components/orthogonal_accelerator/three_zone_ideal_theory.py"):
                with self.subTest(missing=relative):
                    resource = snapshot / relative
                    original = resource.read_bytes()
                    resource.unlink()
                    try:
                        missing = run_prepare()
                        self.assertNotEqual(missing.returncode, 0, missing.stdout)
                        self.assertIn(resource.stem, missing.stderr)
                    finally:
                        resource.write_bytes(original)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_changed_frozen_dependency_reports_both_paths_and_measured_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = root / "repo"
            source = repo / "common/fixture.txt"
            source.parent.mkdir(parents=True)
            original = b"dependency fixture\n"
            source.write_bytes(original)
            inputs = root / "inputs"
            destination = inputs / "runtime_snapshot/common/fixture.txt"
            quote = lambda value: str(value).replace("'", "''")
            script = f"""
. '{quote(DEPENDENCIES)}'
function Copy-Item {{
 param([string]$LiteralPath,[string]$Destination)
 Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination
 # TEST_ONLY: force a different copied payload before the real two hash reads.
 [IO.File]::AppendAllText($Destination,'changed')
}}
$dependency=[pscustomobject]@{{
 id='fixture';provider_scope='repository_common';provider_project='common';provider_repo_path='common'
 source_repo_path='common/fixture.txt';frozen_filename='runtime_snapshot/common/fixture.txt'
 run_input_name='fixture';consumers=@('local_frontend')
}}
try {{
 $null=Copy-FrozenDependency -RepoRoot '{quote(repo)}' -InputDir '{quote(inputs)}' -Dependency $dependency
}} catch {{
 [Console]::Error.WriteLine($_.Exception.Message)
 exit 1
}}
"""
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(destination.read_bytes(), original + b"changed")
            source_hash = hashlib.sha256(original).hexdigest().upper()
            frozen_hash = hashlib.sha256(original + b"changed").hexdigest().upper()
            self.assertEqual(result.stderr.strip(),
                f"Dependency changed while frozen: {source}; destination={destination}; "
                f"source_sha256={source_hash}; frozen_sha256={frozen_hash}")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_registered_provider_roots_and_frozen_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            (root / "integrations/config").mkdir(parents=True)
            registry = {"integrations": [
                {"integration_id": "instrument_assembly", "root": "integrations"},
                {"integration_id": "legacy", "root": "integrations/legacy"},
            ]}
            (root / "integrations/registry.json").write_text(json.dumps(registry), encoding="utf-8")
            for path in (REPO_ROOT / "common").rglob("*"):
                if (path.is_file() and path.suffix in {".py", ".ps1", ".json"}
                        and not any(part in {"assets", "__pycache__", "history", "vendor"}
                                    for part in path.relative_to(REPO_ROOT).parts)):
                    target = root / path.relative_to(REPO_ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
            shutil.copytree(REPO_ROOT / "src/msplatform", root / "src/msplatform",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            groups = []
            for number, (scope, owner, provider) in enumerate((
                ("integration", "instrument_assembly", "integrations"),
                ("integration", "legacy", "integrations/legacy"),
                ("project", "device", "projects/device"),
                ("repository_common", "common", "common"),
            )):
                source = f"{provider}/provider{number}.txt"
                path = root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"VALUE = {number}\n", encoding="utf-8")
                groups.append(dict(provider_scope=scope, provider_project=owner,
                    files=[dict(id=f"provider{number}", source_repo_path=source, consumers=["local_frontend"])],
                    python_packages=[], python_modules=[]))
            contract = root / "integrations/config/dependencies.json"
            contract.write_text(json.dumps(dict(schema_version=3, role="integration_runtime_dependencies",
                owner_id="instrument_assembly", consumer_ids=["local_frontend"], providers=groups)), encoding="utf-8")
            package = root / "projects/device/pkg"
            package.mkdir(parents=True)
            (package / "entry.py").write_text(
                "from .added_helper import VALUE\n"
                "def prepare(destination):\n"
                "    destination.write_text(str(VALUE), encoding='utf-8')\n", encoding="utf-8")
            groups[2]["python_packages"].append(dict(
                source_repo_path="projects/device/pkg", consumers=["local_frontend"]))
            groups[2]["python_packages"].append(dict(
                source_repo_path="projects/device/unrequested", consumers=["not_requested"]))
            author = load(contract)
            author["providers"] = groups
            author["consumer_ids"].append("not_requested")
            contract.write_text(json.dumps(author), encoding="utf-8")
            declared = contract.read_bytes()
            # A new importable module needs no hand-maintained file row.
            (package / "added_helper.py").write_text("VALUE = 42\n", encoding="utf-8")
            self.assertEqual(contract.read_bytes(), declared)
            output = Path(directory) / "inputs"
            script = f"""
. '{DEPENDENCIES}'
$f=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{root}' -ContractPath '{contract}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend
if(@($f.identities).Count-ne6){{throw 'provider count differs'}}
$inventory=Get-Content $f.code_inventory_path -Raw|ConvertFrom-Json
if($inventory.owner_id-ne'instrument_assembly' -or $inventory.PSObject.Properties.Name-contains'consumer_project'){{throw 'owner identity differs'}}
foreach($entry in $inventory.dependencies){{
 if($entry.run_input_name-cne$entry.id-or$entry.frozen_filename-cne('runtime_snapshot/'+$entry.source_repo_path)){{throw 'derived fields differ'}}
}}
if((Get-Content $f.dependency_contract_path -Raw)-cne(Get-Content '{contract}' -Raw)){{throw 'contract differs'}}
$valid=Get-Content '{contract}' -Raw
$cases=@(
  @{{change={{param($d) $d.owner_id='legacy'}};message='*identity*'}},
  @{{change={{param($d) $d.schema_version=1}};message='*schema 3*'}},
  @{{change={{param($d) $d.providers[0].provider_project='unknown'}};message='*registered exactly once*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='common/provider3.txt'}};message='*escapes provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='integrations/../common/provider3.txt'}};message='*escapes its provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='integrations/missing.txt'}};message='*is missing*'}},
  @{{change={{param($d) $d.providers[1].files[0].id=$d.providers[0].files[0].id}};message='*duplicate dependency id*'}},
  @{{change={{param($d) $d.providers[0].files+=@($d.providers[0].files[0]|ConvertTo-Json|ConvertFrom-Json);$d.providers[0].files[1].id='other'}};message='*Duplicate dependency source*'}},
  @{{change={{param($d) $d.providers[0].files[0].consumers=@('unknown')}};message='*invalid consumers*'}},
  @{{change={{param($d) $d.consumer_ids=@('other')}};message='*Unregistered*'}}
)
$index=0
foreach($case in $cases){{
 $bad=$valid|ConvertFrom-Json
 & $case.change $bad
 $bad|ConvertTo-Json -Depth 30|Set-Content '{contract}'
 $destination='{output}-invalid'+$index
 try{{Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{root}' -ContractPath '{contract}' -InputDir $destination -OwnerId instrument_assembly -ConsumerId local_frontend;throw 'invalid author accepted'}}
 catch{{if($_.Exception.Message-notlike$case.message){{throw}}}}
 if(Test-Path $destination){{throw 'Invalid author copied files before rejection'}}
 $index++
}}
$valid|Set-Content '{contract}'
try{{Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{root}' -ContractPath '{contract}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend;throw 'existing destination accepted'}}
catch{{if($_.Exception.Message-notlike'*already exists*'){{throw}}}}
Write-Output 'BOUNDARIES=PASS'
"""
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for group in groups:
                for row in group["files"]:
                    self.assertEqual((output / "runtime_snapshot" / row["source_repo_path"]).read_bytes(),
                                     (root / row["source_repo_path"]).read_bytes())
            inventory = load(output / "code_inventory.json")
            python_rows = [row for row in inventory["dependencies"] if row["source_repo_path"].endswith(".py")]
            self.assertEqual({row["id"] for row in python_rows},
                {"python:projects/device/pkg/entry.py", "python:projects/device/pkg/added_helper.py"})
            root.rename(root.with_name("author-unavailable"))
            plan = Path(directory) / "detached-plan.txt"
            code = "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from projects.device.pkg.entry import prepare;prepare(Path(sys.argv[2]))"
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                str(output / "runtime_snapshot"), str(plan)], cwd=output,
                capture_output=True, text=True, encoding="utf-8", errors="backslashreplace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(plan.read_text(), "42")


if __name__ == "__main__":
    unittest.main()
