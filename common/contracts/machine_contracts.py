"""Legacy repository boundary; scientific validation lives in msplatform.

Retire after the enumerated repository-root consumers migrate, no later than P4.
"""
from pathlib import Path
from msplatform.contracts import machine_contracts as _core

REPO_ROOT = Path(__file__).resolve().parents[2]
ContractError = _core.ContractError
SCHEMA_DIR = _core.SCHEMA_DIR
load_json = _core.load_json
schema_registry = _core.schema_registry
validate_schema = _core.validate_schema
sha256 = _core.sha256


def __getattr__(name):
    return getattr(_core, name)
