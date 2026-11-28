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
INVENTORY = REPO_ROOT / "src/msplatform/workflows/config/runtime_dependencies.json"
DEPENDENCIES = REPO_ROOT / "src/msplatform/execution/resources/dependencies.ps1"


def snapshot_environment(snapshot: Path) -> dict[str, str]:
    return dict(os.environ, PYTHONPATH=os.pathsep.join(python_import_roots(snapshot)), PYTHONNOUSERSITE="1")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class DependencyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_retired_single_reflection_dependency_consumer_is_not_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'inputs'
            script = root / 'retired-consumer.ps1'
            script.write_text("""param($Repo,$Destination,$Python)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'src/msplatform/execution/resources/dependencies.ps1')
$null=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'src/msplatform/workflows/config/runtime_dependencies.json') -InputDir $Destination -OwnerId instrument_assembly -ConsumerId single_reflection_flight
""", encoding='utf-8')
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(script),
                str(REPO_ROOT), str(output), sys.executable], cwd=root,
                capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unregistered or invalid runtime dependency consumer', result.stdout + result.stderr)
            self.assertFalse(output.exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_python_package_freezer_requires_internal_production_source_with_resources(self) -> None:
        from tests.contracts.test_support.run_artifact_workflow import copy_scientific_core

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author = root / "author"
            copy_scientific_core(REPO_ROOT, author)
            registry = author / "src/msplatform/workflows/config/assembly_registry.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / "src/msplatform/workflows/config/assembly_registry.json", registry)
            contract = author / "src/msplatform/workflows/config/dependencies.json"
            provider = author / "src/msplatform/device"
            provider.mkdir(parents=True)
            (provider / "__init__.py").write_bytes(b"PARENT = True\n")
            cases = [({}, False), ({"test_only.py": b"TEST = True\n"}, False),
                     ({"only_test.py": b"TEST = True\n"}, False),
                     ({"__init__.py": b"SOURCE = True\n"}, True),
                     ({"code.py": b"SOURCE = True\n"}, True)]
            for number, (sources, accepted) in enumerate(cases):
                with self.subTest(sources=list(sources)):
                    package = provider / f"pkg{number}"
                    package.mkdir()
                    (package / "model.schema.json").write_bytes(b'{"fixture":42}\n')
                    for name, raw in sources.items():
                        (package / name).write_bytes(raw)
                    relative = package.relative_to(author).as_posix()
                    declaration = dict(schema_version=3, role="workflow_runtime_dependencies",
                        owner_id="instrument_assembly", consumer_ids=["single_reflection_flight"], providers=[
                            dict(provider_scope="repository_core", provider_project="msplatform", files=[],
                                 python_packages=[dict(source_repo_path=relative,
                                     consumers=["single_reflection_flight"], resource_suffixes=[".schema.json", ".py"])],
                                 python_modules=[])])
                    contract.write_text(json.dumps(declaration), encoding="utf-8")
                    destination = root / f"inputs{number}"
                    script = f""". '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{author}' -ContractPath '{contract}' -InputDir '{destination}' -OwnerId instrument_assembly -ConsumerId single_reflection_flight
"""
                    result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                    if not accepted:
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("no production sources", result.stdout + result.stderr)
                        self.assertFalse(destination.exists())
                        continue
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    entries = load(destination / "code_inventory.json")["dependencies"]
                    expected = {"src/msplatform/__init__.py", "src/msplatform/device/__init__.py", relative + "/model.schema.json",
                                *(relative + "/" + name for name in sources)}
                    self.assertEqual({entry["source_repo_path"] for entry in entries}, expected)
                    self.assertEqual(len(entries), len(expected))
                    for entry in entries:
                        self.assertEqual(entry["consumers"], ["single_reflection_flight"])
                        self.assertEqual((destination / "runtime_snapshot" / entry["source_repo_path"]).read_bytes(),
                                         (author / entry["source_repo_path"]).read_bytes())

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
. (Join-Path $Repo 'src/msplatform/execution/resources/dependencies.ps1')
$null=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'src/msplatform/workflows/config/runtime_dependencies.json') -InputDir $Destination -OwnerId instrument_assembly -ConsumerId oa_mr
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
. (Join-Path $Snapshot 'src/msplatform/execution/resources/simion_dispatch_support.ps1')
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
$f=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId prepared_joint
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
                ["prepared_joint", "accelerator_interface", "oa_mr"])
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
            required_companions = {
                "src/msplatform/workflows/resources/ip_functional.ps1",
                "src/msplatform/workflows/resources/run_artifact_workflow.ps1",
                "src/msplatform/backends/simion/resources/run_native_static_field_provider.ps1",
                "src/msplatform/backends/simion/resources/build_dirichlet_patch_basis.lua",
                "src/msplatform/backends/simion/resources/crop_native_static_field.lua",
                "src/msplatform/backends/simion/resources/short_pa_path_support.ps1",
                "src/msplatform/execution/resources/simion_dispatch_support.ps1",
            }
            self.assertTrue(all((snapshot / relative).is_file() for relative in required_companions))
            inventory = json.loads((inputs / "code_inventory.json").read_text(encoding="utf-8"))
            self.assertTrue(required_companions.issubset(
                {row["source_repo_path"] for row in inventory["dependencies"]}))
            code = '''
from pathlib import Path
from msplatform.workflows.accelerator_interface import prepare
from msplatform.recipes import native as native_recipe
from msplatform.workflows.ion_processor import functional
from msplatform.workflows.ion_processor import preparation
import tempfile
root = Path.cwd().resolve()
for module in (prepare, functional, native_recipe, preparation):
    Path(module.__file__).resolve().relative_to(root)
assert callable(preparation.validate_configs)
assert callable(native_recipe.resolve_native)
assert not (root / 'src/msplatform/workflows/multipole_ip/prepare.py').exists()
'''
            result = subprocess.run([sys.executable, "-B", "-s", "-c", code], cwd=snapshot,
                env=snapshot_environment(snapshot),
                capture_output=True, text=True, encoding="utf-8", errors="backslashreplace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tracking_reuse_ignores_unrelated_report_but_binds_actual_collector(self) -> None:
        from msplatform.backends.simion.tracking_units import tracking_applicability
        from tests.contracts.test_simion_tracking_execution import TrackingExecutionPlanTests
        case = TrackingExecutionPlanTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        plan = case.plan(unit_size=27)
        with tempfile.TemporaryDirectory() as directory:
            unrelated = Path(directory) / 'report_only.py'
            unrelated.write_text('value = 1\n', encoding='utf-8')
            before = tracking_applicability(plan)
            unrelated.write_text('value = 2\n', encoding='utf-8')
            self.assertEqual(tracking_applicability(plan), before)
            original = Path.read_bytes
            def changed_collector(path):
                data = original(path)
                return data + b'\n# changed collector\n' if path.name == 'tracking_collection.py' else data
            with mock.patch.object(Path, 'read_bytes', new=changed_collector):
                self.assertNotEqual(tracking_applicability(plan), before)

    def test_shared_dependency_fixture_expands_retained_consumers_without_large_seeds(self) -> None:
        from tests.workflows.single_reflection.test_support.single_reflection_execute_fixture import declared_dependency_paths
        contract = load(INVENTORY)
        originals = {path.relative_to(REPO_ROOT).as_posix() for path in (REPO_ROOT / 'src/msplatform/contracts/schemas').glob('*.schema.json')}
        self.assertTrue(originals)
        for consumer in ('prepared_joint',):
            with self.subTest(consumer=consumer):
                paths = declared_dependency_paths(REPO_ROOT, contract, consumer)
                self.assertIn('src/msplatform/execution/inputs.py', paths)
                self.assertTrue(originals <= paths)
                self.assertFalse(any('iob_seed_placeholder_' in path for path in paths))
        prepared = declared_dependency_paths(REPO_ROOT, contract, 'prepared_joint')
        for name in ('4_instance_seed.iob', '5_instance_seed.iob'):
            self.assertIn('src/msplatform/backends/simion/resources/' + name, prepared)

    def test_joint_finalization_owners_freeze_the_existing_public_adapter(self) -> None:
        entries = {item["source_repo_path"]: set(item["consumers"])
                   for group in load(INVENTORY)["providers"] for item in group["files"]}
        self.assertEqual(entries["src/msplatform/workflows/resources/run_artifact_workflow.ps1"],
                         {"prepared_joint", "accelerator_interface", "oa_mr",
                          "paired_accelerator_pulse"})
        self.assertNotIn("common/resource_budget_support.ps1", entries)
        self.assertNotIn("common/host_execution_lease.ps1", entries)

    def test_paired_static_store_owns_its_real_resource_closure(self) -> None:
        from msplatform.backends.comsol.resources import native_resource_path as comsol_resource
        from msplatform.backends.simion.resources import native_resource_path as simion_resource
        from msplatform.workflows.paired_accelerator_static_field.store_workflow import _MATLAB, _SIMION
        contract = load(INVENTORY)
        self.assertNotIn('paired_accelerator_static_field', contract['consumer_ids'])
        for provider in contract['providers']:
            for item in (*provider.get('python_packages', []), *provider.get('files', [])):
                self.assertNotIn('paired_accelerator_static_field', item['consumers'])
        self.assertEqual(len(_MATLAB), 7)
        self.assertEqual(set(_SIMION), {'builder', 'exporter', 'sampler'})
        for name in _MATLAB:
            self.assertTrue(comsol_resource(name).is_file(), name)
        for name in _SIMION.values():
            self.assertTrue(simion_resource(name).is_file(), name)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_prepared_joint_loads_shared_mr_continuation_guard_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory)/"inputs"
            freeze = f". '{DEPENDENCIES}'; $null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId prepared_joint"
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",freeze],cwd=REPO_ROOT,
                                    capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            snapshot = inputs/"runtime_snapshot"
            runtime = snapshot/"src/msplatform/backends/simion/resources/native_corridor_runtime_support.ps1"
            load_runtime = f". '{runtime}'; if(-not (Get-Command Protect-MrtofContinuationEvidence -ErrorAction SilentlyContinue)){{throw 'missing frozen guard'}}"
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",load_runtime],cwd=snapshot,
                                    capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            environment = snapshot_environment(snapshot)
            result = subprocess.run([sys.executable,"-B","-s","-m",
                "msplatform.workflows.prepared_joint.continuation","--help"],
                cwd=snapshot,env=environment,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_current_field_and_tracking_owners_form_a_dag(self) -> None:
        """Include deferred and relative imports among actual current owners."""
        import importlib.util
        names = ('field_identity', 'field_bank', 'field_execution', 'native_plans',
                 'tracking_units', 'tracking_execution', 'tracking_collection', 'particle_data')
        paths = {'msplatform.backends.simion.' + name:
                 REPO_ROOT / 'src/msplatform/backends/simion' / (name + '.py') for name in names}
        paths['msplatform.results.particle_data'] = REPO_ROOT / 'src/msplatform/results/particle_data.py'
        graph = {}
        for name, source in paths.items():
            graph[name] = set()
            for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
                if isinstance(node, ast.ImportFrom):
                    module = (importlib.util.resolve_name('.' * node.level + (node.module or ''),
                              name.rpartition('.')[0]) if node.level else node.module)
                    candidates = [module, *(module + '.' + alias.name for alias in node.names)] if module else []
                elif isinstance(node, ast.Import):
                    candidates = [alias.name for alias in node.names]
                else:
                    continue
                graph[name].update(candidate for candidate in candidates if candidate in paths and candidate != name)

        def visit(name: str, chain: tuple[str, ...]) -> None:
            self.assertNotIn(name, chain, ' -> '.join((*chain, name)))
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
from msplatform.execution import capacity_ledger, verify_artifact_layout
from msplatform.execution import gui_source_protection
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
. '{detached / 'src/msplatform/execution/resources/dependencies.ps1'}'
$dependency=[pscustomobject]@{{
 id='fixture';provider_scope='repository_core';provider_project='msplatform';provider_repo_path='src/msplatform'
 source_repo_path='src/msplatform/execution/resources/run_artifact_support.ps1';frozen_filename='copied.ps1'
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
            source = detached / "src/msplatform/execution/resources/run_artifact_support.ps1"
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
            shutil.copyfile(REPO_ROOT / "tests/contracts/fixtures/rf_ip_mr_y_minus55_plan.json", parent)
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
                self.assertIn("src/msplatform/execution/capacity_protection.py", paths)
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
from msplatform.execution import capacity_protection
assert Path(native_completion.__file__).is_relative_to(Path.cwd())
assert Path(write_run_manifest.__file__).is_relative_to(Path.cwd())
assert Path(capacity_protection.__file__).is_relative_to(Path.cwd())
"""
                if consumer == 'accelerator_interface':
                    statement += "\nfrom msplatform.backends.simion import ip_batching as batching\n"
                    statement += "assert Path(batching.__file__).is_relative_to(Path.cwd())\n"
                if consumer == 'accelerator_interface':
                    statement += "\nfrom msplatform.backends.simion import mr_bunch_source\n"
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
        from tests.workflows.single_reflection.test_single_reflection_preparation import fixture

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
            self.assertIn("src/msplatform/execution/reconcile_artifact_capacity.py",
                          {row["source_repo_path"] for row in selected})
            snapshot = run / "inputs/runtime_snapshot"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(python_import_roots(snapshot))
            artifact_root = Path(directory) / "artifacts"
            protected = artifact_root / "projects/instrument_assembly/runs/test"
            protected.mkdir(parents=True)
            command = [sys.executable, "-B", "-s", "-m",
                       "msplatform.execution.capacity_lease_cli",
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
class DenyWithdrawn:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('msplatform.workflows.local_frontend', 'msplatform.workflows.cooled_frontend')):
            raise AssertionError('withdrawn workflow imported: '+fullname)
sys.meta_path.insert(0,DenyWithdrawn())
class NoOrchestrationImport:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('integrations.workflows.single_reflection_flight.runtime',
                        'msplatform.workflows.single_reflection_flight.runtime',
                        'msplatform.workflows.single_reflection_flight.collect'):
            raise ImportError('pure evidence/continuation cannot import orchestration: '+fullname)
guard=NoOrchestrationImport()
sys.meta_path.insert(0,guard)
from msplatform.workflows.single_reflection_flight import downstream_fields
from msplatform.workflows.single_reflection_flight import continuation
from msplatform.backends.simion import tracking_collection as census
from msplatform.workflows.single_reflection_flight import pulse
sys.meta_path.remove(guard)
from msplatform.workflows.single_reflection_flight import prepare
from msplatform.workflows.single_reflection_flight import runtime
from msplatform.workflows.single_reflection_flight import collect
from msplatform.workflows.single_reflection_flight import frontend_fields
from msplatform.backends.simion import field_worker, native_plans
assert all(Path(m.__file__).is_relative_to(Path.cwd()) for m in (prepare,downstream_fields,runtime,collect,census,continuation,pulse,frontend_fields,field_worker,native_plans))
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
stage=frontend_fields.prepare_stage(run/'inputs',Path(sys.executable),run)
parent=frontend_fields.domain_members(stage,0,[])
assert parent['domain_id']=='parent' and parent['members']
assert all(Path(record['path']).is_relative_to(run/'inputs') for record in stage['resources'].values())
assert not (run/'simion').exists()

result=downstream_fields.plan_downstream_fields(preparation,run,snapshot_root=Path.cwd())
assert len(result['steps'])==5
assert all(Path(step['argv'][3]).is_relative_to(Path.cwd()) for step in result['steps'])
print(json.dumps(dict(status='FROZEN_DOWNSTREAM_PLAN_PASS',native_executed=False)))
"""
            planned = subprocess.run([sys.executable, "-B", "-s", "-c", statement, str(request), str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["status"], "FROZEN_DOWNSTREAM_PLAN_PASS")
            producer_module = snapshot / 'src/msplatform/backends/simion/frontend_fields.py'
            original_module = producer_module.read_bytes()
            producer_module.unlink()
            try:
                missing = subprocess.run([sys.executable, '-B', '-s', '-c',
                    'from msplatform.workflows.single_reflection_flight import frontend_fields'],
                    cwd=snapshot, env=environment, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn('frontend_fields', missing.stderr)
            finally:
                producer_module.write_bytes(original_module)
            # Remove a non-Python provider resource. A new detached process
            # must fail before execution instead of searching the live tree.
            resource = snapshot / "src/msplatform/backends/simion/resources/oatof_reflectron_ideal_10_5.gem"
            resource.unlink()
            refused = subprocess.run([sys.executable, "-B", "-s", "-c",
                "import json,sys; from pathlib import Path; "
                "from msplatform.backends.simion.downstream_fields import plan_downstream_fields; "
                "plan_downstream_fields(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]),snapshot_root=Path.cwd())",
                str(run / "preparation_for_dependency_test.json"), str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("FileNotFoundError: frozen SIMION GEM resource is missing: "
                          "oatof_reflectron_ideal_10_5.gem", refused.stderr)






    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_changed_frozen_dependency_reports_both_paths_and_measured_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = root / "repo"
            source = repo / "src/msplatform/fixture.txt"
            source.parent.mkdir(parents=True)
            original = b"dependency fixture\n"
            source.write_bytes(original)
            inputs = root / "inputs"
            destination = inputs / "runtime_snapshot/src/msplatform/fixture.txt"
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
 id='fixture';provider_scope='repository_core';provider_project='msplatform';provider_repo_path='src/msplatform'
 source_repo_path='src/msplatform/fixture.txt';frozen_filename='runtime_snapshot/src/msplatform/fixture.txt'
 run_input_name='fixture';consumers=@('single_reflection_flight')
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
            shutil.copytree(REPO_ROOT / "src/msplatform", root / "src/msplatform", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            groups = [dict(provider_scope="repository_core", provider_project="msplatform",
                files=[], python_packages=[], python_modules=[])]
            for number in range(4):
                source = f"src/msplatform/provider{number}.txt"
                path = root / source
                path.write_text(f"VALUE = {number}\n", encoding="utf-8")
                groups[0]["files"].append(dict(id=f"provider{number}", source_repo_path=source,
                    consumers=["single_reflection_flight"]))
            contract = root / "src/msplatform/workflows/config/dependencies.json"
            contract.write_text(json.dumps(dict(schema_version=3, role="workflow_runtime_dependencies",
                owner_id="instrument_assembly", consumer_ids=["single_reflection_flight"], providers=groups)), encoding="utf-8")
            package = root / "src/msplatform/pkg"
            package.mkdir(parents=True)
            (package / "entry.py").write_text(
                "from .added_helper import VALUE\n"
                "def prepare(destination):\n"
                "    destination.write_text(str(VALUE), encoding='utf-8')\n", encoding="utf-8")
            groups[0]["python_packages"].append(dict(
                source_repo_path="src/msplatform/pkg", consumers=["single_reflection_flight"]))
            groups[0]["python_packages"].append(dict(
                source_repo_path="src/msplatform/unrequested", consumers=["not_requested"]))
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
$f=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{root}' -ContractPath '{contract}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId single_reflection_flight
Write-Output ('FROZEN_INPUT_COUNT='+@($f.identities).Count)
if(@($f.identities).Count-ne7){{throw 'provider count differs'}}
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
  @{{change={{param($d) $d.providers[0].provider_project='unknown'}};message='*scientific-core provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='common/provider3.txt'}};message='*escapes provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='integrations/../common/provider3.txt'}};message='*escapes its provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='integrations/missing.txt'}};message='*escapes provider*'}},
  @{{change={{param($d) $d.providers[0].files+=$d.providers[0].files[0]}};message='*duplicate dependency id*'}},
  @{{change={{param($d) $d.providers[0].files+=@($d.providers[0].files[0]|ConvertTo-Json|ConvertFrom-Json);$d.providers[0].files[1].id='other'}};message='*duplicate dependency id*'}},
  @{{change={{param($d) $d.providers[0].files[0].consumers=@('unknown')}};message='*invalid consumers*'}},
  @{{change={{param($d) $d.consumer_ids=@('other')}};message='*Unregistered*'}}
)
$index=0
foreach($case in $cases){{
 $bad=$valid|ConvertFrom-Json
 & $case.change $bad
 $bad|ConvertTo-Json -Depth 30|Set-Content '{contract}'
 $destination='{output}-invalid'+$index
 try{{Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{root}' -ContractPath '{contract}' -InputDir $destination -OwnerId instrument_assembly -ConsumerId single_reflection_flight;throw 'invalid author accepted'}}
 catch{{Write-Output ('CASE='+$index+' ACTUAL='+$_.Exception.Message+' EXPECTED='+[string]$case.message);if($_.Exception.Message -inotlike ([string]$case.message)){{throw}}}}
 if(Test-Path $destination){{throw 'Invalid author copied files before rejection'}}
 $index++
}}
$valid|Set-Content '{contract}'
try{{Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{root}' -ContractPath '{contract}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId single_reflection_flight;throw 'existing destination accepted'}}
catch{{if($_.Exception.Message-notlike'*already exists*'){{throw}}}}
foreach($scope in @('project','repository_common','integration')){{
 try{{Assert-DependencyProviderIdentity -RepoRoot '{root}' -DependencyId 'retired' -Scope $scope -Provider 'legacy' -ProviderRelative 'legacy';throw 'retired scope accepted'}}
 catch{{if($_.Exception.Message-notlike'*unsupported provider scope*'){{throw}}}}
}}
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
                {"python:src/msplatform/__init__.py", "python:src/msplatform/pkg/entry.py", "python:src/msplatform/pkg/added_helper.py"})
            root.rename(root.with_name("author-unavailable"))
            plan = Path(directory) / "detached-plan.txt"
            code = "import json,sys;from pathlib import Path;sys.path[:0]=json.loads(sys.argv[1]);from msplatform.pkg.entry import prepare;prepare(Path(sys.argv[2]))"
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                json.dumps(python_import_roots(output / "runtime_snapshot")), str(plan)], cwd=output,
                capture_output=True, text=True, encoding="utf-8", errors="backslashreplace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(plan.read_text(), "42")


if __name__ == "__main__":
    unittest.main()
