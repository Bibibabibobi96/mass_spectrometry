"""Controlled COMSOL I/O fixtures; no commercial executable or scientific result."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from msplatform.execution.run_session import RunSession
from msplatform.execution.resources import resource_path

def inert_native(arguments, *, model_relative_paths, failure=None):
    """Interpret explicit request paths only; do not execute MATLAB task text."""
    def value(name):
        return arguments[arguments.index(name) + 1]
    task = Path(value("-TaskScript"))
    root = task.parent.parent
    contract = root / "inputs/resolved_model.json"
    resolved = json.loads(contract.read_text(encoding="utf-8"))
    models = [root / relative for relative in model_relative_paths]
    model = models[-1]
    report = root / "results" / (task.stem + ".json")
    if task.stem == "build_model":
        for path in models:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"EXPLICIT_INERT_MPH_NOT_A_COMSOL_MODEL")
    elif failure == "tamper_stage":
        models[0].write_bytes(b"MODIFIED_BY_INERT_VERIFIER")
    elif failure == "tamper":
        model.write_bytes(b"MODIFIED_BY_INERT_VERIFIER")
    runtime = Path(value("-RunDir")) / "comsol_tmp"
    runtime.mkdir()
    (runtime / "inert.tmp").write_bytes(b"diagnostic only")
    if failure == "process":
        raise RuntimeError("inert original process failure")
    result = dict(status="PASS", execution_mode="build_only", model_path=str(model), contract_path=str(contract),
        contract_project_id=resolved["project_id"], contract_model_id=resolved["model_id"],
        selected_mode_id=resolved["selected_mode_id"], parameter_bindings_verified=True,
        candidate_evidence_allowed=False, geometry_built=True, mesh_built=True,
        electrostatics_solved=False, particle_tracing_solved=False, solution_data_empty=[True, True],
        compute_calls=0, model_rewritten=False, geometry_domains=3, mesh_complete=True,
        physics_tags=["es", "cpt"], study_tags=["std1", "std2"], solver_tags=["sol1", "sol2"])
    if task.stem == "verify_model" and failure == "solved":
        result["solution_data_empty"] = [False, True]
    report.write_text(json.dumps(result), encoding="utf-8")
    Path(value("-ReportPath")).write_text("STATUS=RUNNING\nSTATUS=PASS\n", encoding="utf-8")
    receipt = dict(schema_version=1, role="comsol_launcher_completion", run_id=value("-RunId"),
        operations=[dict(operation_id="launcher-attempt-1", observation=dict(exit_confirmed=True,
            returncode=0, process_id=1234, process_started_at_utc_ticks=12345))],
        host_release=dict(inherited=True, token="inert-outer-owner", result=None, error=None))
    if failure == "exit":
        receipt["operations"][0]["observation"]["exit_confirmed"] = False
    Path(value("-CompletionPath")).write_text(json.dumps(receipt), encoding="utf-8")


class InertComsolSession(RunSession):
    def __init__(self, root, *, model_relative_paths, failure=None):
        context = SimpleNamespace(workspace=root, python_executable=Path(sys.executable),
            powershell_executable=Path(sys.executable), host_state_path=root / "state.sqlite3",
            policy_path=resource_path("host_resource_policy.json"),
            tools=dict(comsol_launcher=Path(sys.executable), matlab_root=root))
        super().__init__(context=context, artifact_root=root.parent,
            run_id="inert-ei", project="inert_comsol_fixture", mode="inert_transport",
            package=dict(run_dir=root, artifact_run_dir=root),
            capacity_session=dict(fixture="inert_no_capacity_admission"),
            execution_request=root / "execution_request.json", result_path=root / "Result.json",
            expected_operation_ids=("build_model", "verify_model"))
        self.model_relative_paths = model_relative_paths
        for path in (self.input_dir, self.result_dir, self.log_dir):
            path.mkdir()
        self.run_config.write_text('{"inputs":{}}', encoding="utf-8")
        self.calls = []
        self.failure = failure

    def run_process(self, operation_id, **kwargs):
        self.calls.append((operation_id, kwargs))
        inert_native(kwargs["arguments"], model_relative_paths=self.model_relative_paths, failure=self.failure)
