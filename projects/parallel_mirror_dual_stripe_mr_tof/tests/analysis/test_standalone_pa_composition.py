"""Pure block-codec fixtures; optional official SL reader, never commercial."""
from dataclasses import replace
import importlib.util
import math
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import standalone_pa_composition as c

# Root can freeze these small assets in its existing managed diagnostic run.
# Real GEM compilation, rather than a zero-witness Lua fill, supplies actual
# fractional offsets. This unrefined fixture validates format, not physics.
FRACTIONAL_GEM = '''pa_define(9,9,9,planar,x,electrostatic,,0.1,0.2,0.3,surface=fractional)
e(0) { fill { within { box3D(0,0,0,0.8,1.6,2.4) } notin { box3D(0.1,0.2,0.3,0.7,1.4,2.1) } } }
e(2.5) { fill { within { sphere(0.34,0.84,1.23,0.25) } } }
'''
FRACTIONAL_RELOAD_LUA = r'''
local b,r,o,c=arg[1],arg[2],arg[3],assert(tonumber(arg[4]))
local base=assert(simion.pas:open(b));local response=assert(simion.pas:open(r));local output=assert(simion.pas:open(o))
assert(base.nx==output.nx and base.ny==output.ny and base.nz==output.nz)
assert(base.dx_mm==output.dx_mm and base.dy_mm==output.dy_mm and base.dz_mm==output.dz_mm and base.symmetry==output.symmetry)
local offsets,max_error=0,0
for x,y,z in base:points() do
 local bv,be=base:point(x,y,z);local rv,re=response:point(x,y,z);local ov,oe=output:point(x,y,z)
 assert(be==re and be==oe,'electrode flag changed')
 max_error=math.max(max_error,math.abs(ov-(bv+c*rv)))
 local sx,sy,sz=base:surface_info(x,y,z);local tx,ty,tz=output:surface_info(x,y,z)
 assert(sx==tx and sy==ty and sz==tz,'fractional offset changed')
 if sx or sy or sz then offsets=offsets+1 end
end
assert(offsets>0,'GEM must supply real fractional offsets')
print(string.format('ORDINARY_BLOCK_CODEC_RELOAD offsets=%d max_node_error=%.17g no_refine=true no_fly=true',offsets,max_error))
base:close();response:close();output:close()
'''


