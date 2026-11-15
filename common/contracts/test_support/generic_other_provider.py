"""One shared normally registered test provider for generic scalar cases."""

from common.contracts.test_support import registered_component as toy
from msplatform.components.registry import (
    ProviderDescriptor,
    provider_descriptor,
    register_provider,
)
from msplatform.contracts.machine_contracts import ContractError


def resolve(source, profile):
    resolved, interface = toy.resolve(source, profile)
    interface["project_id"] = "toy_other"
    return resolved, interface


def validate(source, resolved, interface):
    if resolve(source, interface.get("geometry_profile_id")) != (resolved, interface):
        raise ContractError("source mismatch")


DESCRIPTOR = ProviderDescriptor(
    "toy_other",
    "toy_other",
    resolve,
    validate,
    toy.members,
    ("common.contracts.test_support.generic_other_provider", "common.contracts.test_support.registered_component"),
)


def ensure_registered():
    try:
        existing = provider_descriptor("toy_other")
    except ContractError:
        register_provider(DESCRIPTOR)
    else:
        if existing is not DESCRIPTOR:
            raise ContractError("foreign fixture")
