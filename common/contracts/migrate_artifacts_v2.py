"""One-time, non-destructive migration to the repository artifact v2 layout.

The command defaults to a dry run.  ``--apply`` only moves files on the same
workspace volume and never deletes data.  Legacy trees are frozen below one
descriptive archive_id per project; only the qualified oa-TOF formal assets and
their current N=1000 cross-solver evidence are promoted into live locations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from artifact_naming import validate_archive_id, validate_run_id


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO.parent
PROJECTS = WORKSPACE / "artifacts" / "projects"
OA = PROJECTS / "oa_tof"
FORMAL_RUN_ID = "20260718_172003__sim__cross__formal-validation__n1000"
PROJECT_IDS = (
    "oa_tof",
    "rf_quadrupole_collision_cooling",
    "wehnelt_electron_gun",
    "electron_impact_ion_source",
)
LEGACY_ROOTS = ("models", "cad", "results", "runs", "scratch", "logs", "staging")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def ensure_under(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=False)
    resolved.relative_to(root.resolve())
    return resolved


def inventory(path: Path) -> dict[str, int]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return {"files": len(files), "bytes": sum(item.stat().st_size for item in files)}


class Migration:
    def __init__(self, apply: bool, stamp: str) -> None:
        self.apply = apply
        self.stamp = stamp
        self.operations: list[dict[str, str]] = []

    def move(self, source: Path, destination: Path) -> None:
        source = ensure_under(source, PROJECTS)
        destination = ensure_under(destination, PROJECTS)
        if not source.exists() and destination.exists():
            print(f"ALREADY {destination}")
            return
        if not source.exists():
            raise FileNotFoundError(source)
        if destination.exists():
            raise FileExistsError(destination)
        self.operations.append({"source": str(source), "destination": str(destination)})
        print(f"MOVE {source} -> {destination}")
        if self.apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)

    def write_json(self, destination: Path, value: dict) -> None:
        destination = ensure_under(destination, PROJECTS)
        print(f"WRITE {destination}")
        if self.apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )

    def move_tree(self, source: Path, destination: Path) -> None:
        """Merge-move a tree so an open Windows directory handle cannot block files."""
        source = ensure_under(source, PROJECTS)
        destination = ensure_under(destination, PROJECTS)
        if not source.exists() and destination.exists():
            print(f"ALREADY_TREE {destination}")
            return
        if not source.is_dir():
            raise FileNotFoundError(source)
        print(f"MOVE_TREE {source} -> {destination}")
        self.operations.append({"source": str(source), "destination": str(destination)})
        if not self.apply:
            return
        destination.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir(), key=lambda value: value.name.lower()):
            target = destination / item.name
            if item.is_dir():
                self.move_tree(item, target)
            else:
                if target.exists():
                    raise FileExistsError(target)
                os.replace(item, target)
        try:
            source.rmdir()
        except OSError as error:
            print(f"EMPTY_ROOT_RETAINED {source}: {error}")

    def write_text(self, destination: Path, value: str) -> None:
        destination = ensure_under(destination, PROJECTS)
        print(f"WRITE {destination}")
        if self.apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(value, encoding="utf-8")


def file_record(path: Path) -> dict:
    return {"path": str(path.resolve()), "exists": path.is_file(),
            "bytes": path.stat().st_size, "sha256": sha256(path)}


def relative_file_record(path: Path, root: Path) -> dict:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def migrate_oa_formal(migration: Migration) -> None:
    old_comsol = OA / "models" / "comsol" / "formal" / "MS_oaTOF_TwoStageRingStackReflectron_Final.mph"
    migration.move(old_comsol, OA / "formal" / "comsol" / "oa_tof__model.mph")

    old_simion = OA / "models" / "simion" / "formal" / "oatof_524amu"
    if old_simion.exists():
        for item in sorted(old_simion.iterdir(), key=lambda value: value.name.lower()):
            migration.move(item, OA / "formal" / "simion" / item.name)
    elif not (OA / "formal" / "simion").is_dir():
        raise FileNotFoundError(old_simion)

    old_cad = OA / "cad" / "formal"
    cad_names = {
        "MS_oaTOF_TwoStageRingStackReflectron_Final_physical_components.SLDASM": "oa_tof__assembly.SLDASM",
        "MS_oaTOF_TwoStageRingStackReflectron_Final_physical_components.step": "oa_tof__assembly.step",
        "MS_oaTOF_TwoStageRingStackReflectron_Final_physical_components_manifest.csv": "oa_tof__physical-components.csv",
        "MS_oaTOF_TwoStageRingStackReflectron_Final_parts": "parts",
        "MS_oaTOF_TwoStageRingStackReflectron_Final_individual_steps": "individual_steps",
        "oaTOF_solidworks_export_report.json": "export_report.json",
    }
    if old_cad.exists():
        for item in sorted(old_cad.iterdir(), key=lambda value: value.name.lower()):
            migration.move(item, OA / "formal" / "cad" / cad_names.get(item.name, item.name))
    elif not (OA / "formal" / "cad").is_dir():
        raise FileNotFoundError(old_cad)


def migrate_oa_formal_run(migration: Migration) -> None:
    validate_run_id(FORMAL_RUN_ID)
    old_run = OA / "runs" / "formal_validation" / "current_assets_n1000_20260718"
    old_results = OA / "results" / "cross_solver" / "formal_validation" / "current_assets_n1000_20260718"
    new_run = OA / "runs" / FORMAL_RUN_ID
    result_names = {
        "comsol_particles.csv", "simion_particles.csv", "simion_summary.json",
        "comsol_fixedN1000_selected_release_from_data_file.txt",
    }
    log_names = {"comsol_report.txt", "simion.log", "simion.stderr.log"}
    log_rename = {"simion.log": "simion_stdout.log", "simion.stderr.log": "simion_stderr.log"}
    for item in sorted(old_run.iterdir(), key=lambda value: value.name.lower()):
        if item.name in result_names:
            destination = new_run / "results" / item.name
        elif item.name in log_names:
            destination = new_run / "logs" / log_rename.get(item.name, item.name)
        else:
            destination = new_run / "results" / item.name
        migration.move(item, destination)
    for item in sorted(old_results.iterdir(), key=lambda value: value.name.lower()):
        migration.move(item, new_run / "results" / item.name)

    config = {
        "schema_version": 1, "run_id": FORMAL_RUN_ID, "project": "oa_tof",
        "mode": "formal_cross_solver_validation", "project_root": str(OA),
        "formal_gate_passed": True,
        "inputs": {
            "formal_mph": str(OA / "formal" / "comsol" / "oa_tof__model.mph"),
            "ion_table": str(OA / "formal" / "simion" / "oatof_comsol_524amu_gaussian_N1000.ion"),
            "simion_iob": str(OA / "formal" / "simion" / "oatof_ideal_grounded.iob"),
        },
        "parameters": {"mass_amu": 524, "particles": 1000, "migration_only": True},
    }
    migration.write_json(new_run / "run_config.json", config)
    migration.write_json(new_run / "summary.json", {
        "schema_version": 1, "role": "oa_tof_formal_cross_solver_summary",
        "status": "success", "particles": 1000,
        "comparison_metrics": "results/comparison_metrics.json",
        "note": "Legacy evidence reorganized without rerunning either solver.",
    })


def rewrite_oa_manifests(migration: Migration) -> None:
    if not migration.apply:
        return
    simion = OA / "formal" / "simion"
    simion_config_path = simion / "run_config.json"
    simion_config = json.loads(simion_config_path.read_text(encoding="utf-8-sig"))
    simion_config.update(
        run_id="20260719_111417__build__simion__formal-delivery__n1000",
        output_dir=str(simion),
        promotion_evidence="archive_manifest.json records the pre-v2 source path",
    )
    simion_config_path.write_text(json.dumps(simion_config, indent=2) + "\n", encoding="utf-8")
    simion_outputs = [simion / name for name in (
        "oatof_ideal_grounded.iob", "oatof_ideal_grounded.lua",
        "oatof_ideal_grounded.fly2", "SHA256SUMS.csv",
    )]
    simion_manifest = {
        "schema_version": 1, "role": "simulation_run_manifest",
        "run_id": simion_config["run_id"], "project": "oa_tof", "mode": "formal_delivery",
        "status": "success", "recorded_at_utc": "2026-07-19T03:14:17.105123+00:00",
        "software": ["SIMION 2020"], "run_config": file_record(simion_config_path),
        "inputs": {name: file_record(REPO / "projects" / "oa_tof" / value)
                   for name, value in simion_config["inputs"].items()},
        "outputs": [file_record(path) for path in simion_outputs], "formal_eligible": True,
    }
    (simion / "run_manifest.json").write_text(
        json.dumps(simion_manifest, indent=2) + "\n", encoding="utf-8"
    )

    run = OA / "runs" / FORMAL_RUN_ID
    run_config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
    outputs = sorted((run / "results").iterdir()) + sorted((run / "logs").iterdir()) + [run / "summary.json"]
    run_manifest = {
        "schema_version": 1, "role": "simulation_run_manifest", "run_id": FORMAL_RUN_ID,
        "project": "oa_tof", "mode": "formal_cross_solver_validation", "status": "success",
        "recorded_at_utc": "2026-07-18T09:34:15+00:00", "software": ["COMSOL R2025b", "SIMION 2020"],
        "run_config": file_record(run / "run_config.json"),
        "inputs": {name: file_record(Path(value)) for name, value in run_config["inputs"].items()},
        "outputs": [file_record(path) for path in outputs], "formal_eligible": True,
    }
    (run / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")

    asset_manifest = {
        "schema_version": 1, "role": "formal_asset_manifest", "project": "oa_tof",
        "release_id": "20260719_111417__build__cross__formal-assets__n1000",
        "recorded_at_utc": "2026-07-19T03:14:17.105123+00:00",
        "source_run": {
            "run_id": FORMAL_RUN_ID,
            "path": f"runs/{FORMAL_RUN_ID}",
            "run_config": relative_file_record(run / "run_config.json", OA),
            "summary": relative_file_record(run / "summary.json", OA),
            "run_manifest": relative_file_record(run / "run_manifest.json", OA),
        },
        "validation_contract": relative_file_record(
            REPO / "projects" / "oa_tof" / "config" / "formal_validation.json", REPO
        ),
        "assets": {
            "comsol_model": relative_file_record(
                OA / "formal" / "comsol" / "oa_tof__model.mph", OA / "formal"
            ),
            "solidworks_assembly": relative_file_record(
                OA / "formal" / "cad" / "oa_tof__assembly.SLDASM", OA / "formal"
            ),
            "simion_delivery_manifest": relative_file_record(
                simion / "run_manifest.json", OA / "formal"
            ),
        },
        "former_names": {
            "comsol_model": "MS_oaTOF_TwoStageRingStackReflectron_Final.mph",
            "solidworks_assembly": "MS_oaTOF_TwoStageRingStackReflectron_Final_physical_components.SLDASM",
        },
    }
    (OA / "formal" / "asset_manifest.json").write_text(
        json.dumps(asset_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def archive_legacy_roots(migration: Migration) -> None:
    recorded = datetime.now(timezone.utc).isoformat()
    for project_id in PROJECT_IDS:
        project = PROJECTS / project_id
        archive_id = f"{migration.stamp}__migration-snapshot__repo__pre-v2-layout"
        validate_archive_id(archive_id)
        archive = project / "archive" / archive_id
        roots = []
        for name in LEGACY_ROOTS:
            source = project / name
            existing_destination = archive / "legacy-layout" / name
            if source.exists():
                if project_id == "oa_tof" and name == "runs":
                    for item in sorted(source.iterdir(), key=lambda value: value.name.lower()):
                        if item.name == FORMAL_RUN_ID:
                            continue
                        stats = inventory(item) if item.is_dir() else {
                            "files": 1, "bytes": item.stat().st_size,
                        }
                        roots.append({"source": str(item),
                                      "destination": f"legacy-layout/runs/{item.name}", **stats})
                        migration.move_tree(item, archive / "legacy-layout" / "runs" / item.name)
                    continue
                stats = inventory(source)
                roots.append({"source": str(source), "destination": f"legacy-layout/{name}", **stats})
                destination_root = archive / "legacy-layout" / name
                migration.move_tree(source, destination_root)
                if migration.apply:
                    roots[-1].update(inventory(destination_root))
            elif existing_destination.exists():
                stats = inventory(existing_destination)
                roots.append({"source": str(source), "destination": f"legacy-layout/{name}", **stats})
        migration.write_json(archive / "archive_manifest.json", {
            "schema_version": 1, "role": "artifact_archive_manifest",
            "archive_id": archive_id, "project": project_id,
            "reason": "migration-snapshot", "recorded_at_utc": recorded,
            "source_layout": "artifact-v1", "replacement_layout": "artifact-v2",
            "roots": roots, "deletion_performed": False,
        })


def write_navigation(migration: Migration) -> None:
    for project_id in PROJECT_IDS:
        formal = "formal/   current gate-qualified assets\n" if project_id == "oa_tof" else "formal/   absent: no current asset has passed the formal gates\n"
        migration.write_text(PROJECTS / project_id / "00_README.txt", (
            f"PROJECT: {project_id}\n\n"
            f"{formal}runs/     self-contained current runs, named by run_id\n"
            "archive/  frozen evidence, named by archive_id\n"
            "scratch/  disposable active work only; never a citation source\n\n"
            "Authoritative rules and project status are in simulation_repo, not this file.\n"
        ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--stamp", help="Shanghai local YYYYMMDD_HHMMSS")
    args = parser.parse_args()
    # This workspace contract fixes folder timestamps to the Windows host's
    # Asia/Shanghai local clock.  Avoid an optional tzdata dependency here.
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    migration = Migration(args.apply, stamp)
    migrate_oa_formal(migration)
    migrate_oa_formal_run(migration)
    archive_legacy_roots(migration)
    write_navigation(migration)
    rewrite_oa_manifests(migration)
    print(f"ARTIFACT_MIGRATION={'APPLIED' if args.apply else 'DRY_RUN'} OPERATIONS={len(migration.operations)}")


if __name__ == "__main__":
    main()
