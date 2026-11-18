import logging
from datetime import datetime

import pytest
import pytz
from tests.test_eventor_collection.file_events import (
    FileCreateAsciiEvent,
    FileCreateSoftLinkEvent,
    FileCreateHardLinkEvent,
    FileRenameEvent,
    FileWriteEvent,
    FileCopyEvent,
    FileWriteAppendEvent,
    FileDeleteEvent,
    FileDeleteSoftLinkEvent,
    FileDeleteHardLinkEvent,
    FileTruncateEvent,
)
from tests.test_xclient.provisioned_xclient import Singleton_XClient

from tests.util.platform_handling_utils import full_path_to_lowercase
from tests.util.eventor_triggers import DirRenameEvent, DirDeleteEvent
from tests.util.eventor_utils import (
    eval_agent_event_results,
    EventTypes,
    collect_event_buffer_audit,
    find_data_in_audit_for_event,
    run_triggers_collect_results,
)
from tests.util.string_formatting_utils import pprint_event_capture_failure_context

logger = logging.getLogger("tests")

FILE_EVENTS = [
    FileCreateAsciiEvent,
    FileCreateSoftLinkEvent,
    FileCreateHardLinkEvent,
    FileRenameEvent,
    FileCopyEvent,
    FileWriteAppendEvent,
    FileDeleteEvent,
    DirRenameEvent,
    DirDeleteEvent,
    FileDeleteSoftLinkEvent,
    FileDeleteHardLinkEvent,
    FileTruncateEvent,
    FileWriteEvent,
]


pytestmark = pytest.mark.eventor


def file_event_platform_keys():
    available_keys = [
        "fileName",
        "md5",
        "fullPath",
        "fileExtension",
        "closed",
        # "filePath",
        "pid",
        "drive",
        "textAtLowestOffset",
        "numBytesSeenWritten",
        "parentPid",
        "parentProcessPath",
        "writes",
    ]
    return available_keys


@pytest.fixture(scope="module")
def run_file_triggers_collect_results():
    start_time = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
    executed_triggers = run_triggers_collect_results(
        trigger_list=FILE_EVENTS,
        event_keys=file_event_platform_keys(),
        start_time=start_time,
        event_type=EventTypes.FILE_WRITE_EVENT.value
    )
    xclient = Singleton_XClient()
    bulk_audit = collect_event_buffer_audit(
        xclient,
        start_time,
        "FileWriteEvent tests bulk audit",
        EventTypes.FILE_WRITE_EVENT.value,
    )
    yield (bulk_audit, executed_triggers)


@pytest.fixture()
def file_event_runner(request, run_file_triggers_collect_results):
    bulk_audit = run_file_triggers_collect_results[0]
    bulk_audit["eventItem"] = full_path_to_lowercase(bulk_audit)
    executed_triggers = run_file_triggers_collect_results[1]
    test_name = request.param.__name__
    try:
        collected_info = executed_triggers[test_name]["results"]
        trigger = executed_triggers[test_name]["trigger"]
    except KeyError:
        raise KeyError("Failed to locate the test name in the results")
    logger.debug(collected_info)
    agent_event = find_data_in_audit_for_event(
        data=bulk_audit,
        filters=collected_info,
        event_type=EventTypes.FILE_WRITE_EVENT.value,
        after=trigger.trigger_timestamp,
    )
    failure_string = "Agent should have results for the trigger in the pre-captured audit"
    assert agent_event, pprint_event_capture_failure_context(collected_info, failure_string)
    if agent_event:
        eval_agent_event_results(collected_info, agent_event)


@pytest.mark.parametrize(
    "file_event_runner",
    [
        FileCreateAsciiEvent,
        FileRenameEvent,
        FileWriteEvent,
        FileWriteAppendEvent,
        FileCopyEvent,
    ],
    indirect=["file_event_runner"],
    ids=lambda params: params,
)
@pytest.mark.smoke
def test_file_event_triggers(side_loading_setup, file_event_runner):
    pass

