from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid


HELPER = Path(__file__).with_name("short_pa_path_support.ps1")


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell test")
class ShortPaPathSupportTest(unittest.TestCase):
    def test_immutable_source_guard_blocks_write_delete_and_replace_until_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pa"
            replacement = root / "replacement.pa"
            payload = b"immutable-source"
            source.write_bytes(payload)
            replacement.write_bytes(b"replacement")
            script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
Protect-ImmutablePaSource -Source $env:PA_SOURCE -ExpectedBytes ([int64]$env:PA_BYTES) `
  -ExpectedSha256 $env:PA_SHA|Out-Null
$writeBlocked=$false;$deleteBlocked=$false;$replaceBlocked=$false
try{$writer=[IO.File]::Open($env:PA_SOURCE,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite);$writer.Dispose()}
catch [IO.IOException]{$writeBlocked=$true}catch [UnauthorizedAccessException]{$writeBlocked=$true}
try{[IO.File]::Delete($env:PA_SOURCE)}catch [IO.IOException]{$deleteBlocked=$true}catch [UnauthorizedAccessException]{$deleteBlocked=$true}
try{[IO.File]::Move($env:PA_REPLACEMENT,$env:PA_SOURCE,$true)}
catch [IO.IOException]{$replaceBlocked=$true}catch [UnauthorizedAccessException]{$replaceBlocked=$true}
Unprotect-ImmutablePaSource -Source $env:PA_SOURCE|Out-Null
[IO.File]::WriteAllText($env:PA_SOURCE,'released')
[pscustomobject]@{write_blocked=$writeBlocked;delete_blocked=$deleteBlocked;replace_blocked=$replaceBlocked;after_release=[IO.File]::ReadAllText($env:PA_SOURCE)}|ConvertTo-Json -Compress
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_REPLACEMENT": str(replacement), "PA_BYTES": str(len(payload)),
                     "PA_SHA": hashlib.sha256(payload).hexdigest()}, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["write_blocked"])
            self.assertTrue(result["delete_blocked"])
            self.assertTrue(result["replace_blocked"])
            self.assertEqual(result["after_release"], "released")

    def test_immutable_source_guard_is_process_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pa"
            payload = b"idempotent-source"
            source.write_bytes(payload)
            script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$first=Protect-ImmutablePaSource -Source $env:PA_SOURCE -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 $env:PA_SHA
$second=Protect-ImmutablePaSource -Source $env:PA_SOURCE -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 $env:PA_SHA
$count=$global:MassSpectrometryImmutablePaSourceGuards.Count
Unprotect-ImmutablePaSource -Source $env:PA_SOURCE|Out-Null
[pscustomobject]@{first_existing=$first.already_protected;second_existing=$second.already_protected;count=$count;remaining=$global:MassSpectrometryImmutablePaSourceGuards.Count}|ConvertTo-Json -Compress
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_BYTES": str(len(payload)), "PA_SHA": hashlib.sha256(payload).hexdigest()},
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertFalse(result["first_existing"])
            self.assertTrue(result["second_existing"])
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["remaining"], 0)

    def test_immutable_source_guard_rejects_wrong_hash_without_leaking_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pa"
            payload = b"wrong-hash-source"
            source.write_bytes(payload)
            script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$global:MassSpectrometryShortPaUnbufferedThresholdBytes=1
$failed=$false
try{Protect-ImmutablePaSource -Source $env:PA_SOURCE -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 ('0'*64)|Out-Null}catch{$failed=$true}
[IO.File]::WriteAllText($env:PA_SOURCE,'writable-after-failure')
[pscustomobject]@{failed=$failed;remaining=$global:MassSpectrometryImmutablePaSourceGuards.Count;value=[IO.File]::ReadAllText($env:PA_SOURCE)}|ConvertTo-Json -Compress
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_BYTES": str(len(payload))}, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["failed"])
            self.assertEqual(result["remaining"], 0)
            self.assertEqual(result["value"], "writable-after-failure")

    def test_immutable_source_guard_hashes_unbuffered_without_probe_or_pa_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pa"
            payload = b"manifest-view-from-unbuffered-direct-read"
            source.write_bytes(payload)
            script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$global:MassSpectrometryShortPaUnbufferedThresholdBytes=1
function Get-OpenPaStreamSha256 {param([IO.FileStream]$Stream);throw 'buffered source hash must not be used'}
function Copy-StandalonePaBytes {throw 'verification must not copy a PA or create a probe'}
$probeCountBefore=@(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory -Filter 'immutable_pa_source_probe_*').Count
$identity=Protect-ImmutablePaSource -Source $env:PA_SOURCE -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 $env:PA_SHA
$probeCountAfter=@(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory -Filter 'immutable_pa_source_probe_*').Count
Unprotect-ImmutablePaSource -Source $env:PA_SOURCE|Out-Null
[pscustomobject]@{sha=$identity.sha256;probe_delta=$probeCountAfter-$probeCountBefore;remaining=$global:MassSpectrometryImmutablePaSourceGuards.Count}|ConvertTo-Json -Compress
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_BYTES": str(len(payload)), "PA_SHA": hashlib.sha256(payload).hexdigest()},
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["sha"].lower(), hashlib.sha256(payload).hexdigest())
            self.assertEqual(result["probe_delta"], 0)
            self.assertEqual(result["remaining"], 0)

    def test_unbuffered_verification_failure_does_not_copy_or_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pa"
            source.write_bytes(b"locked source")
            script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$global:MassSpectrometryShortPaUnbufferedThresholdBytes=1
function Get-OpenPaStreamSha256 {throw 'buffered fallback forbidden'}
function Copy-StandalonePaBytes {throw 'PA probe forbidden'}
$before=(Get-Location).Path
$stream=[IO.File]::Open($env:PA_SOURCE,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
$failed=$false
try{
  try{Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length $stream.Length|Out-Null}
  catch{$failed=$true;if($_.Exception.Message-notlike'*Unbuffered immutable PA source verification failed*'){throw}}
  if(-not$stream.CanRead){throw 'Caller-owned source guard was closed'}
}finally{$stream.Dispose()}
if((Get-Location).Path-ne$before){throw 'Verification leaked the working directory'}
[IO.File]::WriteAllText($env:PA_SOURCE,'released')
[pscustomobject]@{failed=$failed;released=[IO.File]::ReadAllText($env:PA_SOURCE)}|ConvertTo-Json -Compress
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source)}, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["failed"])
            self.assertEqual(result["released"], "released")

    def test_short_copy_with_large_manifest_identity_verifies_locked_source_hash(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_manifest_unbuffered_copy_"))
        source = root / "source.pa"
        payload = b"manifest-backed-private-copy"
        source.write_bytes(payload)
        copy_dir = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        destination = copy_dir / "copy.pa"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$global:MassSpectrometryShortPaUnbufferedThresholdBytes=1
$script:realHashCommand=${function:Get-OpenPaStreamSha256}
$script:sourceHashCalls=0
function Get-OpenPaStreamSha256 {
  param([IO.FileStream]$Stream)
  $script:sourceHashCalls++
  & $script:realHashCommand -Stream $Stream
}
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 $env:PA_SHA
$actual=(Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash
Remove-ShortPaCopyDirectory -Path $env:PA_COPY_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
[pscustomobject]@{sha=$actual;source_hash_calls=$script:sourceHashCalls;removed=-not(Test-Path -LiteralPath $env:PA_COPY_DIR)}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_DESTINATION": str(destination), "PA_COPY_DIR": str(copy_dir),
                     "PA_BYTES": str(len(payload)), "PA_SHA": hashlib.sha256(payload).hexdigest()},
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["sha"].lower(), hashlib.sha256(payload).hexdigest())
            self.assertEqual(result["source_hash_calls"], 0)
            self.assertTrue(result["removed"])
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if copy_dir.exists():
                shutil.rmtree(copy_dir, ignore_errors=False)

    def test_published_cache_source_requires_complete_manifest_identity(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_published_cache_source_"))
        generation = root / "generation"
        generation.mkdir()
        source = generation / "response.pa"
        payload = b"published-cache-response"
        source.write_bytes(payload)
        (generation / "cache_manifest.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "name": source.name,
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest().upper(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        copy_dir = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        destination = copy_dir / "response.bin"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$rejected=$false
try{New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION|Out-Null}catch{$rejected=$true}
if(-not$rejected){throw 'published cache source without manifest identity was accepted'}
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 $env:PA_SHA
Remove-ShortPaCopyDirectory -Path $env:PA_COPY_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
[pscustomobject]@{rejected=$rejected;removed=-not(Test-Path -LiteralPath $env:PA_COPY_DIR)}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_DESTINATION": str(destination), "PA_COPY_DIR": str(copy_dir),
                     "PA_BYTES": str(len(payload)), "PA_SHA": hashlib.sha256(payload).hexdigest()},
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["rejected"])
            self.assertTrue(result["removed"])
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if copy_dir.exists():
                shutil.rmtree(copy_dir, ignore_errors=False)

    def test_immutable_source_guards_release_by_directory_and_all(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            sources = [first_dir / "a.pa", first_dir / "b.pa", second_dir / "c.pa"]
            for index, source in enumerate(sources):
                source.write_bytes(f"source-{index}".encode())
            identities = [{"path": str(source), "bytes": source.stat().st_size,
                           "sha": hashlib.sha256(source.read_bytes()).hexdigest()} for source in sources]
            script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$items=Get-Content -Raw $env:PA_IDENTITIES|ConvertFrom-Json
foreach($item in $items){Protect-ImmutablePaSource -Source $item.path -ExpectedBytes ([int64]$item.bytes) -ExpectedSha256 $item.sha|Out-Null}
$directoryCount=Unprotect-ImmutablePaSourcesUnderDirectory -Path $env:PA_FIRST_DIR
$afterDirectory=$global:MassSpectrometryImmutablePaSourceGuards.Count
$allCount=Unprotect-AllImmutablePaSources
foreach($item in $items){[IO.File]::Open($item.path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None).Dispose()}
[pscustomobject]@{directory_count=$directoryCount;after_directory=$afterDirectory;all_count=$allCount;remaining=$global:MassSpectrometryImmutablePaSourceGuards.Count}|ConvertTo-Json -Compress
"""
            identity_path = root / "identities.json"
            identity_path.write_text(json.dumps(identities), encoding="utf-8")
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_IDENTITIES": str(identity_path),
                     "PA_FIRST_DIR": str(first_dir)}, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["directory_count"], 2)
            self.assertEqual(result["after_directory"], 1)
            self.assertEqual(result["all_count"], 1)
            self.assertEqual(result["remaining"], 0)

    def test_existing_read_only_copy_can_be_verified_and_registered_in_new_process(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_imported_short_pa_"))
        source = root / "source.pa"
        destination = root / "shared.pa"
        payload = b"cross-process-verified-pa"
        source.write_bytes(payload)
        destination.write_bytes(payload)
        destination.chmod(stat.S_IREAD)
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$identity=Import-ExistingShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_EXPECTED_BYTES) -ExpectedSha256 $env:PA_EXPECTED_SHA256
$writeBlocked=$false
try{
  $writer=[IO.File]::Open($env:PA_DESTINATION,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
  $writer.Dispose()
}catch [IO.IOException]{$writeBlocked=$true}
catch [UnauthorizedAccessException]{$writeBlocked=$true}
Remove-ShortPaCopy -Path $env:PA_DESTINATION
[pscustomobject]@{bytes=$identity.bytes;sha256=$identity.sha256;write_blocked=$writeBlocked;removed=-not(Test-Path -LiteralPath $env:PA_DESTINATION)}|ConvertTo-Json -Compress
"""
        expected = hashlib.sha256(payload).hexdigest()
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8",
                errors="replace", env={
                    **os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                    "PA_EXPECTED_BYTES": str(len(payload)), "PA_EXPECTED_SHA256": expected,
                }, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["bytes"], len(payload))
            self.assertEqual(result["sha256"].lower(), expected)
            self.assertTrue(result["write_blocked"])
            self.assertTrue(result["removed"])
        finally:
            destination.chmod(stat.S_IWRITE | stat.S_IREAD) if destination.exists() else None
            shutil.rmtree(root, ignore_errors=False)

    def test_seed_placeholder_cleanup_is_exact_and_retains_seed_iob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "8_instance_seed.iob").write_bytes(b"seed")
            for index in range(1, 4):
                (root / f"iob_seed_placeholder_{index:02d}.pa0").write_bytes(
                    bytes([index]) * index
                )
            unrelated = root / "iob_input_analyzer.pa"
            unrelated.write_bytes(b"operating")
            script = r"""
. $env:PA_HELPER
$result=Remove-IobSeedPlaceholderCompanions -Directory $env:PA_DIRECTORY -Count 3
$result|ConvertTo-Json -Compress
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent,
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_DIRECTORY": str(root)},
                timeout=30,
            )
            result = json.loads(completed.stdout.strip())
            self.assertEqual(result["removed_count"], 3)
            self.assertEqual(result["removed_bytes"], 6)
            self.assertTrue(result["retained_seed_iob"])
            self.assertTrue((root / "8_instance_seed.iob").is_file())
            self.assertEqual(unrelated.read_bytes(), b"operating")
            self.assertFalse(any(root.glob("iob_seed_placeholder_*.pa0")))

    def test_frozen_identity_is_checked_and_individual_copy_is_unregistered(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_short_pa_identity_"))
        source = root / "source.pa"
        destination = root / "copy.pa"
        source.write_bytes(b"verified-pa-payload")
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_EXPECTED_BYTES) -ExpectedSha256 $env:PA_EXPECTED_SHA256
Remove-ShortPaCopy -Path $copy
[pscustomobject]@{
  destination_removed=-not(Test-Path -LiteralPath $copy)
  registered_count=$script:ShortPaCopies.Count
}|ConvertTo-Json -Compress
"""
        environment = os.environ.copy()
        environment.update(
            PA_HELPER=str(HELPER),
            PA_SOURCE=str(source),
            PA_DESTINATION=str(destination),
            PA_EXPECTED_BYTES=str(source.stat().st_size),
            PA_EXPECTED_SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["destination_removed"])
            self.assertEqual(result["registered_count"], 0)

            environment["PA_EXPECTED_BYTES"] = str(source.stat().st_size + 1)
            rejected = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(
                "byte length differs from its frozen identity",
                rejected.stdout + rejected.stderr,
            )
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_rejects_pa_family_response_member(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_family_member_"))
        source = root / "family.pa7"
        source.write_bytes(b"response")
        destination = root / "response.pa"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION|Out-Null
"""
        environment = os.environ.copy()
        environment.update(
            PA_HELPER=str(HELPER),
            PA_SOURCE=str(source),
            PA_DESTINATION=str(destination),
        )
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "PA-family response members cannot be projected",
                completed.stdout + completed.stderr,
            )
            self.assertFalse(destination.exists())
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_large_pa_uses_verified_unbuffered_copy(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_unbuffered_pa_"))
        source = root / "source.pa"
        destination = root / "copy.pa"
        payload = bytes(range(256)) * (9 * 1024 * 1024 // 256)
        source.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_EXPECTED_BYTES) -ExpectedSha256 $env:PA_EXPECTED_SHA256
$result=[pscustomobject]@{
  hash=(Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash
  staging_count=@(Get-ChildItem -LiteralPath (Split-Path -Parent $copy) -Directory -Filter '.pa_copy_*').Count
}
Remove-ShortPaCopy -Path $copy
$result|ConvertTo-Json -Compress
"""
        environment = os.environ.copy()
        environment.update(
            PA_HELPER=str(HELPER), PA_SOURCE=str(source),
            PA_DESTINATION=str(destination), PA_EXPECTED_BYTES=str(len(payload)),
            PA_EXPECTED_SHA256=expected,
        )
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=environment, timeout=60,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["hash"].lower(), expected)
            self.assertEqual(result["staging_count"], 0)
            self.assertFalse(destination.exists())
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_manifest_backed_large_source_is_hashed_before_copy(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_manifest_source_hash_"))
        generation = root / "generation"
        generation.mkdir()
        source = generation / "response.pa"
        destination = root / "copy.pa"
        source.write_bytes(b"originaL-source-bytes")
        expected_payload = b"original-source-bytes"
        (generation / "cache_manifest.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "name": source.name,
                            "bytes": len(expected_payload),
                            "sha256": hashlib.sha256(expected_payload).hexdigest().upper(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$global:MassSpectrometryShortPaUnbufferedThresholdBytes=1
. $env:PA_HELPER
New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_EXPECTED_BYTES) -ExpectedSha256 $env:PA_EXPECTED_SHA256|Out-Null
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={
                    **os.environ,
                    "PA_HELPER": str(HELPER),
                    "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                    "PA_EXPECTED_BYTES": str(len(source.read_bytes())),
                    "PA_EXPECTED_SHA256": hashlib.sha256(expected_payload).hexdigest(),
                },
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "Locked immutable PA source differs from its manifest",
                completed.stdout + completed.stderr,
            )
            self.assertFalse(destination.exists())
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_source_is_write_locked_for_disposable_copy_lifetime(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_source_guard_"))
        source = root / "source.pa"
        destination = root / "copy.pa"
        source.write_bytes(b"immutable-source")
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION
$write_blocked=$false
try {
  $writer=[IO.File]::Open($env:PA_SOURCE,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
  $writer.Dispose()
} catch [IO.IOException] {$write_blocked=$true}
catch [UnauthorizedAccessException] {$write_blocked=$true}
Remove-ShortPaCopy -Path $copy
$writer=[IO.File]::Open($env:PA_SOURCE,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
$writer.Dispose()
[pscustomobject]@{
  write_blocked_while_registered=$write_blocked
  destination_removed=-not(Test-Path -LiteralPath $copy)
}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={
                    **os.environ,
                    "PA_HELPER": str(HELPER),
                    "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                },
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["write_blocked_while_registered"])
            self.assertTrue(result["destination_removed"])
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_multiple_copies_share_one_source_guard_until_last_removal(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_shared_source_guard_"))
        source = root / "source.pa"
        first = root / "copy_1.pa"
        second = root / "copy_2.pa"
        source.write_bytes(b"shared-immutable-source")
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$first=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_FIRST
$second=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_SECOND
$one_guard=($script:ShortPaSourceGuards.Count-eq1)
$two_references=([int]@($script:ShortPaSourceGuards.Values)[0].reference_count-eq2)
Remove-ShortPaCopy -Path $first
$write_still_blocked=$false
try {
  $writer=[IO.File]::Open($env:PA_SOURCE,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
  $writer.Dispose()
} catch [IO.IOException] {$write_still_blocked=$true}
Remove-ShortPaCopy -Path $second
$writer=[IO.File]::Open($env:PA_SOURCE,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
$writer.Dispose()
[pscustomobject]@{
  one_guard=$one_guard
  two_references=$two_references
  write_still_blocked=$write_still_blocked
  guards_after=$script:ShortPaSourceGuards.Count
  copies_after=$script:ShortPaCopies.Count
}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={
                    **os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                    "PA_FIRST": str(first), "PA_SECOND": str(second),
                }, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["one_guard"])
            self.assertTrue(result["two_references"])
            self.assertTrue(result["write_still_blocked"])
            self.assertEqual(result["guards_after"], 0)
            self.assertEqual(result["copies_after"], 0)
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_cleanup_releases_guard_without_rehashing_source(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_transient_hash_"))
        source = root / "source.pa"
        destination = root / "copy.pa"
        source.write_bytes(b"immutable-source-with-transient-read")
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION
$script:realHashCommand=${function:Get-OpenPaStreamSha256}
$script:hashCalls=0
function Get-OpenPaStreamSha256 {
  param([Parameter(Mandatory)][IO.FileStream]$Stream)
  $script:hashCalls++
  & $script:realHashCommand -Stream $Stream
}
Remove-ShortPaCopy -Path $copy
[pscustomobject]@{
  hash_calls=$script:hashCalls
  destination_removed=-not(Test-Path -LiteralPath $copy)
  source_sha256=(Get-FileHash -LiteralPath $env:PA_SOURCE -Algorithm SHA256).Hash
}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8",
                errors="replace", env={
                    **os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                }, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["hash_calls"], 0)
            self.assertTrue(result["destination_removed"])
            self.assertEqual(
                result["source_sha256"].lower(),
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_destination_write_guard_proves_copy_immutable_without_rehash(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_destination_guard_"))
        source = root / "source.pa"
        destination = root / "copy.pa"
        source.write_bytes(b"guarded-private-pa")
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION -GuardDestinationReadOnly
$identity=Get-ShortPaCopyIdentity -Path $copy
$write_blocked=$false
try {
  $writer=[IO.File]::Open($copy,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
  $writer.Dispose()
} catch [IO.IOException] {$write_blocked=$true}
catch [UnauthorizedAccessException] {$write_blocked=$true}
Remove-ShortPaCopy -Path $copy
[pscustomobject]@{
  write_guarded=$identity.destination_write_guarded
  identity_bytes=$identity.bytes
  identity_sha256=$identity.sha256
  write_blocked=$write_blocked
  destination_removed=-not(Test-Path -LiteralPath $copy)
}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={
                    **os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                }, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["write_guarded"])
            self.assertTrue(result["write_blocked"])
            self.assertTrue(result["destination_removed"])
            self.assertEqual(result["identity_bytes"], len(b"guarded-private-pa"))
            self.assertEqual(
                result["identity_sha256"].lower(),
                hashlib.sha256(b"guarded-private-pa").hexdigest(),
            )
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_guarded_private_copy_is_readable_by_independent_python_hasher(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_cross_process_read_"))
        source = root / "source.pa"
        destination = root / "copy.pa"
        payload = (b"guarded-cross-process-pa" * 4096) + b"end"
        source.write_bytes(payload)
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION `
  -ExpectedBytes ([int64]$env:PA_BYTES) -ExpectedSha256 $env:PA_SHA -GuardDestinationReadOnly
