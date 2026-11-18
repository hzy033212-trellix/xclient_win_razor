from tests.util.sys_utils import SysUtils
from tests.test_eventor_collection.event import Event


class DnsLookupEvent(Event):
    def __init__(self):
        super().__init__()
        self.result_info["hostname"] = "www.trellix.com"


class DnsLookupEventIPv4(DnsLookupEvent):
    def __init__(self):
        super().__init__()

    def trigger_func(self):
        SysUtils.flush_dns_win()
        SysUtils.ping_win(self.result_info["hostname"])


class DnsLookupEventIPv6(DnsLookupEvent):
    def __init__(self):
        super().__init__()

    def trigger_func(self):
        SysUtils.flush_dns()
        SysUtils.ping6(self.result_info["hostname"])