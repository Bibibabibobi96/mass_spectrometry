"""Fly guard forwarding over real shared software process ownership; no SIMION."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

from msplatform.backends.simion.dual_cone_transport_execution import track_transport
from msplatform.execution.context import ExecutionContext
from msplatform.execution.processes import run_observed_process, ProcessExecutionError
from msplatform.execution.resources import resource_path
from msplatform.io.manifest_records import file_record
from common.contracts.test_dual_cone_transport_execution import request
from common.simion.test_analyze_terminal_plane import HEADER


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "real Windows input guard required")
class FlyNativeGuardTests(unittest.TestCase):
    def test_actual_guarded_software_payload_cannot_mutate_audited_basis_or_control(self):
        self._case(tamper=False)

    def test_tampered_basis_is_rejected_before_inert_payload_starts(self):
        self._case(tamper=True)

    def _case(self, *, tamper):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH")
            self.assertTrue(state, "run through normal public GATE")
            context = ExecutionContext(
                workspace=root,
                python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which("pwsh")),
                tools={},
                host_state_path=Path(state),
                policy_path=resource_path("host_resource_policy.json"),
            )
            iob = root / "transport.iob"
            iob.write_bytes(b"INERT_NOT_IOB")
            basis = root / "dual_cone.pa22"
            basis.write_bytes(b"ORIGINAL_AUDITED_BASIS_NOT_PA")
            config = root / "run_config.lua"
            config.write_bytes(b"ORIGINAL_CONFIG")
            guards = [file_record(path, "required_evidence") for path in (basis, iob, config)]
            final = root / "final.csv"
            attempts = root / "attempts.json"
            session = SimpleNamespace(
                context=SimpleNamespace(tools={"simion": Path(sys.executable)}),
                artifact_run_dir=root,
                canonical_path=lambda path: Path(path).resolve(),
                expected_operation_ids=("fly",),
                operations=[],
                log_dir=root,
            )
            calls = []

            def run(operation, **kwargs):
                self.assertEqual(operation, "fly")
                self.assertEqual(kwargs["immutable_input_records"], guards)
                calls.append(kwargs)
                code = """import json,time,sys
from pathlib import Path
records=json.loads(sys.argv[1]);blocked=[]
for record in records:
 path=Path(record['path'])
 for action in(lambda:path.write_bytes(b'UNAUTHORIZED_CHANGE'),lambda:path.unlink()):
  try:action();blocked.append(False)
  except PermissionError:blocked.append(True)
time.sleep(1)
Path(sys.argv[2]).write_text(json.dumps(blocked))
Path(sys.argv[3]).write_text(sys.argv[4])
print('INERT_SOFTWARE_GUARD_NOT_SIMION',flush=True)
print('status,Fly completed. 2 splats, 0.1 seconds',flush=True)
"""
                receipt = run_observed_process(
                    context,
                    executable=Path(sys.executable),
                    arguments=[
                        "-I",
                        "-c",
                        code,
                        json.dumps(guards),
                        str(attempts),
                        str(final),
                        HEADER + "1,10,25.5,25.5,121.75,0,0,1,0\n2,10,25.5,25.5,121.75,0,0,1,3\n",
                    ],
                    working_directory=root,
                    run_directory=root,
                    stdout_path=root / "operation_0001.stdout.log",
                    stderr_path=root / "err.log",
                    usage_path=root / "usage.json",
                    role="GATE",
                    stage="unclassified",
                    run_id="dualcone-fly-inert-guard",
                    limits=None,
                    immutable_input_records=kwargs["immutable_input_records"],
                )
                observed = receipt["observation"]
                session.operations.append(
                    dict(
                        operation_id="fly",
                        observation=dict(
                            exit_confirmed=True,
                            returncode=observed["exit_code"],
                            process_id=observed["root_process_id"],
                            process_started_at_utc_ticks=observed["root_process_started_at_utc_ticks"],
                        ),
                    )
                )
                return receipt

            session.run_process = run
            if tamper:
                basis.write_bytes(b"TAMPERED_BEFORE_FLY")
            args = dict(
                workbench=iob,
                fly2=root / "source.fly2",
                run_config=config,
                numerics=request()["numerics"],
                source_count=2,
                limits={},
                final_state=final,
                immutable_input_records=guards,
            )
            if tamper:
                with self.assertRaises(ProcessExecutionError):
                    track_transport(session, **args)
                self.assertFalse(attempts.exists())
                self.assertFalse(final.exists())
            else:
                metrics, _ = track_transport(session, **args)
                self.assertEqual(json.loads(attempts.read_text()), [True] * 6)
                self.assertEqual(basis.read_bytes(), b"ORIGINAL_AUDITED_BASIS_NOT_PA")
                self.assertEqual(config.read_bytes(), b"ORIGINAL_CONFIG")
                self.assertEqual(metrics["terminal_code_counts"], {"0": 1, "3": 1})
            self.assertEqual(len(calls), 1)
