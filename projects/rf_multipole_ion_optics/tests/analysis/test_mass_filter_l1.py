from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.contracts.capacity_ledger import initialize_capacity_ledger
from msplatform.execution.inputs import freeze_file
from msplatform.ion_release.numpy_box_cone import sample_numpy_box_cone_phase_space
from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    run_finite_length as RUNNER,
)

from msplatform.workflows.rf_mass_filter import finite_length as MODULE
from msplatform.components.rf_multipole import finite_length_transport as KERNEL

PROJECT_ROOT = Path(__file__).parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MassFilterL1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json")
        cls.resolved = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_mass_filter.json")
        cls.mode = load_json(PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json")
        cls.source = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json")

    @staticmethod
    def _run(artifact_root: Path, run_id: str) -> Path:
        # The unchanged owner requires genuinely owning operation leases, just
        # as NormalOwnerTests' actual zero/seven process fixture does.
        inherited = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',
            MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
        with patch.dict(os.environ, inherited):
            return RUNNER.run(
                RUNNER.DEFAULT_BASELINE, RUNNER.DEFAULT_RESOLVED, RUNNER.DEFAULT_MODE,
                RUNNER.DEFAULT_SOURCE, run_id, artifact_root,
                context=MassFilterL1Tests._context(artifact_root),
            )

    @staticmethod
    @contextmanager
    def _workspace():
        """Retain unexpected failures and actual owner holds at original paths."""
        root = Path(tempfile.mkdtemp(prefix='rf-managed-l1-'))
        retain = False
        primary = None
        audit_error = None
        results = []
        active = []
        try:
            yield str(root)
        except BaseException as error:
            primary = error
            retain = True
            raise
        finally:
            try:
                for path in root.rglob('result.json'):
                    if path.parent.parent.name != 'workflow_results':
                        continue
                    value = load_json(path)
                    if value.get('role') == 'run_artifact_workflow_result':
                        results.append(str(path))
                        if value.get('resume_action') is not None or value.get('writers_confirmed') is not True:
                            retain = True
                for path in root.rglob('capacity_session.json'):
                    if (path.parent.name == 'logs' and path.parent.parent.parent.name == 'runs'
                            and load_json(path).get('status') == 'active'):
                        active.append(str(path))
                        retain = True
            except Exception as error:
                retain = True
                if primary is not None:
                    primary.add_note(f'Workspace hold audit failed: {error!r}')
                else:
                    audit_error = error
            finally:
                if retain:
                    print('RF_L1_RETAINED_WORKSPACE=' + json.dumps(dict(path=str(root), results=results, active_capacity_sessions=active)))
                else:
                    if root.resolve().parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith('rf-managed-l1-'):
                        raise AssertionError('Test cleanup target escaped its owned temporary root')
                    shutil.rmtree(root)
            if audit_error is not None:
                raise audit_error

    @staticmethod
    def _context(artifact_root: Path):
        from msplatform.execution.context import ExecutionContext
        workspace = artifact_root.parents[2]
        stage = workspace / 'test-owned-stage-policy.json'
        stage.write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy', stages={
            'rf_mass_filter_l1': dict(limits=dict(wall_clock_seconds=120,
                transient_run_directory_bytes=268435456, process_tree_working_set_bytes=2147483648,
                minimum_system_available_memory_bytes=1073741824, compact_final_retained_bytes=67108864,
                automatic_retry_count=0), artifact_retention=dict(policy_version=1, **{'class': 'compact'}, reason=None))
        })), encoding='utf-8')
        host = json.loads(os.environ['MASS_SPECTROMETRY_HOST_CONTEXT_JSON'])
        return ExecutionContext(workspace=workspace, python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')), tools={},
            host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
            policy_path=Path(host['policy_path']), stage_policy_path=stage)

    @staticmethod
    def _controlled_provider(artifact_root: Path, *, passed: bool = True) -> Path:
        """Freeze a real, explicit test-owned kernel before package preparation."""
        provider = artifact_root.parents[2] / 'controlled_provider/msplatform'
        shutil.copytree(MODULE._source_package_root(), provider, ignore=shutil.ignore_patterns('__pycache__'))
        kernel = provider / 'components/rf_multipole/finite_length_transport.py'
        kernel.write_text(
            '"""TEST-OWNED synthetic response; not a scientific kernel qualification."""\n'
            'def simulate_mass(mass, particles, resolved, steps):\n'
            '    count = len(particles["x_m"])\n'
            f'    transmitted = count if {passed!r} and 99.5 <= mass <= 103.5 else 0\n'
            '    return {"mass_Th": mass, "particles": count, "transmitted": transmitted,\n'
            '            "transmission_fraction": transmitted / count}\n', encoding='utf-8')
        return provider

    @staticmethod
    def _synthetic_response(mass: float, particles: dict, resolved: dict, steps: int) -> dict:
        count = len(particles["x_m"])
        transmitted = count if 99.5 <= mass <= 103.5 else 0
        return {"mass_Th": mass, "particles": count, "transmitted": transmitted,
                "transmission_fraction": transmitted / count}

    def test_run_failures_publish_triplet_and_preserve_original_error(self) -> None:
        for index, stage in enumerate(("input_freezing", "analysis_preparation", "simulation", "analysis_execution")):
            with self.subTest(stage=stage), self._workspace() as temporary:
                capacity_root = Path(temporary) / "artifacts"
                capacity_root.mkdir()
                initialize_capacity_ledger(capacity_root, objects=[])
                artifact_root = capacity_root / "projects/rf_multipole_ion_optics"
                run_id = f"20261028_12000{index}__test__python__l1-failure"
                destination = artifact_root / "runs" / run_id
                error = OSError(f"injected {stage} failure")
                invoke = MODULE._invoke_frozen_stage
                provider = self._controlled_provider(artifact_root)

                def freeze(source: Path, target: Path, **options) -> dict:
                    if target.name == "baseline.json":
                        initial = MODULE.load_json(destination / "run_manifest.json")
                        self.assertEqual(initial["status"], "checkpoint")
                    if stage == "input_freezing" and target.name == "resolved_design_mass_filter.json":
                        raise error
                    return freeze_file(source, target, **options)

                def analysis(session, request, action, guards, limits) -> dict:
                    phase = {'prepare': 'analysis_preparation', 'simulation': 'simulation',
                             'analysis': 'analysis_execution'}[action]
                    if stage == phase:
                        raise error
                    return invoke(session, request, action, guards, limits)

                with patch("msplatform.execution.inputs.freeze_file", side_effect=freeze), \
                     patch.object(MODULE, "_invoke_frozen_stage", side_effect=analysis), \
                     patch.object(MODULE, "_source_package_root", return_value=provider):
                    with self.assertRaises(OSError) as caught:
                        self._run(artifact_root, run_id)
                self.assertIs(caught.exception, error)
                config = MODULE.load_json(destination / "run_config.json")
                summary = MODULE.load_json(destination / "results/failure_context.json")
                manifest = MODULE.load_json(destination / "run_manifest.json")
                self.assertEqual(config["parameters"]["lifecycle_stage"], stage)
                self.assertEqual(config["parameters"]["requested_input_paths"]["baseline"],
                                 str(RUNNER.DEFAULT_BASELINE.resolve()))
                self.assertEqual((summary["status"], summary["failure_stage"], summary["reason"]),
                                 ("failed", stage, f"OSError: {error}"))
                self.assertFalse(summary["threshold_result_eligible"])
                self.assertEqual(summary["model_level"], "L1")
                self.assertEqual(manifest["status"], "failed")
                self.assertEqual(MODULE.load_json(destination / 'summary.json')['status'], 'failed')
                result_path = artifact_root / 'scratch/workflow_results' / run_id / 'result.json'
                self.assertTrue(MODULE.load_json(result_path)['writers_confirmed'])
                self.assertEqual(MODULE.load_json(result_path)['exception']['message'], str(error))
                self.assertIn(destination / 'results/failure_context.json',
                              {Path(row['path']) for row in manifest['outputs']})
                for document in (config, manifest):
                    self.assertEqual(document["run_id"], run_id)
                    self.assertEqual(document["project"], "rf_multipole_ion_optics")
                    self.assertEqual(document["mode"], "mass_filter_reference")
                frozen_paths = {Path(item["path"]) for item in manifest["inputs"].values()}
                self.assertIn(destination / "inputs/baseline.json", frozen_paths)
                if stage != "input_freezing":
                    self.assertIn(destination / "inputs/analysis_request.json", frozen_paths)
                if stage == "analysis_execution":
                    self.assertIn(destination / "inputs/mass_response_for_analysis.csv", frozen_paths)
                if stage in ("simulation", "analysis_execution"):
                    self.assertIn(destination / "inputs/analysis_package.json", frozen_paths)
                if stage == "simulation":
                    self.assertFalse((destination / "inputs/mass_response_for_analysis.csv").exists())
                    self.assertFalse((destination / "results/mass-response__finite-length.csv").exists())
                    self.assertFalse((destination / "results/mass-filter__functional-metrics.json").exists())
                original = {name: (destination / name).read_bytes() for name in
                            ("run_config.json", "summary.json", "run_manifest.json")}
                with self.assertRaises(FileExistsError):
                    self._run(artifact_root, run_id)
                self.assertEqual(original, {name: (destination / name).read_bytes() for name in original})

    def test_run_success_and_physical_failure_keep_published_terminal(self) -> None:
        for passed in (True, False):
            with self.subTest(passed=passed), self._workspace() as temporary:
                capacity_root = Path(temporary) / "artifacts"
                capacity_root.mkdir()
                initialize_capacity_ledger(capacity_root, objects=[])
                artifact_root = capacity_root / "projects/rf_multipole_ion_optics"
                run_id = "20261028_120005__test__python__l1-terminal"
                destination = artifact_root / "runs" / run_id

                provider = self._controlled_provider(artifact_root, passed=passed)
                with patch.object(MODULE, "_source_package_root", return_value=provider):
                    if passed:
                        self.assertEqual(self._run(artifact_root, run_id), destination)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "functional gate failed"):
                            self._run(artifact_root, run_id)
                config = MODULE.load_json(destination / "run_config.json")
                summary = MODULE.load_json(destination / "summary.json")
                manifest = MODULE.load_json(destination / "run_manifest.json")
                metrics = MODULE.load_json(destination / "results/mass-filter__functional-metrics.json")
                self.assertEqual(summary["functional_gate"], "PASS" if passed else "FAIL")
                self.assertNotIn("failure_class", summary)
                self.assertEqual(manifest["status"], "success" if passed else "failed")
                self.assertEqual(config["parameters"]["lifecycle_stage"], "complete")
                self.assertEqual(metrics["particle_count_per_mass"], self.mode["functional_screen"]["particle_count"])
                self.assertTrue(config["frozen_python_analysis"]["environment"]["module_invoked"])
                self.assertTrue((destination / "results/mass-response__passband.png").is_file())
                self.assertFalse(manifest["formal_eligible"])
                if passed:
                    self.assertEqual(metrics["sampled_response_analysis"]["interpolated_main_peak_fwhm_Th"], 4.5)

    def test_run_cleanup_preserves_original_error_and_existing_terminal(self) -> None:
        from msplatform.execution import owner as OWNER
        for published in (False, True):
            with self.subTest(published=published), self._workspace() as temporary:
                capacity_root = Path(temporary) / "artifacts"
                capacity_root.mkdir()
                initialize_capacity_ledger(capacity_root, objects=[])
                artifact_root = capacity_root / "projects/rf_multipole_ion_optics"
                run_id = "20261028_120006__test__python__l1-cleanup"
                destination = artifact_root / "runs" / run_id
                error = OSError("original workflow failure")
                actual_run = RUNNER.run
                prepare = MODULE._prepare_frozen_request
                terminal = {}
                provider = self._controlled_provider(artifact_root)

                def finalization(*args, **kwargs):
                    raise RuntimeError("injected cleanup failure")

                def published_response(*args, **kwargs):
                    actual_run(*args, **kwargs)
                    terminal.update({name: (destination / name).read_bytes() for name in
                                     ("run_config.json", "summary.json", "run_manifest.json")})
                    raise error

                def prepare_analysis(*args, **kwargs) -> tuple:
                    if not published:
                        raise error
                    return prepare(*args, **kwargs)

                from contextlib import ExitStack
                with ExitStack() as patches:
                    patches.enter_context(patch.object(MODULE, '_source_package_root', return_value=provider))
                    patches.enter_context(patch.object(MODULE, '_prepare_frozen_request', side_effect=prepare_analysis))
                    if published:
                        patches.enter_context(patch.object(RUNNER, 'run', side_effect=published_response))
                    else:
                        patches.enter_context(patch.object(OWNER, '_finalize', side_effect=finalization))
                    with self.assertRaises(OSError) as caught:
                        self._run(artifact_root, run_id)
                self.assertIs(caught.exception, error)
                if published:
                    self.assertEqual(terminal, {name: (destination / name).read_bytes() for name in terminal})
                    self.assertEqual(MODULE.load_json(destination / "run_manifest.json")["status"], "success")
                else:
                    self.assertIn("injected cleanup failure", str(error.__notes__))
                    self.assertEqual(MODULE.load_json(destination / "run_manifest.json")["status"], "checkpoint")
                    result = artifact_root / 'scratch/workflow_results' / run_id / 'result.json'
                    self.assertTrue(MODULE.load_json(result)['writers_confirmed'])
                    from msplatform.execution.completion import no_particle_batch_completion_api
                    resumed = OWNER.resume_finalization(self._context(artifact_root), result,
                                                        completion_api=no_particle_batch_completion_api)
                    self.assertEqual(resumed['status'], 'failed')
                    self.assertEqual(MODULE.load_json(destination / 'run_manifest.json')['status'], 'failed')


    def test_actual_frozen_kernel_os_failure_keeps_original_observed_facts(self) -> None:
        from msplatform.execution.processes import ProcessExecutionError
        with self._workspace() as temporary:
            artifact_root = Path(temporary) / 'artifacts/projects/rf_multipole_ion_optics'
            provider = self._controlled_provider(artifact_root)
            (provider / 'components/rf_multipole/finite_length_transport.py').write_text(
                'def simulate_mass(*args):\n'
                '    print("FROZEN_OS_FAILURE_STDOUT", flush=True)\n'
                '    raise OSError("FROZEN_KERNEL_OS_FAILURE")\n', encoding='utf-8')
            run_id = '20261110_120012__test__python__l1-os-failure'
            with patch.object(MODULE, '_source_package_root', return_value=provider):
                with self.assertRaises(ProcessExecutionError) as caught:
                    self._run(artifact_root, run_id)
            error = caught.exception
            destination = artifact_root / 'runs' / run_id
            self.assertTrue(error.observed_process_exit_confirmed)
            self.assertNotEqual(error.observed_process_returncode, 0)
            self.assertGreater(error.receipt['observation']['root_process_id'], 0)
            self.assertIsNotNone(error.receipt['host_release'])
            failure = load_json(destination / 'results/failure_context.json')
            self.assertEqual(failure['failure_stage'], 'simulation')
            self.assertFalse(failure['threshold_result_eligible'])
            self.assertTrue(failure['reason'].startswith('ProcessExecutionError:'))
            child = load_json(destination / 'results/simulation_execution.json')
            self.assertEqual(child['status'], 'failed')
            self.assertEqual(child['error']['module_exit_code'], 1)
            self.assertEqual((destination / 'logs/simulation_module.stdout.log').read_text(encoding='utf-8'),
                             'FROZEN_OS_FAILURE_STDOUT\n')
            self.assertIn('FROZEN_KERNEL_OS_FAILURE',
                          (destination / 'logs/operation_0002.stderr.log').read_text(encoding='utf-8'))
            result = load_json(artifact_root / 'scratch/workflow_results' / run_id / 'result.json')
            self.assertTrue(result['writers_confirmed'])
            self.assertEqual(result['exception']['type'], 'ProcessExecutionError')
            self.assertEqual(load_json(destination / 'run_manifest.json')['status'], 'failed')
            self.assertFalse((destination / 'results/analysis_execution.json').exists())
            print('RF_L1_OS_FAILURE_OBSERVATION=' + json.dumps(error.receipt['observation']))

    def test_actual_default_n100_numeric_csv_matches_same_frozen_science(self) -> None:
        with self._workspace() as temporary:
            root = Path(temporary)
            expected_rows = MODULE.scan_response(self.baseline, self.resolved, self.mode, self.source)
            expected = root / 'expected.csv'
            MODULE.write_response_csv(expected, expected_rows)
            artifact_root = root / 'artifacts/projects/rf_multipole_ion_optics'
            run_id = '20261110_120013__test__python__l1-numeric'
            captured = {}
            invoke = MODULE._invoke_frozen_stage
            def observe(session, request, stage, guards, limits):
                captured['session'] = session
                return invoke(session, request, stage, guards, limits)
            with patch.object(MODULE, '_invoke_frozen_stage', side_effect=observe), \
                 patch.object(KERNEL, 'simulate_mass', side_effect=RuntimeError('LIVE_PRODUCER_USED')):
                destination = self._run(artifact_root, run_id)
            self.assertEqual((destination / 'results/mass-response__finite-length.csv').read_bytes(), expected.read_bytes())
            self.assertEqual(len(expected_rows), 29)
            self.assertTrue(all(row['particles'] == 100 for row in expected_rows))
            self.assertEqual([row['operation_id'] for row in captured['session'].operations],
                             ['prepare', 'simulation', 'analysis'])
            observations = [row['observation'] for row in captured['session'].operations]
            self.assertTrue(all(row['exit_confirmed'] and row['returncode'] == 0 for row in observations))
            self.assertTrue(all(row['process_id'] > 0 and row['process_started_at_utc_ticks'] > 0 for row in observations))
            usage = [load_json(path) for path in sorted((destination / 'logs').glob('operation_*.usage.json'))]
            self.assertEqual(len(usage), 3)
            result = load_json(artifact_root / 'scratch/workflow_results' / run_id / 'result.json')
            retained = sum(path.stat().st_size for path in destination.rglob('*') if path.is_file())
            print('RF_L1_N100_PROCESS_EVIDENCE=' + json.dumps(dict(observations=observations, usage=usage,
                retained_logical_bytes=retained, capacity=result['capacity'])))

    def test_explicit_research_workspace_is_retained_and_conflicting_layout_refused(self) -> None:
        with self._workspace() as temporary:
            workspace = Path(temporary) / 'explicit-alternate-workspace'
            workspace.mkdir()
            artifact_root = workspace / 'artifacts/projects/rf_multipole_ion_optics'
            context = self._context(artifact_root)
            with self.assertRaisesRegex(ValueError, 'selected managed research workspace'):
                RUNNER.run(RUNNER.DEFAULT_BASELINE, RUNNER.DEFAULT_RESOLVED, RUNNER.DEFAULT_MODE,
                    RUNNER.DEFAULT_SOURCE, '20261110_120014__test__python__l1-layout',
                    workspace / 'unmanaged-output', context=context)
            self.assertFalse((workspace / 'artifacts').exists())
            provider = self._controlled_provider(artifact_root)
            with patch.object(MODULE, '_source_package_root', return_value=provider):
                destination = self._run(artifact_root, '20261110_120015__test__python__l1-workspace')
            self.assertTrue(destination.is_relative_to(artifact_root))
            self.assertEqual(load_json(destination / 'run_config.json')['project_root'], str(workspace))

    def test_contract_brackets_theory_passband(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        self.assertAlmostEqual(derived["theory_low_mass_Th"], 99.3275, delta=0.001)
        self.assertAlmostEqual(derived["theory_high_mass_Th"], 103.4120, delta=0.001)
        self.assertAlmostEqual(derived["calibration_mass_Th"], 101.3707, delta=0.001)

    def test_l1_charge_is_exactly_positive_one_without_integer_truncation(self) -> None:
        for charge in (True, 1.5, -1, 0, float("nan"), float("inf")):
            with self.subTest(charge=charge), self.assertRaisesRegex(ValueError, "singly charged"):
                MODULE.validate_l1_contract(self.baseline, self.mode, {**self.source, "charge_state": charge})

    def test_sample_envelope_and_existing_functional_values_are_preserved(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        rows = [{"mass_Th": mass, "transmission_fraction": float(99.5 <= mass <= 103.5)}
                for mass in derived["masses_Th"]]
        result = MODULE.evaluate_response(rows, derived, self.mode)
        self.assertEqual({key: value for key, value in result.items() if key != "sampled_response_analysis"}, {
            "status": "PASS", "checks": {name: True for name in (
                "peak_transmission", "inside_band_transmission", "outside_endpoint_rejection",
                "low_boundary_alignment", "high_boundary_alignment")},
            "peak_mass_Th": 99.5, "peak_transmission": 1.0,
            "minimum_inside_theory_band_transmission": 1.0, "maximum_scan_endpoint_transmission": 0.0,
            "theory_passband_Th": [derived["theory_low_mass_Th"], derived["theory_high_mass_Th"]],
            "observed_half_maximum_band_Th": [99.5, 103.5], "mass_step_Th": 0.5,
        })
        self.assertEqual(result["sampled_response_analysis"]["interpolated_main_peak_fwhm_Th"], 4.5)
        for row in rows:
            row["transmission_fraction"] = 0.0
        zero = MODULE.evaluate_response(rows, derived, self.mode)
        self.assertEqual(zero["status"], "FAIL")
        self.assertIsNone(zero["observed_half_maximum_band_Th"])
        self.assertFalse(zero["checks"]["low_boundary_alignment"])
        self.assertFalse(zero["checks"]["high_boundary_alignment"])

    def test_frozen_l1_analysis_runs_from_snapshot_and_rejects_changed_peak_source(self) -> None:
        with self._workspace() as temporary:
            root = Path(temporary)
            artifact_root = root / 'artifacts/projects/rf_multipole_ion_optics'
            provider = self._controlled_provider(artifact_root)
            run_id = '20261110_120010__test__python__l1-frozen'
            destination = artifact_root / 'runs' / run_id
            captured = {}
            invoke = MODULE._invoke_frozen_stage

            def observe(session, request, stage, guards, limits):
                package_path = session.input_dir / 'analysis_package.json'
                if not captured:
                    captured.update(request=request.read_bytes(), package=package_path.read_bytes(), session=session)
                process = session.run_process
                def competing_worker(*args, **kwargs):
                    kwargs['environment'] = {**kwargs.get('environment', {}), 'PYTHONPATH': str(competing.parent)}
                    arguments = list(kwargs['arguments'])
                    # An actual observed-worker startup marker; no host-broker
                    # environment change and no fabricated process receipt.
                    arguments[-1] = "[Console]::Out.WriteLine('RF_WORKER_PYTHONPATH=' + $env:PYTHONPATH)\n" + arguments[-1]
                    kwargs['arguments'] = arguments
                    return process(*args, **kwargs)
                with patch.object(session, 'run_process', side_effect=competing_worker):
                    result = invoke(session, request, stage, guards, limits)
                ordinal = session.expected_operation_ids.index(stage) + 1
                self.assertIn('RF_WORKER_PYTHONPATH=' + str(competing.parent),
                    (session.log_dir / f'operation_{ordinal:04d}.stdout.log').read_text(encoding='utf-8'))
                self.assertEqual(request.read_bytes(), captured['request'])
                self.assertEqual(package_path.read_bytes(), captured['package'])
                return result

            competing = root / 'competing/msplatform'
            competing.mkdir(parents=True)
            (competing / '__init__.py').write_text("raise RuntimeError('COMPETING_PACKAGE_USED')\n", encoding='utf-8')
            with patch.object(MODULE, '_source_package_root', return_value=provider), \
                 patch.object(MODULE, '_invoke_frozen_stage', side_effect=observe), \
                 patch.object(KERNEL, 'simulate_mass', side_effect=RuntimeError('LIVE_KERNEL_USED')):
                self._run(artifact_root, run_id)
            inputs, results = destination / 'inputs', destination / 'results'
            derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
            count = int(self.mode['functional_screen']['particle_count'])
            rows = [{'mass_Th': float(mass), 'particles': count,
                     'transmitted': count if 99.5 <= mass <= 103.5 else 0,
                     'transmission_fraction': float(99.5 <= mass <= 103.5)}
                    for mass in derived['masses_Th']]
            package = load_json(inputs / 'analysis_package.json')
            execution = load_json(results / 'analysis_execution.json')['environment']
            self.assertTrue(execution["module_invoked"])
            origins = {entry["name"]: Path(entry["origin"]) for entry in execution["frozen_modules"]}
            for name in ("msplatform.analysis.peak_metrics", "msplatform.analysis.mass_response"):
                self.assertTrue(origins[name].is_relative_to(inputs / "analysis_code"))
            actual = load_json(results / "mass-filter__functional-metrics.json")
            self.assertEqual(actual["status"], "PASS")
            self.assertEqual(actual["sampled_response_analysis"], MODULE.evaluate_response(rows, derived, self.mode)["sampled_response_analysis"])
            self.assertTrue((results / "mass-response__passband.png").is_file())
            files = package["package"]["files"]
            self.assertEqual(len({entry["relative_path"] for entry in files}), len(files))
            self.assertEqual(
                {entry["path"] for entry in files},
                {str(path.resolve()) for path in (inputs / "analysis_code").rglob("*") if path.is_file()},
            )
            self.assertEqual([row['operation_id'] for row in captured['session'].operations],
                             ['prepare', 'simulation', 'analysis'])
            self.assertTrue(all(row['observation']['process_id'] > 0 for row in captured['session'].operations))
            self.assertTrue(load_json(results / 'simulation_execution.json')['environment']['module_invoked'])
            expected_csv = root / 'expected.csv'
            MODULE.write_response_csv(expected_csv, rows)
            self.assertEqual((results / 'mass-response__finite-length.csv').read_bytes(), expected_csv.read_bytes())

            def rejected(case: str) -> None:
                case_root = root / case
                target_root = case_root / 'artifacts/projects/rf_multipole_ion_optics'
                target_provider = self._controlled_provider(target_root)
                seen = {}
                target_id = '20261110_120011__test__python__l1-frozen-identity'
                def corrupt_before_producer(session, request, stage, guards, limits):
                    if stage == 'simulation':
                        frozen_package = load_json(session.input_dir / 'analysis_package.json')['package']
                        peak = next(Path(row['path']) for row in frozen_package['files']
                                    if row['relative_path'].endswith('/analysis/peak_metrics.py'))
                        original = peak.read_bytes()
                        record = next(row for row in frozen_package['files'] if Path(row['path']) == peak)
                        self.assertEqual(hashlib.sha256(original).hexdigest().upper(), record['sha256'])
                        seen.update(session=session, request=request.read_bytes(), peak=peak,
                                    original=original, sha256=record['sha256'],
                                    package=(session.input_dir / 'analysis_package.json').read_bytes())
                        if case == 'changed':
                            peak.write_bytes(peak.read_bytes() + b'\n# changed frozen source\n')
                        else:
                            peak.unlink()
                    return invoke(session, request, stage, guards, limits)
                try:
                    with patch.object(MODULE, '_source_package_root', return_value=target_provider), \
                         patch.object(MODULE, '_invoke_frozen_stage', side_effect=corrupt_before_producer):
                        self._run(target_root, target_id)
                finally:
                    if seen:
                        self.assertEqual([row['operation_id'] for row in seen['session'].operations], ['prepare'])
                        self.assertTrue(seen['session'].writers_stopped)
                        self.assertEqual((seen['session'].input_dir / 'analysis_request.json').read_bytes(), seen['request'])
                        self.assertEqual((seen['session'].input_dir / 'analysis_package.json').read_bytes(), seen['package'])
                        from msplatform.execution.capacity_protection import load_capacity_protection_leases
                        from msplatform.execution.completion import no_particle_batch_completion_api
                        from msplatform.execution.owner import resume_finalization
                        result_path = target_root / 'scratch/workflow_results' / target_id / 'result.json'
                        result = load_json(result_path)
                        failure_path = target_root / 'runs' / target_id / 'results/failure_context.json'
                        failure_bytes = failure_path.read_bytes()
                        self.assertEqual(result['status'], 'failed')
                        self.assertTrue(result['writers_confirmed'])
                        if case == 'missing':
                            # Restore only this test-owned original, after the
                            # missing-input rejection. Never adopt new bytes or
                            # rerun the action to close a finalization hold.
                            self.assertEqual(result['resume_action'], 'resume_finalization')
                            self.assertFalse(seen['peak'].exists())
                            self.assertEqual(hashlib.sha256(seen['original']).hexdigest().upper(), seen['sha256'])
                            with seen['peak'].open('xb') as stream:
                                stream.write(seen['original'])
                            self.assertEqual(seen['peak'].stat().st_size, len(seen['original']))
                            self.assertEqual(hashlib.sha256(seen['peak'].read_bytes()).hexdigest().upper(), seen['sha256'])
                            result = resume_finalization(self._context(target_root), result_path,
                                completion_api=no_particle_batch_completion_api)
                        self.assertEqual(result['status'], 'failed')
                        self.assertIsNone(result['resume_action'])
                        self.assertEqual(result['capacity_session']['status'], 'released')
                        self.assertEqual(failure_path.read_bytes(), failure_bytes)
                        self.assertEqual(load_capacity_protection_leases(case_root / 'artifacts')['audit'], [])
                        self.assertEqual([row['operation_id'] for row in seen['session'].operations], ['prepare'])
                        self.assertFalse((target_root / 'runs' / target_id / 'results/simulation_execution.json').exists())
            with self.assertRaisesRegex(RuntimeError, "hash differs"):
                rejected('changed')
            with self.assertRaisesRegex(RuntimeError, "missing"):
                rejected('missing')



    def test_finite_length_screen_transmits_tuned_and_rejects_outer_masses(self) -> None:
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        transmissions = {}
        for mass in (96.0, 101.5, 106.0):
            result = KERNEL.simulate_mass(mass, particles, self.resolved, 80)
            transmissions[mass] = result["transmission_fraction"]
        self.assertGreaterEqual(transmissions[101.5], 0.9)
        self.assertLessEqual(transmissions[96.0], 0.1)
        self.assertLessEqual(transmissions[106.0], 0.1)

    def test_l1_projection_preserves_common_box_cone_release(self) -> None:
        release = sample_numpy_box_cone_phase_space(
            source=self.source, seed=20260722, particle_count=64,
        )
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        self.assertTrue(np.array_equal(particles["x_m"], release["transverse_1_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["y_m"], release["transverse_2_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["energy_j"], release["energy_eV"] * MODULE.electron_volt))
        self.assertTrue(np.array_equal(particles["direction_x"], release["direction_transverse_1"]))
        self.assertTrue(np.array_equal(particles["direction_y"], release["direction_transverse_2"]))
        self.assertTrue(np.array_equal(particles["direction_z"], release["direction_axial"]))
        self.assertTrue(np.array_equal(particles["rf_phase_rad"], release["phase_rad"]))


if __name__ == "__main__":
    unittest.main()
