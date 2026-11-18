"""Test groups (one XClient config each) and the batched audit runs per group.

Every test belongs to one group (``group_of``). pytest runs the groups in
GROUPS order (conftest.py sorts the collected tests). When a group starts, its
config goes into the HXSim stub policy (``hxsim_ioc.set_xclient_config``) and
the audit of every test in the group that needs no preparation (BATCHABLE) is
dropped as an HXSim task at once, so the daemon runs them as one batch. The
tests then run in their normal order; ``Singleton_XClient.run_job`` takes the
batched result (``take``) instead of running the audit again. A test whose audit
script was changed before the run, or whose batched task failed, runs its audit
on its own, also as an HXSim task.

Config groups:

  ioc               The stub policy exactly as HXSim provisioning drops it
                    (IOC alert tests).
  audit             The policy win_razor's side-loading imports
                    (install/xc_Eventor+UnifiedEdr_only.xml), as win_razor's
                    SERVICE ran with, plus Eventor on (AUDIT_SETTINGS).
  log_combined      audit + mxa/log/per_module=false
  log_per_module    audit + mxa/log/per_module=true
  eventor_disabled  audit + mxa/container/Eventor/enabled=false
  restart           audit; last, because its test restarts XClient.
"""
import json
import logging
import re
import shutil
import time
from pathlib import Path

from tests.util import paths

logger = logging.getLogger("tests")

POLICY_XML = paths.INSTALL_DIR / "xc_Eventor+UnifiedEdr_only.xml"

# Settings on top of POLICY_XML, verified with ``xclient -x``. Eventor on (POLICY_XML
# has it too; as a setting it also turns Eventor back on after the eventor_disabled
# group). Not the other ``-C`` flags win_razor passed to every ``xclient.exe -f`` run
# (mxa/container/{HostRemediation,LogonTracker,ProcessTracker,UnifiedEdr,EventStreamer}/enabled=false,
# mxa/eventor/mode=audit): they applied only to that stand-alone process, while
# win_razor's SERVICE kept POLICY_XML (UnifiedEdr on). In the SERVICE's policy they
# would turn UnifiedEdr off, unlike win_razor's SERVICE, and stop the live Eventor
# collecting (mode=audit, mxa events/eventor.cc).
AUDIT_SETTINGS = {
    "mxa/container/Eventor/enabled": "true",
}


def side_loading_policy():
    """{name: value} of every <Setting name="...">value</Setting> in POLICY_XML."""
    text = POLICY_XML.read_text(encoding="utf-8")
    return {name: value for name, value in re.findall(r'<Setting name="([^"]+)">([^<]*)</Setting>', text)}


class Group:
    def __init__(self, name, modules, settings, base_policy=True):
        self.name = name
        self.modules = modules          # node id prefixes; [] = every test no other group claims
        self.settings = settings
        self.base_policy = base_policy

    def policy(self):
        return side_loading_policy() if self.base_policy else {}

    def __repr__(self):
        return "Group({})".format(self.name)


GROUPS = [
    Group("ioc", ["tests/test_ioc_alerts/"], {}, base_policy=False),
    Group("audit", [], AUDIT_SETTINGS),
    Group("log_combined", ["tests/test_audits/test_agent_log_audit.py"],
          dict(AUDIT_SETTINGS, **{"mxa/log/per_module": "false"})),
    Group("log_per_module", ["tests/test_audits/test_agent_log_audit_per_module.py"],
          dict(AUDIT_SETTINGS, **{"mxa/log/per_module": "true"})),
    Group("eventor_disabled", ["tests/test_audits/test_agentinfo.py"],
          dict(AUDIT_SETTINGS, **{"mxa/container/Eventor/enabled": "false"})),
    Group("restart", ["tests/test_audits/test_agent_restart.py"], AUDIT_SETTINGS),
]
_DEFAULT_GROUP = next(g for g in GROUPS if not g.modules)

