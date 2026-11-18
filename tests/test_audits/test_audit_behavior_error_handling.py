import json
import logging
from pathlib import Path

import pytest
from tests.test_xclient.provisioned_xclient import Singleton_XClient
from tests.util.fixtures_audits import create_test_files


logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


def test_audits_with_unknown_parameter(create_test_files):
    # The audit script test_audits_with_unknown_parameter.json runs these audits with
    # an "Unknown param"; files-api lists the create_test_files folder.
    audits = ["files-api", "ports", "volumes", "processes-api",
              "urlhistory", "cookiehistory", "filedownloadhistory", "formhistory"]

    # The browser audits are slow on Windows: urlhistory alone took ~3 min and all
    # four ~6 min on the XClient host (they are slow, not hung), so allow 15 min.
    xclient = Singleton_XClient()
    xclient.run_script(timeout=900)

    output_dir = Path(Singleton_XClient.last_audit["output_dir"])
    with open(output_dir / "manifest.json", "r", encoding="utf-8-sig") as file:
        manifest = json.load(file)
    for auditname in audits:
        logger.info("Validating results for {} audit".format(auditname))
        data = [
            (output_dir / result["payload"]).read_text(encoding="utf-8")
            for audit in manifest["audits"] if audit["generator"] == auditname
            for result in audit.get("results", []) if (output_dir / result["payload"]).is_file()
        ]
        assert any(data), "Agent should return valid results for {} audit".format(auditname)