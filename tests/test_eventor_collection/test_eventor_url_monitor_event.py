import datetime
import logging

import pytest
import pytz
from tests.test_eventor_collection.url_monitor_events import (
    GetUrlMonitorEvent,
    PostUrlMonitorEvent,
    PutUrlMonitorEvent,
    HeadUrlMonitorEvent,
    OptionsUrlMonitorEvent,
    DeleteUrlMonitorEvent,
    PatchUrlMonitorEvent,
    TraceUrlMonitorEvent,
    LinkUrlMonitorEvent,
    UnlinkUrlMonitorEvent,
    ConnectUrlMonitorEvent
)
from tests.test_xclient.provisioned_xclient import Singleton_XClient

from tests.util.eventor_utils import (
    eval_agent_event_results,
    EventTypes,
    collect_event_buffer_audit,
    find_data_in_audit_for_event,
    run_triggers_collect_results,
)

logger = logging.getLogger("tests")


URL_EVENTS = [
    GetUrlMonitorEvent,
    PostUrlMonitorEvent,
    PutUrlMonitorEvent,
    HeadUrlMonitorEvent,
    OptionsUrlMonitorEvent,
    DeleteUrlMonitorEvent,
    PatchUrlMonitorEvent,
    TraceUrlMonitorEvent,
    LinkUrlMonitorEvent,
    UnlinkUrlMonitorEvent,
    ConnectUrlMonitorEvent,
]

URL_MONITOR_EVENT_KEYS = [
    "pid",
    "process",
    "hostname",
    "requestUrl",
#   "remoteIpAddress",
    "remotePort",
    "urlMethod",
]


pytestmark = pytest.mark.eventor


@pytest.fixture(scope="module")
def run_url_monitor_triggers_collect_results():
    # The triggers send plain HTTP to the external URL_MONITOR_HOST (the agent ignores loopback
    # traffic, so a local server can't be used).
    url_events = URL_EVENTS
    start_time = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC) - datetime.timedelta(seconds=5)
    collected_results = run_triggers_collect_results(
        trigger_list=url_events,
        event_keys=URL_MONITOR_EVENT_KEYS,
        start_time=start_time,
        event_type=EventTypes.URL_MONITOR_EVENT.value,
    )
    xclient = Singleton_XClient()
    bulk_audit = collect_event_buffer_audit(
        xclient,
        start_time,
        "UrlMonitorEvent tests bulk audit",
        EventTypes.URL_MONITOR_EVENT.value,
    )
    yield (bulk_audit, collected_results)


@pytest.fixture()
def url_event_runner(request, run_url_monitor_triggers_collect_results):
    bulk_audit = run_url_monitor_triggers_collect_results[0]
    executed_triggers = run_url_monitor_triggers_collect_results[1]
    test_name = request.param.__name__
    try:
        collected_info = executed_triggers[test_name]["results"]
        trigger = executed_triggers[test_name]["trigger"]
    except KeyError:
        raise KeyError("Failed to locate the test name in the results")
    assert trigger.request_error is None, "{} request to {} failed, so no event is expected: {}".format(
        trigger.get_url_method(), trigger.url, trigger.request_error)
    logger.debug(collected_info)
    agent_event = find_data_in_audit_for_event(
        data=bulk_audit, filters=collected_info, event_type=EventTypes.URL_MONITOR_EVENT.value
    )
    assert agent_event, "Agent should have results for the trigger in the pre-captured audit"
    if agent_event:
        eval_agent_event_results(collected_info, agent_event)


@pytest.mark.parametrize(
    "url_event_runner",
    [
        GetUrlMonitorEvent,
        PostUrlMonitorEvent,
        PutUrlMonitorEvent,
        HeadUrlMonitorEvent,
        OptionsUrlMonitorEvent,
        DeleteUrlMonitorEvent,
        TraceUrlMonitorEvent,
        ConnectUrlMonitorEvent,
    ],
    indirect=["url_event_runner"],
    ids=lambda params: params,
)
@pytest.mark.smoke
def test_url_monitor_events(side_loading_setup, url_event_runner):
    pass