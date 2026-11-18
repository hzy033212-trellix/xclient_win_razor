import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util.fixtures_audits import create_test_files


pytestmark = pytest.mark.audit


@pytest.mark.smoke
def test_audit_files_raw(side_loading_setup, create_test_files):
    _, test_file_1, test_file_2 = create_test_files

    xclient = Singleton_XClient()
    data = xclient.run_job(
        "files-raw", notes="files-raw audit test", audit_script_name="test_audit_files_raw"
    )
#   data = task.get_results_for_audit("files-raw")

    assert data, "Data for files-raw audit should be part of the results"

    test1_file_item = test2_file_item = None
    for file_item in data["FileItem"]:
        if file_item["FileName"] == test_file_1.name:
            test1_file_item = file_item

        if file_item["FileName"] == test_file_2.name:
            test2_file_item = file_item

        if test1_file_item and test2_file_item:
            break

    assert test1_file_item, "test1 file should be captured in audit"
    assert test2_file_item, "test2 file should be captured in audit"


@pytest.mark.smoke
def test_audit_file_acquisition_api(side_loading_setup, create_test_files):
    _, test_file, _ = create_test_files

    xclient = Singleton_XClient()
    data = xclient.run_job(
        "file-acquisition-api",
        notes="file-acquisition-api audit test",
        output_file_name="file-acquisition-api-100.dat",
        audit_script_name="test_audit_file_acquisition_api",
    )
    # data = task.get_results_for_audit(
    #     "file-acquisition-api", payload_type="application/octet-stream"
    # )

    assert data == "DEADBEEF", 'File content should be equal to "DEADBEEF"'


@pytest.mark.smoke
def test_audit_file_acquisition_raw(side_loading_setup, create_test_files):
    _, test_file, _ = create_test_files

    xclient = Singleton_XClient()
    data = xclient.run_job(
        "file-acquisition-raw",
        notes="file-acquisition-raw audit test",
        output_file_name="file-acquisition-raw-100.dat",
        audit_script_name="test_audit_file_acquisition_raw",
    )
    # data = task.get_results_for_audit(
    #     "file-acquisition-raw", payload_type="application/octet-stream"
    # )

    assert data == "DEADBEEF", 'File content should be equal to "DEADBEEF"'