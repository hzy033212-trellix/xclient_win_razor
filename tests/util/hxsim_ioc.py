"""HXSim IOC alert verification helpers (merged from HXSim_Verify_IOCs).

hxsim (``<install_dir>\\hxsim``) plays the HX server for a side-loaded XClient:
the stub policy (``<install_dir>\\ma_stub_policy.xml``) points the agent at
127.0.0.1:8443, ``publish_feed`` signs an OpenIOC feed built from CONDITIONS,
Eventor matches events against it and queues alerts. Alert delivery on this host
is the legacy /match doorbell + ``iocmatch`` pull: we drop an iocmatch task, the
daemon uploads queued matches to ``rundir\\uploads\\task_*_data_*``, and hxsim
writes the decrypted XML next to each upload as ``<upload>.decoded``. Each
``<MatchItem><result>`` is base64(gzip(JSON)) with
``{"values": {"<eventType>/<field>": ...}, "key": {"condition_id": ...}}``.

The IOC tests trigger events with Razor's own trigger classes
(tests/test_eventor_collection) and select the alert with Razor's own
``find_data_in_audit_for_event``, so the only difference from the eventbuffer
audit tests is where the event record comes from.

hxsim needs Node >= 18 (``node_exe`` in paths.json); the system node is not used.
"""
import base64
import datetime
import glob
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import winreg
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import psutil

from tests.util import paths
from tests.util.artifactory import xclient_source
from tests.util.eventor_utils import find_data_in_audit_for_event
from tests.util.host_setup import OPENSSL_DIR, WHOAMI_EXE  # staged by host_setup at session start
from tests.util.git_utils import git
from tests.util.util import func_wait, run_windows_commands
from tests.test_xclient.provisioned_xclient import (
    AUDIT_OUTPUT_DIR,
    artifact_dir_for_node,
    current_test_artifact_dir,
    dev_binaries_installed,
    dump_xclient_config,
    ma_installed,
    restart_xclient_service,
    start_xclient_service,
    stop_xclient_service,
    swap_in_dev_binaries,
    wait_for_xclient_config,
    xclient_processes,
)

logger = logging.getLogger("tests")

INSTALL_DIR = paths.INSTALL_DIR
HXSIM_DIR = INSTALL_DIR / "hxsim"
# hxsim's source: tools/hxsim of the XClient repo at the commit XCLIENT_VERSION
# was built from (artifactory.xclient_source), fetched by refresh_hxsim_source.
HXSIM_REPO = "https://github.trellix.com/unified-agent/XClient.git"
HXSIM_REPO_PATH = "tools/hxsim"
# The XClient commit HXSIM_DIR was fetched from.
HXSIM_SOURCE_STAMP = HXSIM_DIR / "xclient_commit.txt"
RUNDIR = HXSIM_DIR / "rundir"
UPLOADS_DIR = RUNDIR / "uploads"
# The cert hxsim issues the agent at SCEP enrollment; tasks are encrypted to it.
ENROLLED_CERT = RUNDIR / "state" / "enrolled.crt"
# Feed files written by bin/gen-intel*.js (the rest of certs\out is the dev PKI,
# re-minted by generate_pki before every hxsim start).
GENERATED_FEED_FILES = ["intel.cms", "intel.payload", "intel_enc.cms",
                        "intel_metadata.cms", "intel_metadata.payload"]
CERTS_OUT = HXSIM_DIR / "certs" / "out"
GEN_CERTS_SH = HXSIM_DIR / "certs" / "gen-certs.sh"
OPENSSL_EXE = OPENSSL_DIR / "openssl.exe"
# Tracked template, without keys (mxs/ca/pem and mxs/provo/{cert,key} are empty).
STUB_POLICY = INSTALL_DIR / "ma_stub_policy.xml"
# Scratch output shared by the whole IOC session (feed, server log, log exports).
HXSIM_WORK_DIR = paths.AUDIT_OUTPUT_DIR / "hxsim"
FEED_XML = HXSIM_WORK_DIR / "iocs_all_events.xml"
SERVER_LOG = HXSIM_WORK_DIR / "hxsim_server.log"
# STUB_POLICY with the keys of the current PKI filled in (written by generate_pki).
GENERATED_STUB_POLICY = HXSIM_WORK_DIR / STUB_POLICY.name
# Written by prepare_ioc_environment once IOC alerting is live; lets a later
# pytest run (the CI "Run all IOC tests" step) reuse the running hxsim.
READY_MARKER = HXSIM_WORK_DIR / "ready.json"

# Where the MA stub reads its policy (not a dependency).
STUB_POLICY_DEST = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Trellix" / "XClient" / STUB_POLICY.name
UDP_KEY = "mxa/eventor/udp_send_events"  # UDP ipv4NetworkEvents on Windows (default false)

HXSIM_PORT = 8443           # full poll (HTTPS/mTLS)
HXSIM_PORTS = (HXSIM_PORT, 8080)
HXSIM_ENV = {"HXSIM_LOG_REQS": "1", "HXSIM_PROVO_ISSUE": "1", "HXSIM_AUTO_IOCMATCH": "1"}
HXSIM_READY = "hxsim full-poll (HTTPS/mTLS) on 127.0.0.1:%d" % HXSIM_PORT
MIN_NODE_MAJOR = 18

INDICATOR_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
# Prefix the file / registry IOC tests give their trigger targets so the
# conditions below match only our events.
IOC_NAME_PREFIX = "hxsim_ioc_"

