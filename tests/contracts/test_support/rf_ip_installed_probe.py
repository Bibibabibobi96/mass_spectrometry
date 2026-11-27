"""Outside-checkout installed RF-IP consumer with inert native process only."""

import json
import os
from pathlib import Path
import sys
import sysconfig
from unittest.mock import patch


def run(fixture, leaf):
    from msplatform.contracts.gas import BoxDomain
    from importlib.resources import files
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.resources import resource_path
    from msplatform.execution import run_session
    from msplatform.io.manifest_records import file_record
    from msplatform.backends.simion import operations
    from msplatform.execution.owner import standalone_native_store
    from msplatform.storage import ArtifactStore

    purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
    assert (
        Path(operations.__file__).resolve()
        == purelib / "msplatform/backends/simion/operations.py"
    )

    def box(lo, hi):
        return BoxDomain(lo, hi, (True, True, True), (True, True, True))

    c = fixture["context"]
    workspace = Path(c["workspace"]); workspace.mkdir(parents=True, exist_ok=True)
    author = json.loads(files('msplatform').joinpath('components/ion_processor/config/gas_environment.json').read_text(encoding='utf8'))
    author['outer_state'] = dict(pressure_pa=4, temperature_k=fixture['gas_temperature'], bulk_velocity_m_s=[1, 2, 3])
    environment = workspace/'test_hs1_environment.json'; environment.write_text(json.dumps(author), encoding='utf8')
    request = dict(
        bath_domain=box((0, -10, -10), (211, 10, 10)),
        outer_domain=box((-200, -40, -40), (300, 40, 40)),
        environment_record=file_record(environment), environment_instance_id='ion_processor',
        vendor_record=file_record(Path(fixture["vendor_path"])),
        numerics=dict(seed=40, hs1_steps_per_mfp=20),
    )
    context = ExecutionContext(
        workspace=Path(c["workspace"]),
        python_executable=Path(sys.executable),
        powershell_executable=Path(c["powershell_executable"]),
        tools={"simion": Path(sys.executable)},
        host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
        policy_path=resource_path("host_resource_policy.json"),
        capacity_policy_path=Path(c["capacity_policy_path"]),
        stage_policy_path=Path(c["stage_policy_path"]),
    )
    bad_reference = json.loads(json.dumps(fixture["reference"]))
    bad_reference["manifest"]["sha256"] = "0" * 64
    with patch.object(
        run_session,
        "run_observed_process",
        side_effect=AssertionError("unexpected process"),
    ):
        try:
            operations.track(
                bad_reference,
                fixture["packet"],
                propagation=fixture["propagation"],
                observations={"plane_observations": []},
                numerics=fixture["numerics"],
                hs1_request=request,
                context=context,
            )
        except AssertionError as error:
            assert "SHA-256 changed" in str(error)
        else:
            raise AssertionError("changed field manifest identity was accepted")
    observed = []
    callback = leaf(run_session.run_observed_process, observed)
    private = dict(
        MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="",
        MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID="",
        MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE="",
    )
    with (
        patch.dict(os.environ, private),
        patch.object(run_session, "run_observed_process", side_effect=callback),
        standalone_native_store(ArtifactStore(Path(fixture["artifact_root"])),
                                task_key="installed-rf-ip-inert", budget=512*1024**2),
    ):
        result = operations.track(
            fixture["reference"],
            fixture["packet"],
            propagation=fixture["propagation"],
            observations={"plane_observations": []},
            numerics=fixture["numerics"],
            hs1_request=request,
            context=context,
        )
    assert len(observed) == 3
    assert (
        result.metadata["tracking_kind"] == "rf_ip"
        and result.metadata["collision_model"] == "hs1"
    )
    collection = json.loads(result.data_path("collection").read_text(encoding="utf-8"))
    assert [row["particle_id"] for row in collection["native_terminals"]] == [7, 91]
    assert collection["census"]["role"] == "rf_ip_full_mother_census"
    for _, actual, expected in observed:
        assert expected <= actual
    print("INSTALLED_RF_IP_TRACKING_OWNER=PASS native=INERT ids=7,91", flush=True)
