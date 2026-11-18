import logging
import socket

from tests.test_eventor_collection.event import Event
from tests.util.util import release_and_renew_ip

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect or send data, just routes the request locally
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

class AddressNotificationEvent(Event):
    def __init__(self):
        super().__init__()
        local_ip = get_local_ip()
        self.result_info["address"] = local_ip
        logging.info(f"Initial local IP address: {local_ip}")

    def trigger_func(self):
        logging.info("Releasing and renewing IP address...")
        new_ipv4_address = release_and_renew_ip()
        self.result_info["address_to_verify"] = new_ipv4_address
        logging.info(f"IP address release and renewal completed. New IPv4 address: {new_ipv4_address}")
