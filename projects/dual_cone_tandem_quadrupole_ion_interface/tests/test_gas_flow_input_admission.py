"""Actual installed scientific boundaries in isolated frozen source consumers."""

from pathlib import Path
import json
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from msplatform.backends.comsol.gas_flow import compiled_gas_flow_paths, resolve_gas_flow_request
from msplatform.io.manifest_records import file_record
from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import _write_fixture

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
NAMES = ("baseline.json", "resolved_geometry.json", "gas_flow_science.json", "comsol_solver_numerics.json")


def cold(root, code, paths):
    dependencies = list(dict.fromkeys(sysconfig.get_path(name) for name in ("purelib", "platlib")))
    bootstrap = "import sys,json,pathlib; sys.path.extend(json.loads(sys.argv[2])); sys.path.insert(0,sys.argv[1]); "
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            bootstrap + code,
            str(root / "src"),
            json.dumps(dependencies),
            *map(str, paths),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


class GasFlowInputAdmissionTests(unittest.TestCase):
    def test_frozen_geometry_pair_and_stale_failure_stop_downstream(self):
        for scenario in ("normal", "stale", "source_changed"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(
                    REPO / "src/msplatform", root / "src/msplatform", ignore=shutil.ignore_patterns("__pycache__")
                )
                paths = []
                for name in NAMES:
                    target = root / name
                    target.write_bytes((PROJECT / "config" / name).read_bytes())
                    paths.append(target)
                if scenario == "stale":
                    paths[1].write_bytes(paths[1].read_bytes() + b" ")
                if scenario == "source_changed":
                    poison = root / "active_source/msplatform/backends/comsol"
                    poison.mkdir(parents=True)
                    (poison / "gas_flow.py").write_text("raise RuntimeError('ACTIVE_REPO_FALLBACK')", encoding="utf-8")
                code = """
from msplatform.backends.comsol.gas_flow import resolve_gas_flow_request
import numpy
request=resolve_gas_flow_request(*map(pathlib.Path,sys.argv[3:7]))
assert set(request['inputs'])=={'baseline','geometry','science','numerics'}
assert all(pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
           for name,module in sys.modules.items() if name=='msplatform' or name.startswith('msplatform.'))
print('GEOMETRY_INPUT_ADMISSION=PASS NUMPY='+numpy.__version__)
"""
                result = cold(root, code, paths)
                if scenario == "stale":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("resolved geometry is stale", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("GEOMETRY_INPUT_ADMISSION=PASS NUMPY=", result.stdout)
                self.assertNotIn("ACTIVE_REPO_FALLBACK", result.stdout + result.stderr)
                self.assertFalse((root / "artifacts").exists())

    def test_postprocess_imports_gas_field_from_frozen_repository_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(
                REPO / "src/msplatform", root / "src/msplatform", ignore=shutil.ignore_patterns("__pycache__")
            )
            csv_path, metadata_path = _write_fixture(root)
            paths = [csv_path, metadata_path]
            for name in NAMES[2:] + NAMES[1:2]:
                target = root / name
                target.write_bytes((PROJECT / "config" / name).read_bytes())
                paths.append(target)
            code = """
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface import gas_field_validation as gas_field
assert pathlib.Path(gas_field.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
gas_field.validate_gas_field(*map(pathlib.Path,sys.argv[3:8]))
print('FROSNAPSHOT')
"""
            result = cold(root, code, paths)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FROSNAPSHOT", result.stdout)
            self.assertNotIn("ACTIVE_FALLBACK", result.stdout + result.stderr)
            (root / "src/msplatform/components/dual_cone_tandem_quadrupole_ion_interface/gas_field_validation.py").unlink()
            missing = cold(root, code, paths)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("gas_field", missing.stderr)

    def test_current_compiler_baseline_pair_and_missing_old_bundle(self):
        from common.contracts.compile_execution_plan import compile_execution
        from msplatform.contracts.machine_contracts import sha256

        registry_path = REPO / "config/project_registry.json"
        for scenario in ("compiled_pair", "missing_baseline", "stale_resolved"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                request_path = root / "request.json"
                request_path.write_text("{}", encoding="utf-8")
                deployment = root / "machine.json"
                deployment.write_text("{}", encoding="utf-8")
                plan = dict(
                    role="solver_neutral_design_plan",
                    request_status="approved",
                    project_id=PROJECT.name,
                    capability_id="axisymmetric_gas_flow_field_generation",
                    mode="axisymmetric_gas_flow_screening",
                    requested_evidence_level="plan",
                    run_id="20260720_130000__analysis__repo__design-request",
                    operating_points=[],
                    objectives=[],
                    design_variables=[],
                    constraints=[],
                    required_outputs=[],
                    provenance=dict(
                        request=dict(path=str(request_path), sha256=sha256(request_path)),
                        project_registry=dict(sha256=sha256(registry_path)),
                    ),
                )
                plan_path = root / "plan.json"
                plan_path.write_text(json.dumps(plan), encoding="utf-8")
                compiled = compile_execution(
                    plan_path,
                    registry_path,
                    bindings=dict(
                        deployment_path=str(deployment),
                        workspace=str(root / "new workspace"),
                        engineering_profile="local",
                    ),
                    purpose="field_generation",
                    qualification="none",
                )
                self.assertEqual(compiled["status"], "EXECUTION_READY", compiled.get("blockers"))
                expected = {"geometry_baseline", "resolved_geometry", "gas_flow_science", "comsol_solver_numerics"}
                self.assertEqual({row["name"] for row in compiled["resolved_inputs"]}, expected)
                private = root / "compiled"
                records = []
                for row in compiled["resolved_inputs"]:
                    target = private / row["relative_path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(row["content"], encoding="utf-8", newline="")
                    records.append(dict(row, path=str(target)))
                if scenario == "missing_baseline":
                    records = [row for row in records if row["name"] != "geometry_baseline"]
                if scenario == "stale_resolved":
                    target = private / "config/resolved_geometry.json"
                    target.write_bytes(target.read_bytes() + b" ")
                bundle = root / "compiled_inputs.json"
                bundle.write_text(
                    json.dumps(
                        dict(
                            role="compiled_execution_inputs", project_id=PROJECT.name, root=str(private), files=records
                        )
                    ),
                    encoding="utf-8",
                )
                if scenario == "compiled_pair":
                    paths = compiled_gas_flow_paths(bundle)
                    resolved = resolve_gas_flow_request(*paths)
                    self.assertEqual(len(resolved["inputs"]), 4)
                    for path, record in zip(paths, records):
                        self.assertEqual(file_record(path)["sha256"], record["sha256"])
                    self.assertFalse((root / "new workspace").exists())
                elif scenario == "missing_baseline":
                    with self.assertRaisesRegex(ValueError, "geometry_baseline"):
                        compiled_gas_flow_paths(bundle)
                else:
                    with self.assertRaisesRegex(AssertionError, "changed"):
                        compiled_gas_flow_paths(bundle)
