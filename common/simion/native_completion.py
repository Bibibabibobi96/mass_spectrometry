"""Finite legacy bridge; canonical SIMION completion parsing lives in msplatform.

Existing frozen readers may retain this entry through P4. No parser or
scientific completion policy is duplicated here.
"""
from msplatform.backends.simion.native_completion import (
    FlyCompletion,
    frontend_batch_completion_path,
    has_recoverable_batch_completion,
    parse_fly_completed_line,
    recoverable_batch_log_kind,
    recoverable_batch_logs,
    require_one_fly_completion,
    validate_frontend_batch_completion,
)

__all__ = [
    "FlyCompletion", "frontend_batch_completion_path", "has_recoverable_batch_completion",
    "parse_fly_completed_line", "recoverable_batch_log_kind", "recoverable_batch_logs",
    "require_one_fly_completion", "validate_frontend_batch_completion",
]
