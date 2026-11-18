"""Make sure the portable Node (``node_exe`` in paths.json) exists.

If ``node_exe`` (default ``C:\\nwr\\tools\\node-v24\\node.exe``) is missing, download
NODE_ZIP (the official ``node-v24.<x>-win-x64.zip``, mirrored unchanged in Trellix
Artifactory's approved-tools-local repository), check it against Artifactory's
SHA-256, and unzip it so that ``node_exe`` exists. Needs ARTIFACTORY_USER /
ARTIFACTORY_TOKEN (see tests/util/artifactory.py). It is never added to PATH, so
the system node (0.12) is left untouched. Called from conftest.py at session
start; does nothing when node is already there.
"""
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from tests.util import artifactory, paths

logger = logging.getLogger("tests")

# Artifactory path (case-sensitive). Its SHA-256 equals nodejs.org's published
# SHASUMS256.txt entry for node-v24.19.0-win-x64.zip (checked 2026-11-06).
NODE_ZIP = "approved-tools-local/Node.js/v24.19.0/node-v24.19.0-win-x64.zip"


def ensure_node(node_exe=paths.NODE_EXE):
    if Path(node_exe).is_file():
        return
    auth = artifactory._auth()
    if not auth:
        logger.warning("%s not found and ARTIFACTORY_USER / ARTIFACTORY_TOKEN are not set, so %s is not "
                       "downloaded; the tests that need node will fail", node_exe, NODE_ZIP)
        return
    target = Path(node_exe).parent
    name = PurePosixPath(NODE_ZIP).name
    logger.info("%s not found; downloading %s into %s.....", node_exe, NODE_ZIP, target)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        archive_path = artifactory._download(NODE_ZIP, Path(scratch) / name, auth)
        with zipfile.ZipFile(str(archive_path)) as archive:
            archive.extractall(str(Path(scratch) / "x"))
        # The zip holds one top folder, node-v24.<x>-win-x64\; its content goes into target.
        for item in (Path(scratch) / "x" / name[:-len(".zip")]).iterdir():
            dest = target / item.name
            if dest.is_dir():
                shutil.rmtree(str(dest))
            elif dest.exists():
                dest.unlink()
            shutil.move(str(item), str(dest))
    assert Path(node_exe).is_file(), "{} still missing after unzipping {} into {}".format(node_exe, name, target)
    logger.info("Node %s installed at %s (not on PATH)", name, node_exe)