$observed=& $env:PYTHON -c 'import sys; from common.contracts.file_identity import file_sha256; print(file_sha256(sys.argv[1]))' $copy
if($LASTEXITCODE-ne0){throw 'Independent Python hash failed.'}
Remove-ShortPaCopy -Path $copy
[pscustomobject]@{observed_sha256=($observed|Select-Object -Last 1);removed=-not(Test-Path -LiteralPath $copy)}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parents[2], check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={
                    **os.environ,
                    "PA_HELPER": str(HELPER),
                    "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                    "PA_BYTES": str(len(payload)),
                    "PA_SHA": hashlib.sha256(payload).hexdigest(),
                    "PYTHON": sys.executable,
                    "PYTHONPATH": str(HELPER.parents[2]),
                },
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(
                result["observed_sha256"], hashlib.sha256(payload).hexdigest().upper()
            )
            self.assertTrue(result["removed"])
        finally:
            shutil.rmtree(root, ignore_errors=False)

    def test_read_only_copy_directory_can_move_before_write_guard(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_pa_read_only_move_"))
        source = root / "source.pa"
        source.write_bytes(b"portable-read-only-pa")
        bundle = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        moved = Path(str(bundle) + "_hidden")
        bundle.mkdir()
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination (Join-Path $env:BUNDLE 'copy.pa') -MarkDestinationReadOnly
$before=Get-ShortPaCopyIdentity -Path $copy
Move-Item -LiteralPath $env:BUNDLE -Destination $env:MOVED
Move-Item -LiteralPath $env:MOVED -Destination $env:BUNDLE
$protected=Protect-ShortPaCopyDestination -Path $copy
Remove-ShortPaCopyDirectory -Path $env:BUNDLE -ExpectedNamePrefix 'simion_pa_links_test_'
[pscustomobject]@{
  read_only_before=$before.destination_read_only
  guarded_after=$protected.destination_write_guarded
  directory_removed=-not(Test-Path -LiteralPath $env:BUNDLE)
}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8",
                errors="replace", env={
                    **os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                    "BUNDLE": str(bundle), "MOVED": str(moved),
                }, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["read_only_before"])
            self.assertTrue(result["guarded_after"])
            self.assertTrue(result["directory_removed"])
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if bundle.exists():
                shutil.rmtree(bundle, ignore_errors=False)
            if moved.exists():
                shutil.rmtree(moved, ignore_errors=False)

    def test_projects_long_read_only_pa_as_isolated_copy_and_removes_it(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_long_pa_source_"))
        source = root
        while len(str(source / "source.pa0")) <= 270:
            source /= "long_cache_generation_component_0123456789"
        source.mkdir(parents=True)
        source_pa = source / "source.pa0"
        source_pa.write_bytes(b"verified-pa-payload")
        source_pa.chmod(stat.S_IREAD)
        link_dir = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$before=[IO.File]::GetAttributes($env:PA_SOURCE)
New-Item -ItemType Directory -Path $env:PA_LINK_DIR|Out-Null
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination (Join-Path $env:PA_LINK_DIR 'p.pa') -VerificationAttempts 3
[IO.File]::WriteAllText($copy,'simulated delayed solver write')
Remove-ShortPaCopyDirectory -Path $env:PA_LINK_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
$after=[IO.File]::GetAttributes($env:PA_SOURCE)
[pscustomobject]@{
  source_length=$env:PA_SOURCE.Length
  payload=[IO.File]::ReadAllText($env:PA_SOURCE)
  directory_removed=-not(Test-Path -LiteralPath $env:PA_LINK_DIR)
  attributes_unchanged=($before-eq$after)
}|ConvertTo-Json -Compress
"""
        environment = os.environ.copy()
        environment.update(
            PA_HELPER=str(HELPER),
            PA_SOURCE=str(source_pa),
            PA_LINK_DIR=str(link_dir),
        )
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertGreater(result["source_length"], 260)
            self.assertEqual(result["payload"], "verified-pa-payload")
            self.assertTrue(result["directory_removed"])
            self.assertTrue(result["attributes_unchanged"])
            helper_source = HELPER.read_text(encoding="utf-8")
            self.assertIn("function New-ShortPaHardLink", helper_source)
            self.assertIn("New-ShortPaCopy -Source $Source -Destination $Destination", helper_source)
            self.assertIn("function Remove-ShortPaHardLinkDirectory", helper_source)
        finally:
            if source_pa.exists():
                source_pa.chmod(stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(root, ignore_errors=False)
            if link_dir.exists():
                shutil.rmtree(link_dir, ignore_errors=False)

    def test_removes_registered_batch_pa_copies_but_retains_companions(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_batch_copy_source_"))
        source = root / "source.pa"
        source.write_bytes(b"batch-private-pa")
        batch_dir = Path(tempfile.gettempdir()) / f"batch_{uuid.uuid4().hex}"
        batch_dir.mkdir()
        companion = batch_dir / "mrtof_batch.iob"
        companion.write_text("portable companion", encoding="utf-8")
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination (Join-Path $env:BATCH_DIR 'iob_input_analyzer.pa')
Remove-ShortPaCopiesUnderDirectory -Path $env:BATCH_DIR -ExpectedNamePrefix 'batch_'
[pscustomobject]@{
  pa_removed=-not(Test-Path -LiteralPath $copy)
  companion_retained=Test-Path -LiteralPath (Join-Path $env:BATCH_DIR 'mrtof_batch.iob')
  directory_retained=Test-Path -LiteralPath $env:BATCH_DIR -PathType Container
  guards_after=$script:ShortPaSourceGuards.Count
  copies_after=$script:ShortPaCopies.Count
}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={
                    **os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                    "BATCH_DIR": str(batch_dir),
                }, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertTrue(result["pa_removed"])
            self.assertTrue(result["companion_retained"])
            self.assertTrue(result["directory_retained"])
            self.assertEqual(result["guards_after"], 0)
            self.assertEqual(result["copies_after"], 0)
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if batch_dir.exists():
                shutil.rmtree(batch_dir, ignore_errors=False)

    def test_copy_registry_survives_nested_script_scope(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_nested_scope_source_"))
        source = root / "source.pa"
        source.write_bytes(b"nested-scope-pa")
        copy_dir = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        child = root / "child.ps1"
        child.write_text(
            "Set-StrictMode -Version Latest\n"
            "$identity=Get-ShortPaCopyIdentity -Path $env:PA_DESTINATION\n"
            "if($identity.bytes -ne 15){throw 'nested identity length differs'}\n",
            encoding="utf-8",
        )
        destination = copy_dir / "copy.pa"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION|Out-Null
& $env:PA_CHILD
Remove-ShortPaCopyDirectory -Path $env:PA_COPY_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=HELPER.parent, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={
                    **os.environ,
                    "PA_HELPER": str(HELPER),
                    "PA_SOURCE": str(source),
                    "PA_DESTINATION": str(destination),
                    "PA_CHILD": str(child),
                    "PA_COPY_DIR": str(copy_dir),
                }, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(copy_dir.exists())
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if copy_dir.exists():
                shutil.rmtree(copy_dir, ignore_errors=False)

    def test_confirm_short_copy_hashes_the_registered_destination(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_confirm_copy_source_"))
        source = root / "source.pa"
        source.write_bytes(b"confirmed-private-copy")
        copy_dir = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        destination = copy_dir / "copy.bin"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION -GuardDestinationReadOnly
$identity=Confirm-ShortPaCopyIdentity -Path $copy -VerificationAttempts 3
Remove-ShortPaCopyDirectory -Path $env:PA_COPY_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
[pscustomobject]@{bytes=$identity.bytes;removed=-not(Test-Path -LiteralPath $env:PA_COPY_DIR)}|ConvertTo-Json -Compress
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_DESTINATION": str(destination), "PA_COPY_DIR": str(copy_dir)}, timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["bytes"], len(b"confirmed-private-copy"))
            self.assertTrue(result["removed"])
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if copy_dir.exists():
                shutil.rmtree(copy_dir, ignore_errors=False)

    def test_confirm_short_copy_rejects_persistent_destination_change(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="simion_confirm_changed_source_"))
        source = root / "source.pa"
        source.write_bytes(b"original-private-copy")
        copy_dir = Path(tempfile.gettempdir()) / f"simion_pa_links_test_{uuid.uuid4().hex}"
        destination = copy_dir / "copy.bin"
        script = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. $env:PA_HELPER
$copy=New-ShortPaCopy -Source $env:PA_SOURCE -Destination $env:PA_DESTINATION
[IO.File]::WriteAllText($copy,'changed-private-copy')
$failed=$false
try{Confirm-ShortPaCopyIdentity -Path $copy -VerificationAttempts 3|Out-Null}catch{$failed=$true}
Remove-ShortPaCopyDirectory -Path $env:PA_COPY_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
if(-not$failed){throw 'persistent destination change was accepted'}
"""
        try:
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script], cwd=HELPER.parent,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PA_HELPER": str(HELPER), "PA_SOURCE": str(source),
                     "PA_DESTINATION": str(destination), "PA_COPY_DIR": str(copy_dir)}, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(copy_dir.exists())
        finally:
            shutil.rmtree(root, ignore_errors=False)
            if copy_dir.exists():
                shutil.rmtree(copy_dir, ignore_errors=False)


if __name__ == "__main__":
    unittest.main()
