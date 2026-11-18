"""Session setup for running the tests against a fake-MA XClient provisioned with HXSim.

run_tests.ps1 installs the msi (no MA: a marked fake Agent registry key and a
stub policy instead) before pytest starts and uninstalls it afterwards. Here:

  session start     folders, portable Node v24, whoami.exe, OpenSSL, mmsutil.exe
  hxsim_ioc_setup   HXSim provisioning, once per session (hxsim_ioc.prepare_ioc_environment)
  xclient_group     per test module: switch XClient to the module's group config and
                    run the group's batch of audits (tests/util/audit_batch.py)
"""
import logging
import os
import re
from pathlib import Path

import pytest

from tests.test_xclient.provisioned_xclient import (
    AUDIT_OUTPUT_DIR,
    Singleton_XClient,
    _protected_path_exists,
    artifact_dir_for_node,
    copy_fixture_audits_for_current_test,
    current_test_script_stem,
    dump_xclient_config,
    get_event_buffer_audit_metadata,
    ma_installed,
    remove_fixture_audits,
    write_event_buffer_audit_artifacts,
    xclient_processes,
)
from tests.util import audit_batch, hxsim_ioc, paths
from tests.util.artifactory import ensure_ma_tools, ensure_tools
from tests.util.host_setup import ensure_openssl, ensure_whoami
from tests.util.node_setup import ensure_node
from tests.util.paths import create_required_dirs

logger = logging.getLogger("tests")


# run_tests.ps1 -WithMA: XClient (the Orbit msi) runs with MA, which delivers its policy.
WITH_MA = os.environ.get("XCLIENT_WITH_MA") == "1"


def pytest_sessionstart(session):
    """Create the folders a fresh clone lacks, download the portable Node v24 to
    node_exe, copy whoami.exe and download OpenSSL into install_dir, and download
    mmsutil.exe from Artifactory (needs ARTIFACTORY_USER/TOKEN), each only if missing."""
    create_required_dirs()
    ensure_node()
    ensure_whoami()
    ensure_openssl()
    ensure_tools()
    if WITH_MA:
        ensure_ma_tools()


# Known failing Windows audit tests (XClient defects), skipped. Tests marked
# ``defect`` or ``broken`` are skipped as well.
KNOWN_FAILURES = {
    # 8402 / STATUS_HEAP_CORRUPTION in the persistence audit on XClient 50.4.0.134
    "test_audit_persistence_completes": "persistence audit crashes with 8402",
    # Export names that cross a page boundary are not read (msvcp_win.dll "Ordinal:N")
    "test_driver_sig_strings_validate_single_item": "XClient export-name page-boundary defect",
    "test_driver_sig_shortest_string_validate_single_item": "XClient export-name page-boundary defect",
    # processes-memory defects on Windows build 28000 (pid-0 / duplicate ProcessItems etc.)
    "test_process_memory_single_process_schema_validate": "XClient processes-memory defect",
    "test_process_memory_export_pe_result_validate": "XClient processes-memory defect",
    "test_processes_memory_all_processes_no_options_schema_validate": "XClient processes-memory defect",
    "test_processes_memory_string_capture_single_process": "XClient processes-memory defect",
    "test_processes_memory_shortest_matched_string_capture_single_process": "XClient processes-memory defect",
}


def pytest_collection_modifyitems(session, config, items):
    """Skip known failures, then run the tests group by group (one XClient config each)."""
    for item in items:
        name = item.originalname or item.name
        if name in KNOWN_FAILURES:
            item.add_marker(pytest.mark.skip(reason="Known failure: " + KNOWN_FAILURES[name]))
        elif item.get_closest_marker("defect") or item.get_closest_marker("broken"):
            item.add_marker(pytest.mark.skip(reason="Known failure (defect/broken marker)"))
    audit_batch.sort_items(items)


