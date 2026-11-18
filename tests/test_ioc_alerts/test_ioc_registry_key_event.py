import winreg

import pytest

from tests.test_eventor_collection.registry_key_events import (
    RegCreateKeyEvent,
    RegCreateValueEvent,
    RegDeleteKeyEvent,
    RegDeleteValueEvent,
)
from tests.test_eventor_collection.test_eventor_registry_key_event import registry_event_platform_keys
from tests.util.hxsim_ioc import IOC_NAME_PREFIX
from tests.util.ioc_batch import IocCase, run_ioc_case
from tests.util.util import random_string

pytestmark = pytest.mark.ioc

# RegKeyEvent's default location (HKLM RunOnce is in the agent's registry key filter).
RUN_ONCE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"


def _ioc_reg_name():
    """A fresh name matching the `regevents` IOC condition."""
    return "{}{}".format(IOC_NAME_PREFIX.upper(), random_string())


def _key_to_delete():
    name = _ioc_reg_name()
    winreg.CloseKey(winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, RUN_ONCE + "\\" + name))
    return name


def _value_to_delete():
    name = _ioc_reg_name()
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RUN_ONCE, 0, winreg.KEY_ALL_ACCESS) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, "1")
    return name


def _remove(name):
    """Remove the name again after the test."""
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RUN_ONCE, 0, winreg.KEY_ALL_ACCESS) as key:
        for remove in (lambda: winreg.DeleteKey(key, name), lambda: winreg.DeleteValue(key, name)):
            try:
                remove()
            except FileNotFoundError:
                pass


IOC_CASES = {
    "test_ioc_reg_create_key": IocCase(
        "regevents", lambda name: RegCreateKeyEvent(target_key=name), registry_event_platform_keys(),
        setup=_ioc_reg_name, cleanup=_remove),
    "test_ioc_reg_delete_key": IocCase(
        "regevents", lambda name: RegDeleteKeyEvent(target_key=name), registry_event_platform_keys(),
        setup=_key_to_delete, cleanup=_remove),
    "test_ioc_reg_create_value": IocCase(
        "regevents", lambda name: RegCreateValueEvent(target_value=name), registry_event_platform_keys(),
        setup=_ioc_reg_name, cleanup=_remove),
    "test_ioc_reg_delete_value": IocCase(
        "regevents", lambda name: RegDeleteValueEvent(target_value=name), registry_event_platform_keys(),
        setup=_value_to_delete, cleanup=_remove),
}


def test_ioc_reg_create_key(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)


def test_ioc_reg_delete_key(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)


def test_ioc_reg_create_value(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)


def test_ioc_reg_delete_value(hxsim_ioc_setup, request):
    run_ioc_case(hxsim_ioc_setup, request)
