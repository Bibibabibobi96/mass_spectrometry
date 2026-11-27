"""Installed mass-spectrum API and original thin-CLI software acceptance."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.workflows import single_reflection_mass_spectrum_study as study

PROJECT = Path(__file__).resolve().parents[4] / "src/msplatform/components/single_reflection_oa_tof"
REPO = Path(__file__).resolve().parents[4]
RUN_ID = "20261116_120000__sim__cross__mass-installed"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class MassSpectrumStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli_environment = tempfile.TemporaryDirectory(prefix="oatof-spectrum-cli-python-")
        environment_root = Path(cls.cli_environment.name)
        subprocess.run([sys.executable, "-m", "venv", str(environment_root)],
            check=True, capture_output=True, text=True, timeout=120, cwd=environment_root)
        cls.cli_python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        # A child venv does not inherit its parent's venv packages. Select the
        # parent's actual dependency roots explicitly instead of host packages.
        import importlib
        dependency_roots = sorted({str(Path(importlib.import_module(name).__file__).resolve().parent.parent)
            for name in ("numpy", "scipy", "pandas", "matplotlib")})
        purelib = Path(subprocess.run([str(cls.cli_python), "-I", "-c",
            "import sysconfig;print(sysconfig.get_path('purelib'))"], check=True, capture_output=True,
            text=True, timeout=30, cwd=environment_root).stdout.strip())
        (purelib / "candidate-selected-dependencies.pth").write_text(
            "\n".join(dependency_roots) + "\n", encoding="utf-8")
        build_environment = {key: value for key, value in os.environ.items()
            if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
        build_environment["PYTHONNOUSERSITE"] = "1"
        installed = subprocess.run([str(cls.cli_python), "-m", "pip", "install", "--no-deps",
            str(REPO)], check=False, capture_output=True, text=True,
            timeout=120, cwd=environment_root, env=build_environment)
        if installed.returncode:
            raise RuntimeError("CLI environment package installation failed:\n" + installed.stdout + installed.stderr)
        origin = subprocess.run([str(cls.cli_python), "-I", "-c",
            "from pathlib import Path;import msplatform.workflows.single_reflection_mass_spectrum_study as m;print(Path(m.__file__).resolve())"],
            check=True, capture_output=True, text=True, timeout=30, cwd=environment_root).stdout.strip()
        if not Path(origin).is_relative_to(environment_root):
            raise RuntimeError("CLI environment did not use its installed current package")

    @classmethod
    def tearDownClass(cls):
        cls.cli_environment.cleanup()

    @contextmanager
    def workspace(self):
        root = Path(tempfile.mkdtemp(prefix="oatof-managed-spectrum-"))
        retain = False
        try:
            yield root
        except BaseException:
            retain = True
            raise
        finally:
            holds = []
            for path in root.glob("artifacts/components/*/scratch/workflow_results/*/result.json"):
                value = _json(path)
                if value.get("resume_action") is not None or value.get("writers_confirmed") is False:
                    holds.append(path)
            if retain or holds:
                print("MASS_SPECTRUM_RETAINED_WORKSPACE=" + str(root))
            else:
                shutil.rmtree(root)

    def context(self, root: Path):
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.resources import resource_path
        stage = root / "stage-policy.json"
        _write_json(stage, dict(schema_version=1, role="execution_stage_policy", stages={
            study.ACTION: dict(limits=dict(wall_clock_seconds=120,
                transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648,
                minimum_system_available_memory_bytes=1073741824,
                compact_final_retained_bytes=67108864, automatic_retry_count=0),
                artifact_retention=dict(policy_version=1, **{"class": "solver_review"},
                                        reason="software native fixture"))}))
        capacity = root / "capacity-policy.json"
        policy = _json(resource_path("artifact_capacity_policy.json"))
        policy.update(target_gib=1, minimum_free_gib=64 / 1024)
        _write_json(capacity, policy)
        host = json.loads(os.environ["MASS_SPECTROMETRY_HOST_CONTEXT_JSON"])
        return ExecutionContext(workspace=root, python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh")), tools={},
            host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
            policy_path=Path(host["policy_path"]), capacity_policy_path=capacity,
            stage_policy_path=stage)

    def inputs(self, root: Path) -> dict[str, Path]:
        context = self.context(root)
        artifact_project = root / "artifacts/components/single_reflection_oa_tof_mass_analyzer"
        formal = artifact_project / "formal"
        (formal / "comsol").mkdir(parents=True, exist_ok=True)
        (formal / "simion").mkdir(parents=True, exist_ok=True)
        mph = formal / "comsol/single_reflection_oa_tof_mass_analyzer__model.mph"
        mph.write_bytes(b"inert formal mass-spectrum model")
        assets = _json(PROJECT / "config/formal_assets.json")
        assets["comsol"]["sha256"] = hashlib.sha256(mph.read_bytes()).hexdigest().upper()
        formal_assets = root / "formal_assets.json"
        _write_json(formal_assets, assets)
        iob = formal / "simion/oatof_ideal_grounded.iob"
        iob.write_bytes(b"inert formal IOB")
        record = file_record(iob, "solver_native_binary")
        manifest = dict(schema_version=1, role="formal_asset_manifest",
            project=study.PROJECT, release_id=assets["release_id"], assets={
                "simion_iob": dict(path="simion/oatof_ideal_grounded.iob",
                                   bytes=record["bytes"], sha256=record["sha256"])})
        asset_manifest = formal / "asset_manifest.json"
        _write_json(asset_manifest, manifest)
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
        if load_capacity_ledger(root / "artifacts") is None:
            initialize_capacity_ledger(root / "artifacts", objects=[])
        simion = root / "inert-simion.exe"
        simion.write_bytes(b"selected inert executable")
        return dict(mode_config=PROJECT / "config/modes/mass_spectrum.json",
            resolved_geometry=PROJECT / "config/resolved_geometry.json",
            particle_count_policy=REPO / "src/msplatform/contracts/particle_count_policy.json",
            formal_mph=mph, formal_asset_manifest=asset_manifest,
            simion_executable=simion, artifact_project_root=artifact_project,
            project_config=PROJECT / "config/project.json", formal_assets=formal_assets,
            baseline=PROJECT / "config/baseline.json",
            formal_mode=PROJECT / "config/modes/formal.json",
            solver_numerics=PROJECT / "config/formal_solver_numerics.json") | {
                "context": context}

    @staticmethod
    def native_leaf(root: Path) -> Path:
        leaf = root / "inert_native.py"
        leaf.write_text(r'''import csv,json,math,os,sys,time
from pathlib import Path
mode=sys.argv[1]
if mode=='comsol':
    report,output,ion,completion,run_id=map(Path,sys.argv[2:7])
    name=ion.stem;mass=float(name.split('_')[0][2:]);count=sum(1 for _ in ion.open())
    fail=os.environ.get('TEST_MASS_FAIL_SPECIES')==name
    with output.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['Ion','TofUs','XMm','YMm','Hit'])
        for i in range(1,count+1):writer.writerow([i,math.sqrt(mass)+(i-1)*.01,48.9,.2,not fail])
    report.write_text(('DETECTED=0/%d\nSTATUS=FAIL\n' if fail else 'DETECTED=%d/%d\nSTATUS=PASS\n')%((count,) if fail else (count,count)))
    release=output.parent/f'{output.stem}_fixedN{count}_selected_release_from_data_file.txt'
    release.write_text('native release fixture\n',encoding='utf-8')
    completion.write_text(json.dumps(dict(schema_version=1,role='comsol_launcher_completion',run_id=str(run_id),
        operations=[dict(operation_id='inert',observation=dict(exit_confirmed=True,returncode=0,
            process_id=os.getpid(),process_started_at_utc_ticks=1))],
        host_release=dict(inherited=True,token='inert-child',error=None))))
    raise SystemExit(23 if fail else 0)
arguments=sys.argv[2:]
ion=Path(arguments[arguments.index('--ion')+1]);rows=list(csv.reader(ion.open()))
for index,row in enumerate(rows,1):
    mass=float(row[1]);print(f'TRACE: detector_crossing ion={index} t={math.sqrt(mass)+(index%100)*.01} x=48.9 y=.2 z=0 r=.1 zmax=0')
''', encoding="utf-8")
        return leaf

    def run_study(self, root: Path, run_id: str, *, fail_species: str = "", partial_parent=None):
        values = self.inputs(root)
        context = values.pop("context")
        leaf = self.native_leaf(root)
        original = RunSession.run_process

        def inert(session, operation_id, *, executable, arguments, **kwargs):
            environment = dict(kwargs.get("environment") or {})
            if operation_id.startswith("comsol-"):
                index = arguments.index("-ReportPath")
                report = Path(arguments[index + 1])
                ion = Path(environment["OATOF_ION_TABLE"])
                completion = Path(arguments[arguments.index("-CompletionPath") + 1])
                output = Path(environment["OATOF_COMSOL_OUTPUT_CSV"])
                argv = [str(leaf), "comsol", str(report), str(output), str(ion),
                        str(completion), session.run_id]
            else:
                ion = Path(arguments[arguments.index("--particles") + 1])
                argv = [str(leaf), "simion", "--ion", str(ion)]
            environment["TEST_MASS_FAIL_SPECIES"] = fail_species
            return original(session, operation_id, executable=Path(sys.executable),
                            arguments=argv, **{**kwargs, "environment": environment})

        with patch.object(RunSession, "run_process", inert), patch.dict(os.environ, {
                "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "",
                "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "",
                "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE": ""}):
            return study.run(context, run_id=run_id, partial_parent=partial_parent, **values)

    def saved_environment(self, root: Path) -> Path:
        context = self.context(root)
        path = root / "execution-environment.json"
        _write_json(path, dict(schema_version=1, role="execution_environment",
            tools=dict(python=str(type(self).cli_python.resolve()),
                       powershell=str(context.powershell_executable)),
            policy=dict(host_state_path=str(context.host_state_path),
                        policy_path=str(context.policy_path),
                        execution_root=str(context.execution_root),
                        capacity_policy_path=str(context.capacity_policy_path)),
            profiles=dict(test=dict(stage_policy_path=str(context.stage_policy_path)))))
        return path

    def cli(self, root: Path, run_id: str, *options: str):
        environment = self.saved_environment(root)
        arguments = ["pwsh", "-NoProfile", "-NonInteractive", "-File",
            str(PROJECT.parents[1] / "workflows/resources" / "run_mass_spectrum_candidate.ps1"),
            "-RunId", run_id, "-Workspace", str(root), "-ExecutionEnvironment", str(environment),
            "-EngineeringProfile", "test"]
        if "-ResumeFinalization" not in options:
            arguments += ["-ArtifactRootPath", str(root / "artifacts"), "-ScienceRoot", str(PROJECT)]
        return subprocess.run([*arguments, *options], cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
            env={**os.environ, "PYTHONPATH": str(REPO / "src"),
                 "SIMULATION_PYTHON_EXE": str(type(self).cli_python.resolve()),
                 "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "",
                 "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "",
                 "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE": ""})

    def test_retired_mass_run_and_partial_successor_refuse_before_owner(self):
        from unittest.mock import patch
        names = ("mode_config", "resolved_geometry", "particle_count_policy", "formal_mph",
                 "formal_asset_manifest", "simion_executable", "artifact_project_root",
                 "project_config", "formal_assets", "baseline", "formal_mode", "solver_numerics")
        paths = dict.fromkeys(names, Path("nonexistent"))
        with patch.object(study, "run_managed_stage") as owner, patch.object(RunSession, "run_process") as native:
            for parent in (None, {"completed": {"mz10_z1": "historical"}}):
                with self.subTest(partial_parent=parent), self.assertRaisesRegex(
                        ValueError, "legacy mass-spectrum run/resume is retired; use msplatform run with a mass_scan recipe"):
                    study.run(object(), run_id=RUN_ID, partial_parent=parent, **paths)
            owner.assert_not_called()
            native.assert_not_called()




    def test_original_cli_rejects_external_retrace_override(self):
        with self.workspace() as root:
            result = self.cli(root, RUN_ID, "--comsol-task", "external-retrace.m")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("comsol-task", result.stderr)
            self.assertFalse((root / "artifacts/components" / study.PROJECT / "runs" / RUN_ID).exists())

    def test_unknown_writer_and_scientific_receipt_negatives(self):
        with self.workspace() as root:
            values = self.inputs(root)
            # Exercise the backend's fail-closed writer state without a native tool.
            from msplatform.backends.comsol.oatof_retrace import load_launcher_completion
            receipt = root / "unknown.json"
            _write_json(receipt, dict(schema_version=1, role="comsol_launcher_completion",
                run_id=RUN_ID, operations=[dict(observation=dict(exit_confirmed=False))],
                host_release=dict(inherited=False, error="unknown")))
            with self.assertRaisesRegex(ValueError, "unknown"):
                load_launcher_completion(receipt, run_id=RUN_ID)
            with self.assertRaises(FileNotFoundError):
                study.validate_formal_inputs(project_config=values["project_config"],
                    formal_assets=values["formal_assets"], formal_mph=values["formal_mph"],
                    formal_asset_manifest=values["formal_asset_manifest"], baseline=values["baseline"],
                    formal_mode=values["formal_mode"], solver_numerics=values["solver_numerics"],
                    resolved_geometry=root / "missing-resolved.json")


if __name__ == "__main__":
    unittest.main()
