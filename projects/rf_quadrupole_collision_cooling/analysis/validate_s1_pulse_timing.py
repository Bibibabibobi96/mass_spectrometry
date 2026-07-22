"""Validate the state-driven RF-to-oaTOF pulse timing policy."""

from derive_s1_centroid_pulse_time import validate_policy


if __name__ == "__main__":
    policy = validate_policy()
    print(f"S1_PULSE_TIMING_POLICY=PASS METHOD={policy['method']}")
