"""Public native recipe with its one real OA focus campaign author."""
import tempfile
import unittest
from pathlib import Path
from msplatform.recipes import load_recipe
from msplatform.particle_release.authoring import sample_release
from tests.contracts.test_support.oa_focus_study import make_focus_recipe

class FocusStudyAuthorTests(unittest.TestCase):
    def test_one_frozen_campaign_supplies_real_model_and_one_birth(self):
        with tempfile.TemporaryDirectory() as directory:
            author,study,projection=make_focus_recipe(Path(directory))
            resolved=load_recipe(author).to_dict()
            actual=resolved['study']['document']['release']
            self.assertEqual(actual['role'],'canonical_birth_source_request')
            self.assertEqual(actual['release_spec'],projection['release_spec'])
            packet=sample_release(actual).to_dict()
            self.assertEqual(len(packet['rows']),100)
            self.assertEqual(packet['realization']['spec']['mother_particle_count'],1000)
            self.assertEqual(study['numerics']['tracing']['end_policy'],{'maximum_particle_age_us':50.})
            campaign=Path(directory)/'focus_campaign.json'
            campaign.write_text('{}',encoding='utf8')
            self.assertEqual(sample_release(actual).to_dict()['realization']['generator_rows'],
                             packet['realization']['generator_rows'])
            with self.assertRaisesRegex(ValueError,'campaign differs'):
                load_recipe(author)


    def test_signed_focus_authors_keep_explicit_species(self):
        from tests.contracts.test_support.oa_focus_study import make_signed_focus_recipe
        for kind in ('negative_ion','electron'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                author,_,_=make_signed_focus_recipe(Path(directory),species_kind=kind)
                if kind=='electron':
                    with self.assertRaisesRegex(ValueError,'electron tracing is not yet validated'):
                        load_recipe(author)
                    continue
                release=load_recipe(author).to_dict()['study']['document']['release']
                packet=sample_release(release).to_dict()
                self.assertEqual(len(packet['rows']),100)
                self.assertTrue(all(row['species_id']==kind and row['charge_state']==-1 for row in packet['rows']))
