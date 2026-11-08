"""Completion policies for operations that never create particle batches."""
from pathlib import Path


class _NoParticleBatchCompletion:
    @staticmethod
    def recoverable_batch_log_kind(path):
        return None

    @staticmethod
    def has_recoverable_batch_completion(path):
        return False

    @staticmethod
    def recoverable_batch_logs(run_dir):
        logs = Path(run_dir) / "logs"
        if logs.is_dir() and any(path.is_file() and
                (path.match("simion__batch*.trace.log") or path.match("simion__batch*.stdout.log"))
                for path in logs.iterdir()):
            raise ValueError("Non-particle action contains unexpected particle batch evidence")
        return set()


def no_particle_batch_completion_api():
    """Reject TRACE recovery for operations without particle-batch products."""
    return _NoParticleBatchCompletion
