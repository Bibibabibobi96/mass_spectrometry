"""Explicit execution, artifact admission and resource ownership mechanisms.

Importing this package performs no host, filesystem or tool discovery.
"""
from .context import ExecutionContext, load_environment
from .recovery import resume_run

__all__ = ["ExecutionContext", "load_environment", "resume_run"]
