import pytest

from tests.test_eventor_collection.address_notification_events import AddressNotificationEvent
from tests.util.ioc_batch import IocCase, run_ioc_case

pytestmark = pytest.mark.ioc


# Runs unconditionally, like test_eventor_address_notification_event.py. The
# trigger runs ipconfig /release + /renew, which briefly drops all network
# connections (an RDP session reconnects afterwards); hxsim is on loopback, so
# alert delivery is unaffected. Each addressNotificationEvent lists every current
# address, so the alert carries the primary IPv4 address the filter expects.
# Primed last: the dropped connections would break the triggers fired after it.
IOC_CASES = {
    "test_ioc_address_notification_event": IocCase(
        "address", lambda _: AddressNotificationEvent(), ["address"], prime_last=True),
}


def test_ioc_address_notification_event(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)
