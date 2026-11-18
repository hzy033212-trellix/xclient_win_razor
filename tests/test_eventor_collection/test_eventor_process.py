import datetime
import logging
import time

import pytest
import pytz

from tests.test_eventor_collection.process_events import PythonProcessEvent
from tests.util.string_formatting_utils import pprint_event_capture_failure_context
from tests.util.eventor_utils import (
    eval_agent_event_results,
    retrieve_event_in_audit,
    EventTypes
)

logger = logging.getLogger("tests")

process_event_platform_keys = [
    "pid",
    "process",
    "processPath",
    "processCmdLine",
    "md5",
    "parentPid",
    "parentProcess",
    "parentProcessPath",
    "username"
    "eventType"
]


pytestmark = pytest.mark.eventor

def get_assertable_results(trigger_result, event_keys):
    return {key: value for key, value in trigger_result.items() if key in event_keys}
    
def func_wait(func, interval=5, timeout=300, negate=False, **kwargs):
    """
    Run a function every interval. On success return.

    :param func: function that runs some sort of check that returns a truthy or falsey value
    :param interval: interval to run function
    :param timeout: max time
    :param negate: negate return of function
    :param kwargs: arbitrary args to pass to function
    :return: return value of func either from first truthy value or last falsey value before timeout
    """
    start_time = time.time()
    result = not func(**kwargs) if negate else func(**kwargs)

    while not result and (time.time() - start_time) < timeout:
        time.sleep(interval)
        result = not func(**kwargs) if negate else func(**kwargs)

    return result

@pytest.fixture()
def process_runner(request):
    event_class = request.param[0]
    event = event_class(request.param[1], request.param[2])

    result_info = event.trigger()
    logger.info("Triggered process event")

    tic = event.trigger_timestamp - datetime.timedelta(0, 1)

    filter_key_val = {
        "process": result_info["process"],
        "processCmdLine": result_info["processCmdLine"],
        "pid": result_info["pid"],
        "eventType": result_info["eventType"],
        "parentPid": result_info["parentPid"],
        "parentProcess": result_info["parentProcess"],
        "md5": result_info["md5"]
    }
    
    logger.debug(f"collected_info contents: {result_info}")

    agent_event = func_wait(
        retrieve_event_in_audit,
        interval=5,
        timeout=30,
        filters=filter_key_val,
        start_time=tic,
        event_type=EventTypes.PROCESS_EVENT.value,
    )
    assert agent_event, pprint_event_capture_failure_context(result_info)

    cleaned_results = get_assertable_results(result_info, process_event_platform_keys)

    # Windows is case insensitive, thus not consistent about how it treats file paths
    cleaned_results["processPath"] = cleaned_results["processPath"].lower()
    agent_event["processPath"] = agent_event["processPath"].lower()

    eval_agent_event_results(cleaned_results, agent_event)


@pytest.mark.parametrize(
    "process_runner",
    [
        (PythonProcessEvent, "ipconfig", ["/flushdns"]),
    ],
    indirect=["process_runner"],
    ids=lambda params: f"{params[0].__name__}-{params[1]}",
)
@pytest.mark.smoke
def test_process(side_loading_setup, process_runner):
    pass
