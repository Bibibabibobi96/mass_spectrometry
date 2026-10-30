from __future__ import annotations

import unittest

from projects.rf_multipole_ion_optics.analysis.analyze_comsol_transport_metrics import derive


class AnalyzeComsolTransportMetricsTests(unittest.TestCase):
    def test_derives_case_metrics_from_canonical_state_and_event_rows(self) -> None:
        state = [
            {"particle_id": "1", "event": "source", "status": "alive", "radial_position_mm": "0", "kinetic_energy_eV": "2", "max_rod_radius_mm": "1"},
            {"particle_id": "1", "event": "terminal", "status": "transmitted", "radial_position_mm": "3", "kinetic_energy_eV": "5", "max_rod_radius_mm": "1"},
        ]
        events = [{"case_id": case, "particle_id": "1", "entrance_port_radius_mm": "1", "exit_port_radius_mm": "1"} for case in ("finite_3d_rf_on", "zero_rf_control")]
        resolved = {"identity": {"project_id":"fixture"}, "axial_drive":{"topology":"none"}, "drive":{},"geometry_mm":{"rod_radius_ratio":1,"rod_radius":2,"rod_center_radius":3,"enclosure":{"model":"bare"},"observations":{"release_plane_z_mm":0,"census_plane_z_mm":1},"enclosure_layout":{"ports":{name:{"cross_section":{"shape":"open_rod_envelope","inscribed_radius_mm":1}} for name in ("mechanical_entrance","mechanical_exit")}}}}
        numerics = {"mesh": {"global_auto_level": 3, "working_region_maximum_element_size_mm": 0.5}}
        result = derive(events, state, state, resolved, numerics)
        self.assertEqual(result["metrics_authority"], "python_canonical_particle_state_and_events")
        self.assertEqual(result["cases"]["finite_3d_rf_on"]["transmission_fraction"], 1.0)
        self.assertEqual(result["cases"]["finite_3d_rf_on"]["exit_rms_radius_mm"], 3.0)

    def test_unknown_lifecycle_and_acceptance_rejection_are_independent_axes(self):
        state, events, resolved, numerics = scenario([
            (17, "transmitted", "acceptance_surface", "accepted", "none"),
            (91, "unknown", "time_window_end", "rejected", "usable_radius_exceeded"),
            (103, "unknown", "ended_without_loss_evidence", "unresolved", "none"),
        ])
        result = derive(events, state, state, resolved, numerics)["cases"]["finite_3d_rf_on"]
        self.assertEqual(result["cohort_census"]["mother_particle_ids"], [17, 91, 103])
        self.assertEqual(result["cohort_census"]["counts"], dict(transmitted=1, lost=0, unknown=2))
        self.assertEqual(result["unknown_terminal_reason_ids"]["time_window_end"], [91])
        self.assertEqual(result["acceptance"]["rejected_particle_ids"], [91])
        self.assertEqual(result["acceptance"]["rejection_reasons"], dict(usable_radius_exceeded=[91]))
        self.assertAlmostEqual(result["transmission_fraction"], 1/3)
        self.assertFalse(result["terminal_fates_resolved"])
        self.assertEqual(result["weight_metrics"]["status"], "not_computable")
        self.assertNotIn("weight_sums", result["cohort_census"])

    def test_legacy_unrecorded_acceptance_does_not_fabricate_reason(self):
        state, events, resolved, numerics = scenario([
            (17, "unknown", None, None, None),
            (91, "lost", "electrode", None, None),
        ])
        result = derive(events, state, state, resolved, numerics)["cases"]["finite_3d_rf_on"]
        self.assertFalse(result["acceptance"]["recorded"])
        self.assertIsNone(result["acceptance"]["rejection_reasons"])
        self.assertEqual(result["unknown_terminal_reason_unrecorded_ids"], [17])
        self.assertEqual(result["unknown_terminal_reason_ids"], dict(loss_evidence_unavailable=[91]))
        self.assertEqual(result["cohort_census"]["counts"], dict(transmitted=0, lost=0, unknown=2))
        self.assertEqual(result["loss_evidence"]["status"], "unavailable")
        self.assertEqual(result["loss_evidence"]["reported_lost_particle_ids"], [91])
        self.assertEqual(result["reported_terminal_facts"]["91"], dict(status="lost", terminal_reason="electrode"))

    def test_duplicate_terminal_and_incomplete_cohort_fail(self):
        for fault, expected in (("duplicate", "duplicate classification"), ("missing", "does not close")):
            with self.subTest(fault=fault):
                state, events, resolved, numerics = scenario([(17, "unknown", "time_window_end", "unresolved", "none")])
                if fault == "duplicate":
                    state.append(dict(state[-1]))
                else:
                    state.pop()
                with self.assertRaisesRegex(ValueError, expected):
                    derive(events, state, state, resolved, numerics)

    def test_partial_or_contradictory_acceptance_fails(self):
        for fault, expected in (("partial", "partial acceptance"), ("contradiction", "contradict"),
                                ("reason", "invalid acceptance"), ("status", "unsupported terminal")):
            with self.subTest(fault=fault):
                state, events, resolved, numerics = scenario([(17, "unknown", "time_window_end", "rejected", "usable_radius_exceeded")])
                if fault == "partial":
                    del state[-1]["acceptance_reason"]
                elif fault == "contradiction":
                    state[-1]["acceptance_status"] = "accepted"
                elif fault == "reason":
                    state[-1]["acceptance_reason"] = "none"
                else:
                    state[-1]["status"] = "bad"
                with self.assertRaisesRegex(ValueError, expected):
                    derive(events, state, state, resolved, numerics)





def scenario(terminals):
    state = []
    for pid, status, reason, acceptance, rejection in terminals:
        base = dict(particle_id=str(pid), radial_position_mm="1", kinetic_energy_eV="2", max_rod_radius_mm="1")
        state.append(dict(base, event="source", status="alive"))
        row = dict(base, event="terminal", status=status)
        if reason is not None:
            row["terminal_reason"] = reason
        if acceptance is not None:
            row.update(acceptance_status=acceptance, acceptance_reason=rejection)
        state.append(row)
    events = [dict(case_id=case, particle_id=str(pid), entrance_port_radius_mm="1", exit_port_radius_mm="1")
              for case in ("finite_3d_rf_on", "zero_rf_control") for pid, *_ in terminals]
    resolved = dict(identity=dict(project_id="fixture"), axial_drive=dict(topology="none"), drive={},
                    geometry_mm=dict(rod_radius_ratio=1, rod_radius=2, rod_center_radius=3,
                                     enclosure=dict(model="bare"), observations=dict(release_plane_z_mm=0, census_plane_z_mm=1),
                                     enclosure_layout=dict(ports={name: dict(cross_section=dict(shape="open_rod_envelope", inscribed_radius_mm=1))
                                                                 for name in ("mechanical_entrance", "mechanical_exit")})))
    return state, events, resolved, dict(mesh=dict(global_auto_level=9, working_region_maximum_element_size_mm=2))


if __name__ == "__main__":
    unittest.main()
