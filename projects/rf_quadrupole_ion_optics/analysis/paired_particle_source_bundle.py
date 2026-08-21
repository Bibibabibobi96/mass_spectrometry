"""Generate deterministic paired ION/canonical multipole particle sources."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts import particle_physics
from common.contracts.file_identity import file_sha256 as sha256
from common.contracts.particle_count_policy import (
    POLICY_PATH,
    load_particle_count_policy,
    validate_prefix_particle_sources,
    validate_standard_particle_count,
)
from common.multipole.particle_source_preflight import COLUMNS, validate_source


BUNDLE_SCHEMA_VERSION = 1
SINGLE_TABLE_ROLE = "paired_particle_single_table"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def _canonical_json_sha256(document: dict[str, Any]) -> str:
    content = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return _sha256_bytes(content)


def _load_inputs(
    source_family: Path, distribution_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    family = json.loads(source_family.read_text(encoding="utf-8-sig"))
    distribution = json.loads(distribution_path.read_text(encoding="utf-8-sig"))
    if not isinstance(family.get("operating_points"), dict):
        raise ValueError("source family does not declare operating points")
    return family, distribution


def _policy_counts() -> tuple[dict[str, Any], int, int]:
    policy = load_particle_count_policy()
    functional = int(policy["functional_check_count"])
    statistical = int(policy["statistical_count"])
    return policy, functional, statistical


def _sample_latent(
    distribution: dict[str, Any], seed: int, count: int
) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    birth_contract = distribution["time_of_birth_us"]
    position = distribution["position_mm"]
    direction = distribution["direction"]
    birth = rng.uniform(birth_contract["min"], birth_contract["max"], count)
    transverse_1 = rng.uniform(
        position["transverse_1"]["min"],
        position["transverse_1"]["max"],
        count,
    )
    transverse_2 = rng.uniform(
        position["transverse_2"]["min"],
        position["transverse_2"]["max"],
        count,
    )
    energy_quantile = rng.random(count)
    phi = rng.uniform(0.0, 2.0 * np.pi, count)
    half_angle = np.deg2rad(direction["half_angle_deg"])
    cos_theta = rng.uniform(np.cos(half_angle), 1.0, count)
    return {
        "birth_time_us": birth,
        "transverse_1_mm": transverse_1,
        "transverse_2_mm": transverse_2,
        "energy_quantile": energy_quantile,
        "phi_rad": phi,
        "cos_theta": cos_theta,
    }


def _latent_sha256(latent: dict[str, np.ndarray]) -> str:
    matrix = np.column_stack([latent[name] for name in latent])
    stream = io.StringIO(newline="")
    np.savetxt(stream, matrix, delimiter=",", fmt="%.17g")
    return _sha256_bytes(stream.getvalue().encode("ascii"))


def _point_energy(point: dict[str, Any], quantile: np.ndarray) -> np.ndarray:
    contract = point["kinetic_energy_eV"]
    distribution = contract.get("distribution")
    if distribution == "uniform":
        minimum = float(contract["min"])
        maximum = float(contract["max"])
        if not math.isfinite(minimum) or not math.isfinite(maximum) or maximum < minimum:
            raise ValueError("uniform energy operating point is invalid")
        return minimum + (maximum - minimum) * quantile
    if distribution == "fixed":
        value = float(contract["value"])
        if not math.isfinite(value) or value < 0:
            raise ValueError("fixed energy operating point is invalid")
        return np.full(len(quantile), value)
    raise ValueError(f"unsupported energy distribution: {distribution}")


def _normalize_bundle_specification(
    family: dict[str, Any],
    point_ids: Sequence[str],
    point_specs: Mapping[str, Mapping[str, Any]],
    bundle_role: str,
    bundle_version: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    if isinstance(point_ids, (str, bytes)):
        raise ValueError("paired bundle point IDs must be a sequence")
    normalized_ids = list(point_ids)
    if (
        not normalized_ids
        or len(normalized_ids) != len(set(normalized_ids))
        or any(not re.fullmatch(r"[A-Za-z0-9_]+", item) for item in normalized_ids)
    ):
        raise ValueError("paired bundle point IDs are empty, duplicated, or invalid")
    if not isinstance(point_specs, Mapping) or set(point_specs) != set(normalized_ids):
        raise ValueError("paired bundle point specifications do not match point IDs")
    if not isinstance(bundle_role, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", bundle_role
    ):
        raise ValueError("paired bundle role is invalid")
    if not isinstance(bundle_version, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", bundle_version
    ):
        raise ValueError("paired bundle version is invalid")
    family_points = family.get("operating_points")
    if not isinstance(family_points, dict):
        raise ValueError("source family does not declare operating points")
    normalized_specs: dict[str, dict[str, Any]] = {}
    for point_id in normalized_ids:
        point = point_specs[point_id]
        if not isinstance(point, Mapping):
            raise ValueError(f"paired bundle point specification is invalid: {point_id}")
        normalized = dict(point)
        for field in ("mass_amu", "charge_state", "kinetic_energy_eV"):
            if field not in normalized:
                raise ValueError(
                    f"paired bundle point specification lacks {field}: {point_id}"
                )
        if family_points.get(point_id) != normalized:
            raise ValueError(
                f"paired bundle point specification differs from source family: {point_id}"
            )
        normalized_specs[point_id] = normalized
    return normalized_ids, normalized_specs


def load_declared_bundle_specification(
    metadata_path: Path,
    source_family_path: Path,
) -> dict[str, Any]:
    """Read a bundle's explicit generic specification without adding policy."""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    family = json.loads(source_family_path.read_text(encoding="utf-8-sig"))
    point_ids = metadata.get("operating_point_ids")
    family_points = family.get("operating_points")
    if not isinstance(point_ids, list) or not isinstance(family_points, dict):
        raise ValueError("paired bundle does not declare a usable point specification")
    point_specs = {
        point_id: family_points[point_id]
        for point_id in dict.fromkeys(point_ids)
        if isinstance(point_id, str) and point_id in family_points
    }
    return {
        "point_ids": point_ids,
        "point_specs": point_specs,
        "bundle_role": metadata.get("role"),
        "bundle_version": metadata.get("algorithm_version"),
    }


