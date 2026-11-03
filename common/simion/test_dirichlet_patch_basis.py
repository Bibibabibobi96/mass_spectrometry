from __future__ import annotations

import os
import hashlib
import time
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_support import fixture_process
from common.host_resource_python import ensure_heavy_entry


ROOT = Path(__file__).resolve().parents[2]
SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
FIXTURE = Path(__file__).with_name("test_dirichlet_patch_basis_fixture.lua")
BUILDER = Path(__file__).with_name("build_dirichlet_patch_basis.lua")
GEM2PA = Path(__file__).with_name("run_gem2pa.ps1")


# Installed SIMION documentation Issue468; this test run-control is explicit,
# never a production/global default or a substitute for scientific assertions.
_ASYNC_IO_PRELUDE = (
    "local d=assert(simion.debug,'async IO debug interface unavailable'); "
    "local before=d.allow_asynchronous_io; "
    "assert(type(before)=='boolean','async IO flag getter unverified'); "
    "print('ASYNC_IO_CONTROL before='..tostring(before)); io.stdout:flush(); "
    "d.allow_asynchronous_io=false; "
    "assert(d.allow_asynchronous_io==false,'async IO flag readback failed'); "
    "print('ASYNC_IO_CONTROL applied=false'); io.stdout:flush()"
)


def _fixture_execution_command(command, *, disable_async_io):
    """Prepare this tiny native Lua test's explicit, executable-scoped I/O mode."""
    original = list(command)
    if not isinstance(disable_async_io, bool):
        raise TypeError('disable_async_io must be boolean')
    if not disable_async_io:
        return original
    if not original or Path(original[0]).resolve() != SIMION.resolve():
        raise ValueError('Explicit native I/O mode requires the configured SIMION executable')
    if '--lua' in original:
        raise ValueError('Explicit native I/O mode conflicts with an existing Lua prelude')
    if original[1:4] != ['--nogui', '--noprompt', 'lua']:
        raise ValueError('Explicit native I/O mode requires the tiny headless Lua fixture command')
    return original[:3] + ['--lua', _ASYNC_IO_PRELUDE] + original[3:]


def _instrument_builder(root):
    """Insert flushed observations only; removing them restores exact producer bytes."""
    original = BUILDER.read_bytes()
    anchors = (
        b"  local pa=assert(simion.pas:open(path), 'cannot open coarse response PA: '..path)",
        b"local target=assert(simion.pas:open(output_path), 'cannot open pre-biased local response PA')",
        b"target:save(output_path)",
        b"for _,source in ipairs(sources) do source.pa:close() end",
        b"if skipped_point~=nil then target:refine{convergence=convergence,skipped_point=skipped_point}\nelseif convergence then target:refine{convergence=convergence} else target:refine() end",
        b"target:close()",
    )
    actual = original
    inserts = []
    for index, anchor in enumerate(anchors):
        expected = 2 if anchor == b'target:save(output_path)' else 1
        if original.count(anchor) != expected:
            raise RuntimeError('Dirichlet checkpoint anchor count changed')
        before = f"print('DIRICHLET_CHECKPOINT={index}:before'); io.stdout:flush()\n".encode()
        after = f"\nprint('DIRICHLET_CHECKPOINT={index}:after'); io.stdout:flush()".encode()
        actual = actual.replace(anchor, before + anchor + after)
        inserts.extend((before, after))
    restored = actual
    for marker in inserts:
        restored = restored.replace(marker, b'')
    if restored != original:
        raise RuntimeError('Dirichlet checkpoint projection changed producer bytes')
    destination = root / 'observed_dirichlet_builder.lua'
    destination.write_bytes(actual)
    return destination, dict(original_sha256=hashlib.sha256(original).hexdigest(),
                             observed_sha256=hashlib.sha256(actual).hexdigest(),
                             restored_bytes_equal=True, anchor_counts=[1, 1, 2, 1, 1, 1])


def _save_native_evidence(destination, root, metadata, stdout, stderr, drained):
    """Reuse serialization only, never the shared fixture's ACK/Job kill policy."""
    cap = 65536
    metadata['output_lengths'] = dict(stdout=len(stdout), stderr=len(stderr))
    metadata['output_sha256'] = dict(stdout=hashlib.sha256(stdout).hexdigest(),
                                     stderr=hashlib.sha256(stderr).hexdigest())
    metadata['raw_output_cap_bytes'] = cap
    metadata['small_inputs'] = []
    raw = (stdout[:cap], stderr[:cap], None if drained is None else drained[0][:cap],
           None if drained is None else drained[1][:cap])
    fixture_process._save_evidence(destination, root or destination, metadata, *raw)
    copy_failure = None
    if root is not None:
        for name in ('target.gem', 'target_mirror.gem', 'target.pa', 'target_mirror.pa',
                     'donor.pa', 'observed_dirichlet_builder.lua'):
            source = root / name
            try:
                if source.is_file() and source.stat().st_size <= cap:
                    payload = source.read_bytes()
                    (destination / name).write_bytes(payload)
                    metadata['small_inputs'].append(dict(name=name, bytes=len(payload),
                                                         sha256=hashlib.sha256(payload).hexdigest()))
            except Exception as error:
                metadata['secondary_errors'].append(f'small_input={name}: {error!r}')
                if copy_failure is None:
                    copy_failure = error
    fixture_process._save_evidence(destination, root or destination, metadata, *raw)
    if copy_failure is not None:
        raise copy_failure


