import json
import logging
import re
import subprocess

import pytest

from tests.util import paths
from tests.util.sys_utils import SysUtils
from tests.util.util import func_wait
from tests.test_xclient.provisioned_xclient import Singleton_XClient

import win32evtlog
import win32evtlogutil


logger = logging.getLogger("tests")

pytestmark = pytest.mark.audit

PROC_STARTED_ID = 4688
# The audit reads the whole Security log. On the runner that log is full (20 MB,
# ~25k records): ~140 s when the host is idle, over 300 s in CI right after the
# all-logs audit of test_event_logs_params_handling.
SECURITY_AUDIT_TIMEOUT = 900


def get_proc_started_event_audit(agent):
    # Run security log audit and return process started event if found.
    data = agent.run_job(
        "eventlogs",
        params={
            "eventlog": "Security.evtx",
            "eventlogfullpath": r"%SystemRoot%\System32\Winevt\Logs\Security.evtx",
        },
        notes="eventlogs audit results test",
        timeout=SECURITY_AUDIT_TIMEOUT, # Audit task should complete within timeout period
    )

    if not data:
        return False

    # Find a process started event (has event id 4688).
    for event in data['EventLogItem']:
        if event['EID'] == str(PROC_STARTED_ID):
            return event

    return False


@pytest.mark.parametrize(
    "test_name, audit_params, audit_timeout",
    [
        pytest.param(
            "single_param",
            {"eventlog": "Setup.evtx"},
            300,
        ),
        pytest.param(
            "no_param",
            None,
            1200,
        ),
        pytest.param(
            "multi_param",
            {
                "eventlog": "Key Management Service",
                "eventlogfullpath": r"%SystemRoot%\System32\Winevt\Logs\Setup.evtx",
            },
            300,
        ),
    ],
)
@pytest.mark.smoke
def test_event_logs_params_handling(test_name, audit_params, audit_timeout):
    # Update the audit script's parameters to match this test case, restoring
    # the original script afterwards.
    audit_script = paths.AUDIT_SCRIPTS_DIR / "test_event_logs_params_handling.json"
    original_script = audit_script.read_text(encoding="utf-8")
    audit_script_json = json.loads(original_script)
    audit_script_json["commands"][0]["parameters"] = [
        {"name": name, "value": value} for name, value in (audit_params or {}).items()
    ]
    audit_script.write_text(json.dumps(audit_script_json, indent=4), encoding="utf-8")
    xclient = Singleton_XClient()
    try:
        data = xclient.run_job(
            "eventlogs",
            params=audit_params,
            notes=f"eventlogs audit results test {test_name}",
            timeout=audit_timeout,
            audit_script_name="test_event_logs_params_handling",
        )
    finally:
        audit_script.write_text(original_script, encoding="utf-8")
    assert data, "Data for the audit should exist"


@pytest.mark.smoke
def test_audit_eventlogs_format():
    # Set Local Group Policy to include process started events in Security log.
    cmd = 'Auditpol /set /category:"Detailed Tracking" /success:enable'
    SysUtils.run_command(cmd)

    # Start/kill notepad to create process event.
    SysUtils.run_command_background(["notepad.exe"])
    try:
        SysUtils.run_command("TASKKILL /F /IM notepad.exe")
    except subprocess.CalledProcessError:
    # Test shouldn't fail if notepad process was already killed/doesn't exist.
        pass

    xclient = Singleton_XClient()
    audit_event = func_wait(get_proc_started_event_audit, agent=xclient, timeout=60)
    assert audit_event, "Audit should contain a process started event (ID: {})".format(str(PROC_STARTED_ID))

    # Open Security Event logs and find latest process start event.
    handle = win32evtlog.OpenEventLog("localhost", "Security")
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

    event_found = False
    while not event_found:
        events = win32evtlog.ReadEventLog(handle, flags, 0)
        if events:
            for log_event in events:
                logger.info(f"Event ID: {log_event.EventID}")
                if log_event.EventID == PROC_STARTED_ID:
                    event_found = True
                    break
        else:
            break

    win32evtlog.CloseEventLog(handle)

    assert event_found, "Event log should contain a process started event (ID: {})".format(str(PROC_STARTED_ID))

    # Find subject names ('Subject:', 'Security ID:', etc.).
    re_subjects = re.compile(r"(\w+\s\w+:)")
    log_subjects = re_subjects.findall(win32evtlogutil.SafeFormatMessage(log_event, "Security"))
    audit_subjects = re_subjects.findall(audit_event["message"])

    assert (
        log_subjects == audit_subjects
    ), "Message format from Windows event logs should match message from event log audit"