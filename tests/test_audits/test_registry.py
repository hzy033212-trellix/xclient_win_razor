import logging

import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


@pytest.mark.smoke
def test_audit_registry_api():
    node_registry_path = r"HKEY_LOCAL_MACHINE\SOFTWARE\Node.js\Components"

    xclient = Singleton_XClient()
    data = xclient.run_job(
        "registry-api", params={"Path": node_registry_path}, notes="registry-api audit test"
    )
#   data = task.get_results_for_audit("registry-api")

    assert data, "Data for registry-api audit should be part of the results"

    node_registry_item = None
    for registry_item in data["RegistryItem"]:
        if registry_item["Path"] == node_registry_path:
            node_registry_item = registry_item
            break

    assert node_registry_item, "Node registry path should be captured"


@pytest.mark.smoke
def test_audit_registry_raw():
    node_registry_path = r"HKEY_LOCAL_MACHINE\SOFTWARE\Node.js\Components"

    xclient = Singleton_XClient()
    data = xclient.run_job(
        "registry-raw", params={"Path": node_registry_path}, notes="registry-raw audit test"
    )
#   data = task.get_results_for_audit("registry-raw")

    assert data, "Data for registry-raw audit should be part of the results"

    node_registry_item = None
    for registry_item in data["RegistryItem"]:
        if registry_item["Path"] == node_registry_path:
            node_registry_item = registry_item
            break

    assert node_registry_item, "Node registry path should be captured"