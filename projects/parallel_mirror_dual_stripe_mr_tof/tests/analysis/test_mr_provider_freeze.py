"""Exercise the actual OA/MR frozen reader and provider in isolated children."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
PROFILE_ID = "closed_two_zone_compact_mr_axial_r3_gap1_4mm"
PROVIDER = "src/msplatform/components/parallel_mirror_dual_stripe_mr_tof/provider.py"

# Test-only entry: all scientific imports below are from the real frozen selection.
ENTRY = r'''import json, pathlib, sys
from msplatform.components.parallel_mirror_dual_stripe_mr_tof import provider, candidate_contract, resolved_geometry
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface import resolve_assembly_interface as mr_interface
from msplatform.components.orthogonal_accelerator.assembly_interface import resolve_assembly_interface as oa_interface
from msplatform.backends.simion.oa_focus_plan import derive
from msplatform.backends.simion import collision_overlay
from msplatform.backends.comsol.static_field_binding import verify_joint_asset_records
from msplatform.assembly.resolve_assembly import compile_assembly_layout
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import resolve_accelerator_iob_origin, resolve_oa_mr_direct_pose
root = pathlib.Path(sys.argv[1]).resolve()
collision_path = root / 'src/msplatform/backends/simion/collision_overlay.py'
assert pathlib.Path(collision_overlay.__file__).resolve() == collision_path.resolve()
assert pathlib.Path(collision_overlay.__spec__.origin).resolve() == collision_path.resolve()
# Synthetic marker reaches the real selected-overlay verifier, without asserting field validity.
try:
    verify_joint_asset_records({'sources': {}, 'records': {}, 'instances': [], 'refinement_windows': [], 'collision_overlay': {}})
except KeyError as error:
    assert error.args == ('patch_plan_path',)
else:
    raise AssertionError('incomplete overlay was accepted')
inputs = pathlib.Path(sys.argv[2]).resolve()
profile_id = sys.argv[3]
for mod, relative in ((provider, 'provider.py'), (candidate_contract, 'candidate_contract.py'), (resolved_geometry, 'resolved_geometry.py')):
    expected = root / 'src/msplatform/components/parallel_mirror_dual_stripe_mr_tof' / relative
    assert pathlib.Path(mod.__file__).resolve() == expected.resolve()
    assert pathlib.Path(mod.__spec__.origin).resolve() == expected.resolve()
contract = candidate_contract.load_contract(inputs / 'candidate.json')
profile = json.loads((inputs / 'oa.json').read_text(encoding='utf-8'))['geometry_profiles'][profile_id]
requirements = resolved_geometry.build_two_zone_accelerator_requirements(contract, geometry_profile=profile)
authority = {'accelerator_requirements': requirements, 'geometry_profile': profile, 'geometry_profile_id': profile_id}
source = {'contract': contract, 'accelerator_requirements': requirements, 'geometry_profile': profile}
result = provider.resolve_component(source, geometry_profile_id=profile_id)
assert result['assembly_interface']['schema_version'] == 3
assert len(result['assembly_interface']['component_electrodes']) == 22
plan = json.loads((inputs / 'plan.json').read_text(encoding='utf-8'))
campaign = inputs / 'campaign.json'
provider_plan = derive(campaign, geometry_profile=profile, mesh_mm_per_gu=[0.25, 0.25, 0.1])
direct = resolve_oa_mr_direct_pose(provider_plan, plan)
plan['components'][direct['oa_instance_id']] = oa_interface(provider_plan['requirements'], geometry_profile_id=profile_id, geometry_profile=profile)
plan['components'][direct['mr_instance_id']] = mr_interface(result['resolved_design'], geometry_profile_id=profile_id, schema_version=3)
plan = compile_assembly_layout(plan['recipe'], plan['components'])
assert plan['schema_version'] == 5
assert resolve_accelerator_iob_origin(contract, provider_plan, plan, accelerator_geometry_authority=authority, mr_source_design=source) == (0.0, -72.25, -6.0)
print('MR_FROZEN_CONSUMER_PASS')
'''

SCRIPT = r'''param($Repo,$Inputs,$Config,$Mode,$Python)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
. (Join-Path $Repo 'src/msplatform/execution/resources/frozen_python_package.ps1')
if ($Mode -eq 'freeze') {
  $f=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') -InputDir $Inputs -OwnerId instrument_assembly -ConsumerId oa_mr
  $f | ConvertTo-Json -Depth 40 -Compress
  exit 0
}
$c=Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
Invoke-IsolatedFrozenPythonModule -Python $Python -Package $c.package -Module frozen_mr_probe -Arguments @($c.snapshot,$c.fixture,$c.profile) -RequiredModuleNames @('msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider','msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract','msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry','msplatform.backends.simion.collision_overlay') -ForbiddenRoots @($Repo) -WorkingDirectory $c.fixture | ConvertTo-Json -Depth 40 -Compress
'''


class MrProviderFreezeTests(unittest.TestCase):
    def test_actual_oa_mr_selection_is_isolated_and_fail_closed(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        with tempfile.TemporaryDirectory(prefix='mr_provider_frozen_') as directory:
            base = Path(directory)
            inputs, fixture = base / 'inputs', base / 'fixture'
            inputs.mkdir()
            fixture.mkdir()
            script = base / 'driver.ps1'
            script.write_text(SCRIPT, encoding='utf-8')
            config = base / 'request.json'
            environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
            def invoke(mode):
                return subprocess.run([pwsh, '-NoProfile', '-File', str(script), str(ROOT), str(inputs), str(config), mode, sys.executable], cwd=fixture, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=180)
            frozen = invoke('freeze')
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            snapshot = Path(json.loads(frozen.stdout)['execution_root'])
            for name, source in {
                'candidate.json': ROOT / 'projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json',
                'oa.json': ROOT / 'projects/orthogonal_accelerator/config/component_contract.json',
                'campaign.json': ROOT / 'projects/orthogonal_accelerator/config/two_zone_component_focus_campaign.json',
                'plan.json': ROOT / 'integrations/config/recipes/oa_mr_two_zone_gap30_plan.json',
            }.items():
                shutil.copyfile(source, fixture / name)
                self.assertEqual((fixture / name).read_bytes(), source.read_bytes())
            provider = snapshot / PROVIDER
            self.assertEqual(provider.read_bytes(), (ROOT / PROVIDER).read_bytes())
            # Add only an explicitly inventoried test entry after the real freezer.
            (snapshot / 'frozen_mr_probe.py').write_text(ENTRY, encoding='utf-8')
            files = [{'relative_path': p.relative_to(snapshot).as_posix(), 'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest().upper()} for p in snapshot.rglob('*') if p.is_file()]
            package = {'code_root': str(snapshot), 'package_roots': [str(snapshot / 'src'), str(snapshot)], 'files': files}
            config.write_text(json.dumps({'package': package, 'snapshot': str(snapshot), 'fixture': str(fixture), 'profile': PROFILE_ID}), encoding='utf-8')
            positive = invoke('run')
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertIn('MR_FROZEN_CONSUMER_PASS', json.loads(positive.stdout)['module_stdout'])
            original = provider.read_bytes()
            provider.unlink()
            missing = invoke('run')
            self.assertNotEqual(missing.returncode, 0, missing.stdout + missing.stderr)
            self.assertIn('Frozen Python dependency is missing', missing.stderr)
            # Even an internally consistent inventory omitting the module must
            # not import the still-present live checkout copy.
            omitted = dict(package)
            omitted['files'] = [row for row in files if row['relative_path'] != PROVIDER]
            config.write_text(json.dumps({'package': omitted, 'snapshot': str(snapshot), 'fixture': str(fixture), 'profile': PROFILE_ID}), encoding='utf-8')
            no_backfill = invoke('run')
            self.assertNotEqual(no_backfill.returncode, 0, no_backfill.stdout + no_backfill.stderr)
            self.assertIn('msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider', no_backfill.stderr)
            config.write_text(json.dumps({'package': package, 'snapshot': str(snapshot), 'fixture': str(fixture), 'profile': PROFILE_ID}), encoding='utf-8')
            provider.write_bytes(original + b'\n# tampered\n')
            tampered = invoke('run')
            self.assertNotEqual(tampered.returncode, 0, tampered.stdout + tampered.stderr)
            self.assertIn('Frozen Python dependency hash differs', tampered.stderr)
            provider.write_bytes(original)
            collision = snapshot / 'src/msplatform/backends/simion/collision_overlay.py'
            collision_original = collision.read_bytes()
            collision.unlink()
            missing_collision = invoke('run')
            self.assertNotEqual(missing_collision.returncode, 0, missing_collision.stdout + missing_collision.stderr)
            self.assertIn('Frozen Python dependency is missing', missing_collision.stderr)
            omitted_collision = dict(package)
            omitted_collision['files'] = [row for row in files if row['relative_path'] != 'src/msplatform/backends/simion/collision_overlay.py']
            config.write_text(json.dumps({'package': omitted_collision, 'snapshot': str(snapshot), 'fixture': str(fixture), 'profile': PROFILE_ID}), encoding='utf-8')
            no_collision_backfill = invoke('run')
            self.assertNotEqual(no_collision_backfill.returncode, 0, no_collision_backfill.stdout + no_collision_backfill.stderr)
            self.assertIn('msplatform.backends.simion.collision_overlay', no_collision_backfill.stderr)
            collision.write_bytes(collision_original)
            for name, source in {'candidate.json': ROOT / 'projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json', 'oa.json': ROOT / 'projects/orthogonal_accelerator/config/component_contract.json', 'campaign.json': ROOT / 'projects/orthogonal_accelerator/config/two_zone_component_focus_campaign.json', 'plan.json': ROOT / 'integrations/config/recipes/oa_mr_two_zone_gap30_plan.json'}.items():
                self.assertEqual((fixture / name).read_bytes(), source.read_bytes())


class FrozenCollectionGateBoundaryTests(unittest.TestCase):
    def test_collection_gate_actual_executor_uses_frozen_identity(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        with tempfile.TemporaryDirectory(prefix='oa_mr_gate_boundary_') as directory:
            base = Path(directory)
            snapshot = base / 'snapshot'
            author = base / 'author'
            fixture = base / 'fixture'
            fixture.mkdir()
            source_paths = (
                'src/msplatform/__init__.py', 'src/msplatform/workflows/__init__.py',
                'src/msplatform/workflows/oa_mr/__init__.py',
                'src/msplatform/workflows/oa_mr/collection_gate.py',
                'src/msplatform/execution/resources/frozen_python_package.ps1',
            )
            for relative in source_paths:
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            # A real competing author module is present throughout all cases.
            shutil.copytree(snapshot / 'src/msplatform', author / 'src/msplatform')
            (author / 'src/msplatform/workflows/oa_mr/collection_gate.py').write_text(
                "raise RuntimeError('AUTHOR_FALLBACK_EXECUTED')\n", encoding='utf-8')
            contract = snapshot / 'contract.json'
            contract.write_text('{}', encoding='utf-8')
            records = [dict(source_repo_path=p.relative_to(snapshot).as_posix(), snapshot_path=str(p),
                            sha256=hashlib.sha256(p.read_bytes()).hexdigest().upper())
                       for p in snapshot.rglob('*') if p.is_file()]
            contract_record = next(x for x in records if x['source_repo_path'] == 'contract.json')
            descriptor = base / 'descriptor.json'
            descriptor.write_text(json.dumps(dict(execution_root=str(snapshot),
                identities=[x for x in records if x is not contract_record],
                dependency_contract_identity=contract_record)), encoding='utf-8')
            observation = fixture / 'observation.json'
            observation.write_text(json.dumps({'cohort_analysis': {'event_integrity_passed': True,
                                                                  'detection_rate': 0.8}}), encoding='utf-8')
            output = fixture / 'gate.json'
            script = base / 'exercise.ps1'
            script.write_text(r"""param($Runner,$Descriptor,$Observation,$Output,$Python,$Author)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
