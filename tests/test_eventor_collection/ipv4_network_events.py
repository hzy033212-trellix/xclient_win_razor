import ipaddress
import logging
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import psutil
import pytz

from tests.util.constants import IPV4_TARGET, IPV6_TARGET
from tests.test_eventor_collection.event import Event
from tests.util.util import (
    get_ip_addresses,
    is_ipv6_capable,
    get_primary_ipv4_address,
    get_primary_ipv6_address,
)

logger = logging.getLogger("razor")


class IPv4NetworkEvent(Event):
    """
    This base class will hold common information about all IPv4 events.
    Event fields for IPv4NetworkEvent:
    event_id
    type_id
    timestamp
    sequence_num
    pid: n % 4 = 0
    ppath: process path
    username: computername/username
    remotePort: 0-65536
    localPort: 0-65536
    ipv6: flag indicating if result is ipv6 or not
    protocol: possible protocols
    (HOPOPT, ICMP, IGMP, GGP, IPV4ENC, ST, TCP, CBT, EGP, IGP, BBN-RCC-MON, NVP-II, PUP, ARGUS,
    EMCON, XNET, CHAOS, UDP, MUX, DCN-MEAS, HMP, PRM, XNS-IDP, TRUNK-1, TRUNK-2, LEAF-1, LEAF-2,
    RDP, IRTP, ISO-TP4, NETBLT, MFE-NSP, MERIT-INP, DCCP, 3PC, IDPR, XTP, DDP, IDPR-CMTP, TP++, IL,
    IPV6ENC, SDRP, IPV6-ROUTE, IPV6-FRAG, IDRP, RSVP, GRE, MHRP, BNA, ESP, AH, I-NLSP, SWIPE, NARP,
    MOBILE, TLSP, SKIP, IPV6-ICMP, IPV6-NONXT, IPV6-OPTS, ANYHOST, CFTP, ANYNET, SAT-EXPAK,
    KRYPTOLAN, RVD, IPPC, ANYFILE, SAT-MON, VISA, IPCV, CPNX, CPHB, WSN, PVP, BR-SAT-MON, SUN-ND,
    WB-MON, WB-EXPAK, ISO-IP, VMTP, SECURE-VMTP, VINES, TTP/IPTM, NSFNET-IGP, DGP, TCF, EIGRP,
    OSPF, SPRITE-RPC, LARP, MTP, AX.25, IPIP, MICP, SCC-SP, ETHERIP, ENCAP, ANYCRYPT, GMTP, IFMP,
    PNNI, PIM, ARIS, SCPS, QNX, A/N, IPCOMP, SNP, COMPAQ-PEER, IPX-IN-IP, VRRP, PGM, ANY0HOP, L2TP,
    DDX, IATP, STP, SRP, UTI, SMP, SM, PTP, IS-IS, FIRE, CRTP, CRUDP, SSCOPMCE, IPLT, SPS, PIPE,
    SCTP, FC, RSVP-E2E-IGNORE, MOBILITY-HEADER, UDP-LITE, MPLS-IN-IP, MANET, HIP, SHIM6)
    """

    def __init__(self):
        super().__init__()
        self.ext_ipv6, self.ext_ipv4, self.local_ipv6, self.local_ipv4 = get_ip_addresses()
        self.ipv6_capable = is_ipv6_capable()

        # set some common result_info
        self.result_info["processPath"] = str(Path(self.result_info["processPath"]).parent)

