import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from tests.util import paths
from tests.util.util import func_wait, run_windows_commands

# Base folder under which per-test audit artifacts are archived.
# Kept as a string because it is used with string concatenation below.
AUDIT_OUTPUT_DIR = str(paths.AUDIT_OUTPUT_DIR)


def current_test_artifact_dir(base_dir):
    """Return ``<base_dir>/<python_script_name>/<test_name>`` for the running test.

    The location is derived from pytest's ``PYTEST_CURRENT_TEST`` environment
    variable (format: ``path/to/test_file.py::test_name (phase)``). When it is
    unset a generic fallback folder is used instead. The directory is created
    if it does not already exist.
    """
    node_id = os.environ.get("PYTEST_CURRENT_TEST", "").split(" (")[0]  # drop the " (call)" phase
    return artifact_dir_for_node(base_dir, node_id)


def _sanitize_for_path(name):
    """Strip characters that are illegal in Windows file/dir names."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return cleaned or "unknown"


def artifact_dir_for(base_dir, nodeid):
    """``<base_dir>/<python script name>/<test name>`` for a pytest node id
    (``path/to/test_file.py::test_name[param]``); not created here."""
    script_name, test_name = "unknown_script", "unknown_test"
    if "::" in nodeid:
        file_part, _, test_part = nodeid.partition("::")
        script_name, test_name = Path(file_part).stem, test_part
    return Path(base_dir) / _sanitize_for_path(script_name) / _sanitize_for_path(test_name)


def artifact_dir_for_node(base_dir, node_id):
    """artifact_dir_for, created if missing."""
    artifact_dir = artifact_dir_for(base_dir, node_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def current_test_script_stem():
    """Return the python script stem of the running test, or a fallback."""
    current = os.environ.get("PYTEST_CURRENT_TEST", "")
    if "::" in current:
        return Path(current.split("::")[0]).stem
    return "unknown_script"


def current_test_node_id():
    """Return the pytest node id (without the trailing ``(phase)``) of the
    running test. The phase changes between setup/call/teardown but the node id
    stays constant, so it is a stable per-test key."""
    current = os.environ.get("PYTEST_CURRENT_TEST", "")
    return current.split(" (")[0] if current else "unknown_test"


def current_test_name():
    """Return the test function name of the running test, or a fallback.

    Any pytest parametrization id (``[...]``) is stripped so the name maps
    directly onto the matching ``<test case name>.json`` audit script under
    ``AUDIT_SCRIPTS_DIR``.
    """
    current = os.environ.get("PYTEST_CURRENT_TEST", "")
    if "::" in current:
        node_id = current.split(" (")[0]  # drop the trailing " (call)"/"(setup)" phase
        test_part = node_id.partition("::")[2]
        return test_part.split("[")[0]  # drop any parametrization id
    return "unknown_test"


# Per-test event buffer audit metadata (the ground-truth filters used to locate
# the event), keyed by pytest node id. Several tests can share one module-scoped
# bulk audit, but each filters it with its own criteria.
_event_buffer_audit_metadata_by_test = {}


def record_event_buffer_audit_metadata(filters):
    """Record the current test's event buffer audit metadata (filters)."""
    if filters is None:
        return
    _event_buffer_audit_metadata_by_test[current_test_node_id()] = dict(filters)


def get_event_buffer_audit_metadata():
    """Return the metadata recorded for the current test, or ``None``."""
    return _event_buffer_audit_metadata_by_test.get(current_test_node_id())


