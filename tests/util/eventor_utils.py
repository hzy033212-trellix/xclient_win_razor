import datetime
import json
import logging
from enum import Enum

import dateutil.parser

from tests.util.util import func_wait
from tests.util.platform_handling_utils import full_path_to_lowercase
from tests.util.platform_handling_utils import image_load_process_to_lowercase
from tests.util.platform_handling_utils import path_to_uppercase
from tests.util.platform_handling_utils import key_path_to_uppercase
from tests.util.platform_handling_utils import hive_to_uppercase
# from tests.util.util import wait_for_config_to_apply
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.test_xclient.provisioned_xclient import record_event_buffer_audit_metadata

logger = logging.getLogger("util")


class EventTypes(Enum):
    DNS_LOOKUP_EVENT = "dnsLookupEvent"
    IMAGE_LOAD_EVENT = "imageLoadEvent"
    PROCESS_EVENT = "processEvent"
    IPV4_NETWORK_EVENT = "ipv4NetworkEvent"
    FILE_WRITE_EVENT = "fileWriteEvent"
    URL_MONITOR_EVENT = "urlMonitorEvent"
    REG_KEY_EVENT = "regKeyEvent"
    ADDRESS_NOTIFICATION_EVENT = "addressNotificationEvent"


def eval_agent_event_results(trigger_result, agent_result):
    for key, value in agent_result.items():
        if key in trigger_result:
            logger.debug("trigger key: {}".format(key))
            logger.debug("trigger value type: {}".format(trigger_result[key]))
            logger.debug("trigger value type: {}".format(type(trigger_result[key])))
            logger.debug("agent result value: {}".format(value))
            logger.debug("agent result value type: {}".format(type(value)))
            assert value == trigger_result[key], (
                "Values in agent: {}, should match those "
                "produced by the trigger: {}, for key: {}".format(value, trigger_result[key], key)
            )

def find_data_in_audit_for_event(data, filters, event_type, after=None):
    """
    Walk the data provided for the event that we want to collect.
    :param data: An audit result of type JSON
    :param filters: The group of key value pairs which represent the event we want to find
    :param event_type: The event type Enum value we will first filter for.
    :param after: filter events to after this timestamp
    :return: The event or list of events we want, or None
    """
    # Capture this test's own ground-truth filters as the event buffer audit
    # metadata. This is done per-test (each test filters the shared audit with
    # its own criteria) and before any filter mutation below, so the recorded
    # metadata reflects exactly what the test searched for.
    record_event_buffer_audit_metadata(filters)

    if data is None or data.get("eventItem") is None:
        return None

    # Collect only specific event type
    events_of_type = [item[event_type] for item in data.get("eventItem") if event_type in item]
    events_of_type.reverse()

    if event_type == "fileWriteEvent" and "fullPath" in filters.keys():
        filters["fullPath"] = full_path_to_lowercase(filters, iterate=False)
        data = full_path_to_lowercase(data)

    # Windows image names are case-insensitive, and the agent reports the image that
    # actually ran: on Windows 11 the System32 notepad.exe hands off to the Store app,
    # reported as "Notepad.exe". Compare imageLoadEvent "process" case-insensitively
    # (filter and events lowercased in place, so eval_agent_event_results agrees too).
    if event_type == "imageLoadEvent" and "process" in filters.keys():
        filters["process"] = image_load_process_to_lowercase(filters, iterate=False)
        image_load_process_to_lowercase(data)

    # Perform case-insensitive comparisons on regKeyEvents.
    if (event_type == "regKeyEvent" and "path" in filters.keys() and "keyPath" in filters.keys() and "hive"
                in filters.keys()):
        filters["path"] = path_to_uppercase(filters, iterate=False)
        filters["keyPath"] = key_path_to_uppercase(filters, iterate=False)
        filters["hive"] = hive_to_uppercase(filters, iterate=False)

    logger.info(f"Filtering {len(events_of_type)} events to find:\n{json.dumps(filters, indent=2)}")

    # Filter out events before timestamp
    if after:
        logger.info(f"After: {after.isoformat()}")
        events = list(
            filter(lambda x: dateutil.parser.isoparse(x["timestamp"]) >= after, events_of_type)
        )
    else:
        events = events_of_type

    def filter_func(item):
        return all([item.get(key, None) == val for key, val in filters.items()])

    if event_type == "processEvent" and "pid" in filters.keys():
      logger.debug("Potential event(s):")
      [logger.debug(f"{json.dumps(x, indent=2)}") for x in events if x["pid"] == filters["pid"] and x["eventType"] == "start"]
      
    matching_events = list(filter(filter_func, events))
    if matching_events:
        event = matching_events[0]
        logger.info(f"Target event found:\n{json.dumps(event, indent=2)}")
    else:
        def partial_filter_func(item):
            # specify at least 2 matches since certain keys can be very common such as username
            return len(list(filter(bool, [item.get(key, None) == val for key, val in filters.items()]))) >= 2
        matching_events = filter(partial_filter_func, events)
        logger.warning("Target event not found")
        logger.debug("Partial matches found: ")
        for event in matching_events:
            logger.debug(f"\n{json.dumps(event, indent=2)}")
        return None

    return event


