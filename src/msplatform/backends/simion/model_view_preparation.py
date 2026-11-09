"""Prepare an owned unsolved GUI model with the unique existing model writer."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from msplatform.results.artifacts import OpenedArtifact
from msplatform.execution.run_session import RunSession
from .field_closure import load_field_model
from .model_execution import _execute_model_preparation, _protected_source, _require_materializer


def prepare_view(session: RunSession, *, model_reference: Mapping | OpenedArtifact,
                 seed_record: Mapping[str, Any], limits: Mapping[str, Any],
                 materialize_geometry: Callable, materializer_record: Mapping[str, Any],
                 allow_asynchronous_io: bool | None = None) -> dict:
    """Rebuild and cold-verify a viewing IOB, not its PA geometry or fields.

    The model's actual clock/drive and raw/surface closure remain unchanged.
    Only the container refers to this new owned run. The two real native
    operations are declared; no byte-identical original IOB claim is made.
    """
    if session.expected_operation_ids != ('materialize_geometry', 'build_model', 'verify_model', 'view_model'):
        raise ValueError('SIMION model view requires exactly materialize/build/verify/view operations')
    _require_materializer(materialize_geometry, materializer_record)
    selected = load_field_model(model_reference)
    source = selected.artifact
    source_manifest = dict(source.reference['manifest'], path=str(source.manifest_location))
    paths = [source.data_locations['compiled_model'],
        *(record['path'] for records in selected.native_assets.values()
          for record in (records['raw_record'], *records['surface_records']))]
    _protected_source(session, source_manifest, required_paths=paths)
    result = _execute_model_preparation(session, model=selected.model, assets=selected.native_assets,
        source_manifest_record=source_manifest, clock_authority_reference=selected.clock_authority_reference,
        seed_record=seed_record, limits=limits, materialize_geometry=materialize_geometry,
        materializer_record=materializer_record, allow_asynchronous_io=allow_asynchronous_io)
    product = result['manifest_extra_fields']['products']['model']
    records = product['data']
    # This is still the action's unpublished preparation result, not a second
    # artifact registry or permission to bypass the eventual owner publication.
    expected = ('materialize_geometry', 'build_model', 'verify_model')
    actual = [row for row in session.operations if row['operation_id'] in expected]
    if (tuple(row['operation_id'] for row in actual) != expected
            or any(row['observation'].get('exit_confirmed') is not True
                   or row['observation'].get('returncode') != 0 for row in actual)):
        raise ValueError('view preparation lacks its three actual successful operation receipts')
    copied = [records[key] for names in product['metadata']['native_assets'].values() for key in names.values()]
    return dict(action_result=result, source_reference=source.reference,
        model_identity_sha256=selected.model.document['model_identity_sha256'],
        workbench_record=records['workbench'], zero_control_record=records['zero_particle_format_control'],
        native_asset_records=copied, data_records=records, preparation_operations=actual,
        view_profile='raw_geometry_no_program_hook', original_iob_bytes_preserved=False,
        path_policy='new_owned_container_same_raw_geometry_and_drive',
        working_directory=str(Path(records['workbench']['path']).parent))
