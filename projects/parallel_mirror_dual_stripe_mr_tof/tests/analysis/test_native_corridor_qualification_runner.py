from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT / "simion" / "run_native_corridor_qualification.ps1"
CONTROLLER = PROJECT / "simion" / "create_native_corridor_controller.lua"
REMOVED_STREAM = PROJECT / "simion" / "run_native_corridor_family_stream.ps1"


class NativeCorridorQualificationRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8-sig")

    def test_one_owner_and_one_common_transaction(self) -> None:
        source = self.source
        self.assertFalse(REMOVED_STREAM.exists())
        self.assertIn("'--action','advance-transaction'", source)
        self.assertIn("Invoke-NativeCorridorTransactionLoop", source)
        self.assertIn("if([string]$probe.disposition-eq'miss')", source)
        self.assertIn("$writerLock=Enter-NativeCorridorWriterLock", source)
        self.assertEqual(source.count("Enter-ArtifactWorkflowCapacitySession"), 1)
        self.assertEqual(source.count("Exit-ArtifactWorkflowCapacitySession"), 1)
        for retired in (
            "PreparedStageToken",
            "prepared_marker",
            "streamReceipt",
            "recoveryPath",
            "ResumePreparedStageReceiptPath",
            "prepare-adoption",
            "finalize-adoption",
            "preparedVerified",
            "buildComplete",
        ):
            self.assertNotIn(retired, source)

    def test_builder_only_fills_common_missing_members_atomically(self) -> None:
        source = self.source
        self.assertIn("$missing=@($State.missing_files", source)
        self.assertIn("$responseIds=@(1..8|Where-Object", source)
        self.assertIn("$scratchDirectory=[IO.Path]::GetFullPath([string]$State.scratch_directory)", source)
        self.assertIn("Move-Item -LiteralPath", source)
        self.assertNotIn("Remove-Item -LiteralPath $buildDirectory", source)
        self.assertNotIn("Remove-Item -LiteralPath $destination", source)
        self.assertNotIn("NewGuid", source)
        self.assertNotIn(".staging", source)

    def test_controller_uses_one_scratch_prefix_without_lua_whole_file_copy(self) -> None:
        source = self.source
        controller = CONTROLLER.read_text(encoding="utf-8-sig")
        self.assertIn("$controllerDirectory=Join-Path $scratchDirectory 'controller'", source)
        self.assertIn("Copy-Item -LiteralPath (Join-Path $buildDirectory 'mrtof_analyzer_corridor.pa#')", source)
        self.assertIn("Remove-Item -LiteralPath $controllerRaw", source)
        self.assertIn("assert(raw_path == native_raw", controller)
        self.assertNotIn("read('*a')", controller)

    def test_response_members_queue_independently_under_public_host_admission(self) -> None:
        source = self.source
        self.assertIn("('response-{0:D2}'-f$ResponseId)", source)
        self.assertIn("-Stage dirichlet_response_refine", source)
        self.assertIn("Invoke-NativeCorridorResponseWave -ResponseIds $responseIds", source)
        self.assertIn("Start-Process -FilePath", source)
        self.assertIn("-InternalResponseId", source)
        self.assertIn("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=''", source)

    def test_transaction_loop_does_not_shadow_verifier_output_path(self) -> None:
        source = self.source
        self.assertIn("$transactionVerificationEvidence=''", source)
        self.assertIn('$state=&$Advance $transactionVerificationEvidence', source)
        self.assertIn('$preverificationOutput=[string](&$Preverify $state)', source)
        self.assertLess(source.index('&$Preverify $state'), source.index('&$BindEvidence $state'))
        self.assertNotIn("$verificationEvidence=''", source)
        self.assertNotIn("maximum_parallel", source.lower())
        release = source.index("Exit-HostExecutionLease -Lease $lease -Outcome success", source.index("function Invoke-NativeCorridorFamilyBuild"))
        dispatch = source.index("Invoke-NativeCorridorResponseWave -ResponseIds $responseIds")
        self.assertLess(release, dispatch)

    def test_worker_failure_cannot_remove_an_already_published_member(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_scratch = root / "response-01" / "corridor.pa1"
            first_scratch.parent.mkdir()
            first_scratch.write_bytes(b"complete")
            first_destination = root / "payload" / "corridor.pa1"
            first_destination.parent.mkdir()
            missing_second = root / "response-02" / "corridor.pa2"
            command = (
                "$tokens=$null;$errors=$null;"
                f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
                "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
                "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $n.Name -eq 'Publish-NativeCorridorBuiltMember'},$true);"
                "Invoke-Expression ('function Publish-NativeCorridorBuiltMember '+$fn.Body.Extent.Text);"
                f"Publish-NativeCorridorBuiltMember -ScratchPath '{first_scratch.as_posix()}' -DestinationPath '{first_destination.as_posix()}';"
                f"try{{Publish-NativeCorridorBuiltMember -ScratchPath '{missing_second.as_posix()}' -DestinationPath '{(root / 'payload' / 'corridor.pa2').as_posix()}'}}catch{{}};"
                f"if(-not(Test-Path '{first_destination.as_posix()}')-or([IO.File]::ReadAllBytes('{first_destination.as_posix()}').Length)-ne8){{exit 3}};"
                "'PASS'"
            )
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-Command", command], check=True, cwd=PROJECT,
                capture_output=True, text=True, timeout=30,
            )
            self.assertIn("PASS", completed.stdout)

    def test_verification_is_the_only_project_state_evidence(self) -> None:
        source = self.source
        self.assertIn("role='simion_pa_family_verification'", source)
        self.assertIn("inventory_sha256=[string]$State.inventory_sha256", source)
        self.assertIn("verification_output_path=$resolvedOutput", source)
        self.assertIn("--verification-evidence", source)
        self.assertNotIn("prepared_receipt_sha256", source)
        self.assertIn("native_corridor_family_verification.log", source)

    def test_transaction_arguments_fixture_always_carries_fixed_pin_reason(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        command = (
            "$tokens=$null;$errors=$null;"
            f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
            "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
            "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $n.Name -eq 'Get-NativeCorridorTransactionArguments'},$true);"
            "Invoke-Expression ('function Get-NativeCorridorTransactionArguments '+$fn.Body.Extent.Text);"
            "$cacheRoot='cache';$identityPath='identity.json';$familyMembers=@('a','b');"
            "$publishedPinReason='MR-TOF native adjustable analyzer PA family; rebuild only on frozen geometry identity change';"
            "$a=@(Get-NativeCorridorTransactionArguments);$b=@(Get-NativeCorridorTransactionArguments -VerificationEvidence verify.json);"
            "$pin=[Array]::IndexOf($a,'--published-pin-reason');"
            "if($pin-lt0-or$a[$pin+1]-ne$publishedPinReason-or([Array]::IndexOf($b,'--published-pin-reason'))-lt0-or"
            "([Array]::IndexOf($b,'--verification-evidence'))-lt0){exit 3};'PASS'"
        )
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", command], check=True, cwd=PROJECT,
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("PASS", completed.stdout)

    def test_os_writer_lock_excludes_same_key_and_releases_on_handle_close(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = (
                "$tokens=$null;$errors=$null;"
                f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
                "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
                "foreach($name in @('Enter-NativeCorridorWriterLock','Exit-NativeCorridorWriterLock')){"
                "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $n.Name -eq $name},$true);Invoke-Expression ('function '+$name+' '+$fn.Body.Extent.Text)};"
                f"$root='{root.as_posix()}';$key='A'*64;"
                "$first=Enter-NativeCorridorWriterLock -Root $root -CacheKey $key;$blocked=$false;"
                "try{$second=Enter-NativeCorridorWriterLock -Root $root -CacheKey $key}catch{$blocked=$_.Exception.Message-like'*active builder*'};"
                "if(-not$blocked){exit 3};Exit-NativeCorridorWriterLock -Lock $first;"
                "$third=Enter-NativeCorridorWriterLock -Root $root -CacheKey $key;"
                "if($null-eq$third){exit 4};Exit-NativeCorridorWriterLock -Lock $third;'PASS'"
            )
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-Command", command], check=True, cwd=PROJECT,
                capture_output=True, text=True, timeout=30,
            )
            self.assertIn("PASS", completed.stdout)

    def test_atomic_member_fixture_never_overwrites_or_deletes_owned_payload(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "scratch.pa1"
            destination = root / "payload.pa1"
            scratch.write_bytes(b"first")
            command = (
                "$tokens=$null;$errors=$null;"
                f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
                "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
                "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $n.Name -eq 'Publish-NativeCorridorBuiltMember'},$true);"
                "Invoke-Expression ('function Publish-NativeCorridorBuiltMember '+$fn.Body.Extent.Text);"
                f"Publish-NativeCorridorBuiltMember -ScratchPath '{scratch.as_posix()}' -DestinationPath '{destination.as_posix()}';"
                f"if((Test-Path '{scratch.as_posix()}')-or-not(Test-Path '{destination.as_posix()}')){{exit 3}};"
                f"Set-Content -LiteralPath '{scratch.as_posix()}' -Value second;"
                f"try{{Publish-NativeCorridorBuiltMember -ScratchPath '{scratch.as_posix()}' -DestinationPath '{destination.as_posix()}';exit 4}}catch{{}};"
                f"if(-not(Test-Path '{scratch.as_posix()}')-or([IO.File]::ReadAllBytes('{destination.as_posix()}')[0])-ne102){{exit 5}};"
                "'PASS'"
            )
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-Command", command], check=True, cwd=PROJECT,
                capture_output=True, text=True, timeout=30,
            )
            self.assertIn("PASS", completed.stdout)

    def test_transition_fixture_recovers_partial_complete_verified_and_published(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = (
                "$tokens=$null;$errors=$null;"
                f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
                "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
                "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $n.Name -eq 'Invoke-NativeCorridorTransactionLoop'},$true);"
                "Invoke-Expression ('function Invoke-NativeCorridorTransactionLoop '+$fn.Body.Extent.Text);"
                "$states=@("
                "[pscustomobject]@{status='building';action_required='build';missing_files=@('pa2','pa3')},"
                "[pscustomobject]@{status='building';action_required='verify';inventory_sha256=('A'*64)},"
                "[pscustomobject]@{status='published';action_required='complete';generation_sha256=('B'*64)});"
                "$script:i=0;$script:builds=@();$script:preverifies=0;$script:binds=0;"
                "$advance={param($evidence)$s=$states[$script:i];$script:i++;$s};"
                "$build={param($state)$script:builds+=,@($state.missing_files)};"
                f"$preverify={{param($state)$script:preverifies++;'{(root / 'preverify.log').as_posix()}'}};"
                f"$bind={{param($state,$output)$script:binds++;'{(root / 'verify.json').as_posix()}'}};"
                "$final=Invoke-NativeCorridorTransactionLoop -Advance $advance -Build $build -Preverify $preverify -BindEvidence $bind;"
                "if($final.status-ne'published'-or$script:builds.Count-ne1-or$script:preverifies-ne1-or$script:binds-ne1){exit 3};"
                "if($script:builds[0].Count-ne2){exit 4};"
                "'PASS'"
            )
            completed = subprocess.run(
                [pwsh, "-NoProfile", "-Command", command],
                check=True,
                cwd=PROJECT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertIn("PASS", completed.stdout)

    def test_published_fixture_does_not_build_or_verify(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        command = (
            "$tokens=$null;$errors=$null;"
            f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
            "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
            "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $n.Name -eq 'Invoke-NativeCorridorTransactionLoop'},$true);"
            "Invoke-Expression ('function Invoke-NativeCorridorTransactionLoop '+$fn.Body.Extent.Text);"
            "$advance={param($evidence)[pscustomobject]@{status='published';action_required='complete'}};"
            "$build={throw 'unexpected build'};$preverify={throw 'unexpected preverify'};$bind={throw 'unexpected bind'};"
            "$final=Invoke-NativeCorridorTransactionLoop -Advance $advance -Build $build -Preverify $preverify -BindEvidence $bind;"
            "if($final.status-ne'published'){exit 3};'PASS'"
        )
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", command],
            check=True,
            cwd=PROJECT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertIn("PASS", completed.stdout)

    def test_verify_ready_without_preinventory_evidence_fails_closed(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        command = (
            "$tokens=$null;$errors=$null;"
            f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',"
            "[ref]$tokens,[ref]$errors);if($errors.Count){exit 2};"
            "$fn=$ast.Find({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $n.Name -eq 'Invoke-NativeCorridorTransactionLoop'},$true);"
            "Invoke-Expression ('function Invoke-NativeCorridorTransactionLoop '+$fn.Body.Extent.Text);"
            "$states=@([pscustomobject]@{status='building';action_required='verify'},"
            "[pscustomobject]@{status='published';action_required='complete'});$script:i=0;$script:v=0;"
            "$advance={param($evidence)$s=$states[$script:i];$script:i++;$s};"
            "$build={throw 'unexpected build'};$preverify={throw 'unexpected preverify'};$bind={param($state,$output)$script:v++;'verify.json'};"
            "try{Invoke-NativeCorridorTransactionLoop -Advance $advance -Build $build -Preverify $preverify -BindEvidence $bind;exit 3}"
            "catch{if($_.Exception.Message-notlike'*without pre-inventory Fast Adjust evidence*'){exit 4}};'PASS'"
        )
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", command], check=True, cwd=PROJECT,
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("PASS", completed.stdout)

    def test_powershell_parses(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        command = (
            "$errors=$null;[void][System.Management.Automation.Language.Parser]::"
            f"ParseFile('{RUNNER.as_posix()}',[ref]$null,[ref]$errors);"
            "if($errors.Count){$errors|ForEach-Object{Write-Error $_};exit 1}"
        )
        subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True, cwd=PROJECT, timeout=30)


if __name__ == "__main__":
    unittest.main()
