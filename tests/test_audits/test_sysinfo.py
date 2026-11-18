import logging
import platform
import socket
import os
from sys import getwindowsversion

import pytest
from tests.util import paths
from tests.util import util
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util.fixtures_audits import get_active_directory_domain_name

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


def _netbios_domain():
    """The NetBIOS name of the domain or workgroup this host is joined to (NetGetJoinInformation),
    or None if it can't be read."""
    import ctypes
    from ctypes import wintypes
    name = wintypes.LPWSTR()
    status = wintypes.DWORD()
    netapi = ctypes.WinDLL("netapi32")
    if netapi.NetGetJoinInformation(None, ctypes.byref(name), ctypes.byref(status)) != 0:
        return None
    try:
        return name.value
    finally:
        netapi.NetApiBufferFree(name)


# Function scoped on purpose: each test runs its own audit with its own
# ``<test case name>.json`` script, and keeps the script and outputs in
# its own temp/<script>/<test>/ folder.
@pytest.fixture(scope="function")
def sysinfo():
    xclient = Singleton_XClient()
    data = xclient.run_job("sysinfo", notes="sysinfo audit test")

    assert data, "Data for sysinfo audit should be part of the results"
    yield data


def get_sysinfo_item(item, sysinfo_data):
    return sysinfo_data["SystemInfoItem"][0][item]


def get_windows_version():
    os_version = platform.release()
    assert os_version, "Python should be able to determine Windows release version"

    # Windows 11 has build number >= 22000
    # Refer: https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information
    if getwindowsversion().build >= 22000:
        os_version = "11"
    elif getwindowsversion().product_type != 1:  # Is a Windows server machine...
        os_version = "Server"

    return f"Windows {os_version}"


@pytest.fixture(scope="module")
def os_version():
    return get_windows_version()


@pytest.fixture(scope="function")
def sysinfo_version(sysinfo):
    return get_sysinfo_item("productName", sysinfo)


@pytest.mark.smoke
def test_os_version(side_loading_setup, sysinfo_version, os_version):
    assert (
        os_version in sysinfo_version
    ), f"The agent should report the correct version, {os_version}, but instead reported {sysinfo_version}"


@pytest.mark.smoke
def test_audit_sysinfo(side_loading_setup, sysinfo):
    hostname = socket.gethostname()
    audit_hostname = None
    for sys_info_item in sysinfo["SystemInfoItem"]:
        if "hostname" in sys_info_item:
            audit_hostname = sys_info_item["hostname"]

    assert (
        audit_hostname.lower() in hostname.lower()
    ), "Sysinfo audit should capture correct hostname"


