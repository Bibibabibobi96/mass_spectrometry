from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
import uuid


HELPER = Path(__file__).with_name("short_pa_path_support.ps1")


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell test")
class ShortPaPathSupportTest(unittest.TestCase):
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

    def test_large_pa_uses_verified_write_through_stream_copy(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
