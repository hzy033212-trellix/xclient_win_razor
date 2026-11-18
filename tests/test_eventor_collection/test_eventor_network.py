import datetime
import logging

import pytest
import pytz
from tests.test_eventor_collection.ipv4_network_events import (
    PythonHTTPEventIPv4,
    PythonUDPEventIPv4,
    PythonICMPEventIPv4,
    PythonHTTPEventIPv6,
    PythonUDPEventIPv6,
    PythonICMPEventIPv6,
)
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util import util
from tests.util.eventor_utils import (
    eval_agent_event_results,
    EventTypes,
    collect_event_buffer_audit,
    find_data_in_audit_for_event,
    run_triggers_collect_results,
)
from tests.util.util import event_has_mandatory_keys

logger = logging.getLogger("tests")


NETWORK_EVENTS = [PythonHTTPEventIPv4, PythonUDPEventIPv4, PythonICMPEventIPv4]

NETWORK_EVENTS_IPV6 = [PythonHTTPEventIPv6, PythonUDPEventIPv6, PythonICMPEventIPv6]

IPV4_NETWORK_EVENT_KEYS = [
    "protocol",
    "process",
    "processPath",
    "remoteIP",
    "remotePort",
]


pytestmark = pytest.mark.eventor


# Keys that an IPv4NetworkEvent must have inorder to be accepted/parsed into by Redline
@pytest.fixture(scope="session")
def mandatory_network_platform_keys():
    mandatory_keys = [
        "remoteIP",
        "remotePort",
        "localIP",
        "localPort",
    ]
    yield mandatory_keys


@pytest.fixture(scope="module")
def network_triggers():
    triggers = NETWORK_EVENTS[:]
    if util.is_ipv6_capable():
        triggers.extend(NETWORK_EVENTS_IPV6)
    return triggers


@pytest.fixture(scope="module")
def run_network_triggers_collect_results(
    network_triggers
):
    start_time = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC) - datetime.timedelta(seconds=2)
    collected_results = run_triggers_collect_results(
        trigger_list=network_triggers,
        event_keys=IPV4_NETWORK_EVENT_KEYS,
        start_time=start_time,
        event_type=EventTypes.IPV4_NETWORK_EVENT.value
    )
    xclient = Singleton_XClient()
    bulk_audit = collect_event_buffer_audit(
        xclient,
        start_time,
        "IPv4NetworkEvent tests bulk audit",
        EventTypes.IPV4_NETWORK_EVENT.value,
    )
    yield (bulk_audit, collected_results)


@pytest.fixture()
def network_event_runner(
    request, run_network_triggers_collect_results, mandatory_network_platform_keys
):
    bulk_audit = run_network_triggers_collect_results[0]
    executed_triggers = run_network_triggers_collect_results[1]
    test_name = request.param.__name__
    try:
        collected_info = executed_triggers[test_name]["results"]
        executed_triggers[test_name]["trigger"]
    except KeyError:
        raise KeyError("Failed to locate the test name in the results")
    logger.debug(collected_info)
    agent_event = find_data_in_audit_for_event(
        data=bulk_audit, filters=collected_info, event_type=EventTypes.IPV4_NETWORK_EVENT.value
    )
    assert agent_event, "Agent should have results for the trigger in the pre-captured audit"
    if agent_event:
        assert event_has_mandatory_keys(
            agent_event, mandatory_network_platform_keys
        ), "The event must have all mandatory key:values for"

        eval_agent_event_results(collected_info, agent_event)


@pytest.mark.parametrize(
    "network_event_runner",
    [
        pytest.param(PythonUDPEventIPv4, marks=[pytest.mark.smoke]),
        pytest.param(PythonHTTPEventIPv4, marks=[pytest.mark.smoke]),
        pytest.param(PythonICMPEventIPv4, marks=[pytest.mark.smoke]),
    ],
    indirect=["network_event_runner"],
    ids=lambda params: params,
)
def test_network_event(side_loading_setup, network_event_runner):
    pass

