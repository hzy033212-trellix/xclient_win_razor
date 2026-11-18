"""Stage host files the tests need into <install_dir> (called from conftest.py at session start)."""
import hashlib
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from tests.util import artifactory, paths

logger = logging.getLogger("tests")

# The IOC process test copies it to C:\Temp\ (the `process` IOC condition).
WHOAMI_EXE = paths.INSTALL_DIR / "whoami.exe"

# OpenSSL for hxsim's Node code (HXSIM_OPENSSL: CMS sign/verify/encrypt/decrypt and
# SCEP issuing). It is also put on PATH for certs/gen-certs.sh, but Git Bash finds
# its own /mingw64/bin/openssl first, so the certs are minted by Git's openssl.
# See OPENSSL.md.
OPENSSL_DIR = paths.INSTALL_DIR / "openssl"
OPENSSL_FILES = ("openssl.exe", "libcrypto-3-x64.dll", "libssl-3-x64.dll")
# Trellix's own Windows x64 build of OpenSSL 3.5.8 (MSVC, VC-WIN64A; not
# Authenticode-signed), kept in Trellix Artifactory by the Active Response team.
# Needs ARTIFACTORY_USER / ARTIFACTORY_TOKEN (see tests/util/artifactory.py).
OPENSSL_ZIP = "perinola-local/active-response-client-deps/openssl/3.5.8/openssl-3.5.8-win.zip"
OPENSSL_ZIP_MEMBER_DIR = "openssl/x64/lib/"
# Pinned on top of Artifactory's own checksum: the zip lives in another team's
# repository, so a replaced file is reported instead of silently used.
OPENSSL_ZIP_SHA256 = "470dc85f9bbe1a860d5dd5e51e258f6be3f814a642aeef132a7b1a16ead1d20c"
# Names the zip <install_dir>\openssl was unpacked from; any other value (or none,
# e.g. an older FireDaemon copy) makes ensure_openssl replace the three files.
OPENSSL_STAMP_NAME = "source.txt"


def ensure_whoami():
    """Copy (never move: it is a protected system file) Windows' whoami.exe into
    <install_dir> unless a copy is already staged there."""
    if WHOAMI_EXE.is_file():
        return
    source = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"
    if not source.is_file():
        logger.warning("%s not found; the IOC process test needs %s", source, WHOAMI_EXE)
        return
    WHOAMI_EXE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(WHOAMI_EXE))
    logger.info("Copied %s -> %s", source, WHOAMI_EXE)


def ensure_openssl(openssl_dir=OPENSSL_DIR):
    """Unless <install_dir>\\openssl holds all of OPENSSL_FILES and its stamp names
    OPENSSL_ZIP, download OPENSSL_ZIP from Trellix Artifactory, check its SHA-256
    and unpack all three files from OPENSSL_ZIP_MEMBER_DIR (all three, so the exe
    and DLLs always come from the same build)."""
    openssl_dir = Path(openssl_dir)
    stamp = openssl_dir / OPENSSL_STAMP_NAME
    missing = [name for name in OPENSSL_FILES if not (openssl_dir / name).is_file()]
    current = stamp.read_text().strip() if stamp.is_file() else ""
    if not missing and current == OPENSSL_ZIP:
        return
    auth = artifactory._auth()
    if not auth:
        logger.warning("%s needs %s but ARTIFACTORY_USER / ARTIFACTORY_TOKEN are not set; %s",
                       openssl_dir, OPENSSL_ZIP,
                       "keeping the files already there" if not missing else "the IOC tests will fail")
        return
    reason = "{} missing".format(", ".join(missing)) if missing else "came from {}".format(current or "an unknown source")
    logger.info("%s: %s; downloading %s.....", openssl_dir, reason, OPENSSL_ZIP)
    with tempfile.TemporaryDirectory() as scratch:
        archive_path = artifactory._download(OPENSSL_ZIP, Path(scratch) / "openssl.zip", auth)
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        assert actual == OPENSSL_ZIP_SHA256, "{} SHA-256 mismatch: got {}, expected {}".format(
            OPENSSL_ZIP, actual, OPENSSL_ZIP_SHA256)
        openssl_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(archive_path)) as archive:
            for name in OPENSSL_FILES:
                (openssl_dir / name).write_bytes(archive.read(OPENSSL_ZIP_MEMBER_DIR + name))
    stamp.write_text(OPENSSL_ZIP + "\n")
    logger.info("OpenSSL 3.5.8 (%s) unpacked into %s", ", ".join(OPENSSL_FILES), openssl_dir)