def write_event_buffer_audit_artifacts(base_dir, record, metadata=None):
    """Write the recorded event buffer audit artifacts for the current test.

    Three artifacts are archived under ``<base_dir>/<script>/<test>/``:
      1. the revised ``audit_script.txt`` sent to xclient,
      2. the event buffer audit metadata (the ground-truth filters), if present,
      3. the event buffer audit output produced by xclient.
    """
    artifact_dir = current_test_artifact_dir(base_dir)

    try:
        with open(artifact_dir / "audit_script.txt", "w") as file:
            file.write(record["audit_script"])
    except OSError as exc:
        logging.warning("Could not save audit script copy: %s", exc)

    if metadata is not None:
        try:
            with open(artifact_dir / "event_metadata.json", "w") as file:
                json.dump(metadata, file, default=str)
        except OSError as exc:
            logging.warning("Could not save event buffer audit metadata: %s", exc)

    try:
        with open(artifact_dir / record["output_file_name"], "w") as file:
            file.write(record["output"])
    except OSError as exc:
        logging.warning("Could not save audit output copy: %s", exc)

    logging.info("Event buffer audit artifacts saved under %s", artifact_dir)
    return artifact_dir


win_xclient_path = paths.XCLIENT_EXE
MMSUTIL_EXE = str(paths.INSTALL_DIR / "mmsutil.exe")
XCLIENT_CONFIG_DUMP = paths.INSTALL_DIR / "xclient_config.txt"


def _mmsutil_until(verb, status):
    run_windows_commands([MMSUTIL_EXE, verb, 'xclient'])
    cnt = 6
    while cnt > 0:
        cnt = cnt - 1
        time.sleep(10)
        output = run_windows_commands([MMSUTIL_EXE, '-query', 'xclient'])
        if status in output:
            return True
    return False


def stop_xclient_service():
    assert _mmsutil_until('-stop', "SERVICE_STOPPED"), "XClient service cannot be stopped by mmsutil tool!"


def start_xclient_service():
    assert _mmsutil_until('-start', "SERVICE_RUNNING"), "XClient service cannot be started by mmsutil tool!"


def restart_xclient_service():
    logging.info("Restart XClient service.....")
    stop_xclient_service()
    start_xclient_service()


def xclient_processes():
    """{pid: '--mode' value} of the running xclient.exe processes."""
    command = ['wmic', 'process', 'where', "name='xclient.exe'", 'get', 'ProcessId,CommandLine', '/format:csv']
    # Not run_windows_commands: no matching process must not raise.
    output = subprocess.run(command, capture_output=True, text=True).stdout
    procs = {}
    for line in output.splitlines():
        mode = re.search(r"--mode\s+(\w+)", line)
        if mode:
            procs[line.rsplit(",", 1)[-1].strip()] = mode.group(1)
    return procs


def read_xclient_config(path):
    """{key: value} of a config dumped by ``xclient -x`` (lines look like ``key:"value"``)."""
    config = {}
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            key, sep, value = line.rstrip("\r\n").partition(':"')
            if sep and value.endswith('"'):
                config[key] = value[:-1]
    return config


def dump_xclient_config(path=XCLIENT_CONFIG_DUMP):
    """``xclient -x`` into ``path``; returns the parsed config."""
    run_windows_commands([str(win_xclient_path), "-x", str(path)])
    return read_xclient_config(path)


def wait_for_xclient_config(settings, max_try=30):
    """Poll ``xclient -x`` until every ``{setting: value}`` shows up in the dumped config."""
    wanted = {k: str(v) for k, v in settings.items()}
    current = {}
    while max_try > 0:
        max_try = max_try - 1
        logging.info("Wait for 10 seconds for new policy to be applied.....")
        time.sleep(10)
        current = dump_xclient_config()
        if all(current.get(k) == v for k, v in wanted.items()):
            logging.info("Target updated config is reflected on local XClient config: %s", wanted)
            return
    missing = {k: (v, current.get(k)) for k, v in wanted.items() if current.get(k) != v}
    assert False, "Target updated config is not reflected on local XClient config (wanted, got): {}".format(missing)


def update_xclient_config(setting_to_change, change_to_value):
    """Set one XClient setting through the HXSim stub policy (the fake MA's only policy source)."""
    from tests.util import hxsim_ioc
    hxsim_ioc.apply_xclient_settings({setting_to_change: change_to_value})


