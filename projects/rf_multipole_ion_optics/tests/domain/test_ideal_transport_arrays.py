"""Solver-free regression tests for common NumPy multipole adapters."""

from __future__ import annotations

import unittest
import tempfile
import subprocess
import sys
import sysconfig
import json
from pathlib import Path

import numpy as np

from msplatform.components.rf_multipole.family_contract import VoltageDrive, rf_waveform_voltage
from msplatform.components.rf_multipole.ideal_transport import (
    electric_field_xy,
    electric_field_xy_array,
    rf_waveform_voltage_array,
    source_particles,
)


class IdealTransportArrayTest(unittest.TestCase):
    def test_rf_waveform_array_matches_scalar_voltage_oracle(self):
        times = np.array([0.0, 0.12e-6, 0.47e-6])
        for waveform in ("sine", "cosine"):
            with self.subTest(waveform=waveform):
                drive = VoltageDrive(waveform, 83.0, 0.0, 0.0, 1.2e6, 0.37)
                expected = np.array(
                    [rf_waveform_voltage(drive, float(time)) for time in times]
                )
                np.testing.assert_allclose(
                    rf_waveform_voltage_array(drive, times),
                    expected,
                    rtol=0.0,
                    atol=1e-13,
                )

    def test_field_array_matches_scalar_oracle_and_broadcasts_voltage(self):
        x_m = np.array([0.1e-3, -0.2e-3, 0.3e-3])
        y_m = np.array([-0.2e-3, 0.3e-3, 0.1e-3])
        for order in (2, 3, 4):
            with self.subTest(order=order):
                field_x, field_y = electric_field_xy_array(
                    order, 2.5e-3, np.array(83.0), x_m, y_m
                )
                expected = np.array(
                    [
                        electric_field_xy(order, 2.5e-3, 83.0, x, y)
                        for x, y in zip(x_m, y_m, strict=True)
                    ]
                )
                np.testing.assert_allclose(field_x, expected[:, 0], rtol=1e-14, atol=1e-12)
                np.testing.assert_allclose(field_y, expected[:, 1], rtol=1e-14, atol=1e-12)

    def test_source_projection_preserves_historical_l1_sequence(self):
        self.assertEqual(source_particles.__globals__["generate_release_states"].__module__,
                         "msplatform.ion_release.release")
        particles = source_particles({
            "rf": {"frequency_Hz": 1_100_000.0},
            "particle_source": {
                "count": 2, "seed": 20260722, "mass_amu": 100.0,
                "charge_state": 1, "kinetic_energy_eV": 2.0,
                "maximum_source_radius_mm": 0.5, "maximum_divergence_deg": 5.0,
            },
        })
        self.assertEqual(particles, [
            {
                "particle_id": 1, "birth_time_s": 9.005917074680262e-07,
                "x_m": -0.00030050212541290637, "y_m": 0.00021591805458583816,
                "vx_m_s": 102.4804793163208, "vy_m_s": 35.336438712049,
                "vz_m_s": 1961.5459142534435,
            },
            {
                "particle_id": 2, "birth_time_s": 7.897899115417313e-07,
                "x_m": 7.029143790761464e-05, "y_m": -0.00012228344093233935,
                "vx_m_s": -110.31001246837077, "vy_m_s": 69.33907541741773,
                "vz_m_s": 1960.2135291941072,
            },
        ])


if __name__ == "__main__":
    unittest.main()


class FrozenIdealTransportBoundaryTests(unittest.TestCase):
    def test_frozen_full_source_has_canonical_origin_and_missing_module_rejects(self):
        from msplatform.execution.inputs import enumerate_python_sources, freeze_file
        from msplatform.components.rf_multipole.family_contract import l1_l2_transport_contract_from_resolved_design
        from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
        repo=Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);snapshot=root/'code'
            resources=['src/msplatform/components/rf_multipole/family_contract.json']
            paths=enumerate_python_sources(repo,package_roots=['src/msplatform'],provider_root='src/msplatform')
            for relative in [*paths,*resources]:
                target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True)
                freeze_file(repo/relative,target)
            selected='src/msplatform/components/rf_multipole/ideal_transport.py'
            self.assertIn(selected,paths)
            contract=l1_l2_transport_contract_from_resolved_design(resolve_design_profile(repo,
                'rf_multipole_ion_optics','hexapole_no_acceleration_full_length')['resolved_design'])
            request=root/'contract.json';request.write_text(json.dumps(contract),encoding='utf-8')
            dependencies=list(dict.fromkeys(sysconfig.get_paths()[key] for key in ('purelib','platlib')))
            code="""import sys,pathlib,json
sys.path[:0]=[sys.argv[1],*json.loads(sys.argv[3])]
from msplatform.components.rf_multipole import ideal_transport as t
assert pathlib.Path(t.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
c=json.loads(pathlib.Path(sys.argv[2]).read_text());t.validate_contract(c)
rows=t.source_particles(c)
assert len(rows)==c['particle_source']['count']==100
assert [r['particle_id'] for r in rows]==list(range(1,101))
assert not any(k.split('.')[0] in ('common','projects','integrations') for k in sys.modules)
"""
            command=[sys.executable,'-I','-S','-B','-c',code,str(snapshot/'src'),str(request),json.dumps(dependencies)]
            positive=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(positive.returncode,0,positive.stderr)
            (snapshot/selected).unlink()
            negative=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(negative.returncode,0)
            self.assertIn('ImportError',negative.stderr)
