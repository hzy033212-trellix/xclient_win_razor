import functools
import hashlib
import ipaddress
import json
import logging
import random
import re
import socket
import string
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import win32api
import win32con

logger = logging.getLogger("util")


def is_win():
    return "win32" in sys.platform


# Using the Trellix Artifactory instance (https://artifactory.trellix.com/) for IPv4 testing.
IPV4_TARGET = "10.40.6.239"

# Using ipv6.google.com for IPv6 testing
IPV6_TARGET = "2607:f8b0:4002:c11::71"


def run_windows_commands(command, log_option = 1):
    try:
        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            check=True
        )
        if log_option:
            logging.info(f"Success: {result.stdout}")
        else:
            logging.info("Success executed command!")
        return result.stdout
    except subprocess.CalledProcessError as e:
        logging.info(f"Error occurred: {e.stderr}")
        raise subprocess.CalledProcessError(e.returncode, command)


def get_fully_qualified_domain_name():
    try:
        return win32api.GetComputerObjectName(win32con.NameFullyQualifiedDN)
    except win32api.error as details:
        logger.error("Failed to get Active Domain Info: {}".format(details.strerror))
        return ""


def is_x64():
    import platform
    return platform.machine().lower() in ("amd64", "x86_64", "arm64", "aarch64", "ia64")


def get_files_in_folder(folder_path, recursive_search=True):
    """
    Get list of all files in a folder
    :param folder_path: folder to recursively search
    """
    for item in folder_path.iterdir():
        yield item
        if recursive_search and item.is_dir():
            yield from get_files_in_folder(item)


def func_wait(func, interval=5, timeout=300, negate=False, **kwargs):
    """
    Run a function every interval. On success return.

    :param func: function that runs some sort of check that returns a truthy or falsey value
    :param interval: interval to run function
    :param timeout: max time
    :param negate: negate return of function
    :param kwargs: arbitrary args to pass to function
    :return: return value of func either from first truthy value or last falsey value before timeout
    """
    start_time = time.time()
    result = not func(**kwargs) if negate else func(**kwargs)

    while not result and (time.time() - start_time) < timeout:
        time.sleep(interval)
        result = not func(**kwargs) if negate else func(**kwargs)

    return result


def dict_is_subset(subset, superset):
    for key, _ in subset.items():
        if key not in superset:
            return False

        if superset[key] != subset[key]:
            return False

    return True


def event_has_mandatory_keys(event, keys):
    return all(key in event for key in keys)


def random_string(length=10, chars=string.ascii_uppercase + string.ascii_lowercase + string.digits):
    """Generate a random string

    :param length: length of random string,
    :param chars: list of characters to choose from, defaults to upper chars + lower chars + digits
    :return: the generated string
    """
    return "".join(random.choice(chars) for _ in range(length))


def md5_hash_file(filename: Path) -> str:
    """md5 hash a file
    Note: This will pull in the entire file for hashing (i.e. w/o chunking), not recommended for
    very large files.

    :param filename: pathlib Path file to hash
    :return: md5 string
    """
    with filename.open("rb") as file_to_check:
        data = file_to_check.read()
        return hashlib.md5(data).hexdigest()


