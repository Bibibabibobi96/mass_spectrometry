from __future__ import annotations

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
    def test_projects_long_read_only_pa_without_copying_or_leaving_links(self) -> None:
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
$link=New-ShortPaHardLink -Source $env:PA_SOURCE -Destination (Join-Path $env:PA_LINK_DIR 'p.pa')
$item=Get-Item -LiteralPath $link -Force
$linkType=$item.LinkType
Remove-ShortPaHardLinkDirectory -Path $env:PA_LINK_DIR -ExpectedNamePrefix 'simion_pa_links_test_'
$after=[IO.File]::GetAttributes($env:PA_SOURCE)
[pscustomobject]@{
  link_type=$linkType
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
                env=environment,
                timeout=30,
            )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(result["link_type"], "HardLink")
            self.assertGreater(result["source_length"], 260)
            self.assertEqual(result["payload"], "verified-pa-payload")
            self.assertTrue(result["directory_removed"])
            self.assertTrue(result["attributes_unchanged"])
        finally:
            if source_pa.exists():
                source_pa.chmod(stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(root, ignore_errors=False)
            if link_dir.exists():
                shutil.rmtree(link_dir, ignore_errors=False)


if __name__ == "__main__":
    unittest.main()