def retrieve_event_in_audit(filters, start_time, event_type):
    xclient = Singleton_XClient()
    data = collect_event_buffer_audit(xclient, start_time, "eventbuffer check", event_type)
    return find_data_in_audit_for_event(data=data, filters=filters, event_type=event_type)


def collect_event_buffer_audit(xclient, timestamp, notes, event_type):
    if isinstance(timestamp, datetime.datetime):
        # Here we need to have the timestamp in the proper format, so force it
        timestamp = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    logger.info(f"check for events after timestamp: {str(timestamp)}")
    data = xclient.run_job(
        "eventbuffer",
        params={"eventTypes": event_type, "intervalStart": str(timestamp)},
        notes="{}".format(notes if notes else "eventBuffer audit collection"),
    )
    return data


def run_triggers_collect_results(
    trigger_list, event_keys, start_time, event_type
):
    """
    This function will run many triggers sequentially, bundle the results, and try to ensure that
    the last event was collected before returning.
    :param trigger_list: Either a list of bare trigger classes, or a tuple with a class, and
        the kwargs needed for the trigger
    :param event_keys: The keys that can be used when comparing product results with trigger results
    :param start_time: Time for filtering the audit results
    :param event_type: The specific event type(s) to include in the audit results
    :return: A dict with the results of the triggers using the trigger class name as a key
    """

    collected_results = {}
    final_filter = None

    logger.info(f"Triggering {len(trigger_list)} events")
    for event_class in trigger_list:
        if isinstance(event_class, tuple):
            # Here we make a hard assumption that specific args are being passed to the trigger
            # constructor. This is used only to maintain flexibility
            event_class, kwargs = event_class
            trigger_event = event_class(**kwargs)
        else:
            trigger_event = event_class()
        logger.info("Triggering: {}".format(event_class.__name__))
        result = trigger_event.trigger()
        cleaned_result = {key: value for key, value in result.items() if key in event_keys}
        collected_results[event_class.__name__] = {
            "results": cleaned_result,
            "trigger": trigger_event,
        }
        final_filter = {key: cleaned_result[key] for key in event_keys if key in cleaned_result}

    # This event check is to ensure that the last event was collected.
    logger.info(f"Waiting for final event to appear in buffer, filter: {final_filter}")
    start_time = start_time if start_time else trigger_event.trigger_timestamp
    agent_event = func_wait(
        retrieve_event_in_audit,
        interval=5,
        timeout=120,
        filters=final_filter,
        start_time=start_time,
        event_type=event_type,
    )
    if not agent_event:
        logger.warning("Final event not found before timeout, potential failures ahead")
        logger.warning("missing event: {}".format(collected_results[type(trigger_event).__name__]))
    else:
        logger.info("Found final event")
    return collected_results
