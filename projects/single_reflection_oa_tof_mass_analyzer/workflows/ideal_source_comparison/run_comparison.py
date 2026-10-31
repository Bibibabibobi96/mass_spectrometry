"""Run both ideal-field comparisons automatically; resume into a new immutable run.

Usage: python -m projects.single_reflection_oa_tof_mass_analyzer.workflows.
ideal_source_comparison.run_comparison --seed 20260827 [--resume-from RUN]
No commercial solver is imported, launched, or required.
"""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import tempfile
from contextlib import contextmanager
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import scipy

from common.paths.workspace_paths import resolve_workspace_paths
from common.contracts.artifact_naming import validate_run_id
from common.analysis.peak_metrics import AnalysisSettings
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication, retention_api
from common.contracts.capacity_protection import renew_capacity_protection_lease, PROTECTION_LEASE_DIRECTORY

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_experiment import (
    build_case_plan, summarize_stage,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison_plot import (
    export_comparison_figures,
)

from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.numerical_case import (
    _run_case, _working_points, _settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
ARTIFACT_ROOT = REPO_ROOT.parent / "artifacts" / "projects" / PROJECT_ROOT.name
DEFAULT_CONFIG = PROJECT_ROOT / "config/experiments/ideal_source_comparison.json"


def _write_json(path: Path, value: Any) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    with pending.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _command(arguments: list[str], *, timeout: float | None = 120) -> str:
    completed = subprocess.run(arguments, cwd=REPO_ROOT, check=False, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f"{arguments[:4]} exit={completed.returncode}: {completed.stdout}\n{completed.stderr}")
    return completed.stdout.strip()


def _inputs(config_path: Path) -> dict[str, Path]:
    local = ["ideal_source_comparison.py", "ideal_source_experiment.py", "ideal_source_comparison_plot.py", "three_zone_ideal_theory.py",
             "oatof_oaaccelerator_coupling.py", "reflectron_dual_stage_solver.py"]
    accelerator = REPO_ROOT / "projects/orthogonal_accelerator/analysis"
    return {"experiment": config_path, "entrypoint": Path(__file__),
            "numerical_case": Path(__file__).with_name("numerical_case.py"),
            "analysis_contract": PROJECT_ROOT / "config/analysis_contract.json",
            "particle_policy": REPO_ROOT / "common/contracts/particle_count_policy.json",
            "peak_metrics": REPO_ROOT / "common/analysis/peak_metrics.py",
            "accelerator_time_focus": accelerator / "accelerator_time_focus.py",
            "accelerator_three_zone_theory": accelerator / "three_zone_ideal_theory.py",
            "accelerator_two_zone_geometry": accelerator / "two_zone_geometry.py",
            **{Path(name).stem: PROJECT_ROOT / "analysis" / name for name in local}}








def _frozen_settings(run_dir: Path) -> AnalysisSettings:
    """Read the once-frozen analysis authority for every supported comparison role."""
    frozen_config = load_json(run_dir / "run_config.json")
    contract = Path(frozen_config["inputs"]["analysis_contract"])
    if file_sha256(contract) != frozen_config["input_sha256"]["analysis_contract"]:
        raise ValueError("frozen analysis contract changed after freezing")
    return _settings(contract)



def _legacy_ideal_parent(previous: Path | None) -> bool:
    if previous is None:
        return False
    config = load_json(previous / "run_config.json")
    return "numerical_case" not in config.get("input_sha256", {}) or "legacy_numerical_projection" in config.get("inputs", {})


@contextmanager
def _legacy_source_protection(previous: Path | None, artifact_root: Path, run_id: str):
    """Pin the explicit old owner through the existing shared-reader capacity API."""
    if not _legacy_ideal_parent(previous):
        yield None
        return
    validate_run_id(run_id)
    manifest = previous / "run_manifest.json"
    if not manifest.is_file():
        raise ValueError("resume source lacks a frozen numerical_case implementation identity and a bound legacy terminal manifest; recover original evidence or recompute cases")
    artifact_root = artifact_root.resolve()
    execution_context = resolve_workspace_paths(REPO_ROOT)
    consumer_root = Path(execution_context["artifact_root"])
    managed_project = consumer_root / "projects" / PROJECT_ROOT.name
    if artifact_root != managed_project:
        raise ValueError("legacy reference recovery requires the selected managed project artifact root; "
                         "configure MASS_SPECTROMETRY_ARTIFACT_ROOT and select its projects/" + PROJECT_ROOT.name +
                         " target, or start a new comparison without legacy reuse")
    future_run = artifact_root / "runs" / run_id
    support = REPO_ROOT / "common/contracts/run_artifact_support.ps1"
    parent_config = load_json(previous / "run_config.json")
    original_owner = previous.resolve()
    references = [{"manifest_record": file_record(manifest), "protected_paths": [str(previous.resolve())], "protected_cache_keys": []}]
    if "legacy_numerical_projection" in parent_config.get("inputs", {}):
        proof_path = Path(parent_config["inputs"]["legacy_numerical_projection"])
        if (not proof_path.resolve().is_relative_to(previous.resolve())
                or file_sha256(proof_path) != parent_config["input_sha256"]["legacy_numerical_projection"]):
            raise ValueError("derived legacy source proof is missing or changed")
        proof = load_json(proof_path)
        if proof.get("role") != "ideal_source_legacy_numerical_projection":
            raise ValueError("unsupported derived legacy numerical source")
        original_owner = Path(proof["original_owner"]).resolve(strict=True)
        reference = proof["source_reference"]
        if Path(reference["manifest_record"]["path"]).resolve() != original_owner / "run_manifest.json":
            raise ValueError("derived legacy source does not bind its original owner")
        references.append(reference)
    else:
        reference = references[0]
    with tempfile.TemporaryDirectory(prefix="ideal_source_pin_") as temporary:
        request_path, session_path = Path(temporary) / "request.json", Path(temporary) / "session.json"
        request_path.write_text(json.dumps({"root": str(consumer_root), "run": str(future_run), "references": references}), encoding="utf-8")
        quoted = lambda path: "'" + str(path).replace("'", "''") + "'"
        bootstrap = "$env:SIMULATION_PYTHON_EXE=" + quoted(sys.executable) + "; "
        for field, variable in (("artifact_root", "MASS_SPECTROMETRY_ARTIFACT_ROOT"),
                                ("execution_root", "MASS_SPECTROMETRY_EXECUTION_ROOT"),
                                ("host_resource_state_path", "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH")):
            bootstrap += "$env:" + variable + "=" + quoted(execution_context[field]) + "; "
        bootstrap += ". " + quoted(support) + "; "
        command = bootstrap + "$d=Get-Content -Raw -Encoding UTF8 " + quoted(request_path) + "|ConvertFrom-Json -AsHashtable; $s=Enter-ArtifactWorkflowCapacitySession -Python " + quoted(sys.executable) + " -RepoRoot " + quoted(REPO_ROOT) + " -ArtifactRoot $d.root -RunDirectory $d.run -CommittedNewBytes 0 -SourceReferences @($d.references); try { Write-RunJson -Depth 64 -Path " + quoted(session_path) + " -Value $s } catch { $primary=$_; try { Exit-ArtifactWorkflowCapacitySession -Python " + quoted(sys.executable) + " -RepoRoot " + quoted(REPO_ROOT) + " -Session $s|Out-Null } catch { Write-Warning ('Source protection rollback also failed: '+$_.Exception.Message) }; throw $primary }"
        _command(["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", command], timeout=None)
        session = load_json(session_path)
        primary = None
        try:
            yield {"session": session, "execution_context": execution_context, "source_reference": reference, "source_references": references,
                   "original_owner": str(original_owner)}
        except BaseException as error:
            primary = error
            raise
        finally:
            session_path.write_text(json.dumps(session), encoding="utf-8")
            command = bootstrap + "$s=Get-Content -Raw -Encoding UTF8 " + quoted(session_path) + "|ConvertFrom-Json; Exit-ArtifactWorkflowCapacitySession -Python " + quoted(sys.executable) + " -RepoRoot " + quoted(REPO_ROOT) + " -Session $s|Out-Null"
            try:
                _command(["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", command], timeout=None)
            except Exception as cleanup:
                # Keep the actual session for the existing capacity owner. Never
                # silently claim release or hide the primary scientific error.
                evidence = artifact_root / "scratch/workflow_results" / run_id / "source_protection.json"
                evidence.parent.mkdir(parents=True, exist_ok=True)
                prior_summary = load_json(future_run / "summary.json") if (future_run / "summary.json").is_file() else None
                _write_json(evidence, {"session": session, "source_reference": reference,
                    "status": "release_failed", "error": str(cleanup), "original_workflow_failure": prior_summary if prior_summary and prior_summary.get("status") != "success" else None,
                    "next_action": "release the recorded session through Exit-ArtifactWorkflowCapacitySession"})
                if primary is not None:
                    primary.add_note(f"source protection release also failed: {cleanup}; session={evidence}")
                else:
                    original_failure = prior_summary.get("failure_reason") if prior_summary and prior_summary.get("status") != "success" else None
                    raise RuntimeError(f"{('original workflow failure: ' + str(original_failure) + '; ') if original_failure else ''}source protection release failed; session={evidence}") from cleanup


def _renew_legacy_source(protection: dict[str, Any]) -> None:
    session = protection["session"]
    ttl = session["lease_ttl_seconds"]
    for item in [session, *session.get("source_protection_leases", [])]:
        path = Path(item["artifact_root"]) / PROTECTION_LEASE_DIRECTORY / (item["lease_id"] + ".json")
        lease = load_json(path)
        expiry = datetime.fromisoformat(lease["expires_at_utc"].replace("Z", "+00:00"))
        if expiry.timestamp() - time.time() <= ttl / 2:
            renewed = renew_capacity_protection_lease(Path(item["artifact_root"]), lease_id=item["lease_id"],
                owner=session["owner"], ttl_seconds=ttl, protected_paths=[Path(item["artifact_root"]) / value for value in lease["protected_paths"]],
                protected_cache_keys=lease["protected_cache_keys"], committed_new_bytes=0)
            if item is session:
                session["lease"] = renewed


def _legacy_ideal_binding(previous: Path, path: Path, manifest: dict[str, Any], label: str, *, verify: bool = True) -> dict[str, Any]:
    path = path.resolve(strict=True)
    if not path.is_relative_to(previous):
        raise ValueError(f"legacy {label} escapes its original owner")
    records = [manifest["run_config"], *manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
    matches = [item for item in records if Path(item["path"]).resolve() == path]
    if not matches or len({(item.get("bytes"), item.get("sha256")) for item in matches}) != 1:
        raise ValueError(f"legacy {label} lacks its original manifest binding")
    if manifest.get("schema_version") == 2:
        classify = retention_api()[0]
        for record in manifest.get("outputs", []):
            if Path(record["path"]).resolve() == path and record.get("retention_role") != classify(path, bytes_count=int(record["bytes"])):
                raise ValueError(f"legacy {label} retained output role differs")
    if verify:
        verify_record("legacy " + label, matches[0])
    return matches[0]


def _legacy_ideal_projection(previous: Path, identities: dict[str, str], seed: int,
                             mode: str, protection: dict[str, Any]) -> dict[str, Any]:
    """Prove one old basic producer, its environment and full scientific inputs."""
    require_completed_terminal_publication(previous / "run_manifest.json")
    verify_record("protected original manifest", protection["source_reference"]["manifest_record"])
    manifest = load_json(previous / "run_manifest.json")
    parent = load_json(previous / "run_config.json")
    if (manifest.get("schema_version") not in (1, 2) or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("status") not in {"success", "failed"} or manifest.get("lifecycle_state") == "provisional"
            or parent.get("schema_version") != 2 or parent.get("mode") != "ideal_source_comparison"
            or mode != "ideal_source_comparison" or parent.get("project") != PROJECT_ROOT.name
            or parent.get("run_id") != previous.name or manifest.get("run_id") != previous.name
            or manifest.get("project") != parent["project"] or manifest.get("mode") != parent["mode"]):
        raise ValueError("legacy resume supports only a completed original basic ideal-source producer")
    _legacy_ideal_binding(previous, previous / "run_config.json", manifest, "run config")
    if manifest["schema_version"] == 2:
        retention = retention_api()[3](parent.get("artifact_retention"))
        expected = {"policy_version": retention.policy_version, "class": retention.class_id, "reason": retention.reason}
        if manifest.get("artifact_retention") != expected:
            raise ValueError("legacy v2 retention contract differs from original config")
    summary = load_json(previous / "summary.json")
    _legacy_ideal_binding(previous, previous / "summary.json", manifest, "summary")
    if (summary.get("status") != manifest["status"] or summary.get("role") != "ideal_source_comparison_summary"
            or type(summary.get("completed_cases")) is not int or type(summary.get("planned_cases")) is not int
            or not 0 <= summary["completed_cases"] <= summary["planned_cases"]):
        raise ValueError("legacy producer summary/terminal case facts differ")
    expected_roles = set(identities) - {"numerical_case"}
    if set(parent.get("inputs", {})) != expected_roles or set(parent.get("input_sha256", {})) != expected_roles:
        raise ValueError("legacy frozen scientific input role set is incomplete or unsupported")
    for name, value in parent["inputs"].items():
        path = Path(value)
        record = _legacy_ideal_binding(previous, path, manifest, "input " + name)
        if record["sha256"] != parent["input_sha256"][name].upper():
            raise ValueError(f"legacy frozen input identity differs: {name}")
        if name not in {"entrypoint", "ideal_source_comparison_plot"} and parent["input_sha256"][name] != identities[name]:
            raise ValueError(f"legacy scientific input changed: {name}; recompute affected cases")
    environment = {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}
    original_identity = _digest({"inputs": parent["input_sha256"], "seed": seed, **environment})
    if parent.get("run_instance", {}).get("seed") != seed or parent.get("numerical_identity") != original_identity:
        raise ValueError("legacy original identity cannot prove the requested seed/environment; recover original environment or recompute cases")
    source = Path(parent["inputs"]["entrypoint"]).read_text(encoding="utf-8")
    numerical = Path(__file__).with_name("numerical_case.py").read_text(encoding="utf-8")
    def function(text, name):
        found = [node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name == name]
        if len(found) != 1 or found[0].decorator_list:
            raise ValueError(f"legacy basic producer lacks its unique {name}")
        return found[0]
    def equal(left, right, label):
        if ast.dump(left, include_attributes=False) != ast.dump(right, include_attributes=False):
            raise ValueError(f"legacy scientific producer differs: {label}; recompute affected cases")
    for name in ("_working_points", "_run_case"):
        equal(function(source, name), function(numerical, name), name)
    expected_settings = copy.deepcopy(function(numerical, "_settings"))
    expected_settings.args.args = []
    expected_settings.body[0] = ast.parse('kde = load_json(PROJECT_ROOT / "config/analysis_contract.json")["kde"]').body[0]
    equal(function(source, "_settings"), expected_settings, "frozen-contract settings mapping")
    equal(function(source, "_digest"), function(Path(__file__).read_text(encoding="utf-8"), "_digest"), "original identity constructor")
    current_source = Path(__file__).read_text(encoding="utf-8")
    class KnownOldDispatch(ast.NodeTransformer):
        def visit_With(self, node):
            if len(node.items) == 1 and isinstance(node.items[0].context_expr, ast.Call) and isinstance(node.items[0].context_expr.func, ast.Name) and node.items[0].context_expr.func.id == "_legacy_source_protection":
                return [self.visit(item) for item in node.body]
            return self.generic_visit(node)
        def visit_If(self, node):
            if isinstance(node.test, ast.Name) and node.test.id == "protection" and len(node.body) == 1 and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Call) and isinstance(node.body[0].value.func, ast.Name) and node.body[0].value.func.id == "_renew_legacy_source":
                return None
            return self.generic_visit(node)
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "_frozen_settings":
                return ast.Call(func=ast.Name(id="_settings", ctx=ast.Load()), args=[], keywords=[])
            if isinstance(node.func, ast.Name) and node.func.id == "_prepare_run":
                node.keywords = [keyword for keyword in node.keywords if keyword.arg != "legacy_source_protection"]
            return node
    expected_execute = KnownOldDispatch().visit(copy.deepcopy(function(current_source, "execute")))
    equal(function(source, "execute"), expected_execute, "complete original execution dispatch")
    for name in ("_write_json", "_publish_manifest", "_write_report", "main"):
        equal(function(source, name), function(current_source, name), name)
    expected_command = copy.deepcopy(function(current_source, "_command"))
    expected_command.args.kwonlyargs = []
    expected_command.args.kw_defaults = []
    for node in ast.walk(expected_command):
        if isinstance(node, ast.keyword) and node.arg == "timeout":
            node.value = ast.Constant(value=120)
    equal(function(source, "_command"), expected_command, "original synchronous process transport")
    expected_inputs = copy.deepcopy(function(current_source, "_inputs"))
    for node in ast.walk(expected_inputs):
        if isinstance(node, ast.Dict):
            retained = [(key, value) for key, value in zip(node.keys, node.values)
                        if not (isinstance(key, ast.Constant) and key.value == "numerical_case")]
            node.keys, node.values = [item[0] for item in retained], [item[1] for item in retained]
    equal(function(source, "_inputs"), expected_inputs, "complete original input role constructor")
    expected_reuse = copy.deepcopy(function(current_source, "_reuse_case"))
    expected_reuse.body = [node for node in expected_reuse.body if not (
        isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_reuse_legacy_ideal_case") and not (
        isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "projected")]
    equal(function(source, "_reuse_case"), expected_reuse, "original checkpoint reader")
    expected_prepare = copy.deepcopy(function(current_source, "_prepare_run"))
    parameters = [(arg, value) for arg, value in zip(expected_prepare.args.kwonlyargs, expected_prepare.args.kw_defaults)
                  if arg.arg != "legacy_source_protection"]
    expected_prepare.args.kwonlyargs = [item[0] for item in parameters]
    expected_prepare.args.kw_defaults = [item[1] for item in parameters]
    old_resume = ast.parse('if resume_from is not None:\n    resume_from = resume_from.resolve()\n    previous = load_json(resume_from / "run_config.json")\n    if previous["numerical_identity"] != identity:\n        raise ValueError("resume code/config/seed/environment differs; start a new comparison without --resume-from")\n    for name, path in previous["inputs"].items():\n        if file_sha256(Path(path)) != previous["input_sha256"][name]:\n            raise ValueError(f"resume frozen input changed: {name}")\n').body[0]
    prepared_body = []
    for node in expected_prepare.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"numerical_inputs", "projection"}:
            continue
        if isinstance(node, ast.If):
            if any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "_legacy_ideal_parent" for item in ast.walk(node.test)):
                continue
            if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == "projection":
                continue
            if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == "resume_from":
                node = copy.deepcopy(old_resume)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "identity":
            for dictionary in ast.walk(node):
                if isinstance(dictionary, ast.Dict):
                    for index, key in enumerate(dictionary.keys):
                        if isinstance(key, ast.Constant) and key.value == "inputs":
                            dictionary.values[index] = ast.Name(id="identities", ctx=ast.Load())
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "_write_json":
            dictionary = node.value.args[1]
            kept = [(key, value) for key, value in zip(dictionary.keys, dictionary.values)
                    if key is not None and not (isinstance(key, ast.Constant) and key.value == "numerical_input_sha256")]
            dictionary.keys, dictionary.values = [item[0] for item in kept], [item[1] for item in kept]
        prepared_body.append(node)
    expected_prepare.body = prepared_body
    equal(function(source, "_prepare_run"), expected_prepare, "complete original freeze/identity constructor")
    known_functions = {"_write_json", "_digest", "_command", "_inputs", "_settings", "_working_points", "_run_case",
                       "_reuse_case", "_publish_manifest", "_write_report", "_prepare_run", "execute", "main"}
    if {node.name for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)} != known_functions:
        raise ValueError("unsupported original producer function set")
    if not any(isinstance(node, ast.ImportFrom) and node.module == "__future__" and any(alias.name == "annotations" for alias in node.names) for node in ast.parse(source).body):
        raise ValueError("unsupported original annotation evaluation mode")
    numerical_imports = {}
    for tree in (ast.parse(current_source), ast.parse(numerical)):
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    numerical_imports[alias.asname or alias.name.split(".")[0]] = (None, alias.name, 0)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    numerical_imports[alias.asname or alias.name] = (node.module, alias.name, node.level)
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                binding = alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                expected = (None, alias.name, 0) if isinstance(node, ast.Import) else (node.module, alias.name, node.level)
                if numerical_imports.get(binding) != expected:
                    raise ValueError(f"legacy numerical imported authority differs: {binding}")
        elif isinstance(node, ast.Assign):
            matches = [item for item in ast.parse(current_source).body if isinstance(item, ast.Assign)
                       and ast.dump(item.targets[0]) == ast.dump(node.targets[0])]
            if len(matches) != 1:
                raise ValueError("unsupported original numerical import-time assignment")
            equal(node, matches[0], "original import-time authority")
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list or (node.name in numerical_imports and node.name not in {"_settings", "_working_points", "_run_case"}):
                raise ValueError("unsupported original numerical import-time function binding")
        elif isinstance(node, ast.If):
            expected_guard = next(item for item in ast.parse(current_source).body if isinstance(item, ast.If))
            equal(node, expected_guard, "original CLI guard")
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            raise ValueError("unsupported original numerical import-time execution")
    return {"schema_version": 1, "role": "ideal_source_legacy_numerical_projection",
            "original_owner": str(previous), "original_identity": original_identity,
            "original_manifest": file_record(previous / "run_manifest.json"),
            "original_source": file_record(Path(parent["inputs"]["entrypoint"])),
            "source_witness_semantics": "original producer bytes inspected for equivalence; never imported or executed in this child",
            "original_input_sha256": parent["input_sha256"], "verified_environment": environment,
            "actual_modern_numerical_input_sha256": {name: value for name, value in identities.items()
                if name not in {"entrypoint", "ideal_source_comparison_plot"}},
            "source_reference": protection["source_reference"], "execution_context": protection["execution_context"],
            "settings_proof": "every reused checkpoint is rechecked against its bound raw CSV with frozen Settings; no claim that legacy live-path reads were frozen"}


