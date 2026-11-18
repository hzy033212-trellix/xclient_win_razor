import shutil
from pathlib import Path

import pytest

from tests.test_eventor_collection.process_events import PythonProcessEvent
from tests.util.hxsim_ioc import WHOAMI_EXE
from tests.util.ioc_batch import IocCase, run_ioc_case

pytestmark = pytest.mark.ioc

# Same keys test_eventor_process.py process_runner filters on.
PROCESS_EVENT_KEYS = ["process", "processCmdLine", "pid", "eventType", "parentPid", "parentProcess", "md5"]

# Must sit under C:\Temp\ -- the `process` IOC condition is processPath starts-with C:\Temp\.
WHOAMI_TARGET = Path(r"C:\Temp\whoami.exe")


def _whoami_in_temp():
    WHOAMI_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(WHOAMI_EXE), str(WHOAMI_TARGET))
    return str(WHOAMI_TARGET)


IOC_CASES = {
    "test_ioc_process_whoami": IocCase(
        "process", lambda path: PythonProcessEvent(path), PROCESS_EVENT_KEYS, setup=_whoami_in_temp),
    "test_ioc_process_ipconfig": IocCase(
        "process_ipconfig", lambda _: PythonProcessEvent("ipconfig", ["/flushdns"]), PROCESS_EVENT_KEYS),
}


def test_ioc_process_whoami(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)


def test_ioc_process_ipconfig(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)
