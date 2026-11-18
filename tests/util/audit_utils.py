"""Helpers for the audit tests."""


def create_test_socket_list(tcp_port, udp_port):
    test_socket_ports = [
        {
            "isIPv6": "true",
            "process": "python",
            "state": "LISTENING",
            "localIP": "0000:0000:0000:0000:0000:0000:0000:0001",
            "remoteIP": "0000:0000:0000:0000:0000:0000:0000:0000",
            "localPort": tcp_port,
            "remotePort": 0,
            "protocol": "TCP",
        },
        {
            "isIPv6": "true",
            "process": "python",
            "state": "UNKNOWN",
            "localIP": "0000:0000:0000:0000:0000:0000:0000:0001",
            "remoteIP": "0000:0000:0000:0000:0000:0000:0000:0000",
            "localPort": udp_port,
            "remotePort": 0,
            "protocol": "UDP",
        },
    ]
    return test_socket_ports