def sha1_hashfile(pathlib_file):
    with pathlib_file.open("rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def sha256_hashfile(pathlib_file):
    with pathlib_file.open("rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def collect_running_process(match_all_args=True, **kwargs):
    """The running processes (psutil.Process) whose attributes match ``kwargs``
    (psutil Process attribute names, e.g. ``name="CreateH.exe", ppid=1000``): all
    of them, or with ``match_all_args=False`` at least one. Waits up to 40 s for one
    to appear; raises ProcessLookupError if none does."""
    import psutil

    def find_proc_in_proc_list():
        processes = []
        for p in psutil.process_iter(list(kwargs.keys())):
            result = [p.info[key] == value for key, value in kwargs.items()]
            if result and (all(result) if match_all_args else any(result)):
                processes.append(p)
        return processes

    list_of_procs = func_wait(find_proc_in_proc_list, interval=0.1, timeout=40)
    if not list_of_procs:
        raise ProcessLookupError("Unable to find the process that we expect to be running.")
    return list_of_procs


def random_unicode_mixed(length=10):
    """Random string of all known valid unicode chars
    Note: unicode sections are sparse, therefore could be some values in the full unicode range
    which cause error in an OS when using it for something like a filename, this function only
    selects from printable characters, so it is safe for use with most filesystems

    :param length: length of random string
    :return: the generated string
    """
    return "".join([random_unicode_char_mixed() for _ in range(length)])


def random_unicode_char_mixed():
    """Random character of all known valid unicode chars
    Note: unicode sections are sparse, therefore could be some values in the full unicode range
    which cause error in an OS when using it for something like a filename, this function only
    selects from printable characters, so it is safe for use with most filesystems

    :return: random unicode char
    """
    func = random.choice(
        [
            random_greek,
            random_arabic,
            random_hebrew,
            random_devanagari,
            random_katakana,
            random_fullwidth,
            random_korean,
        ]
    )
    return func(length=1)


def random_unicode(length=10, char_range=None, printable=True):
    """Generate a random unicode string

    :param printable: whether or not the generated string needs to be printable
    :param length: length of random string
    :param char_range: range of unicode characters
    :return: the generated string
    """
    char_range = range(char_range[0], char_range[1]) if char_range else range(0, int(0x10FFFF))
    if printable:
        return "".join(_generate_printable_range(char_range, length))
    else:
        return "".join(_generate_range(char_range, length))


random_greek = functools.partial(random_unicode, char_range=(int(0x03AE), int(0x03FF)))
random_hebrew = functools.partial(random_unicode, char_range=(int(0x0591), int(0x05C7)))
random_arabic = functools.partial(random_unicode, char_range=(int(0x061E), int(0x06DC)))
random_devanagari = functools.partial(random_unicode, char_range=(int(0x0900), int(0x097F)))
random_katakana = functools.partial(random_unicode, char_range=(int(0x30A0), int(0x30FF)))
random_fullwidth = functools.partial(random_unicode, char_range=(int(0xFF01), int(0xFF9F)))
random_korean = functools.partial(random_unicode, char_range=(int(0x1161), int(0x11FF)))


def _generate_printable_range(char_range, range_length):
    """
    :param range_length: the number of chars to generate
    :type range_length: int
    :param char_range: the char range to select from
    :type char_range: range object of int
    :return: printable character from the range given
    :rtype: str
    """

    def select_char():
        try:
            test_char = unicodedata.name(chr(random.choice(char_range)))
        except ValueError:
            return None
        if unicodedata.lookup(test_char).isprintable():
            return unicodedata.lookup(test_char)
        else:
            return None

    max_loop_count = 10 * len(char_range)

    def get_char():
        char = func_repeat(select_char, attempts=max_loop_count, pause=0)
        if char is None:
            if not check_char_range_printable(char_range):
                raise UserWarning(
                    "Please check that the range you provided has printable characters"
                )
        return char

    for i in range(range_length):
        yield get_char()


def _generate_range(char_range, range_length):
    def select_char():
        return chr(random.choice(char_range))

    for i in range(range_length):
        yield select_char()


def func_repeat(func, attempts=5, pause=0, **kwargs):
    """Repeat a funcntion until a truthy return

    :param func: function that runs some sort of check that returns a truthy or falsey value
    :param attempts: number of times to run the function
    :param pause: sleep time between attempts
    :param kwargs: arbitrary args to pass to a function
    :return: return value of func either from first truthy value or last falsey attempt value
    """
    runs = 0
    result = func(**kwargs)
    while not result and runs < attempts - 1:
        if pause:
            time.sleep(pause)
        result = func(**kwargs)
        runs += 1

    return result


def check_char_range_printable(char_range):
    if all([unicodedata.category(chr(i)) in ["Cc", "Cn"] for i in char_range]):
        return False
    for i in char_range:
        try:
            test_char = unicodedata.name(chr(i))
        except ValueError:
            continue
        if unicodedata.lookup(test_char).isprintable():
            return True
    return False


def get_ip_addresses():
    """Collects the system IP addresses

    :return: 4 lists of ipaddress objects: ext_ipv6, ext_ipv4, local_ipv6, local_ipv4
    """
    ext_ipv6, local_ipv6, ext_ipv4, local_ipv4 = [], [], [], []
    ip_addrs = []
    try:
        ip_addrs = socket.getaddrinfo(socket.gethostname(), 0, socket.AF_INET)
    except (socket.gaierror, OSError):
        pass
    try:
        ip_addrs.extend(socket.getaddrinfo(socket.gethostname(), 0, socket.AF_INET6))
    except (socket.gaierror, OSError):
        # Catch error here when trying to get IP info
        pass
    if not ip_addrs:
        return ext_ipv6, ext_ipv4, local_ipv6, local_ipv4
    for _, _, _, _, item in ip_addrs:
        ip_addr = ipaddress.ip_address(item[0])
        if isinstance(ip_addr, ipaddress.IPv6Address):
            if ip_addr.is_global and not (ip_addr.is_loopback or ip_addr.is_link_local):
                ext_ipv6.append(ip_addr)
            else:
                local_ipv6.append(ip_addr)
        if isinstance(ip_addr, ipaddress.IPv4Address):
            if (
                ip_addr.is_global
                or ip_addr.is_private
                and not (ip_addr.is_loopback or ip_addr.is_link_local)
            ):
                ext_ipv4.append(ip_addr)
            else:
                local_ipv4.append(ip_addr)
    primary_ipv4 = get_primary_ipv4_address()
    if primary_ipv4 not in ext_ipv4:
        ext_ipv4.append(primary_ipv4)
    if is_ipv6_capable():
        primary_ipv6 = get_primary_ipv6_address()
        if primary_ipv6 not in ext_ipv6:
            ext_ipv6.append(primary_ipv6)

    return ext_ipv6, ext_ipv4, local_ipv6, local_ipv4


def is_ipv6_capable(ipv6_target=None):
    """Determines if the current system under test can send IPv6-based traffic

    :return: whether or not host is ipv6 capable
    """
    capable = False
    ipv6_target = ipv6_target if ipv6_target else IPV6_TARGET
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.settimeout(20)
        sock.connect((ipv6_target, int(80)))
        sock.close()
    except OSError:
        logger.info("System not able to open IPv6 socket, continuing...")
        pass
    else:
        capable = True

    return capable


def _get_primary_address(address_family=socket.AF_INET, target=IPV4_TARGET):
    """Get ip address of machine

    :param address_family: ipv4 or ipv6
    :param target: ipv4 or ipv 6
    :return: primary ip address for family
    """
    s = socket.socket(address_family, socket.SOCK_DGRAM)
    ip_addr = None
    try:
        s.connect((target, 80))
        ip_addr = ipaddress.ip_address(s.getsockname()[0])
    except (OSError, socket.gaierror):
        pass
    finally:
        s.close()
    return ip_addr


def get_primary_ipv4_address():
    """Get the primary ipv4 address

    :return: ipv4 address
    """
    return _get_primary_address()


def get_primary_ipv6_address():
    """Get the primary ipv6 address

    :return: ipv6 address
    """
    if not is_ipv6_capable():
        raise OSError("system does not support IPv6, cannot get primary IPv6 address")
    return _get_primary_address(address_family=socket.AF_INET6, target=IPV6_TARGET)


def release_and_renew_ip():
    """Release the current DHCP IP address and request a new one.

    Returns:
        The renewed IPv4 address parsed from the ``ipconfig /renew`` output,
        or ``None`` if it could not be determined.
    """
    try:
        logging.info("Releasing current IP address (ipconfig /release)...")
        release_output = subprocess.run(
            ["ipconfig", "/release"],
            capture_output=True,
            text=True,
            check=True
        )
        logging.info(release_output.stdout)

        logging.info("Renewing IP address (ipconfig /renew)...")
        renew_output = subprocess.run(
            ["ipconfig", "/renew"],
            capture_output=True,
            text=True,
            check=True
        )
        logging.info(renew_output.stdout)

        logging.info("DHCP IP release and renewal completed successfully.")

        match = re.search(
            r"IPv4 Address[ .]*:\s*([\d.]+)", renew_output.stdout
        )
        if match:
            renewed_ip = match.group(1)
            logging.info(f"Renewed IPv4 address: {renewed_ip}")
            return renewed_ip

        logging.warning("Could not parse renewed IPv4 address from ipconfig /renew output.")
        return None

    except subprocess.CalledProcessError as e:
        logging.error(f"An error occurred while running ipconfig commands: {e}")
        logging.error(f"Error Details:\n{e.stderr}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return None


def is_json(data):
    """Check if data is json

    :param: data to test
    :return: Whether or not data is valid json
    """
    try:
        json.loads(str(data))
        return True
    except ValueError as _:
        return False
