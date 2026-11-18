import datetime
import logging
from tests.test_xclient.provisioned_xclient import Singleton_XClient

import pytest
import pytz
from tests.test_eventor_collection.image_load_events import (
    ImageLoadServiceStartEvent,
    ImageLoadExecutableStartEvent,
)

from tests.util.eventor_utils import (
    eval_agent_event_results,
    EventTypes,
    collect_event_buffer_audit,
    find_data_in_audit_for_event,
    run_triggers_collect_results,
)

logger = logging.getLogger("tests")

WIN_IMAGE_TRIGGERS = [
    (ImageLoadServiceStartEvent, {"service_name": "spooler", "library": "nsi.dll"}),
    (ImageLoadExecutableStartEvent, {"executable": "notepad.exe", "library": "ntdll.dll"}),
]

IMAGE_LOAD_EVENT_KEYS = ["fileName", "process"]


pytestmark = pytest.mark.eventor


@pytest.fixture(scope="module")
def platform_triggers():
    return WIN_IMAGE_TRIGGERS


@pytest.fixture(scope="module")
def run_image_load_triggers_collect_results(
    platform_triggers
):
    start_time = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    collected_results = run_triggers_collect_results(
        trigger_list=platform_triggers,
        event_keys=IMAGE_LOAD_EVENT_KEYS,
        start_time=start_time,
        event_type=EventTypes.IMAGE_LOAD_EVENT.value,
    )
    xclient = Singleton_XClient()
    bulk_audit = collect_event_buffer_audit(
        xclient,
        start_time,
        "ImageLoadEvent tests bulk audit",
        EventTypes.IMAGE_LOAD_EVENT.value,
    )
    yield (bulk_audit, collected_results)


@pytest.fixture()
def image_load_runner(request, run_image_load_triggers_collect_results):
    bulk_audit = run_image_load_triggers_collect_results[0]
    executed_triggers = run_image_load_triggers_collect_results[1]
    test_name = request.param.__name__
    try:
        collected_info = executed_triggers[test_name]["results"]
        executed_triggers[test_name]["trigger"]
    except KeyError:
        raise KeyError("Failed to locate the test name in the results")
    logger.debug(collected_info)
    agent_event = find_data_in_audit_for_event(
        data=bulk_audit, filters=collected_info, event_type=EventTypes.IMAGE_LOAD_EVENT.value
    )
    assert agent_event, "Agent should have results for the trigger in the pre-captured audit"
    if agent_event:
        eval_agent_event_results(collected_info, agent_event)


@pytest.mark.parametrize(
    "image_load_runner",
    [
        ImageLoadExecutableStartEvent,
        ImageLoadServiceStartEvent,
    ],
    indirect=["image_load_runner"],
    ids=lambda params: params,
)
def test_image_load(side_loading_setup, image_load_runner):
    pass