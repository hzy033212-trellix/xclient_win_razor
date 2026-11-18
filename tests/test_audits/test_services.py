import logging

import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


@pytest.mark.smoke
def test_audit_services():
    xclient = Singleton_XClient()
    data = xclient.run_job("services", notes="services audit test")
#   data = task.get_results_for_audit("services")

    assert data, "Data for services audit should be part of the results"

    service_names = [service["name"] for service in data["ServiceItem"]]
    # logging.info("Below are all service names : \n")
    # for service in service_names:
    #     logging.info(service + " ,")
#   assert xclient.service_name in service_names, "xagt service should be captured in services audit"
#   For Windows, xclient is no longer a service, so we cannot assert that it is present in the services audit. However, we can assert that mfemms is present.
#   assert "xclient" in service_names, "xclient service should be captured in services audit"
    # Not masvc: that is MA's service, and XClient runs here without MA. mfemms
    # comes with XClient's own vscore install.
    assert "mfemms" in service_names, "mfemms service should be captured in services audit"
