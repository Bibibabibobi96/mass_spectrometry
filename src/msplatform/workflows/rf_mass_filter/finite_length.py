"""Explicit finite-length ideal quadrupole scan and recorded response analysis."""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, TYPE_CHECKING
import numpy as np
from scipy.constants import electron_volt
from msplatform.analysis.mass_response import (export_response_figure as export_sampled_response_figure, prepare_response_analysis)
from msplatform.components.rf_multipole import finite_length_transport as _transport
from msplatform.components.rf_multipole import mass_filter_theory as _mathieu
from . import reference as _reference

if TYPE_CHECKING:
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.run_session import RunSession


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))

def validate_l1_contract(
    baseline: dict[str, Any], mode: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Validate the L1 inputs and return derived scan and passband values."""
    l0_result = _reference.validate_mass_filter_reference(baseline, mode)
    screen = mode.get("functional_screen", {})
    if screen.get("model_level") != "L1":
        raise ValueError("functional_screen.model_level must be L1")
    if screen.get("source_contract") != "../../variants/quadrupole/config/official_particle_source.json":
        raise ValueError("functional_screen.source_contract must reference the official source")
    if int(screen.get("particle_count", 0)) < 64:
        raise ValueError("functional_screen.particle_count must be at least 64")
    if int(screen.get("steps_per_rf_period", 0)) < 40:
        raise ValueError("functional_screen.steps_per_rf_period must be at least 40")
    charge = source.get("charge_state")
    if isinstance(charge, bool) or not isinstance(charge, (int, float)) or charge != 1:
        raise ValueError("L1 reference currently requires singly charged positive ions")

    scan = screen.get("mass_scan_Th", {})
    start = float(scan.get("min", math.nan))
    stop = float(scan.get("max", math.nan))
    step = float(scan.get("step", math.nan))
    if not all(math.isfinite(value) for value in (start, stop, step)) or not start < stop or step <= 0:
        raise ValueError("functional_screen.mass_scan_Th must define finite min < max and step > 0")
    masses = np.arange(start, stop + 0.5 * step, step, dtype=float)

    rf = mode["rf"]
    q_at_tune = float(l0_result["q_at_tune_mass"])
    passband = l0_result["ideal_scanline"]
    tune_mass = float(rf["tune_mass_Th"])
    theory_low = tune_mass * q_at_tune / float(passband["q_out"])
    theory_high = tune_mass * q_at_tune / float(passband["q_in"])
    if not start < theory_low < theory_high < stop:
        raise ValueError("L1 mass scan must bracket both ideal passband boundaries")
    return {
        "masses_Th": masses,
        "theory_low_mass_Th": theory_low,
        "theory_high_mass_Th": theory_high,
        "calibration_mass_Th": _mathieu.mass_to_charge_th(
            float(passband["q_cal"]),
            float(rf["amplitude_V_zero_to_peak_per_group"]),
            float(rf["effective_radius_mm"]),
            float(rf["frequency_Hz"]),
        ),
    }


def _l1_particles_from_release(
    source: dict[str, Any], particle_count: int, random_seed: int
) -> dict[str, np.ndarray]:
    """Project the common source release to the L1 integrator's SI state."""
    from msplatform.ion_release.numpy_box_cone import sample_numpy_box_cone_phase_space

    release = sample_numpy_box_cone_phase_space(
        source=source,
        seed=random_seed,
        particle_count=particle_count,
    )
    return {
        "x_m": release["transverse_1_mm"] * 1e-3,
        "y_m": release["transverse_2_mm"] * 1e-3,
        "energy_j": release["energy_eV"] * electron_volt,
        "direction_x": release["direction_transverse_1"],
        "direction_y": release["direction_transverse_2"],
        "direction_z": release["direction_axial"],
        "rf_phase_rad": release["phase_rad"],
    }


def evaluate_response(
    rows: list[dict[str, float | int]], derived: dict[str, Any], mode: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate the frozen functional acceptance rules against a mass response."""
    analysis = prepare_response_analysis(rows)
    masses = np.asarray(analysis["mass_samples_Th"], dtype=float)
    transmission = np.asarray(analysis["transmission_fraction_samples"], dtype=float)
    low = float(derived["theory_low_mass_Th"])
    high = float(derived["theory_high_mass_Th"])
    acceptance = mode["functional_screen"]["acceptance"]
    inside = (masses >= low) & (masses <= high)
    if not np.any(inside):
        raise ValueError("mass response has no samples inside the theory passband")
    observed_band = analysis["observed_half_maximum_band_Th"]
    step = float(mode["functional_screen"]["mass_scan_Th"]["step"])
    checks = {
        "peak_transmission": float(np.max(transmission)) >= float(acceptance["minimum_peak_transmission"]),
        "inside_band_transmission": float(np.min(transmission[inside])) >= float(acceptance["minimum_inside_band_transmission"]),
        "outside_endpoint_rejection": max(float(transmission[0]), float(transmission[-1])) <= float(acceptance["maximum_endpoint_transmission"]),
        "low_boundary_alignment": observed_band is not None and abs(observed_band[0] - low) <= step,
        "high_boundary_alignment": observed_band is not None and abs(observed_band[1] - high) <= step,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "peak_mass_Th": analysis["peak_mass_Th"],
        "peak_transmission": analysis["peak_transmission"],
        "minimum_inside_theory_band_transmission": float(np.min(transmission[inside])),
        "maximum_scan_endpoint_transmission": max(float(transmission[0]), float(transmission[-1])),
        "theory_passband_Th": [low, high],
        "observed_half_maximum_band_Th": observed_band,
        "mass_step_Th": step,
        "sampled_response_analysis": analysis,
    }


def write_response_csv(path: Path, rows: list[dict[str, float | int]]) -> None:
    """Write the complete sampled mass response."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_response_figure(
    path: Path, rows: list[dict[str, float | int]], metrics: dict[str, Any]
) -> None:
    """Export the L1 response as an accessible report-profile PNG."""
    low, high = metrics["theory_passband_Th"]
    export_sampled_response_figure(
        path, rows, (low, high), "Finite-length L1", metrics["sampled_response_analysis"],
    )


def analyze_response_file(
    response_path: Path, baseline_path: Path, mode_path: Path, source_path: Path,
    metrics_path: Path, figure_path: Path,
) -> dict[str, Any]:
    """Analyze the frozen L1 CSV once; the JSON and figure share that result."""
    baseline, mode, source = (load_json(path) for path in (baseline_path, mode_path, source_path))
    derived = validate_l1_contract(baseline, mode, source)
    with response_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    screen = mode["functional_screen"]
    if [float(row["mass_Th"]) for row in rows] != derived["masses_Th"].tolist():
        raise ValueError("L1 response mass grid differs from its frozen mode")
    expected_count = int(screen["particle_count"])
    if any(int(row["particles"]) != expected_count for row in rows):
        raise ValueError("L1 response particle count differs from its frozen mode")
    if any(float(row["transmission_fraction"]) != int(row["transmitted"]) / expected_count for row in rows):
        raise ValueError("L1 response fraction differs from transmitted/particles")
    metrics = evaluate_response(rows, derived, mode)
    metrics.update({
        "schema_version": 1, "role": "quadrupole_mass_filter_l1_metrics", "model_level": "L1",
        "particle_count_per_mass": int(screen["particle_count"]),
        "random_seed": int(screen["random_seed"]),
        "calibration_mass_Th": float(derived["calibration_mass_Th"]),
        "claim_limit": "Finite-length ideal-field functional screen only; no fringe field or solver qualification.",
    })
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    export_response_figure(figure_path, rows, metrics)
    return metrics


def scan_response(baseline: dict[str, Any], resolved: dict[str, Any], mode: dict[str, Any], source: dict[str, Any]) -> list[dict[str, float | int]]:
    """Use one unchanged sampled source for every explicit mass in this L1 scan."""
    derived = validate_l1_contract(baseline, mode, source)
    screen = mode["functional_screen"]
    particles = _l1_particles_from_release(source, int(screen["particle_count"]), int(screen["random_seed"]))
    return [_transport.simulate_mass(float(mass), particles, resolved, int(screen["steps_per_rf_period"]))
            for mass in derived["masses_Th"]]


def _source_package_root() -> Path:
    """Return this selected canonical provider, without searching a checkout."""
    from importlib.resources import files
    return Path(str(files('msplatform'))).resolve()


def _checkpoint(session: RunSession, stage: str) -> None:
    from msplatform.execution.recorded_file_removal import write_json_atomic
    config = load_json(session.run_config)
    config['parameters']['lifecycle_stage'] = stage
    write_json_atomic(session.run_config, config)


def _prepare_frozen_request(session: RunSession, scientific_records: dict) -> tuple[Path, list[dict]]:
    """Freeze one provider and bind both worker actions before starting either."""
    from msplatform.execution.inputs import enumerate_python_sources, freeze_python_package
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.io.manifest_records import file_record
    provider = _source_package_root()
    source_root = provider.parent
    selected = enumerate_python_sources(source_root, package_roots=[provider.name],
        provider_root=provider.name, resource_suffixes=('.json', '.ps1', '.lua', '.m', '.gem', '.iob'))
    code_root = session.input_dir / 'analysis_code'
    package = freeze_python_package(source_root, code_root, relative_paths=selected)
    code_records = []
    def package_inputs():
        for index, entry in enumerate(package['files']):
            path = session.declare_file(Path(entry['path']), 'required_evidence')
            record = dict(path=str(path), exists=True, bytes=path.stat().st_size,
                          sha256=entry['sha256'], retention_role='required_evidence')
            yield f'analysis_code_{index:04d}', record
            code_records.append(record)
    session.add_inputs(package_inputs())
    package_path = session.declare_file(session.input_dir / 'analysis_package.json', 'required_evidence')
    write_json_atomic(package_path, dict(schema_version=2, role='rf_mass_filter_l1_frozen_package',
        package=package, provider=str(provider)))
    package_record = file_record(package_path, 'required_evidence')
    session.add_input('analysis_package', package_record)
    executor = code_root / provider.name / 'execution/resources/frozen_python_package.ps1'
    executor_record = next(row for row in code_records if Path(row['path']) == executor.resolve())
    frozen = {name: record['path'] for name, record in scientific_records.items()}
    response = session.result_dir / 'mass-response__finite-length.csv'
    response_input = session.input_dir / 'mass_response_for_analysis.csv'
    metrics = session.result_dir / 'mass-filter__functional-metrics.json'
    figure = session.result_dir / 'mass-response__passband.png'
    shared = ['--baseline', frozen['baseline'], '--mode', frozen['mode'], '--source', frozen['source']]
    stages = {
        'prepare': dict(arguments=['--help'], probe_only=True),
        'simulation': dict(arguments=[*shared, '--resolved-design', frozen['resolved_design'],
                                      '--simulate-response', str(response)], probe_only=False),
        'analysis': dict(arguments=[*shared, '--analyze-response', str(response_input),
                                   '--analysis-metrics', str(metrics), '--analysis-figure', str(figure)], probe_only=False),
    }
    for name, stage in stages.items():
        stage['execution_receipt'] = str(session.result_dir / f'{name}_execution.json')
        stage['module_stdout'] = str(session.log_dir / f'{name}_module.stdout.log')
        session.declare_file(stage['module_stdout'], 'required_evidence')
        session.declare_file(stage['execution_receipt'], 'required_evidence')
    request_path = session.declare_file(session.input_dir / 'analysis_request.json', 'required_evidence')
    write_json_atomic(request_path, dict(schema_version=2, role='rf_mass_filter_l1_frozen_request',
        python=str(session.context.python_executable), package_receipt=package_record, executor=executor_record,
        scientific_inputs=scientific_records, module='msplatform.workflows.rf_mass_filter.finite_length',
        required_modules=['msplatform.workflows.rf_mass_filter.finite_length',
                          'msplatform.components.rf_multipole.finite_length_transport',
                          'msplatform.components.rf_multipole.mass_filter_theory',
                          'msplatform.analysis.mass_response', 'msplatform.analysis.peak_metrics'],
        distribution_names=['numpy', 'scipy', 'matplotlib'], forbidden_roots=[str(provider)], stages=stages))
    request_record = file_record(request_path, 'required_evidence')
    session.add_input('analysis_request', request_record)
    for path in (response, metrics, figure):
        session.declare_file(path, 'required_evidence')
    config = load_json(session.run_config)
    config['frozen_python_analysis'] = dict(package=package, request_schema_version=2)
    write_json_atomic(session.run_config, config)
    return request_path, [*code_records, package_record, request_record, *scientific_records.values()]


_FROZEN_STAGE_COMMAND = r'''
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=Get-Content -LiteralPath $env:RF_MASS_RESPONSE_REQUEST -Raw -Encoding UTF8|ConvertFrom-Json
if($request.schema_version-ne2-or$request.role-cne'rf_mass_filter_l1_frozen_request'){throw 'Unsupported frozen L1 request'}
$stage=$request.stages.($env:RF_MASS_RESPONSE_STAGE)
$packageDocument=Get-Content -LiteralPath $request.package_receipt.path -Raw -Encoding UTF8|ConvertFrom-Json
if($packageDocument.schema_version-ne2-or$packageDocument.role-cne'rf_mass_filter_l1_frozen_package'){throw 'Unsupported frozen L1 package'}
. $request.executor.path
try {
    $execution=Invoke-IsolatedFrozenPythonModule -Python $request.python -Package $packageDocument.package `
        -Module $request.module -Arguments @($stage.arguments) -DistributionNames @($request.distribution_names) `
        -RequiredModuleNames @($request.required_modules) -ForbiddenRoots @($request.forbidden_roots) `
        -StdoutPath $stage.module_stdout -ProbeOnly:([bool]$stage.probe_only)
    @{schema_version=2;role='rf_mass_filter_l1_execution_receipt';stage=$env:RF_MASS_RESPONSE_STAGE;
      status='success';request_sha256=(Get-FileHash -LiteralPath $env:RF_MASS_RESPONSE_REQUEST -Algorithm SHA256).Hash;
      package_sha256=(Get-FileHash -LiteralPath $request.package_receipt.path -Algorithm SHA256).Hash;
      environment=$execution}|ConvertTo-Json -Depth 32|Set-Content -LiteralPath $stage.execution_receipt -Encoding utf8NoBOM
} catch {
    $primary=$_
    try {
        @{schema_version=2;role='rf_mass_filter_l1_execution_receipt';stage=$env:RF_MASS_RESPONSE_STAGE;
          status='failed';error=@{type=$primary.Exception.GetType().FullName;message=$primary.Exception.Message;
            module_exit_code=$primary.Exception.Data['exit_code']}}|ConvertTo-Json -Depth 12|
              Set-Content -LiteralPath $stage.execution_receipt -Encoding utf8NoBOM
    } catch {$primary.Exception.Data['receipt_write_error']=$_.Exception.Message}
    throw $primary
}
'''


def _invoke_frozen_stage(session: RunSession, request_path: Path, stage: str, guards: list[dict], limits: dict) -> dict:
    """Use the existing managed process family and sole selected module executor."""
    from msplatform.io.manifest_records import verify_record
    for index, record in enumerate(guards):
        try:
            verify_record(f'L1 frozen input {index}', record)
        except AssertionError as error:
            # Preserve the existing workflow's runtime missing/hash diagnostic;
            # the neutral verifier remains the chained original identity fact.
            if not Path(record['path']).is_file():
                raise RuntimeError(f"Frozen Python dependency is missing: {record['path']}") from error
            raise RuntimeError(f"Frozen Python dependency hash differs: {record['path']}") from error
    session.run_process(stage, executable=session.context.powershell_executable,
        arguments=['-NoProfile', '-NonInteractive', '-Command', _FROZEN_STAGE_COMMAND],
        role='GATE', stage='rf_mass_filter_l1', limits=limits,
        environment=dict(RF_MASS_RESPONSE_REQUEST=str(request_path), RF_MASS_RESPONSE_STAGE=stage),
        immutable_input_records=guards)
    request = load_json(request_path)
    receipt = load_json(Path(request['stages'][stage]['execution_receipt']))
    from msplatform.io.manifest_records import file_record
    if (receipt.get('schema_version') != 2 or receipt.get('role') != 'rf_mass_filter_l1_execution_receipt'
            or receipt.get('status') != 'success' or receipt.get('stage') != stage
            or receipt.get('request_sha256', '').upper() != file_record(request_path)['sha256']
            or receipt.get('package_sha256', '').upper() != request['package_receipt']['sha256']):
        raise ValueError('Frozen L1 execution receipt differs from its immutable request/package')
    return receipt


def _run_action(session: RunSession, *, requested: dict, original_records: dict, stage: dict) -> dict:
    from msplatform.execution.inputs import freeze_file
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.io.manifest_records import file_record, verify_record
    stage_name = 'input_freezing'
    try:
        _checkpoint(session, stage_name)
        frozen = {}
        filenames = dict(baseline='baseline.json', resolved_design='resolved_design_mass_filter.json',
                         mode='mass_filter_reference.json', source='official_particle_source.json')
        for name, source in requested.items():
            verify_record(f'L1 requested {name}', original_records[name])
            target = session.declare_file(session.input_dir / filenames[name], 'required_evidence')
            record = freeze_file(source, target)
            if record['sha256'] != original_records[name]['sha256']:
                raise ValueError('Requested L1 scientific input changed before freezing: ' + name)
            frozen[name] = dict(record, retention_role='required_evidence')
            session.add_input(name, frozen[name])
        validate_l1_contract(*(load_json(Path(frozen[name]['path'])) for name in ('baseline', 'mode', 'source')))
        stage_name = 'analysis_preparation'
        _checkpoint(session, stage_name)
        request, guards = _prepare_frozen_request(session, frozen)
        prepared = _invoke_frozen_stage(session, request, 'prepare', guards, stage['limits'])
        config = load_json(session.run_config)
        config['frozen_python_analysis']['environment'] = prepared['environment']
        write_json_atomic(session.run_config, config)
        stage_name = 'simulation'
        _checkpoint(session, stage_name)
        simulation = _invoke_frozen_stage(session, request, 'simulation', guards, stage['limits'])
        stage_name = 'analysis_execution'
        _checkpoint(session, stage_name)
        response = session.result_dir / 'mass-response__finite-length.csv'
        original_response = file_record(response, 'required_evidence')
        target = session.declare_file(session.input_dir / 'mass_response_for_analysis.csv', 'required_evidence')
        copied = dict(freeze_file(response, target), retention_role='required_evidence')
        verify_record('L1 original response', original_response)
        session.add_input('response_for_analysis', copied)
        analysis = _invoke_frozen_stage(session, request, 'analysis', [*guards, copied, original_response], stage['limits'])
        metrics = load_json(session.result_dir / 'mass-filter__functional-metrics.json')
        config = load_json(session.run_config)
        config['frozen_python_analysis'].update(environment=analysis['environment'], producer_environment=simulation['environment'])
        write_json_atomic(session.run_config, config)
        stage_name = 'publication'
        _checkpoint(session, stage_name)
        _checkpoint(session, 'complete')
        outputs = [response, session.result_dir / 'mass-filter__functional-metrics.json',
                   session.result_dir / 'mass-response__passband.png',
                   *(session.result_dir / f'{name}_execution.json' for name in ('prepare', 'simulation', 'analysis')),
                   *(session.log_dir / f'{name}_module.stdout.log' for name in ('simulation', 'analysis'))]
        return dict(status='success' if metrics['status'] == 'PASS' else 'failed',
            summary=dict(schema_version=1, role='quadrupole_mass_filter_l1_run_summary',
                functional_gate=metrics['status'], model_level='L1', result='results/mass-filter__functional-metrics.json',
                figure='results/mass-response__passband.png'),
            output_paths=outputs, required_output_paths=outputs, retention_preserve_paths=[], manifest_extra_fields={})
    except Exception as primary:
        # The original owner still decides writer closure/publication. This is
        # diagnostic context, never a writer-completion or release assertion.
        failure_paths = []
        try:
            path = session.declare_file(session.result_dir / 'failure_context.json', 'required_evidence')
            write_json_atomic(path, dict(schema_version=2, role='rf_mass_filter_l1_failure_context',
                status='failed', failure_stage=stage_name, reason=f'{type(primary).__name__}: {primary}',
                threshold_result_eligible=False, model_level='L1'))
            failure_paths.append(path)
        except Exception as secondary:
            primary.add_note(f'L1 failure context preservation failed: {secondary!r}')
        try:
            candidates = [session.result_dir / name for name in (
                'mass-response__finite-length.csv', 'mass-filter__functional-metrics.json',
                'mass-response__passband.png', 'prepare_execution.json', 'simulation_execution.json', 'analysis_execution.json')]
            candidates += [session.log_dir / f'{name}_module.stdout.log' for name in ('prepare', 'simulation', 'analysis')]
            candidates += [session.log_dir / f'operation_{index:04d}.{suffix}'
                           for index in range(1, 4) for suffix in ('stdout.log', 'stderr.log', 'usage.json', 'process.json')]
            primary.failure_output_paths = [*failure_paths, *(path for path in candidates if path.is_file())]
        except Exception as secondary:
            primary.add_note(f'L1 failure evidence selection failed: {secondary!r}')
        raise


def run(context: ExecutionContext, *, baseline_path: Path, resolved_path: Path, mode_path: Path,
        source_path: Path, run_id: str, artifact_project_root: Path | None = None) -> dict:
    """Execute explicit L1 inputs with one managed owner and one frozen package.

    Engineering policy must be selected in context. Its wall-clock values are
    warnings with natural family drain, not hard process deadlines. This API
    does not supply a deployment profile or scientific defaults.
    """
    from functools import partial
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record, verify_record
    expected_root = context.workspace / 'artifacts/projects/rf_multipole_ion_optics'
    if artifact_project_root is not None and artifact_project_root.resolve() != expected_root.resolve():
        raise ValueError(f'Explicit artifact root must use the selected managed research workspace: {expected_root}')
    requested = dict(baseline=Path(baseline_path), resolved_design=Path(resolved_path),
                     mode=Path(mode_path), source=Path(source_path))
    original = {name: file_record(path.resolve(), 'required_evidence') for name, path in requested.items()}
    validate_l1_contract(*(load_json(requested[name]) for name in ('baseline', 'mode', 'source')))
    for name, record in original.items():
        verify_record(f'L1 scientific authority {name}', record)
    policy, policy_record = read_stage_policy(context, 'rf_mass_filter_l1')
    result = run_managed_stage(context, descriptor=dict(project='rf_multipole_ion_optics',
        mode='mass_filter_reference', software=['Python solver-free quadrupole L1']), run_id=run_id,
        payload=dict(model_level='L1', solver_rerun=False, lifecycle_stage='prepared',
            requested_input_paths={name: str(path.resolve()) for name, path in requested.items()},
            frozen_request_schema_version=2, process_deadline_policy='engineering_warning_natural_drain'),
        committed_new_bytes=policy['limits']['transient_run_directory_bytes'],
        commitment_inputs=[policy_record, *original.values()], retention=policy['artifact_retention'],
        expected_operation_ids=['prepare', 'simulation', 'analysis'],
        operation_dependencies={'simulation': ['prepare'], 'analysis': ['simulation']},
        action=partial(_run_action, requested=requested, original_records=original, stage=policy),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
        completion_api=no_particle_batch_completion_api)
    if result['status'] == 'failed':
        raise RuntimeError('mass-filter L1 functional gate failed')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--simulate-response", type=Path)
    action.add_argument("--analyze-response", type=Path)
    parser.add_argument("--resolved-design", type=Path)
    parser.add_argument("--analysis-metrics", type=Path)
    parser.add_argument("--analysis-figure", type=Path)
    args = parser.parse_args()
    if args.simulate_response is not None:
        if args.resolved_design is None or args.analysis_metrics is not None or args.analysis_figure is not None:
            parser.error("--simulate-response requires --resolved-design and no analysis outputs")
        rows = scan_response(load_json(args.baseline), load_json(args.resolved_design),
                             load_json(args.mode), load_json(args.source))
        write_response_csv(args.simulate_response, rows)
        print("QUADRUPOLE_MASS_FILTER_L1_SIMULATION=COMPLETED")
    else:
        if args.analysis_metrics is None or args.analysis_figure is None or args.resolved_design is not None:
            parser.error("--analyze-response requires analysis outputs and no --resolved-design")
        metrics = analyze_response_file(args.analyze_response, args.baseline, args.mode, args.source,
                                        args.analysis_metrics, args.analysis_figure)
        print(f"QUADRUPOLE_MASS_FILTER_L1_ANALYSIS=COMPLETED FUNCTIONAL={metrics['status']}")


if __name__ == "__main__":
    main()