def _build_ion_table(
    point: dict[str, Any],
    distribution: dict[str, Any],
    latent: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    energy = _point_energy(point, latent["energy_quantile"])
    theta = np.arccos(latent["cos_theta"])
    v_axial = np.cos(theta)
    v_transverse_1 = np.sin(theta) * np.cos(latent["phi_rad"])
    v_transverse_2 = np.sin(theta) * np.sin(latent["phi_rad"])
    azimuth = np.rad2deg(np.arctan2(v_transverse_1, v_axial))
    elevation = np.rad2deg(np.arcsin(v_transverse_2))
    count = len(energy)
    table = np.column_stack(
        [
            latent["birth_time_us"],
            np.full(count, point["mass_amu"]),
            np.full(count, point["charge_state"]),
            np.full(count, distribution["position_mm"]["axial"]),
            latent["transverse_1_mm"],
            latent["transverse_2_mm"],
            azimuth,
            elevation,
            energy,
            np.full(count, distribution["cwf"]),
            np.full(count, distribution["color"]),
        ]
    )
    vectors = {
        "v_axial": v_axial,
        "v_transverse_1": v_transverse_1,
        "v_transverse_2": v_transverse_2,
        "energy_eV": energy,
    }
    return table, vectors


def _render_ion(table: np.ndarray) -> bytes:
    stream = io.StringIO(newline="")
    np.savetxt(stream, table, delimiter=",", fmt="%.12g")
    return stream.getvalue().encode("ascii")


def _render_canonical(
    point: dict[str, Any],
    distribution: dict[str, Any],
    latent: dict[str, np.ndarray],
    vectors: dict[str, np.ndarray],
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    mass_amu = float(point["mass_amu"])
    speed = np.sqrt(
        2.0
        * vectors["energy_eV"]
        * particle_physics.ELEMENTARY_CHARGE_C
        / (mass_amu * particle_physics.AMU_KG)
    )
    for index in range(len(speed)):
        writer.writerow(
            {
                "particle_id": str(index + 1),
                "birth_time_s": format(latent["birth_time_us"][index] * 1e-6, ".17g"),
                "x_mm": format(latent["transverse_2_mm"][index], ".17g"),
                "y_mm": format(-latent["transverse_1_mm"][index], ".17g"),
                "z_mm": format(float(distribution["position_mm"]["axial"]), ".17g"),
                "vx_m_s": format(-speed[index] * vectors["v_transverse_1"][index], ".17g"),
                "vy_m_s": format(-speed[index] * vectors["v_transverse_2"][index], ".17g"),
                "vz_m_s": format(speed[index] * vectors["v_axial"][index], ".17g"),
                "mass_amu": format(mass_amu, ".17g"),
                "charge_state": str(int(point["charge_state"])),
            }
        )
    return stream.getvalue().encode("ascii")


def _generate_table_prefix(
    family: dict[str, Any],
    distribution: dict[str, Any],
    point_id: str,
    count: int,
    seed: int,
) -> np.ndarray:
    _, _, statistical_count = _policy_counts()
    latent = _sample_latent(distribution, seed, statistical_count)
    table, _ = _build_ion_table(family["operating_points"][point_id], distribution, latent)
    return table[:count]


def _artifact_entry(
    path: Path,
    root: Path,
    point_id: str,
    count: int,
    representation: str,
    parent: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "operating_point_id": point_id,
        "particle_count": count,
        "representation": representation,
        "sha256": sha256(path),
        "n1000_parent": parent,
    }


def generate_bundle(
    source_family_path: Path,
    distribution_path: Path,
    resolved_path: Path,
    output_dir: Path,
    *,
    point_ids: Sequence[str],
    point_specs: Mapping[str, Mapping[str, Any]],
    bundle_role: str,
    bundle_version: str,
    seed: int | None = None,
) -> dict[str, Any]:
    family, distribution = _load_inputs(source_family_path, distribution_path)
    normalized_ids, normalized_specs = _normalize_bundle_specification(
        family,
        point_ids,
        point_specs,
        bundle_role,
        bundle_version,
    )
    policy, functional_count, statistical_count = _policy_counts()
    selected_seed = (
        int(seed)
        if seed is not None
        else int(family["paired_sampling"]["base_seed"])
    )
    latent = _sample_latent(distribution, selected_seed, statistical_count)
    resolved = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for point_id in normalized_ids:
        point = normalized_specs[point_id]
        ion_master, vectors = _build_ion_table(point, distribution, latent)
        canonical_master = _render_canonical(point, distribution, latent, vectors)
        canonical_lines = canonical_master.decode("ascii").splitlines()
        point_artifacts: dict[tuple[int, str], dict[str, Any]] = {}
        for count in (statistical_count, functional_count):
            ion_path = output_dir / f"{point_id}_n{count}.ion"
            canonical_path = output_dir / f"{point_id}_n{count}_canonical.csv"
            ion_path.write_bytes(_render_ion(ion_master[:count]))
            canonical_path.write_bytes(
                ("\n".join(canonical_lines[: count + 1]) + "\n").encode("ascii")
            )
            validate_source(
                canonical_path,
                resolved,
                source_family_path=source_family_path,
                operating_point_id=point_id,
            )
            for representation, path in (
                ("ion11", ion_path),
                ("canonical10", canonical_path),
            ):
                parent = None
                if count == functional_count:
                    master = point_artifacts[(statistical_count, representation)]
                    parent = {
                        "relative_path": master["relative_path"],
                        "sha256": master["sha256"],
                    }
                entry = _artifact_entry(
                    path, output_dir, point_id, count, representation, parent
                )
                artifacts.append(entry)
                point_artifacts[(count, representation)] = entry
        validate_prefix_particle_sources(
            output_dir / f"{point_id}_n{functional_count}.ion",
            output_dir / f"{point_id}_n{statistical_count}.ion",
        )
        validate_prefix_particle_sources(
            output_dir / f"{point_id}_n{functional_count}_canonical.csv",
            output_dir / f"{point_id}_n{statistical_count}_canonical.csv",
        )
    latent_sha = _latent_sha256(latent)
    family_identity = {
        "algorithm_version": bundle_version,
        "seed": selected_seed,
        "policy_sha256": sha256(POLICY_PATH),
        "source_family_sha256": sha256(source_family_path),
        "distribution_sha256": sha256(distribution_path),
        "latent_sha256": latent_sha,
        "operating_point_ids": normalized_ids,
    }
    metadata = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "role": bundle_role,
        "algorithm_version": bundle_version,
        "seed": selected_seed,
        "policy": {
            "source": "common/contracts/particle_count_policy.json",
            "sha256": sha256(POLICY_PATH),
            "functional_count": functional_count,
            "statistical_count": statistical_count,
            "standard_particle_counts": policy["standard_particle_counts"],
        },
        "inputs": {
            "source_family_sha256": sha256(source_family_path),
            "distribution_sha256": sha256(distribution_path),
            "resolved_design_file_sha256": sha256(resolved_path),
            "resolved_design_sha256": resolved["resolved_sha256"],
        },
        "operating_point_ids": normalized_ids,
        "latent_sha256": latent_sha,
        "sample_family_sha256": _canonical_json_sha256(family_identity),
        "coordinate_mapping_version": "simion_ion11_to_multipole_canonical.v1",
        "coordinate_mapping": {
            "position": "x=transverse_2,y=-transverse_1,z=axial",
            "velocity": "vx=-v_transverse_1,vy=-v_transverse_2,vz=v_axial",
        },
        "artifacts": artifacts,
    }
    metadata_path = output_dir / "paired_particle_bundle.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    validate_bundle(
        metadata_path,
        source_family_path,
        distribution_path,
        resolved_path,
        point_ids=normalized_ids,
        point_specs=normalized_specs,
        bundle_role=bundle_role,
        bundle_version=bundle_version,
    )
    return metadata


