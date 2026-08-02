"""Atomically publish one current-identity oa-TOF Formal release."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from common.contracts.artifact_naming import validate_archive_id
from common.contracts.file_identity import file_sha256 as sha256
from common.contracts.write_formal_asset_manifest import (
    record as file_record,
    write_formal_asset_manifest,
)


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT.parent / "artifacts/projects" / PROJECT_ID
CONFIG_PATHS = {
    name: PROJECT_ROOT / "config" / f"{name}.json"
    for name in ("formal_assets", "simion_stable_entry", "formal_validation", "project")
}
REQUIRED_ROLES = {
    "comsol_model", "simion_iob", "simion_con", "simion_program", "simion_fly2", "shared_particle_table",
    "solidworks_assembly", "cad_export_report", "comsol_particles", "comsol_report",
    "simion_particles", "simion_summary", "comparison",
}
GUI_CONTRACTS = {
    "comsol_gui": ("oa_tof_comsol_gui_gate", {"comsol_model"}),
    "simion_gui": (
        "oa_tof_simion_gui_gate", {"simion_iob", "simion_con", "simion_program"}
    ),
    "cad": ("oa_tof_cad_gate", {"solidworks_assembly", "cad_export_report"}),
}
CANONICAL_DESTINATIONS = {
    "comsol_model": "comsol/single_reflection_oa_tof_mass_analyzer__model.mph",
    "simion_iob": "simion/oatof_ideal_grounded.iob", "simion_con": "simion/oatof_ideal_grounded.con",
    "simion_program": "simion/oatof_ideal_grounded.lua", "simion_fly2": "simion/oatof_ideal_grounded.fly2",
    "shared_particle_table": "simion/oatof_comsol_524amu_gaussian_N1000.ion",
    "solidworks_assembly": "cad/single_reflection_oa_tof_mass_analyzer__model_physical_components.SLDASM",
    "cad_export_report": "cad/oaTOF_solidworks_export_report.json",
}
def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )


def relative_path(value: str, allowed_roots: set[str] | None = None) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    if allowed_roots and pure.parts[0] not in allowed_roots:
        raise ValueError(f"path is outside allowed roots: {value!r}")
    return Path(*pure.parts)


def verify_run(run: Path, run_id: str) -> set[Path]:
    manifest = load_json(run / "run_manifest.json")
    if (
        run.name != run_id or manifest.get("run_id") != run_id
        or manifest.get("project") != PROJECT_ID or manifest.get("status") != "success"
    ):
        raise ValueError(f"source run is not successful: {run_id}")
    records = [manifest["run_config"], *manifest.get("inputs", {}).values()]
    records.extend(manifest.get("outputs", []))
    verified: set[Path] = set()
    for record in records:
        path = Path(record["path"]).resolve(strict=True)
        path.relative_to(run.resolve())
        if path.stat().st_size != int(record["bytes"]) or sha256(path) != str(
            record["sha256"]
        ).upper():
            raise ValueError(f"{run_id} manifest record changed: {path}")
        verified.add(path)
    for required in ("run_config.json", "summary.json"):
        path = (run / required).resolve(strict=True)
        if path not in verified:
            raise ValueError(f"{run_id} manifest does not freeze {required}")
    return verified


def source_file(run: Path, value: str, verified: set[Path]) -> Path:
    path = (run / relative_path(value)).resolve(strict=True)
    path.relative_to(run.resolve())
    if path not in verified:
        raise ValueError(f"promotion source is not frozen by its run manifest: {path}")
    return path


def validate_runs(request: dict, candidate: Path, validation: Path,
                  verified: dict[str, set[Path]]) -> None:
    candidate_summary = load_json(candidate / "summary.json")
    candidate_diff = load_json(
        source_file(candidate, "inputs/candidate_diff.json", verified["candidate"])
    )
    acceptance_ref = request["evidence"]["candidate_acceptance"]
    if acceptance_ref.get("source_run") != "candidate":
        raise ValueError("candidate acceptance must come from the candidate run")
    acceptance = load_json(
        source_file(candidate, acceptance_ref["path"], verified["candidate"])
    )
    if (
        candidate_summary.get("candidate_decision") != "candidate_accepted_not_promoted"
        or candidate_summary.get("formal_modified") is not False
        or candidate_summary.get("promotion_authorized") is not False
        or candidate_diff.get("zero_change_reference_reproduction") is not True
        or candidate_diff.get("changed_variables") != []
        or candidate_diff.get("derived_changes") != []
        or acceptance.get("role") != "oa_tof_candidate_acceptance"
        or acceptance.get("status") != "success"
        or acceptance.get("formal_modified") is not False
        or acceptance.get("promotion_authorized") is not False
    ):
        raise ValueError("candidate is not accepted zero-physics-change evidence")
    summary = load_json(validation / "summary.json")
    if (
        summary.get("role") != "oa_tof_formal_vnext_validation_summary"
        or summary.get("status") != "success" or summary.get("particles") != 1000
        or summary.get("formal_modified") is not False
        or summary.get("promotion_authorized") is not False
    ):
        raise ValueError("validation run is not promotable N=1000 evidence")


def stage_assets(request: dict, roots: dict[str, Path],
                 verified: dict[str, set[Path]], staging: Path) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    destinations: set[Path] = set()
    for mapping in request.get("assets", []):
        role, scope = mapping.get("role"), mapping.get("source_run")
        if not role or role in assets or scope not in roots:
            raise ValueError(f"invalid asset mapping: {mapping!r}")
        source = source_file(roots[scope], mapping["source"], verified[scope])
        destination = staging / relative_path(
            mapping["destination"], {"comsol", "simion", "cad", "results"}
        )
        if role in CANONICAL_DESTINATIONS and mapping["destination"] != CANONICAL_DESTINATIONS[role]:
            raise ValueError(f"noncanonical Formal destination for {role}")
        if destination in destinations:
            raise ValueError(f"duplicate Formal destination: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256(source) != sha256(destination):
            raise ValueError(f"staged copy SHA differs: {source}")
        assets[role], destinations = destination, destinations | {destination}
    missing = REQUIRED_ROLES - set(assets)
    if missing:
        raise ValueError(f"promotion request lacks roles: {sorted(missing)}")
    return assets


def stage_simion_bundle(
    request: dict, roots: dict[str, Path], verified: dict[str, set[Path]],
    staging: Path,
) -> dict[str, Path]:
    spec = request.get("simion_bundle", {})
    if (
        spec.get("source_run") != "validation"
        or spec.get("destination") != "simion"
    ):
        raise ValueError("SIMION bundle must bind the validation run to formal/simion")
    source_root = (
        roots["validation"] / relative_path(str(spec.get("source_root", "")))
    ).resolve(strict=True)
    source_root.relative_to(roots["validation"].resolve())
    actual = sorted(path.resolve() for path in source_root.rglob("*") if path.is_file())
    frozen = sorted(path for path in verified["validation"] if source_root in path.parents)
    if actual != frozen:
        raise ValueError("SIMION bundle differs from validation manifest-frozen files")
    required_pa = {
        "accelerator.pa#", "reflectron.pa#",
        "detector_ground.pa#", "flight_tube_ground.pa#",
    }
    if not required_pa.issubset({path.name for path in actual}):
        raise ValueError("SIMION bundle lacks required PA families")
    bundle: dict[str, Path] = {}
    for source in actual:
        source_relative = source.relative_to(source_root).as_posix()
        relative = (
            "source_SHA256SUMS.csv"
            if source_relative == "SHA256SUMS.csv"
            else source_relative
        )
        destination = staging / "simion" / Path(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and sha256(destination) != sha256(source):
            raise ValueError(f"explicit SIMION asset differs from bundle: {relative}")
        if not destination.exists():
            shutil.copy2(source, destination)
        bundle[relative] = destination
    return bundle


def verify_gui(request: dict, roots: dict[str, Path], verified: dict[str, set[Path]],
               assets: dict[str, Path], artifact_root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, (role, reviewed_roles) in GUI_CONTRACTS.items():
        reference = request["evidence"].get(name, {})
        scope = reference.get("source_run")
        if scope != "evidence":
            raise ValueError(f"{name} must come from the immutable evidence run")
        path = source_file(roots[scope], reference.get("path", ""), verified[scope])
        evidence = load_json(path)
        if (
            evidence.get("schema_version") != 1 or evidence.get("role") != role
            or evidence.get("project") != PROJECT_ID or evidence.get("status") != "PASS"
        ):
            raise ValueError(f"{name} evidence is not PASS")
        for asset_role in reviewed_roles:
            if str(evidence.get("reviewed_assets", {}).get(asset_role, "")).upper() != sha256(
                assets[asset_role]
            ):
                raise ValueError(f"{name} evidence SHA differs for {asset_role}")
        result[name] = file_record(path, artifact_root)
    return result


def write_hash_list(root: Path, *, exclude: frozenset[str] = frozenset()) -> Path:
    output = root / "SHA256SUMS.csv"
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path != output
        and path.relative_to(root).as_posix() not in exclude
    )
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("file", "bytes", "sha256"))
        writer.writeheader()
        for path in files:
            writer.writerow(file_record(path, root, key="file"))
    return output


def build_payloads(artifact_root: Path, staging: Path, assets: dict[str, Path],
                   validation_id: str, evidence_id: str,
                   gui: dict[str, dict], bundle: dict[str, Path]) -> dict[str, dict]:
    simion = staging / "simion"
    simion_delivery = simion / "run_manifest.json"
    simion_assets = {
        f"bundle_{index:03d}": file_record(path, simion)
        for index, path in enumerate(bundle.values(), start=1)
    }
    write_json(simion_delivery, {
        "schema_version": 1, "role": "oa_tof_simion_formal_delivery_manifest",
        "project": PROJECT_ID, "release_id": validation_id, "status": "success",
        "assets": simion_assets,
    })
    if "source_SHA256SUMS.csv" not in bundle:
        raise ValueError("SIMION bundle lacks source SHA256SUMS.csv")
    write_hash_list(simion, exclude=frozenset({"run_manifest.json"}))
    results_hashes = write_hash_list(staging / "results")
    comparison = load_json(assets["comparison"])
    simion_summary = load_json(assets["simion_summary"])
    report = {key: value for line in assets["comsol_report"].read_text(
        encoding="utf-8-sig").splitlines() if "=" in line
        for key, value in (line.split("=", 1),)}
    ion_count = sum(bool(line.strip()) for line in assets["shared_particle_table"].read_text(
        encoding="utf-8-sig").splitlines())
    if (
        comparison.get("schema_version") != 3 or comparison.get("status") != "PASS"
        or report.get("STATUS") != "PASS" or ion_count != 1000
        or simion_summary.get("Hit") != 1000 or simion_summary.get("Emitted") != 1000
        or comparison["left"]["metrics"]["particles"] != 1000
        or comparison["right"]["metrics"]["particles"] != 1000
    ):
        raise ValueError("staged N=1000 solver/analysis evidence is not PASS")
    formal = lambda path: "formal/" + path.relative_to(staging).as_posix()
    baseline = PROJECT_ROOT / "config/baseline.json"
    analysis = PROJECT_ROOT / "config/analysis_contract.json"
    formal_validation = {
        "schema_version": 5, "status": "formal_cross_solver_validation",
        "validated_on": date.today().isoformat(), "run_id": validation_id,
        "validation_scope": "validated_candidate_assets_promoted_atomically_to_current_formal",
        "physical_contract": "baseline.json", "physical_contract_sha256": sha256(baseline),
        "analysis_contract": "analysis_contract.json", "analysis_contract_sha256": sha256(analysis),
        "shared_particles": {
            "particles": 1000, "ion_table_artifact_relative_path": formal(assets["shared_particle_table"]),
            "ion_table_sha256": sha256(assets["shared_particle_table"]),
        },
        "comsol": {
            "formal_mph_artifact_relative_path": formal(assets["comsol_model"]),
            "formal_mph_sha256": sha256(assets["comsol_model"]),
            "particle_csv_artifact_relative_path": formal(assets["comsol_particles"]),
            "particle_csv_sha256": sha256(assets["comsol_particles"]), "metrics": comparison["left"]["metrics"],
        },
        "simion": {
            "iob_artifact_relative_path": formal(assets["simion_iob"]), "iob_sha256": sha256(assets["simion_iob"]),
            "delivery_manifest_artifact_relative_path": formal(simion_delivery),
            "delivery_manifest_sha256": sha256(simion_delivery),
            "particle_csv_artifact_relative_path": formal(assets["simion_particles"]),
            "particle_csv_sha256": sha256(assets["simion_particles"]), "metrics": comparison["right"]["metrics"],
        },
        "comparison": comparison["comparison"], "comparison_artifact_relative_path": formal(assets["comparison"]),
        "comparison_artifact_sha256": sha256(assets["comparison"]),
        "promotion_evidence": {
            "validation_run_manifest_artifact_relative_path": f"runs/{validation_id}/run_manifest.json",
            "validation_run_manifest_sha256": sha256(
                artifact_root / "runs" / validation_id / "run_manifest.json"
            ),
            "evidence_run_manifest_artifact_relative_path": f"runs/{evidence_id}/run_manifest.json",
            "evidence_run_manifest_sha256": sha256(
                artifact_root / "runs" / evidence_id / "run_manifest.json"
            ),
            **{
                f"{name}_{key}": value
                for name, item in gui.items() for key, value in (
                    ("artifact_relative_path", item["path"]), ("sha256", item["sha256"])
                )
            },
        },
    }
    cad = load_json(assets["cad_export_report"])["solidWorks"]
    with results_hashes.open(encoding="utf-8") as stream:
        results_count = sum(1 for _ in csv.DictReader(stream))
    formal_assets = {
        "schema_version": 2, "role": "oa_tof_formal_model_and_cad_asset_identity",
        "verified_on": date.today().isoformat(), "release_id": validation_id,
        "comsol": {"geometry_status": "synchronized", "artifact_relative_path": formal(assets["comsol_model"]),
                   "sha256": sha256(assets["comsol_model"])},
        "solidworks": {
            "geometry_status": "synchronized", "revision": cad["solidWorksRevision"],
            "component_count": cad["partCount"], "assembly_artifact_relative_path": formal(assets["solidworks_assembly"]),
            "assembly_sha256": sha256(assets["solidworks_assembly"]),
            "export_report_artifact_relative_path": formal(assets["cad_export_report"]),
            "export_report_sha256": sha256(assets["cad_export_report"]),
        },
        "results": {
            "status": "formal_vnext_zero_physics_change_n1000",
            "source_run_id": validation_id, "artifact_relative_path": "formal/results",
            "sha256_manifest_relative_path": formal(results_hashes),
            "sha256_manifest_bytes": results_hashes.stat().st_size,
            "sha256_manifest_sha256": sha256(results_hashes),
            "manifest_file_count": results_count},
        "simion_manifest": "simion_stable_entry.json",
    }
    project = load_json(CONFIG_PATHS["project"])
    project["lifecycle_status"], project["formal_assets"]["status"] = "formal", "formal"
    for capability in project["capabilities"]:
        if capability["capability_id"] == "single_reflection_mass_analysis":
            capability["status"] = "formal"
    return {"formal_assets": formal_assets, "formal_validation": formal_validation,
            "project": project}


def build_stable_entry(staging: Path) -> dict:
    """Bind runtime requirements to the two authoritative release manifests."""
    manifest_paths = {
        "formal_asset_manifest": staging / "asset_manifest.json",
        "simion_delivery_manifest": staging / "simion/run_manifest.json",
    }
    return {
        "schema_version": 2, "frozen_on": date.today().isoformat(),
        "role": "Stable runtime requirements and manifest bindings for the current formal SIMION delivery.",
        "artifact_workspace_relative": "formal",
        "entries": [{
            "id": "formal_vnext_524amu_split_layer_n1000",
            "manifests": {
                role: file_record(path, staging, key="relative_path")
                for role, path in manifest_paths.items()
            },
            "required_assets": {
                "iob": "simion_iob", "con": "simion_con",
                "program": "simion_program", "fly2": "simion_fly2",
                "ion": "shared_particle_table",
            },
            "gui_requirements": {"expected_instances": 4, "trajectory_quality": 8,
                                 "program_enabled": True, "data_recording_enabled": True},
        }],
    }


def write_release_asset_manifest(artifact_root: Path, staging: Path, validation_id: str,
                                 assets: dict[str, Path], bundle: dict[str, Path],
                                 payloads: dict[str, dict]) -> None:
    validation_bytes = (
        json.dumps(payloads["formal_validation"], indent=2, ensure_ascii=False) + "\n"
    ).encode()
    release_assets = dict(assets)
    recorded_paths = {
        path.resolve().relative_to(staging.resolve()).as_posix()
        for path in release_assets.values()
    }
    for index, path in enumerate(bundle.values(), start=1):
        relative = path.resolve().relative_to(staging.resolve()).as_posix()
        if path.name != "SHA256SUMS.csv" and relative not in recorded_paths:
            release_assets[f"simion_bundle_{index:03d}"] = path
            recorded_paths.add(relative)
    for role, path in {
        "simion_delivery_manifest": staging / "simion/run_manifest.json",
        "simion_sha256_manifest": staging / "simion/SHA256SUMS.csv",
        "formal_results_manifest": staging / "results/SHA256SUMS.csv",
    }.items():
        release_assets[role] = path
    run = artifact_root / "runs" / validation_id
    manifest = write_formal_asset_manifest(
        destination=staging / "asset_manifest.json",
        formal_root=staging,
        project=PROJECT_ID,
        source_run_id=validation_id,
        source_run_root=run,
        validation_contract_path=CONFIG_PATHS["formal_validation"].relative_to(
            REPOSITORY_ROOT
        ).as_posix(),
        validation_contract_bytes=validation_bytes,
        assets=release_assets,
    )
    for item in manifest["assets"].values():
        path = staging / item["path"]
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise ValueError(f"staged asset verification failed: {path}")


def validate_recovery_release(formal: Path, release_id: str) -> dict:
    """Validate the immutable identity around a same-release byte recovery."""
    manifest_path = formal / "asset_manifest.json"
    manifest = load_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("role") != "formal_asset_manifest"
        or manifest.get("project") != PROJECT_ID
        or manifest.get("release_id") != release_id
    ):
        raise ValueError("current Formal manifest is not the requested release")
    validation = load_json(CONFIG_PATHS["formal_validation"])
    assets = load_json(CONFIG_PATHS["formal_assets"])
    project = load_json(CONFIG_PATHS["project"])
    stable = load_json(CONFIG_PATHS["simion_stable_entry"])
    entries = stable.get("entries", [])
    entry = entries[0] if len(entries) == 1 else {}
    if (
        validation.get("run_id") != release_id
        or assets.get("release_id") != release_id
        or project.get("lifecycle_status") != "formal"
        or stable.get("artifact_workspace_relative") != "formal"
        or entry.get("manifests", {}).get("formal_asset_manifest")
        != file_record(manifest_path, formal, key="relative_path")
    ):
        raise ValueError("current Formal contracts do not bind the requested release")
    return manifest


def recovery_sources(
    request: dict, roots: dict[str, Path], verified: dict[str, set[Path]]
) -> dict[str, Path]:
    """Map Formal-relative paths to immutable run files without copying them."""
    sources: dict[str, Path] = {}
    for mapping in request.get("assets", []):
        scope = mapping.get("source_run")
        if scope not in roots:
            raise ValueError(f"invalid recovery asset mapping: {mapping!r}")
        relative = relative_path(
            mapping["destination"], {"comsol", "simion", "cad", "results"}
        ).as_posix()
        if relative in sources:
            raise ValueError(f"duplicate recovery destination: {relative}")
        sources[relative] = source_file(
            roots[scope], mapping["source"], verified[scope]
        )
    spec = request.get("simion_bundle", {})
    if spec.get("source_run") != "validation" or spec.get("destination") != "simion":
        raise ValueError("SIMION recovery source must be the validation bundle")
    source_root = (
        roots["validation"] / relative_path(str(spec.get("source_root", "")))
    ).resolve(strict=True)
    source_root.relative_to(roots["validation"].resolve())
    actual = sorted(path.resolve() for path in source_root.rglob("*") if path.is_file())
    frozen = sorted(path for path in verified["validation"] if source_root in path.parents)
    if actual != frozen:
        raise ValueError("SIMION recovery bundle differs from validation manifest")
    for source in actual:
        source_relative = source.relative_to(source_root).as_posix()
        name = "source_SHA256SUMS.csv" if source_relative == "SHA256SUMS.csv" else source_relative
        destination = f"simion/{name}"
        prior = sources.get(destination)
        if prior is not None and sha256(prior) != sha256(source):
            raise ValueError(f"recovery sources disagree for {destination}")
        sources[destination] = source
    return sources


def verify_manifest_assets(formal: Path, manifest: dict) -> list[dict]:
    """Return manifest records whose current bytes are absent or changed."""
    drifted: list[dict] = []
    for role, record in manifest.get("assets", {}).items():
        relative = relative_path(str(record.get("path", "")))
        path = (formal / relative).resolve()
        path.relative_to(formal.resolve())
        matches = (
            path.is_file()
            and path.stat().st_size == int(record.get("bytes", -1))
            and sha256(path) == str(record.get("sha256", "")).upper()
        )
        if not matches:
            drifted.append({"role": role, "record": record, "path": path})
    return drifted


def recover(
    request_path: Path,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    *,
    replace: Callable[[os.PathLike, os.PathLike], None] = os.replace,
) -> dict:
    """Restore changed assets of the current release from manifest-frozen sources."""
    request_path = request_path.resolve(strict=True)
    artifact_root = artifact_root.resolve(strict=True)
    request = load_json(request_path)
    if (request.get("schema_version"), request.get("role"), request.get("project")) != (
        1, "oa_tof_formal_vnext_promotion_request", PROJECT_ID
    ):
        raise ValueError("invalid recovery request identity")
    release_id = request["validation_run_id"]
    formal = (artifact_root / "formal").resolve(strict=True)
    manifest = validate_recovery_release(formal, release_id)
    ids = {
        "candidate": request["candidate_run_id"],
        "validation": release_id,
        "evidence": request["evidence_run_id"],
    }
    roots = {name: artifact_root / "runs" / run_id for name, run_id in ids.items()}
    verified = {name: verify_run(roots[name], ids[name]) for name in roots}
    validate_runs(request, roots["candidate"], roots["validation"], verified)
    sources = recovery_sources(request, roots, verified)
    drifted = verify_manifest_assets(formal, manifest)
    if not drifted:
        return {"status": "already_verified", "release_id": release_id, "asset_count": 0}

    transaction = sha256(request_path)[:16].lower()
    staging = artifact_root / f".formal-recovery-staging-{transaction}"
    if staging.exists():
        raise FileExistsError(f"recovery staging already exists: {staging}")
    try:
        for item in drifted:
            record = item["record"]
            relative = str(record["path"])
            source = sources.get(relative)
            if source is None:
                raise ValueError(f"drifted generated Formal asset requires republication: {relative}")
            if source.stat().st_size != int(record["bytes"]) or sha256(source) != record["sha256"]:
                raise ValueError(f"immutable recovery source differs from Formal manifest: {source}")
            destination = staging / relative_path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if destination.stat().st_size != int(record["bytes"]) or sha256(destination) != record["sha256"]:
                raise ValueError(f"staged recovery asset differs: {destination}")
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    archive_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "__failed-evidence__simion__formal-asset-drift"
    validate_archive_id(archive_id)
    archive = artifact_root / "archive" / archive_id
    if archive.exists():
        raise FileExistsError(f"recovery archive already exists: {archive}")
    archive.mkdir(parents=True)
    archived_records: list[dict] = []
    for item in drifted:
        relative = str(item["record"]["path"])
        current = item["path"]
        archived = archive / "changed-assets" / relative_path(relative)
        archived.parent.mkdir(parents=True, exist_ok=True)
        if current.is_file():
            shutil.copy2(current, archived)
            archived_records.append({
                "role": item["role"], "formal_path": relative,
                "expected_sha256": item["record"]["sha256"],
                "actual_bytes": archived.stat().st_size,
                "actual_sha256": sha256(archived),
                "archived_path": archived.relative_to(archive).as_posix(),
            })
        else:
            archived_records.append({
                "role": item["role"], "formal_path": relative,
                "expected_sha256": item["record"]["sha256"],
                "actual_bytes": None, "actual_sha256": None, "archived_path": None,
            })
    archive_manifest = {
        "schema_version": 1, "role": "formal_asset_recovery_archive",
        "archive_id": archive_id, "project": PROJECT_ID, "status": "prepared",
        "release_id": release_id, "promotion_request_sha256": sha256(request_path),
        "assets": archived_records,
    }
    write_json(archive / "archive_manifest.json", archive_manifest)

    replaced: list[dict] = []
    try:
        for item in drifted:
            relative = str(item["record"]["path"])
            replace(staging / relative_path(relative), item["path"])
            replaced.append(item)
        remaining = verify_manifest_assets(formal, manifest)
        if remaining:
            raise ValueError("Formal assets still differ after recovery")
    except Exception:
        for item in reversed(replaced):
            relative = str(item["record"]["path"])
            archived = archive / "changed-assets" / relative_path(relative)
            if archived.is_file():
                rollback = staging / "rollback" / relative_path(relative)
                rollback.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(archived, rollback)
                os.replace(rollback, item["path"])
        archive_manifest["status"] = "failed_and_rolled_back"
        write_json(archive / "archive_manifest.json", archive_manifest)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    archive_manifest["status"] = "complete"
    archive_manifest["restored_asset_count"] = len(drifted)
    write_json(archive / "archive_manifest.json", archive_manifest)
    return {
        "status": "success", "release_id": release_id,
        "asset_count": len(drifted), "archive": str(archive),
    }


def replace_configs(payloads: dict[str, dict], transaction: str,
                    replace: Callable[[os.PathLike, os.PathLike], None]) -> None:
    originals = {name: path.read_bytes() for name, path in CONFIG_PATHS.items()}
    replaced: list[str] = []
    temps: dict[str, Path] = {}
    try:
        for name, path in CONFIG_PATHS.items():
            temps[name] = path.with_name(f".{path.name}.{transaction}.tmp")
            write_json(temps[name], payloads[name])
        for name, path in CONFIG_PATHS.items():
            replace(temps[name], path)
            replaced.append(name)
    except Exception:
        for name in reversed(replaced):
            rollback = CONFIG_PATHS[name].with_name(f".{name}.{transaction}.rollback")
            rollback.write_bytes(originals[name])
            os.replace(rollback, CONFIG_PATHS[name])
        raise
    finally:
        for path in temps.values():
            if path.exists():
                path.unlink()


def promote(request_path: Path, artifact_root: Path = DEFAULT_ARTIFACT_ROOT, *,
            replace: Callable[[os.PathLike, os.PathLike], None] = os.replace) -> dict:
    request_path, artifact_root = request_path.resolve(strict=True), artifact_root.resolve()
    request = load_json(request_path)
    if (request.get("schema_version"), request.get("role"), request.get("project")) != (
        1, "oa_tof_formal_vnext_promotion_request", PROJECT_ID
    ):
        raise ValueError("invalid promotion request identity")
    formal = artifact_root / "formal"
    ids = {
        "candidate": request["candidate_run_id"],
        "validation": request["validation_run_id"],
        "evidence": request["evidence_run_id"],
    }
    roots = {name: artifact_root / "runs" / run_id for name, run_id in ids.items()}
    verified = {name: verify_run(roots[name], ids[name]) for name in roots}
    validate_runs(request, roots["candidate"], roots["validation"], verified)
    if formal.exists():
        raise FileExistsError(
            "current Formal release already exists; Publish cannot repair or overwrite it"
        )
    transaction = sha256(request_path)[:16].lower()
    staging = artifact_root / f".formal-vnext-staging-{transaction}"
    if staging.exists():
        raise FileExistsError(f"promotion staging already exists: {staging}")
    staging.mkdir(parents=True)
    assets = stage_assets(request, roots, verified, staging)
    bundle = stage_simion_bundle(request, roots, verified, staging)
    gui = verify_gui(request, roots, verified, assets, artifact_root)
    payloads = build_payloads(
        artifact_root, staging, assets, ids["validation"], ids["evidence"], gui,
        bundle,
    )
    write_release_asset_manifest(
        artifact_root, staging, ids["validation"], assets, bundle, payloads
    )
    payloads["simion_stable_entry"] = build_stable_entry(staging)
    replace(staging, formal)
    try:
        replace_configs(payloads, transaction, replace)
    except Exception:
        os.replace(formal, staging)
        raise
    return {"status": "success", "release_id": ids["validation"],
            "transaction_id": transaction,
            "asset_manifest_sha256": sha256(formal / "asset_manifest.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if args.recover:
        result = recover(args.request, args.artifact_root)
        print(
            f"FORMAL_RELEASE_RECOVERY=PASS RELEASE_ID={result['release_id']} "
            f"ASSETS={result['asset_count']}"
        )
    else:
        result = promote(args.request, args.artifact_root)
        print(f"FORMAL_RELEASE_PUBLICATION=PASS RELEASE_ID={result['release_id']}")


if __name__ == "__main__":
    main()
