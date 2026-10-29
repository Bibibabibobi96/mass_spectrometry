from __future__ import annotations

from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest

from common.simion.pa_family_cache import PAFamilyCacheError, advance_pa_family_cache_transaction

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_response_bank import (
    NATIVE_RESPONSE_NAMES,
    RAW_NAME,
    RECEIPT_NAME,
    STANDALONE_RESPONSE_NAMES,
    response_bank_filenames,
    verify_response_bank_staging,
    write_response_bank_receipt,
)


PROJECT = Path(__file__).resolve().parents[2]


class NativeCorridorResponseBankTest(unittest.TestCase):
    def test_empty_transaction_payload_counts_as_zero_bytes(self) -> None:
        source = (PROJECT / 'simion/run_native_corridor_response_bank.ps1').read_text(encoding='utf-8-sig')
        function = source.split('function Get-ExistingTransactionPayloadBytes {', 1)[1].split('\nfunction ', 1)[0]
        with TemporaryDirectory() as temporary:
            payload = Path(temporary) / '.transactions' / ('A' * 64) / 'payload'
            payload.mkdir(parents=True)
            script = 'function Get-ExistingTransactionPayloadBytes {' + function + '\n'
            script += f"$cacheRoot='{Path(temporary).as_posix()}';"
            script += "$value=Get-ExistingTransactionPayloadBytes -CacheKey ('A'*64);if($value-ne0){exit 3};'PASS'"
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                cwd=PROJECT, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)

    def test_published_correction_request_preserves_frozen_identity_on_retry(self) -> None:
        script = r'''
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$block=$ast.Find({param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if($correctPublication){') -and $n.Extent.Text.Contains('$priorCorrection=')},$true)
if($null-eq$block){throw 'Missing owner correction request block'}
$correctPublication=$true;$CorrectPublishedInventoryMember='bank.pa#';$resultDir=$Root;$continuationOutputs=@()
$capacitySession=[pscustomobject]@{lease_id='new-lease';owner='current-workflow'}
$transaction=[pscustomobject]@{cache_key=('A'*64);owner='cache-owner';generation_sha256=('B'*64);inventory_sha256=('C'*64);
 files=@([pscustomobject]@{name='bank.pa#';sha256=('D'*64)});
 member_recovery=[pscustomobject]@{files=@([pscustomobject]@{name='bank.pa#';sha256=('E'*64)})}}
function Write-RunJson {param($Path,$Depth,$Value) $script:request=$Value}
Invoke-Expression $block.Extent.Text
if($request.sealed_sha256-ne('D'*64)-or$request.retained_sha256-ne('E'*64)-or$request.capacity_lease_id-ne'new-lease'){throw 'Wrong proof or workflow lease'}
$transaction|Add-Member -NotePropertyName publication_metadata_correction -NotePropertyValue ([pscustomobject]@{request=$request})
$transaction.generation_sha256=('F'*64);$transaction.inventory_sha256=('F'*64);$transaction.files[0].sha256=('E'*64)
$capacitySession.lease_id='retry-lease'
Invoke-Expression $block.Extent.Text
if($request.generation_sha256-ne('B'*64)-or$request.inventory_sha256-ne('C'*64)-or$request.sealed_sha256-ne('D'*64)-or$request.capacity_lease_id-ne'retry-lease'){throw 'Retry changed original correction identity or retained stale lease'}
$CorrectPublishedInventoryMember='other.pa'
try{Invoke-Expression $block.Extent.Text;throw 'Wrong member accepted'}catch{if($_.Exception.Message-notlike'*different member*'){throw}}
Write-Output 'CORRECTION_REQUEST=PASS'
'''
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'fixture.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture),
                 str(PROJECT / 'simion/run_native_corridor_response_bank.ps1'), temporary],
                cwd=PROJECT, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CORRECTION_REQUEST=PASS', result.stdout)

    def test_frozen_transaction_continuation_rejects_builder_and_verified_changes(self) -> None:
        source = (PROJECT / 'simion/run_native_corridor_response_bank.ps1').read_text(encoding='utf-8-sig')
        function = source.split('function Select-FrozenTransactionIdentity {', 1)[1].split('\nfunction ', 1)[0]
        current = {'builder_identity': {'response_set_contract_sha256': 'B' * 64, 'producer': 'same'}, 'mesh': [0.25]}
        frozen = json.loads(json.dumps(current))
        frozen['builder_identity']['response_set_contract_sha256'] = 'A' * 64
        transaction = {'status': 'building', 'verification': None, 'generation_sha256': None, 'identity': frozen}
        script = 'function Select-FrozenTransactionIdentity {' + function + '\n'
        script += "$ErrorActionPreference='Stop'\n"
        script += "$current='" + json.dumps(current) + "'|ConvertFrom-Json\n"
        script += "$transaction='" + json.dumps(transaction) + "'|ConvertFrom-Json\n"
        script += """
$selected=Select-FrozenTransactionIdentity -CurrentIdentity $current -Transaction $transaction
if($selected.builder_identity.response_set_contract_sha256 -ne ('A'*64)){throw 'Frozen identity lost'}
$transaction.identity.mesh=@(0.5)
$rejected=$false
try { Select-FrozenTransactionIdentity -CurrentIdentity $current -Transaction $transaction } catch {$rejected=$true}
if(-not$rejected){throw 'Mesh change accepted'}
$transaction.identity.mesh=@(0.25)
$transaction.verification=@{status='pass'}
$rejected=$false
try { Select-FrozenTransactionIdentity -CurrentIdentity $current -Transaction $transaction } catch {$rejected=$true}
if(-not$rejected){throw 'Verified transaction accepted'}
$transaction.status='published';$transaction.generation_sha256=('C'*64)
$selected=Select-FrozenTransactionIdentity -CurrentIdentity $current -Transaction $transaction -AllowPublishedReuse
if($selected.builder_identity.response_set_contract_sha256 -ne ('A'*64)){throw 'Published identity mutated'}
$transaction.identity.mesh=@(0.5)
$rejected=$false
try { Select-FrozenTransactionIdentity -CurrentIdentity $current -Transaction $transaction -AllowPublishedReuse } catch {$rejected=$true}
if(-not$rejected){throw 'Published reuse accepted different physics'}
Write-Output 'CONTINUATION_FIXTURE=PASS'
"""
        result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script], cwd=PROJECT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CONTINUATION_FIXTURE=PASS', result.stdout)

    def test_bank_payload_is_exactly_raw_native_and_detached_response_set(self) -> None:
        names = response_bank_filenames()
        self.assertEqual(len(names), 18)
        self.assertEqual(names[0], RAW_NAME)
        self.assertEqual(names[1:9], NATIVE_RESPONSE_NAMES)
        self.assertEqual(names[9:17], STANDALONE_RESPONSE_NAMES)
        self.assertEqual(names[-1], RECEIPT_NAME)
        self.assertNotIn("mrtof_analyzer_corridor.pa0", names)

    def test_runner_recipe_is_current_and_declares_native_sources_in_payload(self) -> None:
        script = r'''
param($Source,$RepoRoot,$Output)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$commands=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName()-eq'Write-RunJson' -and $n.Extent.Text.Contains('-Path $responseReceiptPath')},$true))
if($commands.Count-ne1){throw 'Expected one actual response recipe writer'}
$responseReceiptPath=$Output
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path -Encoding utf8}
Invoke-Expression $commands[0].Extent.Text
'''
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / 'fixture.ps1'
            fixture.write_text(script, encoding='utf-8')
            output = root / 'recipe.json'
            result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(fixture),
                str(PROJECT / 'simion/run_native_corridor_response_bank.ps1'), str(PROJECT.parents[1]), str(output)],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            recipe = json.loads(output.read_text(encoding='utf-8-sig'))
            names = response_bank_filenames()
            for export in recipe['exports']:
                self.assertIn(export['source_name'], names)
                self.assertIn(export['standalone_name'], names)
            fixture_identity = {
                'geometry': {'fixture': True}, 'gem': {'sha256': 'A' * 64},
                'basis_namespace': {'ids': list(range(1, 9))}, 'mesh': [1, 1, 1],
                'grid_phase': [0, 0, 0], 'surface': 'none',
                'simion_identity': {'release': 'fixture'}, 'refine_policy': {'fixture': True},
                'builder_identity': {'sha256': 'B' * 64},
            }
            state = advance_pa_family_cache_transaction(root / 'cache', fixture_identity, names,
                owner='software-fixture', response_receipt=recipe)
            self.assertEqual(state.action_required, 'build')
            self.assertEqual(recipe['schema_version'], 2)
            self.assertEqual(recipe['source_location'], 'payload')
            old_recipe = dict(recipe, schema_version=1)
            del old_recipe['source_location']
            with self.assertRaisesRegex(PAFamilyCacheError, 'require schema_version 2'):
                advance_pa_family_cache_transaction(root / 'other-cache', fixture_identity, names,
                    owner='software-fixture', response_receipt=old_recipe)

    def test_runner_preserves_registered_v1_recipe_during_explicit_continuation(self) -> None:
        script = r'''
param($Source,$RepoRoot,$CacheRoot,$Key,$Root,$Recover)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$transactionCacheKey=$Key;$resultDir=$Root;$continuationOutputs=@();$correctPublication=$false
$probe=[pscustomobject]@{cache_key=$Key;disposition='miss'}
$transaction=Get-Content -LiteralPath (Join-Path $CacheRoot ".transactions/$Key/transaction.json") -Raw|ConvertFrom-Json -Depth 60
$RecoverMembers=if($Recover-eq'yes'){@('mrtof_analyzer_corridor.response8.pa')}else{@()}
$sourceText=Get-Content -LiteralPath $Source -Raw
$start=$sourceText.IndexOf("`$responseReceiptPath=''")
$end=$sourceText.IndexOf('  # A resumed transaction already occupies', $start)
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path -Encoding utf8}
Invoke-Expression $sourceText.Substring($start,$end-$start)
if($responseReceiptPath){throw 'Registered recipe was replaced by a new recipe'}
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$fallback=$ast.Find({param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.Contains("'--write-receipt-directory',`$build") -and $n.Extent.Text.StartsWith('if(-not$responseReceiptPath')},$true)
if($null-eq$fallback){throw 'Missing existing receipt dispatch'}
$build='unused';$bankModule='unused';$script:fallbackCalls=0
function Invoke-ProjectPython {param($Arguments) $script:fallbackCalls++}
Invoke-Expression $fallback.Extent.Text
if($fallbackCalls){throw 'Registered receipt was written outside the public owner'}
'''
        names = response_bank_filenames()
        fixture_identity = {
            'geometry': {'fixture': True}, 'gem': {'sha256': 'A' * 64},
            'basis_namespace': {'ids': list(range(1, 9))}, 'mesh': [1, 1, 1],
            'grid_phase': [0, 0, 0], 'surface': 'none',
            'simion_identity': {'release': 'fixture'}, 'refine_policy': {'fixture': True},
            'builder_identity': {'sha256': 'B' * 64},
        }
        for recover in ('no', 'yes'):
            with self.subTest(explicit_member_recovery=recover), TemporaryDirectory() as temporary:
                root = Path(temporary)
                cache = root / 'cache'
                exporter = root / 'export.lua'
                exporter.write_text('-- fixture')
                recipe = {'schema_version': 2, 'source_location': 'payload', 'receipt_name': RECEIPT_NAME,
                    'exporter_path': str(exporter), 'exports': [dict(response_id=i,
                        source_name=NATIVE_RESPONSE_NAMES[i-1], standalone_name=STANDALONE_RESPONSE_NAMES[i-1])
                        for i in range(1, 9)]}
                state = advance_pa_family_cache_transaction(cache, fixture_identity, names,
                    owner='original-owner', response_receipt=recipe)
                transaction_path = state.transaction_directory / 'transaction.json'
                document = json.loads(transaction_path.read_text())
                legacy = dict(recipe, schema_version=1)
                del legacy['source_location']
                document['response_receipt'] = legacy
                transaction_path.write_text(json.dumps(document), encoding='utf-8')
                before = transaction_path.read_bytes()
                fixture = root / 'fixture.ps1'
                fixture.write_text(script, encoding='utf-8')
                result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(fixture),
                    str(PROJECT / 'simion/run_native_corridor_response_bank.ps1'), str(PROJECT.parents[1]),
                    str(cache), state.cache_key, str(root), recover],
                    cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(transaction_path.read_bytes(), before)
                for name in state.missing_files:
                    (state.build_directory / name).write_bytes(name.encode())
                sealed = advance_pa_family_cache_transaction(cache, fixture_identity, names, owner='original-owner')
                self.assertEqual(sealed.action_required, 'verify')
                self.assertEqual(json.loads((state.build_directory / RECEIPT_NAME).read_text())['schema_version'], 2)
                self.assertEqual(json.loads(transaction_path.read_text())['response_receipt'], legacy)

    def test_cache_identity_excludes_run_specific_freeze_manifest_hash(self) -> None:
        source = (PROJECT / 'analysis/native_corridor_response_bank.py').read_text(encoding='utf-8-sig')
        self.assertIn('for name in FROZEN_NAMES[:3]', source)
        self.assertNotIn('for name in FROZEN_NAMES\n', source)

    def test_private_receipt_selects_only_detached_runtime_inputs(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (RAW_NAME, *NATIVE_RESPONSE_NAMES, *STANDALONE_RESPONSE_NAMES):
                (root / name).write_bytes(("fixture-" + name).encode("ascii"))
            receipt = write_response_bank_receipt(root)
            self.assertEqual(receipt["schema_version"], 2)
            self.assertEqual(len(receipt["responses"]), 8)
            result = verify_response_bank_staging(root)
        self.assertEqual(result, {
            "role": "mrtof_native_corridor_response_bank_staging",
            "status": "pass",
            "responses": 8,
        })

    def test_runner_exports_before_receipt_and_never_materializes_published_family(self) -> None:
        source = (PROJECT / "simion" / "run_native_corridor_response_bank.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("-InternalResponseId $ResponseId", source)
        self.assertIn("native_corridor_response_{0:D2}.log", source)
        self.assertIn("Tee-Object -FilePath $responseLog", source)
        self.assertNotIn("nativeCorridorDispatchArtifacts", source)
        self.assertIn("Current corridor compiler output differs from the frozen native geometry identity", source)
        self.assertIn("export_standalone_pa.lua", source)
        self.assertIn("--write-receipt-directory", source)
        self.assertLess(source.index("export_standalone_pa.lua"), source.index("--write-receipt-directory"))
        self.assertIn("detached_standalone_responses_only", source)
        self.assertLess(source.index("$retention=Apply-RunArtifactRetention"), source.index("Write-VerifiedRunManifest"))
        self.assertNotIn("materialize_pa_family_cache", source)
        self.assertNotIn("mrtof_analyzer_corridor.pa0", source)
        self.assertNotIn("run_analyzer_local_pa_family", source)

    def test_runner_republishes_frozen_inputs_inside_its_pre_registered_run(self) -> None:
        source = (PROJECT / "simion" / "run_native_corridor_response_bank.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function New-ManagedFrozenInputs", source)
        self.assertIn("--output-directory',$destination,'--run-config',[string]$Package.run_config", source)
        self.assertIn("$managedFrozen=New-ManagedFrozenInputs -Package $package", source)
        self.assertLess(source.index("$package=New-RunPackage"), source.index("$managedFrozen=New-ManagedFrozenInputs"))
        self.assertIn("native_corridor_freeze_manifest=$freezeManifest", source)
        self.assertIn("coarse_raw_generation_manifest=$directCoarseManifest", source)
        self.assertIn("Provide exactly one frozen input directory or coarse raw generation manifest", source)
        self.assertIn("+$frozenOutputs+$continuationOutputs", source)
        self.assertNotIn("--source-generation-manifest", source)
        self.assertIn("-InternalCoarseBasisDirectory $CoarseBasisDirectory", source)
        self.assertIn("$coarseBasisDirectory=[string]$coarseBank.directory", source)
        self.assertIn("Ensure-CoarseBasisBank", source)
        self.assertIn("native_corridor_coarse_basis_bank", source)

    def test_private_verifier_requires_eight_native_and_detached_pairs(self) -> None:
        source = (PROJECT / "simion" / "verify_native_corridor_response_bank.lua").read_text(encoding="utf-8-sig")
        self.assertIn("eight native/detached response pairs are required", source)
        self.assertIn("detached response node differs", source)
        self.assertIn("detached_runtime_only=true", source)
        self.assertNotIn("current_generation", source)


if __name__ == "__main__":
    unittest.main()
