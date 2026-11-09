"""Solver-free owner fixture; no discoverable test methods."""

from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import unittest
from common.contracts.capacity_ledger import initialize_capacity_ledger
from msplatform.execution.inputs import enumerate_python_sources
from common.contracts.write_run_manifest import file_record


REPO = Path(__file__).resolve().parents[3]

OWNER = REPO / "common/contracts/run_artifact_workflow.ps1"

PROJECT = "single_reflection_oa_tof_mass_analyzer"

PWSH = shutil.which("pwsh")

def copy_scientific_core(source_root: Path, destination_root: Path) -> None:
    """Copy the one declared core and its resources into an isolated test author."""
    for relative in enumerate_python_sources(source_root, package_roots=['src/msplatform'],
                                             provider_root='src/msplatform', resource_suffixes=('.schema.json',)):
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / relative, destination)
    # Host/retention readers need the same declared resources in a writable
    # fixture, never the installed policy when a test changes a local budget.
    declaration = source_root / "pyproject.toml"
    shutil.copyfile(declaration, destination_root / "pyproject.toml")
    config = tomllib.loads(declaration.read_text(encoding="utf-8"))
    package = source_root / "src/msplatform/execution"
    for pattern in config["tool"]["setuptools"]["package-data"]["msplatform.execution"]:
        for source in package.glob(pattern):
            if not source.is_file():
                continue
            destination = destination_root / source.relative_to(source_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


CALLBACK = '''import json, os, sys, time
from pathlib import Path
sys.path.insert(0, REPOSITORY)
from common.contracts.write_run_manifest import file_record
from common.contracts.capacity_protection import load_capacity_protection_leases

def execute_prepared_run(config_path, session_path, request_path, completion_path):
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    session = json.loads(session_path.read_text(encoding="utf-8-sig"))
    root = config_path.parent
    payload = request["payload"]
    source_protection = None
    if payload.get("source_artifact_root"):
        source_root = Path(payload["source_artifact_root"])
        source_run = Path(payload["source_run_directory"]).resolve()
        source_protection = load_capacity_protection_leases(source_root)
        assert source_run in source_protection["protected_paths"]
        assert source_protection["committed_new_bytes"] == 0
        assert any(Path(item["artifact_root"]).resolve() == source_root.resolve()
                   and item["status"] == "active" for item in session["source_protection_leases"])
    if request["prepared"].get("native_input_paths"):
        context = session["source_execution_context"]
        assert Path(context["child_run_directory"]).resolve() == root.resolve()
        for path in request["prepared"]["native_input_paths"]:
            source = next(row for row in context["sources"] if str(Path(path).resolve()) in row["input_paths"])
            native = Path(source["execution_directory"]) / Path(path).resolve().relative_to(Path(source["target_directory"]))
            assert len(str(native)) <= 259 and native.read_bytes() == Path(path).read_bytes()
        if payload.get("tamper_source_context"):
            session["source_execution_context"]["sources"][0]["execution_directory"] = "C:/wrong-execution-owner"
            session_path.write_text(json.dumps(session), encoding="utf-8")
    counter = Path(payload["counter_path"])
    counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1", encoding="utf-8")
    protection = load_capacity_protection_leases(Path(session["artifact_root"]))
    assert root.resolve() in protection["protected_paths"]
    assert protection["committed_new_bytes"] == request["capacity"]["committed_new_bytes"]
    if payload.get("raise"):
        raise RuntimeError("original prepared fixture failure")
    config["parameters"] = {"fixture": True}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = root / "results/science.json"
    output.write_text(json.dumps({"capacity_session": session["lease_id"], "worker_process_id": os.getpid(),
        "artifact_root": os.environ.get("MASS_SPECTROMETRY_ARTIFACT_ROOT"),
        "execution_root": os.environ.get("MASS_SPECTROMETRY_EXECUTION_ROOT"),
        "run_directory": os.environ.get("MASS_SPECTROMETRY_RUN_DIRECTORY"),
        "run_execution_directory": os.environ.get("MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"),
        "host_resource_state_path": os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"],
        "source_protected_before_compute": source_protection is not None}), encoding="utf-8")
    outputs, required, preserve = [str(output)], [str(output)], []
    if payload.get("long_native_fixture"):
        extra = root / "results" / ("n" * 190) / "model.json"
        extra.parent.mkdir(); extra.write_text("{}", encoding="utf-8"); outputs.append(str(extra))
    if payload.get("disposable"):
        for name in ("first.pa0", "second.pa0"):
            path = root / "results" / name
            path.write_bytes(b"disposable fixture payload")
            outputs.append(str(path))
    if payload.get("outside_preserve"):
        preserve.append(payload["outside_preserve"])
    if payload.get("log"):
        log = root / "logs/simion__batch01.stdout.log"
        log.write_text("status,Fly completed. 1 splats, 0.1 seconds\\n" if payload["log"] == "complete" else "started\\n", encoding="utf-8")
        outputs.append(str(log)); required.append(str(log))
        if payload.get("preserve"): preserve.append(str(log))
    status = payload.get("status", "success")
    completion = {
        "schema_version": 1, "role": "run_artifact_workflow_completion",
        "run_id": config["run_id"], "project": config["project"],
        "execution_request": file_record(request_path), "run_config": file_record(config_path),
        "status": status, "summary": {"run_id": config["run_id"], "status": status},
        "output_paths": outputs, "required_output_paths": required,
        "retention_preserve_paths": preserve, "manifest_extra_fields": {},
        "writer_completion": payload.get("writers", {"operations": [], "resource_releases": []}),
        "exception": None if status == "success" else {"type": "FixtureFailure", "message": "original scientific failure", "notes": []},
    }
    if payload.get("summary_padding_bytes"):
        completion["summary"]["fixture_padding"] = "x" * payload["summary_padding_bytes"]
    if payload.get("change_request"):
        request_path.write_text("{}", encoding="utf-8")
    if payload.get("change_lifecycle"):
        config["artifact_retention"]["class"] = "qualification"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        completion["run_config"] = file_record(config_path)
    completion_path.write_text(json.dumps(completion), encoding="utf-8")
    if payload.get("late_output"):
        time.sleep(.2)
        print("late prepared stdout 中文", flush=True)
        print("late prepared stderr 中文", file=sys.stderr, flush=True)
    if status != "success": raise RuntimeError("original scientific failure")
'''


def released_writer() -> dict:
    """Synthetic structural receipt, never presented as a real scheduler event."""
    return {
        "operations": [{"operation_id": "native", "observation": {"exit_confirmed": True, "returncode": 0},
                        "resource_release_id": "pool"}],
        "resource_releases": [{"release_id": "pool", "completion_receipt": {"host_release": {
            "inherited": False, "token": "fixture-token", "result": {"status": "released", "token": "fixture-token"},
            "error": None,
        }}}],
    }



class RunArtifactWorkflowFixture(unittest.TestCase):
    """Shared assertions/preparation only; no test methods or shared run state."""

    def _assert_owner_timing(self, result: dict) -> None:
        """Check the existing owner summary clock, independently of command wall time."""
        self.assertGreater(result["elapsed_seconds"], 0)
        self.assertTrue(result["timing"])
        self.assertTrue(all(value >= 0 for value in result["timing"].values()))
        self.assertAlmostEqual(sum(result["timing"].values()), result["elapsed_seconds"], places=2)

    def run_ps(self, root: Path, script: str, *, owned_diagnostics: Path | None = None,
               evidence_paths: tuple[Path, ...] = ()) -> subprocess.CompletedProcess[str]:
        path = root / "invoke.ps1"
        script = "if([Console]::In.ReadLine()-cne'fixture-owned-start'){throw 'Fixture ownership ACK missing'}\n" + script
        path.write_text(script, encoding="utf-8")
        command = [PWSH, "-NoProfile", "-File", str(path)]
        from common.contracts.test_support.fixture_process import run_fixture_process

        outcome = None
        primary = None
        try:
            outcome = run_fixture_process(command, root=root, cwd=REPO,
                                          environment=dict(os.environ, FIXTURE_PYTHON=sys.executable,
                                                           FIXTURE_TEST_METHOD=self.id(), FIXTURE_TEST_SOURCE=__file__),
                                          mode="inherited-grant", timeout=90, diagnostics_root=owned_diagnostics)
            return outcome
        except BaseException as error:
            primary = error
            raise
        finally:
            # Preserve named small records before TemporaryDirectory removes the fixture.
            evidence = getattr(primary if primary is not None else outcome, "fixture_diagnostics", None)
            if evidence is not None:
                try:
                    destination = Path(evidence) / "inputs-and-state"
                    for source in (path, *evidence_paths):
                        relative = source.relative_to(root)
                        if source.is_file():
                            if source.stat().st_size > 1024 * 1024:
                                raise ValueError("Fixture diagnostic input exceeds 1 MiB")
                            target = destination / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                    print(f"FIXTURE_EVIDENCE mode=inherited-grant path={evidence}", flush=True)
                except BaseException as diagnostic_error:
                    if primary is None:
                        raise
                    primary.add_note(f"input_preservation: {diagnostic_error!r}")

    def invoke_fixture(self, root: Path, payload: dict, *, retention: str = "compact", host_state: str | None = None,
                       observation_failure: bool = False, failure_stage: str | None = None, project: str = PROJECT,
                       callback_text: str | None = None, source_references=None,
                       capacity_trace: Path | None = None, native_input_paths=None, expected_execution_relative_paths=None) -> tuple[dict, Path, Path, subprocess.CompletedProcess[str]]:
        artifacts = root / "artifacts"
        artifacts.mkdir()
        initialize_capacity_ledger(artifacts, objects=[])
        callback = root / "fixture_callback.py"
        callback.write_text((CALLBACK if callback_text is None else callback_text).replace("REPOSITORY", repr(str(REPO))), encoding="utf-8")
        # Minimal fixture namespace for the real initial handshake. Production
        # prepared roots already carry this module in their frozen closure.
        (root / "common/contracts").mkdir(parents=True, exist_ok=True)
        for relative in ("common/host_resource_python.py", "common/contracts/file_identity.py"):
            shutil.copyfile(REPO / relative, root / relative)
        copy_scientific_core(REPO, root)
        budget = root / "budget.json"
        committed = payload.get("fixture_commitment_bytes", 1048576)
        budget.write_text(json.dumps({"peak_bytes": committed}), encoding="utf-8")
        project_root = artifacts / "projects" / project
        run = project_root / "runs/20261028_120000__test__python__workflow-fixture"
        request = {
            "schema_version": 1, "role": "run_artifact_workflow_request", "repository_root": str(REPO),
            "python_executable": sys.executable,
            "package": {"project": project, "run_id": run.name, "mode": "software", "artifact_project_root": str(project_root),
                        "software": ["Python"], "retention_class": retention, "retention_reason": "review fixture" if retention != "compact" else ""},
            "capacity": {"committed_new_bytes": committed, "commitment_inputs": [file_record(budget)], "protected_paths": [], "protected_cache_keys": []},
            "prepared": {"module": "fixture_callback", "function": "execute_prepared_run", "import_root": str(root), "entrypoint": file_record(callback)},
            "payload": dict(payload, counter_path=str(root / "callback_count.txt")),
        }
        if source_references is not None:
            request["capacity"]["source_references"] = source_references
        if native_input_paths is not None:
            request["prepared"]["native_input_paths"] = native_input_paths
        if expected_execution_relative_paths is not None:
            request["package"]["expected_execution_relative_paths"] = expected_execution_relative_paths
        request_path, result_path = root / "request.json", root / "result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        # Only disk/host admission is isolated: capacity lease CRUD, package,
        # retention, terminal journal and finalization use the actual TEMP ledger.
        state_setup = (f"$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH='{host_state}'" if host_state is not None else
                       "[Environment]::SetEnvironmentVariable('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH',[NullString]::Value,'Process')")
        sampler = "function Get-ManagedSolverProcessSample { throw 'fixture initial observation unavailable' }" if observation_failure else ""
        hooks = ""
        if failure_stage == "source_alias_cleanup":
            hooks = "function Remove-RunSourceExecutionContext { throw 'fixture source alias cleanup failure' }"
        elif failure_stage == "retention_before":
            hooks = "function Apply-RunArtifactRetention { throw 'fixture before retention' }"
        elif failure_stage == "retention_pending":
            # Run the real retention CLI, failing only its first progress write
            # after the actual unlink; no fake receipt or deletion is supplied.
            hooks = '''$script:retentionFailureCode=@'
import common.contracts.artifact_retention as owner
import msplatform.execution.artifact_retention as canonical_owner
original = canonical_owner.write_json_atomic
def crash(path, value):
    if value.get("status") == "pending" and value.get("removed_file_count") == 1:
        raise OSError("fixture retention progress failure")
    return original(path, value)
canonical_owner.write_json_atomic = crash
owner.main()
'@
$needle=@'
& $Python (Join-Path $RepoRoot 'common\\contracts\\artifact_retention.py') @arguments
'@
$body=${function:Apply-RunArtifactRetention}.ToString().Replace($needle,'& $Python -B -c $script:retentionFailureCode @arguments')
Set-Item Function:Apply-RunArtifactRetention ([scriptblock]::Create($body))
'''
        elif failure_stage == "publication_journal":
            hooks = '''$injection=@'
import msplatform.execution.terminal_publication as publisher_owner
original_write = publisher_owner.write_json_atomic
def crash(path, value):
    original_write(path, value)
    if path.name == "summary.json": raise OSError("fixture after summary publication")
publisher_owner.write_json_atomic = crash

'@
$needle='completion_path, session_path, wait_path = map(Path, sys.argv[1:4])'
$body=${function:Publish-WorkflowTerminal}.ToString().Replace($needle,$injection+"`n"+$needle)
Set-Item Function:Publish-WorkflowTerminal ([scriptblock]::Create($body))
'''
        elif failure_stage == "seal":
            hooks = '''$script:realCapacityCommand=${function:Invoke-RunCapacityCommand}
function Invoke-RunCapacityCommand {
  param($Python,$RepoRoot,$Arguments,$FailureLabel,$StandardInputJson)
  if('seal-stopped-payload'-in$Arguments){throw 'fixture stopped payload seal failure'}
  & $script:realCapacityCommand @PSBoundParameters
}
'''
        elif failure_stage == "release":
            hooks = "function Exit-ArtifactWorkflowCapacitySession { throw 'fixture capacity release failure' }"
        if capacity_trace is not None:
            marker = "from msplatform.execution.capacity_session import create_capacity_session, renew_capacity_session, exit_capacity_session"
            observer = """from msplatform.execution import capacity_session as observed_session
_trace_path = Path(TRACE_PATH)
def _observe_crud(name):
    original = getattr(observed_session.protection, name)
    def invoke(root, *args, **kwargs):
        receipt = original(root, *args, **kwargs)
        row = dict(operation=name, artifact_root=str(Path(root).resolve()),
                   lease_id=kwargs["lease_id"], success=True)
        with _trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\\n")
        return receipt
    setattr(observed_session.protection, name, invoke)
_observe_crud("create_capacity_protection_lease")
_observe_crud("delete_capacity_protection_lease")
""".replace("TRACE_PATH", json.dumps(str(capacity_trace)))
            hooks += f"""
$crudMarker=@'
{marker}
'@
$crudObserver=@'
{observer}
'@
$body=${{function:Invoke-CanonicalCapacitySession}}.ToString()
if(([regex]::Matches($body,[regex]::Escape($crudMarker))).Count-ne1){{throw 'Canonical capacity fixture marker is not unique'}}
$body=$body.Replace($crudMarker,($crudMarker+"`n"+$crudObserver))
Set-Item Function:Invoke-CanonicalCapacitySession ([scriptblock]::Create($body))
"""
        outcome = self.run_ps(root, f""". '{OWNER}'
{state_setup}
{sampler}
Write-RunJson -Path '{root / 'expected_context.json'}' -Value @{{host_resource_state_path=(Resolve-HostResourceStatePath)}}
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
{hooks}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{request_path}' -ResultPath '{result_path}'}}
catch{{Write-Output $_.Exception.Message;exit 7}}
""")
        self.assertTrue(result_path.is_file(), outcome.stdout + outcome.stderr)
        return json.loads(result_path.read_text(encoding="utf-8-sig")), run, artifacts, outcome

    def resume_fixture(self, root: Path, run: Path, *, fail_publication: bool = False,
                       drift_context: bool = False, additional_hooks: str = "") -> tuple[dict, subprocess.CompletedProcess[str]]:
        hook = "function Publish-WorkflowTerminal { throw 'fixture recovery publication failure' }" if fail_publication else ""
        drift = """$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH='changed-relative-state'
$env:MASS_SPECTROMETRY_EXECUTION_ROOT='changed-relative-execution'
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT='changed-relative-payload'""" if drift_context else ""
        outcome = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{
 param($ArtifactRoot,$CapacityProtectionLeaseId)
 $lease=Get-Content -LiteralPath (Join-Path $ArtifactRoot ('common/capacity_protection_leases/'+$CapacityProtectionLeaseId+'.json')) -Raw|ConvertFrom-Json
 return @{{satisfied=$true;fixture_admission=$true;admitted_lease_committed_new_bytes=$lease.committed_new_bytes}}
}}
{hook}
{additional_hooks}
{drift}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{run / 'inputs/execution_request.json'}' -ResultPath '{root / 'result.json'}' -ResumeFinalization}}
catch{{Write-Output $_.Exception.Message;exit 7}}
""")
        return json.loads((root / "result.json").read_text(encoding="utf-8-sig")), outcome

    def _native_source_fixture(self, root: Path, *, deep: bool):
        producer = root / (('source_' + 'x' * 180) if deep else 'source')
        producer.mkdir()
        _, run, artifacts, process = self.invoke_fixture(producer, {})
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        model = run / 'results/science.json'  # Tiny inert input, not an MPH/solve.
        self.assertEqual(len(str(model)) > 259, deep)
        reference = {'manifest_record': file_record(run / 'run_manifest.json'), 'protected_paths': [str(run)]}
        before = {path: path.read_bytes() for path in run.rglob('*') if path.is_file()}
        return run, artifacts, model, reference, before

    def _remove_test_source_aliases(self, root: Path, context: dict) -> None:
        # Test callbacks have actually exited; synthetic unknown-writer evidence
        # must not leave test-only junctions outside TemporaryDirectory cleanup.
        path = root / 'test_alias_cleanup.json'
        path.write_text(json.dumps(context), encoding='utf-8')
        process = self.run_ps(root, f""". '{OWNER}'
$context=Get-Content -Raw '{path}'|ConvertFrom-Json
foreach($source in $context.sources){{if($source.execution_alias){{
 Remove-RunExecutionAlias -ExecutionAlias $source.execution_alias -TargetDirectory $source.target_directory
}}}}
""")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
