"""One existing run package's neutral action/observed-process facts, not another scheduler."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from msplatform.execution.context import ExecutionContext
from msplatform.execution.capacity_session import renew_capacity_session
from msplatform.execution.manifest_records import verify_record
from msplatform.execution.processes import ProcessExecutionError, run_observed_process, run_observed_process_group
from msplatform.execution.recorded_file_removal import write_json_atomic


@dataclass
class RunSession:
    """The explicit package given to one prepared action.

    Files retain canonical identities; run_dir can be the existing short junction.
    The action declares file roles and uses the unique observed-process transport.
    Dependencies are checked, not scheduled or retried by this object.
    """
    context: ExecutionContext
    artifact_root: Path
    run_id: str
    project: str
    mode: str
    package: dict[str, Any]
    capacity_session: dict[str, Any]
    execution_request: Path
    result_path: Path
    expected_operation_ids: tuple[str, ...] = ()
    operation_dependencies: Mapping[str, Sequence[str]] = field(default_factory=dict)
    file_roles: dict[str, str] = field(default_factory=dict)
    operations: list[dict[str, Any]] = field(default_factory=list)
    resource_releases: list[dict[str, Any]] = field(default_factory=list)
    _active: set[str] = field(default_factory=set, repr=False)
    _completed: dict[str, int] = field(default_factory=dict, repr=False)
    _attempted: set[str] = field(default_factory=set, repr=False)
    _lock: Any = field(default_factory=RLock, repr=False)

    @property
    def run_dir(self) -> Path:
        return Path(self.package["run_dir"])

    @property
    def artifact_run_dir(self) -> Path:
        return Path(self.package["artifact_run_dir"])

    @property
    def input_dir(self) -> Path:
        return self.run_dir / "inputs"

    @property
    def result_dir(self) -> Path:
        return self.run_dir / "results"

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def run_config(self) -> Path:
        return self.artifact_run_dir / "run_config.json"

    @property
    def writers_stopped(self) -> bool:
        with self._lock:
            return not self._active

    @property
    def environment(self) -> dict[str, str]:
        return dict(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(self.artifact_root),
            MASS_SPECTROMETRY_EXECUTION_ROOT=str(self.context.execution_root),
            MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(self.context.host_state_path),
            MASS_SPECTROMETRY_RUN_DIRECTORY=str(self.artifact_run_dir),
            MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=str(self.run_dir),
            SIMULATION_PYTHON_EXE=str(self.context.python_executable))

    def renew_capacity(self, *, remaining_committed_new_bytes: int | None = None,
                       protected_cache_keys: Sequence[str] = ()) -> dict[str, Any]:
        """Renew the same finite lease, preserving its original closure deadline."""
        with self._lock:
            result = renew_capacity_session(self.capacity_session,
                remaining_committed_new_bytes=remaining_committed_new_bytes,
                protected_cache_keys=protected_cache_keys)
            write_json_atomic(self.artifact_run_dir / "logs/capacity_session.json", self.capacity_session)
            return result

    def defer_capacity_finalization(self, reason: str) -> None:
        """Persist the original stopped-stage accounting hold, without releasing it.

        Only the original accounting owner can reconcile this condition. This
        records no process completion and provides no clear/retry operation.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Deferred capacity accounting requires its actual reason")
        with self._lock:
            if self.capacity_session["status"] != "active":
                raise ValueError("Deferred capacity accounting requires the active original session")
            self.capacity_session.setdefault("defer_capacity_finalization", reason)
            write_json_atomic(self.artifact_run_dir / "logs/capacity_session.json", self.capacity_session)

    def canonical_path(self, path: str | Path) -> Path:
        path = Path(path)
        return (self.artifact_run_dir / path).resolve() if not path.is_absolute() else path.resolve()

    def declare_file(self, path: str | Path, retention_role: str) -> Path:
        """Register an explicit role; no suffix-to-physics or undeclared-file fallback."""
        if retention_role not in {"required_evidence", "lightweight_optional", "solver_native_binary",
                                  "dense_trajectory", "large_optional"}:
            raise ValueError("Unknown declared retention role")
        target = self.canonical_path(path)
        with self._lock:
            previous = self.file_roles.setdefault(str(target), retention_role)
            if previous != retention_role:
                raise ValueError("Declared file retention role changed")
        return target

    def add_input(self, name: str, record: Mapping[str, Any]) -> None:
        """Bind an actual record and its role into the existing run configuration."""
        if not isinstance(name, str) or not name or name == "execution_request":
            raise ValueError("Input name is missing or reserved")
        verify_record(name, dict(record))
        target = self.declare_file(Path(record["path"]), record["retention_role"])
        with self._lock:
            config = json.loads(self.run_config.read_text(encoding="utf-8-sig"))
            if name in config["inputs"]:
                raise ValueError("Run input name already exists")
            config["inputs"][name] = str(target)
            write_json_atomic(self.run_config, config)

    def classify_file(self, path: Path, **_options: Any) -> str:
        """Classify only this action's explicit records and owner-created metadata."""
        target = self.canonical_path(path)
        try:
            return self.file_roles[str(target)]
        except KeyError as error:
            raise ValueError(f"Run contains an undeclared file: {target}") from error

    def _record_process(self, operation_id: str, receipt: dict[str, Any]) -> None:
        observation = receipt.get("observation")
        if not isinstance(observation, dict):
            error = receipt.get("error")
            data = error.get("data") if isinstance(error, dict) else None
            if isinstance(data, dict) and data.get("observed_process_exit_confirmed") is True:
                # Original public process-owner failure facts; never infer exit from a PID/file.
                observation = dict(exit_code=data.get("observed_process_returncode"),
                    root_process_id=data.get("observed_process_id"),
                    root_process_started_at_utc_ticks=data.get("observed_process_started_at_utc_ticks"))
        if (not isinstance(observation, dict) or any(type(observation.get(name)) is not int
                for name in ("exit_code", "root_process_id", "root_process_started_at_utc_ticks"))
                or observation["root_process_id"] <= 0 or observation["root_process_started_at_utc_ticks"] <= 0):
            return  # An unknown writer keeps its active entry and all protection.
        release = receipt.get("host_release")
        with self._lock:
            release_id = "host-resource-" + str(len(self.resource_releases) + 1)
            if isinstance(release, dict):
                same = next((row for row in self.resource_releases
                    if row["completion_receipt"]["host_release"] == release), None)
                if same is None:
                    self.resource_releases.append(dict(release_id=release_id,
                        completion_receipt={"host_release": release}))
                else:
                    release_id = same["release_id"]
            self.operations.append(dict(operation_id=operation_id,
                observation=dict(exit_confirmed=True, returncode=observation["exit_code"],
                    process_id=observation["root_process_id"],
                    process_started_at_utc_ticks=observation["root_process_started_at_utc_ticks"]),
                resource_release_id=release_id))
            self._completed[operation_id] = observation["exit_code"]
            self._active.remove(operation_id)

    def run_process(self, operation_id: str, *, executable: Path, arguments: Sequence[str],
                    role: str, stage: str, limits: Mapping[str, Any] | None,
                    environment: Mapping[str, str] | None = None,
                    stdout_role: str = "required_evidence",
                    immutable_input_records: Sequence[Mapping[str, Any]] = (),
                    window_style: str = "Hidden") -> dict[str, Any]:
        """Run one declared operation once; always retain its actual transport receipt."""
        if not isinstance(window_style, str) or window_style not in {"Hidden", "Normal"}:
            raise ValueError("window_style requires exactly Hidden or Normal")
        if not Path(executable).is_file():
            raise FileNotFoundError(f"Execution tool is unavailable: {executable}")
        actual_environment = self.environment
        supplied_environment = dict(environment or {})
        if any(name in actual_environment and value != actual_environment[name]
               for name, value in supplied_environment.items()):
            raise ValueError("Operation cannot override its frozen execution environment")
        actual_environment.update(supplied_environment)
        self.renew_capacity()
        with self._lock:
            if operation_id not in self.expected_operation_ids or operation_id in self._attempted:
                raise ValueError("Operation is undeclared or has already been attempted")
            if any(self._completed.get(parent) != 0 for parent in self.operation_dependencies.get(operation_id, ())):
                raise ValueError("Operation prerequisites have not completed successfully")
            self._attempted.add(operation_id)
            self._active.add(operation_id)
            ordinal = self.expected_operation_ids.index(operation_id) + 1
        base = self.log_dir / f"operation_{ordinal:04d}"
        stdout = self.declare_file(base.with_suffix(".stdout.log"), stdout_role)
        stderr = self.declare_file(base.with_suffix(".stderr.log"), "required_evidence")
        usage = self.declare_file(base.with_suffix(".usage.json"), "required_evidence")
        record_path = self.declare_file(base.with_suffix(".process.json"), "required_evidence")
        receipt = None
        primary = None
        try:
            protected = ({"immutable_input_records": immutable_input_records} if immutable_input_records else {})
            receipt = run_observed_process(self.context, executable=executable, arguments=arguments,
                working_directory=self.run_dir, run_directory=self.artifact_run_dir,
                stdout_path=stdout, stderr_path=stderr, usage_path=usage,
                role=role, stage=stage, run_id=self.run_id, limits=limits,
                environment=actual_environment, window_style=window_style, **protected)
            return receipt
        except BaseException as failure:
            primary = failure
            if isinstance(failure, ProcessExecutionError):
                receipt = failure.receipt
            raise
        finally:
            if receipt is not None:
                try:
                    self._record_process(operation_id, receipt)
                    write_json_atomic(record_path, receipt)
                except BaseException as secondary:
                    if primary is None:
                        raise
                    primary.add_note(f"Process receipt preservation failed: {secondary!r}")


    def run_process_group(self, specifications: Sequence[Mapping[str, Any]], *, dispatch_plan: Mapping[str, Any],
                          group_id: str, role: str, stage: str, formal_operation_id: str | None = None,
                          immutable_input_records: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        """Record a fixed-unit group executed by the existing public dispatcher.

        Operations have no dependencies on other members of this concurrent
        group. Unstarted members are explicit facts, never invented PID/exit0.
        All started unknown writers remain active until the same holder drains.
        """
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',group_id):
            raise ValueError('batch group ID must be an explicit filename-safe identifier')
        if not specifications or isinstance(specifications,(str,bytes)):
            raise ValueError('batch specifications must be a nonempty sequence')
        ids = [row['operation_id'] for row in specifications]
        if len(ids) != len(set(ids)):
            raise ValueError('batch operation IDs are duplicated')
        prepared, receipt_paths = [], {}
        for spec in specifications:
            if (set(spec)-{'operation_id','executable','arguments','scheduler_batch','environment','working_directory'}
                    or not {'operation_id','executable','arguments','scheduler_batch'} <= set(spec)):
                raise ValueError('group process specification fields differ')
            if not Path(spec['executable']).is_file():
                raise FileNotFoundError(f"Execution tool is unavailable: {spec['executable']}")
            environment = self.environment
            supplied = dict(spec.get('environment',{}))
            if any(key in environment and environment[key] != value for key,value in supplied.items()):
                raise ValueError('Group operation cannot override frozen execution environment')
            environment.update(supplied)
            if spec['operation_id'] not in self.expected_operation_ids:
                raise ValueError('Group operation is undeclared')
            ordinal = self.expected_operation_ids.index(spec['operation_id'])+1
            base = self.log_dir/f'operation_{ordinal:04d}'
            stdout = self.declare_file(base.with_suffix('.stdout.log'),'required_evidence')
            stderr = self.declare_file(base.with_suffix('.stderr.log'),'required_evidence')
            receipt_paths[spec['operation_id']] = self.declare_file(base.with_suffix('.process.json'),'required_evidence')
            prepared.append(dict(operation_id=spec['operation_id'],executable=Path(spec['executable']),arguments=list(spec['arguments']),
                scheduler_batch=dict(spec['scheduler_batch']),environment=environment,
                working_directory=Path(spec.get('working_directory',self.run_dir)),stdout_path=stdout,stderr_path=stderr,
                receipt_path=receipt_paths[spec['operation_id']]))
        self.renew_capacity()
        base = self.log_dir/('group_'+group_id)
        usage = self.declare_file(base.with_suffix('.usage.json'),'required_evidence')
        self.declare_file(usage.with_suffix('.dispatch.json'),'required_evidence')
        group_path = self.declare_file(base.with_suffix('.process.json'),'required_evidence')
        request_path = self.declare_file(base.with_suffix('.request.json'),'required_evidence')
        if request_path.exists():
            raise FileExistsError('Batch group request already exists')
        write_json_atomic(request_path,dict(operation_ids=ids,dispatch_plan=dict(dispatch_plan),
            specifications=[{key:(str(value) if isinstance(value,Path) else value) for key,value in row.items()} for row in prepared],
            formal_operation_id=formal_operation_id,immutable_input_records=list(immutable_input_records)))
        with self._lock:
            for name in ids:
                if name in self._attempted or any(self._completed.get(parent) != 0 for parent in self.operation_dependencies.get(name,())):
                    raise ValueError('Group operation was attempted or prerequisites are incomplete')
            self._attempted.update(ids);self._active.update(ids)
        receipt, primary = None, None
        try:
            receipt = run_observed_process_group(self.context,specifications=prepared,dispatch_plan=dispatch_plan,
                run_directory=self.artifact_run_dir,usage_path=usage,role=role,stage=stage,run_id=self.run_id,
                formal_operation_id=formal_operation_id,immutable_input_records=immutable_input_records)
            return receipt
        except BaseException as failure:
            primary = failure
            if isinstance(failure,ProcessExecutionError):
                receipt = failure.receipt
            elif not getattr(failure,'execution_bridge_started',False):
                # JSON/specification/Popen preflight failed before a bridge
                # existed; no writer identity is invented for these members.
                with self._lock:
                    self._active.difference_update(ids)
            raise
        finally:
            if receipt is not None:
                try:
                    write_json_atomic(group_path,receipt)
                    for name,observation in receipt.get('observations',{}).items():
                        if name not in ids:
                            raise ValueError('Batch owner returned an undeclared operation')
                        child = dict(observation=observation,error=receipt.get('error'),host_release=receipt.get('host_release'))
                        self._record_process(name,child)
                        write_json_atomic(receipt_paths[name],child)
                    not_started = receipt.get('not_started',[])
                    if any(name not in ids or name in receipt.get('observations',{}) for name in not_started):
                        raise ValueError('Batch not-started facts conflict with actual observations')
                    with self._lock:
                        self._active.difference_update(not_started)
                except BaseException as secondary:
                    if primary is None:
                        raise
                    primary.add_note(f'Batch receipt preservation failed: {secondary!r}')
