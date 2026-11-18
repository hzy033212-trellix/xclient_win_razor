"""Agent log audit with per-module logging (mxa/log/per_module=true).

Its own module because it needs another XClient config than the combined-logging
tests in test_agent_log_audit.py (see tests/util/audit_batch.py).
"""
import datetime
import logging
from collections import defaultdict

import pytest
import pytz

from tests.test_audits.test_agent_log_audit import (  # noqa: F401 (log_config_restoration: autouse fixture)
    AGENT_METADATA_MESSAGE,
    COMMON_MESSAGE,
    log_audit_test,
    log_config_restoration,
    write_audit_script_time_range,
)
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.test_xclient.provisioned_xclient import update_xclient_config

logger = logging.getLogger("test")

pytestmark = pytest.mark.audit


@pytest.fixture()
def per_module_logging():
    xclient = Singleton_XClient()
    config = xclient.get_config_value("mxa/log/per_module")
    if config != "true":
        logger.info("Changing to per module logging")
        update_xclient_config("mxa/log/per_module", "true")

def section_log_by_module(log_data):
    logger.info("Sectioning log by module")
    pids_to_names = {}
    for line in log_data:
        # Every logger starts up with the executable name ("xclient.exe", or "xagt" on older agents), ignore these lines.
        # The textfile format has a 10-character process name column, so "xclient.exe" shows up as "xclient.ex"
        if line.process_name not in ("xclient.exe", "xclient.ex", "xagt.exe", "xagt") and line.pid not in pids_to_names:
            # Associate pids to process names, single logger could have multiple pids if restarted
            pids_to_names[line.pid] = line.process_name

    # Re-organize log lines into sections using the pid-to-name mapping. A pid that only logged startup lines
    # (e.g. the xclient.exe run by the audit itself) keeps its own process name
    sections = defaultdict(list)
    for line in log_data:
        real_process_name = pids_to_names.get(line.pid, line.process_name)
        sections[real_process_name].append(line)

    return sections


def per_module_test(lines):
    sectioned_data = section_log_by_module(lines)

    assert (
        len(sectioned_data.keys()) >= 2
    ), f"There should be at least two loggers in log: {sectioned_data.keys()}"
    assert "service" in sectioned_data.keys()
    assert "eventor" in sectioned_data.keys()


def test_agent_log_audit_per_module(per_module_logging):
    xclient = Singleton_XClient()
    lines = log_audit_test(xclient)
    per_module_test(lines)


def test_agent_log_audit_per_module_text(per_module_logging):
    xclient = Singleton_XClient()
    lines = log_audit_test(
        xclient,
        params={"format": "textfile"},
        any_func=lambda x: COMMON_MESSAGE in x.msg,
        any_msg="Log retriveal should at least contain a common message: {COMMON_MESSAGE}"
    )
    per_module_test(lines)


def test_agent_log_audit_per_module_start_end_time(per_module_logging):
    xclient = Singleton_XClient()
    # Python doesn't do great with ms level precision, remove it
    end_ts = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC).replace(microsecond=0)
    start_ts = (end_ts - datetime.timedelta(minutes=5)).replace(tzinfo=pytz.UTC)
    start_ts = start_ts.replace(tzinfo=pytz.UTC).replace(microsecond=0)
    logger.info(f"start_ts : {start_ts}")
    logger.info(f"end_ts : {end_ts}")
    write_audit_script_time_range("test_agent_log_audit_per_module_start_end_time", start_ts, end_ts)
    xclient = Singleton_XClient()
    lines = log_audit_test(
        xclient,
        params={
            "start-time": start_ts.isoformat(),
            "end-time": end_ts.isoformat()
        },
        # Lines outside the time range (agent metadata added by the audit) must all come from xclient.exe
        all_func=lambda x: start_ts <= x.time <= end_ts or x.process_name == "xclient.exe",
        all_msg=f"Expected: All lines in agent log should have timestamp between {start_ts} and {end_ts}, "
                f"or have process_name xclient.exe",
    )
    per_module_test(lines)


def test_agent_log_audit_per_module_level(per_module_logging):
    xclient = Singleton_XClient()
    lines = log_audit_test(
        xclient,
        params={"level": "INFO"},
        all_func=lambda x: x.level != "D",
        all_msg="All lines' level should be above INFO level"
    )
    per_module_test(lines)


def test_agent_log_audit_per_module_process(per_module_logging):
    xclient = Singleton_XClient()
    log_audit_test(
        xclient,
        params={"process-filter": "eventor"},
        # agent metadata is included in Agent log from v35 MR1 and v36 onwards hence checking for both eventor and
        # xagt processes. Refer https://jira.eng.fireeye.com:8443/browse/ENDPT-102681
        all_func=lambda x: x.process_name in ["eventor", "xclient.exe", "xclient"],
        all_msg="Expected: Value for 'process_name' key for all lines in agent log should be 'eventor'",
    )
    # Skip per module test since we have filtered by module in this test


def test_agent_log_audit_per_module_message(per_module_logging):
    xclient = Singleton_XClient()
    log_audit_test(
        xclient,
        params={"message": COMMON_MESSAGE},
        # agent metadata is included in Agent log from v35 MR1 and v36 onwards hence checking for messages for
        # xagt process as well. Refer https://jira.eng.fireeye.com:8443/browse/ENDPT-102681
        all_func=lambda x: COMMON_MESSAGE in x.msg
        or [item for item in AGENT_METADATA_MESSAGE if item in x.msg],
        all_msg=f"Expected: Value for 'msg' key for all lines in agent log should contain '{COMMON_MESSAGE}' or one "
                f"of the string from this list {AGENT_METADATA_MESSAGE}",
    )
    # Skip per module test since we have filtered by specific message in this test
