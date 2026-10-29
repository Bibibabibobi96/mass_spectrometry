"""Admit frozen real upstream states; no sampling, propagation or transforms.

The assembly workflow owns raw mechanical-exit validation and its single
local-to-assembly projection. IP consumes these already native-frame states.
Arrival starts IP integration; original birth remains the particle-age origin.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.analysis.particle_census import partition_cohort
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.component_particle_state import load_component_particle_state_csv
from common.contracts.machine_contracts import validate_schema
from common.contracts.verify_run_manifest import record_path, verified_successful_run_reference, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication

SCHEMA = Path(__file__).resolve().parent / "schemas/ip_injected_source.schema.json"
FATE_COLUMNS = ["particle_id", "particle_birth_time_us", "mass_amu", "charge_state",
                "terminal_instrument_time_us", "terminal_reason", "particle_weight"]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def injected_source_protection_paths(contract_path: Path) -> list[Path]:
    """Project exact source authorities for capacity admission before freezing."""
    path = Path(contract_path).resolve(strict=True)
    contract = _json(path)
    validate_schema(contract, SCHEMA)
    protected = {path.parent}
    for name in ("clock_authority", "source_states", "mother_census", "mother_fates", "producer_manifest",
                 "preparation_manifest", "preparation_source"):
        if contract.get(name) is not None:
            target = record_path(contract[name], base_dir=path.parent)
            protected.add(target.parent)
            if name == "clock_authority":
                clock = _json(target)
                protected.add((target.parent.parent / clock["authority"]["path"]).resolve().parent)
            if name == "producer_manifest":
                producer = _json(target)
                if isinstance(producer.get("run_config"), dict):
                    protected.add(record_path(producer["run_config"], base_dir=target.parent).parent)
    # An unfrozen source in the standard assembly layout is bound by its
    # containing run manifest, even when older package schemas lack fields.
    candidate = path.parent.parent.parent
    if (candidate / "run_config.json").is_file():
        protected.add(candidate)
    return sorted(protected)


def _published_producer_result(manifest_path: Path, source_path: Path, producer_path: Path) -> dict[str, Any]:
    """Verify the assembly-owned source and its recorded producer conclusion."""
    root, source = manifest_path.resolve().parent, source_path.resolve()
    manifest = _json(manifest_path)
    if manifest.get("run_id") != root.name:
        raise ValueError("handoff run identity differs")
    try:
        relative = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("handoff source is outside its publishing run") from exc
    options = dict(project="instrument_assembly", mode="multipole_ip_preparation", manifest=manifest)
    verified_successful_run_reference(root, relative, **options)
    receipt_path = verified_successful_run_reference(root, "results/multipole_ip/preparation_receipt.json", **options)
    receipt = _json(receipt_path)
    if receipt.get("role") != "multipole_ip_preparation" or receipt.get("status") != "success":
        raise ValueError("handoff preparation receipt differs")
    source_record, producer_record = receipt["injected_source"], receipt["source"]["manifest"]
    if record_path(source_record, base_dir=root) != source:
        raise ValueError("handoff source identity differs from handoff receipt")
    verify_record("handoff source", source_record, base_dir=root)
    require_completed_terminal_publication(record_path(producer_record, base_dir=root))
    verify_record("producer manifest", producer_record, base_dir=root)
    copied = file_record(producer_path)
    if any(copied[key] != producer_record[key] for key in ("bytes", "sha256")):
        raise ValueError("producer manifest identity differs from handoff receipt")
    result = receipt.get("producer_result")
    if not isinstance(result, dict) or result.get("source_scientific_status") not in {"success", "failed"}:
        raise ValueError("handoff producer result is incomplete")
    if result["source_scientific_status"] != _json(producer_path).get("status"):
        raise ValueError("handoff producer result differs from producer terminal status")
    return result


def load_injected_source(contract_path: Path) -> dict[str, Any]:
    """Verify a provider input package once and return actual states/full fate.

    Records resolve relative to the contract directory; absolute records are
    supported by the public file contract. The canonical clock retains the
    producing run's epoch. Zero exits require a null state record, not an empty
    canonical table masquerading as a new simulated cohort.
    """
    path = Path(contract_path).resolve()
    contract = _json(path)
    validate_schema(contract, SCHEMA)
    paths = {}
    for name in ("clock_authority", "source_states", "mother_census", "mother_fates", "producer_manifest"):
        record = contract[name]
        if record is not None:
            verify_record(name, record, base_dir=path.parent)
            paths[name] = record_path(record, base_dir=path.parent)
    clock_path = paths["clock_authority"]
    clock = _json(clock_path)
    validate_clock_authority(clock_path, clock_path.parent.parent)
    epoch_path = clock_path.parent.parent / clock["authority"]["path"]
    epoch = float(_json(epoch_path)[clock["authority"]["field"]])
    if not math.isfinite(epoch) or epoch != 0:
        raise ValueError("IP native schedule requires the inherited instrument epoch zero")
    producer = _json(paths["producer_manifest"])
    require_completed_terminal_publication(paths["producer_manifest"])
    authority_keys = {"preparation_manifest", "preparation_source"}
    if bool(authority_keys & contract.keys()) and not authority_keys <= contract.keys():
        raise ValueError("handoff preparation authority is incomplete")
    authority = None
    if authority_keys <= contract.keys():
        for name in authority_keys:
            verify_record(name, contract[name], base_dir=path.parent)
        authority = {name: record_path(contract[name], base_dir=path.parent) for name in authority_keys}
    else:
        root = path.parent.parent.parent
        candidate = root / "run_manifest.json"
        if candidate.is_file():
            authority = {"preparation_manifest": candidate, "preparation_source": path}
        elif ((root / "run_config.json").is_file()
              and _json(root / "run_config.json").get("mode") == "multipole_ip_preparation"):
            raise ValueError("handoff preparation has not completed terminal publication")
    if authority is not None:
        producer_result = _published_producer_result(authority["preparation_manifest"], authority["preparation_source"],
                                                     paths["producer_manifest"])
        # A frozen consumer copy must still refer to exactly the published package.
        original = _json(authority["preparation_source"])
        if any(contract[key] != original[key] for key in
               ("schema_version", "role", "frame_id", "target_component_id", "producer_case_id")):
            raise ValueError("frozen handoff package differs from published source")
        for name in ("clock_authority", "source_states", "mother_census", "mother_fates", "producer_manifest"):
            if (contract[name] is None) != (original[name] is None):
                raise ValueError("frozen handoff package differs from published source")
            if contract[name] is not None and any(contract[name].get(key) != original[name].get(key) for key in ("bytes", "sha256")):
                raise ValueError("frozen handoff package differs from published source")
    else:
        # Historical packages predate terminal handoff publications.
        from projects.rf_multipole_ion_optics.core.component_port import load_transport_producer_result
        producer_result = load_transport_producer_result(producer, paths["producer_manifest"].parent)
    census = _json(paths["mother_census"])
    if (census.get("schema_version") != 1 or census.get("role") != "multipole_mechanical_exit_census"
            or census.get("status") != "PASS"):
        raise ValueError("injected source requires real mechanical-exit census, not internal handoff")
    mother, exits, losses = (census[key] for key in ("mother_particle_ids", "exit_particle_ids", "non_exit_particle_ids"))
    try:
        partition = partition_cohort(mother, [(pid, "exit") for pid in exits] +
                                     [(pid, "non_exit") for pid in losses],
                                     categories=("exit", "non_exit"), relative_weights=None)
    except ValueError as exc:
        raise ValueError("injected source mother/exit/loss census does not close") from exc
    if (not mother or (census["mother_count"], census["exit_count"], census["non_exit_count"])
            != (partition["mother_count"], partition["counts"]["exit"], partition["counts"]["non_exit"])):
        raise ValueError("injected source mother/exit/loss census does not close")
    with paths["mother_fates"].open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames not in (FATE_COLUMNS, FATE_COLUMNS[:-1]):
            raise ValueError("upstream mother fate columns differ")
        fates = list(reader)
    by_id = {}
    for fate in fates:
        pid, charge = int(fate["particle_id"]), int(fate["charge_state"])
        birth, mass, terminal = (float(fate[key]) for key in
                                ("particle_birth_time_us", "mass_amu", "terminal_instrument_time_us"))
        if (pid in by_id or not all(math.isfinite(v) for v in (birth, mass, terminal))
                or mass <= 0 or charge <= 0 or terminal < birth
                or fate["terminal_reason"] != census["terminal_reasons"].get(str(pid))):
            raise ValueError("invalid upstream mother identity/species/clock/fate")
        by_id[pid] = dict(particle_id=pid, charge_state=charge, mass_amu=mass,
                         particle_birth_time_us=birth, terminal_instrument_time_us=terminal,
                         terminal_reason=fate["terminal_reason"])
        weight = fate.get("particle_weight", "")
        if weight:
            value = float(weight)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("invalid upstream mother weight")
            by_id[pid]["particle_weight"] = value
    if set(by_id) != set(mother):
        raise ValueError("upstream fate table does not preserve every mother ID")
    rows = []
    if exits:
        if "source_states" not in paths:
            raise ValueError("mechanical exits require their canonical states")
        for row in load_component_particle_state_csv(paths["source_states"]).rows:
            pid = row["particle_id"]
            fate = by_id.get(pid)
            if (fate is None or row["state_event"] != "mechanical_exit"
                    or row["frame_id"] != contract["frame_id"]
                    or row["clock_epoch_id"] != clock["clock_epoch_id"]
                    or row["target_component_id"] != contract["target_component_id"]
                    or row["generation"] != 0
                    or ("particle_weight" in fate and row["particle_weight"] != fate["particle_weight"])
                    or any(row[key] != fate[key] for key in ("particle_birth_time_us", "mass_amu", "charge_state"))
                    or row["instrument_time_us"] > fate["terminal_instrument_time_us"]):
                raise ValueError("injected state differs from upstream identity/frame/clock/mechanical exit")
            rows.append(row)
    elif contract["source_states"] is not None:
        raise ValueError("zero mechanical exits require a null state record")
    if {row["particle_id"] for row in rows} != set(exits):
        raise ValueError("injected canonical states differ from the mechanical exit cohort")
    return dict(contract=contract, rows=sorted(rows, key=lambda row: row["particle_id"]),
                clock=clock, epoch_us=epoch, census=census, mother_fates=by_id, producer_result=producer_result,
                records={name: dict(record, path=str(paths[name]))
                         for name, record in contract.items() if name in paths}, authority=authority)


def release_states(admission: dict[str, Any]) -> list[dict[str, Any]]:
    """Project validated states; retain relative weights as non-dynamical metadata."""
    return [dict(particle_id=row["particle_id"], birth_time_s=row["particle_birth_time_us"] / 1e6,
                 arrival_time_us=row["instrument_time_us"], mass_amu=row["mass_amu"],
                 charge_state=row["charge_state"], species_id=row["species_id"], particle_weight=row["particle_weight"],
                 **{f"{axis}_mm": row[f"position_{axis}_mm"] for axis in "xyz"},
                 **{f"v{axis}_m_s": row[f"velocity_{axis}_m_s"] for axis in "xyz"})
            for row in admission["rows"]]


def freeze_injected_source(admission: dict[str, Any], run: Path) -> None:
    """Copy the verified assembly package into IP inputs without a new clock."""
    inputs = run / "inputs"
    contract = dict(admission["contract"])
    if admission.get("authority"):
        contract.update({name: file_record(path) for name, path in admission["authority"].items()})
    for name, record in admission["records"].items():
        target = inputs / ("clock_authority.json" if name == "clock_authority" else
                           "injected_states.csv" if name == "source_states" else
                           "upstream_" + name + Path(record["path"]).suffix)
        shutil.copyfile(record["path"], target)
        contract[name] = dict(record, path=str(target.resolve()))
    source_clock = Path(admission["records"]["clock_authority"]["path"])
    epoch = source_clock.parent.parent / admission["clock"]["authority"]["path"]
    if admission["clock"]["authority"]["path"] != "inputs/instrument_epoch.json":
        raise ValueError("IP frozen clock requires the canonical inputs/instrument_epoch.json authority path")
    shutil.copyfile(epoch, inputs / "instrument_epoch.json")
    (inputs/"injected_source.json").write_text(json.dumps(contract, indent=2)+"\n", encoding="utf-8")


def frozen_release_states(run: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the run's actual injection table, or retain standalone source behavior."""
    if "injected_source" not in config:
        from common.ion_release.release import generate_release_states
        return generate_release_states(config["source"])
    rows = load_component_particle_state_csv(run/"inputs/injected_states.csv").rows if config["source"]["particle_count"] else []
    return sorted(release_states(dict(rows=rows)), key=lambda row: row["particle_id"])
