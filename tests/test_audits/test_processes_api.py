import logging
import os
import pprint
import subprocess
import time

import pytest
from tests.util import util
from tests.util.paths import NODE_EXE
from tests.util.compatibility import WINDOWS, OS_COMPAT, MAC, LINUX
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


def run_audit(xclient_agent, params, note=""):
    data = xclient_agent.run_job(
        "processes-api",
        params=params,
#       notes=note,
        timeout=300,
    )
#   data = task.get_results_for_audit("processes-api")
    assert data["ProcessItem"], "Process API audit should return some process data"
    return data


###############################
# Windows specific test cases #
###############################


# @OS_COMPAT(WINDOWS)
# @pytest.mark.broken(WINDOWS)
# @pytest.mark.memory
# @pytest.mark.caseid(58117957)
# def test_processes_api_param_collection_single_process(provisioned_agent):
#     test_params = {"process name": "python.exe"}
#     task = provisioned_agent.run_job(
#         "processes-api",
#         params=test_params,
#         notes="processes-api process name collection",
#         timeout=300,
#     )
#     data = task.get_results_for_audit("processes-api")

#     assert data, "Data should be produced indicating successful completion."


#####################################
# Mac and Linux specific test cases #
#####################################


def is_our_python_process(p):
    if util.is_lin():
        return p.get("name", "").startswith("python")
    else:
        return p.get("pid", 0) == os.getpid()


# @OS_COMPAT(LINUX, MAC)
# @pytest.mark.nightly
# @pytest.mark.caseid(58117955)
# def test_processes_api_param_collection_processname(provisioned_agent):
#     node_name = "node"

#     data = run_audit(
#         provisioned_agent,
#         params={"process name": node_name},
#         note="processes-api process name collection",
#     )

#     assert all(
#         process["name"] == node_name for process in data["ProcessItem"]
#     ), "Did not capture correct process"


# @OS_COMPAT(LINUX, MAC)
# @pytest.mark.nightly
# @pytest.mark.caseid(58117956)
# def test_processes_api_param_collection_single_pid(provisioned_agent):
#     py_pid = os.getpid()

#     data = run_audit(
#         provisioned_agent,
#         params={"pid": str(py_pid)},
#         note="processes-api process ID collection",
#     )

#     assert all(
#         process["pid"] == py_pid for process in data["ProcessItem"]
#     ), f"Did not capture correct process, found in audit: {data['ProcessItem']}"


@pytest.fixture
def node_process():
    # No node process is otherwise guaranteed to run on the host, so start one
    # (the node from paths.json, node_exe) for the audit to capture.
    if not NODE_EXE.is_file():
        pytest.fail(f"node not found at {NODE_EXE} (node_exe in paths.json)")
    proc = subprocess.Popen([str(NODE_EXE), "-e", "setInterval(() => {}, 1000)"])
    try:
        time.sleep(1)
        assert proc.poll() is None, f"node exited right away with code {proc.returncode}"
        logger.info(f"node started, pid {proc.pid}")
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.mark.smoke
@pytest.mark.caseid(30409495)
def test_audit_processes_api(node_process):
    data = run_audit(xclient, params={}, note="processes-api collection")

    node_name = "node.exe" if util.is_win() else "node"

    captured = next((p for p in data["ProcessItem"] if p.get("pid") == node_process.pid), None)

    assert captured, f"node (pid {node_process.pid}) should be captured as a process, found in audit: {data['ProcessItem']}"
    assert captured.get("name", "").lower() == node_name, f"pid {node_process.pid} should be {node_name}, found: {captured}"


# @OS_COMPAT(LINUX, MAC)
# @pytest.mark.nightly
# @pytest.mark.caseid(17494908)
# def test_audit_process_api_handle_include_file(provisioned_agent):
#     file_path = os.path.realpath("/etc/hosts")
#     file_handle = open(file_path, "rt")

#     data = run_audit(
#         provisioned_agent,
#         params={"handles": "true"},
#         note="processes-api handles param true audit test",
#     )

#     file_handle.close()

#     handle_found = False
#     python_handle_list, python_process = None, None
#     for process in data["ProcessItem"]:
#         if is_our_python_process(process):
#             assert (
#                 process.get("HandleList", None)
#             ), f"should have some handles returned, none found for process: {pprint.pprint(python_process,indent=2)}"
#             python_handle_list = process["HandleList"]
#             python_process = process
#             for h in process["HandleList"]:
#                 if h["Name"] == file_path and h["Type"] == "REG":
#                     handle_found = True
#     assertion_string = "File handle should be captured, found:"
#     if python_process:
#         assertion_string += f"\npython process: \n {pprint.pprint(python_process,indent=2)}"
#     if python_handle_list:
#         assertion_string += f"\npython process handle list: \n {pprint.pprint(python_handle_list,indent=2)}"

#     assert handle_found, assertion_string


# @OS_COMPAT(LINUX, MAC)
# @pytest.mark.smoke
# @pytest.mark.caseid(58117958)
# def test_audit_process_api_handle_include_ipv6(provisioned_agent, create_ipv6_socket):
#     tcp_port, udp_port = create_ipv6_socket

#     data = run_audit(
#         provisioned_agent,
#         params={"handles": "true"},
#         note="processes-api handles param true audit test",
#     )

#     ipv6_type = "IPv6"
#     ipv6_tcp_handle_found = False
#     ipv6_udp_handle_found = False
#     for process in data["ProcessItem"]:
#         if not is_our_python_process(process):
#             continue

#         for h in process["HandleList"]:
#             if (
#                 h["Type"] == ipv6_type
#                 and h["SocketType"] == ipv6_type
#                 and h["SocketLocalAddress"] == "0000:0000:0000:0000:0000:0000:0000:0001"
#             ):
#                 socket_protocol = h["SocketProtocol"]
#                 if socket_protocol == "TCP" and h["SocketLocalPort"] == str(tcp_port):
#                     ipv6_tcp_handle_found = True
#                 elif socket_protocol == "UDP" and h["SocketLocalPort"] == str(udp_port):
#                     ipv6_udp_handle_found = True

#     assert ipv6_tcp_handle_found, "IPv6 TCP listening socket handle should be captured"
#     assert ipv6_udp_handle_found, "IPv6 UDP listening socket handle should be captured"