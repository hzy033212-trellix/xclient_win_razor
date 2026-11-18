"""Fixtures shared by the audit tests."""
import logging
import os
import socket
from pathlib import Path

import pytest
from addict import Dict

from tests.util.constants import RAZOR_PUBLIC
from tests.util.util import get_files_in_folder, get_fully_qualified_domain_name, is_x64

logger = logging.getLogger("tests")

# Helper binaries of the memory audit tests (FireEye Artifactory, anonymous).
TEST_BINARIES_URL = "https://artifactory.eng.fireeye.com/xAgent-deps-dev/TestTools/latest/{}".format(
    "x64" if is_x64() else "x86")


def _download(url, dest):
    import requests
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(resp.content)
    part.replace(dest)


@pytest.fixture(scope="module")
def collect_test_binaries():
    """{stem: path in RAZOR_PUBLIC} of the memory audit helper binaries, each
    downloaded from TEST_BINARIES_URL if missing: CreateH (named kernel objects),
    AslrTest, TestHelper32/64 and their large-address-aware builds (WoW64 32-bit
    ones on x64)."""
    binaries = TEST_BINARIES_URL + "/binaries"
    if is_x64():
        wow64 = TEST_BINARIES_URL + "/WoW64"
        urls = [binaries + "/TestHelper64.exe", binaries + "/TestHelper64_laa.exe",
                wow64 + "/TestHelper32.exe", wow64 + "/TestHelper32_laa.exe"]
    else:
        urls = [binaries + "/TestHelper32.exe", binaries + "/TestHelper32_laa.exe"]
    urls += [binaries + "/AslrTest.exe", binaries + "/CreateH.exe"]

    available = Dict()
    for url in urls:
        dest = RAZOR_PUBLIC / url.rsplit("/", 1)[-1]
        if not dest.is_file():
            logger.info("Downloading %s to %s", url, dest)
            _download(url, dest)
        else:
            logger.info("File already in place %s", dest)
        available[dest.stem] = dest
    return available


def start_test_binary(path, arguments=""):
    """Start a helper binary in the background (through cmd, as win_razor did) and
    return its psutil.Process. Raises unless exactly one such child process is found."""
    from tests.util.sys_utils import SysUtils
    from tests.util.util import collect_running_process
    command = str(Path(path).resolve()) + (" " + arguments if arguments else "")
    # run_command_background_win: SysUtils.run_command_background is a no-op stub here
    # (win_razor bound the *_win methods to the generic names at import time).
    popen = SysUtils.run_command_background_win(command)
    procs = collect_running_process(name=Path(path).name, ppid=popen.pid)
    if len(procs) != 1:
        raise Exception("Test pre-condition requires there to be only 1 instance of {} "
                        "process running, found {}".format(Path(path).name, procs))
    logger.info("process started, name: %s, info: %s", Path(path).name, procs[0])
    return procs[0]


@pytest.fixture(scope="module")
def create_test_files():
    test_directory = RAZOR_PUBLIC / "razor_smoke_test_directory"
    test_file_1 = test_directory / "test1"
    test_file_2 = test_directory / "test2"

    if not test_directory.exists():
        test_directory.mkdir()

    with test_file_1.open("w") as fp:
        fp.write("DEADBEEF")

    with test_file_2.open("w") as fp:
        fp.write("DEADBEEF")

    yield (test_directory, test_file_1, test_file_2)

    test_file_1.unlink()
    test_file_2.unlink()
    test_directory.rmdir()


@pytest.fixture(scope="module")
def create_ipv6_socket():
    IPv6 = "::1"

    # create TCP6 socket in LISTENING state
    sock_tcp = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock_tcp.bind((IPv6, 0))
    sock_tcp.listen(5)
    tcp_port = sock_tcp.getsockname()[1]

    # create UDP6 socket in UNKNOWN state
    sock_udp = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock_udp.bind((IPv6, 0))
    udp_port = sock_udp.getsockname()[1]
    yield (tcp_port, udp_port)

    sock_tcp.close()
    sock_udp.close()


