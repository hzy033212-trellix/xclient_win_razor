import pytest

from tests.test_eventor_collection.dns_lookup_events import DnsLookupEventIPv4
from tests.util.ioc_batch import IocCase, run_ioc_case

pytestmark = pytest.mark.ioc

IOC_CASES = {
    "test_ioc_dns_lookup_event": IocCase("dns", lambda _: DnsLookupEventIPv4(), ["hostname"]),
}


def test_ioc_dns_lookup_event(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)