# Settings of the dumped XClient config that hold keys or credentials.
SECRET_SETTING = re.compile(r"(/pem|/cert|/key|password|secret|token)$", re.IGNORECASE)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """When a test fails: save XClient's config (``xclient -x``, keys redacted) and
    its test group into the test's results folder, next to its audit script and
    outputs."""
    outcome = yield
    report = outcome.get_result()
    if not report.failed or report.when == "teardown":
        return
    try:
        out = artifact_dir_for_node(AUDIT_OUTPUT_DIR, item.nodeid)
        config = dump_xclient_config(out / "xclient_config_raw.txt")
        (out / "xclient_config_raw.txt").unlink()
        group = getattr(audit_batch._current, "name", audit_batch._current)
        lines = ["# XClient config when {} failed ({}), test group: {}".format(item.nodeid, report.when, group)]
        for key in sorted(config):
            value = config[key]
            if SECRET_SETTING.search(key) or "-----BEGIN" in value:
                value = "<redacted>"
            lines.append('{}:"{}"'.format(key, value))
        (out / "xclient_config.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:  # never turn a test failure into a hook error
        logger.warning("Could not save the XClient config of failed %s: %s", item.nodeid, e)


@pytest.fixture(autouse=True)
def save_fixture_audit_artifacts(request):
    """Copy into this test's ``temp/<script>/<test>/<label>/`` the shared fixture
    audits it reads, as listed by ``@pytest.mark.audit_artifacts(<label>, ...)``.

    Module-scoped fixtures run their audits once, while the first test that uses
    them is being set up, and stage them under ``temp/<script>/_fixture_audits/``
    (``run_job(..., artifact_label=...)``). Without this copy only that first test
    would have any audit files, and they would not be the ones every test reads.
    """
    yield
    marker = request.node.get_closest_marker("audit_artifacts")
    if marker is not None:
        copy_fixture_audits_for_current_test(AUDIT_OUTPUT_DIR, marker.args)


@pytest.fixture(scope="module", autouse=True)
def remove_fixture_audit_staging(request):
    """Delete ``temp/<script>/_fixture_audits/`` once the module's tests are done;
    every test has its own copy by then (see save_fixture_audit_artifacts)."""
    yield
    remove_fixture_audits(AUDIT_OUTPUT_DIR, Path(str(request.fspath)).stem)


@pytest.fixture(autouse=True)
def save_event_buffer_audit_artifacts(request):
    """Write a per-test copy of the event buffer audit artifacts.

    Runs for every test but only acts on tests marked ``eventor``. The event
    buffer audit itself may execute just once inside a module-scoped fixture and
    be shared across several (e.g. parametrized) tests; this fixture writes the
    recorded artifacts into each individual test's folder at teardown, so every
    test that uses an event buffer audit gets its own
    ``temp/<script>/<test>/`` copy of the revised audit_script.txt,
    event_metadata.json and audit output.
    """
    yield

    if request.node.get_closest_marker("eventor") is None:
        return

    record = Singleton_XClient.last_event_buffer_audit
    if not record:
        return

    # Only write when the recorded audit belongs to the current test's script,
    # so a stale audit from a previously run module is not attributed here.
    if record.get("source_script") != current_test_script_stem():
        return

    metadata = get_event_buffer_audit_metadata()
    write_event_buffer_audit_artifacts(
        base_dir=AUDIT_OUTPUT_DIR, record=record, metadata=metadata
    )


@pytest.fixture(scope="session")
def side_loading_setup():
    """The msi is already installed by run_tests.ps1; check XClient runs, without MA
    (or with it, for run_tests.ps1 -WithMA)."""
    if WITH_MA:
        assert ma_installed(), "-WithMA run but MA is not installed ({})".format(paths.MCAFEE_AGENT_EXE)
    else:
        assert not ma_installed(), "MA is installed ({}); this run must show XClient works without it".format(
            paths.MCAFEE_AGENT_EXE)
    assert _protected_path_exists(paths.XCLIENT_EXE), "XClient is not installed: {}".format(paths.XCLIENT_EXE)
    modes = set(xclient_processes().values())
    assert "SERVICE" in modes, "XClient SERVICE not running (running: {})".format(modes)
    logger.info("XClient installed and running %s MA", "with" if WITH_MA else "without")


@pytest.fixture(scope="session")
def hxsim_ioc_setup(side_loading_setup):
    """XClient talking to a from-scratch HXSim with the IOC feed published.

    Yields the session's AlertCollector; HXSim is stopped at the end. With
    run_tests.ps1 -KeepInstalled (XCLIENT_KEEP=1) it is left running, and the next
    run of the kept install (XCLIENT_REUSE=1) reuses it if it is still usable
    (hxsim_ioc.environment_ready) instead of provisioning from scratch.
    """
    if os.environ.get("XCLIENT_REUSE") == "1" and hxsim_ioc.environment_ready():
        logger.info("Reusing the HXSim environment of the kept install")
    else:
        hxsim_ioc.prepare_ioc_environment()
    yield hxsim_ioc.AlertCollector()
    if os.environ.get("XCLIENT_KEEP") == "1":
        logger.info("HXSim left running for the next run of the kept install (-KeepInstalled)")
    else:
        hxsim_ioc.stop_all_hxsim()


@pytest.fixture(scope="module", autouse=True)
def xclient_group(request, hxsim_ioc_setup):
    """Put XClient in the config of this module's test group and run the group's
    batched audits when the group starts (tests/util/audit_batch.py)."""
    audit_batch.enter_group(audit_batch.group_of(request.node.nodeid), request.session.items)
