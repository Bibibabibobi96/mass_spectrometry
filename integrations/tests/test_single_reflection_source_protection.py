"""Explicit SF source ownership reaches the existing zero-commitment leases."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import run_capacity_lifecycle as lifecycle
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases
from common.contracts.write_run_manifest import build_run_manifest, file_record
from integrations.workflows.single_reflection_flight.continuation import source_capacity_projection


REPO = Path(__file__).resolve().parents[2]
PROPOSAL = REPO


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def source(root, *, legacy=False, status="success"):
    root.mkdir()
    initialize_capacity_ledger(root, objects=[])
    run = root / "projects/fixture/runs/20261030_010000__test__python__source"
    run.mkdir(parents=True)
    config = dict(schema_version=1, project="fixture", mode="fixture", run_id=run.name, inputs={})
    if not legacy:
        config["capacity_ledger_lifecycle"] = dict(schema_version=1, enabled=True,
            artifact_root=str(root), light_evidence_budget_bytes=1024)
    write(run / "run_config.json", config)
    write(run / "run_manifest.json", build_run_manifest(run / "run_config.json", status))
    return run


def owner_overlay(destination):
    """Only the public capacity owner's executable Python dependency closure."""
    pending = ["common/contracts/run_capacity_lifecycle.py", "common/contracts/reconcile_artifact_capacity.py",
               "common/paths/workspace_paths.py"]
    selected = set()
    while pending:
        relative = pending.pop()
        if relative in selected:
            continue
        selected.add(relative)
        source_path = PROPOSAL / relative
        if not source_path.is_file():
            source_path = REPO / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8-sig"))):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [node.module + "." + item.name for item in node.names]
            for name in names:
                path = name.replace(".", "/") + ".py"
                if name.startswith("common.") and (REPO / path).is_file():
                    pending.append(path)
    for relative in ("common/contracts/run_artifact_support.ps1", "common/host_execution_lease.ps1",
                     "common/require_powershell7.ps1", "common/paths/workspace_paths.ps1",
                     "common/contracts/artifact_capacity_policy.json"):
        original = PROPOSAL / relative
        if not original.is_file():
            original = REPO / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)


class SingleReflectionSourceProtectionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows shared source guard required")
    def test_frontend_source_uses_its_actual_root_lease_without_payload_reads_or_native_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original, target = base / "source", base / "target"
            run = source(original)
            target.mkdir()
            initialize_capacity_ledger(target, objects=[])
            key = "a" * 64
            pa = original / "common/simion/pa_family_cache" / key / "generations" / ("b" * 64) / "frontend.pa0"
            pa.parent.mkdir(parents=True)
            pa.write_bytes(b"fixture-only-array")
            pa_record = file_record(pa)
            field = run / "inputs/frontend_working_fields.json"
            write(field, dict(schema_version=3, domains=[dict(domain_id="parent", working_points=[
                dict(pa_record, generation_directory=str(pa.parent), cache_key=key)])]))
            config = json.loads((run / "run_config.json").read_text())
            config["inputs"]["frontend_fields"] = str(field)
            write(run / "run_config.json", config)
            write(run / "run_manifest.json", build_run_manifest(run / "run_config.json", "success"))
            before = (run / "run_manifest.json").read_bytes()
            request = base / "request.json"
            write(request, dict(providers=dict(frontend_fields=file_record(field))))
            original_open = Path.open
            def protected_open(path, *args, **kwargs):
                if path == pa:
                    raise AssertionError("source projection must not read PA bytes")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", protected_open), patch.object(lifecycle, "_inventory", side_effect=AssertionError("no payload inventory")):
                projection = source_capacity_projection(artifact_root=target, request_path=request)
            references = projection["source_references"]
            self.assertEqual(len(references), 1)
            self.assertEqual(references[0]["protected_paths"], [str(pa)])
            self.assertEqual(references[0]["protected_cache_keys"], [key])
            overlay = base / "owner"
            owner_overlay(overlay)
            data = base / "capacity_request.json"
            write(data, dict(target=str(target), references=references))
            check = base / "check.ps1"
            check.write_text(r'''param($Repo,$Python,$Request)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
function Invoke-ArtifactWorkflowCapacityAdmission {return @{satisfied=$true;fixture_admission=$true}}
$data=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -AsHashtable
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $data.target `
 -RunDirectory (Join-Path $data.target 'projects/fixture/runs/new') -CommittedNewBytes 1024 -SourceReferences @($data.references)
if($session.source_protection_leases.Count-ne1){throw 'Source has no independent original-root lease'}
$source=$session.source_protection_leases[0]
$lease=Get-Content -LiteralPath (Join-Path $source.artifact_root ('common/capacity_protection_leases/'+$source.lease_id+'.json')) -Raw|ConvertFrom-Json
if($lease.committed_new_bytes-ne0-or$session.committed_new_bytes-ne1024){throw 'Source became new target payload'}
if($lease.protected_cache_keys.Count-ne1-or$session.protected_cache_keys.Count-ne0){throw 'Source key was pinned under target owner'}
$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(check), str(overlay), sys.executable, str(data)],
                                    cwd=base, capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(before, (run / "run_manifest.json").read_bytes())
            self.assertFalse(load_capacity_protection_leases(original)["protected_paths"])
            self.assertFalse(load_capacity_protection_leases(target)["protected_paths"])

    def test_explicit_lineage_covers_ancestor_artifacts_and_unknown_owner_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ancestor = source(base / "ancestor")
            direct = source(base / "direct")
            target = base / "target"
            target.mkdir()
            artifact = ancestor / "results/finished.stdout.log"
            artifact.parent.mkdir()
            artifact.write_text("complete fixture", encoding="utf-8")
            write(ancestor / "run_manifest.json", build_run_manifest(ancestor / "run_config.json", "success", output_paths=[artifact]))
            frozen = direct / "inputs/continuation_parent_manifest.json"
            frozen.parent.mkdir()
            shutil.copyfile(ancestor / "run_manifest.json", frozen)
            config = json.loads((direct / "run_config.json").read_text())
            config["inputs"].update(continuation_parent_manifest=str(frozen), continuation_artifact_baseline_fixture=str(artifact))
            write(direct / "run_config.json", config)
            write(direct / "run_manifest.json", build_run_manifest(direct / "run_config.json", "success"))
            request = base / "request.json"
            write(request, dict(continuation=dict(predecessor_run_manifest=file_record(direct / "run_manifest.json"))))
            projection = source_capacity_projection(artifact_root=target, request_path=request)
            references = {Path(row["manifest_record"]["path"]).parent: row for row in projection["source_references"]}
            self.assertIn(str(artifact), references[ancestor]["protected_paths"])
            self.assertEqual(references[direct]["protected_paths"], [])
            with self.assertRaisesRegex(ValueError, "not bound by explicit source lineage"):
                source_capacity_projection(artifact_root=target, request_path=request, borrowed_paths=[str(base / "unowned.pa0")])

    def test_source_only_statuses_preserve_superseded_and_require_real_stopped_checkpoint_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = source(base / "source", status="superseded")
            record = file_record(run / "run_manifest.json")
            with patch.object(lifecycle, "_inventory", side_effect=AssertionError("read-only source must not inventory")):
                self.assertEqual(lifecycle.resolve_consumed_run_capacity_owner(record)["run_directory"], str(run))
            self.assertNotIn("superseded", lifecycle.TERMINAL_STATUSES)
            config_path = run / "run_config.json"
            lifecycle.capacity_ledger.record_capacity_object(run.parents[3], path=run, object_class="rebuildable_payload",
                bytes_count=0, status="writing", owner="fixture", retention_reason="fixture", review_deadline="2027-01-01",
                retirement_route="owner_decision_required", recovery_reason="fixture")
            write(run / "run_manifest.json", build_run_manifest(config_path, "checkpoint"))
            stopped = lifecycle.seal_checkpoint(run.parents[3], config_path, owner="fixture", writing_stopped=True,
                retain_payload=True, retention_reason="fixture stopped source")
            stopped_path = base / "stopped.json"
            write(stopped_path, stopped)
            manifest_record = file_record(run / "run_manifest.json")
            stopped_record = file_record(stopped_path)
            with patch.object(lifecycle, "_inventory", side_effect=AssertionError("no source re-inventory")):
                with self.assertRaisesRegex(ValueError, "explicit stopped payload receipt"):
                    lifecycle.resolve_consumed_run_capacity_owner(manifest_record)
                self.assertEqual(lifecycle.resolve_consumed_run_capacity_owner(manifest_record,
                    stopped_receipt_record=stopped_record)["run_directory"], str(run))
                ledger = load_capacity_ledger(run.parents[3])
                ledger["objects"][0]["pin"] = False
                ledger["objects"][0].pop("pin_reason", None)
                write(run.parents[3] / "common/capacity_ledger.json", ledger)
                with self.assertRaisesRegex(ValueError, "actual ready pinned owner range"):
                    lifecycle.resolve_consumed_run_capacity_owner(manifest_record, stopped_receipt_record=stopped_record)
