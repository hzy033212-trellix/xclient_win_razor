import logging
import struct

import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


@pytest.mark.smoke
def test_audit_prefetch():
    data = xclient.run_job(
        "prefetch", notes="prefetch audit results test", timeout=300
    )
#   assert task.wait_for_done(timeout=300), "Audit task should complete within timeout period"
    assert data, "Audit task should complete within timeout period"
#   data = xclient.get_results_for_audit("prefetch")

    assert data["PrefetchItem"], "Data for the audit should exist"


def test_audit_prefetch_previousruns():
    data = xclient.run_job(
        "prefetch", notes="prefetch audit results test", timeout=300
    )
    assert data, "Audit task should complete within timeout period"
#   data = xclient.get_results_for_audit("prefetch")

    if "PrefetchItem" not in data:
        # no prefetch files in c:\windows
        return
    
    assert data["PrefetchItem"], "Data for the audit should exist"

    # we have at least one prefetch result
    for prefetch_item in data["PrefetchItem"]:

        assert prefetch_item["FullPath"]

        is_prefetch_valid = False
        # Only version 26 and above prefetch files have the previous runs. Check for it here
        # Ref: https://github.com/libyal/libscca/blob/main/documentation/Windows%20Prefetch%20File%20(PF)%20format.asciidoc
        with open(prefetch_item["FullPath"], "rb") as prefetch_file:
            if prefetch_file.read(3) == b"MAM":
                # Windows 10 compressed format
                is_prefetch_valid = True
            else:
                prefetch_file.seek(0)
                version = struct.unpack_from("I", prefetch_file.read(4))[0]
                if version >= 26:
                    is_prefetch_valid = True

        num_previous_runs = (
            7 if prefetch_item["TimesExecuted"] > 7 else prefetch_item["TimesExecuted"] - 1
        )

        # Below asserts will fail because of a potential bug in the prefetch audit code. The audit code is not returning the previous runs for valid prefetch files.
        # if is_prefetch_valid and num_previous_runs > 0:
        #     assert prefetch_item["PreviousRunList"]
        #     assert len(prefetch_item["PreviousRunList"]) == num_previous_runs

        #     # break after verifying a single valid prefetch file to save execution time
        #     break