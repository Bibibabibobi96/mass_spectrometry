"""Explicit solver-free OA-TOF comparisons with the sole installed run owner.

Author paths are resolved once by the parent. Scientific workers consume only
bound frozen records; they do not create runs or publish terminal manifests.
"""
from __future__ import annotations

import argparse
import ast
import copy
import csv
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import scipy

from msplatform.analysis.peak_metrics import AnalysisSettings
from msplatform.contracts.machine_contracts import load_json
from msplatform.execution.artifact_naming import validate_run_id
from msplatform.execution.context import python_runtime_version
from msplatform.execution.artifact_retention import validate_retention
from msplatform.execution.retention import file_record, verify_record, classify_file
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import require_completed_terminal_publication
from .source_experiment import build_case_plan, summarize_stage, validate_experiment
from .figures import export_comparison_figures
from .numerical_case import _run_case, _working_points, _settings

PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"

# Finite inspect-only legacy producer witness; original source is never executed.
_LEGACY_PRODUCER_FUNCTIONS = {'_write_json': '69a7e6a9a872b7d0969b50b8b2d51d2ca8989a16b71c8616fc373eed8d9dfa29',
 '_digest': '799af770547da2b1593b15c4949c585fc28d914855202176a976d9f6d5897c25',
 '_command': 'bc365a31c7bb85a91d9bc277a229315b906327f419c0940390d463e396c7885e',
 '_inputs': '636128dcfd3f69c35998169a30020c8b13aed66082cca49d80696399097ffefc',
 '_settings': '8df2ac7fe3829ec8eab56657fd505eff7b2c95ef1c8b889889935166a4eaa9fe',
 '_working_points': '9094d16433dcdee6bdf9dcc5135dccb0ae90ecbdb88362d6a1640b34bd6fbc23',
 '_run_case': '18a64f3c37e2e3b3197773d0827e021932fb94e9063f41bbac36104f40cac99a',
 '_reuse_case': '8eb2bfc19b2bdb8e47e4df2b66d273ffb855d5388a0c536943f4c18bb2777fb3',
 '_publish_manifest': '1b3df8b66312f2350a90b1bf2d7d70a9883ff003302f3a690da3df2a2b82a74a',
 '_write_report': '1aa6a921b86186a4a4b23882a7935b0e0e7e18fb6be751c5244cd9b0a4a707c5',
 '_prepare_run': '0408eab1734e4849c2c1a83ad19ce39c87fb6ccb99a2fff35cbeccbe30e17139',
 'execute': '35aaabdc934b6172916e99d172cca390a7f4494db9f31ebf09653c1c35e2f6b9',
 'main': '04953a63b827dc415a83aa17f5da64fbcf6ade98f30d2f001f1789f2f4898abf'}
_LEGACY_PRODUCER_TOP_LEVEL = ['7a630925338406195026c335218a1a8fed57f49c12660211176ef18809b976fe',
 '890bede517510aea64e32258c9530f0172f5a6ea2fcbcb247fdadc40c714e8bf',
 '356e6775028bc09e699d8b986887aaebc5e3e8e414a507fe911e3ba7da1264d9',
 'cd368e1323ca66ef47b1c160f651ef9ed6c513861bc160b5c01c36eb7136e49d',
 '092cb77ae0770f1627b29bf41b2732722fbcc3a0e1d77a79674801800a2721d1',
 '211ee42757705c7e350e70e36b762987a737f5e9c268f2a343e2dbfcb8fbea75',
 'ac3a74d6dd975a8e8fe4b7f85fce794793a9355595b850e3926964913948d386',
 '734591fe6aee43764b2c7feaf69f806fec1f5a58bedee51bc0cf5e1c5b36a4de',
 'b461ae95c16c1e73a466fdd306ad6da693ead3a324e5d33627958cc4a2f47e36',
 '9d97d469cf8d66465563e1e22c6dab3b6107819aba2d9956c7080016c1ab9c1b',
 'f7252e3c1dbe1d5edf1f34c020a58a05b55f706b2c1d9479eae91f9a9d4be275',
 'ff05bad0fd9a7212d3cd85fd2726055168be21bc8f6e0d93b29965794b0675d4',
 'daeb2f83800194e0f0fe2bbb6dd603d3e3cb4fc48ac5272304b52ee8789b9831',
 '7dfb3769531200798c4deb8bbda03645308321ac7bb6617fd61bec0e8f7e67b3',
 '59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca',
 '68c3503c96524a291ba3f175e383b38269e898b6c29bd9965c11d7e1d2ae8ae9',
 'cf089123882c6aebe3ed7be344074e1c1ecb61c6d73e2e8ee8265103a982ac53',
 '271fc31378e1108a9784c29c3c4768de571ce080301b4ad9721ba767fcf5842b',
 'c3c7dcd5d5164b7cfe092b4522d76a0a94657f5607017e900cabe77793434f7f',
 '5bec0e1465cb4defa803aa8eb2995d61e2324278dbbf7da1cc24008155885f74',
 '787c8d08a2d5fef36a8497b85c925d88331642f6a6ca2c329fece071eb9f97b4',
 '8781293c35c519252f845c525a43dfcb2fc14a49f33cdafc49ba73ef553b196c',
 '03776b5a2fdb2ea89bb0dcebea4861e6f8528f2bdf691a1dc014267fd0300d5e',
 'd801c55856ffc60b0f865c5090ee46187210c82749126a69fbf5c57c77846ce6',
 '20064d28c728538c632cfb4073ffa0c1842d4018f4e117ad954228c86eced9cc',
 '25b63c68d07e346a6dc7a9cd1a3f877543d6e50fc33facc6efdcc04b4215eedc',
 '0077ce76a3573ee453aa84bbff3bc4aad7be5059e658d47ec362001276658f41',
 '0c76f4ab1f551bc7b696ed3352998a863d5b4a48986d70de709ab9eca7555d7f',
 'bac5fe9964e1d70e5f07f14177b2abe6b7cd6fe4f14e87155650cdaf64903de5',
 'd1de4c7272d7fc73814274437d78ec3d560718e465f3af3884e569432e2b17eb',
 '6be284e4826dbd186e0991ed1df0accae0150d06a60a129547a1a9b0a3ce32a3',
 'ef35c60df21b04c60d2771381d20ab72efd841f82c1e23dbfe94e71c74b295e3',
 'be6767dd3debdea09edccea6c2c2af628c6025cf732c8353f6063635e367dae8']
