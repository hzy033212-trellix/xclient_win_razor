import datetime
import json
import logging
import re
import time
from pathlib import Path

import dateutil.parser
import pytest
import pytz
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.test_xclient.provisioned_xclient import update_xclient_config
from tests.util import paths

logger = logging.getLogger("test")

# It's hard to find a good common message, this selection may fail from time to time
COMMON_MESSAGE = "TCPConnect"
AGENT_METADATA_MESSAGE = [
    'IP for default route at boot:',
    'Local time is',
    'vnum:',
    'product vnum:',
    'host_os vnum:',
    'exe:',
    'cwd:',
    'Eventor status:',
    'EventStreamer status:',
    'HostRemediation status:',
    'LogonTracker status:',
    'ProcessTracker status:',
    'UnifiedEdr status:',
    'Unable to get the agent ID',
    'ExdPlugin status:',
    'MalwareProtection status:',
    'ProRemSvc status:',
    'Agent ID:'
]

pytestmark = pytest.mark.audit


@pytest.fixture(scope="module", autouse=True)
def log_config_restoration():
    xclient = Singleton_XClient()
    previous_config = xclient.get_config("previous_xclient_config.txt")
    if xclient.get_config_value("mxa/container/Eventor/enabled") != "true":
        logger.info("Enabling eventor")
        update_xclient_config("mxa/container/Eventor/enabled", "true")
    yield
    current_config = xclient.get_config("current_xclient_config.txt")
    if current_config != previous_config:
        logger.info("Restoring original config")
        xclient.set_config_data(previous_config)


@pytest.fixture()
def combined_logging():
    xclient = Singleton_XClient()
    config = xclient.get_config_value("mxa/log/per_module")
    if config == "true":
        logger.info("Changing to combined logging")
        update_xclient_config("mxa/log/per_module", "false")


def is_log_metadata_message(msg):
    """
    Check if the msg contain string from Agent Metadata(refer AGENT_METADATA_MESSAGE above) or not
    """
    return re.search(msg.split(':')[0], ' '.join(AGENT_METADATA_MESSAGE)) or "Local time is" in msg


def get_audit_results_by_generator(data, target="log-audit", payload_type="application/json"):
    """
    Use data["manifest"]["audits"] to find the payload ids of the target generator's results with the
    given payload_type, and return the root-level values of data stored under those payload ids
    """
    payloads = [
        result.get("payload")
        for audit in data.get("manifest", {}).get("audits", [])
        if audit.get("generator") == target
        for result in audit.get("results", [])
        if result.get("type") == payload_type
    ]
    return [value for key, value in data.items() if key in payloads]


def load_audit_output(output_dir):
    """
    Combine the xclient audit output folder (manifest.json plus one file per payload) into a single
    dictionary: {"manifest": <manifest>, <payload file name>: <payload content>, ...}
    """
    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    data = {"manifest": manifest}
    for audit in manifest.get("audits", []):
        for result in audit.get("results", []):
            payload_file = output_dir / result["payload"]
            if not payload_file.is_file():
                continue
            content = payload_file.read_text(encoding="utf-8")
            data[result["payload"]] = json.loads(content) if result.get("type") == "application/json" else content
    return data


def write_audit_script_time_range(audit_script_name, start_ts, end_ts):
    """
    run_job runs <test name>.json from AUDIT_SCRIPTS_DIR, so write the test's start/end time into it first
    """
    audit_script = paths.AUDIT_SCRIPTS_DIR / "{}.json".format(audit_script_name)
    audit_script_json = json.loads(audit_script.read_text(encoding="utf-8"))
    time_values = {"start-time": start_ts.isoformat(), "end-time": end_ts.isoformat()}
    for parameter in audit_script_json["commands"][0]["parameters"]:
        if parameter["name"] in time_values:
            parameter["value"] = time_values[parameter["name"]]
    # Rewriting the file right after reading it can fail with OSError (EINVAL: Windows refuses to
    # truncate a file an on-access scanner still has mapped); retry briefly.
    for attempt in range(5):
        try:
            audit_script.write_text(json.dumps(audit_script_json, indent=4), encoding="utf-8")
            return
        except OSError as e:
            if attempt == 4:
                raise
            logger.warning("Writing %s failed (%s), retrying", audit_script, e)
            time.sleep(2)


def log_audit_test(
    agent,
    params=None,
    all_func=None,
    all_msg="",
    any_func=None,
    any_msg=""
):
    params = params or {}

    logger.info("Running log audit")
    agent.run_job("log-audit", params=params, notes="log-audit audit test")
    data = load_audit_output(agent.last_audit["output_dir"])
    log_audit_data = get_audit_results_by_generator(data)
    log_audit_data_file = Path(agent.last_audit["output_dir"]) / "log_audit_data.json"
    log_audit_data_file.write_text(json.dumps(log_audit_data, indent=4), encoding="utf-8")
    logging.info("Log Audit Data saved to : " + str(log_audit_data_file))

    assert log_audit_data, "Log audit should return data"
    if params.get("format", "standard") == "textfile":
        raw_log = get_audit_results_by_generator(
            data,
            payload_type="application/octet-stream"
        )
        assert raw_log, "Raw log text file should exist"
        raw_log = raw_log[0].split("\n")
    else:
        log_audit_data = log_audit_data[0]
        assert "Log" in log_audit_data, "Results should have Log section"
        assert log_audit_data["Log"], "Results should have logging information"
        raw_log = log_audit_data["Log"]

    lines = []
    any_test = not bool(any_func)

    logger.info("Verifying each log line")
    for raw_line in filter(lambda x: x, raw_log):
        line = LogLine.parse_text(raw_line) if params.get("format") == "textfile" else LogLine(raw_line)
        lines.append(line)

        # Assert all basic data is present
        assert line.time is not None, "Log line should have timestamp field"
        assert line.hr is not None, "Log line should have hr field"
        assert line.level is not None, "Log line should have level field"
        assert line.pid is not None, "Log line should have pid field"
        assert line.process_name is not None, "Log line should have process name field"
        assert line.tid is not None, "Log line should have tid field"
        assert line.lid is not None, "Log line should have lid field"
        assert line.fn is not None, "Log line should have fn field"
        assert line.lineno is not None, "Log line should have lineno field"
        assert line.msg is not None, "Log line should have msg field"

        # Custom verify for all lines
        if all_func:
            assert all_func(line), f"{all_msg}. Observed: Line from Agent log is: \n{line}"

        # Test if any line passes any_func
        if any_func:
            any_test = any_test or any_func(line)

    # At least one message should pass the any test
    assert any_test, any_msg

    return lines


