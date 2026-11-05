"""Canonical birth authoring preserves the real sampler and released cohort."""
import copy
import math
import unittest
from unittest.mock import patch

from msplatform.contracts.clock import ClockIdentity
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.ion_release.authoring import author_release
from msplatform.ion_release.release import generate_release_states
from common.ion_release.test_mt19937_disk_cone_rf_phase import _spec
from common.ion_release.test_cylinder import halton_spec


class ReleaseAuthoringTests(unittest.TestCase):
    def author(self, spec, **changes):
        args = dict(clock=ClockIdentity("instrument", "a"*64), instrument_origin_us=12.5,
                    species_id="test_ion", source_component_id="rf", relative_weights=None)
        args.update(changes)
        return author_release(spec, **args)

    def test_sparse_births_preserve_actual_rows_weights_clock_and_full_real_mother(self):
        spec = _spec(3)
        before = copy.deepcopy(spec)
        raw = generate_release_states(spec)
        ids = [11, 1009, 2**60+1]
        weights = {11:.5, 1009:2., 2**60+1:3.}
        with patch("msplatform.ion_release.authoring.generate_release_states", wraps=generate_release_states) as sample:
            result = self.author(spec, particle_ids=ids, relative_weights=weights)
        sample.assert_called_once()
        self.assertEqual(spec, before)
        self.assertEqual(result["realization"]["generator_rows"], raw)
        self.assertEqual(result["realization"]["spec"], before)
        self.assertEqual(list(result["mother"]["records"]), ids)
        self.assertEqual(len(result["mother"]["fates"]), 3)
        self.assertEqual(spec["mother_particle_count"], 5000)
        for ordinal, (row, original) in enumerate(zip(result["rows"], raw, strict=True), 1):
            birth = 12.5 + original["birth_time_s"]*1e6
            self.assertEqual(row["instrument_time_us"], birth)
            self.assertEqual(row["particle_birth_time_us"], birth)
            self.assertEqual(row["lineage_birth_time_us"], birth)
            self.assertEqual((row["particle_age_us"],row["lineage_age_us"],row["last_component_elapsed_time_us"]),(0.,0.,0.))
            self.assertEqual(row["particle_weight"], weights[row["particle_id"]])
            self.assertIsNone(row["phase_rad"])
            self.assertIsNone(row["phase_reference_id"])
            self.assertEqual(result["realization"]["source_id_map"][ordinal-1],dict(ordinal=ordinal,generator_particle_id=original["particle_id"],particle_id=ids[ordinal-1]))
            for axis in "xyz":
                self.assertEqual(row[f"position_{axis}_mm"],original[f"{axis}_mm"])
                self.assertEqual(row[f"velocity_{axis}_m_s"],original[f"v{axis}_m_s"])
            energy=.5*original["mass_amu"]*1.66053906660e-27*sum(original[f"v{axis}_m_s"]**2 for axis in "xyz")/1.602176634e-19
            self.assertTrue(math.isclose(row["kinetic_energy_eV"],energy,rel_tol=2e-15))
        self.assertEqual(len({r["particle_birth_time_us"] for r in result["rows"]}),3)
        validate_component_particle_state_rows(result["rows"])
        result["rows"][0]["particle_weight"]=99
        self.assertEqual(result["mother"]["records"][11]["particle_weight"],.5)
        spec["sampling"]["seed"]=0
        self.assertEqual(result["realization"]["spec"],before)

    def test_actual_authored_birth_mother_feeds_plane_handoff_without_resetting_entry(self):
        from msplatform.assembly.handoff import HandoffClock, HandoffMother
        from msplatform.backends.simion.source import prepare_plane_handoff_states
        from msplatform.contracts.rigid_transform import RigidTransform
        authored=self.author(_spec(2),particle_ids=[11,1009],relative_weights={11:.5,1009:2.})
        mother=HandoffMother(**authored['mother'])
        observations=dict(schema_version=1,role='single_reflection_plane_observations',status='complete',
            definitions=[dict(observation_id='rf_exit',source_instance_id='rf')],rows=[])
        for row,delay in zip(authored['rows'],(3.,7.),strict=True):
            self.assertEqual(mother.records[row['particle_id']]['source_component_entry_time_us'],row['particle_birth_time_us'])
            observations['rows'].append(dict(particle_id=row['particle_id'],observation_id='rf_exit',direction='outward',occurrence=1,
                instrument_time_us=row['particle_birth_time_us']+delay,method='accepted_step_linear_interpolation',
                **{a+'_mm':row['position_'+a+'_mm'] for a in 'xyz'},
                **{'v'+a+'_mm_per_us':row['velocity_'+a+'_m_s']/1000 for a in 'xyz'}))
        clock=ClockIdentity(**authored['clock'])
        frame=authored['rows'][0]['frame_id']
        result=prepare_plane_handoff_states(observations,observation_id='rf_exit',direction='outward',occurrence=1,
            source_instance_id='rf',target_instance_id='oa',frame_id=frame,
            transform=RigidTransform(frame,frame,((1,0,0),(0,1,0),(0,0,1)),(0,0,0)),
            clock=HandoffClock(clock,clock),mother=mother,producer_completed=True)
        self.assertEqual([r['particle_id'] for r in result.rows],[11,1009])
        for row,original,delay in zip(result.rows,authored['rows'],(3.,7.),strict=True):
            self.assertEqual(row['particle_birth_time_us'],original['particle_birth_time_us'])
            self.assertEqual(row['instrument_time_us'],original['particle_birth_time_us']+delay)
            self.assertAlmostEqual(row['particle_age_us'],delay,places=13)
            self.assertAlmostEqual(row['last_component_elapsed_time_us'],delay,places=13)
            self.assertEqual(row['particle_weight'],original['particle_weight'])
        # Later entry is explicit, never inferred from arrival or original birth.
        changed=copy.deepcopy(authored['mother']);changed['records'][11]['source_component_entry_time_us']+=1
        later=prepare_plane_handoff_states(observations,observation_id='rf_exit',direction='outward',occurrence=1,
            source_instance_id='rf',target_instance_id='oa',frame_id=frame,
            transform=RigidTransform(frame,frame,((1,0,0),(0,1,0),(0,0,1)),(0,0,0)),
            clock=HandoffClock(clock,clock),mother=HandoffMother(**changed),producer_completed=True)
        self.assertAlmostEqual(later.rows[0]['last_component_elapsed_time_us'],2.,places=13)
        self.assertEqual(later.rows[0]['particle_birth_time_us'],result.rows[0]['particle_birth_time_us'])

    def test_default_ids_and_existing_family_prefix_remain_exact(self):
        for make in (_spec, halton_spec):
            small, large = make(3), make(5)
            a,b=self.author(small),self.author(large)
            self.assertEqual(a["rows"],b["rows"][:3])
            self.assertEqual([r["particle_id"] for r in a["rows"]],[1,2,3])
            self.assertEqual(a["realization"]["generator_rows"],generate_release_states(small))
            self.assertEqual(len(a["mother"]["records"]),3)
            self.assertTrue(all(r["particle_weight"]==1 for r in a["rows"]))

    def test_invalid_author_identity_weights_clock_and_schema_fail(self):
        for ids in ([],[1,1,3],[True,2,3],[1.,2,3],[0,2,3],[1,2]):
            with self.subTest(ids=ids),self.assertRaises(ValueError): self.author(_spec(3),particle_ids=ids)
        for weights in ({},{1:1,2:1},{1:1,2:1,3:0},{1:1,2:1,3:float("nan")},{1:True,2:1,3:1},{True:1,2:1,3:1}):
            with self.subTest(weights=weights),self.assertRaises(ValueError): self.author(_spec(3),relative_weights=weights)
        for changes in (dict(clock=None),dict(instrument_origin_us=float("inf")),dict(instrument_origin_us=True),dict(species_id=""),dict(source_component_id="bad space")):
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.author(_spec(3),**changes)
        for changes in (dict(particle_count=0),dict(schema_version=99),dict(role="existing_handoff")):
            spec=_spec(3);spec.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.author(spec)
        with patch("msplatform.ion_release.authoring.generate_release_states",return_value=[]),self.assertRaises(ValueError): self.author(_spec(3))

    def test_snapshot_is_not_silently_reclassified_as_birth(self):
        with patch("msplatform.ion_release.authoring.generate_release_states") as sample:
            with self.assertRaisesRegex(ValueError,"snapshot"):
                self.author(dict(role="continuous_axial_volume_ion_beam_source"))
        sample.assert_not_called()


if __name__ == "__main__":
    unittest.main()
