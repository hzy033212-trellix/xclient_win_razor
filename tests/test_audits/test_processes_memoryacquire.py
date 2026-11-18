import json
from pathlib import Path

import pytest
from tests.test_audits.test_agent_log_audit import get_audit_results_by_generator
from tests.util.compatibility import WINDOWS, compatibility_test
from tests.util.compatibility import is_memory_audit_compatible
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()



# @pytest.fixture(autouse=True)
# def high_hxs_timeouts(hxs):
#     old_timeout = hxs.api.task.request_timeout
#     hxs.timeout = 300
#     yield
#     hxs.api.task.request_timeout = old_timeout


@pytest.mark.caseid(45327)
@pytest.mark.smoke
@pytest.mark.compatibility(WINDOWS)
@compatibility_test(is_memory_audit_compatible)
def test_audit_processes_memoryacquire_completes():
    xclient.run_job(
        "processes-memoryacquire",
        notes="processes-memoryacquire base test task"
    )
    # The payloads are binary memory dumps, so map each one to its file path
    # instead of loading its content (load_audit_output reads them as text).
    output_dir = Path(Singleton_XClient.last_audit["output_dir"])
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    audit_output = {"manifest": manifest}
    for audit in manifest.get("audits", []):
        for result in audit.get("results", []):
            payload_file = output_dir / result["payload"]
            if payload_file.is_file():
                audit_output[result["payload"]] = payload_file
    data = get_audit_results_by_generator(
        audit_output,
        target="processes-memoryacquire",
        payload_type="application/octet-stream"
    )
    if not data:
        # XClient needs offset content for the running Windows build to parse
        # physical memory; without it the audit reports this and acquires nothing.
        issues = [issue.get("summary", "")
                  for payload in get_audit_results_by_generator(
                      audit_output, target="processes-memoryacquire",
                      payload_type="application/vnd.fireeye.xa.issue.v1+json")
                  for issue in json.loads(payload.read_text(encoding="utf-8")).get("Issue", [])]
        if any("Unable to determine the version of the OS in physical memory" in s for s in issues):
            pytest.skip("XClient has no memory offsets for this Windows build: {}".format(issues))
    assert data, "Data for processes-memoryacquire audit should be part of the results"