import pytest

from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

@pytest.mark.smoke
def test_audit_systemrestore_completes():
    data = xclient.run_job("systemrestore", notes="systemrestore base test task")
#   data = task.get_results_for_audit("systemrestore")
    assert data, "Data for systemrestore audit should be part of the results"