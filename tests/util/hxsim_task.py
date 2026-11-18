"""Run audit scripts in the XClient SERVICE daemon as HXSim server tasks.

This replaces the stand-alone ``xclient.exe -f <script> -o <dir>`` run: the
script is dropped into ``<hxsim>\\rundir\\tasks``, HXSim advertises it in the
next poll, the daemon runs it and uploads every result part plus the final
manifest. ``collect`` writes them into the test's output folder with the names
``xclient -f -o`` uses (``manifest.json`` and one file per manifest
``payload``), so the code reading audit output is the same for both.

HXSim advertises every dropped task in each poll, so several tasks dropped
together run as one batch (``drop`` many, then ``collect`` each). Results are
matched by task id (``taskId`` in hxsim's lib/taskqueue.js: the first 22
characters of ``"HXSIM" + sha1(name + script bytes)``), never by audit name,
so two tasks of the same audit in one batch can't be mixed up.
"""
import datetime
import hashlib
import itertools
import json
import logging
import os
import re
import time
from pathlib import Path

from tests.util.hxsim_ioc import RUNDIR, SERVER_LOG, UPLOADS_DIR, _wait_stable
from tests.util.util import func_wait

logger = logging.getLogger("tests")

TASKS_DIR = RUNDIR / "tasks"
# Longest wait for a task whose test gives no timeout: a stuck task fails the test
# instead of hanging the run. The slowest audit seen (eventlogs, no parameters) takes
# about 12 minutes.
DEFAULT_WAIT = 30 * 60


def task_id(name, script_bytes):
    """hxsim's lib/taskqueue.js taskId(name, scriptBuf)."""
    digest = hashlib.sha1(name.encode("utf-8") + script_bytes).hexdigest()
    return ("HXSIM" + digest)[:22]


def _upload_name(path):
    """hxsim's lib/upload.js uploadName(): the flattened file name of an upload."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", path.lstrip("/"))


# mx FileUtil::SanitizeFilename: these become '_' in a file name.
_NOT_ALLOWED_IN_FILENAME = re.compile(r'[<>:"/\\|?*]')


def _file_names(command, results, taken, audit_id=""):
    """The file names ``xclient -f`` gives an audit's results (mxa JobIOFile /
    JobStreamer::MakeName): ``<command>`` for the data stream, ``<command>_issues``
    for issues, ``<command>-<stream id>`` for the others, then ``.<audit id>`` if
    the audit has an id (the diagnostic's sub-audits, e.g. InstallLog_TEMP), then
    .json / .xml / .dat by content type. The daemon's manifest has no stream ids, so
    the first JSON or XML result is taken as the data stream and the others are
    numbered from 100, the first extra stream id. ``taken`` holds the names already
    given in this task: where ``-f`` would give two audits the same name (the
    diagnostic's two id-less log-audit audits) and overwrite the first, the second
    gets the next free number instead."""
    suffix = "." + _NOT_ALLOWED_IN_FILENAME.sub("_", audit_id) if audit_id else ""
    names, data_taken = [], False
    for result in results:
        content_type = result.get("type", "")
        ext = suffix + (".json" if "json" in content_type else ".xml" if "xml" in content_type else ".dat")
        name = None
        if "issue" in content_type:
            name = command + "_issues" + ext
        elif not ext.endswith(".dat") and not data_taken:
            name, data_taken = command + ext, True
        if name is None or name in taken:
            extra = 100
            while "{}-{}{}".format(command, extra, ext) in taken:
                extra += 1
            name = "{}-{}{}".format(command, extra, ext)
        taken.add(name)
        names.append(name)
    return names


_NONCE_COUNTER = itertools.count()


class Task:
    """One dropped audit script."""

    def __init__(self, name, script_text):
        self.name = name
        script = json.loads(script_text)
        # The daemon skips a task id it already ran; a fresh nonce in every
        # command id gives each run its own id.
        # The counter keeps tasks created within one clock tick apart (the Windows clock can
        # return the same microseconds for several tasks created in a loop).
        nonce = "{}{:04d}".format(datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f"),
                                  next(_NONCE_COUNTER) % 10000)
        for command in script["commands"]:
            command["id"] = "razor-{}-{}".format(command["name"], nonce)
        self.script_bytes = json.dumps(script).encode("utf-8")
        # The file stem is hxsim's task name; the nonce keeps two tasks of the
        # same script in one batch apart.
        stem = "{}_{}".format(name, nonce)
        self.id = task_id(stem, self.script_bytes)
        self.file = TASKS_DIR / "{}.json".format(stem)
        self.dropped = None

    def drop(self):
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        self.file.write_bytes(self.script_bytes)
        self.dropped = time.time()
        logger.info("Task %s (%s) dropped for the daemon: %s", self.name, self.id, self.file)
        return self

    def _decoded(self, part):
        f = UPLOADS_DIR / (_upload_name("/task/{}/{}".format(self.id, part)) + ".decoded")
        return f if f.is_file() and _wait_stable(str(f)) else None

    def manifest(self):
        """The final manifest (parsed), once the daemon has uploaded it."""
        f = self._decoded("manifest")
        if not f:
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def wait(self, timeout=None):
        """True once the daemon has uploaded the final manifest, within ``timeout``
        seconds (DEFAULT_WAIT if None)."""
        return bool(func_wait(self.manifest, interval=5, timeout=timeout or DEFAULT_WAIT))

    def cancel(self):
        """Stop advertising the task (it is not run if the daemon hasn't fetched it yet)."""
        self.file.unlink(missing_ok=True)

    def collect(self, output_dir):
        """Write the final manifest and every result part into ``output_dir``.

        Call after ``wait``. The task file is removed: the task has run.
        """
        self.cancel()
        manifest = self.manifest()
        assert manifest, "No manifest for task {} ({}), see {}".format(self.name, self.id, SERVER_LOG)
        os.makedirs(output_dir, exist_ok=True)
        # The upload is an sf_manifest: the audit manifest ``xclient -f`` writes is
        # its app_data, and each payload is uploaded as parts named by part id.
        payloads = {p["id"]: p for p in manifest.get("payloads", [])}
        audit_manifest = manifest.get("app_data", {})
        commands = {c["id"]: c["name"] for c in json.loads(self.script_bytes)["commands"]}
        taken = set()
        for audit in audit_manifest.get("audits", []):
            if audit.get("id") in commands:
                # The script's own command (run_job's scripts have no id; Task added one).
                command, audit_id = commands[audit["id"]], ""
                audit["id"] = ""
            else:
                command, audit_id = audit.get("generator"), audit.get("id") or ""
            names = _file_names(command, audit.get("results", []), taken, audit_id)
            for result, file_name in zip(audit.get("results", []), names):
                payload = payloads.get(result.get("payload"))
                if not payload:
                    continue
                content = b""
                for part in sorted(payload.get("parts", []), key=lambda p: p.get("offset", 0)):
                    f = self._decoded("data/" + part["uri"].rsplit("/", 1)[-1])
                    assert f, "Task {} ({}): no upload for {}".format(self.name, self.id, part["uri"])
                    content += f.read_bytes()
                Path(output_dir, file_name).write_bytes(content)
                result["payload"] = file_name
        Path(output_dir, "manifest.json").write_text(json.dumps(audit_manifest, indent=2), encoding="utf-8")
        logger.info("Task %s (%s) finished in %ds, results in %s",
                    self.name, self.id, time.time() - self.dropped, output_dir)
        return manifest