# Tests whose audit can run before the test itself: test name -> audit script
# (AUDIT_SCRIPTS_DIR/<script>.json, used unchanged). Not here: tests that set
# something up first (files, ports, triggers, event logs, install logs) or edit
# their script, the eventbuffer tests, and test_audit_sysinfo_for_win (it compares
# the audit's available memory with systeminfo's at test time, within 500 MB).
BATCHABLE = {name: name for name in (
    # audit
    "test_audit_kernel_hookdetection_completes",
    "test_audit_network_dns_completes",
    "test_audit_persistence_completes",
    "test_audit_prefetch",
    "test_audit_prefetch_previousruns",
    "test_audit_registry_api",
    "test_audit_registry_raw",
    "test_audit_services",
    "test_audit_systemrestore_completes",
    "test_os_version",
    "test_audit_sysinfo",
    "test_audit_active_directory_sysinfo",
    "test_simple_diagnostic",
    "test_standard_diagnostic",
    "test_standard_diagnostic_install_logs",
    "test_audit_ports_donot_include_ipv6",
    # log_combined
    "test_agent_log_audit",
    "test_agent_log_audit_text",
    "test_agent_log_audit_level",
    "test_agent_log_audit_process",
    "test_agent_log_audit_message",
    # log_per_module
    "test_agent_log_audit_per_module",
    "test_agent_log_audit_per_module_text",
    "test_agent_log_audit_per_module_level",
    "test_agent_log_audit_per_module_process",
    "test_agent_log_audit_per_module_message",
    # eventor_disabled
    "test_audit_agentinfo_completes",
    "test_agentinfo_reports_proper_agent_version",
    "test_agentinfo_state_agent_status_disabled",
    "test_audit_agentinfo_parameters",
)}

# Memory audit tests whose module-scoped fixture runs a script that needs nothing
# set up first (audit group). Every test of the fixture is listed with the
# fixture's script and in SHARED_AUDITS, so the batch runs the script once and the
# fixture takes the result whichever of its tests sets it up first.
DRIVERS_MODULELIST_TESTS = ("test_audit_drivers_modulelist", "test_drive_module_schema_validate")
DRIVERS_SIGNATURE_TESTS = (
    "test_audit_drivers_signature",
    "test_driver_sig_imports_validate_pe_file_single",
    "test_driver_sig_imports_validate_single_schema",
    "test_driver_sig_exports_validate_single_schema",
    "test_driver_sig_strings_validate_single_item",
    "test_driver_sig_shortest_string_validate_single_item",
    "test_driver_sig_hash_validate_single_item",
    "test_driver_sig_digital_sig_validate_single_item",
    "test_driver_sig_device_info_validate_single_item",
)
BATCHABLE.update({name: "test_audit_drivers_modulelist" for name in DRIVERS_MODULELIST_TESTS})
BATCHABLE.update({name: "test_audit_drivers_signature" for name in DRIVERS_SIGNATURE_TESTS})
BATCHABLE["test_audit_processes_memoryacquire_completes"] = "test_audit_processes_memoryacquire_completes"

# Tests whose audits are the same script under the same group config and need no
# fresh run of their own: the audit runs once, the others take a copy of its result.
# Listed explicitly, not found by comparing scripts: the same script can need its
# own run, e.g. test_audit_sysinfo_for_win (compares available memory with
# systeminfo at test time) or a test that sets something up before its audit.
SHARED_AUDITS = [
    {"test_audit_agentinfo_completes", "test_agentinfo_reports_proper_agent_version",
     "test_agentinfo_state_agent_status_disabled", "test_audit_agentinfo_parameters"},
    {"test_audit_sysinfo", "test_os_version", "test_audit_active_directory_sysinfo"},
    {"test_audit_prefetch", "test_audit_prefetch_previousruns"},
    # Shared because PREPARE creates the install-log test files before the batch.
    {"test_standard_diagnostic", "test_standard_diagnostic_install_logs"},
    # Not batched (node opens its ports first): the first test's run is shared.
    {"test_audit_ports", "test_audit_ports_donot_include_ipv6_bydefault"},
    # One module-scoped fixture each (memory audit tests, see BATCHABLE).
    set(DRIVERS_MODULELIST_TESTS),
    set(DRIVERS_SIGNATURE_TESTS),
]

# Batched tests whose preparation must happen before the group's batch is dropped:
# test name -> function that prepares and returns the files it created (deleted
# when the group ends; the test's own fixture creates and deletes them again).
def _prepare_install_logs():
    from tests.util.fixtures_audits import create_installer_log_files
    include, ignore, _ = create_installer_log_files()
    return include + ignore


PREPARE = {"test_standard_diagnostic_install_logs": _prepare_install_logs}

BATCH_DIR = paths.AUDIT_OUTPUT_DIR / "_batch"
# Upper bound for a whole batch; a task still running after it is run again by its test.
BATCH_TIMEOUT = 3600

# node id -> (script text, folder holding its manifest.json and results)
_results = {}
_current = None
# files created by PREPARE for the current group
_prepared = []


def _shared_set(name):
    return next((s for s in SHARED_AUDITS if name in s), None)


