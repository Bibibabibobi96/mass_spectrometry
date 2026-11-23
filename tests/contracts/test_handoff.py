"""Independent transfer arithmetic and original-mother/authority boundaries."""
from __future__ import annotations

import copy
import unittest

from msplatform.assembly.handoff import (
    HandoffClock, HandoffMother, HandoffSelection, prepare_handoff_states,
)
from msplatform.contracts.clock import ClockIdentity, age_us, instrument_time_us, seconds_to_microseconds
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.contracts.rigid_transform import RigidTransform


def state(pid=7, birth=5., time=12.5, weight=2.):
    return dict(particle_id=pid, parent_particle_id=None, generation=0, species_id="ion100",
        particle_weight=weight, source_component_id="a", target_component_id="b", state_event="mechanical_exit",
        frame_id="source", clock_epoch_id="epoch", instrument_time_us=time, lineage_age_us=time-birth,
        particle_age_us=time-birth, last_component_elapsed_time_us=2., lineage_birth_time_us=birth,
        particle_birth_time_us=birth, mass_amu=100., charge_state=1, mass_to_charge_Th=100.,
        kinetic_energy_eV=.5*100.*1.66053906660e-27*(1000.**2+2000.**2+3000.**2)/1.602176634e-19,
        position_x_mm=1., position_y_mm=-2., position_z_mm=3.,
        velocity_x_m_s=1000., velocity_y_m_s=-2000., velocity_z_m_s=3000.,
        phase_reference_id="rf", phase_rad=1.2)


