"""One explicit SIMION view action; backend preparation is an explicit callback."""
from __future__ import annotations

from functools import partial
import inspect
from pathlib import Path
from typing import Any, Callable, Mapping

from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.run_session import RunSession
from .simion import open_prepared_model


def execute_simion_open_model(session: RunSession, *, model_reference: Any, prepare_view: Callable,
                              preparer_record: Mapping[str, Any], limits: Mapping[str, Any]) -> dict:
    """Prepare and verify a new owned view, then await the explicit GUI exit.

    The API binds the installed backend callback. Applications never import a
    backend, implement geometry/drive formulas, or create another run owner.
    """
    if session.expected_operation_ids != ('materialize_geometry', 'build_model', 'verify_model', 'view_model'):
        raise ValueError('SIMION viewer requires exactly its original four-operation graph')
    if not callable(prepare_view):
        raise ValueError('SIMION view requires the actual model preparation callback')
    verify_record('SIMION view preparer', dict(preparer_record))
    function = prepare_view.func if isinstance(prepare_view, partial) else prepare_view
    source = inspect.getsourcefile(inspect.unwrap(function))
    if source is None or Path(source).resolve() != Path(preparer_record['path']).resolve():
        raise ValueError('SIMION view preparation callback identity differs')
    session.add_input('simion_view_preparer', dict(preparer_record))
    view = prepare_view(session, model_reference=model_reference)
    if tuple(row['operation_id'] for row in session.operations) != ('materialize_geometry', 'build_model', 'verify_model'):
        raise ValueError('SIMION view preparation differs from the actual three-operation prefix')
    executable = session.context.tools.get('simion')
    if executable is None:
        raise ValueError('SIMION view requires its explicit configured executable')
    viewed = open_prepared_model(session, view=view, executable=executable, limits=limits)
    result = view['action_result']
    result['summary'] = dict(result['summary'], application='simion', gui_calls=1,
        gui_geometry_acceptance='not_inferred_from_process_exit', original_iob_bytes_preserved=False,
        view_container='rebuilt_from_same_raw_geometry_and_drive', lifecycle='application_exit')
    result['output_paths'] = [*result['output_paths'], viewed['receipt_path']]
    result['required_output_paths'] = [*result['required_output_paths'], viewed['receipt_path']]
    # Do not republish a PreparedModel with unchanged old metadata while hiding
    # its new GUI lifecycle. This action publishes viewing evidence only.
    result['manifest_extra_fields'] = {}
    session.add_input('simion_view_action_source', file_record(Path(__file__).resolve(), 'required_evidence'))
    return result
