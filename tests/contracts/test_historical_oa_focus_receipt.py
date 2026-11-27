"""Exact read-only decoding of a v1 OA-to-MR historical receipt."""
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.io.manifest_records import file_record
from msplatform.workflows.historical_oa_focus_receipt import read_historical_oa_mr_receipt


class HistoricalOaReceiptTests(unittest.TestCase):
    def test_success_only_and_tamper_rejection_preserve_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'historic';(root/'results').mkdir(parents=True)
            receipt=root/'results/mrtof_runtime_receipt.json'
            original=dict(schema_version=1,role='orthogonal_accelerator_mrtof_runtime_receipt',
                status='published_standalone_response_bank',qualification='old_candidate',mrtof_projection={'voltage':1.})
            receipt.write_text(json.dumps(original),encoding='utf8')
            config=root/'run_config.json';config.write_text(json.dumps(dict(run_id=root.name,
                project='orthogonal_accelerator',mode='component_focus_workflow',inputs={})),encoding='utf8')
            manifest=root/'run_manifest.json';value=dict(schema_version=2,role='simulation_run_manifest',status='success',
                run_id=root.name,project='orthogonal_accelerator',mode='component_focus_workflow',run_config=file_record(config),
                inputs={},outputs=[file_record(receipt)])
            manifest.write_text(json.dumps(value),encoding='utf8')
            before={p:p.read_bytes() for p in (receipt,config,manifest)}
            result=read_historical_oa_mr_receipt(source_manifest=manifest)
            self.assertEqual(result['original_receipt'],original)
            self.assertEqual(result['interpretation'],'historical_only_referenced_payloads_not_verified')
            self.assertEqual(before,{p:p.read_bytes() for p in before})
            receipt.write_text('{}',encoding='utf8')
            with self.assertRaises((ValueError,OSError)):
                read_historical_oa_mr_receipt(source_manifest=manifest)
            receipt.write_bytes(before[receipt]);value['status']='failed';manifest.write_text(json.dumps(value),encoding='utf8')
            with self.assertRaises(ValueError):read_historical_oa_mr_receipt(source_manifest=manifest)