class StandaloneCompositionTest(unittest.TestCase):
    def test_fractional_gem_fixture_mm_coordinates_inside_physical_domain(self):
        # With explicit pa_define pitches, GEM positions are mm, not grid units.
        # This catches empty/outside fixtures; actual offsets still require gem2pa.
        sphere = re.search(r'sphere\(([^)]+)\)', FRACTIONAL_GEM)
        self.assertIsNotNone(sphere)
        x, y, z, radius = map(float, sphere.group(1).split(','))
        for center, extent in zip((x, y, z), (.8, 1.6, 2.4)):
            self.assertGreater(center - radius, 0)
            self.assertLess(center + radius, extent)
        self.assertIn('box3D(0,0,0,0.8,1.6,2.4)', FRACTIONAL_GEM)
        self.assertNotIn('box(', FRACTIONAL_GEM)
        self.assertIn('surface=fractional', FRACTIONAL_GEM)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.header = c.PaHeader(-2, 1, 100, 3, 5, 2, 1 | (100 << 4), .1, .2, .3)
        self.flags = np.arange(30) % 3 == 1
        self.b = np.arange(30, dtype=np.float64) - 15
        self.r = 7 - np.arange(30, dtype=np.float64) / 4
        self.base = self.write('base.pa', self.b)
        self.response = self.write('response.pa', self.r, maximum=200)
        self.output = self.root / 'output.pa'

    def write(self, name, values, *, flags=None, maximum=100, header=None):
        h = header or replace(self.header, max_voltage=maximum)
        flags = self.flags if flags is None else flags
        raw = np.asarray(values, dtype='<f8') + flags * (2 * h.max_voltage)
        path = self.root / name
        with path.open('wb') as f:
            f.write(struct.pack('<iidiiiiddd', h.mode, h.symmetry, h.max_voltage,
                                h.nx, h.ny, h.nz, h.raw_mirror, h.dx_mm, h.dy_mm, h.dz_mm))
            raw.tofile(f)
        return path

    def decode(self, path):
        h = c.read_pa_header(path)
        with path.open('rb') as f:
            f.seek(56)
            raw = np.fromfile(f, dtype='<f8', count=h.node_count)
        flags = raw > h.max_voltage
        return h, raw - flags * 2 * h.max_voltage, flags

    def test_signed_zero_large_coefficients_flags_and_output_header_roundtrip(self):
        for coefficient in (2, -.5, 0, 1_000_000):
            with self.subTest(coefficient=coefficient):
                output = self.root / f'output{coefficient}.pa'
                result = c.compose_standalone_pa(self.base, output, [(self.response, coefficient)], chunk_nodes=7)
                h, values, flags = self.decode(output)
                np.testing.assert_array_equal(values, self.b + coefficient * self.r)
                np.testing.assert_array_equal(flags, self.flags)
                self.assertEqual(h.grid_identity, self.header.grid_identity)
                self.assertEqual(h.pack(), output.read_bytes()[:56])
                self.assertEqual(output.stat().st_size, 56 + 30 * 8)
                self.assertEqual(result['blocks'], math.ceil(30 / 7))
                self.assertFalse(result['full_pa_hash_performed'])
                self.assertFalse(result['refine_performed'])
                self.assertFalse(result['qualification_passed'])

    def test_negative_electrode_uses_raw_greater_than_max_not_twice_max(self):
        base = self.write('negative.pa', np.full(30, -75.0))
        c.compose_standalone_pa(base, self.output, [], chunk_nodes=5)
        _, actual, flags = self.decode(self.output)
        np.testing.assert_array_equal(actual, np.full(30, -75.0))
        np.testing.assert_array_equal(flags, self.flags)

    def test_new_outputs_flush_and_fsync_before_close_and_success(self):
        for path in (self.base, self.response):
            path.with_suffix('.pa-surf').write_bytes(b'sealed-fractional-offsets')
        events, streams = [], {}
        original_open, original_fsync = Path.open, c.os.fsync

        def observe_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            if args and args[0] == 'xb':
                streams[stream.fileno()] = (path, stream)
                flush, close = stream.flush, stream.close

                def observe_flush():
                    events.append(('flush', path.name))
                    return flush()

                def observe_close():
                    events.append(('close', path.name))
                    return close()

                stream.flush, stream.close = observe_flush, observe_close
            return stream

        def observe_fsync(fd):
            path, stream = streams[fd]
            self.assertFalse(stream.closed)
            self.assertEqual(events[-1], ('flush', path.name))
            events.append(('fsync', path.name))
            return original_fsync(fd)

        with patch.object(Path, 'open', observe_open), patch.object(c.os, 'fsync', side_effect=observe_fsync):
            result = c.compose_standalone_pa(self.base, self.output, [(self.response, -.5)], chunk_nodes=7)
        events.append(('success', result['status']))
        for name in ('output.pa', 'output.pa-surf'):
            self.assertEqual(events.count(('fsync', name)), 1)
            self.assertLess(events.index(('fsync', name)), events.index(('close', name)))
            self.assertLess(events.index(('close', name)), len(events) - 1)
        self.assertEqual(set(path.name for path, _ in streams.values()), {'output.pa', 'output.pa-surf'})
        np.testing.assert_array_equal(self.decode(self.output)[1], self.b - .5 * self.r)
        np.testing.assert_array_equal(self.decode(self.output)[2], self.flags)

    def test_fsync_failure_propagates_without_success_or_input_refresh(self):
        for path in (self.base, self.response):
            path.with_suffix('.pa-surf').write_bytes(b'sealed-fractional-offsets')
        before = {p: p.read_bytes() for p in (self.base, self.response,
                  self.base.with_suffix('.pa-surf'), self.response.with_suffix('.pa-surf'))}
        for fail_at in (1, 2):
            with self.subTest(fail_at=fail_at):
                output = self.root / f'fsync_failure_{fail_at}.pa'
                calls = []
                original_open, original_fsync = Path.open, c.os.fsync
                outputs = {}

                def observe_open(path, *args, **kwargs):
                    stream = original_open(path, *args, **kwargs)
                    if args and args[0] == 'xb':
                        outputs[stream.fileno()] = path
                    return stream

                def fail_fsync(fd):
                    calls.append(outputs[fd])  # An input fd must never reach fsync.
                    if len(calls) == fail_at:
                        raise OSError('fixture fsync refused')
                    return original_fsync(fd)

                with patch.object(Path, 'open', observe_open), patch.object(c.os, 'fsync', side_effect=fail_fsync):
                    with self.assertRaisesRegex(OSError, 'fsync refused'):
                        c.compose_standalone_pa(self.base, output, [(self.response, .5)], chunk_nodes=7)
                self.assertEqual(len(calls), fail_at)
                self.assertTrue(output.exists(), 'private partial output stays with owner lifecycle')
                self.assertEqual(output.with_suffix('.pa-surf').exists(), fail_at == 2)
                self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_bounded_multiresponse_reads_skip_zero_payload(self):
        zero = self.write('zero.pa', np.full(30, np.nan))
        original = c.np.fromfile
        calls = []
        def observe(stream, *, dtype, count):
            calls.append(Path(stream.name).name)
            self.assertLessEqual(count, 4)
            return original(stream, dtype=dtype, count=count)
        with patch.object(c.np, 'fromfile', side_effect=observe):
            result = c.compose_standalone_pa(self.base, self.output,
                                           [(self.response, 2), (self.response, -.5), (zero, 0)], chunk_nodes=4)
        self.assertNotIn('zero.pa', calls)
        self.assertFalse(result['responses'][-1]['payload_consumed'])
        np.testing.assert_array_equal(self.decode(self.output)[1], self.b + 1.5 * self.r)

    def test_identical_fractional_sidecar_copy_hashes_only_small_sidecars(self):
        for path in (self.base, self.response):
            path.with_suffix('.pa-surf').write_bytes(b'opaque-fixture-of-sealed-identical-offsets')
        original = c.file_sha256
        def observe(path):
            self.assertEqual(path.suffix, '.pa-surf')
            return original(path)
        with patch.object(c, 'file_sha256', side_effect=observe):
            result = c.compose_standalone_pa(self.base, self.output, [(self.response, -2)])
        self.assertEqual(self.output.with_suffix('.pa-surf').read_bytes(), self.base.with_suffix('.pa-surf').read_bytes())
        self.assertEqual(result['surface']['sha256'], result['source_surface']['sha256'])

    def test_sidecar_missing_mismatch_or_empty_rejects_before_output(self):
        self.base.with_suffix('.pa-surf').write_bytes(b'sealed')
        for content in (None, b'different', b''):
            with self.subTest(content=content):
                if content is not None:
                    self.response.with_suffix('.pa-surf').write_bytes(content)
                with self.assertRaises(ValueError):
                    c.compose_standalone_pa(self.base, self.output, [(self.response, 1)])
                self.assertFalse(self.output.exists())

    def test_grid_mode_magnetic_unknown_header_and_footer_fail_closed(self):
        for h in (replace(self.header, dx_mm=.25), replace(self.header, raw_mirror=0),
                  replace(self.header, raw_mirror=9), replace(self.header, raw_mirror=1 << 25),
                  replace(self.header, mode=-1), replace(self.header, mode=-3),
                  replace(self.header, symmetry=2), replace(self.header, max_voltage=float('nan'))):
            with self.subTest(header=h):
                response = self.write('bad.pa', self.r, header=h)
                with self.assertRaises(ValueError):
                    c.compose_standalone_pa(self.base, self.output, [(response, 1)])
                self.assertFalse(self.output.exists())
        self.response.write_bytes(self.response.read_bytes() + b'PA0 footer')
        with self.assertRaisesRegex(ValueError, 'footer'):
            c.compose_standalone_pa(self.base, self.output, [(self.response, 1)])

    def test_payload_flags_and_nonfinite_fail_leave_only_new_private_partial(self):
        for cause in ('flags', 'nonfinite'):
            with self.subTest(cause=cause):
                output = self.root / f'{cause}.pa'
                response = self.write(f'{cause}_response.pa', self.r if cause == 'flags' else np.full(30, np.nan),
                                      flags=~self.flags if cause == 'flags' else self.flags)
                before = self.base.read_bytes(), response.read_bytes()
                with self.assertRaises(ValueError):
                    c.compose_standalone_pa(self.base, output, [(response, 1)], chunk_nodes=3)
                self.assertEqual((self.base.read_bytes(), response.read_bytes()), before)
                self.assertTrue(output.exists(), 'partial output belongs to owner lifecycle')

    def test_existing_output_sidecar_and_family_suffix_reject_without_overwrite(self):
        for name in ('existing.pa', 'onlysidecar.pa'):
            output = self.root / name
            protected = output if name == 'existing.pa' else output.with_suffix('.pa-surf')
            protected.write_bytes(b'unrelated owner')
            with self.assertRaises(ValueError):
                c.compose_standalone_pa(self.base, output, [(self.response, 1)])
            self.assertEqual(protected.read_bytes(), b'unrelated owner')
        native = self.root / 'response.pa0'
        native.write_bytes(self.response.read_bytes())
        with self.assertRaises(ValueError):
            c.compose_standalone_pa(self.base, self.output, [(native, 1)])

    def test_coefficients_chunk_sizes_and_overflow_reject(self):
        for coefficient in (True, float('inf'), float('nan'), '1', 1e308):
            with self.subTest(coefficient=coefficient), self.assertRaises(ValueError):
                c.compose_standalone_pa(self.base, self.output, [(self.response, coefficient)])
        for size in (0, -1, True, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                c.compose_standalone_pa(self.base, self.output, [], chunk_nodes=size)
        self.assertFalse(self.output.exists())

    def test_official_installed_sl_reader_accepts_output_values_flags_and_header(self):
        path = Path('C:/Program Files/SIMION-2020/lib/python/SIMION/PA.py')
        if not path.is_file():
            self.skipTest('installed official SL Python reader unavailable')
        spec = importlib.util.spec_from_file_location('official_simion_pa_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        c.compose_standalone_pa(self.base, self.output, [(self.response, -.5)], chunk_nodes=2)
        actual = module.PA(file=str(self.output))
        self.assertEqual(actual.mode(), -2)
        self.assertEqual(actual.dx_mm(), .1)
        self.assertEqual(actual.mirror(), 'x')
        for i, expected in enumerate(self.b - .5 * self.r):
            z, remainder = divmod(i, 15)
            y, x = divmod(remainder, 3)
            flag, value = actual.point(x, y, z)
            self.assertEqual(bool(flag), bool(self.flags[i]))
            self.assertEqual(value, expected)


if __name__ == '__main__':
    unittest.main()
