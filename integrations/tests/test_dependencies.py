from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = REPO_ROOT / "integrations"
INVENTORY = INTEGRATION_ROOT / "config/runtime_dependencies.json"
DEPENDENCIES = INTEGRATION_ROOT / "runtime/dependencies.ps1"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class DependencyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_prepared_joint_derives_scope_from_its_complete_frozen_assembly_closure(self) -> None:
        """Run the actual parent compiler detached, including non-Python schemas."""
        required = (
            "common/integration/resolve_assembly.py",
            "common/contracts/machine_contracts.py",
            "common/contracts/rigid_transform.py",
            "common/contracts/schemas/assembly_recipe.schema.json",
            "common/contracts/schemas/component_geometry_interface.schema.json",
            "common/contracts/schemas/composition_plan.schema.json",
        )
        selected = {item["source_repo_path"] for group in load(INVENTORY)["providers"]
                    for item in group["files"] if "prepared_joint" in item["consumers"]}
        self.assertTrue(set(required) <= selected)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            parent = output / "parent.json"
            shutil.copyfile(INTEGRATION_ROOT / "config/recipes/multipole_ip_mr_y_minus55_plan.json", parent)
            freeze = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId prepared_joint
"""
            frozen = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", freeze],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = output / "runtime_snapshot"
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            statement = """
import json,sys
from pathlib import Path
from common.integration import resolve_assembly
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
                capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
            self.assertIn("FROZEN_PREPARED_JOINT_ASSEMBLY_SCOPE=PASS", complete.stdout)
            for relative in required:
                with self.subTest(missing=relative):
                    resource = snapshot / relative
                    contents = resource.read_bytes()
                    resource.unlink()
                    try:
                        refused = subprocess.run(command, cwd=snapshot, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
                        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
                        self.assertNotIn("FROZEN_PREPARED_JOINT_ASSEMBLY_SCOPE=PASS", refused.stdout)
                        self.assertIn(Path(relative).stem.split('.')[0], refused.stderr)
                    finally:
                        resource.write_bytes(contents)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_native_completion_provider_imports_in_each_frozen_consumer(self) -> None:
        for consumer in ('accelerator_interface', 'cooled_frontend'):
            with self.subTest(consumer=consumer), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                script = f"""
. '{DEPENDENCIES}'
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId {consumer}
"""
                frozen = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=REPO_ROOT,
                    capture_output=True, text=True, encoding='utf-8', timeout=120)
                self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
                snapshot = output / 'runtime_snapshot'
                environment = dict(os.environ)
                environment.pop('PYTHONPATH', None)
                statement = """
from pathlib import Path
from common.simion import native_completion
from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
assert all(Path(module.__file__).is_relative_to(Path.cwd()) for module in (native_completion,batching))
"""
                if consumer == 'accelerator_interface':
                    statement += "\nfrom projects.parallel_mirror_dual_stripe_mr_tof.analysis import bunch_source_and_schedule\n"
                command = [sys.executable, '-B', '-s', '-c', statement]
                completed = subprocess.run(command, cwd=snapshot, env=environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                (snapshot / 'common/simion/native_completion.py').unlink()
                missing = subprocess.run(command, cwd=snapshot, env=environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn('native_completion', missing.stderr)

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
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{run / 'inputs'}' -OwnerId instrument_assembly -ConsumerId single_reflection_flight
"""
            frozen = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", freeze],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = run / "inputs/runtime_snapshot"
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
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
from integrations.workflows.single_reflection_flight import prepare,downstream_fields,runtime,collect,census
assert all(Path(m.__file__).is_relative_to(Path.cwd()) for m in (prepare,downstream_fields,runtime,collect,census))
assert not any('rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' in name for name in sys.modules)
assert not (Path.cwd()/'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer').exists()
request,run=map(Path,sys.argv[1:])
# TEST_ONLY schema branch copied from the fixture, never used as scientific input.
from common.contracts.machine_contracts import validate_schema
from common.contracts.verify_run_manifest import record_path
request_value=json.loads(request.read_text())
provider=next(v for v in request_value['providers']['instances'].values() if 'geometry' not in v)
enclosure_fixture=json.loads(record_path(provider['resolved_design'],base_dir=request.parent).read_text())
enclosure_fixture['governance']={key:'A'*64 for key in ('design_variables_sha256','optimization_envelope_sha256','design_request_file_sha256')}
enclosure_fixture['governance']['enclosure_model']='cylindrical_grounded_shield_through_entrance_exit_v1'
validate_schema(enclosure_fixture,Path.cwd()/'common/contracts/schemas/multipole_resolved_design.schema.json')
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
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["status"], "FROZEN_DOWNSTREAM_PLAN_PASS")
            # Remove a non-Python provider resource. A new detached process
            # must fail before execution instead of searching the live tree.
            resource = snapshot / "projects/single_reflection_oa_tof_mass_analyzer/simion/reflectron/oatof_reflectron_ideal_10_5.gem"
            resource.unlink()
            refused = subprocess.run([sys.executable, "-B", "-s", "-c",
                "import json,sys; from pathlib import Path; "
                "from integrations.workflows.single_reflection_flight.downstream_fields import plan_downstream_fields; "
                "plan_downstream_fields(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]),snapshot_root=Path.cwd())",
                str(run / "preparation_for_dependency_test.json"), str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("frozen downstream provider resources are incomplete", refused.stderr)

    def test_single_reflection_capacity_command_declares_python_import_closure(self) -> None:
        paths = {row["source_repo_path"] for group in load(INVENTORY)["providers"]
                 for row in group["files"] if "single_reflection_flight" in row["consumers"]}
        pending = ["common/contracts/reconcile_artifact_capacity.py"]
        visited = set()
        while pending:
            relative = pending.pop()
            if relative in visited:
                continue
            visited.add(relative)
            self.assertIn(relative, paths, f"unregistered capacity command import: {relative}")
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module, *[node.module + "." + item.name for item in node.names]]
                elif isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                for name in names:
                    imported = name.replace(".", "/") + ".py"
                    if name.split(".")[0] in {"common", "projects", "integrations"} and (REPO_ROOT / imported).is_file():
                        pending.append(imported)

    def test_local_consumer_declares_complete_python_import_closure(self) -> None:
        dependencies = [item for group in load(INVENTORY)["providers"] for item in group["files"]]
        required_ip = {"projects/dual_pressure_rectilinear_ion_processor/analysis/"+name+".py"
                       for name in ("guide_interface", "native_geometry", "electrode_contours", "convex_geometry")}
        prefix = "integrations"
        selected = [r for r in dependencies if "local_frontend" in r["consumers"]]
        paths = {r["source_repo_path"] for r in selected}
        self.assertTrue(required_ip <= paths)
        self.assertNotIn("oatof_analyzer_component", {r["id"] for r in selected})
        for relative in sorted(paths):
            if not relative.endswith(".py"):
                continue
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    # The shared figure imports the conditioner adapter only
                    # for a cooled contract; require that exact guard before
                    # excluding it from the bare-guide consumer's closure.
                    if node.module == "integrations.workflows.cooled_frontend.plot_geometry":
                        self.assertEqual(relative, prefix.replace(".", "/") + "/analysis/plot_single_flight_spatial_six_panel.py")
                        self.assertTrue(any(isinstance(branch, ast.If)
                                            and ast.unparse(branch.test) == "conditioner is not None"
                                            and node in branch.body for branch in ast.walk(tree)))
                        continue
                    names = [node.module, *[node.module+"."+a.name for a in node.names]]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                for name in names:
                    imported = name.replace(".", "/")+".py"
                    if name.split(".")[0] in {"common", "projects", "integrations"} and (REPO_ROOT/imported).is_file():
                        self.assertIn(imported, paths, f"unregistered local_frontend import: {relative} -> {imported}")

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
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId cooled_frontend
"""
            result = subprocess.run([pwsh, "-NoProfile", "-Command", freeze], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            snapshot = output / "runtime_snapshot"
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
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
                "from common.integration import resolve_assembly; "
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
$f=Freeze-ConsumerDependencies -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend
if(@($f.identities).Count-lt1){{throw 'empty selected closure'}}
Write-Output $f.execution_root
"""
            result = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
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
            env.pop("PYTHONPATH", None)
            statement = ("from integrations.workflows.local_frontend "
                         "import prepare,runtime,analyze; from integrations.runtime "
                         "import standalone_pa_family; from common.contracts import run_capacity_lifecycle; "
                         "assert prepare.ROLE=='instrument_assembly_local_frontend_request'; print('LOCAL_SNAPSHOT_IMPORT=PASS')")
            completed = subprocess.run([sys.executable, "-s", "-c", statement], cwd=snapshot, env=env,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            # Removing one declared provider proves the clean snapshot cannot
            # silently recover an undeclared cross-project import from the repo.
            (snapshot/"projects/dual_pressure_rectilinear_ion_processor/analysis/guide_interface.py").unlink()
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
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}' -InputDir '{workspace / 'frozen'}' -OwnerId instrument_assembly -ConsumerId local_frontend
"""
            frozen = subprocess.run([pwsh, "-NoProfile", "-Command", freeze], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout+frozen.stderr)
            snapshot = workspace / "frozen/runtime_snapshot"
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            module = "integrations.workflows.local_frontend.prepare"
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
                    from common.contracts.canonical_clock_authority import validate_clock_authority
                    self.assertEqual(validate_clock_authority(output / "inputs/clock_authority.json", output)["clock_epoch_id"],
                                     load(output / "inputs/source_identity.json")["clock_epoch_id"])
                    self.assertFalse((output / "inputs/source_clock.json").exists())
                    result = json.loads(completed.stdout)
                    self.assertEqual((result["status"], result["particle_count"]), ("validated", 100))

            # Each omitted resource failed in a real frozen run. Fresh processes
            # and -B prevent an already imported module/pyc masking the omission.
            for relative in ("common/contracts/schemas/simion_rectangular_aperture_discretization.schema.json",
                             "common/contracts/canonical_clock_authority.py",
                             "common/contracts/schemas/canonical_clock_authority.schema.json",
                             "common/contracts/schemas/assembly_recipe.schema.json",
                             "common/contracts/schemas/component_geometry_interface.schema.json",
                             "common/contracts/schemas/composition_plan.schema.json",
                             "common/integration/resolve_assembly.py",
                             "projects/orthogonal_accelerator/analysis/assembly_interface.py",
                             "projects/orthogonal_accelerator/analysis/three_zone_ideal_theory.py"):
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
            groups = []
            for number, (scope, owner, provider) in enumerate((
                ("integration", "instrument_assembly", "integrations"),
                ("integration", "legacy", "integrations/legacy"),
                ("project", "device", "projects/device"),
                ("repository_common", "common", "common"),
            )):
                source = f"{provider}/provider{number}.py"
                path = root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"VALUE = {number}\n", encoding="utf-8")
                groups.append(dict(provider_scope=scope, provider_project=owner,
                    files=[dict(id=f"provider{number}", source_repo_path=source, consumers=["local_frontend"])]))
            contract = root / "integrations/config/dependencies.json"
            contract.write_text(json.dumps(dict(schema_version=2, role="integration_runtime_dependencies",
                owner_id="instrument_assembly", consumer_ids=["local_frontend"], providers=groups)), encoding="utf-8")
            output = Path(directory) / "inputs"
            script = f"""
. '{DEPENDENCIES}'
$f=Freeze-ConsumerDependencies -RepoRoot '{root}' -ContractPath '{contract}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend
if(@($f.identities).Count-ne4){{throw 'provider count differs'}}
$inventory=Get-Content $f.code_inventory_path -Raw|ConvertFrom-Json
if($inventory.owner_id-ne'instrument_assembly' -or $inventory.PSObject.Properties.Name-contains'consumer_project'){{throw 'owner identity differs'}}
foreach($entry in $inventory.dependencies){{
 if($entry.run_input_name-cne$entry.id-or$entry.frozen_filename-cne('runtime_snapshot/'+$entry.source_repo_path)){{throw 'derived fields differ'}}
}}
if((Get-Content $f.dependency_contract_path -Raw)-cne(Get-Content '{contract}' -Raw)){{throw 'contract differs'}}
$valid=Get-Content '{contract}' -Raw
$cases=@(
  @{{change={{param($d) $d.owner_id='legacy'}};message='*identity*'}},
  @{{change={{param($d) $d.schema_version=1}};message='*schema 2*'}},
  @{{change={{param($d) $d.providers[0].provider_project='unknown'}};message='*registered exactly once*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='common/provider3.py'}};message='*escapes provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='integrations/../common/provider3.py'}};message='*escapes its provider*'}},
  @{{change={{param($d) $d.providers[0].files[0].source_repo_path='integrations/missing.py'}};message='*is missing*'}},
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
 try{{Freeze-ConsumerDependencies -RepoRoot '{root}' -ContractPath '{contract}' -InputDir $destination -OwnerId instrument_assembly -ConsumerId local_frontend;throw 'invalid author accepted'}}
 catch{{if($_.Exception.Message-notlike$case.message){{throw}}}}
 if(Test-Path $destination){{throw 'Invalid author copied files before rejection'}}
 $index++
}}
$valid|Set-Content '{contract}'
try{{Freeze-ConsumerDependencies -RepoRoot '{root}' -ContractPath '{contract}' -InputDir '{output}' -OwnerId instrument_assembly -ConsumerId local_frontend;throw 'existing destination accepted'}}
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


if __name__ == "__main__":
    unittest.main()