def _protected_path_exists(path):
    """Path.is_file() re-raises PermissionError (WinError 5). A stat that is
    denied by Trellix self-protection still means the file is present, so treat
    Access Denied as 'exists'."""
    try:
        return path.is_file()
    except PermissionError:
        logging.info(f"Access denied stat-ing {path}; treating as present (self-protection).")
        return True


def ma_installed():
    return _protected_path_exists(paths.MCAFEE_AGENT_EXE)


# run_tests.ps1 -WithMA (the Orbit msi), as win_razor did: with self-protection off
# (through MA), these binaries of the fake-MA build replace the installed ones, so
# the daemon takes its policy from the stub policy. Only mxAgent.dll links the
# (fake) MA SDK; the other two are the build's own.
REQUIRED_DEV_BINARIES = ("mxAgent.dll", "mxCore.dll", "xclient.exe")


def _md5_or_none(path):
    try:
        with open(path, "rb") as file:
            return hashlib.md5(file.read()).hexdigest()
    except OSError:
        return None


def dev_binaries_installed(bin_dir):
    xclient_dir = win_xclient_path.parent
    return all(_md5_or_none(xclient_dir / name) is not None
               and _md5_or_none(xclient_dir / name) == _md5_or_none(Path(bin_dir) / name)
               for name in REQUIRED_DEV_BINARIES)


def swap_in_dev_binaries(bin_dir, backup_root):
    """Replace REQUIRED_DEV_BINARIES in the XClient install dir with those of
    ``bin_dir`` (the fake-MA build), with XClient stopped.

    Overwriting an installed binary in place is denied even with self-protection
    off, but moving it out and creating a new file is allowed, so each original is
    moved into ``backup_root/xclient_orig_<ts>`` first. If any could not be
    replaced, every file replaced is rolled back and the swap fails.
    Self-protection must already be off (hxsim_ioc.ma_protection_off).
    """
    xclient_dir = win_xclient_path.parent
    backup = Path(backup_root) / "xclient_orig_{}".format(time.strftime("%Y%m%d_%H%M%S"))
    logging.info("Swap %s in %s with %s (originals -> %s).....", REQUIRED_DEV_BINARIES, xclient_dir, bin_dir, backup)
    stop_xclient_service()
    func_wait(lambda: not xclient_processes(), interval=2, timeout=60)
    replaced = []
    for name in REQUIRED_DEV_BINARIES:
        src, dst = Path(bin_dir) / name, xclient_dir / name
        keep = backup / name
        try:
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(keep))
        except OSError as e:
            logging.error("Failed to move %s out for replacement: %s", dst, e)
            continue
        try:
            shutil.copy2(str(src), str(dst))
            replaced.append((dst, keep))
        except OSError as e:
            logging.error("Failed to copy %s -> %s: %s; restoring original", src, dst, e)
            shutil.move(str(keep), str(dst))
    not_done = set(REQUIRED_DEV_BINARIES) - set(d.name for d, _ in replaced)
    if not_done:
        _rollback_binaries(replaced, backup / "_rejected")
        assert False, "Fake-MA binaries not replaced: {} (rolled back, XClient left stopped)".format(sorted(not_done))
    logging.info("Replaced %d binaries.....", len(replaced))
    start_xclient_service()
    assert func_wait(lambda: "SERVICE" in set(xclient_processes().values()), interval=3, timeout=120),         "XClient SERVICE did not come up after the binary swap!"


def _rollback_binaries(replaced, rejected_dir):
    for dst, keep in reversed(replaced):
        aside = rejected_dir / dst.name
        try:
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(aside))
            shutil.move(str(keep), str(dst))
        except OSError as e:
            logging.error("Could not restore original %s from %s: %s", dst, keep, e)


def apply_razor_public(script_text):
    """Audit scripts refer to RAZOR_PUBLIC as ``{RAZOR_PUBLIC}`` (filled in JSON-escaped)."""
    return script_text.replace("{RAZOR_PUBLIC}", json.dumps(str(paths.RAZOR_PUBLIC))[1:-1])


