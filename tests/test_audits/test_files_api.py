import shutil
from pathlib import Path

import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util.paths import RAZOR_PUBLIC
from tests.util import util
from tests.util.fixtures_audits import create_test_files

pytestmark = pytest.mark.audit


@pytest.fixture(scope="function")
def test_dir():
    test_dir = RAZOR_PUBLIC / "files-api-files"
    if not test_dir.is_dir():
        test_dir.mkdir()

    yield test_dir

    shutil.rmtree(str(test_dir))


def test_basic_listing(test_dir):
    test_file = test_dir / "test.txt"
    with test_file.open("w+") as fp:
        fp.write(util.random_string(length=50))

    xclient = Singleton_XClient()
    data = xclient.run_job("files-api", notes="files-api audit test", audit_script_name="test_basic_listing")

    assert data, "Data for files-api audit should be part of the results"
    assert "FileItem" in data, "files-api should pick up test file"
    assert len(data["FileItem"]) == 1, "FileItem list should have 1 item"
    assert (
        Path(data["FileItem"][0]["FullPath"]) == test_file
    ), "File Item path should match test file"


def test_strings_list(test_dir):
    test_file = test_dir / "test.txt"
    test_str = util.random_string(length=50)

    with test_file.open("w+") as fp:
        fp.write(test_str)

    xclient = Singleton_XClient()
    data = xclient.run_job("files-api", notes="files-api audit test", audit_script_name="test_strings_list")

    assert data, "Data for files-api audit should be part of the results"

    assert "FileItem" in data, "files-api should pick up test file"
    assert len(data["FileItem"]) == 1, "FileItem list should have 1 item"

    assert "StringList" in data["FileItem"][0], "StringList should be in in FileItem"
    assert len(data["FileItem"][0]["StringList"]) == 1, "StringList list should have 1 item"

    assert data["FileItem"][0]["StringList"][0] == test_str, "String should match string in file"


def test_file_hashes(create_test_files):
    test_dir, _, _ = create_test_files

    xclient = Singleton_XClient()
    data = xclient.run_job("files-api", notes="files-api audit test", audit_script_name="test_file_hashes")

    assert data, "Data for files-api audit should be part of the results"

    # With only MD5 hash explicitly enabled, this audit should return only MD5 hash
    # and should not calculate SHA1 or SHA256
    for fileitem in data["FileItem"]:
        assert "Md5sum" in fileitem, "files-api audit should calculate MD5 hash when it is enabled"
        assert (
            "Sha1sum" not in fileitem
        ), "files-api audit should not calculate SHA1 hash when it is disabled"
        assert (
            "Sha256sum" not in fileitem
        ), "files-api audit should not calculate SHA256 hash when it is disabled"