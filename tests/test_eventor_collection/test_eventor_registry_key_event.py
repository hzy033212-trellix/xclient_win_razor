import datetime
import logging

import pytest
import pytz
from tests.test_xclient.provisioned_xclient import Singleton_XClient

from tests.test_eventor_collection.registry_key_events import (
    RegCreateKeyEvent,
    RegCreateValueEvent,
    RegDeleteKeyEvent,
    RegDeleteValueEvent,
)
from tests.util.eventor_utils import (
    EventTypes,
    run_triggers_collect_results,
    collect_event_buffer_audit,
    find_data_in_audit_for_event,
    eval_agent_event_results,
)
from tests.util.string_formatting_utils import pprint_event_capture_failure_context

logger = logging.getLogger("tests")

REGISTRY_EVENTS = [
    RegCreateKeyEvent,
    RegCreateValueEvent,
    RegDeleteKeyEvent,
    RegDeleteValueEvent,
]


pytestmark = pytest.mark.eventor


def registry_event_platform_keys():
    available_keys = ["path", "eventType", "process", "processPath", "keyPath", "hive", "pid"]
    return available_keys


@pytest.fixture(scope="module")
def run_reg_triggers_collect_results():
    start_time = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
    executed_triggers = run_triggers_collect_results(
        trigger_list=REGISTRY_EVENTS,
        event_keys=registry_event_platform_keys(),
        start_time=start_time,
        event_type=EventTypes.REG_KEY_EVENT.value,
    )
    xclient = Singleton_XClient()
    bulk_audit = collect_event_buffer_audit(
        xclient,
        start_time,
        "Registry Key Events tests bulk audit",
        EventTypes.REG_KEY_EVENT.value,
    )
    yield (bulk_audit, executed_triggers)


@pytest.fixture()
def registry_events_runner(request, run_reg_triggers_collect_results):
    bulk_audit = run_reg_triggers_collect_results[0]
    executed_events = run_reg_triggers_collect_results[1]
    test_name = request.param.__name__
    try:
        collected_info = executed_events[test_name]["results"]
        trigger = executed_events[test_name]["trigger"]
    except KeyError:
        raise KeyError("Failed to locate the test name in the results")
    logger.debug(collected_info)
    agent_event = find_data_in_audit_for_event(
        data=bulk_audit,
        filters=collected_info,
        event_type=EventTypes.REG_KEY_EVENT.value,
        after=trigger.trigger_timestamp,
    )
    failure_string = "Agent should have results for the trigger in the pre-captured audit"
    assert agent_event, pprint_event_capture_failure_context(collected_info, failure_string)
    if agent_event:
        eval_agent_event_results(collected_info, agent_event)


@pytest.mark.parametrize(
    "registry_events_runner",
    [
        RegCreateKeyEvent,
        RegCreateValueEvent,
        RegDeleteValueEvent,
        RegDeleteKeyEvent,
    ],
    indirect=["registry_events_runner"],
    ids=lambda params: params,
)
@pytest.mark.smoke
def test_reg_events_triggers(side_loading_setup, registry_events_runner):
    pass