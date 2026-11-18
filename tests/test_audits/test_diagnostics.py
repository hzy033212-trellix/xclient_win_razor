import logging
import os
import json
from pathlib import Path

import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util import util

from tests.util.audit_result_utils import get_filepaths_from_multifileacq_audits
from tests.util.fixtures_audits import create_installer_log_files

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit

def get_result_for_audit(manifest, generator, type):
    manifest_dict = json.loads(manifest)
    audits = manifest_dict['audits']
    payload_content = "ERROR" # Indicating something is wrong!
    for audit in audits:
        if audit['generator'] == generator:
            results = audit['results']
            for result in results:
                if result['type'] == type:
                    payload = result['payload']
                    # The audit outputs live in the per-test folder used by run_job
                    audit_output_path = Singleton_XClient.last_audit["output_dir"]
                    with open(audit_output_path + "\\{}".format(payload), "r") as file:
                        payload_content = file.read()
                        # logging.info(payload_content)
                    break
    return payload_content

def get_issues_from_job_xclient(path):
    """Return all "Error" level issues found in the ``*_issues*.json`` files
    directly under ``path``. Each returned issue keeps its original fields plus a
    ``filename`` key naming the file it came from. The generic "audit encountered
    an error" issue is skipped. Fails if any issues file contains "IssueList".
    """
    ignored_summary = "The audit encountered an error during its execution."
    error_issues = []
    for file_path in sorted(Path(path).iterdir()):
        if not file_path.is_file() or "_issues" not in file_path.name or file_path.suffix.lower() != ".json":
            continue
        with open(file_path, "r", encoding="utf-8-sig") as file:
            raw_content = file.read()
        issues = json.loads(raw_content).get("Issue", [])
        if isinstance(issues, dict):
            issues = [issues]
        for issue in issues:
            assert "level" in issue, "Issue in {} has no level field: {}".format(file_path.name, issue)
            if issue["level"] != "Error" or issue.get("summary") == ignored_summary:
                continue
            error_issues.append({**issue, "filename": file_path.name})
        assert "IssueList" not in raw_content, "IssueList should not be in {}".format(file_path.name)
    return error_issues

def convert_xclient_config_to_dict(config_file_path):
    my_dict = {}
    with open(config_file_path, "r") as file:
        # splits on the first colon and strips extra whitespaces
        my_dict = {
            key.strip(): val.strip()
            for line in file
            if ":" in line
            for key, val in [line.split(":", 1)]
        }
        return my_dict

# Function scoped on purpose: each test runs its own audit with its own
# ``<test case name>.json`` script, and keeps the script and outputs in
# its own temp/<script>/<test>/ folder.
@pytest.fixture(scope="function")
def simple_diagnostic_results():
    xclient = Singleton_XClient()
    manifest = xclient.run_job("diagnostic", notes="simple_diagnostic_audit")
    config_result = get_result_for_audit(
        manifest, "config", "application/json"
    )
    log_result = get_result_for_audit(
        manifest, "log-audit", "application/octet-stream"
    )
    return manifest, json.loads(config_result)["ConfigInfo"][0]["ConfigItem"], log_result

def _normalize(value):
    # Treat None as empty and drop invisible characters (null bytes, BOM, zero-width, etc.)
    if value is None:
        return ""
    value = "".join(ch for ch in str(value) if ch.isprintable()).strip()
    # xclient config output wraps string values in quotes (empty string shows as "")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def config_compare(audit_config, xclient_config):
    xclient_config = {_normalize(k): v for k, v in xclient_config.items()}
    for item in audit_config:
        key = _normalize(item["key"]).strip()
        value = _normalize(item.get("val")).strip()
        actual = _normalize(xclient_config.get(key)).strip()
        if actual != value:
            logging.info(
                "Mismatch found for key: %s, expected value: %r (raw %r), actual value: %r (raw %r)",
                key, value, item.get("val"), actual, xclient_config.get(key),
            )
            return False
    return True

