from enum import Enum

from tests.test_eventor_collection.event import Event
import os
import socket
from pathlib import Path

import winreg

class RegActionType(Enum):
    """
    Various event types with their value for reg events
    """

    create_key = 3
    create_key_value = 1
    delete_key = 4
    delete_key_value = 2


class RegKeyEvent(Event):
    """
    This Reg Event class serves to provide some common members and methods for all RegEvent
    triggers (which are subclasses of this class)
    """

    def __init__(
        self,
        reg_root=None,
        dest_path=None,
        target_key=None,
        target_value=None,
        value_type=None,
        value_data=None,
    ):
        super().__init__()

        self.reg_root = reg_root if reg_root else winreg.HKEY_LOCAL_MACHINE
        self.dest_path = (
            dest_path if dest_path else r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"
        )
        self.target_key = target_key if target_key else "Test_Key"
        self.target_value = target_value if target_value else "Test_Value"
        self.value_type = value_type if value_type else winreg.REG_SZ
        self.value_data = value_data if value_data else "1"

        self.reg_root_mapping = {
            winreg.HKEY_CLASSES_ROOT: "HKEY_CLASSES_ROOT",
            winreg.HKEY_CURRENT_USER: "HKEY_CURRENT_USER",
            winreg.HKEY_LOCAL_MACHINE: "HKEY_LOCAL_MACHINE",
            winreg.HKEY_USERS: "HKEY_USERS",
        }

        self.valueType_mapping = {
            winreg.REG_SZ: "REG_SZ",
            winreg.REG_BINARY: "REG_BINARY",
            winreg.REG_DWORD: "REG_DWORD",
            winreg.REG_LINK: "REG_LINK",
        }

        # Get the required info to assert against
        process_path_object = Path(self._process_path)
        self.split_dest_path = str(self.dest_path).split("\\", 1)
        self.result_info["valueType"] = self.valueType_mapping[self.value_type]
        self.result_info["valueName"] = str(self.target_value)
        self.result_info["hive"] = r"{}\{}".format(
            self.reg_root_mapping[self.reg_root], self.split_dest_path[0]
        )
        self.result_info["text"] = str(self.value_data)
        self.result_info["processPath"] = str(process_path_object.parent)
        self.result_info["username"] = r"{}\{}".format(socket.gethostname().upper(), os.getlogin())
        # can't be implemented until comparison is further refined
        # self.result_info["value"] = str(base64.b64encode(bytes(self.value_data, encoding="utf-8")))

    def get_assertable_keys(self, reg_event_type):
        keys = [
            # "timestamp", Need to check how to implement
            "process",
            "processPath",
            "keyPath",
            "hive",
            "path",
            "pid",
            "username",
        ]

        if reg_event_type == RegActionType.create_key_value.value:
            keys.extend(("valueName", "valueType", "text"))  # Need to add "value"

        if reg_event_type == RegActionType.delete_key_value.value:
            keys.append("valueName")

        return keys


class RegCreateKeyEvent(RegKeyEvent):
    def trigger_func(self):
        """
        Create a Registry Key
        :return:
        """
        try:
            open_key = winreg.OpenKeyEx(
                self.reg_root, r"{}\{}".format(self.dest_path, self.target_key)
            )
            if open_key:
                raise Exception("The key you are trying to create already exists")
        except Exception:
            key_path = r"{}\{}\{}".format(
                self.reg_root_mapping[self.reg_root], self.dest_path, self.target_key
            )
            winreg.CreateKeyEx(self.reg_root, r"{}\{}".format(self.dest_path, self.target_key))
            self.result_info["path"] = key_path
            self.result_info["keyPath"] = r"{}\{}".format(self.split_dest_path[1], self.target_key)
            self.result_info["eventType"] = RegActionType.create_key.value

class RegCreateValueEvent(RegKeyEvent):
    def trigger_func(self):
        """
        Create Registry key value
        :return:
        """
        try:
            open_key = winreg.OpenKeyEx(self.reg_root, self.dest_path, 0, winreg.KEY_ALL_ACCESS)
            if not open_key:
                raise Exception("The key itself doesn't exists")
            query_value = winreg.QueryValueEx(open_key, self.target_value)
            if query_value:
                raise Exception("The value you are trying to create already exists")
        except Exception:
            value_path = r"{}\{}\{}".format(
                self.reg_root_mapping[self.reg_root], self.dest_path, self.target_value
            )
            winreg.SetValueEx(open_key, self.target_value, 0, self.value_type, self.value_data)
            self.result_info["path"] = value_path
            self.result_info["keyPath"] = self.split_dest_path[1]
            self.result_info["eventType"] = RegActionType.create_key_value.value


class RegDeleteKeyEvent(RegKeyEvent):
    def trigger_func(self):
        """
        Delete a Registry Key
        :return:
        """
        key_path = r"{}\{}\{}".format(
            self.reg_root_mapping[self.reg_root], self.dest_path, self.target_key
        )
        try:
            winreg.DeleteKeyEx(self.reg_root, r"{}\{}".format(self.dest_path, self.target_key))
            self.result_info["path"] = key_path
            self.result_info["keyPath"] = r"{}\{}".format(self.split_dest_path[1], self.target_key)
            self.result_info["eventType"] = RegActionType.delete_key.value
        except Exception:
            raise Exception("Encountered error while deleting the registry key")


class RegDeleteValueEvent(RegKeyEvent):
    def trigger_func(self):
        """
        Delete a Registry key value.
        :return:
        """
        value_path = r"{}\{}\{}".format(
            self.reg_root_mapping[self.reg_root], self.dest_path, self.target_value
        )
        try:
            open_key = winreg.OpenKey(self.reg_root, self.dest_path, 0, winreg.KEY_ALL_ACCESS)
            if open_key:
                winreg.DeleteValue(open_key, self.target_value)
                self.result_info["path"] = value_path
                self.result_info["keyPath"] = self.split_dest_path[1]
                self.result_info["eventType"] = RegActionType.delete_key_value.value
        except Exception:
            raise Exception(
                "Encountered error while opening the key containing the value to be deleted"
            )