def render_audit_script(audit_script_name, params=None):
    """The text run_job runs for AUDIT_SCRIPTS_DIR/<audit_script_name>.json:
    ``{RAZOR_PUBLIC}`` filled in, and each ``"{<param>}"`` replaced by the JSON value
    of ``params[<param>]`` (values only known at run time, e.g. a started test
    binary's pid). ``params`` may be None."""
    script = apply_razor_public((paths.AUDIT_SCRIPTS_DIR / "{}.json".format(audit_script_name)).read_text(encoding="utf-8"))
    for param_name, param_value in (params or {}).items():
        script = script.replace('"{%s}"' % param_name, json.dumps(param_value))
    return script


# Shared (module-scoped) fixture audits.
#
# A module-scoped fixture runs its audit(s) once, while the first test that uses
# it is being set up, so saving them under "the running test" would credit them
# all to that one test (and, when a fixture runs several audits, each would
# overwrite the previous one). Instead, a fixture passes ``artifact_label`` to
# ``run_job``: the audit then runs in its own staging folder
# ``<base>/<script>/_fixture_audits/<label>/``. Each test lists the labels it
# actually reads with ``@pytest.mark.audit_artifacts(<label>, ...)``; an autouse
# fixture in conftest.py copies just those into the test's own
# ``<base>/<script>/<test>/<label>/`` at teardown. Another module-scoped autouse
# fixture deletes the staging folder when the module ends.
FIXTURE_AUDITS_FOLDER = "_fixture_audits"
# (script stem, label) -> staging folder of a fixture audit that ran
_fixture_audits = {}


def fixture_audit_root(base_dir, script_stem):
    """``<base_dir>/<script>/_fixture_audits`` for a test script (not created)."""
    return artifact_dir_for(base_dir, "{}.py::x".format(script_stem)).parent / FIXTURE_AUDITS_FOLDER


def copy_fixture_audits_for_current_test(base_dir, labels):
    """Copy the staged fixture audits named in ``labels`` into the running test's
    folder; returns the labels copied (a label whose audit never ran is skipped)."""
    script_stem = current_test_script_stem()
    copied = []
    for label in labels:
        src = _fixture_audits.get((script_stem, label))
        if src is None or not Path(src).is_dir():
            logging.info("No staged fixture audit %r for %s; nothing saved for it", label, script_stem)
            continue
        dst = current_test_artifact_dir(base_dir) / label
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        copied.append(label)
    if copied:
        logging.info("Fixture audit artifacts %s saved under %s", copied, current_test_artifact_dir(base_dir))
    return copied


def remove_fixture_audits(base_dir, script_stem):
    """Delete a script's staging folder and forget its staged audits."""
    for key in [k for k in _fixture_audits if k[0] == script_stem]:
        del _fixture_audits[key]
    root = fixture_audit_root(base_dir, script_stem)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


# Prefetched audits: tasks dropped ahead of the run_job that needs them, so the
# daemon runs them back to back as one batch (like audit_batch's group batch, for
# audits that need something set up first, e.g. a started process whose pid is in
# the script). run_job takes the prefetched task of exactly its script text.
# script text -> (Task, timeout, drop sequence number)
_prefetched = {}
_prefetch_seq = [0]


def prefetch_audits(jobs):
    """Drop the audits ``jobs`` ([(audit_script_name, params, timeout)], in the order
    the tests will need them) as HXSim tasks now. A later run_job of the same
    rendered script waits for its task instead of dropping a new one."""
    from tests.util import hxsim_task
    for audit_script_name, params, timeout in jobs:
        text = render_audit_script(audit_script_name, params)
        if text in _prefetched:
            continue
        _prefetch_seq[0] += 1
        _prefetched[text] = (hxsim_task.Task(audit_script_name, text).drop(), timeout, _prefetch_seq[0])
    logging.info("%d audits prefetched as one batch: %s", len(jobs), [job[0] for job in jobs])


