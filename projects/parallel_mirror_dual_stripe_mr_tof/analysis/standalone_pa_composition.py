"""Blockwise affine combination of ordinary SIMION electrostatic PA files.

Format authority: installed SIMION 2020 SL ``lib/python/SIMION/PA.py``
(load/save/point) and ``lib/cpp/simion/pa.cpp`` (load/save binary), not a new
solver. Only little-endian mode -2, 56-byte ordinary headers are accepted;
PA0 footers, magnetic fields and unknown header flags fail closed.

Inputs must already be immutable, manifest-bound by the owning workflow.
This core reads PA headers/lengths, never hashes entire PA inputs. Fractional
sidecars must have identical byte identity and are copied unchanged to the
new output. Failures leave any partial *new private* output for the owning
run lifecycle; existing files and input arrays are never modified or removed.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import shutil
import struct
from typing import Any, BinaryIO, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256

HEADER = struct.Struct('<iidiiiiddd')
PA_CHUNK_NODES = 1 << 20


@dataclass(frozen=True)
class PaHeader:
    """Ordinary mode -2 header; volts, grid dimensions and mm/grid-unit pitch."""

    mode: int
    symmetry: int
    max_voltage: float
    nx: int
    ny: int
    nz: int
    raw_mirror: int
    dx_mm: float
    dy_mm: float
    dz_mm: float

    @property
    def node_count(self) -> int:
        return self.nx * self.ny * self.nz

    @property
    def file_bytes(self) -> int:
        return HEADER.size + self.node_count * 8

    @property
    def grid_identity(self) -> tuple[Any, ...]:
        return (self.mode, self.symmetry, self.nx, self.ny, self.nz,
                self.raw_mirror, self.dx_mm, self.dy_mm, self.dz_mm)

    def pack(self) -> bytes:
        """Encode the official fixed header without PA0 appended data."""
        return HEADER.pack(*(getattr(self, name) for name in self.__dataclass_fields__))


def _read_header(stream: BinaryIO, path: Path) -> PaHeader:
    data = stream.read(HEADER.size)
    if len(data) != HEADER.size:
        raise ValueError(f'ordinary PA header truncated: {path}')
    header = PaHeader(*HEADER.unpack(data))
    if header.mode != -2 or header.symmetry not in (0, 1):
        raise ValueError(f'only known ordinary mode -2 symmetry supported: {path}')
    # SL PAHeader: bits0..2 mirrors, bit3 magnetic, bits4..20 NG. Preserve
    # the known NG bits even for an electrostatic array; reject unknown bits.
    if header.raw_mirror < 0 or header.raw_mirror & 8 or header.raw_mirror >> 21:
        raise ValueError(f'magnetic or unknown PA header flags: {path}')
    if (min(header.nx, header.ny, header.nz) < 1
            or not math.isfinite(header.max_voltage) or header.max_voltage <= 0
            or not math.isfinite(2 * header.max_voltage)
            or any(not math.isfinite(v) or v <= 0
                   for v in (header.dx_mm, header.dy_mm, header.dz_mm))):
        raise ValueError(f'invalid ordinary PA dimensions/range/pitch: {path}')
    if path.stat().st_size != header.file_bytes:
        raise ValueError(f'ordinary PA payload length or PA0 footer differs: {path}')
    return header


def read_pa_header(path: Path) -> PaHeader:
    """Read/validate only an ordinary .pa header and exact payload length."""
    path = Path(path)
    if path.suffix.lower() != '.pa':
        raise ValueError('only standalone .pa input accepted; no PA family suffix')
    with path.open('rb') as stream:
        return _read_header(stream, path)


def _surface_record(path: Path) -> dict[str, Any] | None:
    surface = path.with_suffix('.pa-surf')
    if not surface.exists():
        return None
    if not surface.is_file() or not surface.stat().st_size:
        raise ValueError(f'fractional sidecar is not a nonempty file: {surface}')
    return dict(path=str(surface.resolve()), bytes=surface.stat().st_size,
                sha256=file_sha256(surface))


def _read_block(stream: BinaryIO, count: int, header: PaHeader) -> tuple[np.ndarray, np.ndarray]:
    raw = np.fromfile(stream, dtype='<f8', count=count)
    if raw.size != count or not np.isfinite(raw).all():
        raise ValueError(f'ordinary PA payload truncated or nonfinite: {stream.name}')
    # Official SL point/electrode getter uses strict raw > max_voltage, not
    # raw >= 2*max_voltage. Negative electrode potentials remain encoded.
    flags = raw > header.max_voltage
    raw[flags] -= 2 * header.max_voltage
    if np.any(np.abs(raw) > header.max_voltage):
        raise ValueError(f'ordinary PA encoded potential exceeds its header range: {stream.name}')
    return raw, flags


def validate_standalone_pa_payload(path: Path, *, chunk_nodes: int = PA_CHUNK_NODES) -> dict[str, Any]:
    """Check every newly refined ordinary PA node in bounded, read-only blocks.

    Reuse the installed SL format boundary above, including negative electrode
    potentials encoded as potential + 2*max_voltage. This is a producer check,
    not an accuracy test or a repeated consumer scan of sealed source arrays.
    """
    if isinstance(chunk_nodes, bool) or not isinstance(chunk_nodes, int) or chunk_nodes < 1:
        raise ValueError('chunk_nodes must be a positive integer')
    path = Path(path).resolve()
    header = read_pa_header(path)
    nodes = blocks = 0
    with path.open('rb') as stream:
        stream.seek(HEADER.size)
        while nodes < header.node_count:
            count = min(chunk_nodes, header.node_count - nodes)
            try:
                _read_block(stream, count, header)
            except ValueError as exc:
                raise ValueError(f'ordinary PA payload validation failed at node block {nodes}: {exc}') from exc
            nodes += count
            blocks += 1
    return dict(schema_version=1, role='simion_standalone_pa_payload_validation', status='PASS',
                path=str(path), bytes=header.file_bytes, expected_nodes=header.node_count,
                validated_nodes=nodes, finite_nodes=nodes, encoded_range_valid=True,
                chunk_nodes=chunk_nodes, blocks=blocks, full_pa_hash_performed=False)


def compose_standalone_pa(
    base_path: Path,
    output_path: Path,
    responses: Sequence[tuple[Path, float]],
    *,
    chunk_nodes: int = PA_CHUNK_NODES,
) -> dict[str, Any]:
    """Write BASE + sum(coefficient*response) in bounded float64 blocks.

    Keep baseline flags and require matching grids/flags for every consumed
    nonzero response. Zero-weight members get header/sidecar validation only,
    without payload reads. The caller owns scientific authority, immutable
    source guards, resource admission, output publication and failure cleanup.
    No Refine, PA-family access, full-array load or full-PA hash is performed.
    """
    if isinstance(chunk_nodes, bool) or not isinstance(chunk_nodes, int) or chunk_nodes < 1:
        raise ValueError('chunk_nodes must be a positive integer')
    base_path, output_path = Path(base_path).resolve(), Path(output_path).resolve()
    if output_path.suffix.lower() != '.pa':
        raise ValueError('new output must be standalone .pa')
    output_surface = output_path.with_suffix('.pa-surf')
    if output_path.exists() or output_surface.exists():
        raise ValueError('composition will not overwrite existing output or sidecar')
    normalized: list[tuple[Path, float]] = []
    for path, coefficient in responses:
        if (isinstance(coefficient, bool) or not isinstance(coefficient, (int, float))
                or not math.isfinite(coefficient)):
            raise ValueError('response coefficient must be finite')
        normalized.append((Path(path).resolve(), float(coefficient)))
    if output_path == base_path or any(path == output_path for path, _ in normalized):
        raise ValueError('output must be distinct from all immutable inputs')
    base_header = read_pa_header(base_path)
    base_surface = _surface_record(base_path)
    active: list[tuple[Path, float, PaHeader]] = []
    inputs = []
    for path, coefficient in normalized:
        header = read_pa_header(path)
        if header.grid_identity != base_header.grid_identity:
            raise ValueError(f'response grid/header flags differ from baseline: {path}')
        surface = _surface_record(path)
        expected = None if base_surface is None else (base_surface['bytes'], base_surface['sha256'])
        actual = None if surface is None else (surface['bytes'], surface['sha256'])
        if actual != expected:
            raise ValueError(f'response fractional sidecar differs from baseline: {path}')
        inputs.append(dict(path=str(path), bytes=header.file_bytes, coefficient=coefficient,
                           payload_consumed=coefficient != 0))
        if coefficient != 0:
            active.append((path, coefficient, header))
    bound = base_header.max_voltage + sum(abs(c) * h.max_voltage for _, c, h in active)
    # One conservative range from input declared ranges avoids a second full
    # pass. Twice the bound keeps even negative electrode potentials safely
    # separated from the flag threshold after output re-encoding.
    maximum = 2 * bound if active else base_header.max_voltage
    if not math.isfinite(maximum) or not math.isfinite(2 * maximum):
        raise ValueError('composition encoded voltage range overflows float64')
    output_header = replace(base_header, max_voltage=maximum)
    blocks = 0
    with ExitStack() as stack:
        base = stack.enter_context(base_path.open('rb'))
        base.seek(HEADER.size)
        streams = []
        for path, coefficient, header in active:
            stream = stack.enter_context(path.open('rb'))
            stream.seek(HEADER.size)
            streams.append((stream, coefficient, header))
        destination = stack.enter_context(output_path.open('xb'))
        destination.write(output_header.pack())
        remaining = base_header.node_count
        while remaining:
            count = min(chunk_nodes, remaining)
            values, flags = _read_block(base, count, base_header)
            for stream, coefficient, header in streams:
                delta, response_flags = _read_block(stream, count, header)
                if not np.array_equal(flags, response_flags):
                    raise ValueError(f'response electrode flags differ from baseline: {stream.name}')
                with np.errstate(over='ignore', invalid='ignore'):
                    delta *= coefficient
                    values += delta
            if not np.isfinite(values).all():
                raise ValueError('composed potential is nonfinite')
            values[flags] += 2 * maximum
            if not np.isfinite(values).all() or not np.array_equal(values > maximum, flags):
                raise ValueError('composed voltage encoding overflows or changes baseline flags')
            values.astype('<f8', copy=False).tofile(destination)
            remaining -= count
            blocks += 1
        # Python 3.11 os.fsync: flush buffered output first; Windows uses _commit.
        destination.flush()
        os.fsync(destination.fileno())
    surface_output = None
    if base_surface is not None:
        source = Path(base_surface['path'])
        with source.open('rb') as incoming, output_surface.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1 << 20)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        surface_output = _surface_record(output_path)
        if (surface_output['bytes'], surface_output['sha256']) != (base_surface['bytes'], base_surface['sha256']):
            raise ValueError('new fractional sidecar differs after immutable copy')
    actual_header = read_pa_header(output_path)
    if actual_header != output_header:
        raise ValueError('new ordinary PA header roundtrip differs')
    return dict(schema_version=1, role='simion_standalone_pa_composition', status='PASS',
                formula='BASE + sum(coefficient * response)',
                base=dict(path=str(base_path), bytes=base_header.file_bytes), responses=inputs,
                output=dict(path=str(output_path), bytes=actual_header.file_bytes),
                surface=surface_output, source_surface=base_surface,
                header=dict(zip(output_header.__dataclass_fields__, HEADER.unpack(output_header.pack()))),
                chunk_nodes=chunk_nodes, blocks=blocks, baseline_flags_preserved=True,
                nonzero_response_flags_verified=True, full_pa_hash_performed=False,
                refine_performed=False, qualification_passed=False)
