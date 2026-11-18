import logging
import socket
import subprocess
import threading

import pytest
from ipaddress import IPv6Address
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util.paths import NODE_EXE
from tests.util.hxsim_ioc import HXSIM_PORTS

from tests.util.audit_utils import create_test_socket_list
from tests.util.util import dict_is_subset
from tests.util.fixtures_audits import create_ipv6_socket

logger = logging.getLogger("tests")

pytestmark = pytest.mark.audit


@pytest.fixture(scope="module")
def test_ports_info(create_ipv6_socket):
    tcp_port, udp_port = create_ipv6_socket
    test_socket_ports = create_test_socket_list(tcp_port, udp_port)
    yield test_socket_ports


NODE_PORTS = [80, 443, 8080]
NODE_READY_TIMEOUT = 30  # seconds to wait for the node listeners

# Listens on every port given on the command line, IPv4 only (0.0.0.0): with no
# host, node binds an IPv6 "::" socket, which the default (no-IPv6) ports audit
# is expected not to report. Kept in plain ES5 so it parses on any node version.
NODE_LISTEN_SCRIPT = """
var net = require('net');
var ports = process.argv.slice(1).map(Number);
var ready = 0;
function onListening() {
  if (++ready === ports.length) console.log('READY');
}
function onError(e) {
  console.error(e.message);
  process.exit(1);
}
for (var i = 0; i < ports.length; i++) {
  net.createServer(function (s) { s.end(); }).listen(ports[i], '0.0.0.0', onListening).on('error', onError);
}
"""


def _port_is_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="module")
def node_open_ports():
    # The node from paths.json (node_exe), not the one on PATH: the system node
    # here is 0.12, whose listen() callback never fires on this Windows version,
    # so it would never report READY.
    node = str(NODE_EXE)
    if not NODE_EXE.is_file():
        pytest.fail(f"node not found at {node} (node_exe in paths.json)")

    proc = subprocess.Popen(
        [node, "-e", NODE_LISTEN_SCRIPT, *map(str, NODE_PORTS)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Read READY on a thread so a node that never reports it can't hang the run.
        lines = []
        reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline().strip()), daemon=True)
        reader.start()
        reader.join(NODE_READY_TIMEOUT)
        if lines != ["READY"]:
            proc.kill()
            _, err = proc.communicate(timeout=10)
            pytest.fail(f"node failed to open ports {NODE_PORTS} within {NODE_READY_TIMEOUT}s: {err.strip()}")
        logger.info(f"node (pid {proc.pid}) listening on ports {NODE_PORTS}")
        yield NODE_PORTS
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        # HXSim itself keeps listening on 127.0.0.1:8080.
        still_open = [p for p in NODE_PORTS if p not in HXSIM_PORTS and _port_is_listening(p)]
        assert not still_open, f"Ports opened by node were not closed: {still_open}"


# Function scoped on purpose: each test runs its own audit with its own
# ``<test case name>.json`` script, and keeps the script and outputs in
# its own temp/<script>/<test>/ folder.
@pytest.fixture(scope="function")
def collect_ports_audit_no_ipv6(node_open_ports):
    xclient = Singleton_XClient()
    data = xclient.run_job("ports", notes="ports audit test")
#   data = task.get_results_for_audit("ports")
    yield data


@pytest.fixture(scope="function")
def collect_ports_audit_with_ipv6(create_ipv6_socket):
    xclient = Singleton_XClient()
    data = xclient.run_job("ports", notes="ports audit test")
#   data = task.get_results_for_audit("ports")
    yield data


def ipv6_port_item_equal(socket_port, port_item):
    sp = socket_port.copy()
    process = sp.pop("process")
    localIP = sp.pop("localIP")
    remoteIP = sp.pop("remoteIP")

    # isIPv6 may be returned as bool or string
    port_item["isIPv6"] = str(port_item["isIPv6"]).lower()

    if port_item["localIP"] == "*": port_item["localIP"] = "::0"
    if port_item["remoteIP"] == "*": port_item["remoteIP"] = "::0"

    return dict_is_subset(sp, port_item) \
           and process in port_item["process"].lower() \
           and IPv6Address(localIP) == IPv6Address(port_item["localIP"]) \
           and IPv6Address(remoteIP) == IPv6Address(port_item["remoteIP"])


@pytest.mark.smoke
def test_audit_ports(collect_ports_audit_no_ipv6):
    data = collect_ports_audit_no_ipv6

    assert data, "Data for ports audit should be part of the results"
    assert "PortItem" in data, "Port items should be in audit results"

    def search_for_port(data, port):
        process_name = "node.exe"
        for port_item in data["PortItem"]:
            if port_item["process"].lower() == process_name and port_item["localPort"] == port:
                return True
        return False

    assert search_for_port(data, 80), "Simulator port 80 should be found"
    assert search_for_port(data, 443), "Simulator port 443 should be found"
    assert search_for_port(data, 8080), "Simulator port 8080 should be found"


@pytest.mark.smoke
def test_audit_ports_donot_include_ipv6_bydefault(collect_ports_audit_no_ipv6):
    data = collect_ports_audit_no_ipv6

    assert data, "Data for ports audit should be part of the results"

    found_ipv6 = False
    for port_item in data["PortItem"]:
        if "isIPv6" in port_item:
            found_ipv6 = True
            break

    assert not found_ipv6, "IPv6 test socket ports should not be found by default"


@pytest.mark.smoke
def test_audit_ports_include_ipv6(collect_ports_audit_with_ipv6, test_ports_info):
    data = collect_ports_audit_with_ipv6
    test_socket_ports = test_ports_info

    assert data, "Data for ports audit should be part of the results"

    found_socket_ports = 0
    for port_item in data["PortItem"]:
        for socket_port in test_socket_ports:
            if "isIPv6" in port_item:
                if ipv6_port_item_equal(socket_port, port_item):
                    found_socket_ports += 1

    assert found_socket_ports == 2, "Both IPv6 test socket ports should be found"


@pytest.mark.smoke
def test_audit_ports_donot_include_ipv6():
    # run ports audit with IncludeIPv6=false
    xclient = Singleton_XClient()
    data = xclient.run_job("ports", notes="ports audit test")
#   data = task.get_results_for_audit("ports")

    assert data, "Data for ports audit should be part of the results"

    found_ipv6 = False
    for port_item in data["PortItem"]:
        if "isIPv6" in port_item:
            found_ipv6 = True
            break

    assert not found_ipv6, "IPv6 test socket ports should not be found"