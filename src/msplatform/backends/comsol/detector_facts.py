"""Validate the COMSOL particle stage's native detector evidence."""
from __future__ import annotations

import re
from typing import Any, Mapping


def validate_comsol_particle_facts(facts: Mapping[str, Any], plan: Mapping[str, Any], *, particle_count: int) -> str:
    """Apply the producer's exact native study, cohort, time and detector checks."""
    if not isinstance(facts, Mapping) or not isinstance(plan, Mapping) or type(particle_count) is not int or particle_count < 1:
        raise ValueError("COMSOL facts require an explicit nonempty particle cohort")
    version = facts.get("comsol_version")
    if (not isinstance(version, str) or not re.fullmatch(r"(?:COMSOL Multiphysics )?6\.4(?: \(Build: [0-9]+\))?", version)
            or facts.get("study_completed") is not True or type(facts.get("particle_count")) not in (int, float)
            or facts["particle_count"] != particle_count or "observation_times_us" not in plan
            or facts.get("stored_times_us") != plan["observation_times_us"]
            or facts.get("boundary_policy") != "metal_and_outer_freeze_ideal_pass"):
        raise ValueError("COMSOL native facts differ from the frozen plan or supported version")
    detector = plan.get("detector_active_face")
    detector_faces = facts.get("detector_faces")
    if detector is not None:
        if (facts.get("detector_observation_native") is not True
                or not isinstance(detector_faces, (int, list)) or isinstance(detector_faces, bool)):
            raise ValueError("native detector boundary evidence is missing")
        if isinstance(detector_faces, int):
            detector_faces = [detector_faces]
        if (not detector_faces or any(type(face) is not int or face <= 0 for face in detector_faces)
                or len(set(detector_faces)) != len(detector_faces)):
            raise ValueError("native detector boundary evidence is invalid")
    elif facts.get("detector_observation_native") not in (None, False):
        raise ValueError("native detector evidence has no frozen authored surface")
    return version
