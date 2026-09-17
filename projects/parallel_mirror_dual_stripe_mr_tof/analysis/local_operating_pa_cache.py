"""Bind MR-TOF local standalone operating PAs to the shared content cache."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from common.simion.operating_pa_cache import (
    CacheDisposition,
    OperatingPACacheError,
    canonical_operating_pa_cache_key,
    canonical_operating_pa_identity,
    content_identity_from_verified_record,
    linear_basis_operating_pa_group_identity,
    materialize_operating_pa_cache,
    probe_operating_pa_cache,
    publish_operating_pa_cache,
    validate_operating_pa_cache_generation,
)
from common.simion.pa_family_cache import canonical_pa_family_cache_key
LOCAL_OUTPUT_NAMES = (
    "local_negative_mirror.pa",
    "local_negative_bridge.pa",
    "local_central.pa",
    "local_positive_bridge.pa",
    "local_positive_mirror.pa",
)
DOWNSTREAM_COORDINATES = (
    "drift_stripe_set_1",
    "drift_stripe_set_2",
    "prism_1",
    "prism_2",
)
MIRROR_COORDINATES = (
    "mirror_B",
    "mirror_C",
    "mirror_D",
    "mirror_E",
)
_GENERATION_SHA256 = re.compile(r"^[A-F0-9]{64}$")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatingPACacheError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise OperatingPACacheError(f"{label} must be a JSON object: {path}")
    return value


def _pinned_generation_probe(
    cache_root: Path, identity: Mapping[str, object], generation_sha256: str,
) -> tuple[str, Path, dict[str, Any]]:
    """Resolve one immutable operating-PA generation without following ``current``.

    Fixed-grid validation must not silently substitute a newer cache generation
    that happens to have the same operating identity.  The returned manifest is
    fully payload-validated by the common cache validator.
    """

    expected = generation_sha256.upper()
    if _GENERATION_SHA256.fullmatch(expected) is None:
        raise OperatingPACacheError("expected operating PA generation SHA-256 is invalid")
    cache_key = canonical_operating_pa_cache_key(identity)
    generation = cache_root.resolve() / cache_key / "generations" / expected
    manifest = validate_operating_pa_cache_generation(
        generation, expected_identity=identity,
    )
    if manifest.get("generation_sha256") != expected:
        raise OperatingPACacheError("pinned operating PA generation identity differs")
    return cache_key, generation, manifest


def _content_record(
    records: object, path: Path, label: str, *, direct_name_inventory: bool = False,
) -> dict[str, object]:
    if not isinstance(records, list):
        raise OperatingPACacheError(f"{label} receipt has no file inventory")
    wanted = path.name if direct_name_inventory else str(path.resolve()).casefold()
    matches = [
        record for record in records if isinstance(record, dict)
        and (str(record.get("name", "")) == wanted if direct_name_inventory
             else str(record.get("path", "")).casefold() == wanted)
    ]
    if len(matches) != 1:
        raise OperatingPACacheError(f"{label} receipt does not identify exactly one file: {path}")
    record = matches[0]
    return content_identity_from_verified_record(
        {"bytes": record.get("bytes"), "sha256": str(record.get("sha256", "")).upper()},
        path=path,
    )


def _family_evidence(
    family_manifest_path: Path, *, family_cache_root: Path | None = None,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    family_run = family_manifest_path.resolve().parent
    run_manifest = _load_object(family_manifest_path, "local-family run manifest")
    if run_manifest.get("status") != "success":
        raise OperatingPACacheError(f"local-family run is not successful: {family_run}")
    contract = _load_object(
        family_run / "results" / "analyzer_local_pa_family_contract.json",
        "local-family contract",
    )
    publication = _load_object(
        family_run / "results" / "pa_family_cache_publication.json",
        "local-family cache publication",
    )
    frozen_identity = _load_object(
        family_run / "results" / "pa_family_cache_identity.json",
        "local-family cache identity",
    )
    cache_key = str(publication.get("cache_key", ""))
    if canonical_pa_family_cache_key(frozen_identity) != cache_key:
        raise OperatingPACacheError("local-family frozen identity and publication key differ")
    # The family-run receipt pins its input generation.  Never replace it with
    # the cache's mutable ``current_generation`` pointer: doing so changes the
    # response basis of a nominally reproducible operating PA.
    generation = Path(str(publication.get("generation_directory", ""))).resolve()
    expected_generation = str(publication.get("generation_sha256", ""))
    if family_cache_root is not None:
        cache_generation_root = (
            family_cache_root.resolve() / cache_key / "generations"
        )
        try:
            generation.relative_to(cache_generation_root)
        except ValueError as exc:
            raise OperatingPACacheError(
                "local-family publication generation is outside the declared cache root"
            ) from exc
    manifest = _load_object(generation / "cache_manifest.json", "local-family cache manifest")
    if cache_key != manifest.get("cache_key"):
        raise OperatingPACacheError("local-family publication and generation cache keys differ")
    if expected_generation != manifest.get("generation_sha256"):
        raise OperatingPACacheError("local-family publication and generation identities differ")
    if manifest.get("identity") != frozen_identity:
        raise OperatingPACacheError("local-family current generation and frozen identities differ")
    return contract, generation, manifest


def build_local_operating_pa_identity(
    local_workbench_run: Path,
    target_voltage_vector_v: Sequence[float],
    *,
    target_mirror_voltage_vector_v: Sequence[float] | None = None,
    implementation_path: Path | None = None,
    pa_format_version: int = 2020,
    family_cache_root: Path | None = None,
) -> dict[str, object]:
    """Compile the five local outputs from frozen run/cache receipts.

    The workbench and local-family run manifests must already have passed their
    owning run verifiers.  This adapter checks their cross-links and current
    file sizes without rehashing the multi-gigabyte source families.
    """

    identity, _ = _build_local_operating_pa_identity_and_lanes(
        local_workbench_run,
        target_voltage_vector_v,
        target_mirror_voltage_vector_v=target_mirror_voltage_vector_v,
        implementation_path=implementation_path,
        pa_format_version=pa_format_version,
        family_cache_root=family_cache_root,
    )
    return identity


def _build_local_operating_pa_identity_and_lanes(
    local_workbench_run: Path,
    target_voltage_vector_v: Sequence[float],
    *,
    target_mirror_voltage_vector_v: Sequence[float] | None = None,
    implementation_path: Path | None = None,
    pa_format_version: int = 2020,
    family_cache_root: Path | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Resolve one canonical identity and its existing-lane synthesis inputs."""

    root = local_workbench_run.resolve()
    config = _load_object(root / "run_config.json", "local-workbench run config")
    manifest = _load_object(root / "run_manifest.json", "local-workbench run manifest")
    if config.get("mode") != "analyzer_local_replacement_workbench" or manifest.get("status") != "success":
        raise OperatingPACacheError("local operating cache requires a successful local replacement workbench")
    inputs = config.get("inputs")
    if not isinstance(inputs, Mapping):
        raise OperatingPACacheError("local-workbench inputs are invalid")
    declared_local_paths = inputs.get("local_operating_pas")
    if not isinstance(declared_local_paths, list) or len(declared_local_paths) != len(LOCAL_OUTPUT_NAMES):
        raise OperatingPACacheError(
            "local-workbench must identify exactly five standalone local operating PAs"
        )
    local_operating_paths: list[Path] = []
    for value in declared_local_paths:
        if not isinstance(value, str) or not value:
            raise OperatingPACacheError("local-workbench local operating PA path is invalid")
        path = Path(value).resolve()
        if path.suffix.lower() != ".pa":
            raise OperatingPACacheError(
                f"local-workbench base is not a true standalone .pa: {path}"
            )
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise OperatingPACacheError(
                f"local-workbench local operating PA escapes the frozen run: {path}"
            ) from exc
        local_operating_paths.append(path)
    family_manifests = inputs.get("local_family_manifests")
    if not isinstance(family_manifests, list) or len(family_manifests) != len(LOCAL_OUTPUT_NAMES):
        raise OperatingPACacheError("local-workbench must identify exactly five local-family manifests")
    base_receipt_path = root / "inputs" / "two_prism_trial_materialization.json"
    base_receipt = _load_object(base_receipt_path, "local-workbench operating-point receipt")
    base = base_receipt.get("stripe_biases_v", []) + base_receipt.get("prism_voltages_v", [])
    if len(base) != len(DOWNSTREAM_COORDINATES) or len(target_voltage_vector_v) != len(DOWNSTREAM_COORDINATES):
        raise OperatingPACacheError("local operating cache requires S1,S2,P1,P2 voltage vectors")
    target = [float(value) for value in target_voltage_vector_v]
    coordinates = list(DOWNSTREAM_COORDINATES)
    base_values = [float(value) for value in base]
    target_values = list(target)
    target_mirror: list[float] | None = None
    if target_mirror_voltage_vector_v is not None:
        mirror_base = base_receipt.get("mirror_voltages_v")
        if not isinstance(mirror_base, list) or len(mirror_base) != 5 or float(mirror_base[0]) != 0.0:
            raise OperatingPACacheError(
                "local operating cache mirror adjustment requires grounded A plus B--E base voltages"
            )
        if len(target_mirror_voltage_vector_v) != len(MIRROR_COORDINATES):
            raise OperatingPACacheError("target mirror voltages must contain B,C,D,E")
        target_mirror = [float(value) for value in target_mirror_voltage_vector_v]
        coordinates = list(MIRROR_COORDINATES) + coordinates
        base_values = [float(value) for value in mirror_base[1:]] + base_values
        target_values = target_mirror + target_values
    deltas = [
        target_value - base_value
        for target_value, base_value in zip(target_values, base_values, strict=True)
    ]
    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping):
        raise OperatingPACacheError("local-workbench parameters are invalid")
    normalization = float(parameters.get("basis_voltage_v"))
    if normalization == 0.0:
        raise OperatingPACacheError("local-workbench basis voltage must be nonzero")

    output_records = manifest.get("outputs")
    members: list[dict[str, object]] = []
    lanes: list[dict[str, object]] = []
    for output_name, base_path, family_manifest in zip(
        LOCAL_OUTPUT_NAMES, local_operating_paths, family_manifests, strict=True,
    ):
        base_content = _content_record(output_records, base_path, "local-workbench run")
        contract, generation, family_cache_manifest = _family_evidence(
            Path(str(family_manifest)), family_cache_root=family_cache_root,
        )
        records = family_cache_manifest.get("files")
        recipes = contract.get("response_recipes")
        if not isinstance(recipes, list):
            raise OperatingPACacheError("local-family contract has no response recipe inventory")
        responses: list[dict[str, object]] = []
        lane_responses: list[dict[str, object]] = []
        for coordinate, delta in zip(coordinates, deltas, strict=True):
            local_id = (
                MIRROR_COORDINATES.index(coordinate) + 1
                if coordinate in MIRROR_COORDINATES
                else DOWNSTREAM_COORDINATES.index(coordinate) + 5
            )
            matches = [
                recipe for recipe in recipes
                if isinstance(recipe, Mapping) and recipe.get("local_id") == local_id
            ]
            if len(matches) != 1:
                raise OperatingPACacheError(
                    f"local-family contract does not identify exactly one response recipe for local ID {local_id}"
                )
            standalone_name = matches[0].get("standalone_response_filename")
            if not isinstance(standalone_name, str) or Path(standalone_name).name != standalone_name:
                raise OperatingPACacheError("local-family standalone response filename is invalid")
            if Path(standalone_name).suffix.lower() != ".pa":
                raise OperatingPACacheError("local-family response recipe is not standalone .pa")
            response_path = generation / standalone_name
            response_content = _content_record(
                records, response_path, "local-family cache", direct_name_inventory=True,
            )
            responses.append({
                "coordinate": coordinate,
                "content": response_content,
                "basis_normalization_v": normalization,
                "applied_voltage_delta_v": delta,
            })
            if delta != 0.0:
                lane_responses.append({
                    "source": str(response_path),
                    "coefficient": delta / normalization,
                    "coordinate": coordinate,
                })
        members.append({
            "output_name": output_name,
            "base_pa": base_content,
            "responses": responses,
            "target_voltage_vector_v": target_values,
        })
        lanes.append({
            "label": output_name.removesuffix(".pa"),
            "output_name": output_name,
            "base_mode": "standalone",
            "base_source": str(base_path),
            "source_family_cache_key": str(family_cache_manifest["cache_key"]),
            "responses": lane_responses,
        })
    if implementation_path is None:
        implementation_path = Path(__file__).resolve().parents[3] / "common" / "simion" / "compose_standalone_pa.lua"
    identity = linear_basis_operating_pa_group_identity(
        members, pa_format_version=pa_format_version, implementation_path=implementation_path,
    )
    return identity, lanes


