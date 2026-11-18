import pytest

from tests.test_xclient.provisioned_xclient import Singleton_XClient

@pytest.mark.smoke
def test_audit_kernel_hookdetection_completes():
    xclient = Singleton_XClient()
    data = xclient.run_job(
        "kernel-hookdetection",
        notes="kernel-hookdetection base test task"
    )
#   data = task.get_results_for_audit("kernel-hookdetection")
    assert data, "Data for kenel-hookdetection audit should be part of the results"