def _legacy_csv_analysis(previous: Path, document: dict[str, Any], config: dict[str, Any], settings: AnalysisSettings) -> None:
    """Verify old analysis from its original full-mother CSV, without resampling."""
    from collections import Counter
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import _peak_summary
    path = previous / "results" / document["particles"]["path"]
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    count = config["sampling"]["particle_count"]
    if [int(row["particle_id"]) for row in rows] != list(range(1, count + 1)):
        raise ValueError("legacy CSV does not preserve the original complete particle IDs")
    for row in rows:
        if not np.isfinite(float(row["source_x_mm"])) or not np.isfinite(float(row["source_velocity_m_per_s"])):
            raise ValueError("legacy source state is incomplete or nonfinite")
    for name, arm in document["arms"].items():
        counts = dict(sorted(Counter(row[name + "__classification"] for row in rows).items()))
        arrivals = [row for row in rows if row[name + "__classification"] == "detector_arrival"]
        if counts != arm["classification_counts"] or arm["mother_particle_count"] != count or arm["axial_model_reachability_fraction"] != len(arrivals) / count or arm["full_cohort_reachable"] != (len(arrivals) == count):
            raise ValueError("legacy CSV classification/mother cohort differs from checkpoint")
        times = np.asarray([float(row[name + "__tof_us"]) for row in arrivals])
        if not np.all(np.isfinite(times)) or any(row[name + "__tof_us"] for row in rows if row[name + "__classification"] != "detector_arrival"):
            raise ValueError("legacy CSV has contradictory arrival state")
        recalculated = _peak_summary(times, config["source"]["mass_to_charge_th"], settings)
        if any(arm.get(key) != value for key, value in recalculated.items()):
            raise ValueError("legacy raw CSV cannot reproduce checkpoint metrics with its frozen analysis contract; reanalyze the retained CSV")
        metrics = recalculated.get("peak_metrics") or {}
        if arm["resolution"] != metrics.get("mass_resolution") or arm["fwhm_ns"] != metrics.get("direct_fwhm_tof_ns"):
            raise ValueError("legacy checkpoint summary metrics differ from raw CSV")

def _reuse_case(previous: Path | None, case: dict[str, Any], identity: str, destination: Path) -> dict[str, Any] | None:
    if previous is None:
        return None
    projected = _reuse_legacy_ideal_case(previous, case, identity, destination)
    if projected is not None:
        return projected
    path = previous / "results" / f"{case['case_id']}.json"
    if not path.is_file():
        return None
    document = load_json(path)
    if document["identity"] != identity or document["case"] != case or document["record_sha256"] != _digest({k: v for k, v in document.items() if k != "record_sha256"}):
        raise ValueError(f"checkpoint identity/content mismatch: {path}")
    record = document["particles"]
    if Path(record["path"]).name != record["path"]:
        raise ValueError("checkpoint particle file must be local to results")
    verify_record("checkpoint particles", record, base_dir=path.parent)
    shutil.copy2(path.parent / record["path"], destination / record["path"])
    shutil.copy2(path, destination / path.name)
    return document



def _reuse_legacy_ideal_case(previous: Path, case: dict[str, Any], identity: str, destination: Path) -> dict[str, Any] | None:
    config_path = destination.parent / "run_config.json"
    child_config = load_json(config_path)
    proof_value = child_config.get("inputs", {}).get("legacy_numerical_projection")
    if not proof_value:
        return None
    proof = load_json(Path(proof_value))
    original = Path(proof["original_owner"])
    path = original / "results" / f"{case['case_id']}.json"
    if not path.is_file():
        return None
    manifest = load_json(original / "run_manifest.json")
    _legacy_ideal_binding(original, path, manifest, "case checkpoint")
    document = load_json(path)
    if (document.get("identity") != proof["original_identity"] or document.get("case") != case
            or document.get("record_sha256") != _digest({key: value for key, value in document.items() if key != "record_sha256"})):
        raise ValueError("legacy checkpoint identity/case/content mismatch")
    relative_csv = document["particles"]["path"]
    if Path(relative_csv).name != relative_csv:
        raise ValueError("original legacy particle file must be local to original results")
    csv_path = path.parent / relative_csv
    record = _legacy_ideal_binding(original, csv_path, manifest, "case CSV", verify=False)
    if (record["bytes"], record["sha256"]) != (document["particles"]["bytes"], document["particles"]["sha256"]):
        raise ValueError("legacy checkpoint CSV and original manifest identity differ")
    verify_record("legacy checkpoint CSV", document["particles"], base_dir=path.parent)
    frozen_experiment = load_json(Path(child_config["inputs"]["experiment"]))
    _legacy_csv_analysis(original, document, frozen_experiment, _frozen_settings(destination.parent))
    # Canonical state/events remain the original complete CSV. No row is
    # resampled, renumbered, copied, filtered or rewritten in this child.
    derived = {**document, "identity": identity,
        "particles": {**document["particles"], "path": str(csv_path.resolve())},
        "derived_from": {"original_identity": proof["original_identity"], "checkpoint": file_record(path),
                         "original_csv": record, "source_owner": str(original)}}
    derived.pop("record_sha256")
    derived["record_sha256"] = _digest(derived)
    _write_json(destination / path.name, derived)
    input_name = "legacy_case_csv_" + case["case_id"]
    child_config["inputs"][input_name] = str(csv_path.resolve())
    child_config["input_sha256"][input_name] = document["particles"]["sha256"]
    child_config.setdefault("legacy_external_case_inputs", {})[case["case_id"]] = input_name
    _write_json(config_path, child_config)
    return derived

def _publish_manifest(run_dir: Path, status: str) -> None:
    command = [sys.executable, "-m", "common.contracts.write_run_manifest", "--run-config", str(run_dir / "run_config.json"), "--status", status, "--software", f"Python {platform.python_version()}; NumPy {np.__version__}; SciPy {scipy.__version__}"]
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name not in {"run_config.json", "run_manifest.json"}:
            # Writer resolves outputs against run_config's parent. Relative paths
            # keep Windows CreateProcess below its command-line length limit.
            command.extend(["--output", path.relative_to(run_dir).as_posix()])
    print(_command(command), flush=True)
    print(_command([sys.executable, "-m", "common.contracts.verify_run_manifest", str(run_dir / "run_manifest.json"), "--require-status", status]), flush=True)


def _write_report(run_dir: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = ["# Ideal-field source comparison", "", f"Execution: {summary['status']}; elapsed {summary['elapsed_s']:.2f} s.", "", "Scope: synthetic axial sources, pulse-relative exact TOF, fixed geometry. Only mirror voltages change in the residual comparison. No 3D, physical transmission or global optimum claim.", ""]
    for result in summary["stages"]:
        lines.extend([f"## {result['stage']}", "", f"{result['scientific_status']}: {result['reason']}", ""])
        if "acceptance" in result:
            lines.extend(["|Residual (m/s)|Setting|Contiguous tested width (mm)|First failing width (mm)|", "|---:|---|---:|---:|"])
            for item in result["acceptance"]:
                lines.append(f"|{item['residual_sigma_m_per_s']}|{item['arm']}|{item['contiguous_tested_accepted_width_mm']}|{item['first_failing_width_mm']}|")
            lines.append("")
    lines.extend(["## Every case (all seeds, no selected best run)", "", "|Stage|Width (mm)|Residual (m/s)|Seed|Setting|R|FWHM (ns)|Model arrivals|", "|---|---:|---:|---:|---|---:|---:|---:|"])
    for record in records:
        case = record["case"]
        for name, arm in record["arms"].items():
            lines.append(f"|{case['stage']}|{case['full_width_mm']}|{case['residual_sigma_m_per_s']}|{case['seed']}|{name}|{arm['resolution']}|{arm['fwhm_ns']}|{arm['model_arrival_fraction']}|")
    if summary["failure_reason"]:
        lines.extend(["", "## Failure", "", f"{summary['failure_stage']}: {summary['failure_reason']}"])
    (run_dir / "results/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prepare_run(config_path: Path, *, seed: int, run_id: str, resume_from: Path | None,
                 artifact_root: Path, extra_inputs: dict[str, Path] | None = None,
                 mode: str = "ideal_source_comparison", legacy_source_protection: dict[str, Any] | None = None) -> tuple[Path, str]:
    """Shared immutable input freeze for ideal-source analysis modes."""
    validate_run_id(run_id)
    if _legacy_ideal_parent(resume_from) and legacy_source_protection is None:
        with _legacy_source_protection(resume_from, artifact_root, run_id) as protection:
            return _prepare_run(config_path, seed=seed, run_id=run_id, resume_from=resume_from,
                artifact_root=artifact_root, extra_inputs=extra_inputs, mode=mode, legacy_source_protection=protection)
    config_path = config_path.resolve()
    config = load_json(config_path)
    inputs = {**_inputs(config_path), **(extra_inputs or {})}
    identities = {name: file_sha256(path) for name, path in inputs.items()}
    numerical_inputs = {name: value for name, value in identities.items()
                        if name not in {"entrypoint", "ideal_source_comparison_plot"}}
    identity = _digest({"inputs": numerical_inputs, "seed": seed, "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__})
    projection = None
    if resume_from is not None:
        resume_from = resume_from.resolve()
        previous = load_json(resume_from / "run_config.json")
        if _legacy_ideal_parent(resume_from):
            if legacy_source_protection is None:
                raise ValueError("legacy source protection is unavailable")
            projection = _legacy_ideal_projection(Path(legacy_source_protection["original_owner"]), identities, seed, mode, legacy_source_protection)
            if "numerical_case" in previous.get("input_sha256", {}) and previous.get("numerical_identity") != identity:
                raise ValueError("derived legacy numerical code/config/seed/environment differs")
        elif previous["numerical_identity"] != identity:
            raise ValueError("resume code/config/seed/environment differs; start a new comparison without --resume-from")
        external = set(previous.get("legacy_external_case_inputs", {}).values()) if projection else set()
        for name, path in previous["inputs"].items():
            if name in external:
                continue  # Verified once against original manifest/CSV by the selected case reader.
            if file_sha256(Path(path)) != previous["input_sha256"][name]:
                raise ValueError(f"resume frozen input changed: {name}")
    run_dir = artifact_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    for name in ("inputs", "results", "logs"):
        (run_dir / name).mkdir()
    frozen = {}
    for name, path in inputs.items():
        destination = run_dir / "inputs" / (name + path.suffix)
        shutil.copy2(path, destination)
        if file_sha256(destination) != identities[name]:
            raise ValueError(f"input changed during freeze: {name}")
        frozen[name] = str(destination.resolve())
    if projection is not None:
        original = Path(projection["original_owner"])
        for name, source in (("legacy_original_entrypoint", Path(projection["original_source"]["path"])),
                             ("legacy_original_manifest", original / "run_manifest.json")):
            destination = run_dir / "inputs" / (name + source.suffix)
            shutil.copy2(source, destination)
            frozen[name] = str(destination.resolve())
            identities[name] = file_sha256(destination)
        projection["original_source_witness"] = file_record(Path(frozen["legacy_original_entrypoint"]))
        proof_path = run_dir / "inputs/legacy_numerical_projection.json"
        _write_json(proof_path, projection)
        frozen["legacy_numerical_projection"] = str(proof_path)
        identities["legacy_numerical_projection"] = file_sha256(proof_path)
    _write_json(run_dir / "run_config.json", {"schema_version": 2, "run_id": run_id,
                "project": PROJECT_ROOT.name, "mode": mode, "inputs": frozen,
                "input_sha256": identities, "numerical_input_sha256": numerical_inputs, "numerical_identity": identity,
                # Execution provenance is deliberately outside numerical/resume identity.
                "execution_source_sha256": {
                    name: file_sha256(REPO_ROOT / "common" / name)
                    for name in ("host_resource_python.py", "host_resource_python.ps1",
                                 "host_execution_lease.ps1", "host_resource_scheduler.py", "host_resource_policy.json")
                },
                "git_head": _command(["git", "rev-parse", "HEAD"]),
                "git_worktree_status": _command(["git", "status", "--short"]),
                "run_instance": {"seed": seed, "resume_from": str(resume_from) if resume_from else None},
                **({"source_references": legacy_source_protection["source_references"],
                    "paths": legacy_source_protection["execution_context"]} if projection else {}),
                "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
                "formal_gate_passed": False, "claim_scope": config["scope"]})
    return run_dir, identity


def execute(config_path: Path, *, seed: int, run_id: str, resume_from: Path | None = None,
            artifact_root: Path = ARTIFACT_ROOT, max_workers: int | None = None) -> Path:
    """Execute the selected ideal analysis with frozen inputs and terminal evidence.

Resume verifies identical code/config/environment and copies completed cases into
a new run. It never edits or finalizes a previous run, including crash leftovers.
"""
    config_path = config_path.resolve()
    config = load_json(config_path)
    if config.get("role") == "ideal_acceptance_theory":
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.acceptance_theory import execute_theory
        return execute_theory(config_path, seed=seed, run_id=run_id, resume_from=resume_from,
                              artifact_root=artifact_root, max_workers=max_workers)
    if config.get("role") == "ideal_source_slope_scan":
        if max_workers is not None:
            raise ValueError("max workers is unsupported by ideal_source_slope_scan")
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.slope_scan import execute_slope_scan
        return execute_slope_scan(config_path, seed=seed, run_id=run_id, resume_from=resume_from,
                                  artifact_root=artifact_root)
    if max_workers is not None:
        raise ValueError("max workers is supported only by ideal_acceptance_theory runs")
    with _legacy_source_protection(resume_from, artifact_root, run_id) as protection:
        plan = build_case_plan(config, seed)
        run_dir, identity = _prepare_run(config_path, seed=seed, run_id=run_id,
                                        resume_from=resume_from, artifact_root=artifact_root, legacy_source_protection=protection)
        started = time.perf_counter()
        records: list[dict[str, Any]] = []
        stages: list[dict[str, Any]] = []
        stage, reused, error, current_case = "working_points", 0, None, None
        status = "success"
        try:
            points, settings = _working_points(config), _frozen_settings(run_dir)
            _write_json(run_dir / "results/working_points.json", {k: v.to_dict() for k, v in points.items()})
            for stage in ("residual_scan", "width_scan"):
                print(f"IDEAL_COMPARISON STAGE={stage} EVENT=START", flush=True)
                for case in (c for c in plan if c["stage"] == stage):
                    stage = case["stage"]
                    current_case = case["case_id"]
                    if protection:
                        _renew_legacy_source(protection)
                    record = _reuse_case(resume_from, case, identity, run_dir / "results")
                    if record is None:
                        record = _run_case(case, config, points, settings, run_dir / "results")
                        record["identity"] = identity
                        record["record_sha256"] = _digest(record)
                        _write_json(run_dir / "results" / f"{case['case_id']}.json", record)
                    else:
                        reused += 1
                    records.append(record)
                    print(f"IDEAL_COMPARISON CASE={case['case_id']} EVENT=COMPLETE DONE={len(records)}/{len(plan)} REUSED={reused}", flush=True)
                conclusion = summarize_stage(stage, [r for r in records if r["case"]["stage"] == stage], config)
                stages.append(conclusion)
                _write_json(run_dir / "results" / f"{stage}__summary.json", conclusion)
                print(f"IDEAL_COMPARISON STAGE={stage} SCIENTIFIC_STATUS={conclusion['scientific_status']} REASON={conclusion['reason']}", flush=True)
                current_case = None
            stage = "figures"
            export_comparison_figures(records, config, run_dir / "results")
        except (Exception, KeyboardInterrupt) as exc:
            status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            error = f"{type(exc).__name__}: {exc}"
            (run_dir / "logs/failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        summary = {"schema_version": 1, "role": "ideal_source_comparison_summary", "status": status,
                   "stages": stages, "completed_cases": len(records), "planned_cases": len(plan), "reused_cases": reused,
                   "failure_stage": stage if error else None, "failure_reason": error,
                   "failure_case_id": current_case if error else None,
                   "elapsed_s": time.perf_counter() - started, "formal_gate_passed": False,
                   "next_action": "inspect stage conclusions" if status == "success" else "inspect failure.log; fix inputs/code if needed; resume unchanged cases only into a new run"}
        _write_json(run_dir / "summary.json", summary)
        _write_report(run_dir, records, summary)
        try:
            _publish_manifest(run_dir, status)
        except Exception as exc:
            summary.update(status="failed", failure_stage="manifest_publication",
                           failure_reason=f"{type(exc).__name__}: {exc}",
                           next_action="repair publication; completed case checkpoints remain available")
            _write_json(run_dir / "summary.json", summary)
            (run_dir / "logs/failure.log").write_text(traceback.format_exc(), encoding="utf-8")
            _write_report(run_dir, records, summary)
            raise
        print(f"IDEAL_COMPARISON STATUS={status} COMPLETED={len(records)}/{len(plan)} ELAPSED_S={summary['elapsed_s']:.2f} RUN={run_dir} REASON={error or 'both scans completed'}", flush=True)
        return run_dir


def main(argv: list[str] | None = None) -> int:
    """Single public CLI; no stage-by-stage manual continuation is required."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--max-workers", type=int,
                        help="Theory-only process-pool cap; does not change frozen science inputs.")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.plan:
            config = load_json(args.config)
            if config.get("role") == "ideal_acceptance_theory":
                from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.acceptance_theory import validate_theory_config
                validate_theory_config(config)
                plan = config
            elif config.get("role") == "ideal_source_slope_scan":
                from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.slope_scan import validate_slope_scan_config
                validate_slope_scan_config(config)
                plan = config
            else:
                plan = build_case_plan(config, args.seed)
            print(json.dumps(plan, indent=2))
            return 0
        from common.host_resource_python import ensure_heavy_entry

        ensure_heavy_entry(
            "projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison", argv,
        )
        run_id = args.run_id or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S__analysis__python__ideal-source-comparison")
        run_dir = execute(args.config, seed=args.seed, run_id=run_id,
                          resume_from=args.resume_from, max_workers=args.max_workers)
        return 0 if load_json(run_dir / "summary.json")["status"] == "success" else 1
    except Exception as exc:
        print(f"IDEAL_COMPARISON STATUS=failed REASON={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