_LEGACY_SCIENTIFIC_SOURCE_PAIRS = {'oatof_oaaccelerator_coupling': ('0D5D37C11D35A98E494DD2A76A152F2FA0AEDD36D9669978154676DD2F1395A2',
                                  'C63A4E996780C519A7F05B20F12B927EEAB8CE6B4832F49C5FF8E07B274C5178'),
 'reflectron_dual_stage_solver': ('EE7D5D21F8E34A0601451FC79054A048452307CD304E67161978F7CD8F21591D',
                                  'C73B0E452A2688FB05F4141ED6455F36C61824EE6C4EF125359DD1A419C620D2'),
 'accelerator_time_focus': ('09888DE7F7929E074EF38C1B17E5AEE5CA7342FF647794E716B31EB5E95C31C7',
                            '28FA9E54FF3E62292B92C07AC1DC736E5D8BC923D8024988406890C6AEF96F8D'),
 'ideal_source_experiment': ('7E29AC168E92E2B04ED6E403A6D7BA35823B8C725D8B7298A4BE7D3304EE9ECB',
                             '124774594D4A242B0A9307CF837784E3E5EA4371238338FD0CD0F651015F4CA8')}

def _legacy_scientific_binding(name: str, original_sha: str, current_sha: str) -> bool:
    """Accept only equal bytes or this migration's exact reviewed source pair."""
    original_sha, current_sha = original_sha.upper(), current_sha.upper()
    return original_sha == current_sha or _LEGACY_SCIENTIFIC_SOURCE_PAIRS.get(name) == (original_sha, current_sha)