def build_local_operating_pa_lane_specs(
    local_workbench_run: Path,
    target_voltage_vector_v: Sequence[float],
    *,
    target_mirror_voltage_vector_v: Sequence[float] | None = None,
    implementation_path: Path | None = None,
    pa_format_version: int = 2020,
    family_cache_root: Path | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Return the canonical cache identity and five lane-ready source specs."""

    return _build_local_operating_pa_identity_and_lanes(
        local_workbench_run,
        target_voltage_vector_v,
        target_mirror_voltage_vector_v=target_mirror_voltage_vector_v,
        implementation_path=implementation_path,
        pa_format_version=pa_format_version,
        family_cache_root=family_cache_root,
    )


def _parse_voltages(value: str, label: str) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(item) for item in value.split(","))
    except ValueError as exc:
        raise OperatingPACacheError(f"{label} must be comma-separated numbers") from exc
    if len(values) != 4:
        raise OperatingPACacheError(f"{label} must contain exactly four values")
    return values  # type: ignore[return-value]


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("identity", "plan", "probe", "publish", "materialize"), required=True)
    parser.add_argument("--local-workbench-run", type=Path)
    parser.add_argument("--target-voltages-v")
    parser.add_argument("--target-mirror-voltages-v")
    parser.add_argument("--identity-input", type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--destination-directory", type=Path)
    parser.add_argument("--identity-output", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--expected-generation-sha256")
    parsed = parser.parse_args(arguments)
    if parsed.expected_generation_sha256 is not None and parsed.action not in {"probe", "materialize"}:
        raise OperatingPACacheError("--expected-generation-sha256 is valid only for probe or materialize")
    if parsed.identity_input is not None:
        if parsed.action == "plan":
            raise OperatingPACacheError("plan requires local-workbench identity source arguments")
        if (
            parsed.local_workbench_run is not None
            or parsed.target_voltages_v is not None
            or parsed.target_mirror_voltages_v is not None
        ):
            raise OperatingPACacheError("--identity-input cannot be combined with identity source arguments")
        identity = canonical_operating_pa_identity(
            _load_object(parsed.identity_input, "local operating PA cache identity")
        )
    else:
        if parsed.local_workbench_run is None or parsed.target_voltages_v is None:
            raise OperatingPACacheError(
                "identity compilation requires --local-workbench-run and --target-voltages-v"
            )
        voltages = _parse_voltages(parsed.target_voltages_v, "target S1,S2,P1,P2 voltages")
        mirror_voltages = (
            _parse_voltages(parsed.target_mirror_voltages_v, "target mirror B,C,D,E voltages")
            if parsed.target_mirror_voltages_v is not None else None
        )
        if parsed.action == "plan":
            identity, lanes = build_local_operating_pa_lane_specs(
                parsed.local_workbench_run, voltages,
                target_mirror_voltage_vector_v=mirror_voltages,
                family_cache_root=parsed.cache_root,
            )
        else:
            identity = build_local_operating_pa_identity(
                parsed.local_workbench_run, voltages,
                target_mirror_voltage_vector_v=mirror_voltages,
                family_cache_root=parsed.cache_root,
            )
    if parsed.identity_output is not None:
        parsed.identity_output.write_text(
            json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if parsed.action == "plan":
        if parsed.plan_output is None:
            raise OperatingPACacheError("plan requires --plan-output")
        document = {
            "schema_version": 1,
            "role": "mrtof_local_operating_pa_lane_plan",
            "target_voltage_vector_v": list(voltages),
            "target_mirror_voltage_vector_v": (
                list(mirror_voltages) if mirror_voltages is not None else None
            ),
            "lanes": lanes,
        }
        parsed.plan_output.parent.mkdir(parents=True, exist_ok=True)
        parsed.plan_output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        document = {"identity": identity, "plan": document}
    elif parsed.action == "identity":
        document: dict[str, object] = {"identity": identity}
    else:
        if parsed.cache_root is None:
            raise OperatingPACacheError("cache action requires --cache-root")
        if parsed.action == "probe":
            if parsed.expected_generation_sha256 is not None:
                cache_key, generation, manifest = _pinned_generation_probe(
                    parsed.cache_root, identity, parsed.expected_generation_sha256,
                )
                document = {
                    "disposition": CacheDisposition.HIT.value,
                    "cache_key": cache_key,
                    "generation_sha256": str(manifest["generation_sha256"]),
                    "generation_directory": str(generation),
                    "detail": "pinned_generation_verified",
                }
            else:
                result = probe_operating_pa_cache(parsed.cache_root, identity)
                document = {"disposition": result.disposition.value, "cache_key": result.cache_key,
                            "generation_sha256": (
                                result.generation_directory.name
                                if result.generation_directory is not None else None
                            ),
                            "generation_directory": str(result.generation_directory) if result.generation_directory else None,
                            "detail": result.detail}
        elif parsed.action == "publish":
            if parsed.source_directory is None:
                raise OperatingPACacheError("publish requires --source-directory")
            result = publish_operating_pa_cache(parsed.cache_root, identity, parsed.source_directory)
            document = {"disposition": result.disposition.value, "cache_key": result.cache_key,
                        "generation_sha256": result.generation_sha256,
                        "generation_directory": str(result.generation_directory)}
        else:
            if parsed.destination_directory is None:
                raise OperatingPACacheError("materialize requires --destination-directory")
            if parsed.expected_generation_sha256 is not None:
                cache_key, generation, manifest = _pinned_generation_probe(
                    parsed.cache_root, identity, parsed.expected_generation_sha256,
                )
            else:
                probe = probe_operating_pa_cache(parsed.cache_root, identity)
                if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
                    raise OperatingPACacheError(
                        f"local operating PA cache is not an intact hit: {probe.disposition.value}: {probe.detail}"
                    )
                cache_key, generation = probe.cache_key, probe.generation_directory
                manifest = validate_operating_pa_cache_generation(
                    generation, expected_identity=identity,
                )
            result = materialize_operating_pa_cache(
                generation, parsed.destination_directory, expected_identity=identity,
            )
            document = {"disposition": "materialized", "cache_key": cache_key,
                        "generation_sha256": str(manifest["generation_sha256"]),
                        "generation_directory": str(generation), "files": list(result.files)}
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
