"""Build XClient against the fake MA SDK, at the commit an Orbit XClient installer build was built from.

    venv\\Scripts\\python tools\\fakema\\build_fake_xclient.py --version 50.4.0.174 --work C:\\nwr\\fakema

Run by Get-FakeMaMsi.ps1, with this repo's toolchain on PATH (tools\\toolchain.ps1 Use-Toolchain -Build).

  <work>\\XClient\\       https://github.trellix.com/unified-agent/XClient at the commit --version was built
                         from (tests/util/artifactory.py xclient_source: the Orbit and XCBins console logs)
  <work>\\ma-sdk-fake\\   $MA_SDK_FAKE_REPO ($MA_SDK_FAKE_BRANCH, default main)
  <work>\\build\\         the build (build\\Build-FakeMaXClient.ps1); <work>\\build\\install\\bin holds
                         xclient.exe, mxCore.dll and the fake-MA mxAgent.dll

Nothing is rebuilt when <work>\\last_build.json already records the same XClient commit, ma-sdk-fake
commit, build tooling and build tools (NWR_ROOT\\tools markers): a new XClient version built from
the same commit reuses the build.

Prints "XCLIENT_INSTALL=<path>" as its last line. Exit code: 0 ok, otherwise build.cmd's or 1.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # repo root, for tests.util

XCLIENT_REPO = "https://github.trellix.com/unified-agent/XClient.git"
# ma-sdk-fake repo URL comes from the environment (like the credentials), e.g. a CI secret.
MA_SDK_FAKE = (os.environ.get("MA_SDK_FAKE_REPO", ""), os.environ.get("MA_SDK_FAKE_BRANCH") or "main")
BUILD_DIR = HERE / "build"


def _ma_sdk_fake_repo():
    if not MA_SDK_FAKE[0]:
        sys.exit("MA_SDK_FAKE_REPO is not set (git URL of the ma-sdk-fake repo).")
    return MA_SDK_FAKE[0]
TOOLING = ["build.cmd", "Build-FakeMaXClient.ps1", "lib/Common.ps1", "lib/Prereqs.ps1", "lib/Stages.ps1"]
# The build tools setup.ps1 installs into NWR_ROOT\tools (folder names from tools\toolchain.ps1).
# Their .nwr_version markers (version and download source) are part of the build record, so a
# tool reinstalled at another version or from another source rebuilds XClient with it.
NWR_TOOLS = Path(os.environ.get("NWR_ROOT") or r"C:\nwr") / "tools"
BUILD_TOOLS = ["python39", "git", "cmake", "perl", "node012", "conan-venv"]

# XClient's CMakeLists.txt runs `cmd /c tools\set-repo-options.sh`, which asks Windows which program
# opens .sh files (an invisible prompt for a service account, so configure hangs). Run it with Git Bash.
SET_REPO_OPTIONS_CMD = "COMMAND cmd /c tools\\\\set-repo-options.sh"


def _git():
    from tests.util.git_utils import git
    return git


def _head(dest):
    try:
        return _git()("-C", str(dest), "rev-parse", "HEAD")
    except AssertionError:  # no commit checked out yet
        return None


def sync(url, ref, dest):
    """Make ``dest`` a clean shallow checkout of ``ref`` (a branch tip or a commit hash). Returns the commit.

    A commit hash that is already checked out is not fetched again; the checkout is only reset
    (e.g. the CMakeLists.txt patch of the last build undone)."""
    git = _git()
    if not (dest / ".git").is_dir():
        if dest.exists():
            shutil.rmtree(str(dest))
        git("init", "-q", str(dest))
        git("-C", str(dest), "remote", "add", "origin", url)
    if _head(dest) == ref:
        git("-C", str(dest), "reset", "-q", "--hard", "HEAD")
    else:
        git("-C", str(dest), "fetch", "-q", "--depth", "1", "origin", ref)
        git("-C", str(dest), "reset", "-q", "--hard", "FETCH_HEAD")
    git("-C", str(dest), "clean", "-q", "-ffdx")
    return git("-C", str(dest), "rev-parse", "HEAD")


def tooling_hash():
    # CRLF -> LF first: a checkout and a copy of the same content may differ only in line endings.
    sha = hashlib.sha256()
    for name in TOOLING:
        sha.update((BUILD_DIR / name).read_bytes().replace(b"\r\n", b"\n"))
    return sha.hexdigest()


def build_tools():
    """{tool folder: its .nwr_version marker} for BUILD_TOOLS ("" when missing)."""
    tools = {}
    for name in BUILD_TOOLS:
        marker = NWR_TOOLS / name / ".nwr_version"
        tools[name] = marker.read_text(encoding="utf-8", errors="replace").strip() if marker.is_file() else ""
    return tools


def run_set_repo_options_with_bash(xclient):
    from tests.util import paths
    cmake_lists = xclient / "CMakeLists.txt"
    text = cmake_lists.read_text(encoding="utf-8")
    if SET_REPO_OPTIONS_CMD not in text:
        print("{} no longer contains {!r}; not patched".format(cmake_lists, SET_REPO_OPTIONS_CMD), flush=True)
        return
    bash = str(paths.BASH_EXE).replace("\\", "/")
    cmake_lists.write_text(text.replace(SET_REPO_OPTIONS_CMD, 'COMMAND "{}" tools/set-repo-options.sh'.format(bash)),
                           encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True, help="Orbit installer version, e.g. 50.4.0.174")
    parser.add_argument("--work", required=True, type=Path, help="work folder, e.g. C:\\nwr\\fakema")
    parser.add_argument("--force", action="store_true", help="build even if nothing changed")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", args.version):
        parser.error("--version must look like 50.4.0.174")

    os.environ["XCLIENT_VERSION"] = args.version  # read by tests.util.artifactory at import time
    from tests.util.artifactory import xclient_source

    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    branch, commit = xclient_source()
    print("XClient {} was built from {} {} @ {}".format(args.version, XCLIENT_REPO, branch, commit), flush=True)
    state = {"XClient": sync(XCLIENT_REPO, commit, work / "XClient"),
             "ma-sdk-fake": sync(_ma_sdk_fake_repo(), MA_SDK_FAKE[1], work / "ma-sdk-fake"),
             "tooling": tooling_hash(),
             "tools": build_tools()}
    install = work / "build" / "install"

    record = work / "last_build.json"
    last = json.loads(record.read_text()) if record.is_file() else {}
    if not args.force and last == state and (install / "bin" / "mxAgent.dll").is_file():
        print("Fake-MA XClient for {} is already built in {}".format(state["XClient"][:12], install), flush=True)
    else:
        # The build is about to change <work>\build: drop the record first so a failed build can't look current.
        if record.is_file():
            record.unlink()
        run_set_repo_options_with_bash(work / "XClient")
        rc = subprocess.call(["cmd", "/c", str(BUILD_DIR / "build.cmd"),
                              "-XClientSource", str(work / "XClient"),
                              "-FakeSdkSource", str(work / "ma-sdk-fake"),
                              "-BuildDir", str(work / "build")])
        if rc != 0:
            print("build.cmd failed with exit code {}; logs in {}".format(rc, BUILD_DIR / "logs"), flush=True)
            return rc
        record.write_text(json.dumps(state, indent=2))

    if not (install / "bin" / "mxAgent.dll").is_file():
        print("No bin\\mxAgent.dll in {}".format(install), flush=True)
        return 1
    print("XCLIENT_INSTALL={}".format(install), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