def _ast_identity(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def _verify_legacy_source(source: str) -> None:
    """Check the complete finite thirteen-function producer without importing it."""
    tree = ast.parse(source)
    functions = {node.name: _ast_identity(node) for node in tree.body if isinstance(node, ast.FunctionDef)}
    if len(functions) != sum(isinstance(node, ast.FunctionDef) for node in tree.body) or functions != _LEGACY_PRODUCER_FUNCTIONS:
        raise ValueError("legacy scientific producer differs: unsupported original function set/body")
    other = [_ast_identity(node) for node in tree.body if not isinstance(node, ast.FunctionDef)]
    if other != _LEGACY_PRODUCER_TOP_LEVEL:
        raise ValueError("legacy numerical imported authority or import-time execution differs")


def _write_json(path: Path, value: Any) -> None:
    """Use the shared atomic writer with the original strict finite-JSON policy."""
    from msplatform.execution.recorded_file_removal import write_json_atomic
    write_json_atomic(path, value, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _legacy_ideal_parent(previous: Path | None) -> bool:
    if previous is None:
        return False
    config = load_json(previous / "run_config.json")
    return "numerical_case" not in config.get("input_sha256", {}) or "legacy_numerical_projection" in config.get("inputs", {})


def _legacy_ideal_binding(previous: Path, path: Path, manifest: dict[str, Any], label: str, *, verify: bool = True) -> dict[str, Any]:
    path = path.resolve(strict=True)
    if not path.is_relative_to(previous):
        raise ValueError(f"legacy {label} escapes its original owner")
    records = [manifest["run_config"], *manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
    matches = [item for item in records if Path(item["path"]).resolve() == path]
    if not matches or len({(item.get("bytes"), item.get("sha256")) for item in matches}) != 1:
        raise ValueError(f"legacy {label} lacks its original manifest binding")
    if manifest.get("schema_version") == 2:
        classify = classify_file
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
            or mode != "ideal_source_comparison" or parent.get("project") != PROJECT_ID
            or parent.get("run_id") != previous.name or manifest.get("run_id") != previous.name
            or manifest.get("project") != parent["project"] or manifest.get("mode") != parent["mode"]):
        raise ValueError("legacy resume supports only a completed original basic ideal-source producer")
    _legacy_ideal_binding(previous, previous / "run_config.json", manifest, "run config")
    if manifest["schema_version"] == 2:
        retention = validate_retention(parent.get("artifact_retention"))
        expected = {"policy_version": retention.policy_version, "class": retention.class_id, "reason": retention.reason}
        if manifest.get("artifact_retention") != expected:
            raise ValueError("legacy v2 retention contract differs from original config")
    summary = load_json(previous / "summary.json")
    _legacy_ideal_binding(previous, previous / "summary.json", manifest, "summary")
    if (summary.get("status") != manifest["status"] or summary.get("role") != "ideal_source_comparison_summary"
            or type(summary.get("completed_cases")) is not int or type(summary.get("planned_cases")) is not int
            or not 0 <= summary["completed_cases"] <= summary["planned_cases"]):
        raise ValueError("legacy producer summary/terminal case facts differ")
    expected_roles = {"experiment", "entrypoint", "analysis_contract", "particle_policy", "peak_metrics",
        "accelerator_time_focus", "accelerator_three_zone_theory", "accelerator_two_zone_geometry",
        "ideal_source_comparison", "ideal_source_experiment", "ideal_source_comparison_plot",
        "three_zone_ideal_theory", "oatof_oaaccelerator_coupling", "reflectron_dual_stage_solver"}
    if set(parent.get("inputs", {})) != expected_roles or set(parent.get("input_sha256", {})) != expected_roles:
        raise ValueError("legacy frozen scientific input role set is incomplete or unsupported")
    for name, value in parent["inputs"].items():
        path = Path(value)
        record = _legacy_ideal_binding(previous, path, manifest, "input " + name)
        if record["sha256"] != parent["input_sha256"][name].upper():
            raise ValueError(f"legacy frozen input identity differs: {name}")
        if name == "accelerator_two_zone_geometry":
            if parent["input_sha256"][name].upper() != "C85505DF65FB9ACD0C19085EDE5CC802A6F5729C33181AE0C4A69947B1D93D3C":
                raise ValueError("unsupported original two-zone provenance source")
        elif name not in {"entrypoint", "ideal_source_comparison_plot"} and not _legacy_scientific_binding(name, parent["input_sha256"][name], identities[name]):
            raise ValueError(f"legacy scientific input changed: {name}; recompute affected cases")
    environment = {"python": python_runtime_version(), "numpy": np.__version__, "scipy": scipy.__version__}
    original_identity = _digest({"inputs": parent["input_sha256"], "seed": seed, **environment})
    if parent.get("run_instance", {}).get("seed") != seed or parent.get("numerical_identity") != original_identity:
        raise ValueError("legacy original identity cannot prove the requested seed/environment; recover original environment or recompute cases")
    source = Path(parent["inputs"]["entrypoint"]).read_text(encoding="utf-8")
    _verify_legacy_source(source)
    numerical = Path(__file__).with_name("numerical_case.py").read_text(encoding="utf-8")
    old_functions = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    new_functions = {node.name: node for node in ast.parse(numerical).body if isinstance(node, ast.FunctionDef)}
    for name in ("_working_points", "_run_case"):
        if _ast_identity(old_functions[name]) != _ast_identity(new_functions[name]):
            raise ValueError(f"legacy scientific producer differs: {name}; recompute affected cases")
    settings = copy.deepcopy(new_functions["_settings"])
    settings.args.args = []
    settings.body[0] = ast.parse('kde = load_json(PROJECT_ROOT / "config/analysis_contract.json")["kde"]').body[0]
    if _ast_identity(old_functions["_settings"]) != _ast_identity(settings):
        raise ValueError("legacy scientific producer differs: frozen-contract settings mapping")
    return {"schema_version": 1, "role": "ideal_source_legacy_numerical_projection",
            "original_owner": str(previous), "original_identity": original_identity,
            "original_manifest": file_record(previous / "run_manifest.json"),
            "original_source": file_record(Path(parent["inputs"]["entrypoint"])),
            "source_witness_semantics": "original producer bytes inspected for equivalence; never imported or executed in this child",
            "original_input_sha256": parent["input_sha256"], "verified_environment": environment,
            "actual_modern_numerical_input_sha256": {name: value for name, value in identities.items()
                if name not in {"entrypoint", "ideal_source_comparison_plot"}},
            "source_reference": protection["source_reference"], "execution_context": protection["execution_context"],
            "settings_proof": "every reused checkpoint is rechecked against its bound raw CSV with frozen Settings; no claim that legacy live-path reads were frozen",
            "source_witness_limit": "known original producer/input evidence, not complete historical transitive execution closure; no missing historical constant source is backfilled"}


def _legacy_csv_analysis(previous: Path, document: dict[str, Any], config: dict[str, Any], settings: AnalysisSettings) -> None:
    """Verify old analysis from its original full-mother CSV, without resampling."""
    from collections import Counter
    from msplatform.components.single_reflection_oa_tof.ideal_source_comparison import _peak_summary
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


def _reuse_case(previous: Path | None, case: dict[str, Any], identity: str, destination: Path, *,
                frozen_inputs: dict,
                settings: AnalysisSettings) -> dict[str, Any] | None:
    if previous is None:
        return None
    projected = _reuse_legacy_ideal_case(previous, case, identity, destination,
                                          frozen_inputs=frozen_inputs, settings=settings)
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


def _reuse_legacy_ideal_case(previous: Path, case: dict[str, Any], identity: str, destination: Path, *,
                            frozen_inputs: dict,
                            settings: AnalysisSettings) -> dict[str, Any] | None:
    if "legacy_numerical_projection" not in frozen_inputs:
        return None
    proof_value = frozen_inputs["legacy_numerical_projection"]["path"]
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
    frozen_experiment = load_json(Path(frozen_inputs["experiment"]["path"]))
    _legacy_csv_analysis(original, document, frozen_experiment, settings)
    # Canonical state/events remain the original complete CSV. No row is
    # resampled, renumbered, copied, filtered or rewritten in this child.
    derived = {**document, "identity": identity,
        "particles": {**document["particles"], "path": str(csv_path.resolve())},
        "derived_from": {"original_identity": proof["original_identity"], "checkpoint": file_record(path),
                         "original_csv": record, "source_owner": str(original)}}
    derived.pop("record_sha256")
    derived["record_sha256"] = _digest(derived)
    _write_json(destination / path.name, derived)
    return derived

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



def _declared_path(value: Any, base: Path, label: str) -> Path:
    """Resolve one author declaration once, without any checkout lookup."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must declare an explicit input path")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve(strict=True)


def _source_files(config_path: Path, analysis_path: Path) -> dict[str, Path]:
    """Bind original scientific roles to the actual selected canonical sources."""
    from msplatform.analysis import peak_metrics
    from msplatform.contracts import particle_count_policy, particle_physics
    from msplatform.components.orthogonal_accelerator import accelerator_time_focus
    from msplatform.components.orthogonal_accelerator import three_zone_ideal_theory as accelerator_theory
    from msplatform.components.single_reflection_oa_tof import ideal_source_comparison
    from msplatform.components.single_reflection_oa_tof import three_zone_ideal_theory
    from msplatform.components.single_reflection_oa_tof import oatof_oaaccelerator_coupling
    from msplatform.components.single_reflection_oa_tof import reflectron_dual_stage_solver
    from . import numerical_case, source_experiment, figures
    modules = {"entrypoint": sys.modules[__name__], "numerical_case": numerical_case,
        "particle_physics": particle_physics,
        "peak_metrics": peak_metrics, "accelerator_time_focus": accelerator_time_focus,
        "accelerator_three_zone_theory": accelerator_theory,
        "ideal_source_comparison": ideal_source_comparison,
        "ideal_source_experiment": source_experiment, "ideal_source_comparison_plot": figures,
        "three_zone_ideal_theory": three_zone_ideal_theory,
        "oatof_oaaccelerator_coupling": oatof_oaaccelerator_coupling,
        "reflectron_dual_stage_solver": reflectron_dual_stage_solver}
    return {"experiment": config_path, "analysis_contract": analysis_path,
            "particle_policy": particle_count_policy.POLICY_PATH.resolve(),
            **{name: Path(module.__file__).resolve() for name, module in modules.items()}}


def _resolve_inputs(config_path: Path, *, input_root: Path,
                    receipt_root: Path | None, expected_role: str | None = None) -> tuple[dict, dict[str, Path]]:
    """Validate scientific declarations before creating the managed owner."""
    config_path = Path(config_path).resolve(strict=True)
    base = Path(input_root).resolve(strict=True)
    if not base.is_dir():
        raise ValueError("input_root must be the explicit author input directory")
    config = load_json(config_path)
    role = config.get("role")
    if expected_role is not None and role != expected_role:
        raise ValueError("selected scientific configuration role differs")
    extra = {}
    if role == "ideal_acceptance_theory":
        from . import acceptance_theory
        acceptance_theory.validate_theory_config(config)
        reference_path = _declared_path(config["reference_config"], base, "reference_config")
        reference = load_json(reference_path)
        validate_experiment(reference)
        analysis = _declared_path(reference["analysis_contract"], base, "reference analysis_contract")
        from msplatform.components.single_reflection_oa_tof import ideal_acceptance_theory
        from msplatform.components.single_reflection_oa_tof import ideal_acceptance_design
        from msplatform.components.single_reflection_oa_tof import ideal_acceptance_linear_design
        from msplatform.components.single_reflection_oa_tof import ideal_acceptance_experiment
        kernels = {"ideal_acceptance_theory": ideal_acceptance_theory,
            "ideal_acceptance_design": ideal_acceptance_design,
            "ideal_acceptance_linear_design": ideal_acceptance_linear_design,
            "ideal_acceptance_experiment": ideal_acceptance_experiment}
        if "density" in config["numerics"]:
            from msplatform.components.single_reflection_oa_tof import ideal_acceptance_density
            kernels["ideal_acceptance_density"] = ideal_acceptance_density
        extra = {"theory_workflow": Path(acceptance_theory.__file__).resolve(),
                 "reference_config": reference_path,
                 **{name: Path(module.__file__).resolve() for name, module in kernels.items()}}
    elif role == "ideal_source_slope_scan":
        from . import slope_scan
        slope_scan.validate_slope_scan_config(config)
        if receipt_root is None:
            raise ValueError("slope scan requires an explicit receipt_root")
        receipt_base = Path(receipt_root).resolve(strict=True)
        if not receipt_base.is_dir():
            raise ValueError("receipt_root must be the explicit scalar-receipt base directory")
        receipt = slope_scan._receipt_path(config, receipt_root=receipt_base)
        analysis = _declared_path(config["analysis_contract"], base, "analysis_contract")
        from msplatform.components.single_reflection_oa_tof import ideal_acceptance_linear_design
        extra = {"slope_scan_workflow": Path(slope_scan.__file__).resolve(),
                 "historical_slope_receipt": receipt,
                 "ideal_acceptance_linear_design": Path(ideal_acceptance_linear_design.__file__).resolve()}
    elif role == "ideal_source_comparison":
        validate_experiment(config)
        analysis = _declared_path(config["analysis_contract"], base, "analysis_contract")
    else:
        raise ValueError("unsupported ideal-source configuration role")
    if role != "ideal_source_slope_scan" and receipt_root is not None:
        raise ValueError("receipt_root is supported only by the explicit slope study")
    _settings(analysis)
    return config, {**_source_files(config_path, analysis), **extra}


def _source_references(previous: Path | None) -> tuple[list[dict], dict | None]:
    """Select existing manifests; only the original owner acquires their leases."""
    if previous is None:
        return [], None
    previous = Path(previous).resolve(strict=True)
    manifest = previous / "run_manifest.json"
    if not manifest.is_file():
        raise ValueError("resume source lacks its bound terminal manifest")
    references = [{"manifest_record": file_record(manifest),
                   "protected_paths": [str(previous)], "protected_cache_keys": []}]
    if not _legacy_ideal_parent(previous):
        return references, None
    parent = load_json(previous / "run_config.json")
    original = previous
    reference = references[0]
    if "legacy_numerical_projection" in parent.get("inputs", {}):
        path = Path(parent["inputs"]["legacy_numerical_projection"])
        if not path.resolve().is_relative_to(previous) or file_sha256(path) != parent["input_sha256"]["legacy_numerical_projection"]:
            raise ValueError("derived legacy source proof is missing or changed")
        proof = load_json(path)
        if proof.get("role") != "ideal_source_legacy_numerical_projection":
            raise ValueError("unsupported derived legacy numerical source")
        original = Path(proof["original_owner"]).resolve(strict=True)
        reference = proof["source_reference"]
        if Path(reference["manifest_record"]["path"]).resolve() != original / "run_manifest.json":
            raise ValueError("derived legacy source does not bind its original owner")
        references.append(reference)
    return references, {"source_reference": reference, "source_references": references,
                        "original_owner": str(original)}


def _source_package_root() -> Path:
    from importlib.resources import files
    return Path(str(files("msplatform"))).resolve()


def _freeze_worker_package(session: Any, frozen: dict[str, dict], *, seed: int,
                           identity: str, resume_from: Path | None,
                           max_workers: int | None) -> tuple[Path, list[dict]]:
    """Use the existing provider enumerator, copier and isolated module executor."""
    from msplatform.execution.inputs import enumerate_python_sources, freeze_python_package
    provider = _source_package_root()
    # Freeze the actual TOF scientific/owner closure, including the shared
    # component initializer's explicit catalog and model imports.  The same
    # enumerator still owns parent initializers and declared resource files.
    selected = enumerate_python_sources(provider.parent, package_roots=[
        "msplatform/analysis", "msplatform/contracts", "msplatform/execution", "msplatform/io",
        "msplatform/components/orthogonal_accelerator", "msplatform/components/single_reflection_oa_tof",
        "msplatform/components/rf_multipole",
        "msplatform/workflows/oa_tof_design",
    ], module_paths=["msplatform/components/catalog.py", "msplatform/components/model.py"],
        provider_root=provider.name, resource_suffixes=(".json", ".ps1", ".lua", ".m", ".gem", ".iob"),
        require_python_source=True)
    code_root = session.artifact_run_dir / "inputs/analysis_code"
    package = freeze_python_package(provider.parent, code_root, relative_paths=selected)
    guards = []
    def package_inputs():
        for index, entry in enumerate(package["files"]):
            path = session.declare_file(entry["path"], "required_evidence")
            record = dict(path=str(path), exists=True, bytes=path.stat().st_size,
                          sha256=entry["sha256"], retention_role="required_evidence")
            yield f"analysis_code_{index:04d}", record
            guards.append(record)
    session.add_inputs(package_inputs())
    selected_members = {Path(record["path"]): record for record in guards}
    for name, scientific in frozen.items():
        source = Path(scientific.get("source_path", scientific["path"])).resolve()
        if source.is_relative_to(provider):
            member_path = (code_root / provider.name / source.relative_to(provider)).resolve()
            member = selected_members.get(member_path)
            if (member is None or member["bytes"] != scientific["bytes"]
                    or member["sha256"].upper() != scientific["sha256"].upper()):
                raise ValueError("Frozen scientific role differs from selected package member: " + name)
    package_path = session.declare_file(session.input_dir / "analysis_package.json", "required_evidence")
    _write_json(package_path, package)
    package_record = file_record(package_path, "required_evidence")
    session.add_input("analysis_package", package_record)
    executor_path = code_root / provider.name / "execution/resources/frozen_python_package.ps1"
    if not executor_path.is_file():
        raise FileNotFoundError("Required frozen Python executor missing: " + str(executor_path))
    executor = next(row for row in guards if Path(row["path"]) == executor_path.resolve())
    request_path = session.declare_file(session.input_dir / "scientific_request.json", "required_evidence")
    outputs = {name: str(session.declare_file(path, "required_evidence")) for name, path in {
        "completion": session.result_dir / "scientific_completion.json",
        "environment": session.result_dir / "scientific_environment.json",
        "stdout": session.log_dir / "scientific_module.stdout.log"}.items()}
    _write_json(request_path, dict(schema_version=1, role="oa_tof_design_scientific_request",
        python=str(session.context.python_executable), module="msplatform.workflows.oa_tof_design.source_comparison",
        package_receipt=package_record, executor=executor, scientific_inputs=frozen,
        run_directory=str(session.artifact_run_dir), working_directory=str(session.run_dir),
        seed=seed, numerical_identity=identity,
        numerical_input_sha256=load_json(session.run_config)["numerical_input_sha256"],
        resume_from=None if resume_from is None else str(resume_from.resolve()),
        max_workers=max_workers, outputs=outputs, capacity_session=session.capacity_session,
        forbidden_roots=[str(provider)], distribution_names=["numpy", "scipy", "matplotlib", "Pillow"],
        required_modules=["msplatform.workflows.oa_tof_design.source_comparison",
                          "msplatform.workflows.oa_tof_design.numerical_case",
                          "msplatform.workflows.oa_tof_design.source_experiment",
                          "msplatform.workflows.oa_tof_design.figures",
                          "msplatform.workflows.oa_tof_design.acceptance_theory",
                          "msplatform.workflows.oa_tof_design.slope_scan"]))
    request_record = file_record(request_path, "required_evidence")
    session.add_input("scientific_request", request_record)
    return request_path, [*guards, package_record, request_record, *frozen.values()]


_FROZEN_WORKER_COMMAND = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=Get-Content -LiteralPath $env:OA_TOF_SCIENTIFIC_REQUEST -Raw -Encoding UTF8|ConvertFrom-Json
if($request.schema_version-ne1-or$request.role-cne'oa_tof_design_scientific_request'){throw 'Unsupported frozen TOF request'}
$package=Get-Content -LiteralPath $request.package_receipt.path -Raw -Encoding UTF8|ConvertFrom-Json
. $request.executor.path
$execution=Invoke-IsolatedFrozenPythonModule -Python $request.python -Package $package `
    -Module $request.module -Arguments @('--worker-request',$env:OA_TOF_SCIENTIFIC_REQUEST) `
    -DistributionNames @($request.distribution_names) -RequiredModuleNames @($request.required_modules) `
    -ForbiddenRoots @($request.forbidden_roots) -StdoutPath $request.outputs.stdout `
    -WorkingDirectory $request.working_directory
$execution|ConvertTo-Json -Depth 32|Set-Content -LiteralPath $request.outputs.environment -Encoding utf8NoBOM
"""


def _invoke_worker(session: Any, request_path: Path, guards: list[dict], stage: dict) -> dict:
    for index, record in enumerate(guards):
        verify_record(f"frozen TOF input {index}", record)
    session.run_process("scientific_analysis", executable=session.context.powershell_executable,
        arguments=["-NoProfile", "-NonInteractive", "-Command", _FROZEN_WORKER_COMMAND],
        role="GATE", stage="oa_tof_design", limits=stage["limits"],
        environment={"OA_TOF_SCIENTIFIC_REQUEST": str(request_path)}, immutable_input_records=guards)
    request = load_json(request_path)
    completion = load_json(Path(request["outputs"]["completion"]))
    if (completion.get("schema_version") != 1 or completion.get("role") != "oa_tof_design_scientific_completion"
            or completion.get("request_sha256") != file_sha256(request_path)):
        raise ValueError("scientific worker completion differs from its bound request")
    for index, record in enumerate(guards):
        verify_record(f"completed TOF input {index}", record)
    session.renew_capacity()
    return completion


def _run_comparison_cases(config: dict[str, Any], *, seed: int, run_dir: Path,
                          identity: str, resume_from: Path | None,
                          settings: AnalysisSettings, frozen_inputs: dict,
                          capacity: dict) -> dict[str, Any]:
    """Keep original residual/width ordering and scientific checkpoints in one worker."""
    plan = build_case_plan(config, seed)
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    stage, reused, error, current_case = "working_points", 0, None, None
    status = "success"
    try:
        points = _working_points(config)
        _write_json(run_dir / "results/working_points.json", {"schema_version": 2, "role": "ideal_source_working_points",
                    "working_points": {k: v.to_dict() for k, v in points.items()}})
        for stage in ("residual_scan", "width_scan"):
            print(f"IDEAL_COMPARISON STAGE={stage} EVENT=START", flush=True)
            for case in (c for c in plan if c["stage"] == stage):
                stage = case["stage"]
                current_case = case["case_id"]
                _renew_selected_capacity(capacity)
                record = _reuse_case(resume_from, case, identity, run_dir / "results",
                                     frozen_inputs=frozen_inputs, settings=settings)
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
    _write_report(run_dir, records, summary)
    external = {"legacy_case_csv_" + record["case"]["case_id"]: record["particles"]
                for record in records if "derived_from" in record}
    return {"summary": summary, "external_inputs": external}


def _numerical_identity(input_sha256: dict[str, str], *, seed: int) -> str:
    """Preserve the original scientific/config/seed/environment dependency set.

    The whole frozen provider and engineering policy are execution provenance;
    neither is silently promoted to a numerical or modern-resume dependency.
    """
    numerical_inputs = {name: value for name, value in input_sha256.items()
                        if name not in {"entrypoint", "ideal_source_comparison_plot"}}
    return _digest({"inputs": numerical_inputs, "seed": seed,
                    "python": python_runtime_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__})


def _renew_selected_capacity(capacity: dict) -> None:
    """Renew only this existing owner-bound capacity/source lease at case boundaries."""
    from msplatform.execution.capacity_session import renew_capacity_session
    now = time.monotonic()
    previous = capacity.get("_worker_last_renewal_monotonic")
    if previous is None or now - previous >= capacity["lease_ttl_seconds"] / 2:
        renew_capacity_session(capacity)
        capacity["_worker_last_renewal_monotonic"] = now


_WORKER_ORIGIN_REPORTED = False
_BOUND_SCIENTIFIC_REQUEST: dict | None = None


def _bind_scientific_worker_request(request: dict | None) -> None:
    """Bind the explicit verified request in this worker or actual pool child."""
    global _BOUND_SCIENTIFIC_REQUEST, _WORKER_ORIGIN_REPORTED
    _BOUND_SCIENTIFIC_REQUEST = request
    _WORKER_ORIGIN_REPORTED = False


def _verify_scientific_worker_origin() -> None:
    """Bind actual scientific and ProcessPool workers to the selected frozen provider."""
    global _WORKER_ORIGIN_REPORTED
    request = _BOUND_SCIENTIFIC_REQUEST
    if request is None:
        return  # Direct pure scientific calls do not claim managed worker evidence.
    package = load_json(Path(request["package_receipt"]["path"]))
    roots = [Path(root).resolve() for root in package["package_roots"]]
    origins = {}
    for name, module in list(sys.modules.items()):
        if name == "msplatform" or name.startswith("msplatform."):
            source = getattr(module, "__file__", None)
            if source is None or not any(Path(source).resolve().is_relative_to(root) for root in roots):
                raise ValueError("scientific worker loaded a foreign canonical provider: " + name)
            origins[name] = str(Path(source).resolve())
    if not _WORKER_ORIGIN_REPORTED:
        print("OA_TOF_WORKER_ORIGIN=" + json.dumps({"pid": os.getpid(), "modules": origins}, sort_keys=True), flush=True)
        _WORKER_ORIGIN_REPORTED = True



def _renew_worker_capacity() -> None:
    """Renew the request's same owner lease at an existing scientific task boundary."""
    request = _BOUND_SCIENTIFIC_REQUEST
    if request is not None:
        from msplatform.execution.capacity_session import renew_capacity_session
        renew_capacity_session(request["capacity_session"])


def _scientific_worker(request_path: Path) -> None:
    """Consume bound run-local records and emit scientific completion, never owner files."""
    global _BOUND_SCIENTIFIC_REQUEST, _WORKER_ORIGIN_REPORTED
    request = load_json(request_path)
    if (type(request.get("schema_version")) is not int or request["schema_version"] != 1
            or request.get("role") != "oa_tof_design_scientific_request"):
        raise ValueError("unsupported frozen TOF scientific request")
    frozen = request["scientific_inputs"]
    for name, record in frozen.items():
        verify_record("scientific input " + name, record)
    previous = (_BOUND_SCIENTIFIC_REQUEST, _WORKER_ORIGIN_REPORTED)
    _bind_scientific_worker_request(request)
    try:
        _verify_scientific_worker_origin()
        numerical_inputs = request["numerical_input_sha256"]
        if any(name not in frozen or frozen[name]["sha256"] != value
               for name, value in numerical_inputs.items()):
            raise ValueError("Frozen numerical input identity differs from scientific role records")
        if _numerical_identity(numerical_inputs, seed=request["seed"]) != request["numerical_identity"]:
            raise ValueError("Selected scientific worker Python/NumPy/SciPy environment differs from the bound numerical identity")
        config = load_json(Path(frozen["experiment"]["path"]))
        settings = _settings(Path(frozen["analysis_contract"]["path"]))
        shared = dict(seed=request["seed"], run_dir=Path(request["run_directory"]),
                      identity=request["numerical_identity"], settings=settings)
        capacity = request["capacity_session"]
        _renew_selected_capacity(capacity)
        if config["role"] == "ideal_source_comparison":
            result = _run_comparison_cases(config, **shared,
                resume_from=None if request["resume_from"] is None else Path(request["resume_from"]),
                frozen_inputs=frozen, capacity=capacity)
        elif config["role"] == "ideal_acceptance_theory":
            from .acceptance_theory import _run_theory_cases
            result = _run_theory_cases(config, load_json(Path(frozen["reference_config"]["path"])),
                **shared, max_workers=request["max_workers"])
        elif config["role"] == "ideal_source_slope_scan":
            from .slope_scan import _run_slope_cases
            result = _run_slope_cases(config, **shared)
        else:
            raise ValueError("unsupported frozen TOF scientific role")
        _renew_selected_capacity(capacity)
        for name, record in frozen.items():
            verify_record("completed scientific input " + name, record)
        _write_json(Path(request["outputs"]["completion"]), dict(schema_version=1,
            role="oa_tof_design_scientific_completion", request_sha256=file_sha256(request_path),
            result=result))
    finally:
        _BOUND_SCIENTIFIC_REQUEST, _WORKER_ORIGIN_REPORTED = previous


def _run_action(session: Any, *, requested: dict[str, Path], original: dict[str, dict],
                config: dict, seed: int, identity: str, resume_from: Path | None,
                max_workers: int | None, stage: dict, policy_record: dict,
                legacy_protection: dict | None) -> dict:
    """Freeze once, observe one scientific family, and return to the sole publisher."""
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.recorded_file_removal import write_json_atomic
    frozen = {}
    try:
        for name, source in requested.items():
            verify_record("selected TOF " + name, original[name])
            target = session.declare_file(session.input_dir / (name + source.suffix), "required_evidence")
            record = dict(freeze_file(source, target), retention_role="required_evidence")
            if record["sha256"] != original[name]["sha256"]:
                raise ValueError("TOF input changed while freezing: " + name)
            session.add_input(name, record)
            frozen[name] = record
        identities = {name: record["sha256"] for name, record in frozen.items()}
        projection = None
        if resume_from is not None:
            previous = load_json(resume_from / "run_config.json")
            if legacy_protection is not None:
                protection = dict(legacy_protection,
                                  execution_context=load_json(session.run_config)["paths"])
                projection = _legacy_ideal_projection(Path(protection["original_owner"]),
                    identities, seed, config["role"], protection)
                if "numerical_case" in previous.get("input_sha256", {}) and previous.get("numerical_identity") != identity:
                    raise ValueError("derived legacy numerical code/config/seed/environment differs")
            elif previous.get("numerical_identity") != identity:
                raise ValueError("resume code/config/seed/environment differs; start a new comparison without --resume-from")
            external = set(previous.get("legacy_external_case_inputs", {}).values()) if projection else set()
            for name, expected_sha in previous["input_sha256"].items():
                path = previous["inputs"][name]
                if name not in external and file_sha256(Path(path)) != expected_sha:
                    raise ValueError("resume frozen input changed: " + name)
        if projection is not None:
            for name, source in (("legacy_original_entrypoint", Path(projection["original_source"]["path"])),
                                 ("legacy_original_manifest", Path(projection["original_owner"]) / "run_manifest.json")):
                target = session.declare_file(session.input_dir / (name + source.suffix), "required_evidence")
                record = dict(freeze_file(source, target), retention_role="required_evidence")
                frozen[name] = record
                session.add_input(name, record)
            projection["original_source_witness"] = frozen["legacy_original_entrypoint"]
            target = session.declare_file(session.input_dir / "legacy_numerical_projection.json", "required_evidence")
            _write_json(target, projection)
            frozen["legacy_numerical_projection"] = file_record(target, "required_evidence")
            session.add_input("legacy_numerical_projection", frozen["legacy_numerical_projection"])
        run_config = load_json(session.run_config)
        run_config.update(input_sha256={name: row["sha256"] for name, row in frozen.items()},
            numerical_input_sha256={name: value for name, value in identities.items()
                if name not in {"entrypoint", "ideal_source_comparison_plot"}},
            numerical_identity=identity, run_instance=dict(seed=seed,
                resume_from=None if resume_from is None else str(resume_from)),
            claim_scope=config["scope"], formal_gate_passed=False,
            execution_source_sha256=dict(stage_policy=policy_record["sha256"]),
            selected_scientific_sources={name: dict(source_path=str(requested[name]),
                frozen_record=frozen[name]) for name in requested})
        write_json_atomic(session.run_config, run_config)
        request, guards = _freeze_worker_package(session, frozen, seed=seed, identity=identity,
            resume_from=resume_from, max_workers=max_workers)
        completion = _invoke_worker(session, request, guards, stage)
        scientific = completion["result"]
        external = scientific.get("external_inputs", {})
        external_roles = {}
        for name, record in external.items():
            session.add_input(name, dict(record, retention_role="required_evidence"))
            run_config = load_json(session.run_config)
            run_config["input_sha256"][name] = record["sha256"]
            external_roles[name.removeprefix("legacy_case_csv_")] = name
            write_json_atomic(session.run_config, run_config)
        run_config = load_json(session.run_config)
        if external_roles:
            run_config["legacy_external_case_inputs"] = external_roles
        run_config["scientific_execution"] = scientific.get("execution", {})
        write_json_atomic(session.run_config, run_config)
        outputs = [path for root in (session.result_dir, session.log_dir)
                   for path in root.rglob("*") if path.is_file()]
        required = []
        for path in outputs:
            role = session.file_roles.get(str(session.canonical_path(path)))
            if role is None:
                role = "required_evidence" if path.suffix.lower() in {".csv", ".json"} else classify_file(path)
                session.declare_file(path, role)
            if role == "required_evidence":
                required.append(path)
        return dict(status=scientific["summary"]["status"], summary=scientific["summary"],
            output_paths=outputs, required_output_paths=required,
            retention_preserve_paths=[], manifest_extra_fields={})
    except BaseException as primary:
        # Actual process/writer completion is exclusively the existing owner's decision.
        primary.failure_output_paths = []
        try:
            for root in (session.result_dir, session.log_dir):
                for path in root.rglob("*"):
                    if path.is_file():
                        role = session.file_roles.get(str(session.canonical_path(path)))
                        if role is None:
                            role = "required_evidence" if path.suffix.lower() in {".csv", ".json"} else classify_file(path)
                            session.declare_file(path, role)
                        primary.failure_output_paths.append(path)
        except Exception as secondary:
            primary.add_note(f"TOF failure evidence selection also failed: {secondary!r}")
        raise


def _execute_role(config_path: Path, *, input_root: Path, context: Any, seed: int,
                  run_id: str, resume_from: Path | None, max_workers: int | None = None,
                  receipt_root: Path | None = None, expected_role: str | None = None) -> Path:
    """Use the existing managed owner; no author checkout or engineering defaults."""
    from functools import partial
    from msplatform.execution import capacity_ledger
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.execution.completion import no_particle_batch_completion_api
    if not isinstance(context, ExecutionContext):
        raise ValueError("execution requires an explicit managed ExecutionContext")
    validate_run_id(run_id)
    artifact_root = context.workspace / "artifacts"
    # Same existing owner precondition, before source/CSV/lease reads; no ad-hoc adoption.
    if artifact_root.exists() and capacity_ledger.load_capacity_ledger(artifact_root) is None:
        raise ValueError("Existing artifact root lacks its explicit calibrated capacity ledger")
    config, requested = _resolve_inputs(config_path, input_root=input_root,
        receipt_root=receipt_root, expected_role=expected_role)
    if max_workers is not None and config["role"] != "ideal_acceptance_theory":
        raise ValueError("max workers is supported only by ideal_acceptance_theory runs")
    original = {name: file_record(path, "required_evidence") for name, path in requested.items()}
    identities = {name: row["sha256"] for name, row in original.items()}
    identity = _numerical_identity(identities, seed=seed)
    previous = None if resume_from is None else Path(resume_from).resolve(strict=True)
    references, legacy = _source_references(previous)
    stage, policy_record = read_stage_policy(context, config["role"])
    run_managed_stage(context, descriptor=dict(project=PROJECT_ID, mode=config["role"],
        software=["Python solver-free OA-TOF design"]), run_id=run_id,
        payload=dict(formal_gate_passed=False, claim_scope=config["scope"],
            scientific_role=config["role"], numerical_identity=identity,
            requested_input_paths={name: str(path) for name, path in requested.items()}),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record, *original.values()], retention=stage["artifact_retention"],
        expected_operation_ids=["scientific_analysis"], operation_dependencies={},
        expected_relative_paths=["."],
        action=partial(_run_action, requested=requested, original=original, config=config,
            seed=seed, identity=identity, resume_from=previous, max_workers=max_workers,
            stage=stage, policy_record=policy_record, legacy_protection=legacy),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        source_references=references, completion_api=no_particle_batch_completion_api)
    return artifact_root / "projects" / PROJECT_ID / "runs" / run_id


def execute(config_path: Path, *, input_root: Path, context: Any, seed: int,
            run_id: str, resume_from: Path | None = None, max_workers: int | None = None,
            receipt_root: Path | None = None) -> Path:
    """Run one explicitly selected scientific role; failed science still returns its run."""
    return _execute_role(config_path, input_root=input_root, context=context, seed=seed,
        run_id=run_id, resume_from=resume_from, max_workers=max_workers, receipt_root=receipt_root)


def main(argv: list[str] | None = None) -> int:
    """Select explicit scientific inputs; deployment is required only for execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--receipt-root", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--max-workers", type=int)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--resume-finalization", type=Path)
    parser.add_argument("--worker-request", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker_request is not None:
            if any(value is not None for value in (args.config, args.input_root, args.receipt_root,
                    args.seed, args.run_id, args.resume_from, args.max_workers, args.workspace,
                    args.environment, args.profile, args.resume_finalization)) or args.plan:
                raise ValueError("frozen worker accepts only its bound request")
            from msplatform.workflows.oa_tof_design import source_comparison
            source_comparison._scientific_worker(args.worker_request)
            return 0
        if args.resume_finalization is None:
            if args.config is None or args.input_root is None or args.seed is None:
                raise ValueError("scientific operation requires explicit config, input-root and seed")
            if args.plan:
                config, _ = _resolve_inputs(args.config, input_root=args.input_root,
                    receipt_root=args.receipt_root)
                plan = build_case_plan(config, args.seed) if config["role"] == "ideal_source_comparison" else config
                print(json.dumps(plan, indent=2))
                return 0
        elif (args.plan or any(value is not None for value in (args.config, args.input_root,
                args.receipt_root, args.seed, args.run_id, args.resume_from, args.max_workers))):
            raise ValueError("finalization-only cannot replace frozen scientific inputs")
        if args.workspace is None or args.environment is None or args.profile is None:
            raise ValueError("execution requires explicit workspace, environment and profile")
        from msplatform.execution.context import load_environment
        context = load_environment(args.environment, workspace=args.workspace, profile=args.profile)
        if args.resume_finalization is not None:
            from msplatform.execution.owner import resume_finalization
            from msplatform.execution.completion import no_particle_batch_completion_api
            result = resume_finalization(context, result_path=args.resume_finalization,
                completion_api=no_particle_batch_completion_api)
            return 0 if result["status"] == "success" else 1
        run_id = args.run_id or datetime.now(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y%m%d_%H%M%S__analysis__python__ideal-source-comparison")
        run_dir = execute(args.config, input_root=args.input_root, context=context,
            seed=args.seed, run_id=run_id, resume_from=args.resume_from,
            max_workers=args.max_workers, receipt_root=args.receipt_root)
        return 0 if load_json(run_dir / "summary.json")["status"] == "success" else 1
    except Exception as exc:
        print(f"IDEAL_COMPARISON STATUS=failed REASON={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