def share(nodeid, script_text, output_dir):
    """After ``nodeid``'s audit ran on its own: offer its result to the other tests
    of its SHARED_AUDITS set (same test file), so they take it instead of running
    the same script again."""
    path, _, name = nodeid.partition("::")
    for other in _shared_set(name) or ():
        if other != name:
            _results.setdefault("{}::{}".format(path, other), (script_text, Path(output_dir)))


def group_of(nodeid):
    nodeid = nodeid.replace("\\", "/")
    for group in GROUPS:
        if any(nodeid.startswith(prefix) for prefix in group.modules):
            return group
    return _DEFAULT_GROUP


def sort_items(items):
    """Order the collected tests group by group (stable within a group)."""
    order = {group.name: i for i, group in enumerate(GROUPS)}
    items.sort(key=lambda item: order[group_of(item.nodeid).name])


def enter_group(group, items):
    """Switch XClient to ``group``'s config and batch-run its BATCHABLE audits.

    ``items`` are the session's tests; only those of ``group`` are batched.
    Nothing happens if ``group`` is already the current one.
    """
    global _current
    if _current is group:
        return
    from tests.util import hxsim_ioc
    logger.info("===== Test group %s: XClient config %s", group.name, group.settings)
    hxsim_ioc.set_xclient_config(group.policy(), group.settings)
    _current = group
    _results.clear()
    for f in _prepared:
        if f.exists():
            f.unlink()
    _prepared.clear()
    batch = [item for item in items if group_of(item.nodeid) is group and item.originalname in BATCHABLE]
    for item in batch:
        if item.originalname in PREPARE:
            _prepared.extend(PREPARE[item.originalname]())
            logger.info("Prepared for %s before the batch", item.nodeid)
    if batch:
        run_batch(group, batch)


def run_batch(group, items):
    from tests.test_xclient.provisioned_xclient import apply_razor_public
    from tests.util import hxsim_task
    from tests.test_xclient.provisioned_xclient import artifact_dir_for
    tasks = []
    # (shared set, script text) -> index in tasks: a SHARED_AUDITS set runs once
    shared = {}
    for item in items:
        script = BATCHABLE[item.originalname]
        text = apply_razor_public((paths.AUDIT_SCRIPTS_DIR / "{}.json".format(script)).read_text(encoding="utf-8"))
        same = _shared_set(item.originalname)
        key = (frozenset(same), text) if same else None
        if key in shared:
            tasks[shared[key]][0].append(item.nodeid)
            continue
        if key:
            shared[key] = len(tasks)
        tasks.append(([item.nodeid], text, hxsim_task.Task(script, text).drop()))
    logger.info("Group %s: %d audits dropped as one batch for %d tests", group.name, len(tasks), len(items))
    started = time.time()
    for nodeids, text, task in tasks:
        nodeid = nodeids[0]
        left = max(1, BATCH_TIMEOUT - (time.time() - started))
        if not task.wait(left):
            task.cancel()
            logger.warning("Batched audit for %s did not finish; the test runs it again", nodeid)
            continue
        out = artifact_dir_for(BATCH_DIR / group.name, nodeid)
        if out.exists():
            shutil.rmtree(str(out))
        try:
            task.collect(str(out))
        except AssertionError as e:
            logger.warning("Batched audit for %s incomplete (%s); the test runs it again", nodeid, e)
            continue
        for each in nodeids:
            _results[each] = (text, out)
        if len(nodeids) > 1:
            logger.info("Batched audit for %s shared by %s", nodeid, nodeids[1:])
    logger.info("Group %s: batch of %d finished in %ds (%d results)",
                group.name, len(tasks), time.time() - started, len(_results))


def take(nodeid, script_text, output_dir):
    """Copy the batched result of ``nodeid`` into ``output_dir``; False if there
    is none for exactly this script."""
    entry = _results.pop(nodeid, None)
    if not entry:
        return False
    text, folder = entry
    if text != script_text:
        logger.info("Script of %s changed since the batch; running it again", nodeid)
        return False
    # manifest.json and the result files it names only: a shared folder can be
    # another test's output folder, with that test's own script and artifacts.
    manifest = json.loads(Path(folder, "manifest.json").read_text(encoding="utf-8-sig"))
    names = ["manifest.json"] + [result["payload"] for audit in manifest.get("audits", [])
                                 for result in audit.get("results", []) if result.get("payload")]
    for name in names:
        if Path(folder, name).is_file():
            shutil.copyfile(str(Path(folder, name)), str(Path(output_dir, name)))
    logger.info("Batched audit result used for %s (%s)", nodeid, folder)
    return True