@pytest.mark.smoke
def test_simple_diagnostic(simple_diagnostic_results):
    _, audit_config, audit_log = simple_diagnostic_results
    xclient = Singleton_XClient()
    config_file_path = xclient.get_config("xclient_config.txt")
    xclient_config = convert_xclient_config_to_dict(config_file_path)
    assert config_compare(audit_config, xclient_config), "Config audit result should match the current agent result"
    assert not util.is_json(audit_log), "the log should not be able to be parsed into json"


@pytest.fixture(scope="module")
def create_test_installer_log_files(request):
    # test_files_to_include / test_files_to_ignore hold files created by this
    # fixture; they are deleted at teardown.  pre_existing_to_include holds
    # pre-existing system files that xclient already collects and that the test
    # should verify — they must NOT be deleted at teardown.
    created = ([], [])

    # for making sure that the files are deleted at teardown even in case of an exception
    def files_finalizer():
        for fp in created[0] + created[1]:
            if fp.exists():
                fp.unlink()

    request.addfinalizer(files_finalizer)

    test_files_to_include, test_files_to_ignore, pre_existing_to_include = create_installer_log_files()
    created[0].extend(test_files_to_include)
    created[1].extend(test_files_to_ignore)

    logger.debug(f"Files to include in results: {test_files_to_include + pre_existing_to_include}")
    logger.debug(f"Files to ignore in results: {test_files_to_ignore}")
    # Yield created + pre-existing files for include verification; the finalizer
    # only cleans up test_files_to_include (which never contains pre-existing files).
    yield test_files_to_include + pre_existing_to_include, test_files_to_ignore


@pytest.fixture(scope="function")
def standard_diagnostic_results():
    xclient = Singleton_XClient()
    xclient.run_job("diagnostic", notes="standard diagnostic audit")
    # run_job writes the audit script and outputs to temp/<test file name>/<test case name>/
    audit_output_dir = Singleton_XClient.last_audit["output_dir"]

    issues = get_issues_from_job_xclient(audit_output_dir)
    for issue in issues:
        assert False, f"There should be no issues with diagnostic audit, found {issues}"

    with open(Path(audit_output_dir) / "manifest.json", "r", encoding="utf-8-sig") as file:
        manifest = json.load(file)
    return manifest["audits"]


@pytest.mark.smoke
def test_standard_diagnostic(standard_diagnostic_results):
    assert standard_diagnostic_results, "Standard diagnostic should return some data"


def test_standard_diagnostic_install_logs(
    create_test_installer_log_files, standard_diagnostic_results
):
    test_files_to_include, test_files_to_ignore = create_test_installer_log_files
    audit_results = standard_diagnostic_results

    files_in_audit, found_issues = get_filepaths_from_multifileacq_audits(
        audit_results, "InstallLog"
    )
    # kernel driver logs live in a separate audit whose id is "kernel-driver-log", not "InstallLog*"
    kernel_files, kernel_found_issues = get_filepaths_from_multifileacq_audits(
        audit_results, "kernel-driver-log"
    )
    files_in_audit.extend(kernel_files)
    found_issues = found_issues or kernel_found_issues

    # Validate that these install logs acquisitions did not generate any issues
    assert not found_issues, "Installer logs acquisitions should not generate any issues"

    test_files_to_include = [str(test_file).lower() for test_file in test_files_to_include]
    test_files_to_ignore = [str(test_file).lower() for test_file in test_files_to_ignore]
    # collect the audit results
    files_in_audit = [test_file.lower() for test_file in files_in_audit]
    # build the lists to assert on
    files_should_be_included = [val for val in test_files_to_include if val not in files_in_audit]
    files_should_be_missing = [val for val in test_files_to_ignore if val in files_in_audit]

    assert (
        not files_should_be_included
    ), f"Standard diagnostic audit should include installer logs, missing: \n{files_should_be_included}"

    assert (
        not files_should_be_missing
    ), f"Standard diagnostic audit should not include files not matching pattern, found: \n{files_should_be_missing}"

