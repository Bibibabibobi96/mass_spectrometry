from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_SCRIPT = REPO_ROOT / "common" / "report_cloc_delta.ps1"


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


class ClocDeltaReportTests(unittest.TestCase):
    def _initialize_repo(self, root: Path) -> None:
        (root / "src").mkdir()
        (root / "config").mkdir()
        (root / "src" / "main.py").write_text("print('base')\n", encoding="utf-8")
        (root / "src" / "test_legacy.py").write_text(
            "def test_base(): pass\n", encoding="utf-8"
        )
        (root / "config" / "settings.json").write_text("{}\n", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.name", "CLOC Test"],
            ["git", "config", "user.email", "cloc-test@example.invalid"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "baseline"],
        ):
            completed = _run(command, root)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def _write_fake_cloc(self, root: Path) -> Path:
        fake = root / ".venv" / "fake_cloc.ps1"
        fake.parent.mkdir()
        fake.write_text(
            textwrap.dedent(
                r"""
                param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
                if($Arguments -contains '--version'){
                  Write-Output '2.02-test-double'
                  exit 0
                }
                $listArgument=@($Arguments|Where-Object{$_ -like '--list-file=*'})
                if($listArgument.Count-ne 1){throw 'Expected one --list-file argument.'}
                $listPath=$listArgument[0].Substring('--list-file='.Length)
                $document=[ordered]@{header=[ordered]@{cloc_version='2.02-test-double'}}
                $languages=@{}
                foreach($path in @(Get-Content -LiteralPath $listPath -Encoding UTF8)){
                  $normalized=$path.Replace('\','/').ToLowerInvariant()
                  if($normalized-match '/(artifacts|generated|vendor|third_party|runs)/'){
                    throw "Excluded path reached cloc: $path"
                  }
                  $language=switch([IO.Path]::GetExtension($path).ToLowerInvariant()){
                    '.py' {'Python';break}
                    '.lua' {'Lua';break}
                    '.json' {'JSON';break}
                    '.ps1' {'PowerShell';break}
                    default {'Other';break}
                  }
                  if(-not$languages.ContainsKey($language)){
                    $languages[$language]=[ordered]@{nFiles=0;blank=0;comment=0;code=0}
                  }
                  $languages[$language].nFiles+=1
                  foreach($line in @(Get-Content -LiteralPath $path -Encoding UTF8)){
                    if([string]::IsNullOrWhiteSpace($line)){
                      $languages[$language].blank+=1
                    }elseif($line.TrimStart().StartsWith('#')){
                      $languages[$language].comment+=1
                    }else{
                      $languages[$language].code+=1
                    }
                  }
                }
                foreach($language in $languages.Keys){$document[$language]=$languages[$language]}
                $document|ConvertTo-Json -Depth 6
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return fake

    def test_report_classifies_tests_and_excludes_untracked_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._initialize_repo(root)
            fake_cloc = self._write_fake_cloc(root)

            (root / "src" / "main.py").write_text(
                "print('base')\nprint('current')\n", encoding="utf-8"
            )
            (root / "src" / "new.lua").write_text("return 1\n", encoding="utf-8")
            test_dir = root / "project" / "tests"
            test_dir.mkdir(parents=True)
            (test_dir / "test_api.py").write_text(
                "def test_api(): pass\n", encoding="utf-8"
            )
            (test_dir / "run_case.ps1").write_text(
                "Write-Output 'run'\n", encoding="utf-8"
            )
            (test_dir / "helper.py").write_text(
                "VALUE = 1\n", encoding="utf-8"
            )
            pure_support = test_dir / "test_support"
            pure_support.mkdir()
            (pure_support / "helper.py").write_text(
                "FIXTURE_VALUE = 1\n", encoding="utf-8"
            )
            for relative in (
                "artifacts/run/output.py",
                "generated/output.py",
                "vendor/package.py",
                "third_party/package.py",
                "runs/run_id/output.py",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("raise RuntimeError\n", encoding="utf-8")

            completed = _run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(REPORT_SCRIPT),
                    "-Base",
                    "HEAD",
                    "-Current",
                    "WORKTREE",
                    "-ClocExe",
                    str(fake_cloc),
                    "-RepoRoot",
                    str(root),
                ],
                root,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = completed.stdout
            for required in (
                "CLOC_DELTA=PASS",
                "BASELINE=",
                "RESULT=WORKTREE(head=",
                "CLOC_VERSION=2.02-test-double",
                "FILTER=extensions=",
                "CATEGORY=total",
                "CATEGORY=production",
                "CATEGORY=tests",
                "CATEGORY=unclassified",
                "REASON=active_powershell_entrypoint",
                "CLASSIFICATION_WARNING SNAPSHOT=result "
                "PATH=project/tests/helper.py",
            ):
                self.assertIn(required, output)
            self.assertRegex(
                output,
                r"(?s)CATEGORY=production.*LANGUAGE=Lua "
                r"BASE_FILES=0 RESULT_FILES=1 DELTA_FILES=1",
            )
            self.assertRegex(
                output,
                r"(?s)CATEGORY=tests.*LANGUAGE=Python "
                r"BASE_FILES=1 RESULT_FILES=3 DELTA_FILES=2",
            )
            self.assertRegex(
                output,
                r"(?s)CATEGORY=production.*LANGUAGE=PowerShell "
                r"BASE_FILES=0 RESULT_FILES=1 DELTA_FILES=1",
            )
            self.assertNotIn("Excluded path reached cloc", output)

    def test_missing_cloc_fails_without_fallback(self) -> None:
        completed = _run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(REPORT_SCRIPT),
                "-Base",
                "HEAD",
                "-ClocExe",
                "definitely_missing_cloc_for_test",
            ],
            REPO_ROOT,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("CLOC_UNAVAILABLE", completed.stderr)
        self.assertIn("no fallback counter", completed.stderr)
        self.assertIn("is permitted", completed.stderr)


if __name__ == "__main__":
    unittest.main()
