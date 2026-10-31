"""Verify and copy the current Formal SIMION package to a disposable runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record as verify_run_record, _select_consumed_output
from common.contracts.write_run_manifest import file_record


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"unsafe Formal asset path: {value!r}")
    return Path(*pure.parts)


def verify_record(root: Path, record: dict) -> Path:
    path = (root / safe_relative(str(record.get("path", "")))).resolve(strict=True)
    path.relative_to(root.resolve(strict=True))
    if (
        not path.is_file()
        or path.stat().st_size != int(record.get("bytes", -1))
        or file_sha256(path) != str(record.get("sha256", "")).upper()
    ):
        raise ValueError(f"Formal SIMION asset identity differs: {path}")
    return path


def stage_runtime(artifact_root: Path, destination: Path, receipt: Path) -> dict:
    """Copy one manifest-verified SIMION package and write its source receipt."""
    artifact_root = artifact_root.resolve(strict=True)
    formal = (artifact_root / "formal").resolve(strict=True)
    manifest_path = formal / "asset_manifest.json"
    manifest = load_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("role") != "formal_asset_manifest"
        or manifest.get("project") != PROJECT_ID
    ):
        raise ValueError("Formal asset manifest identity differs")
    records = {
        role: record
        for role, record in manifest.get("assets", {}).items()
        if str(record.get("path", "")).startswith("simion/")
    }
    if not records:
        raise ValueError("Formal asset manifest has no SIMION package")
    expected_paths = {str(record["path"])[len("simion/") :] for record in records.values()}
    formal_simion = formal / "simion"
    actual_paths = {
        path.relative_to(formal_simion).as_posix()
        for path in formal_simion.rglob("*")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ValueError("Formal SIMION package file set differs from its asset manifest")

    destination = destination.resolve()
    destination.relative_to(artifact_root)
    if formal == destination or formal in destination.parents:
        raise ValueError("runtime destination must remain outside Formal")
    staging = destination.with_name(f".{destination.name}.staging")
    if destination.exists() or staging.exists():
        raise FileExistsError(f"SIMION runtime destination already exists: {destination}")
    try:
        staging.mkdir(parents=True)
        asset_receipts = []
        for role, record in sorted(records.items()):
            source = verify_record(formal, record)
            relative = str(record["path"])[len("simion/") :]
            target = staging / safe_relative(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if target.stat().st_size != int(record["bytes"]) or file_sha256(target) != record["sha256"]:
                raise ValueError(f"staged SIMION runtime asset differs: {target}")
            asset_receipts.append({"role": role, **record})
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    payload = {
        "schema_version": 1,
        "role": "oa_tof_formal_simion_runtime_receipt",
        "project": PROJECT_ID,
        "release_id": manifest["release_id"],
        "formal_asset_manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": file_sha256(manifest_path),
        },
        "assets": asset_receipts,
    }
    try:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return payload


def stage_diagnostic_inputs(source_run: Path, destination: Path, receipt: Path, cases: list[str]) -> dict:
    """Freeze only a terminal diagnostic's actual logs, ION tables and controls.

    The caller holds the existing terminal-consumption guard during this copy.
    No Formal package or solver installation is consulted on this branch.
    """
    source_run = source_run.resolve(strict=True)
    manifest_path = source_run / 'run_manifest.json'
    manifest = load_json(manifest_path)
    if manifest.get('status') not in {'success', 'failed', 'interrupted'}:
        raise ValueError('diagnostic analysis requires a terminal source run')
    config_path = record_path(manifest['run_config'], base_dir=source_run)
    config = load_json(config_path)
    if config.get('mode') != 'simion_ideal_field_matrix':
        raise ValueError('analysis source must be an ideal-field matrix run')
    count, seed = config.get('particles'), config.get('seed')
    if type(count) is not int or count < 1 or type(seed) is not int:
        raise ValueError('source diagnostic particle count and seed are missing or invalid')
    if not cases or len(cases) != len(set(cases)) or any(
            len(case.split('__')) != 2 or not all(part.replace('_', '').isalnum() for part in case.split('__'))
            for case in cases):
        raise ValueError('explicit diagnostic cases must be unique distribution/mode names')
    sources = {f'logs/{case}.log': source_run / 'logs' / f'{case}.log' for case in cases}
    sources.update({f'ions/ions_{case.split("__")[0]}_N{count}.ion':
        source_run / 'simion' / f'ions_{case.split("__")[0]}_N{count}.ion' for case in cases})
    command = [sys.executable, '-B', '-m', 'common.contracts.verify_run_manifest', str(manifest_path),
        '--require-status', manifest['status'], '--require-project', PROJECT_ID,
        '--require-run-id', source_run.name, '--require-mode', 'simion_ideal_field_matrix',
        '--require-local-run-config', '--consumer-projection-id', 'ideal_field_diagnostic_analysis']
    for path in sources.values():
        command.extend(['--consumed-output', str(path)])
    try:
        subprocess.run(command, cwd=Path(__file__).resolve().parents[3], timeout=None,
                       check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as error:
        error.add_note(error.stderr.strip() or error.stdout.strip())
        error.add_note("ACTION=provide_complete_manifest_bound_diagnostic_logs_and_original_ION_or_run_normal_diagnostic")
        raise
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f'diagnostic input destination already exists: {destination}')
    records = {}
    try:
        destination.mkdir(parents=True)
        for relative, source in sources.items():
            _, bound = _select_consumed_output(manifest['outputs'], source, base_dir=source_run)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            frozen = dict(bound, path=str(target))
            verify_run_record('frozen diagnostic input', frozen)
            if relative.startswith('ions/'):
                from projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics import read_ion_table
                if len(read_ion_table(target)) != count:
                    raise ValueError('source diagnostic ION count differs from its frozen run control')
            records[relative] = dict(frozen, source_path=str(source))
        for name, source, bound in (('source_run_config.json', config_path, manifest['run_config']),
                                    ('source_run_manifest.json', manifest_path, file_record(manifest_path))):
            target = destination / name
            shutil.copyfile(source, target)
            frozen = dict(bound, path=str(target))
            verify_run_record('frozen diagnostic authority', frozen)
            records[name] = dict(frozen, source_path=str(source))
        payload = dict(schema_version=1, role='oa_tof_ideal_field_analysis_source',
            source_run_id=manifest['run_id'], source_status=manifest['status'], particle_count=count,
            seed=seed, cases=cases, inputs=records)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8', newline='\n')
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument('--analysis-source-run', type=Path)
    parser.add_argument('--case', action='append', default=[])
    args = parser.parse_args()
    if args.analysis_source_run is not None:
        result = stage_diagnostic_inputs(args.analysis_source_run, args.destination, args.receipt, args.case)
        print(json.dumps(result))
        return
    result = stage_runtime(args.artifact_root, args.destination, args.receipt)
    print(
        f"FORMAL_SIMION_RUNTIME_STAGE=PASS RELEASE_ID={result['release_id']} "
        f"ASSETS={len(result['assets'])}"
    )


if __name__ == "__main__":
    main()