def test_audit_sysinfo_for_win(side_loading_setup, sysinfo):
    cache = os.popen("SYSTEMINFO")
    source = cache.read()
    src = source.split('\n')
    src_dict = {s.split(': ')[0].strip() : s.split(': ')[1].strip() for s in src if ': ' in s and not s == ''}

    for sys_info_item in sysinfo["SystemInfoItem"]:
        if "hostname" in sys_info_item:
            assert(src_dict['Host Name'].lower() == sys_info_item["hostname"].lower()),\
                   "Information {0} and {1} doesn't match".format(src_dict['Host Name'].lower(),
                                                                  sys_info_item["hostname"].lower())

        if "machine" in sys_info_item:
            assert(platform.node().lower() == sys_info_item["machine"].lower()),\
                "Information {0} and {1} doesn't match".format(platform.node().lower(),
                                                               sys_info_item["machine"].lower())

        if "biosInfo" in sys_info_item:
            bios_info = dict(sys_info_item["biosInfo"])
            if sys_info_item["biosInfo"]["biosVersion"]+", "+sys_info_item["biosInfo"]["biosDate"] == \
                    src_dict['BIOS Version']:
                assert (sys_info_item["biosInfo"]["biosVersion"]+", "+sys_info_item["biosInfo"]["biosDate"] ==
                        src_dict['BIOS Version']), "Information {0} and {1} doesn't match".\
                    format(sys_info_item["biosInfo"]["biosVersion"]+", "+sys_info_item["biosInfo"]["biosDate"],
                           src_dict['BIOS Version'])
            else:
                # SYSTEMINFO reports the BIOS date without leading zeros (e.g. 8/5/2026),
                # so fall back to the BIOS registry subkey the audit itself reads from:
                # biosVersion == "<BIOSVendor> <BIOSVersion>" and biosDate == BIOSReleaseDate.
                res = os.popen(r"reg query HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\BIOS /v BIOSVendor")
                info = res.read()
                bios_vendor = info.split("\n")[2].split("REG_SZ")[1].strip()
                res = os.popen(r"reg query HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\BIOS /v BIOSVersion")
                info = res.read()
                bios_version = info.split("\n")[2].split("REG_SZ")[1].strip()
                res = os.popen(r"reg query HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\BIOS /v BIOSReleaseDate")
                info = res.read()
                bios_info_date = info.split("\n")[2].split("REG_SZ")[1].strip()
                bios_info_system = bios_vendor + " " + bios_version
                assert (bios_info_system + ", " + bios_info_date ==
                        sys_info_item["biosInfo"]["biosVersion"]+", "+sys_info_item["biosInfo"]["biosDate"]), \
                    "Information {0} and {1} doesn't match".format(bios_info_system + ", " + bios_info_date,
                                                                   sys_info_item["biosInfo"]["biosVersion"]+", "+
                                                                   sys_info_item["biosInfo"]["biosDate"])

        if "directory" in sys_info_item:
            assert (src_dict['System Directory'] == sys_info_item['directory']),\
                "Information {0} and {1} doesn't match".format(src_dict['System Directory'],
                                                               sys_info_item['directory'])

        if "procType" in sys_info_item:
            assert (src_dict['OS Build Type'] == sys_info_item["procType"]), \
                "Information {0} and {1} doesn't match".format(src_dict['OS Build Type'],
                                                               sys_info_item["procType"])

        if "regOwner" in sys_info_item:
            assert (src_dict['Registered Owner'] == sys_info_item["regOwner"]),\
                "Information {0} and {1} doesn't match".format(src_dict['Registered Owner'],
                                                               sys_info_item["regOwner"])

        if "processor" in sys_info_item:
            source1 = os.popen("wmic cpu get name").read()
            assert (source1.split('\n')[2].strip() == sys_info_item["processor"]),\
                "Information {0} and {1} doesn't match".format(source1.split('\n')[2].strip(),
                                                               sys_info_item["processor"])

        if "OS" in sys_info_item:
            if "Windows 11" in sys_info_item["OS"]:
                # SYSTEMINFO's OS Name carries the edition (e.g. "Pro", "Enterprise N")
                # which the audit's OS field omits, so compare against the family + build only.
                os_family = "Microsoft Windows 11"
                os_version = src_dict['OS Version'].split('Build')[1].strip()
                expected = os_family + " " + os_version
                assert (src_dict['OS Name'].startswith(os_family)
                        and expected == "Microsoft " + sys_info_item["OS"]), \
                    "Information {0} and {1} doesn't match".format(expected, "Microsoft " +
                                                                   sys_info_item["OS"])
            else:
                info = os.popen(r"reg query \"hklm\software\microsoft\windows nt\currentversion\" /v ProductName").read()
                if sys_info_item["OS"] == info.split("\n")[2].split("REG_SZ")[1].strip():
                    assert (sys_info_item["OS"] == info.split("\n")[2].split("REG_SZ")[1].strip()), \
                        "Information {0} and {1} doesn't match".\
                            format(sys_info_item["OS"],info.split("\n")[2].split("REG_SZ")[1].strip())
                else:
                    info2 = os.popen(r"reg query \"hklm\software\microsoft\windows nt\currentversion\" /v CSDVersion").read()
                    if "CSDVersion" not in info2.split("\n")[2]:
                        info2 = os.popen(r"reg query \"hklm\software\microsoft\windows nt\currentversion\" /v CurrentBuild").read()
                    if sys_info_item["OS"] == \
                            info.split("\n")[2].split("REG_SZ")[1].strip() + " " +\
                            info2.split("\n")[2].split("REG_SZ")[1].strip():
                        assert (sys_info_item["OS"] ==
                                info.split("\n")[2].split("REG_SZ")[1].strip() + " " +
                                info2.split("\n")[2].split("REG_SZ")[1].strip()), \
                            "Information {0} and {1} doesn't match".format(sys_info_item["OS"],
                                                                   info.split("\n")[2].split("REG_SZ")[1].strip())
                    else:
                        assert (sys_info_item["OS"] ==
                                info.split("\n")[2].split("REG_SZ")[1].strip() + " " +
                                src_dict['OS Version'].split('Build')[1].strip() + " " +
                                info2.split("\n")[2].split("REG_SZ")[1].strip()), \
                            "Information {0} and {1} doesn't match".format(sys_info_item["OS"],
                                                                   info.split("\n")[2].split("REG_SZ")[1].strip())

        if "productName" in sys_info_item:
            if "Windows 11" in sys_info_item["productName"]:
                # SYSTEMINFO's OS Name carries the edition the audit's productName omits,
                # so require OS Name to start with "Microsoft <productName>".
                os_name = src_dict['OS Name'].strip()
                assert (os_name.startswith("Microsoft " + sys_info_item["productName"])), \
                    "Information {0} and {1} doesn't match".format(os_name ,"Microsoft " + sys_info_item["productName"])
            else:
                info = os.popen(r"reg query \"hklm\software\microsoft\windows nt\currentversion\" /v ProductName").read()
                if sys_info_item["productName"] == info.split("\n")[2].split("REG_SZ")[1].strip():
                    assert (sys_info_item["productName"] == info.split("\n")[2].split("REG_SZ")[1].strip()), \
                        "Information {0} and {1} doesn't match".format(sys_info_item["productName"],
                                                                       info.split("\n")[2].split("REG_SZ")[1].strip())
                else:
                    info2 = os.popen(r"reg query \"hklm\software\microsoft\windows nt\currentversion\" /v CSDVersion").read()
                    assert (sys_info_item["productName"] == info.split("\n")[2].split("REG_SZ")[1].strip() + " " +
                            info2.split("\n")[2].split("REG_SZ")[1].strip()), \
                        "Information {0} and {1} doesn't match".format(sys_info_item["productName"],
                                                                   info.split("\n")[2].split("REG_SZ")[1].strip())

        if "buildNumber" in sys_info_item:
            os_version = src_dict['OS Version'].split('Build')[1].strip()
            assert (os_version == sys_info_item["buildNumber"]), \
                "Information {0} and {1} doesn't match".format(os_version,
                                                               sys_info_item["buildNumber"])

        if "productID" in sys_info_item:
            assert (src_dict['Product ID'] == sys_info_item["productID"]), \
                "Information {0} and {1} doesn't match".format(src_dict['Product ID'],
                                                               sys_info_item["productID"])


        if "OSbitness" in sys_info_item:
            bit = "64-bit" if util.is_x64() else "32-bit"
            assert (bit == sys_info_item['OSbitness']), \
                "Information {0} and {1} doesn't match".format(bit, sys_info_item['OSbitness'])


        if "domain" in sys_info_item:
            # systeminfo shows a joined domain's DNS name (cda.bea.lab); XClient reports its NetBIOS
            # name (CDA). On a workgroup host both are the workgroup name.
            names = {src_dict['Domain'].lower()}
            netbios = _netbios_domain()
            if netbios:
                names.add(netbios.lower())
            assert sys_info_item["domain"].lower() in names, \
                "Domain {0} is none of {1}".format(sys_info_item["domain"], sorted(names))

        if "networkArray" in sys_info_item:
            net_array = sys_info_item["networkArray"].pop(0)
            if "ipArray" in net_array:
                ipv6_addr = net_array["ipArray"].pop(0)
                if "ipv6Address" in ipv6_addr:
                    hostname = socket.gethostname()
                    ip_detail = socket.getaddrinfo(hostname, 80)
                    for ip in ip_detail:
                        if str(ip[0]).split(":")[0] == 'AddressFamily.AF_INET6':
                            assert (ip[4][0] == ipv6_addr["ipv6Address"]), \
                                "Information {0} and {1} doesn't match".format(ip[4][0], ipv6_addr["ipv6Address"])
                            break

        if "primaryIpv4Address" in sys_info_item:
            # A host can have several adapters: the primary address must be one of the host's.
            hostname = socket.gethostname()
            ipaddrs = set(socket.gethostbyname_ex(hostname)[2])
            ipaddrs.update(a[4][0] for a in socket.getaddrinfo(hostname, None, socket.AF_INET))
            assert sys_info_item["primaryIpv4Address"] in ipaddrs, \
                "primaryIpv4Address {0} is none of the host's {1}".format(sys_info_item["primaryIpv4Address"],
                                                                         sorted(ipaddrs))

        if "totalphysical" in sys_info_item:
            # Converting Bytes to MB
            physical_mem = str(int(int(sys_info_item["totalphysical"]) / (1024 * 1024))) + " MB"
            assert (src_dict['Total Physical Memory'].replace(',', '') == physical_mem), \
                "Information {0} and {1} doesn't match".format(src_dict['Total Physical Memory'], physical_mem)

        if "availphysical" in sys_info_item:
            # Converting Bytes to MB
            physical_mem = int(sys_info_item["availphysical"]) / (1024*1024)
            min_range = int(src_dict['Available Physical Memory'].split(" ")[0].replace(',',"")) - 500
            max_range = int(src_dict['Available Physical Memory'].split(" ")[0].replace(',',"")) + 500
            assert (min_range <= physical_mem <= max_range), \
                "Available Memory is not in range {0} <= {1} <= {2}".format(min_range, physical_mem, max_range)

        if "appVersion" in sys_info_item:
            res = os.popen("\"{}\" -v".format(paths.XCLIENT_EXE))
            # xclient reports e.g. "v50.3.0.17706"; the audit's appVersion is the 3-part version.
            full_version = res.read().split("\n")[0].strip().lstrip("v")
            agent_version = ".".join(full_version.split(".")[:3])
            assert (agent_version == sys_info_item["appVersion"]), \
                "Information {0} and {1} doesn't match".format(agent_version, sys_info_item["appVersion"])

        if "platform" in sys_info_item:
            assert (platform.system().lower()[0:3] == sys_info_item["platform"]), \
                "Information {0} and {1} doesn't match".format(platform.system().lower()[0:3],
                                                               sys_info_item["platform"])


def test_audit_active_directory_sysinfo(side_loading_setup, sysinfo, get_active_directory_domain_name):
    active_directory_info = get_active_directory_domain_name
    audit_active_directory_info = ""
    for sys_info_item in sysinfo["SystemInfoItem"]:
        if "ADInfo" in sys_info_item:
            audit_active_directory_info = sys_info_item["ADInfo"]
            break

    assert (
        audit_active_directory_info == active_directory_info
    ), "Sysinfo audit should capture correct active directory info"