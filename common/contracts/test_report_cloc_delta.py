from __future__ import annotations

import re
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
        errors="replace",
        timeout=60,
    )


class ClocDeltaReportTests(unittest.TestCase):
    def _initialize_repo(self, root: Path) -> None:
        (root / "src").mkdir()
        (root / "config").mkdir()
        (root / "docs" / "history" / "baseline_snapshot").mkdir(parents=True)
        (root / "scratch" / "baseline_task").mkdir(parents=True)
        (root / "projects" / "active_project").mkdir(parents=True)
        (root / "projects" / "active_project" / "archive").mkdir()
        (root / "src" / "main.py").write_text("print('base')\n", encoding="utf-8")
        (root / "src" / "test_legacy.py").write_text(
            "def test_base(): pass\n", encoding="utf-8"
        )
        (root / "config" / "settings.json").write_text("{}\n", encoding="utf-8")
        (root / "docs" / "history" / "baseline_snapshot" / "legacy.py").write_text(
            "raise RuntimeError('history is not active code')\n", encoding="utf-8"
        )
        (root / "scratch" / "baseline_task" / "temporary.m").write_text(
            "error('scratch is not active code');\n", encoding="utf-8"
        )
        (root / "projects" / "active_project" / "model.m").write_text(
            "value = 1;\n", encoding="utf-8"
        )
        (
            root
            / "projects"
            / "active_project"
            / "archive"
            / "active_authority.json"
        ).write_text('{"active": true}\n', encoding="utf-8")
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
                if($Arguments -notcontains '--by-file'){throw 'Expected --by-file.'}
                if($Arguments -notcontains '--skip-uniqueness'){
                  throw 'Expected --skip-uniqueness.'
                }
                if($Arguments -notcontains '--force-lang=MATLAB,m'){
                  throw 'Expected MATLAB language override.'
                }
                if($Arguments -notcontains '--force-lang=Lua,fly2'){
                  throw 'Expected Fly2 language override.'
                }
                $languageDefinition=@(
                  $Arguments|Where-Object{$_ -like '--read-lang-def=*'}
                )
                if($languageDefinition.Count-ne 1){
                  throw 'Expected one --read-lang-def argument.'
                }
                $definitionPath=$languageDefinition[0].Substring(
                  '--read-lang-def='.Length
                )
                if(-not(Test-Path -LiteralPath $definitionPath -PathType Leaf)){
                  throw 'CLOC language definition does not exist.'
                }
                $listArgument=@($Arguments|Where-Object{$_ -like '--list-file=*'})
                if($listArgument.Count-ne 1){throw 'Expected one --list-file argument.'}
                $listPath=$listArgument[0].Substring('--list-file='.Length)
                Add-Content -LiteralPath (Join-Path $PSScriptRoot 'calls.log') `
                  -Value $listPath -Encoding UTF8
                $document=[ordered]@{header=[ordered]@{cloc_version='2.02-test-double'}}
                foreach($path in @(Get-Content -LiteralPath $listPath -Encoding UTF8)){
                  $normalized=$path.Replace('\','/').ToLowerInvariant()
                  if(
                    $normalized-match '/(artifacts|generated|vendor|third_party|runs)/' -or
                    $normalized-match '/docs/history/' -or
                    $normalized-match '/scratch/'
                  ){
                    throw "Excluded path reached cloc: $path"
                  }
                  $language=switch([IO.Path]::GetExtension($path).ToLowerInvariant()){
                    '.py' {'Python';break}
                    '.lua' {'Lua';break}
                    '.fly2' {'Lua';break}
                    '.m' {'MATLAB';break}
                    '.gem' {'SIMION GEM';break}
                    '.json' {'JSON';break}
                    '.ps1' {'PowerShell';break}
                    default {'Other';break}
                  }
                  $metrics=[ordered]@{
                    blank=0
                    comment=0
                    code=0
                    language=$language
                  }
                  foreach($line in @(Get-Content -LiteralPath $path -Encoding UTF8)){
                    if([string]::IsNullOrWhiteSpace($line)){
                      $metrics.blank+=1
                    }elseif($line.TrimStart().StartsWith('#')){
                      $metrics.comment+=1
                    }else{
                      $metrics.code+=1
                    }
                  }
                  $document[$path]=$metrics
                }
                $document.SUM=[ordered]@{blank=0;comment=0;code=0}
                $document|ConvertTo-Json -Depth 6
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return fake

    @staticmethod
    def _category_code_sums(output: str) -> dict[str, int]:
        sums: dict[str, int] = {}
        current_category: str | None = None
        for line in output.splitlines():
            if line.startswith("CATEGORY="):
                current_category = line.removeprefix("CATEGORY=")
            elif current_category and line.startswith("LANGUAGE=SUM "):
                match = re.search(r" RESULT_CODE=(\d+)", line)
                if match:
                    sums[current_category] = int(match.group(1))
        return sums

    def test_report_classifies_tests_and_excludes_untracked_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._initialize_repo(root)
            fake_cloc = self._write_fake_cloc(root)

            (root / "src" / "main.py").write_text(
                "print('base')\nprint('current')\n", encoding="utf-8"
            )
            (root / "src" / "new.lua").write_text("return 1\n", encoding="utf-8")
            (root / "src" / "forced_matlab.m").write_text(
                "value = 2;\n", encoding="utf-8"
            )
            (root / "src" / "geometry.gem").write_text(
                "; geometry\npa_define(10, 10, 10)\n", encoding="utf-8"
            )
            (root / "src" / "particles.fly2").write_text(
                "particles { }\n", encoding="utf-8"
            )
            worktree_history = (
                root
                / "projects"
                / "active_project"
                / "docs"
                / "history"
                / "worktree_snapshot"
            )
            worktree_history.mkdir(parents=True)
            (worktree_history / "superseded.py").write_text(
                "raise RuntimeError('history is not active code')\n",
                encoding="utf-8",
            )
            worktree_scratch = root / "scratch" / "worktree_task"
            worktree_scratch.mkdir(parents=True)
            (worktree_scratch / "temporary.m").write_text(
                "error('scratch is not active code');\n", encoding="utf-8"
            )
            worktree_tmp = root / ".tmp" / "worktree_task"
            worktree_tmp.mkdir(parents=True)
            (worktree_tmp / "temporary.json").write_text(
                '{"temporary": true}\n', encoding="utf-8"
            )
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
            ignored_profile = (
                root
                / "projects"
                / "active_project"
                / "config"
                / "execution_profiles.json"
            )
            ignored_profile.parent.mkdir()
            (root / ".gitignore").write_text(
                "projects/active_project/config/execution_profiles.json\n",
                encoding="utf-8",
            )
            ignored_profile.write_text(
                '{"profiles":[{"steps":[{"entrypoint":"tests/helper.py"}]}]}\n',
                encoding="utf-8",
            )
            ignored_test_dir = root / "projects" / "active_project" / "tests"
            ignored_test_dir.mkdir()
            (ignored_test_dir / "helper.py").write_text(
                "VALUE = 2\n", encoding="utf-8"
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
                "CREATED_UTC=",
                "CLASSIFIER_SHA256=",
                "LANGUAGE_DEFINITION_SHA256=",
                "WORKTREE_DIRTY=true",
                "WORKTREE_TRACKED_DIRTY_COUNT=1",
                "INPUT_IDENTITY SNAPSHOT=baseline",
                "INPUT_IDENTITY SNAPSHOT=result",
                "FILTER=extensions=",
                "language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM",
                "excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|"
                "artifacts/projects/<project>/(archive|scratch)/**",
                "CATEGORY=total",
                "CATEGORY=production",
                "CATEGORY=tests",
                "CATEGORY=unclassified",
                "REASON=active_powershell_entrypoint",
                "CLASSIFICATION_WARNING SNAPSHOT=result "
                "PATH=project/tests/helper.py",
                "CLASSIFICATION_WARNING SNAPSHOT=result "
                "PATH=projects/active_project/tests/helper.py",
            ):
                self.assertIn(required, output)
            self.assertRegex(
                output,
                r"(?s)CATEGORY=production.*LANGUAGE=Lua "
                r"BASE_FILES=0 RESULT_FILES=2 DELTA_FILES=2",
            )
            self.assertRegex(
                output,
                r"(?s)CATEGORY=production.*LANGUAGE=MATLAB "
                r"BASE_FILES=1 RESULT_FILES=2 DELTA_FILES=1",
            )
            self.assertRegex(
                output,
                r"(?s)CATEGORY=production.*LANGUAGE=SIMION GEM "
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
            self.assertRegex(
                output,
                r"(?s)CATEGORY=production.*LANGUAGE=JSON "
                r"BASE_FILES=2 RESULT_FILES=2 DELTA_FILES=0",
            )
            self.assertNotIn("Excluded path reached cloc", output)
            identities = re.findall(
                r"INPUT_IDENTITY SNAPSHOT=(?:baseline|result) FILES=\d+ "
                r"SHA256=([0-9a-f]{64})",
                output,
            )
            self.assertEqual(len(identities), 2, identities)
            self.assertNotEqual(identities[0], identities[1])
            calls = (fake_cloc.parent / "calls.log").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(calls), 2, calls)
            sums = self._category_code_sums(output)
            self.assertEqual(
                sums["total"],
                sums["production"] + sums["tests"] + sums["unclassified"],
            )

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
