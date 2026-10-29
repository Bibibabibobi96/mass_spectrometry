import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.contracts import verify_run_manifest, write_run_manifest


VERIFIER = Path(__file__).with_name("verify_run_manifest.py")
REPO_ROOT = Path(__file__).parents[2]


class ManifestOutputListTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_same_producer_publication_checks_metadata_without_second_payload_reader(self):
        callers = (
            ("parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1",
             "Write-RunManifest", "if($null-ne$capacity)", "parallel_mirror_dual_stripe_mr_tof", "native_fixture", ("success", "failed", "interrupted"), ()),
            ("dual_pressure_rectilinear_ion_processor/simion/prepare_gui_replay.ps1",
             "Write-RunManifest", "", "dual_pressure_rectilinear_ion_processor", "gui_fixture", ("checkpoint", "failed"), ("project",)),
            ("single_reflection_oa_tof_mass_analyzer/workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1",
             "& $python @manifestArgs", "$runRecordComplete", "single_reflection_oa_tof_mass_analyzer", "formal_cross_solver_diagnostics", ("success",), ("project", "mode")),
        )
        with tempfile.TemporaryDirectory(prefix="producer_manifest_boundary_") as directory:
            root = Path(directory)
            script = root / "publication.ps1"
            script.write_text(r'''param($RepoRoot,$RealPython,$Root,$CasePath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
$case=Get-Content -LiteralPath $CasePath -Raw|ConvertFrom-Json
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($case.runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$starts=@($ast.FindAll({param($n)
 $n-is[Management.Automation.Language.PipelineAst]-and$n.Extent.Text.StartsWith($case.start)
},$true))
if($starts.Count-ne1){throw 'Expected one actual producer publication boundary'}
$statements=@($starts[0].Parent.Statements)
$selected=@();$collect=$false
foreach($statement in $statements){
 if($statement-eq$starts[0]){$collect=$true}
 if($collect-and$case.end-and$statement.Extent.Text.StartsWith($case.end)){break}
 if($collect){$selected+=$statement.Extent.Text}
}
$publication=[scriptblock]::Create(($selected-join"`n"))
$RunDirectory=$Root;$runDir=$Root;$repo=$RepoRoot
$runConfig=Join-Path $Root 'run_config.json'
$manifestPath=Join-Path $Root 'run_manifest.json'
$pkg=@{run_dir=$Root;run_config=$runConfig};$package=$pkg
$outputs=@(Join-Path $Root 'result.txt');$software=@('software fixture')
[IO.File]::WriteAllText($outputs[0],'closed payload')
function Invoke-PublicationFixturePython {
 if(($args-join' ')-match 'verify_run_manifest'){
  $script:verifierCalls++;throw 'SECOND_PAYLOAD_READER'
 }
 $script:writerCalls++
 if($args-contains'--output-list-json'){@($input)|& $RealPython @args}else{& $RealPython @args}
 if($LASTEXITCODE-ne0){throw 'Public writer failed'}
 if($script:attempt.document-ne'none'){
  $path=if($script:attempt.document-eq'manifest'){$manifestPath}else{$runConfig}
  $document=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json -AsHashtable
  $document[$script:attempt.field]=$script:attempt.value
  Write-RunJson -Path $path -Value $document
 }
}
$Python='Invoke-PublicationFixturePython';$PythonExe=$Python
$results=@()
foreach($script:attempt in $case.attempts){
 $status=$script:attempt.status;$script:writerCalls=0;$script:verifierCalls=0
 Write-RunJson -Path $runConfig -Value @{
  schema_version=1;run_id='20261029_120000__test__python__producer-manifest'
  project=$case.project;mode=$case.mode;inputs=@{}
 }
 $manifestArgs=@((Join-Path $RepoRoot 'common/contracts/write_run_manifest.py'),
  '--run-config',$runConfig,'--status',$status,'--output',$outputs[0])
 $caught=$null
 try{$null=. $publication}catch{$caught=$_.Exception.Message}
 $results+=@{accepted=($null-eq$caught);error=$caught;writer_calls=$script:writerCalls;verifier_calls=$script:verifierCalls}
}
ConvertTo-Json -InputObject @($results) -Depth 8 -Compress
''', encoding="utf-8", newline="\n")
            for relative, start, end, project, mode, statuses, identity_fields in callers:
                with self.subTest(caller=relative):
                    attempts = [dict(status=status, document="none", field="", value="") for status in statuses]
                    for field in ("status", *identity_fields):
                        for document in (("manifest",) if field == "status" else ("manifest", "config")):
                            expected = statuses[0] if field == "status" else {"project": project, "mode": mode}[field]
                            for value in ("wrong", expected.upper()):
                                attempts.append(dict(status=statuses[0], document=document, field=field, value=value))
                    case_path = root / "case.json"
                    case_path.write_text(json.dumps(dict(
                        runner=str(REPO_ROOT / "projects" / relative), start=start, end=end,
                        project=project, mode=mode, attempts=attempts,
                    )), encoding="utf-8")
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(script), str(REPO_ROOT), sys.executable, str(root), str(case_path)],
                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=40,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(result.stdout)
                    self.assertEqual(len(actual), len(attempts))
                    for attempt, observed in zip(attempts, actual, strict=True):
                        with self.subTest(attempt=attempt):
                            self.assertEqual(observed["writer_calls"], 1, observed)
                            self.assertEqual(observed["verifier_calls"], 0, observed)
                            self.assertEqual(observed["accepted"], attempt["document"] == "none", observed)

    def test_successful_reference_uses_one_exact_manifest_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "value.json"
            path.write_text("{}", encoding="utf-8")
            record = write_run_manifest.file_record(path)
            manifest = dict(project="assembly", mode="prepare", status="success",
                            inputs={"value": record}, outputs=[{"path": "unconsumed-missing.bin"}])
            def invoke(value):
                return verify_run_manifest.verified_successful_run_reference(
                    root, path.name, project="assembly", mode="prepare", manifest=value)
            self.assertEqual(invoke(manifest), path)
            for field, value in (("project", "other"), ("mode", "other"), ("status", "interrupted")):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    invoke(dict(manifest, **{field: value}))
            with self.assertRaisesRegex(ValueError, "exactly one"):
                invoke(dict(manifest, outputs=[record]))
            with self.assertRaisesRegex(ValueError, "exactly one"):
                invoke(dict(manifest, inputs={}))
            (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(verify_run_manifest.verified_successful_run_reference(
                root, path.name, project="assembly", mode="prepare"), path)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "SHA-256"):
                invoke(manifest)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_public_json_writer_preserves_array_shape_for_all_cardinalities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "json_shapes.ps1"
            script.write_text('''param($Repo,$Output)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
Write-RunJson -Value @() -Path (Join-Path $Output 'empty.json')
Write-RunJson -Value @('single') -Path (Join-Path $Output 'single.json')
Write-RunJson -Value @('first','second') -Path (Join-Path $Output 'multiple.json')
Write-RunJson -Value @{logs=@('single');count=1} -Path (Join-Path $Output 'object.json')
''', encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script), str(REPO_ROOT), str(root)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name, expected in (
                ("empty", []), ("single", ["single"]),
                ("multiple", ["first", "second"]),
                ("object", {"logs": ["single"], "count": 1}),
            ):
                with self.subTest(name=name):
                    self.assertEqual(json.loads((root / f"{name}.json").read_text(encoding="utf-8-sig")), expected)

    def config(self, root):
        path = root / "run_config.json"
        path.write_text(json.dumps(dict(
            schema_version=1, run_id="20261016_210000__analysis__python__manifest-output-list",
            project="fixture", mode="fixture", inputs={},
        )), encoding="utf-8")
        return path

    def test_cli_keeps_output_compatibility_and_appends_utf8_json_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            files = [root / "first.txt", root / "空间 output.txt"]
            for path in files:
                path.write_text("fixture", encoding="utf-8")
            listing = root / "outputs.json"
            listing.write_text(json.dumps([str(files[1])], ensure_ascii=False), encoding="utf-8")
            for source in (str(listing), "-"):
                with self.subTest(source=source):
                    result = subprocess.run(
                        [sys.executable, str(Path(write_run_manifest.__file__)), "--run-config", str(config),
                         "--status", "success", "--output", str(files[0]), "--output-list-json", source],
                        input=listing.read_text(encoding="utf-8") if source == "-" else None,
                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual([row["path"] for row in manifest["outputs"]], [str(p.resolve()) for p in files])

    def test_output_list_rejects_non_list_non_strings_and_accepts_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            listing = root / "outputs.json"
            for value in ({}, None, "file.txt", [None], [True], [123], [["file.txt"]], []):
                with self.subTest(value=value):
                    listing.write_text(json.dumps(value), encoding="utf-8")
                    arguments = ["writer", "--run-config", str(config), "--status", "checkpoint",
                                 "--output-list-json", str(listing)]
                    with patch.object(sys, "argv", arguments):
                        if value == []:
                            write_run_manifest.main()
                            self.assertEqual(json.loads((root / "run_manifest.json").read_text())["outputs"], [])
                        else:
                            with self.assertRaisesRegex(SystemExit, r"JSON list\[str\]"):
                                write_run_manifest.main()

    def test_cli_refuses_missing_outputs_and_pending_publication_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            manifest = root / "run_manifest.json"
            manifest.write_bytes(b"previous publication")
            for status in ("success", "failed", "checkpoint", "interrupted", "superseded"):
                with self.subTest(status=status), patch.object(sys, "argv", [
                    "writer", "--run-config", str(config), "--status", status,
                    "--output", str(root / "missing.txt"),
                ]):
                    with self.assertRaisesRegex(SystemExit, "missing run outputs"):
                        write_run_manifest.main()
                    self.assertEqual(manifest.read_bytes(), b"previous publication")
            configuration = json.loads(config.read_text(encoding="utf-8"))
            configuration["inputs"] = {"required": str(root / "missing-input.txt")}
            config.write_text(json.dumps(configuration), encoding="utf-8")
            with patch.object(sys, "argv", ["writer", "--run-config", str(config), "--status", "success"]):
                with self.assertRaisesRegex(SystemExit, "missing run inputs"):
                    write_run_manifest.main()
            self.assertEqual(manifest.read_bytes(), b"previous publication")
            (root / write_run_manifest.TERMINAL_JOURNAL_NAME).write_text("{}")
            with patch.object(sys, "argv", ["writer", "--run-config", str(config), "--status", "success"]):
                with self.assertRaisesRegex(SystemExit, "publication is incomplete"):
                    write_run_manifest.main()
            self.assertEqual(manifest.read_bytes(), b"previous publication")

    def test_cli_rejects_corrupt_persisted_manifest_without_rereading_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            output = root / "result.txt"
            output.write_bytes(b"result")
            arguments = ["writer", "--run-config", str(config), "--status", "success", "--output", str(output)]
            persist = write_run_manifest.write_json_atomic
            for replacement in (b"{", b'{"schema_version":true}', b'{"schema_version":1,"schema_version":1}'):
                def corrupt(path, document):
                    persist(path, document)
                    payload = write_run_manifest._json_bytes(document)
                    path.write_bytes(payload.replace(b'"schema_version": 1', replacement[1:-1])
                                     if replacement != b"{" else replacement)

                with self.subTest(replacement=replacement), patch.object(sys, "argv", arguments), \
                        patch.object(write_run_manifest, "write_json_atomic", side_effect=corrupt), \
                        patch.object(write_run_manifest, "file_sha256", wraps=file_sha256) as reader:
                    with self.assertRaisesRegex(SystemExit, "published manifest differs"):
                        write_run_manifest.main()
                    self.assertEqual(sum(Path(call.args[0]) == output for call in reader.call_args_list), 1)

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows PowerShell 7 required")
    def test_real_powershell_publication_over_40k_argument_equivalent_and_full_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            files = [root / (f"output_{i:03}_" + "a" * 145 + "_空间.txt") for i in range(240)]
            for path in files:
                path.write_text("small fixture", encoding="utf-8")
            command_length = len(subprocess.list2cmdline([
                sys.executable, str(Path(write_run_manifest.__file__)), "--run-config", str(config),
                "--status", "success", *[arg for path in files for arg in ("--output", str(path))],
            ]))
            self.assertGreater(command_length, 40_000)
            listing = root / "fixture-list.json"
            listing.write_text(json.dumps([str(p) for p in files], ensure_ascii=False), encoding="utf-8")
            script = root / "fixture.ps1"
            script.write_text('''param($Repo,$Python,$Config,$List)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$outputs=@(Get-Content -LiteralPath $List -Raw -Encoding UTF8|ConvertFrom-Json)
Write-VerifiedRunManifest -Python $Python -RepoRoot $Repo -RunConfig $Config -Status success -Outputs $outputs
''', encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script), str(REPO_ROOT), sys.executable, str(config), str(listing)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("RUN_MANIFEST=PASS", result.stdout)
            manifest = root / "run_manifest.json"
            self.assertEqual(len(json.loads(manifest.read_text(encoding="utf-8"))["outputs"]), 240)
            verified = subprocess.run(
                [sys.executable, str(VERIFIER), str(manifest), "--require-status", "success"],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)


def record(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


class ManifestPayloadReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.payload = Path(self.directory.name) / "field.pa"
        self.payload.write_bytes(b"fixture!")

    def repeated_manifest(self, *, cached=True, **kwargs):
        root = self.payload.parent
        config = root / "run_config.json"
        config.write_text(json.dumps(dict(
            schema_version=2, run_id="20261017_120000__test__python__manifest-read-reuse",
            project="fixture", mode="fixture", inputs={"first": "field.pa", "alias": "./field.pa"},
            artifact_retention={"policy_version": 1, "class": "solver_review", "reason": "identity fixture"},
        )), encoding="utf-8")
        reader = write_run_manifest.file_record

        def uncached(*args, **options):
            options.pop("_identity_cache", None)
            return reader(*args, **options)

        with patch.object(write_run_manifest, "file_record", reader if cached else uncached):
            return write_run_manifest.build_run_manifest(
                config, "success", output_paths=[self.payload, self.payload], **kwargs)

    def test_build_reuses_identity_without_changing_record_shapes_or_staging_paths(self) -> None:
        calls = []

        def read(path):
            calls.append(path.resolve())
            return file_sha256(path)

        destination = self.payload.parent / "published"
        with patch.object(write_run_manifest, "file_sha256", side_effect=read):
            original = self.repeated_manifest(cached=False, recorded_root=destination)
            self.assertEqual(calls.count(self.payload.resolve()), 4)
            calls.clear()
            reused = self.repeated_manifest(recorded_root=destination)
            self.assertEqual(calls.count(self.payload.resolve()), 1)
        for document in (original, reused):
            document.pop("recorded_at_utc")
        self.assertEqual(reused, original)
        self.assertEqual(reused["inputs"]["first"]["path"], str(destination / "field.pa"))
        self.assertNotIn("retention_role", reused["inputs"]["first"])
        self.assertEqual(reused["outputs"][0]["retention_role"], "solver_native_binary")

    def test_build_and_verify_each_read_fresh_and_reject_conflicting_declarations(self) -> None:
        calls = []

        def read(path):
            calls.append(path.resolve())
            return file_sha256(path)

        manifest_path = self.payload.parent / "run_manifest.json"
        with patch.object(write_run_manifest, "file_sha256", side_effect=read):
            manifest = self.repeated_manifest()
            self.repeated_manifest()
            self.assertEqual(calls.count(self.payload.resolve()), 2)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(sys, "argv", ["verify", str(manifest_path)]):
                verify_run_manifest.main()
                verify_run_manifest.main()
            self.assertEqual(calls.count(self.payload.resolve()), 4)
            for field, value, error in (("sha256", "A" * 64, "SHA-256 changed"),
                                         ("bytes", 9, "byte count changed")):
                changed = json.loads(json.dumps(manifest))
                changed["outputs"][0][field] = value
                manifest_path.write_text(json.dumps(changed), encoding="utf-8")
                with patch.object(sys, "argv", ["verify", str(manifest_path)]), self.assertRaisesRegex(AssertionError, error):
                    verify_run_manifest.main()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.payload.write_bytes(b"changed!")
            with patch.object(sys, "argv", ["verify", str(manifest_path)]), self.assertRaisesRegex(AssertionError, "SHA-256 changed"):
                verify_run_manifest.main()

    def test_same_call_metadata_changes_invalidate_identity_and_missing_files_fail(self) -> None:
        cache = {}
        with patch.object(write_run_manifest, "file_sha256", wraps=file_sha256) as reader:
            original = write_run_manifest.file_record(self.payload, _identity_cache=cache)
            metadata = self.payload.stat()
            self.payload.write_bytes(b"changed!")
            os.utime(self.payload, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 2_000_000_000))
            changed = write_run_manifest.file_record(self.payload, _identity_cache=cache)
            self.assertNotEqual(changed["sha256"], original["sha256"])
            self.assertEqual(reader.call_count, 2)
            with self.assertRaisesRegex(AssertionError, "SHA-256 changed"):
                verify_run_manifest.verify_record("old declaration", original, _identity_cache=cache)
            self.assertEqual(reader.call_count, 2)
            self.payload.unlink()
            with self.assertRaisesRegex(AssertionError, "is missing"):
                verify_run_manifest.verify_record("old declaration", original, _identity_cache=cache)

    def test_same_call_keeps_buffered_unbuffered_and_virtual_identities_separate(self) -> None:
        cache = {}
        with (
            patch.object(write_run_manifest, "os", SimpleNamespace(name="nt")),
            patch.object(write_run_manifest, "_UNBUFFERED_SOLVER_PAYLOAD_BYTES", 8),
            patch.object(write_run_manifest, "file_sha256", return_value="B" * 64) as buffered,
            patch.object(write_run_manifest, "file_sha256_unbuffered", return_value="A" * 64) as direct,
        ):
            for _ in range(2):
                ordinary = write_run_manifest.file_record(self.payload, "diagnostic_data", _identity_cache=cache)
                native = write_run_manifest.file_record(self.payload, "solver_native_binary", _identity_cache=cache)
            self.assertEqual((ordinary["sha256"], native["sha256"]), ("B" * 64, "A" * 64))
            buffered.assert_called_once_with(self.payload)
            direct.assert_called_once_with(self.payload)
            first = write_run_manifest.file_record(self.payload, document={"future": 1}, _identity_cache=cache)
            second = write_run_manifest.file_record(self.payload, document={"future": 2}, _identity_cache=cache)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertEqual(len(cache), 2)
            self.assertEqual(buffered.call_count, 1)
            self.assertEqual(direct.call_count, 1)

    def test_virtual_build_bytes_and_recorded_paths_match_fresh_records(self) -> None:
        document = {"status": "future"}
        options = dict(recorded_root=self.payload.parent / "published",
                       virtual_documents={self.payload: document})
        original = self.repeated_manifest(cached=False, **options)
        reused = self.repeated_manifest(**options)
        for manifest in (original, reused):
            manifest.pop("recorded_at_utc")
        self.assertEqual(reused, original)
        expected = write_run_manifest.file_record(self.payload, document=document)
        self.assertEqual(reused["outputs"][0]["sha256"], expected["sha256"])
        self.assertNotEqual(reused["inputs"]["first"]["sha256"], expected["sha256"])

    def test_writer_and_verifier_share_one_unbuffered_selection(self) -> None:
        self.payload = self.payload.rename(self.payload.with_suffix(".pa15"))
        with (
            patch.object(write_run_manifest, "os", SimpleNamespace(name="nt")),
            patch.object(write_run_manifest, "_UNBUFFERED_SOLVER_PAYLOAD_BYTES", 8),
            patch.object(write_run_manifest, "file_sha256", return_value="B" * 64) as buffered,
            patch.object(write_run_manifest, "file_sha256_unbuffered", return_value="A" * 64) as direct,
        ):
            cache = {}
            item = write_run_manifest.file_record(self.payload, _identity_cache=cache)
            output = write_run_manifest.file_record(
                self.payload, "solver_native_binary", _identity_cache=cache)
            self.assertNotIn("retention_role", item)
            self.assertEqual(item["sha256"], output["sha256"])
            self.assertEqual(direct.call_count, 1)
            verify_run_manifest.verify_record("input", item)
            self.assertEqual(item["sha256"], "A" * 64)
            self.assertEqual(direct.call_count, 2)
            for call in direct.call_args_list:
                self.assertEqual(call.args, (self.payload,))
            buffered.assert_not_called()

    def test_small_ordinary_and_non_windows_records_keep_buffered_reads(self) -> None:
        cases = (
            ("nt", "solver_native_binary", 9),
            ("nt", None, 9),
            ("nt", "diagnostic_data", 8),
            ("posix", "solver_native_binary", 8),
            ("posix", None, 8),
        )
        for platform_name, role, threshold in cases:
            with (
                self.subTest(platform=platform_name, role=role, threshold=threshold),
                patch.object(write_run_manifest, "os", SimpleNamespace(name=platform_name)),
                patch.object(write_run_manifest, "_UNBUFFERED_SOLVER_PAYLOAD_BYTES", threshold),
                patch.object(write_run_manifest, "file_sha256", return_value="A" * 64) as buffered,
                patch.object(write_run_manifest, "file_sha256_unbuffered") as direct,
                patch.object(write_run_manifest, "retention_api", side_effect=AssertionError("unneeded policy read")),
            ):
                item = write_run_manifest.file_record(self.payload, role)
                verify_run_manifest.verify_record("output", item)
                self.assertEqual(buffered.call_count, 2)
                direct.assert_not_called()

    def test_unbuffered_failure_propagates_without_retry_or_fallback(self) -> None:
        item = dict(path=str(self.payload), bytes=8, sha256="A" * 64)
        with (
            patch.object(write_run_manifest, "os", SimpleNamespace(name="nt")),
            patch.object(write_run_manifest, "_UNBUFFERED_SOLVER_PAYLOAD_BYTES", 8),
            patch.object(write_run_manifest, "file_sha256") as buffered,
            patch.object(write_run_manifest, "file_sha256_unbuffered", side_effect=OSError("read failed")) as direct,
        ):
            with self.assertRaisesRegex(OSError, "read failed"):
                write_run_manifest.file_record(self.payload)
            direct.assert_called_once_with(self.payload)
            direct.reset_mock()
            with self.assertRaisesRegex(OSError, "read failed"):
                verify_run_manifest.verify_record("output", item)
            direct.assert_called_once_with(self.payload)
            buffered.assert_not_called()

    def test_mismatching_unbuffered_bytes_fail_existing_identity(self) -> None:
        item = dict(path=str(self.payload), bytes=8, sha256="A" * 64)
        with (
            patch.object(write_run_manifest, "os", SimpleNamespace(name="nt")),
            patch.object(write_run_manifest, "_UNBUFFERED_SOLVER_PAYLOAD_BYTES", 8),
            patch.object(write_run_manifest, "file_sha256") as buffered,
            patch.object(write_run_manifest, "file_sha256_unbuffered", return_value="B" * 64) as direct,
        ):
            with self.assertRaisesRegex(AssertionError, "SHA-256 changed"):
                verify_run_manifest.verify_record("output", item)
            direct.assert_called_once_with(self.payload)
            buffered.assert_not_called()

    def test_size_mismatch_rejects_before_reading_payload(self) -> None:
        with patch.object(verify_run_manifest, "file_record") as reader:
            with self.assertRaisesRegex(AssertionError, "byte count changed"):
                verify_run_manifest.verify_record("output", dict(path=str(self.payload), bytes=9))
            reader.assert_not_called()


class VerifyRunManifestIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.run = Path(self.temporary_directory.name) / "runs" / "reference-run"
        self.run.mkdir(parents=True)
        self.resolved_sha = "A" * 64
        self.source_sha = "B" * 64
        self.config = self.run / "run_config.json"
        self.consumed_input = self.run / "consumed_input.json"
        self.consumed_input.write_text('{"stable": true}\n', encoding="utf-8")
        self.unconsumed_input = self.run / "unconsumed_input.bin"
        self.unconsumed_input.write_bytes(b"original")
        self.consumed_output = self.run / "consumed_output.json"
        self.consumed_output.write_text('{"result": 1}\n', encoding="utf-8")
        self.unconsumed_output = self.run / "unconsumed_output.bin"
        self.unconsumed_output.write_bytes(b"original")
        self.config.write_text(
            json.dumps(
                {
                    "run_id": "reference-run",
                    "project": "rf_quadrupole_ion_optics",
                    "mode": "resolved_design_transport",
                    "parameters": {"design_profile_id": "official"},
                    "provenance": {
                        "parent_resolved_design_sha256": self.resolved_sha,
                        "particle_source_sha256": self.source_sha,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.manifest = self.run / "run_manifest.json"
        self._write_manifest("success")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_manifest(self, status: str) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "run_id": "reference-run",
                    "project": "rf_quadrupole_ion_optics",
                    "mode": "resolved_design_transport",
                    "status": status,
                    "run_config": record(self.config),
                    "inputs": {
                        "consumed_contract": record(self.consumed_input),
                        "unconsumed_payload": record(self.unconsumed_input),
                    },
                    "outputs": [
                        record(self.consumed_output),
                        record(self.unconsumed_output),
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _verify(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(self.manifest),
                "--require-status",
                "success",
                "--require-local-run-config",
                "--require-run-id",
                "reference-run",
                "--require-project",
                "rf_quadrupole_ion_optics",
                "--require-mode",
                "resolved_design_transport",
                "--require-design-profile-id",
                "official",
                "--require-parent-resolved-design-sha256",
                self.resolved_sha,
                "--require-particle-source-sha256",
                self.source_sha,
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=30,
        )

    def test_reference_constraints_accept_matching_fixture(self) -> None:
        result = self._verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUN_MANIFEST_VERIFY=PASS", result.stdout)

    def test_pending_terminal_journal_blocks_manifest_consumption(self) -> None:
        (self.run / ".run_terminal_publication.json").write_text("{}\n", encoding="utf-8")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("publication is incomplete", result.stderr)

    def test_historical_run_relative_records_resolve_from_manifest(self) -> None:
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        document["run_config"]["path"] = "run_config.json"
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        result = self._verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUN_MANIFEST_VERIFY=PASS", result.stdout)

    def test_reference_constraints_fail_closed_on_failed_status(self) -> None:
        self._write_manifest("failed")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 'success'", result.stderr)

    def test_checkpoint_manifest_is_verifiable_when_explicitly_requested(self) -> None:
        self._write_manifest("checkpoint")
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(self.manifest),
                "--require-status",
                "checkpoint",
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reference_constraints_fail_closed_on_identity_mismatch(self) -> None:
        document = json.loads(self.config.read_text(encoding="utf-8"))
        document["provenance"]["particle_source_sha256"] = "C" * 64
        self.config.write_text(json.dumps(document), encoding="utf-8")
        self._write_manifest("success")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("particle_source_sha256", result.stderr)

    def test_reference_constraints_reject_external_run_config(self) -> None:
        external = self.run.parent / "external_run_config.json"
        external.write_text(self.config.read_text(encoding="utf-8"), encoding="utf-8")
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        document["run_config"] = record(external)
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside its run directory", result.stderr)

    def test_consumer_projection_verifies_only_explicit_path_bound_records(self) -> None:
        self.unconsumed_input.write_bytes(b"corrupt")
        self.unconsumed_output.write_bytes(b"corrupt")
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
            "--consumed-input",
            "consumed_contract",
            str(self.consumed_input),
            "--consumed-output",
            str(self.consumed_output),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SCOPE=consumer_projection", result.stdout)
        self.assertIn("CONSUMED_INPUTS=1", result.stdout)
        self.assertIn("CONSUMED_OUTPUTS=1", result.stdout)

    def test_consumer_projection_fails_closed_on_consumed_record_drift(self) -> None:
        self.consumed_input.write_text('{"stable": truf}\n', encoding="utf-8")
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
            "--consumed-input",
            "consumed_contract",
            str(self.consumed_input),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 changed", result.stderr)

    def test_consumer_projection_binds_declared_record_to_consumed_path(self) -> None:
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
            "--consumed-input",
            "consumed_contract",
            str(self.unconsumed_input),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path is", result.stderr)

    def test_consumer_projection_requires_named_records(self) -> None:
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --consumed-input or --consumed-output", result.stderr)

    def test_consumed_selectors_require_projection_identity(self) -> None:
        result = self._verify(
            "--consumed-output",
            str(self.consumed_output),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require --consumer-projection-id", result.stderr)


if __name__ == "__main__":
    unittest.main()
