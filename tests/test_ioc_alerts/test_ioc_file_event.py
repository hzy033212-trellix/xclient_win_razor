import shutil

import pytest

from tests.test_eventor_collection.file_events import (
    FileCopyEvent,
    FileCreateAsciiEvent,
    FileRenameEvent,
    FileWriteAppendEvent,
    FileWriteEvent,
)
from tests.test_eventor_collection.test_eventor_file_event import file_event_platform_keys
from tests.util.hxsim_ioc import IOC_NAME_PREFIX
from tests.util.ioc_batch import IocCase, run_ioc_case
from tests.util.paths import RAZOR_PUBLIC
from tests.util.util import random_string

pytestmark = pytest.mark.ioc

FILE_EVENT_CLASSES = [FileCreateAsciiEvent, FileRenameEvent, FileWriteEvent, FileWriteAppendEvent, FileCopyEvent]


def _ioc_target_file():
    """A fresh RAZOR_PUBLIC file whose name matches the `filewrite` IOC condition."""
    RAZOR_PUBLIC.mkdir(parents=True, exist_ok=True)
    return {"target": RAZOR_PUBLIC / "{}{}.txt".format(IOC_NAME_PREFIX, random_string())}


def _make_trigger(event_class):
    def make(state):
        state["trigger"] = event_class(target_file=state["target"])
        return state["trigger"]
    return make


def _cleanup(state):
    dest_dir = getattr(state.get("trigger"), "dest_dir", None)
    if dest_dir is not None:
        shutil.rmtree(str(dest_dir), ignore_errors=True)
    state["target"].unlink(missing_ok=True)


IOC_CASES = {
    "test_ioc_file_event[{}]".format(c.__name__): IocCase(
        "filewrite", _make_trigger(c), file_event_platform_keys(), setup=_ioc_target_file, cleanup=_cleanup)
    for c in FILE_EVENT_CLASSES
}


@pytest.mark.parametrize("event_class", FILE_EVENT_CLASSES, ids=lambda c: c.__name__)
def test_ioc_file_event(hxsim_ioc_setup, request, event_class):
    run_ioc_case(hxsim_ioc_setup, request)