@pytest.mark.smoke
def test_agent_log_audit(combined_logging):
    xclient = Singleton_XClient()
    log_audit_test(
        xclient,
        any_func=lambda x: COMMON_MESSAGE in x.msg,
        any_msg="Log retriveal should at least contain a common message: {COMMON_MESSAGE}"
    )


def test_agent_log_audit_text(combined_logging):
    xclient = Singleton_XClient()
    log_audit_test(
        xclient,
        params={"format": "textfile"},
        any_func=lambda x: COMMON_MESSAGE in x.msg,
        any_msg="Log retriveal should at least contain a common message: {COMMON_MESSAGE}"
    )


def test_agent_log_audit_start_end_time(combined_logging):
    # Python doesn't do great with ms level precision, remove it
    end_ts = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC).replace(microsecond=0)
    start_ts = (end_ts - datetime.timedelta(minutes=5)).replace(tzinfo=pytz.UTC)
    start_ts = start_ts.replace(tzinfo=pytz.UTC).replace(microsecond=0)
    logger.info(f"start_ts : {start_ts}")
    logger.info(f"end_ts : {end_ts}")
    write_audit_script_time_range("test_agent_log_audit_start_end_time", start_ts, end_ts)
    xclient = Singleton_XClient()
    log_audit_test(
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


def test_agent_log_audit_level(combined_logging):
    xclient = Singleton_XClient()
    log_audit_test(
        xclient,
        params={"level": "INFO"},
        all_func=lambda x: x.level != "D",
        all_msg="All lines' level should be above INFO level"
    )


def test_agent_log_audit_process(combined_logging):
    xclient = Singleton_XClient()
    log_audit_test(
        xclient,
        params={"process-filter": "eventor"},
        # agent metadata is included in Agent log from v35 MR1 and v36 onwards hence checking for both eventor and
        # xagt processes. Refer https://jira.eng.fireeye.com:8443/browse/ENDPT-102681
        all_func=lambda x: x.process_name in ["eventor", "xclient.exe", "xclient"],
        all_msg="Expected: Value for 'process_name' key for all lines in agent log should be 'eventor'",
    )


def test_agent_log_audit_message(combined_logging):
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


class LogLine:
    def __init__(self, log_data):
        self.uid = log_data.get("uid", None)
        # Python datetime doesn't do microsecond precision too well, zero it for easier comparisons
        self.time = dateutil.parser.isoparse(
            log_data.get("time", None)
        ).replace(tzinfo=pytz.UTC).replace(microsecond=0)
        self.hr = log_data.get("hr", None)
        self.level = log_data.get("lvl", None)
        self.flags = log_data.get("flags", None)
        self.pid = log_data.get("pid", None)
        self.process_name = log_data.get("process_name", None).lower()
        self.tid = log_data.get("tid", None)
        self.lid = log_data.get("lid", None)
        self.fn = log_data.get("fn", None)
        self.lineno = log_data.get("ln", None)
        self.msg = log_data.get("msg", None)
        self.args = log_data.get("args", [])

    def __str__(self):
        s = "\n"
        s += f"uid: {self.uid}\n"
        s += f"ts: {self.time}\n"
        s += f"hr: {self.hr}\n"
        s += f"level: {self.level}\n"
        s += f"flags: {self.flags}\n"
        s += f"pid: {self.pid}\n"
        s += f"process_name: {self.process_name}\n"
        s += f"tid: {self.tid}\n"
        s += f"lid: {self.lid}\n"
        s += f"fn: {self.fn}\n"
        s += f"lineno: {self.lineno}\n"
        s += f"msg: {self.msg}\n"
        s += f"args: {self.args}\n\n"
        return s

    @staticmethod
    def parse_text(log_line):
        data = {}
        data["uid"] = None
        data["time"] = log_line.split(" ")[0]
        hr = log_line.split(" ")[1].split(",")
        data["hr"] = int(hr[0]) + int(hr[1].split(":")[0])/1000000000
        data["lvl"] = log_line.split("[")[0].split(":")[-1].strip()
        data["flags"] = None
        data["pid"] = log_line.split("[")[1].split("]")[0]
        data["process_name"] = log_line.split("(")[1].split(")")[0].strip()
        data["tid"] = log_line.split("t:")[1].split(" ")[0]
        data["lid"] = log_line.split("lc")[1].split(":")[0]
        data["fn"] = log_line.split("m=")[0].split(":")[-3].strip()
        data["ln"] = log_line.split("m=")[0].split(":")[-2]
        data["msg"] = log_line.split("m=")[1]
        data["args"] = []
        return LogLine(data)