class PythonIPv4NetworkEvent(IPv4NetworkEvent):
    """
    Class which relies totally on internal python code in order to generate the events in
    question.
    """

    def __init__(
        self,
        address: Optional[Union[ipaddress.IPv6Address, ipaddress.IPv4Address]] = None,
        port: Optional[int] = None,
    ):
        self.address = address if address else ipaddress.ip_address(IPV4_TARGET)
        if not isinstance(self.address, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            raise ipaddress.AddressValueError("You must provide an ipaddress object")
        self.port = port if port else 80
        super().__init__()


class PythonHTTPEvent(PythonIPv4NetworkEvent):
    """
    Basic HTTP connection event trigger. This will initiate a HTTP request to a server.
    """

    def __init__(
        self,
        address: Optional[Union[ipaddress.IPv6Address, ipaddress.IPv4Address]] = None,
        port: Optional[int] = None,
        socket_type: Optional[socket.SocketKind] = None,
        address_family: Optional[socket.AddressFamily] = None,
    ):
        self.socket_type = socket_type if socket_type else socket.SOCK_STREAM
        self.address_family = address_family if address_family else socket.AF_INET
        super().__init__(address=address, port=port)

    def pre_trigger_func(self):
        """
        Common pre-trigger runner action.
        :return: N/A
        """
        self.result_info["timestamp"] = datetime.utcnow().replace(tzinfo=pytz.UTC)

    def collect_info(self, sock):
        """
        Collects specific information relevant to the trigger action
        :param sock: socket object which was used
        :return: N/A
        """
        self.result_info["protocol"] = "TCP"
        cli_addr, cli_port = sock.getsockname()
        srv_addr, srv_port = sock.getpeername()
        self.result_info["remoteIP"] = srv_addr
        self.result_info["localIP"] = cli_addr
        self.result_info["localPort"] = cli_port
        self.result_info["remotePort"] = self.port if self.port else srv_port

    def trigger_func(self):
        """
        Initiate an HTTP request which is successful. Collect and track the related information
        for comparing to agent results.
        :return: result_info dictionary
        :rtype: dict
        """
        # logging.info(" ========== ")
        # logging.info("Enter trigger func for PythonHTTPEvent!!!!!")
        # logging.info("Remote IP address : " + self.address.exploded)
        # logging.info("Remote port is : " + str(self.port))
        # logging.info(" ========== ")
        # time.sleep(10)
        sock = socket.socket(self.address_family, self.socket_type)
        sock.settimeout(20)
        try:
            sock.connect((self.address.exploded, int(self.port)))
        except OSError:
            raise OSError("Connection attempt was unsuccessful, trigger use failed.")
        finally:
            self.collect_info(sock)
            sock.close()


class PythonHTTPEventIPv4(PythonHTTPEvent):
    """
    Basic IPv4 only HTTP event trigger
    """

    pass


class PythonHTTPEventIPv6(PythonHTTPEvent):
    """
    Basic IPv6 only HTTP event trigger
    """

    def __init__(
        self, address: Optional[ipaddress.IPv6Address] = None, port: Optional[int] = None,
    ):
        address_family = socket.AF_INET6
        address = address if address else ipaddress.ip_address(IPV6_TARGET)
        super().__init__(address=address, port=port, address_family=address_family)
        if not self.ipv6_capable:
            raise OSError(
                "OS cannot successfully create the IPv6 connection, trigger cannot be used."
            )

    def trigger_func(self):
        """
        Initiate an HTTP request which is successful. Collect and track the related information
        for comparing to agent results.
        :return: result_info dictionary
        :rtype: dict
        """
        # logging.info(" ========== ")
        # logging.info("Enter trigger func for PythonHTTPEventIPv6!!!!!")
        # logging.info(" ========== ")
        # time.sleep(10)
        super().trigger_func()


class PythonICMPEvent(PythonIPv4NetworkEvent):
    """
    Basic ICMP trigger base class for both the IPv6 and IPv4 triggers.
    """

    def __init__(
        self,
        address: Optional[Union[ipaddress.IPv6Address, ipaddress.IPv4Address]] = None,
        wait_to_complete=False,
    ):
        self.wait_to_complete = wait_to_complete
        super().__init__(address=address, port=0)

    def build_ping_command(self, count=4, ipv6=False):
        """
        Prepares ping command to run
        """
        command = ["ping", "-n", str(count), self.address.exploded]
        if ipv6:
            command.insert(1, "-6")
        return command

    def exec_ping_no_wait(self, command):
        """
        Launch the command and return
        """
        self.result_info["pid"] = subprocess.Popen(command, shell=False).pid
        try:
            psutil_info = psutil.Process(pid=self.result_info["pid"]).as_dict()
            self.result_info["process"] = psutil_info["name"]
            # Per the psutil docs "exe" will sometimes return None, so we have a fallback
            if psutil_info["exe"] is not None:
                self.result_info["processPath"] = str(Path(psutil_info["exe"]).parent)
            else:
                ping_path = shutil.which(command[0])
                self.result_info["processPath"] = str(Path(ping_path).parent)
            self.result_info["username"] = psutil_info["username"]
        except psutil.NoSuchProcess:
            # Fill in default values in the case that we were unable to resolve the ping information
            self.result_info["process"] = "PING.EXE"
            self.result_info["processPath"] = str(
                Path(shutil.which(self.result_info["process"])).parent
            )
            logger.debug("psutil_ping result info : {}".format(self.result_info))

    def psutil_ping(self, count=4, ipv6=False):
        """
        Custom ping usage solely b/c of the need to collect additional information about the ping
        process.
        :param ipv6: whether or not to make the ping action over ipv6 or ipv4
        :param count: number of times the ping utility should run
        :return: N/A
        """
        command = self.build_ping_command(count, ipv6)

        logger.info(
            "Running ping to {} with {} user".format(
                self.address.exploded, self.result_info["username"]
            )
        )

        self.exec_ping_no_wait(command)

    def collect_info(self):
        """
        Collect trigger action information
        :return:
        """
        self.result_info["remotePort"] = 0
        self.result_info["localPort"] = 0
        self.result_info["localIP"] = get_primary_ipv4_address().exploded
        self.result_info["remoteIP"] = self.address.exploded
        # On Windows ICMP events have fewer fields that expected
        self.result_info.pop("process")
        self.result_info.pop("processPath")
        self.result_info.pop("parentPid")
        # And 1 field will always be 0
        self.result_info["pid"] = 0

    def pre_trigger_func(self):
        """
        Pre trigger actions for ICMP events
        :return:
        """
        self.result_info["timestamp"] = datetime.utcnow().replace(tzinfo=pytz.UTC)


class PythonICMPEventIPv4(PythonICMPEvent):
    """
    Basic ICMPEvent trigger
    """

    def collect_info(self):
        """
        Collect trigger action information
        :return: N/A
        """
        super().collect_info()
        self.result_info["protocol"] = "ICMP"

    def trigger_func(self):
        """
        Run the needed trigger and ensure all needed information is collected
        :return: N/A
        """
        # logging.info(" ========== ")
        # logging.info("Enter trigger func for PythonICMPEvent!!!!!")
        # logging.info(" ========== ")
        # time.sleep(10)
        self.psutil_ping()
        # This is all an overwrite of the information set during class instantiation
        self.collect_info()


class PythonICMPEventIPv6(PythonICMPEvent):
    """
    Basic ICMPEvent trigger for IPv6
    """

    def __init__(
        self, address: Optional[ipaddress.IPv6Address] = None,
    ):
        address = address if address else ipaddress.ip_address(IPV6_TARGET)
        super().__init__(address=address)

    def collect_info(self):
        """
        Collect trigger action information
        :return: N/A
        """
        super().collect_info()
        self.result_info["localIP"] = get_primary_ipv6_address().exploded()
        self.result_info["protocol"] = "IPV6-ICMP"

    def trigger_func(self):
        """
        Run the needed trigger and ensure all needed information is collected
        :return: N/A
        """
        # logging.info(" ========== ")
        # logging.info("Enter trigger func for PythonICMPEventIPv6!!!!!")
        # logging.info(" ========== ")
        # time.sleep(10)
        self.psutil_ping(ipv6=True)
        self.collect_info()


class PythonUDPEvent(PythonIPv4NetworkEvent):
    def __init__(
        self,
        address: Optional[Union[ipaddress.IPv6Address, ipaddress.IPv4Address]] = None,
        port: Optional[int] = None,
        socket_type: Optional[socket.SocketKind] = None,
        address_family: Optional[socket.AddressFamily] = None,
        data: Optional[Union[bytes, bytearray, str]] = None,
    ):
        self.data = data if data else b"random UDP data"
        self.port = port if port else 5555
        self.socket_type = socket_type if socket_type else socket.SOCK_DGRAM
        self.address_family = address_family if address_family else socket.AF_INET
        # Pass the resolved port: with port=None the parent would reset it to its own default (80).
        super().__init__(address=address, port=self.port)

    def collect_info(self, sock):
        """
        Collects specific information relevant to the trigger action
        :param sock: socket object which was used
        :return: N/A
        """
        self.result_info["protocol"] = "UDP"
        _, cli_port = sock.getsockname()
        self.result_info["remotePort"] = self.port
        self.result_info["localPort"] = cli_port
        self.result_info["remoteIP"] = self.address.exploded

    def pre_trigger_func(self):
        """
        Actions to execute before the trigger
        :return: N/A
        """
        self.result_info["timestamp"] = datetime.utcnow().replace(tzinfo=pytz.UTC)

    def trigger_func(self):
        """
        Trigger which will send some UDP traffic to a remote location.
        :return: N/A
        """
        sock = socket.socket(self.address_family, self.socket_type)
        try:
            sock.sendto(self.data, (self.address.exploded, self.port))
        except Exception:
            raise Exception("Failed to send data to remote address")
        finally:
            self.collect_info(sock)
            sock.close()


class PythonUDPEventIPv4(PythonUDPEvent):
    """
    Basic UDP traffic generator trigger.
    """

    def __init__(
        self,
        address: Optional[ipaddress.IPv4Address] = None,
        port: Optional[int] = None,
        data: Optional[Union[bytes, bytearray, str]] = None,
    ):
        super().__init__(address=address, port=port, address_family=socket.AF_INET, data=data)

    def trigger_func(self):
        # logging.info(" ========== ")
        # logging.info("Enter trigger func for PythonUDPEvent!!!!!")
        # logging.info("Local IP address : " + get_primary_ipv4_address().exploded)
        # logging.info(" ========== ")
        # time.sleep(10)
        super().trigger_func()
        self.result_info["localIP"] = get_primary_ipv4_address().exploded


class PythonUDPEventIPv6(PythonUDPEvent):
    """
    UDP event trigger over IPv6.
    """

    def __init__(
        self,
        address: Optional[ipaddress.IPv6Address] = None,
        port: Optional[int] = None,
        data: Optional[Union[bytes, bytearray, str]] = None,
    ):
        super().__init__(address=address, port=port, address_family=socket.AF_INET6, data=data)

    def trigger_func(self):
        # logging.info(" ========== ")
        # logging.info("Enter trigger func for PythonUDPEventIPv6!!!!!")
        # logging.info("Remote IP address : " + get_primary_ipv6_address().exploded)
        # logging.info(" ========== ")
        # time.sleep(10)
        super().trigger_func()
        self.result_info["localIP"] = get_primary_ipv6_address().exploded
