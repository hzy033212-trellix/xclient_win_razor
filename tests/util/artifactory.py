"""Artifactory lookups for the XClient build under test, and the tools the tests need.

XCLIENT_VERSION (the installer version, e.g. 50.4.0.174; run_tests.ps1 sets it
from the msi it installs) is looked up by xclient_build():

  msi            XClientInstaller-local/WIN_<a.b.c>/b<build>.<n>/xclient_<version>_x64.msi
  XCBins build   the XClient binaries build the installer packaged, named in the
                 installer build's console log next to the msi
  branch/commit  the XClient checkout in the XCBins build's console log; hxsim
                 (hxsim_ioc.refresh_hxsim_source) is fetched at this commit

The lookup is cached in XCLIENT_BUILD_CACHE, so Artifactory is asked again only
when XCLIENT_VERSION changes. ensure_tools() downloads mmsutil.exe (XClient
service stop / start / query) into <install_dir> if it is missing.

For runs with MA (run_tests.ps1 -WithMA: the Orbit msi, which only takes policy
from MA) ensure_ma_tools() also stages, as win_razor did:

  FramePkg_UPD.exe       from the MA 5.8.5 build 495 package zip
  AacUtil.exe            from EDRF-tools-local/ (MA self-protection off)
  local_policy_config\   the local_policy_config folder of the XClientBinaries
                         zip in the XCBins build of XCLIENT_VERSION (stamped with
                         the version it came from)

Credentials come only from the environment, never from the repo:

  ARTIFACTORY_USER    Artifactory user name (e.g. first.last@trellix.com)
  ARTIFACTORY_TOKEN   an Artifactory identity token (Profile > Generate Identity Token)

They are never logged. Each download is checked against Artifactory's
X-Checksum-Sha256 header.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import requests

from tests.util import paths

logger = logging.getLogger("tests")

# The XClient installer build under test. The environment variable of the same
# name overrides it for a one-off run.
XCLIENT_VERSION = os.environ.get("XCLIENT_VERSION") or "50.4.0.174"
assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", XCLIENT_VERSION), \
    "XCLIENT_VERSION must look like 50.3.0.1501, not {!r}".format(XCLIENT_VERSION)

ARTIFACTORY = "https://artifactory.trellix.com/artifactory/"
XCLIENT_INSTALLER_REPO = "XClientInstaller-local"
# Tools downloaded as is: Artifactory path -> local file name (Artifactory names are case-sensitive).
TOOLS = {"EDRF-tools-local/mmsutil.exe": paths.INSTALL_DIR / "mmsutil.exe"}

MSI_NAME = "xclient_{}_x64.msi".format(XCLIENT_VERSION)

MA_ZIP = "MA-local/MA_5.8.5/b495.9/MA-WIN 5.8.5 Build 495 Package #9 (ENU-LICENSED-RELEASE-MAIN).zip"
FRAMEPKG = paths.INSTALL_DIR / "FramePkg_UPD.exe"
AACUTIL = paths.INSTALL_DIR / "AacUtil.exe"
LOCAL_POLICY_CONFIG_DIR = paths.INSTALL_DIR / "local_policy_config"
LOCAL_POLICY_CONFIG_EXE = LOCAL_POLICY_CONFIG_DIR / "local_policy_config.exe"
# The XCLIENT_VERSION local_policy_config\ was extracted for.
LOCAL_POLICY_CONFIG_STAMP = LOCAL_POLICY_CONFIG_DIR / "xclient_version.txt"
# xclient_build()'s result for the XCLIENT_VERSION it names.
XCLIENT_BUILD_CACHE = paths.INSTALL_DIR / "xclient_build.json"
# Installer build log: "[orbitbuild.downloadFromArtifactory()] [component:XCBins, ...,
# root:XClient-local/WIN_X64_50.3.0/b18059.1/, ...]", the XClient binaries build it packaged.
XCBINS_ROOT = re.compile(r"\[component:XCBins,[^\]]*?\broot:([^,\]\s]+)")
CHECKOUT = re.compile(r"Checking out Revision ([0-9a-f]{40}) \(([^)]+)\)")


# Seconds to wait before each retry of a 401 / 5xx answer (see _get).
RETRY_DELAYS = (2, 5)


def _url(artifact_path):
    # Quote spaces, '#', '(' ... so e.g. '#9' is sent, not taken as a URL fragment.
    return ARTIFACTORY + quote(artifact_path, safe="/")


def _auth():
    user, token = os.environ.get("ARTIFACTORY_USER"), os.environ.get("ARTIFACTORY_TOKEN")
    return (user, token) if user and token else None


def _get(url, auth, **kwargs):
    # Artifactory now and then answers a valid token with a one-off 401 (or a 5xx);
    # retry those so only a persistent refusal is reported as a credentials problem.
    for delay in RETRY_DELAYS:
        response = requests.get(url, auth=auth, timeout=(30, 600), **kwargs)
        if response.status_code != 401 and response.status_code < 500:
            break
        response.close()
        logger.warning("Artifactory answered %s with HTTP %s; retrying in %ss", url, response.status_code, delay)
        time.sleep(delay)
    else:
        response = requests.get(url, auth=auth, timeout=(30, 600), **kwargs)
    if response.status_code in (401, 403):
        response.close()
        raise AssertionError("Artifactory refused {} (HTTP {}): check ARTIFACTORY_USER / ARTIFACTORY_TOKEN "
                             "and the account's read access".format(url, response.status_code))
    response.raise_for_status()
    return response


def _download(artifact_path, dest, auth):
    """Stream an artifact to ``dest`` and check it against X-Checksum-Sha256."""
    url = _url(artifact_path)
    logger.info("Downloading %s.....", url)
    sha256 = hashlib.sha256()
    with _get(url, auth, stream=True) as response:
        expected = response.headers.get("X-Checksum-Sha256")
        with open(dest, "wb") as file:
            for chunk in response.iter_content(chunk_size=1 << 20):
                file.write(chunk)
                sha256.update(chunk)
    if expected:
        assert sha256.hexdigest() == expected.lower(), "{} SHA-256 mismatch: got {}, expected {}".format(
            url, sha256.hexdigest(), expected)
    else:
        logger.warning("Artifactory sent no X-Checksum-Sha256 for %s; download not checksum-verified", url)
    return Path(dest)


def ensure_tools():
    """Download whichever of TOOLS is missing."""
    missing = {artifact: dest for artifact, dest in TOOLS.items() if not dest.is_file()}
    if not missing:
        return
    auth = _auth()
    assert auth, "Set ARTIFACTORY_USER and ARTIFACTORY_TOKEN to download {}".format(list(missing.values()))
    paths.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        for artifact, dest in missing.items():
            _download(artifact, Path(scratch) / dest.name, auth)
            shutil.move(str(Path(scratch) / dest.name), str(dest))
            logger.info("Staged %s", dest)


def _extract_file(archive, basename, dest):
    """Extract the one member named ``basename`` (any folder, case-insensitive) to ``dest``."""
    matches = [n for n in archive.namelist() if PurePosixPath(n).name.lower() == basename.lower()]
    assert len(matches) == 1, "Expected one {} in the zip, found {}".format(basename, matches or "none")
    with archive.open(matches[0]) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
    return matches[0]


def _extract_folder(archive, folder, dest):
    """Extract the content of the (single) folder named ``folder``, at any depth, into ``dest``."""
    roots = sorted({"/".join(parts[:i + 1]) for parts in (PurePosixPath(n).parts for n in archive.namelist())
                    for i, part in enumerate(parts[:-1]) if part.lower() == folder.lower()})
    assert len(roots) == 1, "Expected one {}/ folder in the zip, found {}".format(folder, roots or "none")
    root = roots[0] + "/"
    dest.mkdir(parents=True, exist_ok=True)
    for name in archive.namelist():
        if name.startswith(root) and not name.endswith("/"):
            target = dest.joinpath(*PurePosixPath(name[len(root):]).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return root


def _local_policy_config_current():
    try:
        return LOCAL_POLICY_CONFIG_EXE.is_file() and LOCAL_POLICY_CONFIG_STAMP.read_text().strip() == XCLIENT_VERSION
    except OSError:
        return False


def ensure_ma_tools():
    """Download whichever of FRAMEPKG, AACUTIL and LOCAL_POLICY_CONFIG_DIR (for XCLIENT_VERSION) is missing."""
    if FRAMEPKG.is_file() and AACUTIL.is_file() and _local_policy_config_current():
        return
    auth = _auth()
    assert auth, "Set ARTIFACTORY_USER and ARTIFACTORY_TOKEN to download the MA tools"
    paths.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        if not AACUTIL.is_file():
            _download("EDRF-tools-local/AacUtil.exe", Path(scratch) / AACUTIL.name, auth)
            shutil.move(str(Path(scratch) / AACUTIL.name), str(AACUTIL))
            logger.info("Staged %s", AACUTIL)
        if not FRAMEPKG.is_file():
            with zipfile.ZipFile(_download(MA_ZIP, Path(scratch) / "ma.zip", auth)) as archive:
                member = _extract_file(archive, FRAMEPKG.name, FRAMEPKG)
            logger.info("Staged %s (from %s)", FRAMEPKG, member)
        if not _local_policy_config_current():
            xcbins = xclient_build()["xcbins"]
            zips = [n for n in _children(xcbins, auth) if re.fullmatch(r"XClientBinaries_.*\.zip", n)]
            assert len(zips) == 1, "Expected one XClientBinaries_*.zip in {}, found {}".format(xcbins, zips or "none")
            if LOCAL_POLICY_CONFIG_DIR.exists():
                shutil.rmtree(str(LOCAL_POLICY_CONFIG_DIR))  # another XClient build's
            binaries_zip = xcbins + "/" + zips[0]
            with zipfile.ZipFile(_download(binaries_zip, Path(scratch) / "xclient_binaries.zip", auth)) as archive:
                root = _extract_folder(archive, LOCAL_POLICY_CONFIG_DIR.name, LOCAL_POLICY_CONFIG_DIR)
            assert LOCAL_POLICY_CONFIG_EXE.is_file(), "No local_policy_config.exe in {} of the zip".format(root)
            LOCAL_POLICY_CONFIG_STAMP.write_text(XCLIENT_VERSION)
            logger.info("Staged %s (from %s of %s)", LOCAL_POLICY_CONFIG_DIR, root, binaries_zip)


def _children(folder, auth):
    """Names of the files and folders in an Artifactory folder."""
    children = _get(ARTIFACTORY + "api/storage/" + quote(folder, safe="/"), auth).json().get("children", [])
    return [c["uri"].lstrip("/") for c in children]


def _msi_artifact(auth):
    """Artifactory path of MSI_NAME: in XClientInstaller-local/WIN_<a.b.c>/b<build>.<n>/, highest <n> first."""
    release, build = XCLIENT_VERSION.rsplit(".", 1)
    base = "{}/WIN_{}".format(XCLIENT_INSTALLER_REPO, release)
    folders = [name for name in _children(base, auth) if re.fullmatch(r"b{}\.\d+".format(build), name)]
    for folder in sorted(folders, key=lambda name: int(name.rsplit(".", 1)[1]), reverse=True):
        if MSI_NAME in _children(base + "/" + folder, auth):
            return "{}/{}/{}".format(base, folder, MSI_NAME)
    raise AssertionError("No {} in {}{}/b{}.*".format(MSI_NAME, ARTIFACTORY, base, build))


def _console_log(folder, names, auth):
    """Text of the Jenkins console log (*-ConsoleText-*.log) among ``names``, the content of an Orbit build folder."""
    logs = [name for name in names if re.fullmatch(r".*-ConsoleText-\d+\.log", name)]
    assert len(logs) == 1, "Expected one *-ConsoleText-*.log in {}, found {}".format(folder, logs or "none")
    with tempfile.TemporaryDirectory() as scratch:
        return _download(folder + "/" + logs[0], Path(scratch) / logs[0], auth).read_text(
            encoding="utf-8", errors="replace")


def _xclient_checkout(log):
    """(branch, commit) of the first unified-agent/XClient checkout in a Jenkins console log.

    The Git plugin logs "git fetch ... <repo url> ..." and then "Checking out
    Revision <sha> (<branch>)"; other repos (e.g. UEDRBuildLib) are checked out too.
    """
    fetching_xclient = False
    for line in log.splitlines():
        if "git fetch" in line:
            fetching_xclient = "unified-agent/XClient.git" in line
        match = fetching_xclient and CHECKOUT.search(line)
        if match:
            return re.sub(r"^origin/", "", match.group(2)), match.group(1)
    raise AssertionError("No unified-agent/XClient checkout in the console log")


def xclient_build():
    """The Artifactory builds and XClient source behind XCLIENT_VERSION.

    {"version", "msi", "xcbins", "branch", "commit"}: the msi's path, the XCBins
    build folder it packaged (XCBINS_ROOT in the installer build's console log,
    next to the msi) and the XClient branch / commit in that build's console log. Cached in
    XCLIENT_BUILD_CACHE, so Artifactory is only asked again when XCLIENT_VERSION changes.
    """
    try:
        cached = json.loads(XCLIENT_BUILD_CACHE.read_text(encoding="utf-8"))
        if cached["version"] == XCLIENT_VERSION:
            return cached
    except (OSError, ValueError, KeyError):
        pass
    auth = _auth()
    assert auth, "Set ARTIFACTORY_USER and ARTIFACTORY_TOKEN: the builds behind XClient {} are looked up " \
                 "on {}".format(XCLIENT_VERSION, ARTIFACTORY)
    msi = _msi_artifact(auth)
    msi_folder = str(PurePosixPath(msi).parent)
    match = XCBINS_ROOT.search(_console_log(msi_folder, _children(msi_folder, auth), auth))
    assert match, "The installer build log in {} names no XCBins build".format(msi_folder)
    xcbins = match.group(1).rstrip("/")
    branch, commit = _xclient_checkout(_console_log(xcbins, _children(xcbins, auth), auth))
    build = {"version": XCLIENT_VERSION, "msi": msi, "xcbins": xcbins, "branch": branch, "commit": commit}
    XCLIENT_BUILD_CACHE.parent.mkdir(parents=True, exist_ok=True)
    XCLIENT_BUILD_CACHE.write_text(json.dumps(build, indent=2), encoding="utf-8")
    logger.info("XClient %s: %s, binaries %s, built from XClient %s @ %s",
                XCLIENT_VERSION, msi, xcbins, branch, commit)
    return build


def xclient_source():
    """(branch, commit) of the XClient source XCLIENT_VERSION's binaries were built from."""
    build = xclient_build()
    return build["branch"], build["commit"]