def validate_bundle(
    metadata_path: Path,
    source_family_path: Path,
    distribution_path: Path,
    resolved_path: Path,
    *,
    point_ids: Sequence[str],
    point_specs: Mapping[str, Mapping[str, Any]],
    bundle_role: str,
    bundle_version: str,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    if (
        metadata.get("role") != bundle_role
        or metadata.get("schema_version") != BUNDLE_SCHEMA_VERSION
    ):
        raise ValueError("paired particle bundle metadata identity is invalid")
    family, distribution = _load_inputs(source_family_path, distribution_path)
    normalized_ids, normalized_specs = _normalize_bundle_specification(
        family,
        point_ids,
        point_specs,
        bundle_role,
        bundle_version,
    )
    policy, functional_count, statistical_count = _policy_counts()
    if metadata.get("algorithm_version") != bundle_version:
        raise ValueError("paired particle bundle algorithm version differs")
    expected_policy = {
        "source": "common/contracts/particle_count_policy.json",
        "sha256": sha256(POLICY_PATH),
        "functional_count": functional_count,
        "statistical_count": statistical_count,
        "standard_particle_counts": policy["standard_particle_counts"],
    }
    if metadata.get("policy") != expected_policy:
        raise ValueError("paired particle bundle policy identity differs")
    resolved = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    expected_inputs = {
        "source_family_sha256": sha256(source_family_path),
        "distribution_sha256": sha256(distribution_path),
        "resolved_design_file_sha256": sha256(resolved_path),
        "resolved_design_sha256": resolved["resolved_sha256"],
    }
    if metadata.get("inputs") != expected_inputs:
        raise ValueError("paired particle bundle input identity differs")
    if metadata.get("operating_point_ids") != normalized_ids:
        raise ValueError("paired particle bundle operating points differ")
    latent = _sample_latent(distribution, int(metadata["seed"]), statistical_count)
    latent_sha = _latent_sha256(latent)
    family_identity = {
        "algorithm_version": bundle_version,
        "seed": int(metadata["seed"]),
        "policy_sha256": sha256(POLICY_PATH),
        "source_family_sha256": sha256(source_family_path),
        "distribution_sha256": sha256(distribution_path),
        "latent_sha256": latent_sha,
        "operating_point_ids": normalized_ids,
    }
    if metadata.get("latent_sha256") != latent_sha:
        raise ValueError("paired particle bundle latent identity differs")
    if metadata.get("sample_family_sha256") != _canonical_json_sha256(family_identity):
        raise ValueError("paired particle bundle sample-family identity differs")
    root = metadata_path.parent
    entries = metadata.get("artifacts")
    if (
        not isinstance(entries, list)
        or len(entries) != len(normalized_ids) * 4
    ):
        raise ValueError("paired particle bundle artifact inventory is incomplete")
    inventory: dict[tuple[str, int, str], dict[str, Any]] = {}
    for entry in entries:
        relative = Path(entry["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("paired particle bundle artifact path escapes its root")
        path = root / relative
        key = (
            entry["operating_point_id"],
            int(entry["particle_count"]),
            entry["representation"],
        )
        if key in inventory or not path.is_file() or sha256(path) != entry["sha256"]:
            raise ValueError("paired particle bundle artifact identity differs")
        inventory[key] = entry
    for point_id in normalized_ids:
        point = normalized_specs[point_id]
        expected_ion, expected_vectors = _build_ion_table(
            point, distribution, latent
        )
        expected_canonical_lines = _render_canonical(
            point, distribution, latent, expected_vectors
        ).decode("ascii").splitlines()
        for representation, suffix in (
            ("ion11", ".ion"),
            ("canonical10", "_canonical.csv"),
        ):
            small = inventory[(point_id, functional_count, representation)]
            large = inventory[(point_id, statistical_count, representation)]
            if small["n1000_parent"] != {
                "relative_path": large["relative_path"],
                "sha256": large["sha256"],
            } or large["n1000_parent"] is not None:
                raise ValueError("paired particle bundle parent identity differs")
            validate_prefix_particle_sources(
                root / f"{point_id}_n{functional_count}{suffix}",
                root / f"{point_id}_n{statistical_count}{suffix}",
                expected_n100_sha256=small["sha256"],
                expected_n1000_sha256=large["sha256"],
            )
            for count, entry in (
                (functional_count, small),
                (statistical_count, large),
            ):
                expected_bytes = (
                    _render_ion(expected_ion[:count])
                    if representation == "ion11"
                    else (
                        "\n".join(expected_canonical_lines[: count + 1]) + "\n"
                    ).encode("ascii")
                )
                if (root / entry["relative_path"]).read_bytes() != expected_bytes:
                    raise ValueError(
                        "paired particle bundle artifact differs from frozen latent family"
                    )
        validate_source(
            root / inventory[(point_id, functional_count, "canonical10")]["relative_path"],
            resolved,
            source_family_path=source_family_path,
            operating_point_id=point_id,
        )
        validate_source(
            root / inventory[(point_id, statistical_count, "canonical10")]["relative_path"],
            resolved,
            source_family_path=source_family_path,
            operating_point_id=point_id,
        )
    return metadata


def generate_single_table(
    source_family_path: Path,
    distribution_path: Path,
    operating_point_id: str,
    particle_count: int,
    output_path: Path,
    metadata_path: Path,
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one ION table from a caller-selected latent-family point."""
    validate_standard_particle_count(particle_count)
    family, distribution = _load_inputs(source_family_path, distribution_path)
    if operating_point_id not in family["operating_points"]:
        raise ValueError(f"unknown operating point: {operating_point_id}")
    selected_seed = (
        seed
        if seed is not None
        else int(family["paired_sampling"]["base_seed"])
    )
    generated = _generate_table_prefix(
        family,
        distribution,
        operating_point_id,
        particle_count,
        selected_seed,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(output_path, generated, delimiter=",", fmt="%.12g")
    metadata = {
        "schema_version": 1,
        "role": SINGLE_TABLE_ROLE,
        "operating_point": operating_point_id,
        "particles": particle_count,
        "master_particles": _policy_counts()[2],
        "prefix_sampling": True,
        "seed": selected_seed,
        "mass_amu": family["operating_points"][operating_point_id]["mass_amu"],
        "charge_state": family["operating_points"][operating_point_id]["charge_state"],
        "source_family_sha256": sha256(source_family_path),
        "distribution_sha256": sha256(distribution_path),
        "particle_table": str(output_path.resolve()),
        "particle_table_sha256": sha256(output_path),
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata
