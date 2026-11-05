"""Repository policy adapter to the single installed host scheduler.

The canonical installed policy is its one authority after migration;
retire repository adapters no later than P4. Installed code never searches it.
"""
from msplatform.execution.resources import resource_path
from msplatform.execution import host_resource_scheduler as _core

StaleSnapshotError = _core.StaleSnapshotError
validate_budget = _core.validate_budget


def load_policy():
    """Read the canonical installed policy for existing repository consumers."""
    return _core.load_policy(resource_path("host_resource_policy.json"))


def transact(path, request, snapshot, policy=None):
    """Delegate the unchanged transaction using this adapter's explicit policy."""
    return _core.transact(path, request, snapshot, load_policy() if policy is None else policy)


def __getattr__(name):
    return getattr(_core, name)


if __name__ == "__main__":
    raise SystemExit(_core.main(policy=load_policy()))
