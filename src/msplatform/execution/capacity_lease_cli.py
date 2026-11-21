"""Create or delete one explicit artifact-capacity protection lease."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from msplatform.execution.capacity_protection import (
    create_capacity_protection_lease,
    delete_capacity_protection_lease,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--create-protection-lease")
    actions.add_argument("--delete-protection-lease")
    parser.add_argument("--lease-owner")
    parser.add_argument("--lease-ttl-seconds", type=int)
    parser.add_argument("--committed-new-bytes", type=int)
    parser.add_argument("--protect-path", action="append", type=Path, default=[])
    parser.add_argument("--protect-cache-key", action="append", default=[])
    arguments = parser.parse_args()
    if arguments.create_protection_lease is not None:
        if arguments.lease_owner is None or arguments.lease_ttl_seconds is None:
            parser.error("lease creation requires owner and TTL")
        result = create_capacity_protection_lease(
            arguments.artifact_root,
            lease_id=arguments.create_protection_lease,
            owner=arguments.lease_owner,
            ttl_seconds=arguments.lease_ttl_seconds,
            protected_paths=arguments.protect_path,
            protected_cache_keys=arguments.protect_cache_key,
            committed_new_bytes=arguments.committed_new_bytes,
        )
    else:
        if any((arguments.lease_owner, arguments.lease_ttl_seconds,
                arguments.committed_new_bytes, arguments.protect_path,
                arguments.protect_cache_key)):
            parser.error("lease deletion accepts only the artifact root and lease ID")
        result = delete_capacity_protection_lease(
            arguments.artifact_root, lease_id=arguments.delete_protection_lease,
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
