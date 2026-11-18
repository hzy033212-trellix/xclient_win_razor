import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient


@pytest.mark.smoke
def test_audit_network_dns_completes():
    xclient = Singleton_XClient()
    data = xclient.run_job("network-dns", notes="network-dns base test task")
#   data = task.get_results_for_audit("network-dns")
    assert data, "Data for network--dns audit should be part of the results"