$fn=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-FrozenCollectionGate'},$true)
if($null-eq$fn){throw 'Actual gate invocation function missing'}
Invoke-Expression $fn.Extent.Text
$frozen=Get-Content -LiteralPath $Descriptor -Raw|ConvertFrom-Json
Invoke-FrozenCollectionGate -Frozen $frozen -Observation $Observation -Output $Output -Python $Python -AuthorRoot $Author
""", encoding='utf-8')
            env = {**os.environ, 'PYTHONPATH': str(author / 'src')}
            def invoke():
                return subprocess.run([pwsh, '-NoProfile', '-File', str(script),
                    str(ROOT / 'integrations/workflows/oa_mr/execute.ps1'), str(descriptor),
                    str(observation), str(output), sys.executable, str(author)], cwd=fixture,
                    env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            positive = invoke()
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['status'], 'accepted')
            self.assertIn('MRTOF_BUNCH_COLLECTION_GATE=accepted', positive.stdout)
            output.unlink()
            module = snapshot / 'src/msplatform/workflows/oa_mr/collection_gate.py'
            original = module.read_bytes()
            try:
                module.unlink()
                missing = invoke()
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn('Frozen Python dependency is missing', missing.stderr)
                self.assertNotIn('AUTHOR_FALLBACK_EXECUTED', missing.stderr)
                self.assertFalse(output.exists())
                full_descriptor = descriptor.read_text(encoding='utf-8')
                omitted = json.loads(full_descriptor)
                omitted['identities'] = [entry for entry in omitted['identities']
                    if entry['source_repo_path'] != 'src/msplatform/workflows/oa_mr/collection_gate.py']
                descriptor.write_text(json.dumps(omitted), encoding='utf-8')
                no_fallback = invoke()
                self.assertNotEqual(no_fallback.returncode, 0)
                self.assertIn('msplatform.workflows.oa_mr.collection_gate', no_fallback.stderr)
                self.assertNotIn('AUTHOR_FALLBACK_EXECUTED', no_fallback.stderr)
                self.assertFalse(output.exists())
                descriptor.write_text(full_descriptor, encoding='utf-8')
                module.write_bytes(original + b'\n# changed\n')
                tampered = invoke()
                self.assertNotEqual(tampered.returncode, 0)
                self.assertIn('Frozen Python dependency hash differs', tampered.stderr)
                self.assertFalse(output.exists())
            finally:
                module.write_bytes(original)


class PublicFrozenCollectionGateTests(unittest.TestCase):
    def test_public_oa_mr_freezer_and_actual_gate_boundary(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        with tempfile.TemporaryDirectory(prefix='oa_mr_public_gate_') as directory:
            base = Path(directory)
            inputs, fixture = base / 'inputs', base / 'fixture'
            inputs.mkdir()
            fixture.mkdir()
            freeze_script = base / 'freeze.ps1'
            freeze_script.write_text(SCRIPT, encoding='utf-8')
            descriptor = base / 'frozen.json'
            environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
            frozen = subprocess.run([pwsh, '-NoProfile', '-File', str(freeze_script), str(ROOT),
                str(inputs), str(descriptor), 'freeze', sys.executable], cwd=fixture,
                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=180)
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            data = json.loads(frozen.stdout)
            snapshot = Path(data['execution_root'])
            relative = 'src/msplatform/workflows/oa_mr/collection_gate.py'
            module = snapshot / relative
            self.assertEqual(module.read_bytes(), (ROOT / relative).read_bytes())
            identities = [row for row in data['identities'] if row['source_repo_path'] == relative]
            self.assertEqual(len(identities), 1)
            self.assertEqual(identities[0]['sha256'], hashlib.sha256(module.read_bytes()).hexdigest().upper())
            helper = [row for row in data['identities'] if row['source_repo_path'] ==
                      'src/msplatform/execution/resources/frozen_python_package.ps1']
            self.assertEqual(len(helper), 1)
            descriptor.write_text(json.dumps(data), encoding='utf-8')
            runner = base / 'actual-gate.ps1'
            runner.write_text(r"""param($Repo,$Descriptor,$Observation,$Output,$Python)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/oa_mr/execute.ps1'),[ref]$tokens,[ref]$errors)
