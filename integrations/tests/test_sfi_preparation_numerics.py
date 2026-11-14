"""Explicit backend numerics for neutral-component SFI preparation requests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from integrations.tests import test_single_reflection_preparation as fixtures
from msplatform.examples import load_example
from msplatform.io.manifest_records import file_record, record_path
from msplatform.workflows.single_reflection_flight.prepare import validate_preparation_request


class PreparationNumericsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path, self.run, self.legacy = fixtures.scientific_preparation_fixture(
            Path(temporary.name), recorded_birth=True)
        numerics = load_example('rf_oatof_functional_v1').geometry_numerics
        self.request = copy.deepcopy(self.legacy)
        self.request['schema_version'] = 11
        self.request['numerics'].update({
            key: copy.deepcopy(numerics[key]) for key in ('geometry_build', 'detector_marker')})

    def test_neutral_provider_is_frozen_unchanged_and_downstream_uses_explicit_numerics(self):
        from msplatform.workflows.single_reflection_flight.prepare import prepare
        from msplatform.workflows.single_reflection_flight.downstream_fields import plan_downstream_fields
        provider = self.request['providers']['instances']['oatof']
        path = record_path(provider['resolved_design'], base_dir=self.path.parent)
        neutral = json.loads(path.read_text(encoding='utf-8'))
        self.request['numerics']['geometry_build'] = neutral.pop('simion_geometry_build')
        self.request['numerics']['detector_marker'] = neutral.pop('simion_detector_marker')
        fixtures.write_json(path, neutral)
        provider['resolved_design'] = file_record(path)
        fixtures.write_json(self.path, self.request)
        receipt = prepare(self.path, self.run)
        fixtures.write_json(self.run / 'run_config.json', {'project': 'instrument_assembly'})
        frozen = receipt['input_records']['instance_design__oatof']
        self.assertEqual(json.loads(record_path(frozen).read_text(encoding='utf-8')), neutral)
        plan = plan_downstream_fields(receipt, self.run, snapshot_root=Path(__file__).resolve().parents[2])
        planned = json.loads(record_path(plan['plan_record']).read_text(encoding='utf-8'))
        self.assertEqual(planned['role'], 'single_reflection_downstream_native_plan')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), neutral)

    def test_explicit_numerics_validate_without_changing_author_request(self):
        before = copy.deepcopy(self.request)
        self.assertEqual(validate_preparation_request(self.request), 11)
        self.assertEqual(self.request, before)
        self.assertEqual(validate_preparation_request(self.legacy), 10)

    def test_missing_or_unknown_backend_numerics_are_rejected(self):
        for key in ('geometry_build', 'detector_marker'):
            changed = copy.deepcopy(self.request)
            del changed['numerics'][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_preparation_request(changed)
        changed = copy.deepcopy(self.request)
        changed['numerics']['geometry_build']['detector']['hidden_margin_mm'] = 1.
        with self.assertRaises(ValueError):
            validate_preparation_request(changed)

    def test_noninteger_native_targets_and_invalid_steps_are_rejected(self):
        changed = copy.deepcopy(self.request)
        provider = next(iter(changed['providers']['instances'].values()))
        group = next(iter(provider['electrode_bindings']))
        provider['electrode_bindings'][group] = float(provider['electrode_bindings'][group])
        with self.assertRaises(ValueError):
            validate_preparation_request(changed)
        for step in (0., -1., True):
            changed = copy.deepcopy(self.request)
            changed['numerics']['geometry_build']['reflectron']['cell_axial_mm'] = step
            with self.subTest(step=step), self.assertRaises(ValueError):
                validate_preparation_request(changed)
