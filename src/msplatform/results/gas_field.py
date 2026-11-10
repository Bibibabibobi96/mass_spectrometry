"""Read published axisymmetric gas fields independently of native execution."""

from collections.abc import Mapping
from typing import Any
from dataclasses import dataclass
from msplatform.contracts.gas_field import GasFieldData, read_gas_field_data
from .artifacts import ArtifactResolver, OpenedArtifact, open_artifact


@dataclass(frozen=True)
class OpenedGasField:
    """Original product identity together with its actual neutral data scan."""

    artifact: OpenedArtifact
    data: GasFieldData


def read_gas_field(reference: Mapping[str, Any], *, resolver: ArtifactResolver | None = None) -> OpenedGasField:
    """Verify selected gas data, including the explicit historical manifest format."""
    import json
    from pathlib import Path
    from msplatform.io.manifest_records import validate_file_record, require_completed_terminal_publication
    from .artifacts import _verified_path

    if not isinstance(reference, Mapping) or set(reference) != {"manifest", "product_id"}:
        raise ValueError("Gas field requires explicit manifest and product identity")
    manifest_record = validate_file_record(reference["manifest"], "manifest")
    location = _verified_path(manifest_record, label="manifest", base=None, resolver=resolver)
    require_completed_terminal_publication(location)
    manifest = json.loads(location.read_text(encoding="utf-8-sig"))
    if "products" in manifest:
        artifact = open_artifact(reference, expected_kind="gas_field", resolver=resolver)
    else:
        if (
            type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] not in (1, 2)
            or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("status") != "success"
            or manifest.get("project") != "dual_cone_tandem_quadrupole_ion_interface"
            or manifest.get("mode") != "axisymmetric_gas_flow_screening"
            or manifest.get("lifecycle_state") == "provisional"
            or reference["product_id"] != "gas_field"
        ):
            raise ValueError("Unsupported historical gas-field producer")
        inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
        if not isinstance(inputs, dict) or not isinstance(outputs, list):
            raise ValueError("Historical gas-field records are missing")
        records, paths = {}, {}
        for name, old_name in (
            ("science", "gas_flow_science"),
            ("numerics", "comsol_solver_numerics"),
            ("geometry", "resolved_geometry"),
        ):
            records[name] = validate_file_record(inputs.get(old_name), name)
            paths[name] = _verified_path(records[name], label=name, base=location.parent, resolver=resolver)
        numerical = json.loads(paths["numerics"].read_text(encoding="utf-8-sig"))
        for name, output_name in (
            ("field_csv", numerical["artifact_names"]["field_csv"]),
            ("field_metadata", numerical["artifact_names"]["field_metadata"]),
        ):
            matches = [
                record
                for record in outputs
                if isinstance(record, dict) and Path(str(record.get("path", ""))).name == output_name
            ]
            if len(matches) != 1:
                raise ValueError("Historical gas-field output is missing or ambiguous: " + name)
            records[name] = validate_file_record(matches[0], name)
            paths[name] = _verified_path(records[name], label=name, base=location.parent, resolver=resolver)
        metadata = json.loads(paths["field_metadata"].read_text(encoding="utf-8-sig"))
        artifact = OpenedArtifact(
            kind="gas_field",
            product_id="gas_field",
            reference=dict(reference),
            metadata=dict(field_type="axisymmetric_gas", claim_scope=metadata["claim_scope"], legacy_manifest=True),
            records=records,
            paths=paths,
            producer={name: manifest.get(name) for name in ("run_id", "project", "mode", "status")},
            manifest_location=location,
        )
    paths = artifact.data_locations
    data = read_gas_field_data(
        paths["field_csv"], paths["field_metadata"], paths["science"], paths["numerics"], paths["geometry"]
    )
    return OpenedGasField(artifact=artifact, data=data)


def read_gas_model(reference: Mapping[str, Any], expected_contracts: Mapping[str, Mapping[str, Any]]) -> dict:
    """Read an explicitly published model, including a terminal failed-export producer.

    A model record must be an actual producer output; the three current physical
    contracts must match its published inputs. Native reopening still verifies
    the stored terminal pressure/stabilization tuple before any field export.
    """
    import json
    from pathlib import Path
    from msplatform.io.manifest_records import verify_record, require_completed_terminal_publication

    if set(reference) != {"manifest", "model", "completion"}:
        raise ValueError("Gas model resume requires explicit manifest, model and writer-completion records")
    if any(not Path(record["path"]).is_absolute() for record in reference.values()):
        raise ValueError("Gas model resume records require explicit absolute paths")
    manifest_record, model = dict(reference["manifest"]), dict(reference["model"])
    verify_record("gas model producer", manifest_record)
    location = Path(manifest_record["path"])
    require_completed_terminal_publication(location)
    manifest = json.loads(location.read_text(encoding="utf-8-sig"))
    if (
        type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") not in (1, 2)
        or manifest.get("role") != "simulation_run_manifest"
        or manifest.get("project") != "dual_cone_tandem_quadrupole_ion_interface"
        or manifest.get("mode") != "axisymmetric_gas_flow_screening"
        or manifest.get("status") not in {"success", "failed", "interrupted", "superseded"}
        or manifest.get("lifecycle_state") == "provisional"
    ):
        raise ValueError("Gas model resume requires a published terminal producer")
    if model not in manifest.get("outputs", []):
        raise ValueError("Gas model is not an exact published producer output")
    completion_record = dict(reference["completion"])
    if completion_record not in manifest.get("outputs", []):
        raise ValueError("Gas model writer completion is not a published producer output")
    verify_record("gas model writer completion", completion_record)
    completion = json.loads(Path(completion_record["path"]).read_text(encoding="utf-8-sig"))
    if (
        completion.get("role") != "run_artifact_workflow_completion"
        or completion.get("schema_version") != 1
        or any(completion.get(name) != manifest.get(name) for name in ("project", "run_id", "status"))
    ):
        raise ValueError("Gas model writer completion differs from its producer")
    writer = completion.get("writer_completion", {})
    operations, releases = writer.get("operations"), writer.get("resource_releases")
    if not isinstance(operations, list) or not operations or not isinstance(releases, list):
        raise ValueError("Gas model lacks actual native writer closure")
    released = set()
    for row in releases:
        release = row.get("completion_receipt", {}).get("host_release", {})
        if (
            isinstance(release.get("token"), str)
            and release["token"]
            and release.get("error") is None
            and release.get("inherited") is False
            and release.get("result") == {"status": "released", "token": release["token"]}
        ):
            released.add(row["release_id"])
    for operation in operations:
        observation = operation.get("observation", {})
        if (
            observation.get("exit_confirmed") is not True
            or any(
                type(observation.get(name)) is not int
                for name in ("returncode", "process_id", "process_started_at_utc_ticks")
            )
            or observation["process_id"] <= 0
            or observation["process_started_at_utc_ticks"] <= 0
            or operation.get("resource_release_id") not in released
        ):
            raise ValueError("Gas model has an unknown native writer or unconfirmed release")
    for name in ("science", "numerics", "geometry"):
        expected = expected_contracts[name]
        if not any(
            isinstance(record, dict)
            and record.get("exists") is True
            and all(record.get(key) == expected[key] for key in ("bytes", "sha256"))
            for record in manifest.get("inputs", {}).values()
        ):
            raise ValueError("Resume gas model lacks the current source contract: " + name)
    verify_record("gas resume model", model)
    return dict(model=model, manifest=manifest_record, completion=completion_record)
