"""Validate the repository-wide N=100/N=1000 particle-count policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).with_name("particle_count_policy.json")


def load_particle_count_policy() -> dict[str, Any]:
    """Load and validate the shared particle-trajectory count policy."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    standard = [int(value) for value in policy["standard_particle_counts"]]
    if standard != [100, 1000]:
        raise ValueError("standard particle counts must be exactly [100, 1000]")
    if int(policy["default_particle_count"]) != 100:
        raise ValueError("default particle count must be 100")
    if int(policy["functional_check_count"]) != 100:
        raise ValueError("functional check count must be 100")
    if int(policy["statistical_count"]) != 1000:
        raise ValueError("statistical count must be 1000")
    if policy.get("prefix_sampling_required") is not True:
        raise ValueError("N=100 must be the deterministic prefix of the N=1000 source")
    return policy


def validate_standard_particle_count(count: int) -> int:
    """Return *count* when it is a repository-standard trajectory size."""
    standard = load_particle_count_policy()["standard_particle_counts"]
    if count not in standard:
        raise ValueError(f"standard particle count must be one of {standard}; received {count}")
    return count


def validate_prefix_particle_sources(n100_path: Path, n1000_path: Path) -> None:
    """Require N=100 to equal the first 100 nonblank rows of N=1000."""
    small = [line for line in n100_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    large = [line for line in n1000_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(small) != 100 or len(large) != 1000:
        raise ValueError("prefix source validation requires exactly N=100 and N=1000")
    if small != large[:100]:
        raise ValueError("N=100 source is not the deterministic prefix of N=1000")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int)
    parser.add_argument("--prefix-n100", type=Path)
    parser.add_argument("--prefix-n1000", type=Path)
    args = parser.parse_args()
    if args.prefix_n100 or args.prefix_n1000:
        if not args.prefix_n100 or not args.prefix_n1000:
            parser.error("prefix validation requires --prefix-n100 and --prefix-n1000")
        validate_prefix_particle_sources(args.prefix_n100, args.prefix_n1000)
        print("PARTICLE_COUNT_PREFIX=PASS N100_PREFIX_OF_N1000=true")
    elif args.count is not None:
        validate_standard_particle_count(args.count)
        print(f"PARTICLE_COUNT_POLICY=PASS COUNT={args.count}")
    else:
        parser.error("provide --count or both prefix source paths")


if __name__ == "__main__":
    main()
