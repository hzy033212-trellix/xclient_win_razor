import psutil
import pytest

from tests.test_eventor_collection.image_load_events import ImageLoadExecutableStartEvent
from tests.test_eventor_collection.test_eventor_image_load import IMAGE_LOAD_EVENT_KEYS, WIN_IMAGE_TRIGGERS
from tests.util.ioc_batch import IocCase, run_ioc_case

pytestmark = pytest.mark.ioc

COND_KEYS = {"ImageLoadServiceStartEvent": "imageload_service", "ImageLoadExecutableStartEvent": "imageload"}

# Razor's Windows image-load triggers, except that Notepad is expected to load
# uxtheme.dll (the IOC guide's example, reported by the agent for Notepad)
# rather than ntdll.dll, which this agent has not been seen to report.
IOC_IMAGE_TRIGGERS = [
    (event_class, dict(kwargs, library="uxtheme.dll") if event_class is ImageLoadExecutableStartEvent else kwargs)
    for event_class, kwargs in WIN_IMAGE_TRIGGERS
]


def _notepad_pids():
    return {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "notepad.exe"}


def _close_new_notepads(before):
    for pid in _notepad_pids() - before:  # the executable trigger leaves Notepad open
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass


IOC_CASES = {
    "test_ioc_image_load[{}]".format(c.__name__): IocCase(
        COND_KEYS[c.__name__], lambda _, c=c, kw=kw: c(**kw), IMAGE_LOAD_EVENT_KEYS,
        setup=_notepad_pids, cleanup=_close_new_notepads)
    for c, kw in IOC_IMAGE_TRIGGERS
}


@pytest.mark.parametrize("event_class, kwargs", IOC_IMAGE_TRIGGERS, ids=[c.__name__ for c, _ in IOC_IMAGE_TRIGGERS])
def test_ioc_image_load(hxsim_ioc_setup, request, event_class, kwargs):
    run_ioc_case(hxsim_ioc_setup, request)