# key -> (event type, [(field, operator, type, value)], comment).
# Multiple tests in one condition are ANDed.
_CONDITION_DEFS = {
    "process":    ("processEvent",
                   [("processPath", "starts-with", "text", "C:\\Temp\\")],
                   "Any process run from C:\\Temp (whoami.exe)"),
    "filewrite":  ("fileWriteEvent",
                   [("fileName", "contains", "text", IOC_NAME_PREFIX)],
                   "File write to a file named hxsim_ioc_*"),
    "ipv4":       ("ipv4NetworkEvent",
                   [("remotePort", "contains", "text", str(HXSIM_PORT)),
                    ("process", "contains", "text", "python")],
                   "python.exe connecting to the 'HX' (hxsim) port 8443"),
    "dns":        ("dnsLookupEvent",
                   [("hostname", "matches", "text", "w{3}\\.trellix\\..*")],
                   "DNS lookup of www.trellix.*"),
    "imageload":  ("imageLoadEvent",
                   [("process", "contains", "text", "notepad.exe"),
                    ("fileName", "contains", "text", "uxtheme.dll")],
                   "notepad.exe loading uxtheme.dll"),
    "address":    ("addressNotificationEvent",
                   [("address", "contains", "text", ".")],
                   "Any IPv4 address-change notification"),
    "regevents":  ("regKeyEvent",
                   [("path", "contains", "text", IOC_NAME_PREFIX.upper())],
                   "Any registry key/value event on an HXSIM_IOC_* name"),
    "udp":        ("ipv4NetworkEvent",
                   [("protocol", "contains", "text", "UDP"),
                    ("remotePort", "contains", "text", "5555")],
                   "UDP datagram to port 5555; needs mxa/eventor/udp_send_events=true"),
    "icmp":       ("ipv4NetworkEvent",
                   [("protocol", "contains", "text", "ICMP")],
                   "ICMP echo"),
    "process_ipconfig": ("processEvent",
                   [("process", "contains", "text", "ipconfig.exe"),
                    ("processCmdLine", "contains", "text", "/flushdns")],
                   "ipconfig /flushdns"),
    "imageload_service": ("imageLoadEvent",
                   [("process", "contains", "text", "spoolsv.exe"),
                    ("fileName", "contains", "text", "nsi.dll")],
                   "spooler service loading nsi.dll"),
    "url_any":    ("urlMonitorEvent",
                   [("hostname", "contains", "text", "httpbin")],
                   "Any HTTP method to httpbin.*"),
}


def _condition_id(event_type, tests):
    """Condition id derived from the condition's content.

    Eventor caches the feed and keeps the definition of every condition id it
    already has: a later feed with the same ids is a "diff" load that skips them
    ("excluded N conditions that exist in current intel_id"). So a changed
    condition must get a new id, or the agent keeps matching the old tests.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "hxsim-ioc:" + json.dumps([event_type, tests])))


# key -> (condition id, event type, tests, comment)
CONDITIONS = {key: (_condition_id(evt, tests), evt, tests, comment)
              for key, (evt, tests, comment) in _CONDITION_DEFS.items()}


#####################
# Node / hxsim deps #
#####################


def require_dependencies():
    """Fail fast unless everything the IOC session needs is present."""
    needed = [HXSIM_DIR / "hxsim.js", HXSIM_DIR / "bin" / "gen-iocmatch.js",
              HXSIM_DIR / "bin" / "gen-intel.js", HXSIM_DIR / "bin" / "gen-intel-metadata.js",
              HXSIM_DIR / "bin" / "gen-intel-key.js", HXSIM_DIR / "bin" / "gen-policy.js",
              GEN_CERTS_SH, paths.BASH_EXE, OPENSSL_EXE, STUB_POLICY, WHOAMI_EXE]
    missing = [str(p) for p in needed if not p.exists()]
    assert not missing, "Missing IOC test dependencies (see tests/test_ioc_alerts/README.md):\n" + "\n".join(missing)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HXSIM_WORK_DIR.mkdir(parents=True, exist_ok=True)
    version = run_windows_commands([str(node_exe()), "--version"]).strip()
    major = int(re.match(r"v(\d+)", version).group(1))
    assert major >= MIN_NODE_MAJOR, "hxsim needs node >= {}, but {} is {}".format(MIN_NODE_MAJOR, node_exe(), version)
    # hxsim's lib/cms.js runs a bare `openssl` unless HXSIM_OPENSSL is set; every
    # node call and the server inherit os.environ.
    os.environ.setdefault("HXSIM_OPENSSL", str(OPENSSL_EXE))


def node_exe():
    """Node >= 18 for hxsim: ``node_exe`` in paths.json, or the NODE environment variable."""
    exe = os.environ.get("NODE") or str(paths.NODE_EXE)
    assert os.path.isfile(exe), (
        "Node >= {} not found at {} -- unzip a portable node (node-v24.x-win-x64.zip) there "
        "or fix node_exe in paths.json (the system node is not used)".format(MIN_NODE_MAJOR, exe))
    return exe


def node(*args):
    # Decode leniently: on a bad/partial upload decode-iocmatch.js dumps raw CMS bytes.
    p = subprocess.run([node_exe()] + list(args), cwd=str(HXSIM_DIR),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


################
# hxsim server #
################


def _listening(port):
    # Look for a listening socket instead of connecting: a python -> :8443
    # connection is exactly what the `ipv4` IOC condition alerts on.
    return any(c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN
               for c in psutil.net_connections("tcp"))


def _hxsim_node_pids():
    output = subprocess.run(['wmic', 'process', 'where', "name='node.exe'", 'get',
                             'ProcessId,CommandLine', '/format:csv'], capture_output=True, text=True).stdout
    return [line.rsplit(",", 1)[-1].strip() for line in output.splitlines() if "hxsim.js" in line]


def stop_all_hxsim(timeout=30):
    """Stop every node process running hxsim.js (from any folder) and wait for its ports to free up."""
    READY_MARKER.unlink(missing_ok=True)  # the prepared environment is gone with hxsim
    pids = _hxsim_node_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/f", "/t", "/pid", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Stopped hxsim node process(es): %s", pids or "none running")
    stopped = func_wait(lambda: not _hxsim_node_pids() and not any(_listening(p) for p in HXSIM_PORTS),
                        interval=1, timeout=timeout)
    assert stopped, "hxsim still running or ports {} held by another program".format(HXSIM_PORTS)


class HxsimStalled(AssertionError):
    """hxsim died or stopped receiving agent traffic, so no alert can arrive."""


class HxsimWatchdog:
    """Detects a dead or silent hxsim while a test waits for an alert.

    The agent polls hxsim about once a minute and hxsim logs every request
    (HXSIM_LOG_REQS), so a server log that stops growing means hxsim hung or the
    agent's channel to it is stuck: waiting longer for the alert is pointless.
    """

    def __init__(self, stall_after=240):
        self.stall_after = stall_after
        self.size = self._log_size()
        self.changed = time.time()

    @staticmethod
    def _log_size():
        try:
            return os.path.getsize(SERVER_LOG)
        except OSError:
            return -1

    def check(self):
        if not _hxsim_node_pids():
            raise HxsimStalled("hxsim node process is gone; log tail:\n" + _read_server_log()[-1500:])
        size = self._log_size()
        if size != self.size:
            self.size, self.changed = size, time.time()
        elif time.time() - self.changed >= self.stall_after:
            raise HxsimStalled("hxsim log {} has not grown for {}s (no agent polls); log tail:\n{}".format(
                SERVER_LOG, int(time.time() - self.changed), _read_server_log()[-1500:]))


def _read_server_log(offset=0):
    try:
        with open(SERVER_LOG, encoding="utf-8", errors="replace") as file:
            file.seek(offset)
            return file.read()
    except FileNotFoundError:
        return ""


# Preload that turns off Node's 300 s request timeout in hxsim's servers (a large
# audit result streamed in one PUT takes longer; see the file).
NO_REQUEST_TIMEOUT_JS = Path(__file__).resolve().parent / "hxsim_no_request_timeout.js"


def start_hxsim(timeout=60):
    """(Re)start ``node hxsim.js --serve`` detached from <install_dir>\\hxsim, log -> temp\\hxsim,
    with NO_REQUEST_TIMEOUT_JS preloaded."""
    stop_all_hxsim()
    out = open(SERVER_LOG, "a", encoding="utf-8")
    out.write("\n===== start %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    out.flush()
    offset = out.tell()
    proc = subprocess.Popen([node_exe(), "--require", str(NO_REQUEST_TIMEOUT_JS), "hxsim.js", "--serve"],
                            cwd=str(HXSIM_DIR),
                            env=dict(os.environ, **HXSIM_ENV), stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, close_fds=True,
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    logger.info("Started hxsim (pid %d), log %s", proc.pid, SERVER_LOG)
    ready = func_wait(lambda: HXSIM_READY in _read_server_log(offset) or proc.poll() is not None,
                      interval=1, timeout=timeout)
    assert ready and proc.poll() is None, "hxsim did not come up:\n" + _read_server_log(offset)[-1500:]


def _rmtree(path):
    """shutil.rmtree that also removes read-only files (git's object files are read-only)."""
    def make_writable(func, failed, _exc_info):
        os.chmod(failed, 0o700)
        func(failed)
    if os.path.exists(path):
        shutil.rmtree(str(path), onerror=make_writable)


def _fetch_hxsim_source(commit, attempts=3):
    """Sparse-fetch HXSIM_REPO_PATH at commit into a new temp folder and return it.

    Each attempt starts over in a fresh folder: git can transiently fail to read
    files it just wrote there (seen as "not a git repository" right after git init,
    with an on-access file scanner active on the host).
    """
    for attempt in range(1, attempts + 1):
        scratch = tempfile.mkdtemp(prefix="hxsim_src_")
        try:
            git("init", "-q", scratch)
            git("-C", scratch, "config", "core.autocrlf", "false")
            git("-C", scratch, "config", "core.eol", "lf")
            git("-C", scratch, "remote", "add", "origin", HXSIM_REPO)
            git("-C", scratch, "sparse-checkout", "set", HXSIM_REPO_PATH)
            git("-C", scratch, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit)
            git("-C", scratch, "checkout", "-q", "FETCH_HEAD")
            return scratch
        except AssertionError as e:
            _rmtree(scratch)
            if attempt == attempts:
                raise
            logger.warning("hxsim source fetch attempt %d failed, retrying: %s", attempt, e)
            time.sleep(5)


def refresh_hxsim_source():
    """Make <install_dir>\\hxsim a copy of tools/hxsim at the commit XCLIENT_VERSION was built from.

    Nothing is fetched if HXSIM_SOURCE_STAMP shows it already is (what earlier
    runs left in rundir\\ and certs\\out\\ is cleared by reset_hxsim / generate_pki).
    Otherwise a shallow, sparse fetch of that commit (artifactory.xclient_source)
    checks out only HXSIM_REPO_PATH (about 1 MB), with
    core.autocrlf=false and core.eol=lf so files keep the repo's LF line endings
    (its .gitattributes marks *.sh / *.js as text, which Windows git would
    otherwise check out as CRLF; a CRLF certs/gen-certs.sh breaks under bash). The
    old folder is emptied only after the download succeeded. Credentials: see
    git_utils.git_env (XCLIENT_GITHUB_TOKEN or Git Credential Manager; git never
    prompts, so a missing one fails fast).
    """
    branch, commit = xclient_source()
    try:
        current = HXSIM_SOURCE_STAMP.read_text().strip()
    except OSError:
        current = None
    if current == commit and (HXSIM_DIR / "hxsim.js").is_file():
        logger.info("hxsim source already at %s %s:%s (commit %s): %s",
                    HXSIM_REPO, branch, HXSIM_REPO_PATH, commit[:12], HXSIM_DIR)
        return
    stop_all_hxsim()  # a running hxsim keeps its folder in use
    scratch = _fetch_hxsim_source(commit)
    try:
        source = Path(scratch, *HXSIM_REPO_PATH.split("/"))
        assert (source / "hxsim.js").is_file(), "No hxsim.js in {}:{} of {}".format(
            commit, HXSIM_REPO_PATH, HXSIM_REPO)
        # Empty the folder rather than delete it: Windows refuses to remove a folder
        # another process has open (a shell or Explorer window in it, an editor
        # watching it), but its content can still go.
        HXSIM_DIR.mkdir(parents=True, exist_ok=True)
        for child in HXSIM_DIR.iterdir():
            _rmtree(child) if child.is_dir() else (os.chmod(child, 0o700), child.unlink())
        shutil.copytree(str(source), str(HXSIM_DIR), dirs_exist_ok=True)
        HXSIM_SOURCE_STAMP.write_text(commit)
    finally:
        _rmtree(scratch)
    logger.info("hxsim source refreshed from %s %s:%s (commit %s) into %s",
                HXSIM_REPO, branch, HXSIM_REPO_PATH, commit[:12], HXSIM_DIR)


def reset_hxsim():
    """Start hxsim from scratch: drop everything an earlier run left behind.

    Removes (hxsim's own fresh-start hygiene, L3_cheatsheet.md step 2):
      rundir\\tasks    queued tasks plus the hidden .done markers and .enc cache
      rundir\\uploads  every captured upload, i.e. all earlier IOC alerts
      rundir\\state    the agent's enrollment cert (re-issued by reenroll_agent)
      certs\\out\\intel*  the previously signed IOC feed (GENERATED_FEED_FILES)
    plus the session's server log and rendered feed under temp\\hxsim.
    """
    stop_all_hxsim()
    for name in ("tasks", "uploads", "state"):
        if (RUNDIR / name).exists():
            shutil.rmtree(str(RUNDIR / name))
    (RUNDIR / "tasks").mkdir(parents=True)
    UPLOADS_DIR.mkdir(parents=True)
    for name in GENERATED_FEED_FILES:
        (HXSIM_DIR / "certs" / "out" / name).unlink(missing_ok=True)
    for f in (SERVER_LOG, FEED_XML):
        f.unlink(missing_ok=True)
    logger.info("hxsim reset: no tasks, uploads (alerts), enrollment or IOC feed from earlier runs")


def generate_pki():
    """Mint a fresh hxsim dev PKI into certs\\out and re-pin the stub policy to it.

    ``certs/gen-certs.sh`` (Git Bash; ``openssl`` from <install_dir>\\openssl on
    PATH) re-mints the dev CA, server/agent/signer certs, intel_enc.key and the
    comms CRL. The stub policy's ``mxs/ca/pem`` and ``mxs/provo/{cert,key}`` are
    derived from that PKI, so ``bin/gen-policy.js --provision`` then fills them in
    from the key-less STUB_POLICY template into GENERATED_STUB_POLICY (every other
    setting preserved; the tracked template never holds keys). Run while hxsim is
    stopped and after reset_hxsim wiped rundir\\state: an enrollment cert from the
    old CA would make task envelopes target the wrong recipient. hxsim must then
    be up before the new policy reaches the agent (drop_stub_policy), so the
    agent SCEP-enrolls against the new CA.
    """
    if CERTS_OUT.exists():
        shutil.rmtree(str(CERTS_OUT))
    env = dict(os.environ, NODE=node_exe())
    env["PATH"] = str(OPENSSL_EXE.parent) + os.pathsep + env.get("PATH", "")
    p = subprocess.run([str(paths.BASH_EXE), "certs/gen-certs.sh"], cwd=str(HXSIM_DIR), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, "gen-certs.sh failed:\n" + out[-1500:]
    HXSIM_WORK_DIR.mkdir(parents=True, exist_ok=True)
    rc, out, err = node("bin/gen-policy.js", "--provision", "--template", str(STUB_POLICY),
                        "--out", str(GENERATED_STUB_POLICY))
    assert rc == 0, "gen-policy.js failed:\n" + out + err
    logger.info("hxsim dev PKI minted into %s; stub policy with its keys: %s", CERTS_OUT, GENERATED_STUB_POLICY)


def reenroll_agent(timeout=300):
    """Restart XClient so it SCEP-enrolls with the freshly reset hxsim.

    The agent only enrolls when it starts, and hxsim encrypts every task to the
    enrolled cert, so this must happen before any task (e.g. the intel key).
    """
    restart_xclient_service()
    assert func_wait(ENROLLED_CERT.is_file, interval=3, timeout=timeout), \
        "XClient did not enroll with hxsim within {}s (no {}), see {}".format(timeout, ENROLLED_CERT, SERVER_LOG)
    logger.info("Agent enrolled with hxsim: %s", ENROLLED_CERT)


def deliver_intel_key(timeout=300):
    """``node bin/gen-intel-key.js`` and wait for the agent's SUCCESS result.

    ``--created <now>`` gives the fixed task a fresh id, so hxsim advertises it even
    if it was delivered before. Needed after every fresh agent install.
    """
    created = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    rc, out, err = node("bin/gen-intel-key.js", "--created", created)
    assert rc == 0, "gen-intel-key.js failed:\n" + out + err
    rc, task_id, err = node("-e", "var tq=require('./lib/taskqueue');process.stdout.write("
                            "tq.taskId('intel-key',require('fs').readFileSync('rundir/tasks/intel-key.json')))")
    task_id = task_id.strip()
    logger.info("intel-key task %s dropped; waiting for the daemon to run it.....", task_id)

    def key_status():
        for f in UPLOADS_DIR.glob("task_{}_data_*.decoded".format(task_id)):
            m = re.search(r"<Status>([^<]*)</Status>\s*<Message>([^<]*)</Message>",
                          f.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.groups()
        return None

    status = func_wait(key_status, interval=3, timeout=timeout)
    assert status, "The daemon never returned the intel-key result (is it polling hxsim? see {})".format(SERVER_LOG)
    assert status[0] == "SUCCESS", "intel-key command failed: {} {}".format(*status)
    logger.info("Intel key stored by the agent: %s (%s)", *status)


###############
# Stub policy #
###############


# Settings added to the stub policy on top of GENERATED_STUB_POLICY: the XClient
# config of the running test group (see tests/util/audit_batch.py). ``policy``
# is a bulk base (not verified one by one), ``settings`` are verified with
# ``xclient -x`` after every change. A key the stub policy already holds keeps
# the stub's value in ``policy`` (it connects XClient to hxsim).
XCLIENT_POLICY = {}
XCLIENT_SETTINGS = {}


def _set_setting(text, name, value):
    line = '<Setting name=%s value=%s/>' % (quoteattr(name), quoteattr(str(value)))
    pattern = re.compile(r'<Setting name="%s" value="[^"]*"/>' % re.escape(name))
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text)
    i = text.index(">", text.index("<Section ")) + 1  # first setting of the first <Section>
    return text[:i] + "\n" + line + text[i:]


def _stub_policy_text():
    """GENERATED_STUB_POLICY with mxa/eventor/udp_send_events forced to true and
    the group's XCLIENT_POLICY / XCLIENT_SETTINGS added."""
    text = GENERATED_STUB_POLICY.read_text(encoding="utf-8")
    stub_keys = set(re.findall(r'<Setting name="([^"]*)"', text))
    for name, value in XCLIENT_POLICY.items():
        if name not in stub_keys:
            text = _set_setting(text, name, value)
    for name, value in XCLIENT_SETTINGS.items():
        text = _set_setting(text, name, value)
    return _set_setting(text, UDP_KEY, "true")


# run_tests.ps1 -WithMA (the Orbit msi), as win_razor did: MA delivers one setting,
# self-protection off, so the fake-MA build's binaries (FAKE_MA_BIN_DIR) can be
# swapped in; from then on the stub policy is XClient's policy source, as without MA.
MA_POLICY_BASE = INSTALL_DIR / "xc_Eventor+UnifiedEdr_only.xml"
MA_POLICY = HXSIM_WORK_DIR / "ma_policy.xml"
FAKE_MA_BIN_DIR = Path(os.environ["XCLIENT_FAKE_MA_BIN"]) if os.environ.get("XCLIENT_FAKE_MA_BIN") else None
PROTECTION_KEY = "mxa/process/protection_enabled"


def _ma_policy_text(settings):
    """MA_POLICY_BASE with ``settings`` set (or added to its first policy section)."""
    root = ET.parse(str(MA_POLICY_BASE)).getroot()
    existing = {s.get("name"): s for s in root.iter("Setting")}
    target = next(sec for ps in root.iter("EPOPolicySettings") if ps.get("type") != ".EPO_ENFORCE"
                  for sec in ps.iter("Section"))
    for name, value in settings.items():
        setting = existing.get(name)
        if setting is None:
            setting = ET.SubElement(target, "Setting", {"name": name})
        setting.text = value
    return ET.tostring(root, encoding="unicode")


def ma_protection_off():
    """Turn XClient's self-protection off through MA, as win_razor's
    do_ma_policy_update did: local_policy_config, MA self-protection off, masvc
    restarted, then wait until ``xclient -x`` shows it."""
    from tests.util.artifactory import AACUTIL, LOCAL_POLICY_CONFIG_EXE
    MA_POLICY.parent.mkdir(parents=True, exist_ok=True)
    MA_POLICY.write_text(_ma_policy_text({PROTECTION_KEY: "false"}), encoding="utf-8")
    logger.info("Import %s through MA (local_policy_config).....", MA_POLICY)
    run_windows_commands([str(LOCAL_POLICY_CONFIG_EXE), "-f", str(MA_POLICY)])
    run_windows_commands([str(AACUTIL), "disable", "-group", "ma.selfprotect"])
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\masvc", 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "LockdownEnabled", 0, winreg.REG_DWORD, 0)
    run_windows_commands(["net", "stop", "masvc"])
    run_windows_commands(["net", "start", "masvc"])
    wait_for_xclient_config({PROTECTION_KEY: "false"})


def install_fake_ma_binaries():
    """With MA: self-protection off, then the fake-MA build's binaries swapped in
    (skipped if already in place)."""
    assert FAKE_MA_BIN_DIR and FAKE_MA_BIN_DIR.is_dir(),         "Set XCLIENT_FAKE_MA_BIN (run_tests.ps1 -FakeMaBin) to the fake-MA build's xclient bin folder"
    if dev_binaries_installed(FAKE_MA_BIN_DIR):
        logger.info("Fake-MA binaries already installed from %s", FAKE_MA_BIN_DIR)
        return
    ma_protection_off()
    swap_in_dev_binaries(FAKE_MA_BIN_DIR, HXSIM_WORK_DIR)


def drop_stub_policy():
    """Point XClient at hxsim: drop the stub policy (with UDP capture on), restart, verify.

    Skipped when the dropped policy is already up to date.
    """
    wanted = _stub_policy_text()
    if STUB_POLICY_DEST.is_file() and STUB_POLICY_DEST.read_text(encoding="utf-8") == wanted:
        logger.info("Stub policy already in place: %s", STUB_POLICY_DEST)
        return
    logger.info("Drop stub policy %s -> %s.....", GENERATED_STUB_POLICY, STUB_POLICY_DEST)
    STUB_POLICY_DEST.parent.mkdir(parents=True, exist_ok=True)
    try:
        STUB_POLICY_DEST.write_text(wanted, encoding="utf-8")
        restart_xclient_service()
    except PermissionError:
        stop_xclient_service()
        STUB_POLICY_DEST.write_text(wanted, encoding="utf-8")
        start_xclient_service()
    wait_for_xclient_config(dict(XCLIENT_SETTINGS, **{UDP_KEY: "true"}))


def set_xclient_config(policy, settings):
    """Make the stub policy hold exactly ``policy`` + ``settings`` (a test group's
    config) on top of the provisioned stub policy, restarting XClient if it changed."""
    XCLIENT_POLICY.clear()
    XCLIENT_POLICY.update(policy)
    XCLIENT_SETTINGS.clear()
    XCLIENT_SETTINGS.update({k: str(v) for k, v in settings.items()})
    drop_stub_policy()


def apply_xclient_settings(settings):
    """Change some XClient settings through the stub policy and wait until
    ``xclient -x`` shows them. Nothing is restarted if XClient already has them."""
    settings = {k: str(v) for k, v in settings.items()}
    XCLIENT_SETTINGS.update(settings)
    current = dump_xclient_config()
    in_place = STUB_POLICY_DEST.is_file() and STUB_POLICY_DEST.read_text(encoding="utf-8") == _stub_policy_text()
    if all(current.get(k) == v for k, v in settings.items()) and in_place:
        logger.info("XClient already has %s", settings)
        return
    drop_stub_policy()


################
# IOC feed     #
################


def render_feed():
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<indicator id="%s"' % INDICATOR_ID,
             '    xmlns="http://www.openioc.org/2012/OpenIOC"',
             '    require="http://www.mandiant.com/OpenIOC/Events#1">', '']
    for key, (cid, evt, tests, comment) in CONDITIONS.items():
        lines.append("  <!-- %s: %s -->" % (key, escape(comment).replace("--", "-")))
        lines.append('  <condition id="%s" scope="">' % cid)
        for field, op, typ, value in tests:
            lines.append('    <test value=%s operator=%s type=%s>%s</test>' % (
                quoteattr(evt + "/" + field), quoteattr(op), quoteattr(typ), escape(value)))
        lines.append("  </condition>")
        lines.append("")
    lines.append("</indicator>")
    return "\n".join(lines) + "\n"


def sign_feed():
    """Sign CONDITIONS into hxsim (served at /content/v1/intel/ioc/delta).

    Run before hxsim starts serving, so the agent's first pull (right after the
    intel key) never gets a stale intel.cms left in certs\\out by an earlier run.
    """
    FEED_XML.write_text(render_feed(), encoding="utf-8")
    for tool, flag in (("bin/gen-intel.js", "--in"), ("bin/gen-intel-metadata.js", "--from-openioc")):
        rc, out, err = node(tool, flag, str(FEED_XML))
        assert rc == 0, "{} failed:\n{}{}".format(tool, out, err)
    logger.info("IOC feed (%d conditions) signed into %s", len(CONDITIONS), HXSIM_DIR / "certs" / "out")


def publish_feed():
    """Restart XClient so Eventor holds exactly the current feed.

    Eventor pulls unconditionally on startup (otherwise only on its 900 s refresh
    timer). It also caches the last feed it received and full-loads that cache
    on startup, so after this restart conditions from an earlier feed are gone;
    without it they would stay in memory next to the new ones until the next
    restart. wait_until_alerting is the readiness check that follows.
    """
    old = {pid for pid, mode in xclient_processes().items() if mode == "Eventor"}
    restart_xclient_service()
    new_eventor = func_wait(lambda: {pid for pid, mode in xclient_processes().items() if mode == "Eventor"} - old,
                            interval=3, timeout=120)
    assert new_eventor, "No new Eventor process after the XClient restart"
    logger.info("Eventor restarted (pid %s)", new_eventor)


##########
# Alerts #
##########


def _wait_stable(path, quiet=3.0, limit=60):
    """Wait until hxsim has finished writing ``path`` (size unchanged for ``quiet`` s)."""
    end = time.time() + limit
    last, since = -1, time.time()
    while time.time() < end:
        size = os.path.getsize(path)
        if size != last:
            last, since = size, time.time()
        elif time.time() - since >= quiet:
            return True
        time.sleep(0.5)
    return False


def _decode_matches(path):
    """MatchItems in an iocmatch upload, or None if it isn't one (yet)."""
    # Prefer hxsim's <upload>.decoded sidecar; the node decoder is only a fallback
    # (from an interactive PowerShell session it silently lost its XML output).
    out = ""
    if os.path.isfile(path + ".decoded"):
        with open(path + ".decoded", "rb") as file:
            out = file.read().decode("utf-8", "replace")
    if "<?xml" not in out:
        out = node("bin/decode-iocmatch.js", path)[1]
    start = out.find("<?xml")
    if start < 0 or 'generator="iocmatch"' not in out[start:start + 300]:
        return None
    matches = []
    for item in ET.fromstring(out[start:].encode("utf-8")).iter("MatchItem"):
        rec = {c.tag: (c.text or "") for c in item}
        try:
            rec["body"] = json.loads(gzip.decompress(base64.b64decode(rec.get("result", ""))).decode("utf-8"))
        except Exception as e:
            rec["body"] = {"_decode_error": str(e)}
        rec["upload"] = path
        matches.append(rec)
    return matches


def event_record(match, event_type):
    """IOC alert -> plain event dict, like an eventbuffer audit item."""
    prefix = event_type + "/"
    return {k[len(prefix):]: v for k, v in match["body"].get("values", {}).items() if k.startswith(prefix)}


def _normalize_record(event_type, rec):
    """Alert-side normalisation on top of Razor's find_data_in_audit_for_event rules.

    Razor uppercases regKey path/keyPath/hive in the *filter*; alerts report
    path/keyPath upper-case already but not always hive. (imageLoadEvent
    "process" case is handled by find_data_in_audit_for_event itself.)
    """
    rec = dict(rec)
    if event_type == "regKeyEvent":
        for k in ("path", "keyPath", "hive"):
            if k in rec:
                rec[k] = str(rec[k]).upper()
    return rec


class AlertCollector:
    """Pulls iocmatch uploads from hxsim and keeps every decoded alert for the session.

    Alerts are cached across tests, so an alert that arrived while another test
    was waiting is still found. Pulls are repeated because hxsim's auto-iocmatch
    writes the same rundir/tasks/iocmatch.json, so one pull can overwrite the other.
    """

    def __init__(self):
        self.started = time.time() - 2
        self.decoded = {}   # (path, mtime) -> matches
        self.max_marker = 0
        self.last_pull = 0

    def pull(self, repull=45):
        if time.time() - self.last_pull >= repull:
            rc, out, err = node("bin/gen-iocmatch.js")
            assert rc == 0, "gen-iocmatch failed:\n" + out + err
            self.last_pull = time.time()
            logger.info("iocmatch pull task dropped; waiting for the daemon poll/upload.....")
        uploads = [f for f in glob.glob(str(UPLOADS_DIR / "task_*_data_*")) if "." not in os.path.basename(f)]
        for f in sorted(uploads, key=os.path.getmtime):
            mtime = os.path.getmtime(f)
            if mtime < self.started or (f, mtime) in self.decoded or not _wait_stable(f):
                continue
            try:
                matches = _decode_matches(f)
            except ET.ParseError:
                matches = None
            if matches is None:
                if os.path.isfile(f + ".decoded"):  # decoded by hxsim: another task's result, never re-check it
                    self.decoded[(f, mtime)] = []
                continue
            self.decoded[(f, os.path.getmtime(f))] = matches
            for m in matches:
                try:
                    self.max_marker = max(self.max_marker, int(m.get("marker", 0)))
                except ValueError:
                    pass
            logger.info("iocmatch upload %s: %d match(es)", os.path.basename(f), len(matches))

    def alerts_for(self, cond_key):
        cid = CONDITIONS[cond_key][0]
        return [m for ms in self.decoded.values() for m in ms
                if m["body"].get("key", {}).get("condition_id") == cid]

    def forget_alerts(self):
        """Drop every alert seen so far (uploads stay marked as read)."""
        self.decoded = {key: [] for key in self.decoded}

    def ack(self):
        """Acknowledge every pulled match (clears the daemon queue, stops the /match re-fire)."""
        if self.max_marker:
            node("bin/gen-iocmatch.js", "--last-seen", str(self.max_marker))
            logger.info("Ack task dropped for markers <= %d", self.max_marker)

    def wait_for_alert(self, cond_key, filters, after, timeout=300, settle=20):
        """Wait for an alert of ``cond_key`` whose event passes Razor's filter.

        Raises HxsimStalled as soon as hxsim is dead or silent (see HxsimWatchdog).
        """
        event_type = CONDITIONS[cond_key][1]
        watchdog = HxsimWatchdog()
        time.sleep(settle)  # Eventor matches every 60 s (eventor/match_interval)

        def find():
            self.pull()
            pairs = [(m, _normalize_record(event_type, event_record(m, event_type))) for m in self.alerts_for(cond_key)]
            audit = {"eventItem": [{event_type: r} for _, r in pairs]}
            found = find_data_in_audit_for_event(audit, dict(filters), event_type, after=after)
            match = next((m for m, r in pairs if r is found), None)
            if match is None:
                watchdog.check()
            return match

        return func_wait(find, interval=5, timeout=timeout)


def wait_until_alerting(collector, timeout=600, rewrite=60):
    """Readiness gate: wait until a probe file write comes back as a `filewrite` IOC alert.

    For about a minute after an XClient restart, file writes are not matched
    (a file test run first after setup got no alert at all), so a fixed sleep is
    not enough. A new probe file is written every ``rewrite`` seconds until one
    of them is alerted, which proves event capture -> match -> alert -> pull works.
    """
    paths.RAZOR_PUBLIC.mkdir(parents=True, exist_ok=True)
    probes, end, last_write = set(), time.time() + timeout, 0
    try:
        while time.time() < end:
            if time.time() - last_write >= rewrite:
                probe = paths.RAZOR_PUBLIC / "{}warmup_{}.txt".format(IOC_NAME_PREFIX, int(time.time()))
                probe.write_text("hxsim IOC readiness probe")
                probes.add(probe)
                last_write = time.time()
                logger.info("Readiness probe written: %s", probe)
            collector.pull()
            names = {p.name for p in probes}
            if any(event_record(m, "fileWriteEvent").get("fileName") in names for m in collector.alerts_for("filewrite")):
                logger.info("IOC alerting is live (probe alert received)")
                # The ack also drains matches the agent still had queued from earlier
                # runs; then the tests start with an empty alert list.
                collector.ack()
                collector.forget_alerts()
                return
            time.sleep(5)
        assert False, "No IOC alert for the readiness probe within {}s, see {}".format(timeout, SERVER_LOG)
    finally:
        for probe in probes:
            probe.unlink(missing_ok=True)


def prepare_ioc_environment():
    """Bring a side-loaded XClient and a from-scratch hxsim to "IOC alerting is live".

    Without MA the installed binaries are used as they are; with MA (the Orbit
    msi, run_tests.ps1 -WithMA) the fake-MA build's are swapped in first
    (install_fake_ma_binaries), as win_razor did. hxsim itself is
    fetched from the XClient repo if it isn't at XCLIENT_VERSION's commit yet
    (refresh_hxsim_source), reset, and gets a freshly minted PKI (so the stub
    policy is re-pinned and re-dropped), so no tasks, alerts, enrollment, keys
    or feed carry over. hxsim is left running and
    READY_MARKER is written, so a
    later pytest run can reuse it (see environment_ready). The agent must already
    be installed (side_loading_setup).
    """
    refresh_hxsim_source()
    require_dependencies()
    if ma_installed():
        install_fake_ma_binaries()
    reset_hxsim()
    generate_pki()
    sign_feed()
    start_hxsim()
    drop_stub_policy()
    reenroll_agent()
    deliver_intel_key()
    publish_feed()
    wait_until_alerting(AlertCollector())
    READY_MARKER.write_text(json.dumps({
        "hxsim_pids": _hxsim_node_pids(), "feed_sha256": _feed_sha256(),
        "ready_at": datetime.datetime.utcnow().isoformat() + "Z"}), encoding="utf-8")
    logger.info("IOC environment ready (hxsim left running): %s", READY_MARKER)


def environment_ready():
    """True if prepare_ioc_environment's result can be reused: READY_MARKER exists,
    the same hxsim process still serves 8443, the feed has the current CONDITIONS
    and the XClient SERVICE and Eventor processes are running."""
    try:
        marker = json.loads(READY_MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    checks = {
        "hxsim still running": bool(set(marker.get("hxsim_pids", [])) & set(_hxsim_node_pids())),
        "hxsim listening on %d" % HXSIM_PORT: _listening(HXSIM_PORT),
        "feed has the current conditions": marker.get("feed_sha256") == _feed_sha256(),
        "XClient SERVICE + Eventor running": {"SERVICE", "Eventor"} <= set(xclient_processes().values()),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        logger.info("Prepared IOC environment not reusable (%s); setting it up again", ", ".join(failed))
    return not failed


def _feed_sha256():
    return hashlib.sha256(render_feed().encode("utf-8")).hexdigest()


def _ioc_out_dir(nodeid):
    return artifact_dir_for_node(AUDIT_OUTPUT_DIR, nodeid)


def _fire(out, cond_key, trigger, event_keys):
    """Fire ``trigger`` and write its event_metadata.json / trigger_info.json into
    ``out``; return (filters, after) for wait_for_alert."""
    cid, event_type, tests, comment = CONDITIONS[cond_key]
    result = trigger.trigger()
    filters = {k: result[k] for k in event_keys if k in result}
    after = trigger.trigger_timestamp - datetime.timedelta(seconds=2)  # agent clock rounding slack
    _write_json(out / "event_metadata.json", filters)
    _write_json(out / "trigger_info.json", {
        "trigger": type(trigger).__name__, "event_type": event_type, "condition_key": cond_key,
        "condition_id": cid, "ioc_tests": [{"field": "%s/%s" % (event_type, f), "operator": o, "type": t, "value": v}
                                           for f, o, t, v in tests],
        "trigger_timestamp": trigger.str_trigger_timestamp, "filter_after": after.isoformat()})
    return filters, after


def _clear(out):
    for stale in out.iterdir():  # a FAIL must not leave an earlier run's ioc_alert.json behind
        if stale.is_file():
            stale.unlink()


def fire_ioc_trigger(nodeid, cond_key, trigger, event_keys):
    """Fire the trigger of IOC test ``nodeid`` ahead of the test (ioc_batch.prime)."""
    out = _ioc_out_dir(nodeid)
    _clear(out)
    return _fire(out, cond_key, trigger, event_keys)


def verify_ioc_alert(collector, cond_key, trigger, event_keys, timeout=300, primed=None):
    """Trigger a Razor event, wait for its IOC alert and save artifacts under temp/<script>/<test>/.

    ``trigger`` is a Razor trigger instance (tests/test_eventor_collection); the
    filter is its result_info restricted to ``event_keys``, as in
    run_triggers_collect_results.

    ``primed`` (ioc_batch): the trigger already fired ahead of the test; its
    {"filters", "after", "fired"} are used and the first attempt only waits for
    the alert (the settle time counts from when it fired).

    If hxsim stalls (HxsimStalled) the IOC environment is set up again and the
    event is triggered once more; a second stall fails the test.
    """
    cid, event_type, tests, comment = CONDITIONS[cond_key]
    logger.info("IOC %s: %s (condition %s)%s", cond_key, comment, cid, " - primed" if primed else "")
    out = current_test_artifact_dir(AUDIT_OUTPUT_DIR)
    if not primed:
        _clear(out)

    for attempt in (1, 2):
        settle = 20
        if attempt == 1 and primed:
            filters, after = primed["filters"], primed["after"]
            settle = max(0, 20 - (time.time() - primed["fired"]))
        else:
            filters, after = _fire(out, cond_key, trigger, event_keys)
        try:
            found = collector.wait_for_alert(cond_key, filters, after, timeout=timeout, settle=settle)
            break
        except HxsimStalled as e:
            (out / "hxsim_stall_attempt{}.log".format(attempt)).write_text(str(e), encoding="utf-8")
            if attempt == 2:
                raise
            logger.warning("hxsim stalled, setting the IOC environment up again and retrying: %s",
                           str(e).splitlines()[0])
            prepare_ioc_environment()
            collector.forget_alerts()
        finally:
            _write_json(out / "ioc_alerts_for_condition.json",
                        [_alert_record(m, event_type) for m in collector.alerts_for(cond_key)])
            collector.ack()
    assert found, "No {} IOC alert passed the Razor filter within {}s, see {}".format(event_type, timeout, out)
    _write_json(out / "ioc_alert.json", _alert_record(found, event_type))
    shutil.copyfile(found["upload"] + ".decoded", str(out / "iocmatch_upload.xml"))
    logger.info("IOC alert verified: %s marker=%s reported=%s", event_type, found["marker"], found["reported"])
    return found


def _alert_record(match, event_type):
    rec = {k: match.get(k) for k in ("marker", "source", "reported")}
    rec.update({"event": event_record(match, event_type), "key": match["body"].get("key", {}),
                "values": match["body"].get("values", {})})
    return rec


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(obj, file, indent=2, default=str)
