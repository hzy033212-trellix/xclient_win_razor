import logging
from pathlib import Path

import pytest
from tests.util.compatibility import WINDOWS, OS_COMPAT

from tests.util.memory_utils import check_schema_handles_in_proc, validate_handles_not_missing
from tests.util.fixtures_audits import collect_test_binaries, start_test_binary
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


@pytest.fixture(scope="module")
def start_create_h_process(collect_test_binaries):
    create_psutil_process = start_test_binary(collect_test_binaries.CreateH)
    try:
        yield create_psutil_process
    finally:
        create_psutil_process.kill()


@pytest.fixture(scope="module")
def collect_process_handle_audit(start_create_h_process):
    params = {"handles": True}
    data = xclient.run_job(
        "w32processes-handle",
        params=params,
        notes="w32processes-handle audit test",
        audit_script_name="test_audit_processes_handle",
    )

    yield data


@OS_COMPAT(WINDOWS)
@pytest.mark.smoke
@pytest.mark.caseid(30409496)
def test_audit_processes_handle(collect_process_handle_audit):
    data = collect_process_handle_audit
    process_name = "CreateH.exe"

    assert data, "Data for processes-handle audit should be part of the results"

    createh_process = None
    for process in data["ProcessItem"]:
        if process["name"] == process_name:
            createh_process = process

    assert createh_process, f"{process_name} should be captured as a process"


@OS_COMPAT(WINDOWS)
@pytest.mark.smoke
@pytest.mark.caseid(10884606)
def test_processes_handle_check_all_parameters(
    collect_process_handle_audit, start_create_h_process
):
    """
    CASE [10884606]:
    NOTE: checks for the known matches we expect to create. There
    will be more than what we check for, but most handles are ephemeral,
    thus completeness checks should never even be attempted.
    """
    process_name = "CreateH.exe"
    expected_create_h_handles = {
        "Section": "sfAgentSection",
        "Semaphore": "sfAgentSemaphore",
        "SymbolicLink": "sfAgentSymbolicLink",
        "Timer": "sfAgentWaitableTimer",
        "WindowStation": "sfAgentWinSta",
        "Directory": "sfAgent",
        "ALPC Port": "sfAgentTestPort",
        "Desktop": "sfAgentDesktop",
        "Event": "sfAgentEvent",
        "Job": "sfAgentJob",
        "Mutant": "sfAgentMutex",
    }
    data_to_validate = {
        "arguments": "".join(start_create_h_process.cmdline()),
        "name": start_create_h_process.name(),
        "path": str(Path(start_create_h_process.exe()).parent),
        "pid": start_create_h_process.pid,
    }

    audit_data = collect_process_handle_audit

    # Match on pid too, so a CreateH.exe left running by an earlier run is not picked
    createh_audit_result = None
    for process in audit_data["ProcessItem"]:
        if process["name"] == process_name and process.get("pid") == start_create_h_process.pid:
            createh_audit_result = process

    assert (
        createh_audit_result
    ), f"should be able to find CreateH (pid {start_create_h_process.pid}) in audit, found: {[(process['name'], process.get('pid')) for process in audit_data['ProcessItem'] if process['name'] == process_name]}"

    check_schema_handles_in_proc(createh_audit_result["HandleList"])
    validate_handles_not_missing(expected_create_h_handles, createh_audit_result)

    # Validate some base ProcessItem fields for the retrieved process
    for key, val in data_to_validate.items():
        assert (
            key in createh_audit_result
        ), f"Should have key: {key} in audit results for process, found: {createh_audit_result}"
        assert (
            createh_audit_result[key] == val
        ), f"audit result: {createh_audit_result[key]} does not match expected value: {val}"