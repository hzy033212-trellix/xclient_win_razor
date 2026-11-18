import pytest

from tests.test_eventor_collection.test_eventor_url_monitor_event import URL_MONITOR_EVENT_KEYS
from tests.test_eventor_collection.url_monitor_events import (
    ConnectUrlMonitorEvent,
    DeleteUrlMonitorEvent,
    GetUrlMonitorEvent,
    HeadUrlMonitorEvent,
    OptionsUrlMonitorEvent,
    PostUrlMonitorEvent,
    PutUrlMonitorEvent,
    TraceUrlMonitorEvent,
)
from tests.util.ioc_batch import IocCase, run_ioc_case

pytestmark = pytest.mark.ioc

# The Windows cases enabled in test_eventor_url_monitor_event.py (plain HTTP to httpbin.org/anything).
URL_EVENT_CLASSES = [GetUrlMonitorEvent, PostUrlMonitorEvent, PutUrlMonitorEvent, HeadUrlMonitorEvent,
                     OptionsUrlMonitorEvent, DeleteUrlMonitorEvent, TraceUrlMonitorEvent, ConnectUrlMonitorEvent]

IOC_CASES = {
    "test_ioc_url_monitor_event[{}]".format(c.__name__): IocCase("url_any", lambda _, c=c: c(), URL_MONITOR_EVENT_KEYS)
    for c in URL_EVENT_CLASSES
}


@pytest.mark.parametrize("event_class", URL_EVENT_CLASSES, ids=lambda c: c.__name__)
def test_ioc_url_monitor_event(hxsim_ioc_setup, request, event_class):
    run_ioc_case(hxsim_ioc_setup, request)