def mother(rows):
    keys = ("species_id", "mass_amu", "charge_state", "particle_weight", "particle_birth_time_us")
    return HandoffMother({r["particle_id"]: {k:r[k] for k in keys} for r in rows},
        ({"particle_id":99, "terminal_reason":"unknown", "particle_weight":3.},
         {"particle_id":7, "terminal_reason":"unknown", "particle_weight":2.}))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.rows = [state(), state(99, birth=8., weight=3.)]
        self.mother = mother(self.rows)
        identity = ClockIdentity("epoch", "A"*64)
        self.clock = HandoffClock(identity, identity)
        self.pose = RigidTransform("source", "target", ((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)), (10.,20.,30.))

    def run_handoff(self, *, rows=None, selection=None, mother=None, clock=None):
        return prepare_handoff_states(self.rows if rows is None else rows, transform=self.pose,
            clock=self.clock if clock is None else clock,
            selection=HandoffSelection("plane_crossing", (7,)) if selection is None else selection,
            mother=self.mother if mother is None else mother)

    def test_rotation_translation_sparse_identity_original_birth_and_full_mother(self):
        before = copy.deepcopy((self.rows, self.mother))
        result = self.run_handoff()
        row = result.rows[0]
        self.assertEqual([row[f"position_{a}_mm"] for a in "xyz"], [12.,21.,33.])
        self.assertEqual([row[f"velocity_{a}_m_s"] for a in "xyz"], [2000.,1000.,3000.])
        self.assertEqual(row["frame_id"], "target")
        self.assertEqual((row["instrument_time_us"],row["particle_birth_time_us"],row["particle_age_us"],
                          row["last_component_elapsed_time_us"]), (12.5,5.,7.5,2.))
        self.assertEqual((row["phase_reference_id"],row["phase_rad"]), ("rf",1.2))
        self.assertEqual(row["kinetic_energy_eV"], self.rows[0]["kinetic_energy_eV"])
        self.assertEqual(result.selected_particle_ids, (7,))
        self.assertEqual(result.untransferred_particle_ids, (99,))
        self.assertEqual(sum(r["particle_weight"] for r in result.mother.records.values()), 5.)
        self.assertEqual(result.mother.fates[0]["terminal_reason"], "unknown")
        self.assertEqual((self.rows,self.mother), before)
        result.rows[0]["particle_weight"] = 88.
        self.assertEqual(self.rows[0]["particle_weight"], 2.)

    def test_snapshot_is_volume_not_plane_and_retains_explicit_order(self):
        result = self.run_handoff(selection=HandoffSelection("time_snapshot", (99,7), 12.5))
        self.assertEqual([r["particle_id"] for r in result.rows], [99,7])
        self.assertEqual([r["particle_birth_time_us"] for r in result.rows], [8.,5.])
        self.assertEqual([r["particle_age_us"] for r in result.rows], [4.5,7.5])

    def test_zero_transfer_retains_unknown_without_empty_canonical_csv(self):
        result = self.run_handoff(rows=[], selection=HandoffSelection("plane_crossing", ()))
        self.assertEqual(result.rows, ())
        self.assertEqual(result.untransferred_particle_ids, (7,99))
        self.assertEqual(result.mother, self.mother)
        with self.assertRaisesRegex(ValueError, "at least one"):
            validate_component_particle_state_rows([])

    def test_wrong_authority_epoch_and_unknown_clock_reject(self):
        for target in (ClockIdentity("epoch","B"*64), ClockIdentity("other","A"*64)):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "authority"):
                self.run_handoff(clock=HandoffClock(self.clock.source,target))
        for args in (("","A"*64),("epoch",""),("epoch","unknown")):
            with self.subTest(args=args), self.assertRaises(ValueError): ClockIdentity(*args)

    def test_missing_duplicate_unknown_selection_and_wrong_snapshot_reject(self):
        for selection in (HandoffSelection("plane_crossing",(7,7)), HandoffSelection("plane_crossing",(8,)),
                          HandoffSelection("time_snapshot",(7,),13.), HandoffSelection("checkpoint",(7,)),
                          HandoffSelection("plane_crossing",(7,),12.5)):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.run_handoff(selection=selection)
        with self.assertRaises(ValueError): self.run_handoff(rows=[self.rows[0],self.rows[0]])
        with self.assertRaises(ValueError): self.run_handoff(rows=[])

    def test_birth_species_weight_and_invalid_typed_rows_cannot_be_reshaped(self):
        for field,value in (("particle_birth_time_us",4.),("particle_weight",4.),("species_id","other")):
            changed = copy.deepcopy(self.mother.records); changed[7][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_handoff(mother=HandoffMother(changed,self.mother.fates))
        for field,value in (("velocity_x_m_s",float("nan")),("particle_weight",float("inf")),
                            ("parent_particle_id",7),("particle_age_us",8.),("frame_id","wrong")):
            changed = copy.deepcopy(self.rows);changed[0][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.run_handoff(rows=changed)

    def test_full_fates_and_existing_lineage_are_not_rebuilt_from_survivors(self):
        for fates in (self.mother.fates[:1], (*self.mother.fates,self.mother.fates[0]),
                      ({"particle_id":8,"terminal_reason":"unknown"},)):
            with self.subTest(fates=fates), self.assertRaises(ValueError):
                self.run_handoff(mother=HandoffMother(self.mother.records,fates))
        rows = copy.deepcopy(self.rows)
        rows[0].update(parent_particle_id=3, generation=1, lineage_birth_time_us=2., lineage_age_us=10.5)
        row = self.run_handoff(rows=rows).rows[0]
        self.assertEqual((row["parent_particle_id"],row["generation"],row["lineage_birth_time_us"],
                          row["lineage_age_us"],row["particle_birth_time_us"]), (3,1,2.,10.5,5.))


class ClockArithmeticTests(unittest.TestCase):
    def test_nonzero_anchor_and_independent_arrival_birth(self):
        self.assertEqual(instrument_time_us(43.,instrument_origin_us=100.,native_origin_us=40.),103.)
        self.assertEqual(instrument_time_us(39.,instrument_origin_us=100.,native_origin_us=40.),99.)
        self.assertEqual(seconds_to_microseconds(5e-6), 5.)
        self.assertEqual(age_us(103.,birth_time_us=5.),98.)
        for value in (True,float("nan"),float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                instrument_time_us(value,instrument_origin_us=0.,native_origin_us=0.)
        with self.assertRaises(ValueError): age_us(4.,birth_time_us=5.)


if __name__ == "__main__":
    unittest.main()
