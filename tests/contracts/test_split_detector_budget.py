"""Split detector budget equals the existing SIMION PA-set forecast."""
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import unittest

from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import preflight_native


EXAMPLES = Path(__file__).resolve().parents[2]/'src/msplatform/examples'


class SplitDetectorBudgetTests(unittest.TestCase):
    def test_only_engineering_limit_and_study_digest_changed(self):
        previous = {'oa_split_tof_native_small_v1':'71ec596ce5f1535dcccf9eac6f8577ba17ccfe9b7674c3ab842f5d3ea5c5e348',
                    'rf_split_oatof_native_small_v1':'b060fb4454fc5cccffc463e8d8a014e4839b7950c7a6b1199b5394d3154626fb'}
        for stem, old_hash in previous.items():
            with self.subTest(stem=stem):
                actual=(EXAMPLES/(stem+'.json')).read_bytes()
                self.assertEqual(actual.count(b'"max_mib": 128.0'),1)
                prior=actual.replace(b'"max_mib": 128.0',b'"max_mib": 64.0')
                self.assertEqual(hashlib.sha256(prior).hexdigest(),old_hash)
                recipe=load_recipe(EXAMPLES/(stem+'.toml')).to_dict()
                self.assertEqual(recipe['study']['document']['numerics']['geometry']['geometry_build']['detector']['max_mib'],128.)

    def test_real_recipe_preflight_enforces_existing_lua_forecast(self):
        stem='oa_split_tof_native_small_v1'
        raw=(EXAMPLES/(stem+'.toml')).read_text(encoding='utf8')
        original=json.loads((EXAMPLES/(stem+'.json')).read_text(encoding='utf8'))
        estimate=165*165*126*8*3.25/1024**2
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for limit, accepted in ((64.,False),(math.nextafter(estimate,-math.inf),False),(estimate,True),(128.,True)):
                with self.subTest(limit=limit):
                    document=json.loads(json.dumps(original))
                    document['numerics']['geometry']['geometry_build']['detector']['max_mib']=limit
                    body=json.dumps(document,ensure_ascii=False).encode('utf8')
                    (root/(stem+'.json')).write_bytes(body)
                    author=root/(stem+'.toml')
                    author.write_text(re.sub(r'sha256 = "[a-fA-F0-9]{64}"',
                        'sha256 = "'+hashlib.sha256(body).hexdigest()+'"',raw),encoding='utf8')
                    if accepted:
                        self.assertTrue(preflight_native(load_recipe(author).to_dict())['implemented'])
                    else:
                        with self.assertRaisesRegex(ValueError,'estimated detector PA set'):
                            preflight_native(load_recipe(author).to_dict())


if __name__ == '__main__': unittest.main()
