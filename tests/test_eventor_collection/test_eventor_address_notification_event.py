import datetime
import pytest
import pytz
from tests.test_eventor_collection.address_notification_events import AddressNotificationEvent
from tests.util.util import func_wait
from tests.util.eventor_utils import retrieve_event_in_audit, eval_agent_event_results, EventTypes

pytestmark = pytest.mark.eventor


@pytest.fixture(scope="session")
def platform_keys():
    return ["address"]


@pytest.mark.smoke
def test_address_notification_events(side_loading_setup, platform_keys):
    address_notification_event = AddressNotificationEvent()
    collected_info = address_notification_event.trigger()
    filter_key_val = {"address": collected_info["address"]}
    tic = (
        datetime.datetime.utcnow().replace(tzinfo=pytz.UTC) - datetime.timedelta(0, 10)
    ).isoformat()

    agent_result = func_wait(
        retrieve_event_in_audit,
        timeout=60,
        filters=filter_key_val,
        start_time=tic,
        event_type=EventTypes.ADDRESS_NOTIFICATION_EVENT.value,
    )

    assert agent_result, "Agent should have address notification events captured within the timeout"

    if agent_result:
        cleaned_results = {
            key: value for key, value in collected_info.items() if key in platform_keys
        }
        if cleaned_results:
            eval_agent_event_results(cleaned_results, agent_result)