import logging
import datetime
import os
import pytest

from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util.fixtures_eventor import update_config_eventor_disabled
from tests.util.paths import XCLIENT_EXE

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


# Function scoped on purpose: each test runs its own audit with its own
# ``<test case name>.json`` script, and keeps the script and outputs in
# its own temp/<script>/<test>/ folder.
@pytest.fixture(scope="function")
def collect_agent_info_job_result(update_config_eventor_disabled):
    xclient = Singleton_XClient()
    data = xclient.run_job("agentinfo", notes="agentinfo test suit task")
    yield data


def date_formatting(date_to_use):
    date = date_to_use.split('T')[0]
    yy = int(date.split('-')[0])
    mn = int(date.split('-')[1])
    dd = int(date.split('-')[2])
    time = date_to_use.split('T')[1][:-1]
    hr = int(time.split(":")[0])
    mm = int(time.split(":")[1])
    se = int(time.split(":")[2])
    return datetime.datetime(second=se, minute=mm, hour=hr, year=yy, month=mn, day=dd, tzinfo=datetime.timezone.utc)

@pytest.mark.smoke
def test_audit_agentinfo_completes(collect_agent_info_job_result):
    data = collect_agent_info_job_result
    assert data, "Data for agentinfo audit should be part of the results"


@pytest.mark.smoke
def test_agentinfo_reports_proper_agent_version(collect_agent_info_job_result):
    data = collect_agent_info_job_result
    xclient = Singleton_XClient()
    assert (
        data["AgentInfo"][0]["appVersion"] == xclient.version()[1:]
    ), "Agent Version from audit should match installed version"


@pytest.mark.smoke
def test_agentinfo_state_agent_status_disabled(collect_agent_info_job_result):
    data = collect_agent_info_job_result
    assert (
        data["AgentInfo"][0]["stateAgentStatus"] == "monitoring_disabled"
    ), "StateAgentStatus should be monitoring_disabled when eventor is disabled"


@pytest.mark.smoke
def test_audit_agentinfo_parameters(collect_agent_info_job_result):
    data = collect_agent_info_job_result

    # Agent Version validation
    assert (data['@generatorVersion'] == data["AgentInfo"][0]["appVersion"]), "Agent version doesn't match"

    time_appCreated = date_formatting(data["AgentInfo"][0]["appCreated"])
    time_appStarted = date_formatting(data["AgentInfo"][0]["appStarted"])

    # App Time Started should be greater than App Time Created
    assert (time_appCreated < time_appStarted), \
        "Time started {0} is not greater than Time created {1}".format(time_appStarted, time_appCreated)

    # appCreated is xclient.exe's creation time (st_ctime on Windows).
    time_created = datetime.datetime.fromtimestamp(os.stat(XCLIENT_EXE).st_ctime, tz=datetime.timezone.utc)

    assert (time_created == time_appCreated),         "xclient.exe created {0}, agentinfo appCreated {1}".format(time_created, time_appCreated)

    assert (data["AgentInfo"][0]['containmentSupported'] == True),         "When the daemon runs the audit as a server task, XClient runs the containment service so it should be reported as true."

    # Containment status should be in normal
    assert (data["AgentInfo"][0]['containmentState'] == 'normal'),         "Expected 'normal' containment state, got {0}".format(data["AgentInfo"][0]['containmentState'])