def cancel_prefetched_audits():
    """Stop advertising the prefetched tasks no run_job took (e.g. their test failed
    or was deselected)."""
    for task, _, _ in _prefetched.values():
        task.cancel()
        logging.info("Prefetched audit %s (%s) not used; cancelled", task.name, task.id)
    _prefetched.clear()


def _take_prefetched(script_text, timeout):
    """(task, timeout) of the prefetched task of ``script_text``, or (None, timeout).
    The daemon fetches the whole batch in one poll and runs it in its own order, not
    the drop order (seen with 50.4.0.244: the task dropped first finished 10th of 11),
    so the timeout of a task also covers every other prefetched task not taken yet."""
    entry = _prefetched.pop(script_text, None)
    if not entry:
        return None, timeout
    task, own_timeout, _ = entry
    from tests.util import hxsim_task
    timeouts = [t for _, t, _ in _prefetched.values()] + [timeout or own_timeout]
    total = sum(t or hxsim_task.DEFAULT_WAIT for t in timeouts)
    return task, total


def _command_execution_errors(audit_output_path):
    """The "command execution error" issues of a manifest with no audit results:
    the audit itself failed (e.g. its process crashed, or its result upload failed).
    Its manifest.json must not be passed off as the audit's data."""
    with open(os.path.join(audit_output_path, "manifest.json"), "r", encoding="utf-8-sig") as file:
        manifest = json.load(file)
    if manifest.get("audits"):
        return []
    return [i.get("str") for i in manifest.get("issues", []) if "command execution error" in (i.get("str") or "")]


def _run_audit_task(script_name, script_text, audit_output_path, timeout):
    """Run the audit script in the SERVICE daemon as an HXSim task, or take the
    result the group batch already fetched for this test, and write manifest.json
    plus the result files into ``audit_output_path``."""
    from tests.util import audit_batch, hxsim_task
    if audit_batch.take(current_test_node_id(), script_text, audit_output_path):
        return
    task, timeout = _take_prefetched(script_text, timeout)
    if task:
        logging.info("Prefetched audit %s (%s) used", task.name, task.id)
    else:
        task = hxsim_task.Task(script_name, script_text).drop()
    if not task.wait(timeout):
        task.cancel()
        assert False, "Audit {} did not finish within {} seconds!".format(
            script_name, timeout or hxsim_task.DEFAULT_WAIT)
    task.collect(audit_output_path)
    audit_batch.share(current_test_node_id(), script_text, audit_output_path)


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))  # Google's public DNS server
    local_ip = s.getsockname()[0]
    s.close()
    return local_ip


