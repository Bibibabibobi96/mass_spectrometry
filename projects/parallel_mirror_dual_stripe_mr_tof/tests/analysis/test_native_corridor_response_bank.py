from __future__ import annotations

from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest


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

    def test_private_receipt_selects_only_detached_runtime_inputs(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (RAW_NAME, *NATIVE_RESPONSE_NAMES, *STANDALONE_RESPONSE_NAMES):
                (root / name).write_bytes(("fixture-" + name).encode("ascii"))
            write_response_bank_receipt(root)
            result = verify_response_bank_staging(root)
        self.assertEqual(result, {
            "role": "mrtof_native_corridor_response_bank_staging",
            "status": "pass",
            "responses": 8,
        })

    def test_runner_exports_before_receipt_and_never_materializes_published_family(self) -> None:
        source = (PROJECT / "simion" / "run_native_corridor_response_bank.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("-InternalResponseId $ResponseId", source)
        self.assertIn("Current corridor compiler output differs from the frozen native geometry identity", source)
        self.assertIn("export_standalone_pa.lua", source)
        self.assertIn("--write-receipt-directory", source)
        self.assertLess(source.index("export_standalone_pa.lua"), source.index("--write-receipt-directory"))
        self.assertIn("detached_standalone_responses_only", source)
        self.assertLess(source.index("$retention=Apply-RunArtifactRetention"), source.index("Write-VerifiedRunManifest"))
        self.assertNotIn("materialize_pa_family_cache", source)
        self.assertNotIn("mrtof_analyzer_corridor.pa0", source)
        self.assertNotIn("run_analyzer_local_pa_family", source)

    def test_private_verifier_requires_eight_native_and_detached_pairs(self) -> None:
        source = (PROJECT / "simion" / "verify_native_corridor_response_bank.lua").read_text(encoding="utf-8-sig")
        self.assertIn("eight native/detached response pairs are required", source)
        self.assertIn("detached response node differs", source)
        self.assertIn("detached_runtime_only=true", source)
        self.assertNotIn("current_generation", source)


if __name__ == "__main__":
    unittest.main()
