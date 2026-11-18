import ipaddress

import pytest

from tests.test_eventor_collection.ipv4_network_events import (
    PythonHTTPEventIPv4,
    PythonICMPEventIPv4,
    PythonUDPEventIPv4,
)
from tests.test_eventor_collection.test_eventor_network import IPV4_NETWORK_EVENT_KEYS
from tests.util.hxsim_ioc import HXSIM_PORT
from tests.util.ioc_batch import IocCase, run_ioc_case

pytestmark = pytest.mark.ioc

# Loopback instead of Razor's lab host (IPV4_TARGET): hxsim plays "HX" on
# 127.0.0.1:8443, and loopback traffic is reported by the agent.
LOOPBACK = ipaddress.ip_address("127.0.0.1")

IOC_CASES = {
    "test_ioc_network_event[PythonHTTPEventIPv4]": IocCase(
        "ipv4", lambda _: PythonHTTPEventIPv4(address=LOOPBACK, port=HXSIM_PORT), IPV4_NETWORK_EVENT_KEYS),
    "test_ioc_network_event[PythonUDPEventIPv4]": IocCase(
        "udp", lambda _: PythonUDPEventIPv4(address=LOOPBACK), IPV4_NETWORK_EVENT_KEYS),
    "test_ioc_network_event[PythonICMPEventIPv4]": IocCase(
        "icmp", lambda _: PythonICMPEventIPv4(address=LOOPBACK), IPV4_NETWORK_EVENT_KEYS),
}


@pytest.mark.parametrize("case_id", ["PythonHTTPEventIPv4", "PythonUDPEventIPv4", "PythonICMPEventIPv4"],
                         ids=lambda i: i)
def test_ioc_network_event(hxsim_ioc_setup, request, case_id):
    run_ioc_case(hxsim_ioc_setup, request)
