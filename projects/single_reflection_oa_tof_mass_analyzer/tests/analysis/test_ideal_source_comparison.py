"""Small deterministic regressions for the ideal numerical-source comparison."""

from dataclasses import replace
from concurrent.futures import Future
from types import SimpleNamespace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack

import numpy as np

from common.analysis.peak_metrics import AnalysisSettings
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    AxialParticleSource,
    NumericalSourceSpec,
    build_numerical_source,
    build_working_point,
    propagate_ideal_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    exact_total_normalized_time,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison import slope_scan, acceptance_theory
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison import run_comparison
from common.contracts.file_identity import file_sha256


class IdealSourceComparisonTests(unittest.TestCase):
    """Cover pairing, fixed geometry, exact time parity, and complete loss accounting."""

    def setUp(self) -> None:
        self.spec = NumericalSourceSpec(100.0, 1.498375640839315, -2.9323518410018137, 228.80604377795845)
        self.outer = OuterGeometry(3.25, 17.0, 0.3, 250.0, 2000.0)
        self.reflectron = ReflectronGeometry(120.0, 96.1563, 600.0, 600.0)
        self.settings = AnalysisSettings(grid_points=201, standardized_grid_points=101)

    def point(self, slope: float | None = None, eta: float = -1.0391326394747527):
        return build_working_point(
            self.spec, self.outer, self.reflectron,
            design_velocity_slope_m_per_s_per_mm=self.spec.velocity_slope_m_per_s_per_mm if slope is None else slope,
            eta=eta, focus_drift_mm=42.742615461548496,
        )

    def sample(self, count: int = 31, width: float = 1.0, sigma: float = 3.0):
        return build_numerical_source(self.spec, particle_count=count, seed=73, full_width_mm=width, residual_sigma_m_per_s=sigma)

    def test_random_pairs_preserve_prefix_and_residual_scaling(self) -> None:
        small, large = self.sample(17), self.sample(31)
        np.testing.assert_array_equal(small.source_x_mm, large.source_x_mm[:17])
        np.testing.assert_array_equal(small.residual_m_per_s, large.residual_m_per_s[:17])
        wide = self.sample(width=2.0, sigma=6.0)
        np.testing.assert_allclose(wide.source_x_mm-self.spec.center_x_mm, 2*(large.source_x_mm-self.spec.center_x_mm), atol=1e-15)
        np.testing.assert_array_equal(wide.residual_m_per_s, 2*large.residual_m_per_s)

    def test_resume_retains_numeric_cases_after_plot_or_report_change_but_rejects_numeric_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root/(name+'.py') for name in
                     ('entrypoint','ideal_source_comparison_plot','numerical_case')}
            for name, path in paths.items():
                path.write_text(name+' initial\n', encoding='utf-8')
            config = root/'experiment.json'
            config.write_text(json.dumps(dict(scope='inert dependency fixture')), encoding='utf-8')
            inputs = dict(experiment=config, **paths)
            with patch.object(run_comparison, '_inputs', return_value=inputs), \
                    patch.object(run_comparison, '_command', return_value='fixture'):
                parent, identity = run_comparison._prepare_run(config, seed=7,
                    run_id='20261030_130100__analysis__python__numeric-context', resume_from=None, artifact_root=root)
                case = dict(case_id='fixture')
                particles = parent/'results/fixture.csv'
                particles.write_text('particle_id,tof_us\n1,2\n', encoding='utf-8')
                document = dict(identity=identity, case=case,
                    particles=dict(path=particles.name, bytes=particles.stat().st_size, sha256=file_sha256(particles)))
                document['record_sha256'] = run_comparison._digest(document)
                (parent/'results/fixture.json').write_text(json.dumps(document), encoding='utf-8')
                before = {p:p.read_bytes() for p in parent.rglob('*') if p.is_file()}
                paths['entrypoint'].write_text('changed reporting only\n', encoding='utf-8')
                paths['ideal_source_comparison_plot'].write_text('changed display only\n', encoding='utf-8')
                child, child_identity = run_comparison._prepare_run(config, seed=7,
                    run_id='20261030_130200__analysis__python__numeric-context', resume_from=parent, artifact_root=root)
                self.assertEqual(child_identity, identity)
                self.assertEqual(run_comparison._reuse_case(parent, case, child_identity, child/'results'), document)
                self.assertEqual((child/'results/fixture.csv').read_bytes(), particles.read_bytes())
                frozen = json.loads((child/'run_config.json').read_text(encoding='utf-8'))
                self.assertIn('entrypoint', frozen['input_sha256'])
                self.assertIn('ideal_source_comparison_plot', frozen['input_sha256'])
                self.assertNotIn('entrypoint', frozen['numerical_input_sha256'])
                self.assertNotIn('ideal_source_comparison_plot', frozen['numerical_input_sha256'])
                paths['numerical_case'].write_text('changed propagation formula\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'resume code/config/seed/environment differs'):
                    run_comparison._prepare_run(config, seed=7,
                        run_id='20261030_130300__analysis__python__numeric-context', resume_from=parent, artifact_root=root)
                self.assertEqual({p:p.read_bytes() for p in before}, before)

    def test_legacy_comparison_without_frozen_numerical_case_fails_before_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'experiment.json'
            config.write_text(json.dumps(dict(scope='inert legacy binding fixture')), encoding='utf-8')
            helper = root / 'numerical_case.py'
            helper.write_text('frozen numerical implementation\n', encoding='utf-8')
            legacy = root / 'legacy'
            legacy.mkdir()
            (legacy / 'run_config.json').write_text(json.dumps(dict(
                schema_version=2, input_sha256={}, inputs={}, numerical_identity='old-full-runner-identity')),
                encoding='utf-8')
            before = (legacy / 'run_config.json').read_bytes()
            run_id = '20261031_130100__analysis__python__legacy-evidence-gap'
            with patch.object(run_comparison, '_inputs', return_value=dict(experiment=config, numerical_case=helper)), \
                    patch.object(run_comparison, '_command', return_value='fixture'):
                with self.assertRaisesRegex(ValueError, 'lacks a frozen numerical_case implementation identity'):
                    run_comparison._prepare_run(config, seed=7, run_id=run_id,
                                                resume_from=legacy, artifact_root=root)
            self.assertFalse((root / 'runs' / run_id).exists())
            self.assertEqual((legacy / 'run_config.json').read_bytes(), before)

    def test_execute_uses_frozen_settings_after_active_drift_and_rejects_invalid_frozen_settings(self):
        for scenario in ('active_drift', 'invalid_frozen', 'frozen_tamper'):
            invalid_frozen = scenario == 'invalid_frozen'
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / 'experiment.json'
                config.write_text(json.dumps(dict(scope='inert frozen settings transport')), encoding='utf-8')
                active = root / 'active_analysis_contract.json'
                good = dict(kde=dict(grid_points=4001, bandwidth_multiplier=1.06,
                                     significant_mode_threshold_fraction=0.10))
                bad = dict(kde=dict(grid_points=1, bandwidth_multiplier=1.06,
                                    significant_mode_threshold_fraction=0.10))
                active.write_text(json.dumps(bad if invalid_frozen else good), encoding='utf-8')
                prepare = run_comparison._prepare_run

                def freeze_then_change_active(*args, **kwargs):
                    prepared = prepare(*args, **kwargs)
                    active.write_text(json.dumps(good if invalid_frozen else bad), encoding='utf-8')
                    if scenario == 'frozen_tamper':
                        frozen_config = json.loads((prepared[0] / 'run_config.json').read_text(encoding='utf-8'))
                        Path(frozen_config['inputs']['analysis_contract']).write_text(json.dumps(bad), encoding='utf-8')
                    return prepared

                with patch.object(run_comparison, '_inputs', return_value=dict(experiment=config, analysis_contract=active)), \
                     patch.object(run_comparison, '_command', return_value='fixture'), \
                     patch.object(run_comparison, '_prepare_run', side_effect=freeze_then_change_active), \
                     patch.object(run_comparison, 'build_case_plan', return_value=[]), \
                     patch.object(run_comparison, '_working_points', return_value={}), \
                     patch.object(run_comparison, '_settings', wraps=run_comparison._settings) as settings, \
                     patch.object(run_comparison, '_run_case', side_effect=AssertionError('propagation must not start')) as propagation, \
                     patch.object(run_comparison, 'summarize_stage', return_value=dict(scientific_status='NOT_EVALUATED', reason='fixture')), \
                     patch.object(run_comparison, 'export_comparison_figures'), \
                     patch.object(run_comparison, '_write_report'), \
                     patch.object(run_comparison, '_publish_manifest'):
                    run = run_comparison.execute(config, seed=7,
                        run_id='20261031_130200__analysis__python__frozen-settings', artifact_root=root)
                frozen = json.loads((run / 'run_config.json').read_text(encoding='utf-8'))
                summary = json.loads((run / 'summary.json').read_text(encoding='utf-8'))
                if scenario == 'frozen_tamper':
                    settings.assert_not_called()
                    self.assertIn('frozen analysis contract changed after freezing', summary['failure_reason'])
                else:
                    settings.assert_called_once_with(Path(frozen['inputs']['analysis_contract']))
                    self.assertNotEqual(settings.call_args.args[0], active)
                self.assertEqual(summary['status'], 'success' if scenario == 'active_drift' else 'failed')
                if invalid_frozen:
                    self.assertIn('grid_points must be an integer of at least three', summary['failure_reason'])
                    self.assertEqual(summary['failure_stage'], 'working_points')
                propagation.assert_not_called()

    def test_other_comparison_consumers_transport_the_same_explicit_settings(self):
        source = self.sample(count=7)
        point = self.point()
        result = SimpleNamespace(classification=np.array(['hit'] * 7), tof_us=np.arange(7) / 10 + 1,
            summary=dict(status='COMPUTED', peak_metrics=dict(mass_resolution=1000.0, direct_fwhm_tof_ns=1.0)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slope_config = dict(sampling=dict(particle_count=7), full_width_mm=1.0, residual_sigma_m_per_s=1.0)
            with patch.object(slope_scan, '_source', return_value=self.spec), \
                 patch.object(slope_scan, 'build_numerical_source', return_value=source), \
                 patch.object(slope_scan, '_arms', return_value=dict(zero_slope_design=point, matching_slope_design=point)), \
                 patch.object(slope_scan, 'propagate_ideal_source', return_value=result) as propagated:
                slope_scan._record_case(slope_config, 1.0, 73, root, settings=self.settings)
            self.assertEqual(propagated.call_count, 2)
            self.assertTrue(all(call.kwargs['settings'] is self.settings for call in propagated.call_args_list))
            launched = []

            class ImmediateExecutor:
                def __init__(self, max_workers):
                    launched.append(max_workers)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def submit(self, function, *args):
                    future = Future()
                    future.set_result(function(*args))
                    return future

            config = dict(full_widths_mm=[1.0], residual_sigma_m_per_s=1.0, minimum_resolution=1000.0,
                          sampling=dict(particle_count=7, replicate_count=1),
                          numerics=dict(population_orders=[], population_resolution_relative_tolerance=0.1),
                          design=dict(selected_per_width=1, selection='transport fixture'))
            with patch.object(acceptance_theory, 'ProcessPoolExecutor', ImmediateExecutor), \
                 patch.object(acceptance_theory, 'source_at_point', return_value=self.spec), \
                 patch.object(acceptance_theory, 'build_numerical_source', return_value=source), \
                 patch.object(acceptance_theory, 'accepted', return_value=False), \
                 patch.object(acceptance_theory, 'propagate_ideal_source', return_value=result) as propagated:
                reports, _ = acceptance_theory._confirm_widths_parallel(
                    config, self.spec, point, {1.0: []}, 73, root, 1, settings=self.settings)
            self.assertEqual(launched, [1])
            self.assertEqual(len(reports), 1)
            self.assertFalse(reports[0]['theoretical_population_pass'])
            propagated.assert_called_once()
            self.assertIs(propagated.call_args.kwargs['settings'], self.settings)

    def test_supported_role_entries_read_frozen_settings_once_before_cases_or_workers(self):
        for mode in ('slope', 'acceptance'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                run = root / 'run'
                for name in ('inputs', 'results', 'logs'):
                    (run / name).mkdir(parents=True)
                contract = run / 'inputs/analysis_contract.json'
                contract.write_text(json.dumps(dict(kde=dict(grid_points=self.settings.grid_points,
                    bandwidth_multiplier=self.settings.bandwidth_multiplier,
                    significant_mode_threshold_fraction=self.settings.mode_threshold_fraction))), encoding='utf-8')
                (run / 'run_config.json').write_text(json.dumps(dict(inputs=dict(analysis_contract=str(contract)),
                    input_sha256=dict(analysis_contract=file_sha256(contract)))), encoding='utf-8')
                config_path = root / 'experiment.json'
                module = slope_scan if mode == 'slope' else acceptance_theory
                stack.enter_context(patch.object(module, '_prepare_run', return_value=(run, 'fixture')))
                stack.enter_context(patch.object(module, '_publish_manifest'))
                settings = stack.enter_context(patch.object(module, '_frozen_settings', wraps=run_comparison._frozen_settings))
                if mode == 'slope':
                    config_path.write_text(json.dumps(dict(source_slopes_m_per_s_per_mm=[0.0],
                        sampling=dict(replicate_count=1), historical_slope_receipt='fixture')), encoding='utf-8')
                    stack.enter_context(patch.object(module, 'validate_slope_scan_config'))
                    stack.enter_context(patch.object(module, '_receipt_path', return_value=config_path))
                    consumer = stack.enter_context(patch.object(module, '_record_case', return_value=dict(
                        source_slope_m_per_s_per_mm=0.0, seed=73, resolution_gain_percent=0.0,
                        arms=dict(zero_slope_design=dict(resolution=1.0), matching_slope_design=dict(resolution=1.0)))))
                    module.execute_slope_scan(config_path, seed=73, run_id='fixture', resume_from=None, artifact_root=root)
                else:
                    baseline = root / 'reference.json'
                    baseline.write_text(json.dumps(dict(source=vars(self.spec))), encoding='utf-8')
                    config_path.write_text(json.dumps(dict(reference_config=str(baseline), numerics={},
                        full_widths_mm=[], scope='inert role settings transport')), encoding='utf-8')
                    stack.enter_context(patch.object(module, 'validate_theory_config'))
                    stack.enter_context(patch.object(module, '_working_points', return_value=dict(three_zone_matched=self.point())))
                    stack.enter_context(patch.object(module, '_select', return_value=({}, {})))
                    consumer = stack.enter_context(patch.object(module, '_confirm_widths_parallel', return_value=([], {})))
                    module.execute_theory(config_path, seed=73, run_id='fixture', resume_from=None, artifact_root=root, max_workers=1)
                settings.assert_called_once_with(run)
                consumer.assert_called_once()
                self.assertIsInstance(consumer.call_args.kwargs['settings'], AnalysisSettings)
                self.assertEqual(consumer.call_args.kwargs['settings'].grid_points, self.settings.grid_points)
                self.assertEqual(json.loads((run / 'summary.json').read_text(encoding='utf-8'))['status'], 'success')

    def test_quadratic_mean_and_no_detector_fit(self) -> None:
        spec = replace(self.spec, velocity_quadratic_m_per_s_per_mm2=17.0)
        source = build_numerical_source(spec, particle_count=17, seed=73, full_width_mm=1.0, residual_sigma_m_per_s=0.0)
        offset = source.source_x_mm-spec.center_x_mm
        np.testing.assert_allclose(source.velocity_z_m_per_s, spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*offset+17*offset**2)
        np.testing.assert_array_equal(source.residual_m_per_s, np.zeros(17))

    def test_reflectron_retuning_does_not_move_any_geometry_or_accelerator_voltage(self) -> None:
        before, after = self.point(0.0), self.point()
        self.assertEqual(before.reflectron, after.reflectron)
        self.assertEqual(before.focus_drift_mm, after.focus_drift_mm)
        for name in ("repeller_v", "grid1_v", "grid2_v", "field1_v_per_mm", "field2_v_per_mm", "field3_v_per_mm"):
            self.assertEqual(getattr(before.state, name), getattr(after.state, name))
        self.assertNotEqual(before.inner.stage1_voltage_drop_v, after.inner.stage1_voltage_drop_v)
        self.assertLess(abs(after.reflectron_solution.total_first_derivative_residual), 1e-12)
        self.assertLess(abs(after.reflectron_solution.total_second_derivative_residual), 1e-12)

    def test_zero_residual_matches_existing_affine_exact_total_time(self) -> None:
        source, point = self.sample(sigma=0.0), self.point()
        result = propagate_ideal_source(source, point, settings=self.settings)
        expected = exact_total_normalized_time(point.design_source, point.state, point.reflectron, point.inner, source.source_x_mm, point.focus_drift_mm)*point.design_source.time_scale_s_per_mm_sqrt_v*1e6
        np.testing.assert_allclose(result.tof_us, expected, atol=2e-14, rtol=1e-14)
        self.assertEqual(result.summary["detector_arrival_count"], 31)
        self.assertEqual(result.summary["status"], "SUCCESS")

    def test_fixed_reference_plane_closure_in_full_particle_times(self) -> None:
        point = self.point()
        offsets = np.linspace(-0.003, 0.003, 7)
        times = np.asarray(exact_total_normalized_time(
            point.design_source, point.state, point.reflectron, point.inner,
            self.spec.center_x_mm + offsets, point.focus_drift_mm,
        ))
        coefficients = np.polynomial.polynomial.polyfit(offsets, times-times[3], 4)
        # Finite-time differencing amplifies float64 roundoff by h^-order;
        # these bounds are tied to the evaluated time magnitude and stencil.
        roundoff = 64.0*np.spacing(float(np.max(times)))
        self.assertLess(abs(coefficients[1]), roundoff/0.001)
        self.assertLess(abs(coefficients[2]), roundoff/0.001**2)

    def test_two_zone_degeneration_independent_of_arbitrary_split(self) -> None:
        first = self.point(eta=0.0)
        second = build_working_point(self.spec, replace(self.outer, split_fraction=.7), self.reflectron, design_velocity_slope_m_per_s_per_mm=self.spec.velocity_slope_m_per_s_per_mm, eta=0.0, focus_drift_mm=first.focus_drift_mm)
        left = propagate_ideal_source(self.sample(), first, settings=self.settings)
        right = propagate_ideal_source(self.sample(), second, settings=self.settings)
        np.testing.assert_allclose(left.tof_us, right.tof_us, rtol=1e-14, atol=2e-14)

    def test_loss_labels_keep_full_mother_and_no_common_hit_filter(self) -> None:
        point = self.point()
        source = AxialParticleSource(np.arange(1, 5), np.array([-1., .01, 1.5, 1.5]), np.array([0., -2000., 0., 50000.]), np.zeros(4), 100.)
        result = propagate_ideal_source(source, point, settings=self.settings)
        self.assertEqual(result.classification.tolist(), ["source_outside_first_acceleration_zone", "repeller_collision", "detector_arrival", "reflectron_backplate_collision"])
        self.assertEqual(sum(result.summary["classification_counts"].values()), 4)
        self.assertFalse(result.summary["full_cohort_reachable"])
        self.assertTrue(np.isnan(result.tof_us[[0, 1, 3]]).all())

    def test_first_stage_mirror_turn_is_unsupported_not_fabricated_arrival(self) -> None:
        point = self.point()
        point = replace(point, inner=InnerSolution(2100.0, 10.0, point.inner.eta))
        result = propagate_ideal_source(self.sample(sigma=0.0), point, settings=self.settings)
        self.assertEqual(result.summary["classification_counts"], {"reflectron_stage1_turn_model_unsupported": 31})
        self.assertEqual(result.summary["status"], "NO_ARRIVALS")

    def test_identical_arrivals_have_no_infinite_or_fabricated_resolution(self) -> None:
        result = propagate_ideal_source(self.sample(width=0.0, sigma=0.0), self.point(), settings=self.settings)
        self.assertEqual(result.summary["status"], "SINGULAR_OR_NUMERICALLY_UNRESOLVED_PEAK")
        self.assertIsNone(result.summary["peak_metrics"])

    def test_invalid_source_and_mismatched_mass_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.sample(sigma=-1.0)
        with self.assertRaises(ValueError):
            AxialParticleSource(np.array([1, 1]), np.zeros(2), np.zeros(2), np.zeros(2), 100.)
        with self.assertRaises(ValueError):
            propagate_ideal_source(replace(self.sample(), mass_to_charge_th=300.), self.point(), settings=self.settings)

    def test_slope_scan_uses_theory_derived_matching_and_zero_slope_arms(self) -> None:
        config = slope_scan.load_json(Path(__file__).parents[2] / "config" / "experiments" / "ideal_source_affine_slope_scan.json")
        slope_scan.validate_slope_scan_config(config)
        zero = slope_scan._arms(config, 0.0)
        self.assertEqual(zero["zero_slope_design"], zero["matching_slope_design"])
        historical = slope_scan._arms(config, 37.79182865654923)
        self.assertNotEqual(historical["matching_slope_design"].design_source.chi_slope_sqrt_v_per_mm, 0.0)
        self.assertEqual(historical["zero_slope_design"].design_source.chi_slope_sqrt_v_per_mm, 0.0)
        self.assertNotEqual(historical["matching_slope_design"].inner, historical["zero_slope_design"].inner)
        self.assertNotEqual(
            historical["matching_slope_design"].state.field3_v_per_mm,
            historical["zero_slope_design"].state.field3_v_per_mm,
        )


if __name__ == "__main__":
    unittest.main()