class Singleton_XClient:
    _xclient_ip = get_local_ip()
    _instance = None
    # In-memory snapshot of the most recent event buffer audit (revised audit
    # script, metadata and output). It is written to each test's own folder by a
    # pytest fixture, so tests that share a single module-scoped audit still each
    # get their own copy of the artifacts.
    last_event_buffer_audit = None
    # Most recent non-eventbuffer audit: the per-test folder
    # (``temp/<script>/<test>/``) holding its audit script and outputs.
    last_audit = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, value=None):
        if not hasattr(self, '_initialized'):
            self.value = value
            self._initialized = True

    def run_job(self, audit_name = "eventbuffer", params = {}, notes = "", output_file_name = "", audit_script_name = "", timeout = None, artifact_label = ""):
        # If ``timeout`` (in seconds) is given and the audit takes longer, the
        # test fails. ``None`` waits for the audit to finish however long it takes.
        # ``artifact_label`` (non-eventbuffer audits only) is for shared,
        # module-scoped fixtures: the audit runs in its own staging folder and is
        # copied at teardown into each test marked
        # ``@pytest.mark.audit_artifacts(<label>)``. See fixture_audit_root().
        audit_config_path = str(paths.AUDIT_SCRIPT_TXT)
        script_name = "eventbuffer"
        if audit_name != "eventbuffer":
            logging.info("Current audit is not eventbuffer but %s", audit_name)
            # The audit script to run is named after the test case that triggers
            # it: ``<test case name>.json`` under AUDIT_SCRIPTS_DIR. When
            # ``audit_script_name`` is omitted it is derived from the running test.
            if not audit_script_name:
                audit_script_name = current_test_name()
            script_name = audit_script_name
            source_script = paths.AUDIT_SCRIPTS_DIR / "{}.json".format(audit_script_name)
            logging.info("Existing audit script used - {}".format(source_script))
            # Keep each audit test's script and outputs in its own
            # ``temp/<script>/<test>/`` folder (a fixture audit's in its staging folder).
            if artifact_label:
                script_stem = current_test_script_stem()
                staging_dir = fixture_audit_root(AUDIT_OUTPUT_DIR, script_stem) / artifact_label
                if staging_dir.exists():  # stale files from an earlier run must not mix in
                    shutil.rmtree(staging_dir)
                staging_dir.mkdir(parents=True)
                _fixture_audits[(script_stem, artifact_label)] = str(staging_dir)
                audit_output_path = str(staging_dir)
            else:
                audit_output_path = str(current_test_artifact_dir(AUDIT_OUTPUT_DIR))
            audit_config_path = os.path.join(audit_output_path, source_script.name)
            script = render_audit_script(audit_script_name, params)
            with open(audit_config_path, "w", encoding="utf-8") as file:
                file.write(script)
            Singleton_XClient.last_audit = {"output_dir": audit_output_path}
        else:
            audit_output_path = AUDIT_OUTPUT_DIR
        os.makedirs(audit_output_path, exist_ok=True)
        if audit_name == "eventbuffer":
            with open(audit_config_path, "r") as file:
                content = file.read()
                logging.info(content)
            audit_script_json = json.loads(content)
            audit_script_json["commands"][0]["parameters"][0]["value"] = params["eventTypes"]
            audit_script_json["commands"][0]["parameters"][1]["value"] = params["intervalStart"]
            with open(audit_config_path, "w") as file:
                file.write(json.dumps(audit_script_json))
                logging.info("New audit script saved!")
        with open(audit_config_path, "r", encoding="utf-8") as file:
            script_text = file.read()
        _run_audit_task(script_name, script_text, audit_output_path, timeout)
        if len(output_file_name) == 0:
            output_file_name = audit_name + ".json"
        audit_output_file = audit_output_path + "\\{}".format(output_file_name)
        if not os.path.isfile(audit_output_file):
            assert os.path.isfile(audit_output_path + "\\manifest.json"), "Audit failed and manifest not found!"
            failed = _command_execution_errors(audit_output_path)
            assert not failed, "Audit {} failed in XClient, no output: {}".format(audit_name, failed)
            logging.info("Audit output file not found, but manifest exists. Return manifest content instead.")
            with open(audit_output_path + "\\manifest.json", "r", encoding="utf-8") as file:
                content = file.read()
                logging.info(content)
            return content
        with open(audit_output_file, "r", encoding="utf-8") as file:
            content = file.read()
        # Path and size only: the output is on disk, and a full copy in the log
        # (e.g. a 190 MB eventlogs audit) is also held in memory by pytest's log capture.
        logging.info("Audit %s output: %s (%d bytes)", audit_name, audit_output_file, os.path.getsize(audit_output_file))
        # Record the revised audit script and output for each event buffer audit
        # in memory. The audit may run only once inside a module-scoped fixture,
        # so the actual per-test files are written later by the autouse fixture
        # in conftest.py (once for each test).
        if audit_name == "eventbuffer":
            Singleton_XClient.last_event_buffer_audit = {
                "audit_script": script_text,
                "output_file_name": output_file_name,
                "output": content,
                "source_script": current_test_script_stem(),
            }
        if output_file_name.endswith(".json"):
            return json.loads(content)
        return content

    def run_script(self, params = {}, output_file_name = "", audit_script_name = "", timeout = None):
        """Run the audit script ``<test case name>.json`` under AUDIT_SCRIPTS_DIR.

        The audit name is taken from the first command in the script. Returns
        the parsed output (or the manifest content if the audit output is
        missing). If ``timeout`` (in seconds) is given and the audit takes
        longer, the test fails.
        """
        if not audit_script_name:
            audit_script_name = current_test_name()
        source_script = paths.AUDIT_SCRIPTS_DIR / "{}.json".format(audit_script_name)
        logging.info("Existing audit script used - {}".format(source_script))
        audit_output_path = str(current_test_artifact_dir(AUDIT_OUTPUT_DIR))
        os.makedirs(audit_output_path, exist_ok=True)
        audit_config_path = os.path.join(audit_output_path, source_script.name)
        script = apply_razor_public(source_script.read_text(encoding="utf-8"))
        audit_name = json.loads(script)["commands"][0]["name"]
        with open(audit_config_path, "w", encoding="utf-8") as file:
            file.write(script)
        logging.info(script)
        Singleton_XClient.last_audit = {"output_dir": audit_output_path}
        _run_audit_task(audit_script_name, script, audit_output_path, timeout)
        if len(output_file_name) == 0:
            output_file_name = audit_name + ".json"
        audit_output_file = audit_output_path + "\\{}".format(output_file_name)
        if not os.path.isfile(audit_output_file):
            assert os.path.isfile(audit_output_path + "\\manifest.json"), "Audit failed and manifest not found!"
            failed = _command_execution_errors(audit_output_path)
            assert not failed, "Audit {} failed in XClient, no output: {}".format(audit_name, failed)
            logging.info("Audit output file not found, but manifest exists. Return manifest content instead.")
            with open(audit_output_path + "\\manifest.json", "r") as file:
                content = file.read()
                logging.info(content)
            return content
        with open(audit_output_file, "r") as file:
            content = file.read()
        logging.info("Audit %s output: %s (%d bytes)", audit_name, audit_output_file, os.path.getsize(audit_output_file))
        if output_file_name.endswith(".json"):
            return json.loads(content)
        return content

    def version(self):
        output = run_windows_commands([str(win_xclient_path), '--version'])
        raw_version = output.split("\n")[1].split(" ")[-1]
        version, _, _ = raw_version.rpartition('.')
        return version

    def get_config(self, config_file_name):
        """Dump the xclient config into the current test's artifact folder and
        return the full path of the written file."""
        config_path = str(current_test_artifact_dir(AUDIT_OUTPUT_DIR) / config_file_name)
        run_windows_commands([str(win_xclient_path), '-x', config_path])
        return config_path

    def get_config_value(self, key, config_file_name="xclient_config.txt"):
        """Dump the xclient config via get_config and return the value of
        ``key``, or ``None`` if absent."""
        return read_xclient_config(self.get_config(config_file_name)).get(key)

    def set_config_data(self, config_path):
        """Apply every setting that differs between the current xclient config
        and the config dumped at ``config_path`` (a get_config() output) through
        the HXSim stub policy. Return True once the dumped config matches
        ``config_path`` exactly, else False."""
        from tests.util import hxsim_ioc
        target_config = read_xclient_config(config_path)
        current_config = read_xclient_config(self.get_config("current_xclient_config.txt"))
        if current_config == target_config:
            logging.info("Current XClient config already matches %s", config_path)
            return True
        if current_config.keys() != target_config.keys():
            logging.error("XClient config keys differ, cannot be fixed by a policy update: %s",
                          sorted(current_config.keys() ^ target_config.keys()))
            return False
        changes = {key: value for key, value in target_config.items() if current_config[key] != value}
        logging.info("Update %d XClient settings: %s", len(changes), changes)
        hxsim_ioc.apply_xclient_settings(changes)
        if read_xclient_config(self.get_config("updated_xclient_config.txt")) == target_config:
            logging.info("Updated XClient config matches %s", config_path)
            return True
        logging.error("Updated XClient config does not match %s", config_path)
        return False
