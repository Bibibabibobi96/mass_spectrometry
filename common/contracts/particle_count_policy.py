"""Validate the repository-wide N=100/N=1000 particle-count policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
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


def _nonblank_lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _has_header(lines: list[str]) -> bool:
    sample = "\n".join(lines[: min(len(lines), 21)])
    try:
        return csv.Sniffer().has_header(sample)
    except csv.Error as error:
        raise ValueError("particle source header could not be classified") from error


def _validate_expected_sha256(
    path: Path, expected_sha256: str | None, label: str
) -> None:
    if expected_sha256 is None:
        return
    expected = expected_sha256.upper()
    if len(expected) != 64 or any(character not in "0123456789ABCDEF" for character in expected):
        raise ValueError(f"{label} expected SHA-256 is invalid")
    actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if actual != expected:
        raise ValueError(f"{label} SHA-256 differs from the expected identity")


def validate_prefix_particle_sources(
    n100_path: Path,
    n1000_path: Path,
    *,
    expected_n100_sha256: str | None = None,
    expected_n1000_sha256: str | None = None,
) -> None:
    """Require N=100 data rows to exactly prefix the N=1000 source."""
    _validate_expected_sha256(n100_path, expected_n100_sha256, "N=100 source")
    _validate_expected_sha256(n1000_path, expected_n1000_sha256, "N=1000 source")
    small = _nonblank_lines(n100_path)
    large = _nonblank_lines(n1000_path)
    small_has_header = _has_header(small)
    large_has_header = _has_header(large)
    if small_has_header != large_has_header:
        raise ValueError("prefix source validation does not allow mixed header formats")
    if small_has_header:
        if small[0] != large[0]:
            raise ValueError("prefix particle sources do not share the same header")
        small = small[1:]
        large = large[1:]
    policy = load_particle_count_policy()
    functional_count = int(policy["functional_check_count"])
    statistical_count = int(policy["statistical_count"])
    if len(small) != functional_count or len(large) != statistical_count:
        raise ValueError(
            "prefix source validation requires exactly "
            f"N={functional_count} and N={statistical_count} data rows"
        )
    if small != large[:functional_count]:
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
