import logging

import pytest
from tests.test_audits.test_diagnostics import get_issues_from_job_xclient
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


@pytest.fixture(scope="module")
def collect_persistence_job_result():
    data = xclient.run_job("persistence", notes="persistence test suite task", timeout=500)
    assert data, "Audit task should complete within timeout period"

    audit_output_dir = Singleton_XClient.last_audit["output_dir"]
    issues = get_issues_from_job_xclient(audit_output_dir)
    yield data, issues


@pytest.mark.smoke
def test_audit_persistence_completes(collect_persistence_job_result):
    data, issues = collect_persistence_job_result
    assert data, "Data for the audit should exist"
    for issue in issues:
        assert issue["level"] != "Error", "Audit should not return any Error level issues"