def _wait_owned_child(process, error, metadata, pending):
    """Keep the original owner/handle until its child actually exits, without killing."""
    if pending is not None:
        try:
            pending()
        except Exception as cleanup:
            error.add_note(f'native_fixture_pending_secondary={cleanup!r}')
            metadata['secondary_errors'].append(repr(cleanup))
    while process.poll() is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue
        except Exception as cleanup:
            error.add_note(f'native_fixture_wait_secondary={cleanup!r}')
            metadata['secondary_errors'].append(repr(cleanup))
            time.sleep(1)
    metadata['returncode'] = process.returncode
    metadata['exit_confirmed'] = True


def _stop_timed_out_child(process, error, metadata, pending=None):
    """Retain subprocess.run's own-child kill policy without masking its timeout."""
    drained = None
    try:
        process.kill()
    except Exception as cleanup:
        error.add_note(f'native_fixture_kill_secondary={cleanup!r}')
        metadata['secondary_errors'].append(repr(cleanup))
    try:
        drained = process.communicate(timeout=5)
    except Exception as cleanup:
        error.add_note(f'native_fixture_drain_secondary={cleanup!r}')
        metadata['secondary_errors'].append(repr(cleanup))
    metadata['returncode'] = process.returncode
    metadata['exit_confirmed'] = process.poll() is not None
    if not metadata['exit_confirmed']:
        _wait_owned_child(process, error, metadata, pending)
    return drained


def run_native_fixture(command, *, root, timeout=120, observation=None, disable_async_io=False):
    """Original direct-child deadline with bounded evidence and primary preservation."""
    original_command = list(command)
    command = _fixture_execution_command(command, disable_async_io=disable_async_io)
    evidence_root = Path(tempfile.gettempdir()) / 'oatof_fixture_diagnostics'
    evidence_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='dirichlet-', dir=evidence_root))
    metadata = dict(command=list(command), original_command=original_command, observation=observation,
                    io_mode='explicit_async_disabled' if disable_async_io else 'installed_default_unmodified',
                    control_lua_prelude=_ASYNC_IO_PRELUDE if disable_async_io else None, timeout_seconds=timeout,
                    cwd=str(ROOT), started_monotonic=time.monotonic(), secondary_errors=[],
                    scope='tiny_native_fixture', evidence_directory=str(destination))
    stdout = stderr = b''
    drained = None
    failure = None
    process = None
    try:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        metadata['pid'] = process.pid
        if os.name == 'nt':
            try:
                metadata['creation_filetime_100ns'] = fixture_process._creation_filetime(int(process._handle))
            except Exception as error:
                metadata['secondary_errors'].append(repr(error))
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.output or b'', error.stderr or b''
            metadata['primary'] = dict(type=type(error).__name__, message=str(error))
            drained = _stop_timed_out_child(process, error, metadata,
                pending=lambda: _save_native_evidence(destination, root, metadata, stdout, stderr, None))
            if drained is not None:
                error.output, error.stderr = drained
            raise
        metadata['returncode'] = process.returncode
        metadata['exit_confirmed'] = process.poll() is not None
        result = subprocess.CompletedProcess(command, process.returncode,
                                            stdout.decode('utf-8', errors='replace'),
                                            stderr.decode('utf-8', errors='replace'))
        result.check_returncode()
        if metadata['secondary_errors']:
            raise RuntimeError('Native fixture process identity evidence unavailable')
        return result
    except BaseException as error:
        failure = error
        metadata['primary'] = dict(type=type(error).__name__, message=str(error))
        if process is not None and process.poll() is None:
            _wait_owned_child(process, error, metadata,
                pending=lambda: _save_native_evidence(destination, root, metadata, stdout, stderr, drained))
        error.add_note(f'native_fixture_evidence={destination}')
        raise
    finally:
        close_failure = None
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception as error:
                        metadata['secondary_errors'].append(repr(error))
                        if failure is not None:
                            failure.add_note(f'native_fixture_close_secondary={error!r}')
                        elif close_failure is None:
                            close_failure = error
        if close_failure is not None and failure is None:
            failure = close_failure
            metadata['primary'] = dict(type=type(failure).__name__, message=str(failure))
        metadata['finished_monotonic'] = time.monotonic()
        try:
            _save_native_evidence(destination, root, metadata, stdout, stderr, drained)
        except Exception as error:
            if failure is None:
                raise
            failure.add_note(f'native_fixture_diagnostic_secondary={error!r}')
        if close_failure is not None and failure is close_failure:
            raise close_failure


@unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
class DirichletPatchBasisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if (not os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN') or
                os.environ.get('MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE') != 'SIMION'):
            raise RuntimeError('Dirichlet native tests require the declared public SIMION/pa_refine grant')
        ensure_heavy_entry(__name__, role='SIMION', stage='pa_refine')

    def run_simion(self, *arguments: object) -> str:
        original = [str(SIMION), '--nogui', '--noprompt', 'lua', *(str(v) for v in arguments)]
        directories = [Path(str(v)) for v in arguments if Path(str(v)).is_dir()]
        root = directories[-1] if directories else Path(str(arguments[1]).split(',')[0]).parent
        owned = root.is_absolute() and root.parent == Path(tempfile.gettempdir()) and root.name.startswith('simion-')
        observation = dict(original_command=original)
        command = list(original)
        if Path(str(arguments[0])) == BUILDER:
            if owned:
                observed, identity = _instrument_builder(root)
                command[4] = str(observed)
                observation.update(identity)
            else:
                # Invalid arguments fail before arrays open; use a fresh owned diagnostic scope.
                with tempfile.TemporaryDirectory(prefix='simion-dirichlet-invalid-') as directory:
                    observed, identity = _instrument_builder(Path(directory))
                    command[4] = str(observed)
                    observation.update(identity)
                    return run_native_fixture(command, root=Path(directory), timeout=120,
                                              observation=observation, disable_async_io=True).stdout
        return run_native_fixture(command, root=root if owned else None, timeout=120,
                                  observation=observation, disable_async_io=True).stdout

    def test_native_10000_v_donor_is_not_rescaled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-patch-") as directory:
            self.assertIn("PREPARED", self.run_simion(FIXTURE, "prepare", directory))
            compile_result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target.gem"),
                 "-OutputPaPath", str(Path(directory) / "target.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            self.assertIn("SIMION_GEM2PA=PASS", compile_result.stdout)
            output = self.run_simion(
                BUILDER,
                Path(directory) / "target.pa",
                Path(directory) / "donor.pa",
                "0,0,0",
                "1,1,1",
            )
            self.assertIn("native_basis_voltage=10000", output)
            self.assertIn("boundary_scale=1", self.run_simion(FIXTURE, "verify", directory))

    def test_optional_source_coefficient_scales_only_donor_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-scaled-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target.gem"),
                 "-OutputPaPath", str(Path(directory) / "target.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            self.run_simion(
                BUILDER,
                Path(directory) / "target.pa",
                f"{Path(directory) / 'donor.pa'},0.5",
                "0,0,0",
                "1,1,1",
            )
            self.assertIn("boundary_scale=0.5", self.run_simion(FIXTURE, "verify_scaled", directory))
    def test_x_mirror_plane_is_not_overwritten_by_dirichlet_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-mirror-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target_mirror.gem"),
                 "-OutputPaPath", str(Path(directory) / "target_mirror.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            output = self.run_simion(
                BUILDER, Path(directory) / "target_mirror.pa", Path(directory) / "donor.pa",
                "0,0,0", "0,0,0", "x_mirror_five_faces",
            )
            self.assertIn("boundary_mode=x_mirror_five_faces", output)
            self.assertIn("boundary_mode=x_mirror_five_faces", self.run_simion(FIXTURE, "verify_mirror", directory))

    def test_explicit_stopping_keeps_mirror_edges_and_physical_voltage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-stopping-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target_mirror.gem"),
                 "-OutputPaPath", str(Path(directory) / "target_mirror.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            output = self.run_simion(
                BUILDER, Path(directory) / "target_mirror.pa", Path(directory) / "donor.pa",
                "0,0,0", "0,0,0", "x_mirror_five_faces", "1e-5",
            )
            self.assertIn("refine_convergence=1e-05", output.lower())
            self.assertIn("boundary_mode=x_mirror_five_faces", self.run_simion(FIXTURE, "verify_mirror", directory))

    def test_invalid_stopping_is_rejected_before_opening_arrays(self) -> None:
        for value in ("0", "-1", "nan", "inf", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(subprocess.CalledProcessError) as failure:
                    self.run_simion(BUILDER, "absent-target.pa", "absent-source.pa",
                                    "0,0,0", "0,0,0", "six_faces", value)
                message = (failure.exception.stdout or "") + (failure.exception.stderr or "")
                self.assertIn("convergence", message.lower())

    def test_parent_refine_cli_accepts_explicit_stopping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-parent-stopping-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            target = Path(directory) / "target.pa"
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target.gem"),
                 "-OutputPaPath", str(target)],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "refine", "--convergence=1e-5", str(target)],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            self.assertIn("Refine completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
