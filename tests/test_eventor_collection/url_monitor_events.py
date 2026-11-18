import logging
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from tests.test_eventor_collection.event import Event

logger = logging.getLogger("tests")


# We need to avoid the CDA network proxy for these tests to work, hence the blank proxies here.
NO_PROXY_DICT = {
    "http": "",
    "https": ""
}


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GET Handled")

    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"POST Handled")

    def do_PUT(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"PUT Handled")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_DELETE(self):
        self.send_response(200)
        self.end_headers()

    def do_PATCH(self):
        self.send_response(200)
        self.end_headers()

    def do_TRACE(self):
        self.send_response(200)
        self.end_headers()

    def do_CONNECT(self):
        self.send_response(200)
        self.end_headers()

    def do_LINK(self):
        self.send_response(200)
        self.end_headers()

    def do_UNLINK(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return


class UrlMonitorHttpServer:
    def __init__(self, ip: str = "localhost", port: int = 8000):
        self.ip = ip
        self.port = port
        self.server = HTTPServer((self.ip, self.port), SimpleHTTPRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True

    def start(self):
        self.server_thread.start()

    def stop(self):
        self.server.shutdown()
        self.server_thread.join()


# The agent ignores loopback traffic (requests to UrlMonitorHttpServer on this host are never
# reported), so the triggers use an external host. httpbin.org/anything answers every common
# method over plain HTTP without redirecting to HTTPS or bot-blocking scripted clients.
URL_MONITOR_HOST = "httpbin.org"
URL_MONITOR_PORT = 80
URL_MONITOR_PATH = "/anything"


def url_monitor_host_addresses():
    """All IPv4 addresses URL_MONITOR_HOST resolves to (it rotates between several)."""
    return socket.gethostbyname_ex(URL_MONITOR_HOST)[2]


class UrlMonitorEvent(Event):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__()
        self.http_response = None
        self.request_error = None
        self.port = port
        self.path = path
        self.remote_host = remote_host
        self.result_info["hostname"] = self.remote_host if self.port == 80 else f"{self.remote_host}:{self.port}"
        self.result_info["requestUrl"] = self.path
        # Informational only: the host has several addresses and requests may connect to any of them.
        self.result_info["remoteIpAddress"] = socket.gethostbyname(self.remote_host)
        self.result_info["remotePort"] = self.port
        self.result_info["userAgent"] = requests.utils.default_headers()["User-Agent"]
        self.url = f"http://{self.result_info['hostname']}{self.path}"

    def get_url_method(self):
        return self.result_info["urlMethod"]

    def get_http_response(self):
        return self.http_response

    def send_request(self, **kwargs):
        """Send this event's request; a connection error is kept in request_error rather than raised,
        so one dropped request doesn't stop the other triggers of a bulk run."""
        try:
            self.http_response = requests.request(
                method=self.result_info["urlMethod"], url=self.url, proxies=NO_PROXY_DICT,
                timeout=30, **kwargs)
        except requests.RequestException as e:
            self.request_error = e
            logger.warning("%s request to %s failed: %s", self.result_info["urlMethod"], self.url, e)

# Mimic a standard Windows Chrome browser header
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

class GetUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "GET"

    def trigger_func(self):
        self.send_request(headers=headers)


class PostUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "POST"

    def trigger_func(self):
        self.send_request(headers=headers)


class PutUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "PUT"

    def trigger_func(self):
        self.send_request(headers=headers)


class HeadUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "HEAD"

    def trigger_func(self):
        self.send_request()


class OptionsUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "OPTIONS"

    def trigger_func(self):
        self.send_request(headers=headers)


class DeleteUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "DELETE"

    def trigger_func(self):
        self.send_request(headers=headers)


class PatchUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "PATCH"

    def trigger_func(self):
        self.send_request(headers=headers)


class TraceUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "TRACE"

    def trigger_func(self):
        self.send_request(headers=headers)


class ConnectUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "CONNECT"

    def trigger_func(self):
        self.send_request(headers=headers)


class LinkUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "LINK"

    def trigger_func(self):
        self.send_request(headers=headers)


class UnlinkUrlMonitorEvent(UrlMonitorEvent):
    def __init__(self, remote_host: str = URL_MONITOR_HOST, port: int = URL_MONITOR_PORT,
                 path: str = URL_MONITOR_PATH):
        super().__init__(remote_host, port, path)
        self.result_info["urlMethod"] = "UNLINK"

    def trigger_func(self):
        self.send_request(headers=headers)