$fn=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-FrozenCollectionGate'},$true)
if($null-eq$fn){throw 'Actual gate invocation function missing'}
Invoke-Expression $fn.Extent.Text
$frozen=Get-Content -LiteralPath $Descriptor -Raw|ConvertFrom-Json
Invoke-FrozenCollectionGate -Frozen $frozen -Observation $Observation -Output $Output -Python $Python -AuthorRoot $Repo
""", encoding='utf-8')
            observation, output = fixture / 'observation.json', fixture / 'gate.json'
            observation.write_text(json.dumps({'cohort_analysis': {'event_integrity_passed': True,
                                                                  'detection_rate': 0.8}}), encoding='utf-8')
            def invoke():
                return subprocess.run([pwsh, '-NoProfile', '-File', str(runner), str(ROOT), str(descriptor),
                    str(observation), str(output), sys.executable], cwd=fixture, env=environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=180)
            accepted = invoke()
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['status'], 'accepted')
            output.unlink()
            original = module.read_bytes()
            try:
                module.unlink()
                missing = invoke()
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn('Frozen Python dependency is missing', missing.stderr)
                self.assertFalse(output.exists())
                module.write_bytes(original + b'\n# tampered\n')
                tampered = invoke()
                self.assertNotEqual(tampered.returncode, 0)
                self.assertIn('Frozen Python dependency hash differs', tampered.stderr)
                self.assertFalse(output.exists())
            finally:
                module.write_bytes(original)
