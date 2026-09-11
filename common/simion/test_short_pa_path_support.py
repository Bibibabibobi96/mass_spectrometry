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


if __name__ == "__main__":
    unittest.main()
