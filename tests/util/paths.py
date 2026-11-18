"""Centralized filesystem paths for the test suite.

Every machine- and environment-specific path used across this repo is declared
in ``paths.json`` at the repo root. To point the tests at a different checkout,
install location, user profile, etc. edit ``paths.json`` only - all modules read
their paths from here, so nothing else needs to change.

Any value can be overridden with an environment variable ``RAZOR_<KEY>`` (e.g.
``RAZOR_INSTALL_DIR``). Each value may use environment variables (``%USERPROFILE%``, ``%ProgramFiles%``)
and ``~``; a value that is still relative after that is relative to the repo
root (the folder holding ``paths.json``), so the checkout can be moved without
editing ``paths.json``.

Values are exposed as absolute ``pathlib.Path`` objects. When a caller needs a
plain string (e.g. for string concatenation or ``subprocess`` on older code
paths), wrap it with ``str(...)``.
"""
import json
import os
from pathlib import Path

# tests/util/paths.py -> parents[0]=util, parents[1]=tests, parents[2]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATHS_FILE = _REPO_ROOT / "paths.json"

with open(_PATHS_FILE, "r") as _f:
    _PATHS = json.load(_f)


def _path(key):
    # An environment variable RAZOR_<KEY> (e.g. RAZOR_INSTALL_DIR) overrides the
    # paths.json value.
    value = os.environ.get("RAZOR_" + key.upper()) or _PATHS[key]
    path = Path(os.path.expanduser(os.path.expandvars(value)))
    return path if path.is_absolute() else (_REPO_ROOT / path).resolve()


# Repo / workspace locations
WORKSPACE_ROOT = _path("workspace_root")
INSTALL_DIR = _path("install_dir")
AUDIT_OUTPUT_DIR = _path("audit_output_dir")
AUDIT_SCRIPT_TXT = _path("audit_script_txt")
AUDIT_SCRIPTS_DIR = _path("audit_scripts_dir")

# User-profile data directories exercised by the tests. The audit scripts in
# AUDIT_SCRIPTS_DIR refer to RAZOR_PUBLIC as ``{RAZOR_PUBLIC}`` (filled in by
# Singleton_XClient.run_job).
RAZOR_PUBLIC = _path("razor_public")
TMP_FOLDER = _path("tmp_folder")

# Installed product executables
XCLIENT_EXE = _path("xclient_exe")
MCAFEE_AGENT_EXE = _path("mcafee_agent_exe")

# Node >= 18, used to run hxsim (IOC alert tests) and the port listeners of the
# ports audit tests (tests/test_audits/test_ports.py). A portable copy, kept off
# PATH, so the system-wide node install (0.12) is left untouched.
NODE_EXE = _path("node_exe")

# Git Bash, used to run hxsim's certs/gen-certs.sh (a bash script) that mints
# hxsim's dev PKI before every hxsim start (IOC alert tests).
BASH_EXE = _path("bash_exe")

# Folders the tests write into that a fresh clone (or a new host) doesn't have:
# temp/ is git-ignored, the other two live outside the repo. INSTALL_DIR is not
# here -- it must be staged with the vendor binaries (see DEPENDENCIES.md).
REQUIRED_DIRS = (AUDIT_OUTPUT_DIR, RAZOR_PUBLIC, TMP_FOLDER)


def create_required_dirs():
    """Create every folder in REQUIRED_DIRS that doesn't exist yet."""
    for folder in REQUIRED_DIRS:
        folder.mkdir(parents=True, exist_ok=True)