@pytest.fixture(scope="session")
def get_active_directory_domain_name() -> str: # type: ignore
    yield get_fully_qualified_domain_name()


def create_installer_log_files():
    """Create the install-log test files the standard diagnostic should (and
    should not) collect. Returns (created files it should include, created files it
    should ignore, pre-existing system files it should include); the caller deletes
    the created ones. Used by test_diagnostics' create_test_installer_log_files and,
    before the audit group's batch, by audit_batch (PREPARE), so the one standard
    diagnostic run both diagnostic tests share already sees the files."""
    test_files_to_include = []
    test_files_to_ignore = []
    pre_existing_to_include = []

    # trailing backslash makes this the drive root ("C:\"), not the drive-relative "C:"
    system_drive = Path(os.environ["systemdrive"] + "\\")
    # xclient's InstallLog_TEMP audit scans the current user's %TEMP%, not the
    # machine-wide C:\Windows\Temp returned by get_system_temp(). Use %TEMP% so
    # test files land in the folder xclient actually collects from. resolve(): %TEMP%
    # can be an 8.3 short path (C:\Users\ERICHU~1\...), while the SERVICE, which
    # finds the folder through the user profiles, reports the long one.
    test_dirs = [
        Path(os.environ["TEMP"]).resolve(),
        system_drive / "Windows\\System32\\config\\systemprofile\\AppData\\Local\\Temp",
        system_drive / "Windows\\ServiceProfiles\\LocalService\\AppData\\Local\\Temp",
    ]

    # get a standard windows temp path of any user
    user_profiles = [
        item for item in get_files_in_folder(system_drive / "\\users", False) if item.is_dir()
    ]
    for profile in user_profiles:
        temp_path = profile / "AppData\\Local\\Temp"
        if temp_path.is_dir():
            test_dirs.append(temp_path)
            break

    include_string = "hello fireeye world"
    ignore_string = "hello world"
    files_contents_to_include = []
    files_contents_to_ignore = []
    for dir in test_dirs:
        if dir.exists():
            files_contents_to_include.extend(
                (
                    (dir / "MSItest1.LOG", include_string),
                    (dir / "plugin-install_issues.xml", include_string),
                    (dir / "plugin-uninstall_issues.xml", include_string),
                )
            )

            files_contents_to_ignore.extend(
                ((dir / "MSItest2.LOG", ignore_string), (dir / "testfile2.log", include_string))
            )

    # kernel driver logs: xclient's "kernel-driver-log" audit collects
    # setupapi.dev.log specifically (not a wildcard). Verify the pre-existing
    # system file is collected rather than creating a test file that won't
    # match. It goes in pre_existing_to_include, which the finalizer never
    # touches, so the system file is never deleted.
    kernel_log_path = system_drive / "Windows\\inf"
    if kernel_log_path.exists():
        dev_log = kernel_log_path / "setupapi.dev.log"
        if dev_log.exists():
            pre_existing_to_include.append(dev_log)
        else:
            logger.warning(f"Pre-existing kernel driver log not found: {dev_log}")

        files_contents_to_ignore.extend(
            (
                (kernel_log_path / "setupapi.test2.log", ignore_string),
                (kernel_log_path / "testfile.log", include_string),
            )
        )

    # only files that were actually created are yielded; the rest are logged
    for files_contents, created_files in (
        (files_contents_to_include, test_files_to_include),
        (files_contents_to_ignore, test_files_to_ignore),
    ):
        for fp, content in files_contents:
            try:
                fp.write_text(content)
            except OSError as ex:
                logger.warning(f"Test setup file was not created: {fp}. Exception: {ex}")
                continue
            if fp.exists():
                created_files.append(fp)
            else:
                logger.warning(f"Test setup file was not created: {fp}")

    return test_files_to_include, test_files_to_ignore, pre_existing_to_include
