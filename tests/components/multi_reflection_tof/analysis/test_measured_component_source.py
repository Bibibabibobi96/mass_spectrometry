"""Pure source projection tests; no SIMION process or external artifact needed."""
from __future__ import annotations

import copy
import math
import unittest

from msplatform.io.strict_json import StrictJsonError
from msplatform.workflows.mr_design.measured_component_source import author_measured_centroid_prism_target


class MeasuredCentroidTargetTests(unittest.TestCase):
    @staticmethod
    def evidence():
        from msplatform.contracts.particle_physics import speed_m_s_from_kinetic_energy_ev, kinetic_energy_ev
        from tests.components.multi_reflection_tof.analysis.test_dual_stripe_l0_math import converging_prism_fixture
        contract, _, reference = converging_prism_fixture()
        record = lambda name: dict(path="C:/synthetic-unit-evidence/"+name+".json",bytes=1,sha256="ab"*32)
        records={name:record(name) for name in ("event_field_audit","audit_request","controller_projection",
                                               "source_receipt","trajectory_contract","design_target")}
        canonical, binding=record("canonical"),record("binding")
        mass,charge=524.,1
        h=4364.5339559932+5.
        def point(name,event,time,position,axes,phi):
            velocity=[speed_m_s_from_kinetic_energy_ev(mass,e) for e in axes]
            velocity[2]*=-1
            kinetic=kinetic_energy_ev(mass,*velocity)
            query=dict(sample_id=name,event=event,instrument_time_us=time,position_mm=position,
                       velocity_m_s=velocity,kinetic_energy_per_charge_ev=kinetic)
            return query,dict(query,phi_v=phi,k_over_q_plus_phi_v=kinetic+phi)
        birth,birth_row=point("source_centroid","source_centroid",100.,[.01,-55.,0.],[2.,.1,4364.5339559932-2.1],5.)
        clean,clean_row=point("event_000001","central_plane_directional",101.,[.03,9.29765627041,0.],
                              [3.,2.,h-11.-3.-2.],11.)
        source=dict(role="mrtof_measured_exit_centroid_probe_source",counts=dict(source=1,transferred=1,not_transferred=0),
            mass_amu=mass,charge_state=charge,centroid_kinetic_energy_eV=birth["kinetic_energy_per_charge_ev"],
            mean_particle_kinetic_energy_eV=4364.822522004543,solver_epoch_instrument_time_us=100.,
            outputs=dict(component_particle_state=canonical))
        request=dict(schema_version=1,role="mrtof_actual_probe_event_field_audit_request",mass_amu=mass,charge_state=charge,
            inputs=dict(source_receipt=records["source_receipt"],canonical_source=canonical,projection=records["controller_projection"],candidate_binding=binding),
            points=[birth,clean])
        audit=dict(schema_version=1,role="mrtof_actual_probe_event_energy_field_audit",status="reported",
            potential_authority="actual_materialized_scalar_native_PA__scalar_adapter_raw_sample",
            inputs=dict(request=records["audit_request"]),samples=[birth_row,clean_row],source_centroid_h_over_q_v=h)
        values=[0.]*20;values[10:12]=[-27.36410265968425]*2
        projection=dict(role="mrtof_measured_exit_centroid_controller_projection",inputs=dict(source_receipt=records["source_receipt"]),field_authority_projection=dict(
            role="mrtof_measured_centroid_live_field_projection",binding_record=binding,analyzer_electrode_voltages_v=values))
        design=dict(schema_version=1,role="mrtof_measured_centroid_closure_target_authority",prism_handoff_target=reference,
            inputs=dict(interface_energy_field_audit=record("old-audit"),trajectory_contract=records["trajectory_contract"],mother_source_receipt=record("mother")),
            target_slow_turn_y_mm=360.,target_k=24.5,target_positive_mirror_turn_y_mm=0.,target_low_field_tangent_ratio_vy_over_vz=.03506096645)
        return dict(event_field_audit=audit,audit_request=request,controller_projection=projection,source_receipt=source,
                    trajectory_contract=contract,design_target=design,stripe_1_voltage_v=values[10],input_records=records)

    def test_partition_uses_actual_phi_and_ex_not_unclosed_ky_or_oa_energy(self):
        from msplatform.components.multi_reflection_tof.dual_stripe_l0 import converging_design_potential_delta_v
        evidence=self.evidence();before=copy.deepcopy(evidence)
        result=author_measured_centroid_prism_target(**evidence)
        target=result["target_authority"];model=target["prism_handoff_target"];ledger=result["authoring_ledger"]
        self.assertEqual(evidence,before)
        self.assertAlmostEqual(ledger["source_h_over_q_v"],4369.5339559932)
        self.assertAlmostEqual(ledger["available_clean_yz_energy_ev_per_q"],4355.5339559932)
        self.assertNotEqual(model["axial_energy_per_charge_v"],before["design_target"]["prism_handoff_target"]["axial_energy_per_charge_v"])
        self.assertNotEqual(model["axial_energy_per_charge_v"],ledger["source_h_over_q_v"])
        self.assertNotAlmostEqual(model["clean_reference_slow_energy_per_charge_v"],2.)
        self.assertAlmostEqual(model["axial_energy_per_charge_v"]+model["clean_reference_slow_energy_per_charge_v"],4355.5339559932)
        psi=converging_design_potential_delta_v(model,evidence["stripe_1_voltage_v"],9.29765627041)
        self.assertAlmostEqual(model["clean_reference_slow_energy_per_charge_v"]+psi,model["slow_energy_reference_per_charge_v"],places=9)
        self.assertEqual(target["source_energy_ledger"]["mean_particle_kinetic_energy_ev_per_q"],4364.822522004543)
        self.assertEqual((target["target_slow_turn_y_mm"],target["target_k"]),(360.,24.5))
        self.assertEqual(model["angle_tolerance_degrees"],.01)
        self.assertNotEqual(model["energy_tolerance_per_charge_v"],before["design_target"]["prism_handoff_target"]["energy_tolerance_per_charge_v"])
        angle=math.asin(math.sqrt(model["clean_reference_slow_energy_per_charge_v"]/model["total_energy_reference_per_charge_v"]))
        self.assertAlmostEqual(ledger["clean_target_angle_degrees"],math.degrees(angle))
        self.assertFalse(result["physical_matching_qualified"])

    def test_numeric_representation_is_checked_before_target_physics(self):
        for value in (True, "-27.36410265968425", None, math.inf, 10**1000):
            evidence = self.evidence()
            evidence["stripe_1_voltage_v"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(StrictJsonError):
                author_measured_centroid_prism_target(**evidence)

    def test_invalid_or_incomplete_actual_ledger_fails_closed(self):
        for scenario in ("nan_phi","missing_phi","missing_ex_state","charge","wrong_binding","wrong_source","bad_K","bad_H","no_clean","no_partition","bad_geometry"):
            with self.subTest(scenario=scenario):
                evidence=self.evidence();audit=evidence["event_field_audit"]
                if scenario=="nan_phi": audit["samples"][1]["phi_v"]=math.nan
                elif scenario=="missing_phi": del audit["samples"][1]["phi_v"]
                elif scenario=="missing_ex_state": audit["samples"][1]["velocity_m_s"]=audit["samples"][1]["velocity_m_s"][1:]
                elif scenario=="charge": evidence["source_receipt"]["charge_state"]=0
                elif scenario=="wrong_binding": evidence["controller_projection"]["field_authority_projection"]["binding_record"]=dict(bytes=1,sha256="cd"*32)
                elif scenario=="wrong_source": evidence["source_receipt"]["outputs"]["component_particle_state"]=dict(bytes=2,sha256="cd"*32)
                elif scenario=="bad_K": audit["samples"][0]["kinetic_energy_per_charge_ev"]+=1
                elif scenario=="bad_H": audit["samples"][1]["k_over_q_plus_phi_v"]+=1
                elif scenario=="no_clean": audit["samples"][1]["event"]="other"
                elif scenario=="no_partition": evidence["design_target"]["prism_handoff_target"]["slow_energy_reference_per_charge_v"]=10000.
                else: evidence["design_target"]["prism_handoff_target"]["single_mirror_angle_degrees"]*=2
                with self.assertRaises(ValueError):
                    author_measured_centroid_prism_target(**evidence)
