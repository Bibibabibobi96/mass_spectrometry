"""Explicit JSON transport to the existing PowerShell process/lease owner."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from msplatform.execution.context import ExecutionContext
from msplatform.execution.process_transport import _finish_bridge_after_failure, _host_release
from msplatform.execution.resources import resource_path


class ProcessExecutionError(RuntimeError):
    """A process/owner failure retaining its observation and release facts."""

    def __init__(self, message: str, receipt: dict[str, Any]) -> None:
        super().__init__(message)
        self.receipt = receipt
        observation = receipt.get("observation")
        observation = observation if isinstance(observation, dict) else {}
        error = receipt.get("error")
        data = error.get("data") if isinstance(error, dict) else {}
        data = data if isinstance(data, dict) else {}
        confirmed = bool(observation) and all(type(observation.get(field)) is int for field in
            ("exit_code", "root_process_id", "root_process_started_at_utc_ticks")) and (
                observation["root_process_id"] > 0 and observation["root_process_started_at_utc_ticks"] > 0)
        self.observed_process_exit_confirmed = confirmed or data.get("observed_process_exit_confirmed") is True
        self.observed_process_returncode = observation.get("exit_code", data.get("observed_process_returncode"))
        self.host_release = receipt.get("host_release")


def _interpret_process_result(output: bytes, errors: bytes, returncode: int) -> dict[str, Any]:
    """Keep the original operation failure ahead of release/transport faults."""
    prefix = "EXECUTION_PROCESS_RESULT="
    try:
        lines = [line[len(prefix):] for line in output.decode("utf-8").splitlines() if line.startswith(prefix)]
        if len(lines) != 1:
            raise ValueError("no unique receipt")
        receipt = json.loads(lines[0])
        if not isinstance(receipt, dict) or set(receipt) != {"observation", "error", "host_release"}:
            raise ValueError("receipt fields differ")
    except (UnicodeError, ValueError) as error:
        raise ProcessExecutionError(f"Execution owner result is invalid: {error}; stderr={errors!r}", {}) from error
    failure = None
    error = receipt["error"]
    observation = receipt["observation"]
    if error is not None:
        if not isinstance(error, dict) or not isinstance(error.get("message"), str):
            failure = ProcessExecutionError("Execution owner error record is invalid", receipt)
        else:
            failure = ProcessExecutionError(error["message"], receipt)
    elif (not isinstance(observation, dict) or
          any(type(observation.get(field)) is not int for field in
              ("exit_code", "root_process_id", "root_process_started_at_utc_ticks")) or
          observation["root_process_id"] <= 0 or observation["root_process_started_at_utc_ticks"] <= 0):
        failure = ProcessExecutionError("Execution process exit identity is unconfirmed", receipt)
    elif observation["exit_code"] != 0:
        failure = ProcessExecutionError(f"Observed process failed with exit {observation['exit_code']}", receipt)
    try:
        release = _host_release(receipt)
        if not release["inherited"] and (release["error"] is not None or
                (release["result"] or {}).get("status") != "released"):
            raise ValueError(f"owner release was not confirmed: {release}")
    except ValueError as error:
        if failure is not None:
            failure.add_note(f"Execution host release secondary: {error}")
        else:
            failure = ProcessExecutionError(f"Execution host release is unconfirmed: {error}", receipt)
    if returncode:
        if failure is None:
            failure = ProcessExecutionError(f"Execution owner failed with exit {returncode}", receipt)
        else:
            failure.add_note(f"Execution owner exited with code {returncode}")
    if failure is not None:
        raise failure
    return receipt


def inherited_host_token(context: ExecutionContext, required: bool = False) -> str | None:
    """Return the inherited token only for its original explicit state owner."""
    token = os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN")
    state = os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH")
    if token and (not state or Path(state).resolve() != context.host_state_path.resolve()):
        raise ValueError("execution context host state differs from the inherited lease owner")
    if required and not token:
        raise ValueError("worker requires its actual inherited host lease")
    return token


def run_observed_process(
    context: ExecutionContext, *, executable: Path, arguments: Sequence[str],
    working_directory: Path, run_directory: Path, stdout_path: Path, stderr_path: Path,
    usage_path: Path, role: str, stage: str, run_id: str,
    limits: Mapping[str, Any] | None, environment: Mapping[str, str] | None = None,
    immutable_input_records: Sequence[Mapping[str, Any]] = (),
    window_style: str = "Hidden",
) -> dict[str, Any]:
    """Execute one explicit process under the unchanged owner, without a timeout.

    The caller supplies authorization/stage, frozen engineering limits and native
    arguments. Scientific/native completion remains the backend's responsibility.
    A communication error drains and waits the same healthy owner handle.
    """
    if not isinstance(window_style, str) or window_style not in {"Hidden", "Normal"}:
        raise ValueError("window_style requires exactly Hidden or Normal")
    inherited_host_token(context)
    paths = dict(executable=executable, working_directory=working_directory,
                 run_directory=run_directory, stdout_path=stdout_path,
                 stderr_path=stderr_path, usage_path=usage_path)
    if any(not Path(path).is_absolute() for path in paths.values()):
        raise ValueError("process execution paths must be absolute")
    if isinstance(arguments, str) or any(not isinstance(arg, str) or "\0" in arg for arg in arguments):
        raise ValueError("process arguments must be a string sequence without NUL")
    if role not in {"GATE", "SIMION", "COMSOL"} or not stage or not run_id:
        raise ValueError("process execution requires a known role, stage and run ID")
    settings = {name: str(getattr(context, name)) for name in
                ("workspace", "python_executable", "host_state_path", "policy_path")}
    request = {**{name: str(path) for name, path in paths.items()}, "context": settings,
               "argument_line": subprocess.list2cmdline(list(arguments)), "role": role,
               "stage": stage, "run_id": run_id, "limits": None if limits is None else dict(limits),
               "environment": {} if environment is None else dict(environment), "window_style": window_style}
    if immutable_input_records:
        records = [dict(record) for record in immutable_input_records]
        seen = set()
        for record in records:
            path = Path(record.get("path", ""))
            digest = record.get("sha256")
            if (not path.is_absolute() or record.get("exists") is not True
                    or type(record.get("bytes")) is not int or record["bytes"] < 0
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdefABCDEF" for char in digest)
                    or str(path.resolve()).casefold() in seen):
                raise ValueError("immutable inputs require unique absolute frozen file records")
            seen.add(str(path.resolve()).casefold())
        request["immutable_input_records"] = records
    return _invoke_process_owner(context, request, 'process_owner.ps1', _interpret_process_result)


def _invoke_process_owner(context, request, resource_name, interpret):
    """Use the same healthy-owner transport/drain for single and group calls."""
    command = [str(context.powershell_executable), "-NoLogo", "-NoProfile", "-NonInteractive",
               "-File", str(resource_path(resource_name))]
    child_environment = dict(os.environ)
    child_environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = str(context.host_state_path)
    child_environment["SIMULATION_PYTHON_EXE"] = str(context.python_executable)
    payload = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
    process = subprocess.Popen(command, cwd=context.workspace, env=child_environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    primary = None
    close_errors = []
    try:
        output, errors = process.communicate(payload)
    except BaseException as error:
        error.execution_bridge_started = True
        primary = error
        _finish_bridge_after_failure(process, error)
        raise
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except BaseException as error:
                    if primary is not None:
                        primary.add_note(f"Execution bridge stream close failed: {error}")
                    else:
                        close_errors.append(error)
    try:
        receipt = interpret(output, errors, process.returncode)
    except BaseException as failure:
        failure.execution_bridge_started = True
        for error in close_errors:
            failure.add_note(f"Execution bridge stream close secondary: {error}")
        raise
    if close_errors:
        failure = ProcessExecutionError(f"Execution bridge stream close failed: {close_errors[0]}", receipt)
        for error in close_errors[1:]:
            failure.add_note(f"Execution bridge stream close secondary: {error}")
        raise failure
    return receipt


def _interpret_batch_result(output: bytes, errors: bytes, returncode: int) -> dict[str, Any]:
    """Preserve every real child result and the original group failure."""
    prefix = 'EXECUTION_BATCH_RESULT='
    try:
        lines = [line[len(prefix):] for line in output.decode('utf-8').splitlines() if line.startswith(prefix)]
        if len(lines) != 1:
            raise ValueError('no unique batch receipt')
        receipt = json.loads(lines[0])
        if (not isinstance(receipt, dict) or set(receipt) != {'observations','attempts','not_started','error','host_release'}
                or not isinstance(receipt['observations'], dict) or not isinstance(receipt['not_started'], list)
                or not isinstance(receipt['attempts'], list)):
            raise ValueError('batch result fields differ')
    except (UnicodeError, ValueError) as error:
        raise ProcessExecutionError(f'Execution batch result is invalid: {error}; stderr={errors!r}', {}) from error
    original = receipt['error']
    if original is not None:
        if not isinstance(original, dict) or not isinstance(original.get('message'), str):
            raise ProcessExecutionError('Execution batch error record is invalid', receipt)
        failure = ProcessExecutionError(original['message'], receipt)
    else:
        failure = None
    for name, observation in receipt['observations'].items():
        try:
            _interpret_process_result(('EXECUTION_PROCESS_RESULT='+json.dumps(dict(
                observation=observation,error=None,host_release=receipt['host_release']))).encode('utf-8'), b'', 0)
        except ProcessExecutionError as error:
            if failure is None:
                failure = ProcessExecutionError(f'{name}: {error}', receipt)
            else:
                failure.add_note(f'Batch child {name}: {error}')
    if receipt['not_started'] and failure is None:
        failure = ProcessExecutionError('Execution batch did not start all declared operations', receipt)
    try:
        release = _host_release(receipt)
        if not release['inherited'] and (release['error'] is not None or (release['result'] or {}).get('status') != 'released'):
            raise ValueError('batch host release unconfirmed')
    except ValueError as error:
        if failure is None:
            failure = ProcessExecutionError(str(error),receipt)
        else:
            failure.add_note(f'Execution batch release secondary: {error}')
    if returncode and failure is None:
        failure = ProcessExecutionError(f'Execution batch owner failed with exit {returncode}',receipt)
    if failure is not None:
        raise failure
    return receipt


def run_observed_process_group(context: ExecutionContext, *, specifications: Sequence[Mapping[str, Any]],
                               dispatch_plan: Mapping[str, Any], run_directory: Path, usage_path: Path,
                               role: str, stage: str, run_id: str, formal_operation_id: str | None = None,
                               immutable_input_records: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Transport a fixed-unit group to the sole existing installed dispatcher.

    There is no Python pool, retry, resource policy or lifecycle here. A formal
    operation is the real largest missing unit from the existing fixed planner.
    Native/semantic completion remains the consuming backend's responsibility.
    """
    from msplatform.execution.recorded_file_removal import write_json_atomic
    inherited_host_token(context)
    if (role not in {'GATE','SIMION','COMSOL'} or not stage or not run_id
            or not Path(run_directory).is_absolute() or not Path(usage_path).is_absolute()):
        raise ValueError('batch requires explicit owner, role and absolute output paths')
    if isinstance(specifications,(str,bytes)) or not specifications:
        raise ValueError('batch specifications must be a nonempty explicit sequence')
    seen, rows = set(), []
    for spec in specifications:
        expected = {'operation_id','executable','arguments','working_directory','stdout_path','stderr_path',
                    'receipt_path','environment','scheduler_batch'}
        if not isinstance(spec,Mapping) or set(spec) != expected:
            raise ValueError('batch process specification fields differ')
        name = spec['operation_id']
        if not isinstance(name,str) or not name or name in seen:
            raise ValueError('batch operation IDs must be unique')
        seen.add(name)
        if any(not Path(spec[key]).is_absolute() for key in ('executable','working_directory','stdout_path','stderr_path','receipt_path')):
            raise ValueError('batch process paths must be absolute')
        args = spec['arguments']
        if isinstance(args,(str,bytes)) or any(not isinstance(value,str) or '\0' in value for value in args):
            raise ValueError('batch argv must be an explicit string sequence without NUL')
        if not isinstance(spec['environment'],Mapping) or not isinstance(spec['scheduler_batch'],Mapping):
            raise ValueError('batch environment and ordinal unit must be objects')
        rows.append({**{key:str(spec[key]) for key in ('operation_id','executable','working_directory','stdout_path','stderr_path','receipt_path')},
                     'argument_line':subprocess.list2cmdline(list(args)), 'environment':dict(spec['environment']),
                     'scheduler_batch':dict(spec['scheduler_batch'])})
    if dispatch_plan.get('role') != 'simion_repository_dispatch_plan':
        raise ValueError('batch requires the existing repository dispatch plan')
    if formal_operation_id is not None:
        if formal_operation_id not in seen or dispatch_plan.get('estimation',{}).get('recovered_missing_observation') is not True:
            raise ValueError('formal batch requires the existing fixed-partition missing-unit observation plan')
    records, paths = [], set()
    for value in immutable_input_records:
        row = dict(value);path = Path(row.get('path',''));digest = row.get('sha256')
        if (not path.is_absolute() or row.get('exists') is not True or type(row.get('bytes')) is not int or row['bytes'] < 0
                or not isinstance(digest,str) or len(digest) != 64 or any(c not in '0123456789abcdefABCDEF' for c in digest)
                or str(path.resolve()).casefold() in paths):
            raise ValueError('batch immutable inputs require unique absolute frozen records')
        paths.add(str(path.resolve()).casefold());records.append(row)
    runtime_plan = Path(usage_path).with_suffix('.dispatch.json')
    if runtime_plan.exists():
        raise FileExistsError('batch runtime dispatch output already exists')
    write_json_atomic(runtime_plan,dict(dispatch_plan))
    request = dict(specifications=rows,dispatch_plan_path=str(runtime_plan),formal_operation_id=formal_operation_id,
        run_directory=str(run_directory),usage_path=str(usage_path),role=role,stage=stage,run_id=run_id,
        immutable_input_records=records,context={name:str(getattr(context,name)) for name in
            ('workspace','python_executable','host_state_path','policy_path')})
    def checked(output, errors, returncode):
        receipt = _interpret_batch_result(output,errors,returncode)
        completed = set(receipt['observations'])
        pending = receipt['not_started']
        if len(pending) != len(set(pending)) or completed.intersection(pending) or completed.union(pending) != seen:
            raise ProcessExecutionError('Batch result does not cover its exact declared operations',receipt)
        return receipt
    return _invoke_process_owner(context,request,'batch_process_owner.ps1',checked)
