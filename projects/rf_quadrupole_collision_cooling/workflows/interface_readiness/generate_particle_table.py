"""Generate or validate the governed interface-readiness particle-source bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.particle_source_policy import (
    generate_interface_bundle,
    validate_interface_bundle,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-family", type=Path, required=True)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--resolved-design", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--bundle-output-dir", type=Path)
    action.add_argument("--validate-bundle", type=Path)
    args = parser.parse_args()
    if args.validate_bundle is not None:
        if args.seed is not None:
            raise ValueError("bundle validation does not accept --seed")
        validate_interface_bundle(
            args.validate_bundle,
            args.source_family,
            args.distribution,
            args.resolved_design,
        )
        print("STATUS=PASS BUNDLE_VALIDATION=true")
        return
    metadata = generate_interface_bundle(
        args.source_family,
        args.distribution,
        args.resolved_design,
        args.bundle_output_dir,
        seed=args.seed,
    )
    print(
        "STATUS=PASS "
        f"PARTICLES={metadata['policy']['statistical_count']} "
        f"SAMPLE_FAMILY_SHA256={metadata['sample_family_sha256']}"
    )


if __name__ == "__main__":
    main()
